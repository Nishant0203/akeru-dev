"""Append-only query log helpers."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LOG_PATH = Path(os.getenv("VANIK_QUERY_LOG", "/tmp/vanik_query_log.jsonl")).expanduser().resolve()


def deterministic_query_id(session_id: str, turn_number: int, content: str) -> str:
    digest = hashlib.sha1(f"{session_id}:{turn_number}:{content}".encode("utf-8")).hexdigest()
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return f"vanik_{stamp}_{digest[:10]}"


def append_query(record: dict[str, Any]) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(record)
    payload.setdefault("timestamp", datetime.now(UTC).isoformat())
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload) + "\n")


def info() -> dict[str, Any]:
    count = 0
    if LOG_PATH.exists():
        count = sum(1 for _ in LOG_PATH.open("r", encoding="utf-8"))
    return {"log_path": str(LOG_PATH), "entries": count}
