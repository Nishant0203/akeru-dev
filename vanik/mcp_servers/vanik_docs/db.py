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
        # FTS5 over tariff descriptions (content table = tariff_rows)
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS tariff_fts USING fts5(
                hs_code,
                description,
                content='tariff_rows',
                content_rowid='id'
            )
            """
        )


def reset_doc_type(doc_type: str) -> None:
    """Delete existing rows for a document type before fresh ingest."""
    with _connect() as conn:
        conn.execute("DELETE FROM tariff_rows WHERE doc_type = ?", (doc_type,))


def _rebuild_tariff_fts(conn: sqlite3.Connection) -> None:
    """Rebuild FTS index from tariff_rows (external content)."""
    try:
        conn.execute("INSERT INTO tariff_fts(tariff_fts) VALUES('rebuild')")
    except sqlite3.OperationalError:
        pass


def reset_and_insert(rows: list[dict[str, Any]], doc_type: str = "cbic") -> int:
    """Atomically replace all rows for doc_type and refresh FTS (single transaction)."""
    if doc_type not in {"cbic", "taric"}:
        raise ValueError("doc_type must be 'cbic' or 'taric'")

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

    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("DELETE FROM tariff_rows WHERE doc_type = ?", (doc_type,))
            if normalized:
                conn.executemany(
                    """
                    INSERT INTO tariff_rows (doc_type, hs_code, description, bcd_rate_pct, unit, notes)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    normalized,
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        _rebuild_tariff_fts(conn)

    return len(normalized)


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
        _rebuild_tariff_fts(conn)
    return len(normalized)


def search_tariff_rows_by_fts(term: str, limit: int = 10) -> list[dict[str, Any]]:
    """Ranked FTS search; returns [] if query is empty or FTS unavailable."""
    raw = (term or "").strip()
    if not raw:
        return []
    # Basic sanitisation for FTS5 MATCH: phrase search
    safe = raw.replace('"', "").replace("'", "")[:200]
    if not safe:
        return []
    match_expr = f"\"{safe}\""
    with _connect() as conn:
        try:
            rows = conn.execute(
                """
                SELECT t.doc_type, t.hs_code, t.description, t.bcd_rate_pct, t.unit, t.notes, t.created_at
                FROM tariff_fts
                JOIN tariff_rows t ON t.id = tariff_fts.rowid
                WHERE tariff_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (match_expr, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    return [dict(r) for r in rows]


def search_tariff_rows_by_description(term: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search tariff_rows by description LIKE %term%. Returns list of dicts with hs_code, description, etc."""
    t = f"%{term.strip()}%" if term else "%"
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT doc_type, hs_code, description, bcd_rate_pct, unit, notes, created_at
            FROM tariff_rows
            WHERE description LIKE ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (t, limit),
        ).fetchall()
    return [dict(r) for r in rows]


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
