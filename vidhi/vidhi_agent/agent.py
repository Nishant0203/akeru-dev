"""
vidhi/vidhi_agent/agent.py
────────────────────
Vidhi — Architecture Guidelines Agent
Starlette ASGI app. Runs at api.akeru.dev/vidhi/*
Separate from Vanik; mount alongside it in deploy.

Routes
  POST /vidhi/api/chat          → SSE stream (text/event-stream)
  GET  /vidhi/health            → {"status": "ok", "agent": "vidhi"}

Design
  - Gemini API via google-generativeai SDK
  - Section-aware system prompts drawn from architecture document
 - Full architecture document embedded in every context (≈12.8K tokens,
    within typical Gemini context limits; local LLaMA uses excerpt selection)
  - Stateless: caller sends full history each request
  - Model: gemini-1.5-flash (fast) or gemini-1.5-pro (deeper) — caller selects

Run (dev):
  uvicorn vidhi.vidhi_agent.agent:app --port 8001 --reload

Run (prod, alongside Vanik on port 8000):
  uvicorn vidhi.vidhi_agent.agent:app --port 8001 --workers 1
  # Caddy reverse-proxies /vidhi/* → localhost:8001
"""

import asyncio
import hashlib
import json
import logging
import os
import time
from pathlib import Path

import google.generativeai as genai
import httpx
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

# ── Logging ─────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [vidhi] %(message)s")
log = logging.getLogger("vidhi")

# ── Gemini client ───────────────────────────────────────────────────
# We configure google-generativeai lazily to avoid "empty key" auth failures.
_GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
_GEMINI_CONFIGURED = False


def _configure_gemini_if_needed() -> None:
    global _GEMINI_CONFIGURED
    if _GEMINI_CONFIGURED:
        return
    if not _GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set on the server.")
    genai.configure(api_key=_GEMINI_API_KEY)
    _GEMINI_CONFIGURED = True

# Optional: lock Gemini behind a shareable code
_GEMINI_UNLOCK_CODE = os.environ.get("VIDHI_GEMINI_UNLOCK_CODE", "").strip()

# Optional: Ollama local model (default path)
_OLLAMA_BASE_URL = os.environ.get("VIDHI_OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
_DEFAULT_OLLAMA_MODEL = os.environ.get("VIDHI_OLLAMA_MODEL", "llama3.1:8b").strip()

# Use fully-qualified model IDs as returned by genai.list_models() (e.g. "models/gemini-2.0-flash").
# Model availability varies by project/key; keep this list aligned with what we enable in the UI.
ALLOWED_MODELS = {
    "models/gemini-2.0-flash",
    "models/gemini-2.5-flash",
    "models/gemini-2.5-pro",
    "models/gemini-flash-latest",
    "models/gemini-pro-latest",
}
MAX_HISTORY_TURNS = 12   # keep last N user+assistant pairs to stay within budget

# ── Basic endpoint rate limiting (prevents abuse, especially for Ollama) ──
_RATE_LIMIT_PER_MIN = int(os.environ.get("VIDHI_RATE_LIMIT_PER_MIN", "20"))
_rate_lock = asyncio.Lock()
_rate_state: dict[str, list[float]] = {}

# ── Query log (JSONL audit trail) ──
_QUERY_LOG_PATH = Path(os.environ.get("VIDHI_QUERY_LOG_PATH", "vidhi/vidhi_agent/vidhi_query_log.jsonl"))
_query_log_lock = asyncio.Lock()


def _is_gemini_model(model: str) -> bool:
    return model.startswith("models/")


def _is_ollama_model(model: str) -> bool:
    return model.startswith("ollama/")


def _build_prompt(system_prompt: str, history: list[dict]) -> str:
    """Build a single text prompt from (system + chat history)."""
    lines: list[str] = [system_prompt.strip(), "", "Conversation:", "────────────"]
    for turn in history:
        role = turn.get("role")
        content = (turn.get("content") or "").strip()
        if not content:
            continue
        if role == "user":
            lines.append(f"User: {content}")
        elif role == "assistant":
            lines.append(f"Vidhi: {content}")
    lines.append("────────────")
    lines.append("Vidhi:")
    return "\n".join(lines).strip() + "\n"


def _build_gemini_contents(system_prompt: str, history: list[dict]) -> list[dict]:
    """Build role-structured contents for Gemini.

    If Gemini rejects this shape, the caller can fall back to the flat prompt string.
    """
    contents: list[dict] = [{"role": "user", "parts": [system_prompt]}]
    for turn in history:
        role = turn.get("role")
        content = (turn.get("content") or "").strip()
        if not content:
            continue
        if role == "user":
            contents.append({"role": "user", "parts": [content]})
        elif role == "assistant":
            # Gemini "model" role corresponds to assistant outputs.
            contents.append({"role": "model", "parts": [content]})
    return contents

# ── Architecture document (embedded once at startup) ─────────────────
# The document is ≈12.8K tokens — well within the 128K context window.
# Path: loaded from file if present, else from VIDHI_ARCH_DOC env var,
# else from the embedded fallback stub below.
def _load_arch_doc() -> str:
    # 1. Try file path (recommended — keep vanik_architecture.txt in repo)
    doc_path = Path(
        os.environ.get("VIDHI_ARCH_DOC_PATH", "vidhi/vidhi_agent/vanik_architecture.txt")
    )
    if doc_path.exists():
        return doc_path.read_text(encoding="utf-8")
    # 2. Try env var (for injection at deploy time)
    env_doc = os.environ.get("VIDHI_ARCH_DOC", "")
    if env_doc:
        return env_doc
    # 3. Stub — replace with actual document before first use
    log.warning("Architecture document not found — using stub. Set VIDHI_ARCH_DOC_PATH.")
    return (
        "[Architecture document not loaded. "
        "Set VIDHI_ARCH_DOC_PATH to the path of vanik_architecture.txt "
        "or VIDHI_ARCH_DOC to the document text.]"
    )

ARCH_DOC: str = _load_arch_doc()
ARCH_DOC_HASH: str = hashlib.md5(ARCH_DOC.encode("utf-8", errors="ignore")).hexdigest()[:8]
log.info(f"Architecture document loaded: {len(ARCH_DOC):,} chars")


# ── Section system prompts ────────────────────────────────────────────
# Each section focuses the agent on a slice of the document.
# The full document is always included — the section context is the lens.

BASE_SYSTEM = """You are Vidhi (विधि), the architecture guidelines agent for the Akeru platform.
Your knowledge comes from the Vanik Architecture Document (v1.6.0), provided below.
You help engineers understand the system design, make implementation decisions, and navigate the codebase.

Rules:
- Answer precisely. Cite the relevant section or file when relevant.
- When suggesting implementation, reference the specific file and function (see Section 10 of the document).
- If a question cannot be answered from the architecture document, say so clearly — do not invent design decisions.
- Keep responses concise. Prefer specificity over completeness.
- Format code blocks with triple backticks and the language name.

Architecture Document:
──────────────────────
{arch_doc}
──────────────────────
"""

# Smaller system prompt for local LLMs (we inject only relevant excerpts).
BASE_SYSTEM_EXCERPTS = """You are Vidhi (विधि), the architecture guidelines agent for the Akeru platform.
Your knowledge comes from the Vanik Architecture Document (v1.6.0).
You will be given EXCERPTS relevant to the user's question.

Rules:
- Answer precisely and ground answers in the excerpts.
- Cite the relevant section heading or file path when possible.
- If the excerpts are insufficient, ask for clarification rather than guessing.
- Keep responses concise. Prefer specificity over completeness.

Relevant excerpts:
──────────────────
{excerpts}
──────────────────
"""

SECTION_ADDENDUM = {
    "general": "",

    "model-selection": """
Current section focus: MODEL SELECTION (Section 9).
Key topics: local Ollama LLaMA vs Gemini Flash vs Gemini Pro, Claude Haiku vs Sonnet,
DeBERTa Job A (NER) vs Job B (chapter classifier), Sentence Transformers on-premise,
when each model is appropriate, cost and latency trade-offs.
Always ground answers in the pipeline context — where in Module 1/2/3 each model sits.
""",

    "manifest-search": """
Current section focus: MANIFEST SEARCH / NES PIPELINE (Sections 3, 3.1, 3.2).
Key topics: Module 1 (Entity Extractor / extractor.py), Module 2 (Query Builder / query_builder.py),
Module 3 (Search Executor / search_hs_schedule.py), ExtractionResult contract, SearchPlan,
SearchStrategy, chapter_hints.yaml, FTS5, uk_api_search, LIKE fallback.
The root cause of the cotton-shirts → brake-callipers failure is central to this section.
""",

    "mcp": """
Current section focus: MCP PROTOCOL STACK (Sections 4a, 5).
Key topics: Three MCP servers (wto, uk-tariff, eu-taric), streamable-http transport (not stdio),
HMAC token authentication in MCP init handshake, A2A protocol compatibility,
tool schemas, platform surfaces map (Section 4a), api.akeru.dev routing.
""",

    "rag-vs-reasoning": """
Current section focus: RAG vs REASONING LAYERS (Sections 2, 3, 4b, 9).
Key topics: deterministic retrieval (SQLite FTS5, UK Trade Tariff API, LIKE),
vs chain-of-thought reasoning (Claude Haiku Tier 2, Gemini Pro),
the architecture agent's own RAG design (Section 4b: Voyage-3 embeddings, Sonnet synthesis),
when retrieval quality dominates (Huyen Ch.6 framing), the query construction layer as the fix.
""",

    "prompt-engineering": """
Current section focus: PROMPT ENGINEERING (Section 8).
Key topics: Haiku extraction prompt (Tier 2, Section 3.1), Hindi synthesis prompt (_HINDI_SYSTEM,
Section 8.4a), chapter prediction prompt (Section 3.2), architecture agent system prompt (Section 4b),
language-aware error messages (errors.py, Section 3.3), prompt design principles visible in the codebase.
""",
}


def build_system_prompt(section: str) -> str:
    base = BASE_SYSTEM.format(arch_doc=ARCH_DOC)
    addendum = SECTION_ADDENDUM.get(section, "")
    return base + addendum


def _extract_keywords(text: str) -> list[str]:
    words: list[str] = []
    for raw in (text or "").lower().replace("/", " ").replace("_", " ").split():
        w = "".join(ch for ch in raw if ch.isalnum() or ch in ("-", "."))
        if len(w) >= 4:
            words.append(w)
    out: list[str] = []
    for w in words:
        if w not in out:
            out.append(w)
    return out[:12]


_SEMANTIC_MODEL = None
_SEMANTIC_CHUNKS: list[str] | None = None
_SEMANTIC_EMBEDS = None


def _init_semantic_index() -> bool:
    """Build a semantic index for the architecture doc.

    Uses Sentence Transformers (all-MiniLM-L6-v2) on CPU.
    If dependencies are missing, returns False (caller should fall back).
    """
    global _SEMANTIC_MODEL, _SEMANTIC_CHUNKS, _SEMANTIC_EMBEDS
    if _SEMANTIC_MODEL is not None and _SEMANTIC_CHUNKS is not None and _SEMANTIC_EMBEDS is not None:
        return True

    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
        import numpy as np  # noqa: F401
    except Exception:
        return False

    embed_model_name = os.environ.get("VIDHI_EMBED_MODEL", "all-MiniLM-L6-v2").strip()

    # Chunk by markdown headings ("## ").
    chunks: list[str] = []
    parts = ARCH_DOC.split("\n## ")
    for idx, p in enumerate(parts):
        block = ("## " + p) if idx > 0 else p
        block = block.strip()
        if not block:
            continue
        if len(block) > 3500:
            block = block[:3500]
        chunks.append(block)

    model = SentenceTransformer(embed_model_name)
    embeds = model.encode(chunks, normalize_embeddings=True)

    _SEMANTIC_MODEL = model
    _SEMANTIC_CHUNKS = chunks
    _SEMANTIC_EMBEDS = embeds
    return True


def _doc_excerpts_for_query_semantic(
    query: str, section: str, *, max_chars: int = 9000, top_k: int = 6
) -> str | None:
    if not _init_semantic_index():
        return None
    if _SEMANTIC_MODEL is None or _SEMANTIC_CHUNKS is None or _SEMANTIC_EMBEDS is None:
        return None

    import numpy as np

    qtext = f"{query}\n\nSection lens: {section}".strip()
    qv = _SEMANTIC_MODEL.encode([qtext], normalize_embeddings=True)[0]
    sims = np.dot(_SEMANTIC_EMBEDS, qv)

    top_idxs = np.argsort(-sims)[:top_k]
    chosen: list[str] = []
    remaining = max_chars
    for i in top_idxs:
        chunk = _SEMANTIC_CHUNKS[int(i)]
        if len(chunk) > remaining:
            chunk = chunk[:remaining]
        if chunk:
            chosen.append(chunk)
            remaining -= len(chunk) + 2
        if remaining <= 0:
            break

    if not chosen:
        return None
    return "\n\n".join(chosen).strip()


def _doc_excerpts_for_query(query: str, section: str, *, max_chars: int = 9000) -> str:
    """Select relevant markdown 'chapters' (## headings).

    Prefer semantic retrieval when Sentence Transformers is available.
    Fall back to keyword scoring otherwise.
    """
    semantic = _doc_excerpts_for_query_semantic(query, section, max_chars=max_chars)
    if semantic:
        return semantic

    kws = set(_extract_keywords(query) + _extract_keywords(section))
    if not kws:
        kws = {"vanik", "architecture"}

    parts = ARCH_DOC.split("\n## ")
    scored: list[tuple[int, str]] = []
    for idx, p in enumerate(parts):
        block = ("## " + p) if idx > 0 else p
        lower = block.lower()
        score = sum(lower.count(k) for k in kws)
        if score:
            scored.append((score, block.strip()))

    scored.sort(key=lambda t: t[0], reverse=True)
    if not scored:
        return ARCH_DOC[: max_chars // 2]

    chosen: list[str] = []
    remaining = max_chars
    for score, block in scored[:6]:
        if remaining <= 0:
            break
        snippet = block
        if len(snippet) > remaining:
            snippet = snippet[:remaining]
        chosen.append(snippet)
        remaining -= len(snippet) + 2
    return "\n\n".join(chosen).strip()


def build_system_prompt_local(
    section: str, query: str, *, anchor_context: str = ""
) -> str:
    excerpts = _doc_excerpts_for_query(query, section)
    base = BASE_SYSTEM_EXCERPTS.format(excerpts=excerpts)
    addendum = SECTION_ADDENDUM.get(section, "")
    anchor_block = ""
    ac = (anchor_context or "").strip()
    if ac:
        ac = ac[:12000]
        anchor_block = (
            "\n\nBlog / anchor context (reader selected this on akeru.dev):\n"
            "──────────────────\n"
            f"{ac}\n"
            "──────────────────\n"
            "Ground answers in the architecture excerpts above; treat this anchor context "
            "as the reader's immediate focus.\n"
        )
    return base + addendum + anchor_block


# ── Request validation ───────────────────────────────────────────────

def _validate_request(body: dict) -> tuple[str, str, str, list[dict], str | None]:
    """Returns (model, section, session_id, history, error_msg)."""
    model = body.get("model", f"ollama/{_DEFAULT_OLLAMA_MODEL}")
    if not isinstance(model, str) or not model:
        return "", "", "", [], "model must be a non-empty string"
    if _is_gemini_model(model) and model not in ALLOWED_MODELS:
        return "", "", "", [], f"Unknown model '{model}'. Allowed: {sorted(ALLOWED_MODELS)}"
    if _is_ollama_model(model):
        # ok — local models are validated by Ollama at runtime
        pass
    elif not _is_gemini_model(model):
        return "", "", "", [], "Unsupported model format. Use 'ollama/<name>' or 'models/<gemini-id>'."

    section = body.get("section", "general")
    if section not in SECTION_ADDENDUM:
        section = "general"

    session_id = str(body.get("session_id", ""))[:64]

    raw_history = body.get("history", [])
    if not isinstance(raw_history, list):
        return model, section, session_id, [], "history must be a list"

    # Sanitise and cap history
    history: list[dict] = []
    for turn in raw_history:
        if not isinstance(turn, dict):
            continue
        role = turn.get("role", "")
        content = turn.get("content", "")
        if role in ("user", "assistant") and isinstance(content, str):
            history.append({"role": role, "content": content[:8000]})

    # Keep last N turns (user+assistant pairs) to avoid context overflow
    max_msgs = MAX_HISTORY_TURNS * 2
    if len(history) > max_msgs:
        history = history[-max_msgs:]

    return model, section, session_id, history, None


# ── SSE helpers ──────────────────────────────────────────────────────

def _sse(data: str) -> bytes:
    return f"data: {data}\n\n".encode()

def _sse_error(msg: str):
    # Vidhi UI expects the OpenAI-like delta shape: {"choices":[{"delta":{"content": ...}}]}
    payload = json.dumps({"choices": [{"delta": {"content": msg}}]})
    return _sse(payload)


# ── Chat endpoint ────────────────────────────────────────────────────

async def chat_endpoint(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    # Rate limit per client IP (important to prevent abuse of local Ollama endpoint).
    client_host = (
        (request.headers.get("X-Forwarded-For", "") or "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )
    now = time.time()
    window_start = now - 60.0
    async with _rate_lock:
        bucket = _rate_state.setdefault(client_host, [])
        bucket[:] = [t for t in bucket if t >= window_start]
        if len(bucket) >= _RATE_LIMIT_PER_MIN:
            return JSONResponse({"error": "Rate limit exceeded"}, status_code=429)
        bucket.append(now)

    model, section, session_id, history, err = _validate_request(body)
    if err:
        return JSONResponse({"error": err}, status_code=400)
    access_code = str(body.get("access_code", "")).strip()
    if _is_gemini_model(model):
        if _GEMINI_UNLOCK_CODE and access_code != _GEMINI_UNLOCK_CODE:
            return JSONResponse({"error": "Gemini is locked. Provide a valid access_code."}, status_code=403)
        if not _GEMINI_API_KEY:
            return JSONResponse(
                {"error": "GEMINI_API_KEY is not set on the server."},
                status_code=500,
            )

    # Extract the latest user question so we can lens excerpts accordingly.
    last_user = ""
    for turn in reversed(history):
        if turn.get("role") == "user":
            last_user = str(turn.get("content") or "")
            break

    anchor_context = str(body.get("anchor_context", "") or "").strip()[:12000]

    # Blend anchor snippet into excerpt retrieval (φ¹/φ² blog panels).
    query_for_excerpts = (
        f"{last_user}\n\n{anchor_context}" if anchor_context else last_user
    )

    # Avoid dumping the full ARCH_DOC into Gemini; inject only relevant excerpts instead.
    # For Ollama we always do this (context window constraints).
    system_prompt = (
        build_system_prompt_local(
            section, query_for_excerpts, anchor_context=anchor_context
        )
        if (_is_ollama_model(model) or _is_gemini_model(model))
        else build_system_prompt(section)
    )
    prompt = _build_prompt(system_prompt, history)

    last_user_query = ""
    for turn in reversed(history):
        if turn.get("role") == "user":
            last_user_query = str(turn.get("content") or "")
            break

    log.info(f"session={session_id} model={model} section={section} turns={len(history)}")

    async def event_stream():
        try:
            answer_parts: list[str] = []
            answer_len = 0

            if _is_ollama_model(model):
                ollama_model = model.split("/", 1)[1]
                url = f"{_OLLAMA_BASE_URL}/api/generate"
                async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=60.0)) as client:
                    async with client.stream(
                        "POST",
                        url,
                        json={"model": ollama_model, "prompt": prompt, "stream": True},
                        headers={"Content-Type": "application/json"},
                    ) as resp:
                        if resp.status_code >= 400:
                            body_text = (await resp.aread()).decode(errors="replace")
                            raise RuntimeError(
                                f"Ollama HTTP {resp.status_code} from {url}: {body_text[:500]}"
                            )
                        async for line in resp.aiter_lines():
                            if not line:
                                continue
                            try:
                                obj = json.loads(line)
                            except Exception:
                                continue
                            if obj.get("error"):
                                raise RuntimeError(f"Ollama error: {obj.get('error')}")
                            delta = obj.get("response") or ""
                            if delta:
                                if answer_len < 20000:
                                    answer_parts.append(delta)
                                    answer_len += len(delta)
                                payload = json.dumps({"choices": [{"delta": {"content": delta}}]})
                                yield _sse(payload)
                            if obj.get("done") is True:
                                break
            else:
                _configure_gemini_if_needed()
                gmodel = genai.GenerativeModel(model_name=model)

                # google-generativeai streaming iterator is blocking; run in a thread and forward chunks.
                q: asyncio.Queue[str | None] = asyncio.Queue()

                def _run_stream() -> None:
                    try:
                        contents = _build_gemini_contents(system_prompt, history)
                        try:
                            iterator = gmodel.generate_content(
                                contents,
                                stream=True,
                                generation_config={
                                    "temperature": 0.3,
                                    "max_output_tokens": 2048,
                                },
                            )
                        except Exception:
                            iterator = gmodel.generate_content(
                                prompt,
                                stream=True,
                                generation_config={
                                    "temperature": 0.3,
                                    "max_output_tokens": 2048,
                                },
                            )

                        for chunk in iterator:
                            text = getattr(chunk, "text", None)
                            if text:
                                q.put_nowait(text)
                    except Exception as exc:
                        q.put_nowait(f"[ERROR]{exc}")
                    finally:
                        q.put_nowait(None)

                producer = asyncio.create_task(asyncio.to_thread(_run_stream))

                while True:
                    try:
                        delta = await asyncio.wait_for(q.get(), timeout=30.0)
                    except asyncio.TimeoutError:
                        raise TimeoutError("Gemini stream timed out (no tokens for 30s).")
                    if delta is None:
                        break
                    if delta.startswith("[ERROR]"):
                        raise RuntimeError(delta[len("[ERROR]") :])
                    if answer_len < 20000:
                        answer_parts.append(delta)
                        answer_len += len(delta)
                    payload = json.dumps({"choices": [{"delta": {"content": delta}}]})
                    yield _sse(payload)

                await producer

            # Write a single JSONL log line after the stream completes.
            try:
                _query_log_entry = {
                    "ts": int(time.time()),
                    "session_id": session_id,
                    "model": model,
                    "section": section,
                    "question": last_user_query[:4000],
                    "answer": "".join(answer_parts)[:20000],
                }
                _query_log_path = _QUERY_LOG_PATH
                _query_log_path.parent.mkdir(parents=True, exist_ok=True)
                with open(_query_log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(_query_log_entry, ensure_ascii=False) + "\n")
            except Exception:
                # Logging must never break chat streaming.
                pass
            yield _sse("[DONE]")
        except Exception as exc:
            log.exception("Vidhi stream error")
            msg = str(exc).strip() or repr(exc)
            yield _sse_error(msg)
            yield _sse("[DONE]")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable Nginx/Caddy buffering
        },
    )


# ── Health ───────────────────────────────────────────────────────────

async def health_endpoint(request: Request):
    doc_loaded = ARCH_DOC and not ARCH_DOC.startswith("[Architecture document not loaded")
    return JSONResponse({
        "status": "ok",
        "agent": "vidhi",
        "arch_doc_loaded": doc_loaded,
        "arch_doc_chars": len(ARCH_DOC),
        "arch_doc_hash": ARCH_DOC_HASH,
    })


# ── App ──────────────────────────────────────────────────────────────

app = Starlette(
    debug=False,
    routes=[
        Route("/vidhi/api/chat", chat_endpoint, methods=["POST"]),
        Route("/vidhi/health",   health_endpoint, methods=["GET"]),
    ],
    middleware=[
        Middleware(
            CORSMiddleware,
            allow_origins=[
                "https://akeru.dev",
                "https://www.akeru.dev",
                "http://localhost:3000",
                "http://127.0.0.1:3000",
            ],
            allow_methods=["POST", "GET", "OPTIONS"],
            allow_headers=["Content-Type"],
        )
    ],
)
