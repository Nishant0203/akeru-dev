"""SQLite job metadata for async batch uploads."""

from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_DB = Path(
    os.getenv(
        "VANIK_BATCH_DB",
        str(Path(__file__).resolve().parent.parent / "data" / "batch_jobs.db"),
    )
)


def _conn() -> sqlite3.Connection:
    _DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(_DB))
    c.row_factory = sqlite3.Row
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS batch_jobs (
            job_id        TEXT PRIMARY KEY,
            status        TEXT NOT NULL,
            input_key     TEXT,
            output_key    TEXT,
            total         INTEGER DEFAULT 0,
            succeeded     INTEGER DEFAULT 0,
            failed        INTEGER DEFAULT 0,
            needs_review  INTEGER DEFAULT 0,
            created_at    TEXT,
            completed_at  TEXT,
            error         TEXT
        )
        """
    )
    return c


def create_job() -> str:
    job_id = str(uuid.uuid4())
    with _conn() as c:
        c.execute(
            "INSERT INTO batch_jobs (job_id, status, created_at) VALUES (?,?,?)",
            (job_id, "queued", datetime.now(UTC).isoformat()),
        )
        c.commit()
    return job_id


def get_job(job_id: str) -> dict[str, Any] | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM batch_jobs WHERE job_id=?", (job_id,)).fetchone()
    return dict(row) if row else None


def update_job(job_id: str, **kwargs: Any) -> None:
    if not kwargs:
        return
    keys = list(kwargs.keys())
    sets = ", ".join(f"{k}=?" for k in keys)
    vals = [kwargs[k] for k in keys] + [job_id]
    with _conn() as c:
        c.execute(f"UPDATE batch_jobs SET {sets} WHERE job_id=?", vals)
        c.commit()
