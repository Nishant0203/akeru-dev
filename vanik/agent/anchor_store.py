"""SQLite-backed task anchor store."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DB_PATH = Path(os.getenv("VANIK_ANCHORS_DB", "/tmp/vanik_anchors.db")).expanduser().resolve()


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS anchors (
                anchor_id TEXT PRIMARY KEY,
                user_id TEXT,
                label TEXT,
                hs_code TEXT,
                description TEXT,
                corridor TEXT,
                prior_query TEXT,
                rates_json TEXT,
                completed_at TEXT,
                query_id TEXT,
                session_id TEXT,
                schema_version INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_anchors_user_id ON anchors(user_id, completed_at DESC)")


def _row_to_anchor(row: sqlite3.Row) -> dict[str, Any]:
    payload = dict(row)
    rates_json = payload.get("rates_json")
    if rates_json:
        try:
            payload["rates_summary"] = json.loads(rates_json)
        except json.JSONDecodeError:
            payload["rates_summary"] = {}
    else:
        payload["rates_summary"] = {}
    payload.pop("rates_json", None)
    return payload


def create_anchor(
    *,
    user_id: str | None,
    label: str,
    hs_code: str,
    description: str,
    corridor: str,
    prior_query: str,
    rates_summary: dict[str, Any],
    query_id: str,
    session_id: str,
) -> dict[str, Any]:
    init_db()
    anchor_id = f"anc_{hs_code}_{uuid.uuid4().hex[:8]}"
    completed_at = datetime.now(UTC).isoformat()

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO anchors (
                anchor_id, user_id, label, hs_code, description,
                corridor, prior_query, rates_json, completed_at,
                query_id, session_id, schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                anchor_id,
                user_id,
                label,
                hs_code,
                description,
                corridor,
                prior_query,
                json.dumps(rates_summary),
                completed_at,
                query_id,
                session_id,
            ),
        )

    return {
        "anchor_id": anchor_id,
        "user_id": user_id,
        "label": label,
        "hs_code": hs_code,
        "description": description,
        "corridor": corridor,
        "prior_query": prior_query,
        "rates_summary": rates_summary,
        "completed_at": completed_at,
        "query_id": query_id,
        "session_id": session_id,
        "schema_version": 1,
    }


def list_anchors(user_id: str | None = None) -> list[dict[str, Any]]:
    init_db()
    with _connect() as conn:
        if user_id:
            rows = conn.execute(
                """
                SELECT * FROM anchors WHERE user_id = ?
                ORDER BY completed_at DESC
                """,
                (user_id,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM anchors ORDER BY completed_at DESC").fetchall()
    return [_row_to_anchor(row) for row in rows]


def get_anchor(anchor_id: str) -> dict[str, Any] | None:
    init_db()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM anchors WHERE anchor_id = ?", (anchor_id,)).fetchone()
    return _row_to_anchor(row) if row else None


def rename_anchor(anchor_id: str, label: str) -> dict[str, Any] | None:
    init_db()
    with _connect() as conn:
        conn.execute("UPDATE anchors SET label = ? WHERE anchor_id = ?", (label, anchor_id))
    return get_anchor(anchor_id)


def delete_anchor(anchor_id: str) -> bool:
    init_db()
    with _connect() as conn:
        cur = conn.execute("DELETE FROM anchors WHERE anchor_id = ?", (anchor_id,))
    return cur.rowcount > 0


def info() -> dict[str, Any]:
    init_db()
    with _connect() as conn:
        count = conn.execute("SELECT COUNT(1) FROM anchors").fetchone()[0]
    return {"db_path": str(DB_PATH), "count": int(count)}


init_db()
