"""SQLite job metadata + optional Lane B row references."""

from __future__ import annotations

import json
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
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS batch_row_refs (
            job_id     TEXT NOT NULL,
            row_index  INTEGER NOT NULL,
            ref_json   TEXT NOT NULL,
            PRIMARY KEY (job_id, row_index)
        )
        """
    )
    c.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_batch_row_refs_job
        ON batch_row_refs (job_id)
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


def save_lane_b_rows(job_id: str, items: list[dict[str, Any]]) -> None:
    """Persist Lane B ``reference`` payloads by row index."""
    with _conn() as c:
        for i, item in enumerate(items):
            ref = item.get("reference")
            if not ref:
                continue
            c.execute(
                """
                INSERT OR REPLACE INTO batch_row_refs (job_id, row_index, ref_json)
                VALUES (?,?,?)
                """,
                (job_id, i, json.dumps(ref, ensure_ascii=False)),
            )
        c.commit()


def load_lane_b_rows(job_id: str, n: int) -> list[dict[str, Any] | None]:
    """Return list length ``n`` with dict or None per row."""
    out: list[dict[str, Any] | None] = [None] * n
    with _conn() as c:
        rows = c.execute(
            "SELECT row_index, ref_json FROM batch_row_refs WHERE job_id=? ORDER BY row_index",
            (job_id,),
        ).fetchall()
    for r in rows:
        idx = int(r["row_index"])
        if 0 <= idx < n:
            try:
                out[idx] = json.loads(r["ref_json"])
            except json.JSONDecodeError:
                out[idx] = {}
    return out


def delete_lane_b_rows(job_id: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM batch_row_refs WHERE job_id=?", (job_id,))
        c.commit()


def mark_stale_processing_jobs_failed(
    reason: str = "Server restarted while job was processing; use admin batch retry or re-upload.",
) -> int:
    """Mark jobs left in ``processing`` as failed (startup cleanup after crash/deploy)."""
    now = datetime.now(UTC).isoformat()
    with _conn() as c:
        cur = c.execute(
            """
            UPDATE batch_jobs
            SET status = 'failed', error = ?, completed_at = ?
            WHERE status = 'processing'
            """,
            (reason, now),
        )
        c.commit()
        return int(cur.rowcount or 0)
