"""Session Gateway HTTP service for Vanik chat/API modes."""

from __future__ import annotations

import asyncio
import json
import logging
import os

from datetime import UTC, datetime
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = lambda _: None  # noqa: ARG005

# Load .env from vanik/ so ANTHROPIC_API_KEY, OPENAI_API_KEY, etc. are available at runtime
_vanik_root = Path(__file__).resolve().parent.parent
_env_file = _vanik_root / ".env"
_alt_env = _vanik_root / "Vanik_connections.env"
load_dotenv(_env_file)
if not _env_file.exists() and _alt_env.exists():
    load_dotenv(_alt_env)
from typing import Any
from uuid import uuid4

from starlette.applications import Starlette
from starlette.background import BackgroundTasks
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

CORS_ORIGINS = [
    "https://akeru.dev",
    "https://www.akeru.dev",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

from batch.batch_parser import parse_batch_bytes, parse_upload_csv
from batch.batch_processor import batch_max_items, process_batch
from batch.batch_reporter import results_to_csv
from batch.job_store import create_job, get_job, update_job
from batch.object_store import download as batch_store_download
from batch.object_store import upload as batch_store_upload

from agent.anchor_store import create_anchor, delete_anchor, list_anchors, rename_anchor
from agent.guardrails import validate_agent_output
from agent.health import build_health_snapshot
from agent.query_log import append_query, deterministic_query_id
from agent.session_store import SessionState, store
from agent.vanik_agent import vanik_agent

logger = logging.getLogger(__name__)


def _json_error(code: str, message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": {"code": code, "message": message}}, status_code=status)


def _session_payload(session: SessionState) -> dict[str, Any]:
    anchors = list_anchors(session.user_id) if session.user_id else []
    return {
        "session_id": session.session_id,
        "state": session.state,
        "seed": session.seed,
        "history_turn_count": session.history_turn_count,
        "pending_gate": session.pending_gate is not None,
        "anchors": anchors,
    }


async def _emit(session: SessionState, event: dict[str, Any], *, buffered: bool = True) -> None:
    if session.is_closed:
        return
    if buffered:
        with session.events_lock:
            session.last_response_events.append(event)
    await session.event_queue.put(event)


_WELCOME_MESSAGE = "Welcome to Vanik. Ask me about import duties for any product — for example: brake callipers from India to UK."


async def emit_welcome(session: SessionState) -> None:
    """Emit a static welcome sequence (thinking on → tokens → thinking off → done). No agent call. Unbuffered so reconnect does not replay it."""
    if session.is_closed:
        return
    await _emit(session, {"type": "thinking", "visible": True}, buffered=False)
    words = _WELCOME_MESSAGE.split()
    for idx, word in enumerate(words):
        suffix = "" if idx == len(words) - 1 else " "
        await _emit(session, {"type": "token", "content": word + suffix}, buffered=False)
        await asyncio.sleep(0)
    await _emit(session, {"type": "thinking", "visible": False}, buffered=False)
    await _emit(session, {"type": "done", "query_id": None, "anchor": None}, buffered=False)


async def _stream_narrative_tokens(session: SessionState, narrative: str) -> None:
    words = narrative.split(" ")
    for idx, token in enumerate(words):
        suffix = "" if idx == len(words) - 1 else " "
        await _emit(session, {"type": "token", "content": token + suffix})


def _landed_cost_from_result(result: dict[str, Any]) -> dict[str, Any]:
    data = result.get("data_part", {}).get("data", {})
    return data.get("vanik.compliance.LandedCost", {})


def _build_anchor_from_result(session: SessionState, query: str, result: dict[str, Any], query_id: str) -> dict[str, Any]:
    lc = _landed_cost_from_result(result)
    hs_code = str(lc.get("hs_code", ""))
    origin = str(lc.get("origin", ""))
    destination = str(lc.get("destination", ""))
    label = f"HS {hs_code} {origin} -> {destination}" if hs_code else "Vanik query"
    rates_summary = {
        "IN_to_GB_mfn_pct": lc.get("uk_mfn_rate_pct"),
        "IN_to_EU_mfn_pct": lc.get("eu_mfn_rate_pct"),
        "world_to_IN_mfn_pct": lc.get("india_mfn_rate_pct"),
    }
    return create_anchor(
        user_id=session.user_id,
        label=label,
        hs_code=hs_code,
        description=str(lc.get("description", "")),
        corridor=f"{origin} -> {destination}",
        prior_query=query,
        rates_summary=rates_summary,
        query_id=query_id,
        session_id=session.session_id,
    )


async def _handle_agent_result(session: SessionState, user_query: str, result: dict[str, Any]) -> None:
    if session.is_closed:
        return
    status = result.get("status")

    if status == "awaiting_confirmation":
        session.pending_gate = {
            "query": user_query,
            "entities": result.get("entities", {}),
            "options": result.get("options", []),
        }
        session.state = "awaiting_gate_response"
        await _emit(
            session,
            {
                "type": "gate",
                "options": result.get("options", []),
                "allow_manual": result.get("allow_manual_hs", True),
                "message": result.get("message", "Select one option or provide a 6/8/10-digit code."),
            },
        )
        return

    if status == "needs_clarification":
        missing = result.get("missing", [])
        field = missing[0] if missing else "unknown"
        session.state = "awaiting_clarification"
        await _emit(
            session,
            {
                "type": "clarify",
                "field": field,
                "message": result.get("message", "Please provide missing corridor details."),
            },
        )
        return

    if not result.get("ok"):
        session.state = "active"
        await _emit(
            session,
            {
                "type": "error",
                "code": status or "agent_error",
                "message": result.get("message", "Unable to complete query."),
                "details": result.get("errors") or result.get("error"),
            },
        )
        return

    valid, reason = validate_agent_output(result)
    if not valid:
        session.state = "active"
        await _emit(
            session,
            {
                "type": "error",
                "code": "guardrail_violation",
                "message": "Generated response failed output guardrail validation.",
                "details": {"reason": reason or "unknown"},
            },
        )
        return

    session.pending_gate = None
    session.state = "streaming"

    narrative = str(result.get("narrative", ""))
    await _stream_narrative_tokens(session, narrative)

    query_id = deterministic_query_id(session.session_id, session.history_turn_count, user_query)
    anchor = _build_anchor_from_result(session, user_query, result, query_id)

    # Skip audit and done event if session was closed while we were streaming (orphaned job).
    if session.is_closed:
        return

    append_query(
        {
            "query_id": query_id,
            "session_id": session.session_id,
            "user_id": session.user_id,
            "raw_query": user_query,
            "response": result,
            "status": "ok",
        }
    )

    session.state = "active"
    await _emit(session, {"type": "done", "query_id": query_id, "anchor": anchor})
    with session.events_lock:
        session.last_response_events.clear()


async def _run_agent_job(
    *,
    session: SessionState,
    user_query: str,
    gate_selection: str | None,
    precomputed_entities: dict[str, Any] | None = None,
    gate_options: list[dict[str, Any]] | None = None,
) -> None:
    """Run one agent turn asynchronously so POST /msg can return 202 immediately."""
    try:
        result = await vanik_agent(
            user_query,
            gate_selection=gate_selection,
            precomputed_entities=precomputed_entities,
            gate_options=gate_options,
        )
        if session.is_closed:
            return
        await _handle_agent_result(session, user_query, result)
    except Exception as exc:  # pragma: no cover - defensive path
        logger.exception("Agent execution failed: %s", exc)
        if session.is_closed:
            return
        session.state = "active"
        await _emit(
            session,
            {
                "type": "error",
                "code": "agent_execution_error",
                "message": "Agent execution failed.",
                "details": {"error": str(exc)},
            },
        )
    finally:
        if session.is_closed:
            return
        await _emit(session, {"type": "thinking", "visible": False}, buffered=False)


async def create_session(request: Request) -> JSONResponse:
    seed: dict[str, Any] = {}
    if request.headers.get("content-type", "").startswith("application/json"):
        try:
            seed = await request.json()
        except json.JSONDecodeError:
            seed = {}
    session = store.create(seed=seed)
    background = BackgroundTasks()
    background.add_task(emit_welcome, session)
    return JSONResponse(
        {"session_id": session.session_id, "created_at": session.created_at},
        status_code=201,
        background=background,
    )


async def get_session(request: Request) -> JSONResponse:
    session_id = request.path_params["session_id"]
    session = store.get(session_id)
    if session is None:
        return _json_error("session_not_found", "Session not found", status=404)
    return JSONResponse(_session_payload(session))


async def post_session_message(request: Request) -> JSONResponse:
    session_id = request.path_params["session_id"]
    session = store.get(session_id)
    if session is None:
        return _json_error("session_not_found", "Session not found", status=404)

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return _json_error("invalid_json", "Body must be valid JSON")

    role = str(body.get("role", "user"))
    content = str(body.get("content", "")).strip()
    if role != "user" or not content:
        return _json_error("invalid_message", "Body requires role='user' and non-empty content")

    store.append_message(session_id, "user", content)
    await _emit(session, {"type": "thinking", "visible": True}, buffered=False)

    background = BackgroundTasks()
    if session.pending_gate:
        pending = dict(session.pending_gate)
        background.add_task(
            _run_agent_job,
            session=session,
            user_query=pending.get("query", ""),
            gate_selection=content,
            precomputed_entities=pending.get("entities", {}),
            gate_options=pending.get("options", []),
        )
    else:
        background.add_task(
            _run_agent_job,
            session=session,
            user_query=content,
            gate_selection=None,
        )
    return JSONResponse({"ok": True, "accepted": True}, status_code=202, background=background)


async def resume_session(request: Request) -> JSONResponse:
    session_id = request.path_params["session_id"]
    session = store.get(session_id)
    if session is None:
        return _json_error("session_not_found", "Session not found", status=404)

    session.state = "reconnect"
    with session.events_lock:
        replay_count = len(session.last_response_events)
    return JSONResponse(
        {
            "session_id": session.session_id,
            "state": session.state,
            "last_response_replay": replay_count > 0,
            "replay_event_count": replay_count,
        }
    )


async def close_session(request: Request) -> Response:
    session_id = request.path_params["session_id"]
    state = store.delete(session_id)
    if state is None:
        return _json_error("session_not_found", "Session not found", status=404)

    append_query(
        {
            "query_id": deterministic_query_id(session_id, state.history_turn_count, "session_closed"),
            "session_id": session_id,
            "user_id": state.user_id,
            "status": "closed",
            "history_turn_count": state.history_turn_count,
        }
    )
    return Response(status_code=204)


def _encode_sse(event: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(event)}\n\n".encode("utf-8")


async def stream_events(request: Request) -> StreamingResponse | JSONResponse:
    session_id = request.path_params["session_id"]
    session = store.get(session_id)
    if session is None:
        return _json_error("session_not_found", "Session not found", status=404)

    with session.sse_lock:
        if session.has_active_sse:
            return _json_error(
                "sse_already_connected",
                "An SSE stream is already active for this session.",
                status=409,
            )
        session.has_active_sse = True

    session.state = "active"

    async def event_stream() -> Any:
        try:
            with session.events_lock:
                replay_events = list(session.last_response_events)
            for event in replay_events:
                yield _encode_sse(event)

            while True:
                if session.is_closed:
                    break
                if await request.is_disconnected():
                    session.state = "idle"
                    break

                try:
                    event = await asyncio.wait_for(session.event_queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield b": keepalive\n\n"
                    continue

                yield _encode_sse(event)
        finally:
            with session.sse_lock:
                session.has_active_sse = False

    return StreamingResponse(event_stream(), media_type="text/event-stream")


async def list_anchor_records(request: Request) -> JSONResponse:
    user_id = request.query_params.get("user_id")
    anchors = list_anchors(user_id)
    return JSONResponse(anchors)


async def patch_anchor(request: Request) -> JSONResponse:
    anchor_id = request.path_params["anchor_id"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return _json_error("invalid_json", "Body must be valid JSON")

    label = str(body.get("label", "")).strip()
    if not label:
        return _json_error("invalid_label", "label is required")

    updated = rename_anchor(anchor_id, label)
    if updated is None:
        return _json_error("anchor_not_found", "Anchor not found", status=404)
    return JSONResponse(updated)


async def delete_anchor_record(request: Request) -> Response | JSONResponse:
    anchor_id = request.path_params["anchor_id"]
    ok = delete_anchor(anchor_id)
    if not ok:
        return _json_error("anchor_not_found", "Anchor not found", status=404)
    return Response(status_code=204)


async def api_query(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return _json_error("invalid_json", "Body must be valid JSON")

    query = str(body.get("query", "")).strip()
    hs_code = str(body.get("hs_code", "")).strip()
    quantity = body.get("quantity")
    unit_value_usd = body.get("unit_value_usd")

    if not query or not hs_code:
        return _json_error("invalid_input", "query and hs_code are required")

    result = await vanik_agent(query, hs_code_provided=hs_code)
    if not result.get("ok"):
        status = 422 if result.get("status") in {"invalid_input", "needs_clarification"} else 502
        return JSONResponse(result, status_code=status)

    lc = _landed_cost_from_result(result)
    origin = str(lc.get("origin", "IN"))
    destination = str(lc.get("destination", "GB"))

    quantity_val = float(quantity) if quantity is not None else None
    unit_val = float(unit_value_usd) if unit_value_usd is not None else None

    def duty_estimate(rate: float | None) -> float | None:
        if rate is None or quantity_val is None or unit_val is None:
            return None
        return round(quantity_val * unit_val * (rate / 100.0), 2)

    api_session_id = f"api:{uuid4().hex}"
    query_id = deterministic_query_id(api_session_id, 1, query)

    payload = {
        "commodity_code": lc.get("hs_code"),
        "description": lc.get("description", ""),
        "corridors": {
            "IN_to_GB": {
                "mfn_rate_pct": lc.get("uk_mfn_rate_pct"),
                "estimated_duty_usd": duty_estimate(lc.get("uk_mfn_rate_pct")),
                "fta_available": False,
                "source": lc.get("uk_source"),
                "measure_type": lc.get("uk_measure_type"),
            },
            "IN_to_EU": {
                "mfn_rate_pct": lc.get("eu_mfn_rate_pct"),
                "estimated_duty_usd": duty_estimate(lc.get("eu_mfn_rate_pct")),
                "fta_available": False,
                "source": lc.get("eu_source"),
                "measure_type": lc.get("eu_measure_type"),
            },
            "world_to_IN": {
                "mfn_rate_pct": lc.get("india_mfn_rate_pct"),
                "igst_flag": "18% or 28% depending on sub-classification — not included",
                "source": lc.get("in_source"),
                "indicator": lc.get("in_indicator"),
                "year": lc.get("in_year"),
            },
        },
        "audit": {
            **result.get("audit", {}),
            "hs_code_source": "caller_supplied",
            "human_confirmed": False,
            "query_id": query_id,
            "origin": origin,
            "destination": destination,
        },
    }

    append_query({"query_id": query_id, "session_id": api_session_id, "raw_query": query, "response": payload})
    return JSONResponse(payload)


MAX_BATCH_UPLOAD_BYTES = 5 * 1024 * 1024


async def api_batch(request: Request) -> Response | JSONResponse:
    """POST batch: JSON or CSV body; JSON results or CSV when Accept: text/csv."""
    raw = await request.body()
    ct = request.headers.get("content-type", "")
    try:
        items = parse_batch_bytes(ct, raw)
    except (json.JSONDecodeError, ValueError) as exc:
        return _json_error("invalid_batch", str(exc))

    limit = batch_max_items()
    if len(items) > limit:
        return _json_error(
            "batch_too_large",
            f"Maximum {limit} items per request",
            status=413,
        )

    results = await process_batch(items)
    accept = (request.headers.get("accept") or "").lower()
    if "text/csv" in accept:
        return Response(
            results_to_csv(list(results)),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="vanik_batch.csv"'},
        )
    return JSONResponse({"ok": True, "count": len(results), "results": results})


async def _run_batch_job(job_id: str, items: list[dict[str, Any]]) -> None:
    """Background worker: process_batch → results CSV in object store."""
    update_job(job_id, status="processing")
    try:
        results = await process_batch(items)
        csv_raw = results_to_csv(list(results)).encode("utf-8")
        output_key = batch_store_upload(csv_raw, "results.csv", job_id)

        succeeded = sum(1 for r in results if r.get("ok"))
        failed = sum(1 for r in results if not r.get("ok"))
        needs_review = sum(1 for r in results if r.get("needs_review"))

        update_job(
            job_id,
            status="done",
            output_key=output_key,
            succeeded=succeeded,
            failed=failed,
            needs_review=needs_review,
            completed_at=datetime.now(UTC).isoformat(),
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Batch job %s failed", job_id)
        update_job(
            job_id,
            status="failed",
            error=str(exc)[:2000],
            completed_at=datetime.now(UTC).isoformat(),
        )


async def batch_upload(request: Request) -> JSONResponse:
    """POST /v1/batch/upload — multipart CSV; returns job_id, async processing."""
    try:
        form = await request.form()
    except Exception as exc:
        return _json_error("invalid_form", str(exc))

    file = form.get("file")
    if file is None:
        return _json_error("missing_file", "Upload a CSV file using the form field 'file'")

    content = await file.read()
    if len(content) > MAX_BATCH_UPLOAD_BYTES:
        return _json_error("file_too_large", "Maximum file size is 5MB")

    try:
        text = content.decode("utf-8")
        items = parse_upload_csv(text)
    except UnicodeDecodeError:
        return _json_error("invalid_encoding", "File must be UTF-8")
    except ValueError as exc:
        return _json_error("parse_error", str(exc))

    limit = batch_max_items()
    if not items:
        return _json_error("empty_file", "No valid rows found (need product, origin, destination).")
    if len(items) > limit:
        return _json_error(
            "too_many_rows",
            f"Maximum {limit} rows per batch. Your file has {len(items)}.",
            status=413,
        )

    job_id = create_job()
    input_key = batch_store_upload(content, "input.csv", job_id)
    update_job(job_id, input_key=input_key, total=len(items))

    background = BackgroundTasks()
    background.add_task(_run_batch_job, job_id, items)
    return JSONResponse(
        {
            "ok": True,
            "job_id": job_id,
            "status": "queued",
            "total_rows": len(items),
            "message": "Batch job queued. Poll GET /v1/batch/jobs/{job_id} for status.",
        },
        background=background,
    )


async def batch_job_status(request: Request) -> JSONResponse:
    """GET /v1/batch/jobs/{job_id} — status and optional download path."""
    job_id = request.path_params["job_id"]
    job = get_job(job_id)
    if not job:
        return _json_error("job_not_found", "Job not found", status=404)

    payload: dict[str, Any] = {
        "ok": True,
        "job_id": job_id,
        "status": job["status"],
        "total": job["total"],
        "succeeded": job["succeeded"],
        "failed": job["failed"],
        "needs_review": job["needs_review"],
        "created_at": job["created_at"],
        "completed_at": job["completed_at"],
    }
    if job["status"] == "done":
        dl = f"/v1/batch/jobs/{job_id}/download"
        payload["download_path"] = dl
        payload["download_url"] = dl
    if job["status"] == "failed":
        payload["error"] = job["error"]
    return JSONResponse(payload)


async def batch_job_download(request: Request) -> Response | JSONResponse:
    """GET /v1/batch/jobs/{job_id}/download — results CSV."""
    job_id = request.path_params["job_id"]
    job = get_job(job_id)
    if not job or job["status"] != "done" or not job.get("output_key"):
        return _json_error("not_ready", "Job not complete or no output", status=404)

    try:
        body = batch_store_download(job["output_key"])
    except Exception as exc:
        logger.exception("Batch download failed for %s", job_id)
        return _json_error("download_error", str(exc), status=500)

    return Response(
        body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="vanik_batch_{job_id}.csv"'},
    )


async def health(request: Request) -> JSONResponse:
    _ = request
    return JSONResponse(build_health_snapshot())


routes = [
    Route("/sessions", create_session, methods=["POST"]),
    Route("/sessions/{session_id}", get_session, methods=["GET"]),
    Route("/sessions/{session_id}/msg", post_session_message, methods=["POST"]),
    Route("/sessions/{session_id}/resume", resume_session, methods=["POST"]),
    Route("/sessions/{session_id}", close_session, methods=["DELETE"]),
    Route("/sessions/{session_id}/sse", stream_events, methods=["GET"]),
    Route("/anchors", list_anchor_records, methods=["GET"]),
    Route("/anchors/{anchor_id}", patch_anchor, methods=["PATCH"]),
    Route("/anchors/{anchor_id}", delete_anchor_record, methods=["DELETE"]),
    Route("/v1/query", api_query, methods=["POST"]),
    Route("/v1/batch", api_batch, methods=["POST"]),
    Route("/v1/batch/upload", batch_upload, methods=["POST"]),
    Route("/v1/batch/jobs/{job_id}", batch_job_status, methods=["GET"]),
    Route("/v1/batch/jobs/{job_id}/download", batch_job_download, methods=["GET"]),
    Route("/health", health, methods=["GET"]),
]

app = Starlette(
    debug=False,
    routes=routes,
    middleware=[
        Middleware(
            CORSMiddleware,
            allow_origins=CORS_ORIGINS,
            allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["*"],
            expose_headers=["*"],
        ),
    ],
)


def main() -> None:
    import uvicorn

    host = os.getenv("VANIK_HOST", "127.0.0.1")
    port = int(os.getenv("VANIK_PORT", "8000"))
    uvicorn.run("agent.session_gw:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
