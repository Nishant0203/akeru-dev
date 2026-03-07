"""SQLite storage helpers for vanik_docs."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from mcp_servers.vanik_docs.config import settings


def _connect() -> sqlite3.Connection:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create required tables and indexes."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tariff_rows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_type TEXT NOT NULL,
                hs_code TEXT NOT NULL,
                description TEXT,
                bcd_rate_pct REAL,
                unit TEXT,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tariff_rows_doc_hs ON tariff_rows(doc_type, hs_code)")


def reset_doc_type(doc_type: str) -> None:
    """Delete existing rows for a document type before fresh ingest."""
    with _connect() as conn:
        conn.execute("DELETE FROM tariff_rows WHERE doc_type = ?", (doc_type,))


def insert_tariff_rows(rows: list[dict[str, Any]], doc_type: str = "cbic") -> int:
    """Insert extracted rows into SQLite and return inserted count."""
    if doc_type not in {"cbic", "taric"}:
        raise ValueError("doc_type must be 'cbic' or 'taric'")

    if not rows:
        return 0

    normalized: list[tuple[Any, ...]] = []
    for row in rows:
        hs_code = str(row.get("hs_code", "")).strip()
        if not hs_code:
            continue
        description = row.get("description")
        rate = row.get("bcd_rate_pct")
        try:
            bcd_rate_pct = float(rate) if rate is not None else None
        except (ValueError, TypeError):
            bcd_rate_pct = None
        unit = row.get("unit")
        notes = row.get("notes")
        normalized.append((doc_type, hs_code, description, bcd_rate_pct, unit, notes))

    if not normalized:
        return 0

    with _connect() as conn:
        conn.executemany(
            """
            INSERT INTO tariff_rows (doc_type, hs_code, description, bcd_rate_pct, unit, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            normalized,
        )
    return len(normalized)


def lookup_hs(hs_code: str, doc_type: str = "cbic") -> list[dict[str, Any]]:
    """Lookup rows by exact HS code and doc type."""
    if doc_type not in {"cbic", "taric"}:
        raise ValueError("doc_type must be 'cbic' or 'taric'")

    code = str(hs_code).strip()
    if not code:
        return []

    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT doc_type, hs_code, description, bcd_rate_pct, unit, notes, created_at
            FROM tariff_rows
            WHERE doc_type = ? AND hs_code = ?
            ORDER BY id DESC
            """,
            (doc_type, code),
        ).fetchall()

    return [dict(r) for r in rows]


def db_info() -> dict[str, Any]:
    """Return DB metadata useful for diagnostics."""
    with _connect() as conn:
        count = conn.execute("SELECT COUNT(1) FROM tariff_rows").fetchone()[0]
    return {"db_path": str(settings.db_path), "row_count": int(count)}


# Ensure DB exists on module import for tool calls.
init_db()
