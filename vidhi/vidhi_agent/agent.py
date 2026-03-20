"""
vidhi/vidhi_agent/agent.py  —  v2.0
────────────────────────────────────────────────────────────────
Vidhi — Architecture Guidelines Agent
Starlette ASGI app. Runs at api.akeru.dev/vidhi/*

Routes
  POST /vidhi/api/chat    → SSE stream (text/event-stream)
  GET  /vidhi/health      → {"status": "ok", "agent": "vidhi", ...}

Two request modes
  Anchor mode:   { concept_key, post_id, ... }
                 Concept Resolution resolves seed from server-side YAML.
                 Client never sends seed text.

  Freeform mode: { section, ... }
                 Full arch doc in context. Standalone Vidhi page.

Changes from 748a2d1
  1. Concept Resolution (concept_resolution.py) replaces client-sent
     anchor_context. Client sends concept_key + post_id only.
     anchor_context from client accepted as backward-compat fallback.

  2. Correct layer ordering (attention position rule):
     OLD: ANCHOR_PREAMBLE → ARCH_DOC → section_addendum
     NEW: role → arch_doc_sections → section_addendum → ANCHOR_PREAMBLE (END)

  3. InformationFilter: anchor mode sends only relevant arch doc sections,
     not full 12.8K. Full doc for freeform sessions only.

  4. Gemini native contents format replaces flat _build_prompt string.

  5. Query log extended: concept_key, post_id, arch_doc_hash, registry_hash,
     resolution_tier, prompt_version.

  6. DeepSeek references removed from SECTION_ADDENDUM.

  7. enterprise-privacy section added for φ² post.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from collections import defaultdict
from pathlib import Path

import google.generativeai as genai
import httpx
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from .concept_resolution import (
    ConceptContext,
    ResolutionResult,
    load_registry,
    registry_status,
    resolve_concept,
)

# ── Logging ───────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [vidhi] %(message)s")
log = logging.getLogger("vidhi")

PROMPT_VERSION = "vidhi-v2.0"

# ── Gemini — lazy configure (not at import time) ─────────────────────
_gemini_configured = False

def _configure_gemini() -> None:
    global _gemini_configured
    if _gemini_configured:
        return
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set on the server.")
    genai.configure(api_key=key)
    _gemini_configured = True

_GEMINI_UNLOCK_CODE   = os.environ.get("VIDHI_GEMINI_UNLOCK_CODE", "").strip()
_OLLAMA_BASE_URL      = os.environ.get("VIDHI_OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
_DEFAULT_OLLAMA_MODEL = os.environ.get("VIDHI_OLLAMA_MODEL", "llama3.1:8b").strip()

# ── Rate limiter (per real client IP via X-Real-IP) ───────────────────
_RATE_LIMIT     = int(os.environ.get("VIDHI_RATE_LIMIT_PER_MIN", "20"))
_rate_store: dict[str, list[float]] = defaultdict(list)

def _is_rate_limited(ip: str) -> bool:
    now = time.time()
    _rate_store[ip] = [t for t in _rate_store[ip] if t > now - 60.0]
    if len(_rate_store[ip]) >= _RATE_LIMIT:
        return True
    _rate_store[ip].append(now)
    return False

# ── Architecture document (GroundingDocument) ─────────────────────────
def _load_arch_doc() -> str:
    path = Path(os.environ.get("VIDHI_ARCH_DOC_PATH", "vidhi/vidhi_agent/vanik_architecture.txt"))
    if path.exists():
        return path.read_text(encoding="utf-8")
    env = os.environ.get("VIDHI_ARCH_DOC", "")
    if env:
        return env
    log.warning("Architecture document not found. Set VIDHI_ARCH_DOC_PATH.")
    return "[Architecture document not loaded.]"

ARCH_DOC:      str = _load_arch_doc()
ARCH_DOC_HASH: str = hashlib.md5(ARCH_DOC.encode()).hexdigest()[:8]
log.info(f"Architecture document: {len(ARCH_DOC):,} chars hash={ARCH_DOC_HASH}")

# Load concept registries at startup
for _pid in ("phi1", "phi2"):
    load_registry(_pid)

# ── Allowed models ────────────────────────────────────────────────────
ALLOWED_MODELS = {
    "models/gemini-2.0-flash",
    "models/gemini-2.5-flash",
    "models/gemini-2.5-pro",
    "models/gemini-flash-latest",
    "models/gemini-pro-latest",
}
MAX_HISTORY_PAIRS = 12

def _is_gemini_model(m: str) -> bool: return m.startswith("models/")
def _is_ollama_model(m: str) -> bool: return m.startswith("ollama/")

# ── Section addenda ───────────────────────────────────────────────────
SECTION_ADDENDUM: dict[str, str] = {
    "general": "",
    "model-selection": """
Current section focus: MODEL SELECTION (Section 8).
Key topics: Claude Haiku vs Sonnet, Gemini Flash vs Pro,
DeBERTa Job A (NER) vs Job B (chapter classifier), Sentence Transformers,
LLM-as-last-resort principle, cost and latency trade-offs.
Ground answers in which pipeline stage each model sits.
""",
    "manifest-search": """
Current section focus: MANIFEST SEARCH / NES PIPELINE (Sections 4, 5).
Key topics: Module 1 extractor.py (ExtractionResult), Module 2 query_builder.py
(SearchPlan/SearchStrategy), Module 3 search_hs_schedule.py, corridor stripping,
chapter_hints.yaml, FTS5, UK Trade Tariff API, cotton-shirts failure.
""",
    "mcp": """
Current section focus: MCP PROTOCOL STACK (Section 6).
Key topics: vanik_api / vanik_docs servers, streamable-http transport,
HMAC authentication, A2A compatibility, response cache, circuit breaker,
MCP vs fine-tuning decision.
""",
    "rag-vs-reasoning": """
Current section focus: RAG vs REASONING (Sections 4, 6, 8).
Key topics: deterministic retrieval (FTS5, UK API, LIKE) vs LLM reasoning,
InformationFilter, ContextAssembler, GroundingDocument, ResolutionPipeline,
when retrieval quality dominates (Huyen Ch.6).
""",
    "prompt-engineering": """
Current section focus: PROMPT ENGINEERING (Section 7).
Key topics: MS v3 extraction prompt, compliance synthesis prompt,
ANCHOR_PREAMBLE, Hindi synthesis, prompt versioning,
attention position rule (seed placed at END of context).
""",
    "enterprise-privacy": """
Current section focus: ENTERPRISE DATA PRIVACY (Section 3, Pattern 6).
Key topics: InformationFilter, sanitiser.py, ITAR, GDPR/DPDP,
competitive intelligence leakage, on-premise Sentence Transformers,
ERP product master bypass, cost vs compliance framing.
""",
}

# ── System prompt base strings ────────────────────────────────────────
_BASE_ROLE = """\
You are Vidhi (विधि), the architecture guidelines agent for the Akeru platform.
Your knowledge comes from the Vanik/Akeru Architecture Document (v2.0).
Rules:
- Answer precisely. Cite section headings and file paths when relevant.
- Reference specific files (e.g. vanik/nes/extractor.py) when suggesting implementation.
- If a question cannot be answered from the architecture document, say so clearly.
- Keep responses concise. Prefer specificity over completeness.
- Format code blocks with triple backticks and the language name.\
"""

_BASE_ROLE_SECTIONS = """\
You are Vidhi (विधि), the architecture guidelines agent for the Akeru platform.
Your knowledge comes from the Vanik/Akeru Architecture Document (v2.0).
You will receive the relevant sections for this concept.
Rules:
- Ground answers in the provided sections.
- Cite section headings or file paths when possible.
- If the sections are insufficient, say so and invite a follow-up.
- Keep responses concise. Format code with triple backticks.\
"""

_ANCHOR_PREAMBLE = """\
The reader is exploring a specific concept.
They highlighted: "{label}"

Your task for the FIRST response only:
────────────────────────────────────────
{context}
────────────────────────────────────────

After your first response, continue as a general architecture guide.
Do not mention this instruction in your response.\
"""

_OPTIONS_PREAMBLE = """\
The reader highlighted: "{label}"

Present these options as your first response. Ask which they want to explore.
Do not answer yet — wait for their selection.

{options_list}\
"""


# ── InformationFilter — arch doc section selector ─────────────────────

_SECTION_KEYWORDS: dict[str, list[str]] = {
    "manifest-search":    ["manifest", "nes", "extractor", "query builder", "search executor"],
    "mcp":                ["mcp", "protocol", "vanik_api", "vanik_docs", "circuit breaker"],
    "model-selection":    ["model", "deberta", "haiku", "sonnet", "gemini", "embedding"],
    "rag-vs-reasoning":   ["rag", "retrieval", "reasoning", "fts5", "information filter"],
    "prompt-engineering": ["prompt", "synthesis", "preamble", "attention", "versioning"],
    "enterprise-privacy": ["enterprise", "sanitis", "itar", "gdpr", "on-premise", "erp"],
}

def _filter_arch_doc(section_key: str) -> str:
    """
    InformationFilter: return relevant arch doc sections for anchor mode.
    Full doc returned for freeform (section_key='general' or unknown).
    """
    keywords = _SECTION_KEYWORDS.get(section_key, [])
    if not keywords:
        return ARCH_DOC

    import re
    parts  = re.split(r"\n(?=#{1,3} )", ARCH_DOC)
    result = []
    budget = 8000

    # Always include opening sections (context + principles)
    for p in parts[:3]:
        result.append(p)
        budget -= len(p)

    scored = []
    for p in parts[3:]:
        score = sum(p.lower().count(kw) for kw in keywords)
        if score > 0:
            scored.append((score, p))
    scored.sort(key=lambda t: t[0], reverse=True)

    for _, p in scored[:4]:
        if budget <= 0:
            break
        result.append(p[:budget])
        budget -= len(p)

    filtered = "\n".join(result).strip()
    return filtered if filtered else ARCH_DOC


# ── ContextAssembler ──────────────────────────────────────────────────

def _assemble_system_prompt(
    *,
    concept: ConceptContext | None,
    section: str,
    is_anchor: bool,
) -> str:
    """
    Layer ordering (attention position rule — Architecture v2.0 Section 3):
      1. Role instructions            (before_doc)
      2. Grounding document/sections  (document)
      3. Section addendum             (after_doc)
      4. Anchor preamble / seed       (END — highest attention weight)
    """
    parts: list[str] = []

    # Layer 1 — Role
    parts.append(_BASE_ROLE_SECTIONS.strip() if is_anchor else _BASE_ROLE.strip())

    # Layer 2 — Grounding document
    if is_anchor and concept:
        filtered = _filter_arch_doc(concept.section)
        parts.append(
            "Relevant architecture sections:\n"
            "──────────────────────────────\n"
            + filtered.strip() +
            "\n──────────────────────────────"
        )
    else:
        parts.append(
            "Architecture Document:\n"
            "──────────────────────\n"
            + ARCH_DOC.strip() +
            "\n──────────────────────"
        )

    # Layer 3 — Section addendum
    addendum_key = (concept.section if concept else section)
    addendum = SECTION_ADDENDUM.get(addendum_key, "").strip()
    if addendum:
        parts.append(addendum)

    # Layer 4 — Anchor preamble (END)
    if is_anchor and concept:
        if concept.opening_mode == "options" and concept.options:
            opts = "\n".join(f"  {i+1}. {o}" for i, o in enumerate(concept.options))
            preamble = _OPTIONS_PREAMBLE.format(
                label=concept.label, options_list=opts
            ).strip()
        else:
            preamble = _ANCHOR_PREAMBLE.format(
                label=concept.label, context=concept.context
            ).strip()
        parts.append(preamble)

    return "\n\n".join(parts)


# ── Gemini contents builder ───────────────────────────────────────────

def _gemini_contents(system_prompt: str, history: list[dict]) -> list[dict]:
    """Native Gemini role structure. System prompt prepended to first user turn."""
    contents: list[dict] = []
    for i, turn in enumerate(history):
        role    = "user" if turn["role"] == "user" else "model"
        content = turn.get("content", "")
        if i == 0 and role == "user":
            content = f"{system_prompt}\n\n{content}"
        contents.append({"role": role, "parts": [{"text": content}]})
    if not contents:
        contents = [{"role": "user", "parts": [{"text": system_prompt}]}]
    return contents


def _flat_prompt(system_prompt: str, history: list[dict]) -> str:
    """Flat string prompt for Ollama."""
    lines = [system_prompt.strip(), "", "Conversation:", "────────────"]
    for turn in history:
        role    = turn.get("role")
        content = (turn.get("content") or "").strip()
        if not content:
            continue
        lines.append(f"{'User' if role == 'user' else 'Vidhi'}: {content}")
    lines += ["────────────", "Vidhi:"]
    return "\n".join(lines).strip() + "\n"


# ── Query log ─────────────────────────────────────────────────────────

_LOG_PATH = os.environ.get("VIDHI_QUERY_LOG_PATH", "vidhi/vidhi_agent/vidhi_query_log.jsonl")

def _log_query(entry: dict) -> None:
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:
        log.warning(f"Query log write failed: {exc}")


# ── Request validation ────────────────────────────────────────────────

def _validate(body: dict) -> tuple[dict, str | None]:
    model = body.get("model", f"ollama/{_DEFAULT_OLLAMA_MODEL}")
    if not isinstance(model, str) or not model:
        return {}, "model must be a non-empty string"
    if _is_gemini_model(model) and model not in ALLOWED_MODELS:
        return {}, f"Unknown model '{model}'. Allowed: {sorted(ALLOWED_MODELS)}"
    if not _is_gemini_model(model) and not _is_ollama_model(model):
        return {}, "Unsupported model. Use 'ollama/<n>' or 'models/<gemini-id>'."

    section     = str(body.get("section", "general"))
    if section not in SECTION_ADDENDUM:
        section = "general"
    session_id  = str(body.get("session_id", ""))[:64]
    concept_key = str(body.get("concept_key", ""))[:64].strip()
    post_id     = str(body.get("post_id", "phi1"))[:32].strip()
    client_ctx  = str(body.get("anchor_context", ""))[:12000].strip()
    opening_mode= str(body.get("opening_mode", "answer"))

    raw_history = body.get("history", [])
    if not isinstance(raw_history, list):
        return {}, "history must be a list"
    history: list[dict] = [
        {"role": t["role"], "content": t["content"][:8000]}
        for t in raw_history
        if isinstance(t, dict) and t.get("role") in ("user", "assistant")
           and isinstance(t.get("content"), str)
    ]
    if len(history) > MAX_HISTORY_PAIRS * 2:
        history = history[-(MAX_HISTORY_PAIRS * 2):]

    return {
        "model": model, "section": section, "session_id": session_id,
        "concept_key": concept_key, "post_id": post_id,
        "client_ctx": client_ctx, "opening_mode": opening_mode, "history": history,
    }, None


# ── SSE helpers ───────────────────────────────────────────────────────

def _sse(data: str) -> bytes:
    return f"data: {data}\n\n".encode()

def _sse_delta(text: str) -> bytes:
    return _sse(json.dumps({"choices": [{"delta": {"content": text}}]}))


# ── Chat endpoint ─────────────────────────────────────────────────────

async def chat_endpoint(request: Request) -> StreamingResponse | JSONResponse:
    ip = (
        request.headers.get("X-Real-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or getattr(request.client, "host", "unknown")
    )
    if _is_rate_limited(ip):
        return JSONResponse({"error": "Rate limit exceeded"}, status_code=429)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    fields, err = _validate(body)
    if err:
        return JSONResponse({"error": err}, status_code=400)

    model       = fields["model"]
    section     = fields["section"]
    session_id  = fields["session_id"]
    concept_key = fields["concept_key"]
    post_id     = fields["post_id"]
    history     = fields["history"]
    client_ctx  = fields["client_ctx"]
    access_code = str(body.get("access_code", "")).strip()

    if _is_gemini_model(model):
        if _GEMINI_UNLOCK_CODE and access_code != _GEMINI_UNLOCK_CODE:
            return JSONResponse({"error": "Gemini is locked. Provide access_code."}, status_code=403)
        try:
            _configure_gemini()
        except RuntimeError as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)

    # ── Concept Resolution ───────────────────────────────────────────
    is_anchor = bool(concept_key)
    concept:   ConceptContext | None = None
    cr_result: ResolutionResult | None = None

    if is_anchor:
        cr_result = resolve_concept(concept_key, post_id)
        if cr_result.resolved:
            concept = cr_result.concept
        elif client_ctx:
            # Backward-compat: client-sent seed as fallback until YAML populated
            log.info(f"[CR] Tier miss for '{concept_key}' — using client fallback (tier 0)")
            concept = ConceptContext(
                concept_key=concept_key,
                post_id=post_id,
                label=concept_key.replace("-", " "),
                section=section,
                context=client_ctx,
                opening_mode=fields["opening_mode"],
                resolution_tier=0,
            )
        else:
            # No YAML, no client fallback — graceful degradation
            async def _not_found():
                msg = (
                    f"I don't have a specific guide for "
                    f"**{concept_key.replace('-', ' ')}** yet. "
                    f"Ask me directly — I'm grounded in the full architecture document."
                )
                yield _sse_delta(msg)
                yield _sse("[DONE]")
            return StreamingResponse(
                _not_found(), media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

    # ── Assemble context ─────────────────────────────────────────────
    system_prompt = _assemble_system_prompt(
        concept=concept, section=section, is_anchor=is_anchor
    )

    log.info(
        f"session={session_id} model={model} anchor={is_anchor} "
        f"concept={concept_key or '-'} post={post_id} turns={len(history)}"
    )

    # ── Stream ──────────────────────────────────────────────────────
    async def event_stream():
        out = ""
        try:
            if _is_ollama_model(model):
                prompt = _flat_prompt(system_prompt, history)
                ollama_model = model.split("/", 1)[1]
                async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=60.0)) as client:
                    async with client.stream(
                        "POST", f"{_OLLAMA_BASE_URL}/api/generate",
                        json={"model": ollama_model, "prompt": prompt, "stream": True},
                        headers={"Content-Type": "application/json"},
                    ) as resp:
                        if resp.status_code >= 400:
                            body_text = (await resp.aread()).decode(errors="replace")
                            raise RuntimeError(f"Ollama {resp.status_code}: {body_text[:300]}")
                        async for line in resp.aiter_lines():
                            if not line: continue
                            try:
                                obj = json.loads(line)
                            except Exception:
                                continue
                            if obj.get("error"):
                                raise RuntimeError(f"Ollama: {obj['error']}")
                            delta = obj.get("response") or ""
                            if delta:
                                out += delta
                                yield _sse_delta(delta)
                            if obj.get("done"):
                                break

            else:
                # Gemini — native contents format (Bug fix: not flat string)
                contents = _gemini_contents(system_prompt, history)
                gmodel   = genai.GenerativeModel(model_name=model)
                q: asyncio.Queue[str | None] = asyncio.Queue()

                def _run() -> None:
                    try:
                        for chunk in gmodel.generate_content(
                            contents, stream=True,
                            generation_config={"temperature": 0.3, "max_output_tokens": 2048},
                        ):
                            text = getattr(chunk, "text", None)
                            if text:
                                q.put_nowait(text)
                    except Exception as exc:
                        q.put_nowait(f"[ERROR]{exc}")
                    finally:
                        q.put_nowait(None)

                producer = asyncio.create_task(asyncio.to_thread(_run))
                while True:
                    try:
                        delta = await asyncio.wait_for(q.get(), timeout=30.0)
                    except asyncio.TimeoutError:
                        raise RuntimeError("Gemini stream timed out after 30s")
                    if delta is None:
                        break
                    if delta.startswith("[ERROR]"):
                        raise RuntimeError(delta[len("[ERROR]"):])
                    out += delta
                    yield _sse_delta(delta)
                await producer

            yield _sse("[DONE]")

        except Exception as exc:
            log.exception("Vidhi stream error")
            yield _sse_delta(f"\n\n[Error: {str(exc).strip() or repr(exc)}]")
            yield _sse("[DONE]")

        finally:
            _log_query({
                "ts":              time.time(),
                "session_id":      session_id,
                "model":           model,
                "prompt_version":  PROMPT_VERSION,
                "arch_doc_hash":   ARCH_DOC_HASH,
                "registry_hash":   (cr_result.registry_hash if cr_result else ""),
                "is_anchor":       is_anchor,
                "concept_key":     concept_key or None,
                "post_id":         post_id or None,
                "resolution_tier": (concept.resolution_tier if concept else None),
                "section":         (concept.section if concept and is_anchor else section),
                "turns":           len(history),
                "response_chars":  len(out),
            })

    return StreamingResponse(
        event_stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Health ────────────────────────────────────────────────────────────

async def health_endpoint(request: Request) -> JSONResponse:
    doc_ok = ARCH_DOC and not ARCH_DOC.startswith("[Architecture")
    return JSONResponse({
        "status":          "ok",
        "agent":           "vidhi",
        "prompt_version":  PROMPT_VERSION,
        "arch_doc_loaded": doc_ok,
        "arch_doc_chars":  len(ARCH_DOC),
        "arch_doc_hash":   ARCH_DOC_HASH,
        "registries":      registry_status(),
    })


# ── App ───────────────────────────────────────────────────────────────

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
