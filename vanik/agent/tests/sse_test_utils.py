"""Shared SSE test utilities for gateway tests.

Diagnosis preserved:
- This solves a test harness deadlock, not an endpoint bug.
- The SSE endpoint is intentionally persistent and should not be changed for test convenience.
- In-process Starlette TestClient streaming can block indefinitely on persistent streams.
- The fix is to consume incrementally with a timeout in a daemon thread, while using
  a dedicated loopback HTTP server transport so events are actually streamable.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from typing import Any

import httpx
import pytest
import uvicorn
from starlette.testclient import TestClient


def _start_loopback_server(app: Any) -> tuple[str, uvicorn.Server, threading.Thread]:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    for _ in range(100):
        if server.started:
            break
        time.sleep(0.02)

    if not server.started:
        raise RuntimeError("Failed to start loopback server for SSE test consumption")

    return f"http://127.0.0.1:{port}", server, thread


def _stop_loopback_server(server: uvicorn.Server, thread: threading.Thread) -> None:
    server.should_exit = True
    thread.join(timeout=2.0)


def collect_sse_events(
    *,
    client: TestClient,
    url: str,
    stop_type: str,
    timeout_seconds: float = 5.0,
) -> list[dict[str, Any]]:
    """Incrementally consume SSE events until `stop_type` appears or timeout fires."""
    events: list[dict[str, Any]] = []
    stop = threading.Event()
    reader_error: Exception | None = None

    base_url, server, server_thread = _start_loopback_server(client.app)

    def _reader() -> None:
        nonlocal reader_error
        timeout = httpx.Timeout(timeout_seconds + 0.5, read=timeout_seconds + 0.5)
        try:
            with httpx.Client(timeout=timeout) as http:
                with http.stream("GET", f"{base_url}{url}") as response:
                    for line in response.iter_lines():
                        if stop.is_set():
                            break
                        if not line.startswith("data:"):
                            continue
                        event = json.loads(line[len("data:") :].strip())
                        events.append(event)
                        if event.get("type") == stop_type:
                            break
        except Exception as exc:  # pragma: no cover - exercised via failure diagnostics
            reader_error = exc

    try:
        thread = threading.Thread(target=_reader, daemon=True)
        thread.start()
        thread.join(timeout=timeout_seconds)

        if thread.is_alive():
            stop.set()
            types = [str(event.get("type")) for event in events]
            pytest.fail(
                f"SSE stream did not emit {stop_type!r} within {timeout_seconds} seconds. "
                f"Received event types: {types}"
            )

        if reader_error is not None:
            types = [str(event.get("type")) for event in events]
            pytest.fail(
                f"SSE reader failed before receiving {stop_type!r}: {reader_error}. "
                f"Received event types: {types}"
            )

        if not any(event.get("type") == stop_type for event in events):
            types = [str(event.get("type")) for event in events]
            pytest.fail(
                f"SSE stream closed before {stop_type!r} was received. "
                f"Received event types: {types}"
            )

        return events
    finally:
        _stop_loopback_server(server, server_thread)
