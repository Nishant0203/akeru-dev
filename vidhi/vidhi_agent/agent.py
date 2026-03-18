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
    well within DeepSeek's 128K window)
  - Stateless: caller sends full history each request
  - Model: gemini-1.5-flash (fast) or gemini-1.5-pro (deeper) — caller selects

Run (dev):
  uvicorn vidhi.vidhi_agent.agent:app --port 8001 --reload

Run (prod, alongside Vanik on port 8000):
  uvicorn vidhi.vidhi_agent.agent:app --port 8001 --workers 1
  # Caddy reverse-proxies /vidhi/* → localhost:8001
"""

import asyncio
import json
import logging
import os
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
# Set GEMINI_API_KEY in secrets.env.
_GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
if not _GEMINI_API_KEY:
    log.warning("GEMINI_API_KEY not set — /vidhi/api/chat will fail until configured.")

genai.configure(api_key=_GEMINI_API_KEY)

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

SECTION_ADDENDUM = {
    "general": "",

    "model-selection": """
Current section focus: MODEL SELECTION (Section 9).
Key topics: deepseek-chat (V3.2) vs deepseek-reasoner (R1), Claude Haiku vs Sonnet,
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
vs chain-of-thought reasoning (Claude Haiku Tier 2, DeepSeek R1),
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
    payload = json.dumps({"error": msg})
    return _sse(payload)


# ── Chat endpoint ────────────────────────────────────────────────────

async def chat_endpoint(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

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

    system_prompt = build_system_prompt(section)
    prompt = _build_prompt(system_prompt, history)

    log.info(f"session={session_id} model={model} section={section} turns={len(history)}")

    async def event_stream():
        try:
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
                        resp.raise_for_status()
                        async for line in resp.aiter_lines():
                            if not line:
                                continue
                            try:
                                obj = json.loads(line)
                            except Exception:
                                continue
                            delta = obj.get("response") or ""
                            if delta:
                                payload = json.dumps({"choices": [{"delta": {"content": delta}}]})
                                yield _sse(payload)
                            if obj.get("done") is True:
                                break
            else:
                gmodel = genai.GenerativeModel(model_name=model)

                # google-generativeai streaming iterator is blocking; run in a thread and forward chunks.
                q: asyncio.Queue[str | None] = asyncio.Queue()

                def _run_stream() -> None:
                    try:
                        for chunk in gmodel.generate_content(
                            prompt,
                            stream=True,
                            generation_config={
                                "temperature": 0.3,
                                "max_output_tokens": 2048,
                            },
                        ):
                            text = getattr(chunk, "text", None)
                            if text:
                                q.put_nowait(text)
                    except Exception as exc:
                        q.put_nowait(f"[ERROR]{exc}")
                    finally:
                        q.put_nowait(None)

                producer = asyncio.create_task(asyncio.to_thread(_run_stream))

                while True:
                    delta = await q.get()
                    if delta is None:
                        break
                    if delta.startswith("[ERROR]"):
                        raise RuntimeError(delta[len("[ERROR]") :])
                    payload = json.dumps({"choices": [{"delta": {"content": delta}}]})
                    yield _sse(payload)

                await producer
            yield _sse("[DONE]")
        except Exception as exc:
            log.error(f"Vidhi stream error: {exc}")
            yield _sse_error(str(exc))
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
