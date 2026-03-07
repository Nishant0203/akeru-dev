"""Session Gateway HTTP service for Vanik chat/API modes."""

from __future__ import annotations

import asyncio
import json
import os
import threading
from queue import Empty
from typing import Any
from uuid import uuid4

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from agent.anchor_store import create_anchor, delete_anchor, get_anchor, list_anchors, rename_anchor
from agent.health import build_health_snapshot
from agent.query_log import append_query, deterministic_query_id
from agent.session_store import SessionState, store
from agent.vanik_agent import vanik_agent


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
    session.event_queue.put(event)


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
                "message": result.get("message", "Select one option or provide a 10-digit code."),
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


def _spawn_agent_job(
    *,
    session: SessionState,
    user_query: str,
    gate_selection: str | None,
    precomputed_entities: dict[str, Any] | None = None,
    gate_options: list[dict[str, Any]] | None = None,
) -> None:
    def _runner() -> None:
        asyncio.run(
            _run_agent_job(
                session=session,
                user_query=user_query,
                gate_selection=gate_selection,
                precomputed_entities=precomputed_entities,
                gate_options=gate_options,
            )
        )

    threading.Thread(target=_runner, daemon=True).start()


async def create_session(request: Request) -> JSONResponse:
    seed: dict[str, Any] = {}
    if request.headers.get("content-type", "").startswith("application/json"):
        try:
            seed = await request.json()
        except json.JSONDecodeError:
            seed = {}
    session = store.create(seed=seed)
    return JSONResponse({"session_id": session.session_id, "created_at": session.created_at})


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

    if session.pending_gate:
        pending = dict(session.pending_gate)
        _spawn_agent_job(
            session=session,
            user_query=pending.get("query", ""),
            gate_selection=content,
            precomputed_entities=pending.get("entities", {}),
            gate_options=pending.get("options", []),
        )
    else:
        _spawn_agent_job(
            session=session,
            user_query=content,
            gate_selection=None,
        )
    return JSONResponse({"ok": True, "accepted": True}, status_code=202)


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
                    event = await asyncio.to_thread(session.event_queue.get, True, 15)
                except Empty:
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
    Route("/health", health, methods=["GET"]),
]

app = Starlette(debug=False, routes=routes)


def main() -> None:
    import uvicorn

    host = os.getenv("VANIK_HOST", "127.0.0.1")
    port = int(os.getenv("VANIK_PORT", "8000"))
    uvicorn.run("agent.session_gw:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
