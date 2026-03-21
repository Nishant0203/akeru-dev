"""Query interface for ingested dictionaries (resolution layer uses this, not tariff DB)."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from rapidfuzz import fuzz, process

from dictionary.ingestor import DictionaryType

# FTS5 special chars — strip or replace to avoid query syntax errors
_FTS_SPECIAL = re.compile(r'["*]')


@dataclass
class LookupResult:
    found: bool
    canonical: str | None = None
    dict_type: str | None = None
    metadata: dict = field(default_factory=dict)
    match_method: str | None = None
    score: float = 1.0


def _fts_phrase(term: str) -> str:
    """Build a safe FTS5 phrase query (double-quoted)."""
    t = _FTS_SPECIAL.sub(" ", (term or "").strip())
    t = re.sub(r"\s+", " ", t).strip()
    if not t:
        return ""
    escaped = t.replace('"', '""')
    return f'"{escaped}"'


class DictionaryIndex:
    """Stateless queries against the dictionary SQLite + FTS5 file."""

    def __init__(self, index_path: str | Path) -> None:
        self.index_path = str(index_path)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.index_path)
        conn.row_factory = sqlite3.Row
        return conn

    def lookup(
        self,
        term: str,
        dict_type: DictionaryType,
        *,
        fuzzy_threshold: int = 85,
    ) -> LookupResult:
        normalised = (term or "").lower().strip()
        if not normalised:
            return LookupResult(found=False)

        with self._conn() as c:
            row = c.execute(
                """
                SELECT canonical, dict_type, metadata_json
                FROM dictionary_entries
                WHERE lower(canonical) = ? AND dict_type = ?
                """,
                (normalised, dict_type),
            ).fetchone()
            if row:
                return LookupResult(
                    found=True,
                    canonical=row["canonical"],
                    dict_type=row["dict_type"],
                    metadata=json.loads(row["metadata_json"] or "{}"),
                    match_method="exact",
                )

            row = c.execute(
                """
                SELECT a.canonical, a.dict_type, e.metadata_json
                FROM dictionary_aliases a
                JOIN dictionary_entries e
                  ON lower(e.canonical) = lower(a.canonical)
                 AND e.dict_type = a.dict_type
                WHERE a.alias = ? AND a.dict_type = ?
                """,
                (normalised, dict_type),
            ).fetchone()
            if row:
                return LookupResult(
                    found=True,
                    canonical=row["canonical"],
                    dict_type=row["dict_type"],
                    metadata=json.loads(row["metadata_json"] or "{}"),
                    match_method="alias",
                )

            fts_q = _fts_phrase(term)
            if fts_q:
                rows = c.execute(
                    """
                    SELECT canonical, dict_type
                    FROM dictionary_fts
                    WHERE dictionary_fts MATCH ? AND dict_type = ?
                    LIMIT 5
                    """,
                    (fts_q, dict_type),
                ).fetchall()
                if rows:
                    canon = rows[0]["canonical"]
                    return LookupResult(
                        found=True,
                        canonical=canon,
                        dict_type=rows[0]["dict_type"],
                        metadata=self._get_metadata(c, canon, dict_type),
                        match_method="fts",
                    )

            all_canonicals = [
                r["canonical"]
                for r in c.execute(
                    "SELECT canonical FROM dictionary_entries WHERE dict_type = ?",
                    (dict_type,),
                ).fetchall()
            ]

        if all_canonicals:
            lowered = [x.lower() for x in all_canonicals]
            result = process.extractOne(
                normalised,
                lowered,
                scorer=fuzz.token_sort_ratio,
                score_cutoff=fuzzy_threshold,
            )
            if result:
                idx = lowered.index(result[0])
                matched = all_canonicals[idx]
                with self._conn() as c2:
                    meta = self._get_metadata(c2, matched, dict_type)
                return LookupResult(
                    found=True,
                    canonical=matched,
                    dict_type=dict_type,
                    metadata=meta,
                    match_method="fuzzy",
                    score=result[1] / 100.0,
                )

        return LookupResult(found=False)

    def _get_metadata(self, conn: sqlite3.Connection, canonical: str, dict_type: str) -> dict:
        row = conn.execute(
            """
            SELECT metadata_json FROM dictionary_entries
            WHERE canonical = ? AND dict_type = ?
            """,
            (canonical, dict_type),
        ).fetchone()
        return json.loads(row["metadata_json"]) if row else {}

    def get_metadata(self, canonical: str, dict_type: DictionaryType) -> dict:
        with self._conn() as c:
            return self._get_metadata(c, canonical, dict_type)

    def list_batches(self, dict_type: DictionaryType | None = None) -> list[dict]:
        with self._conn() as c:
            query = "SELECT * FROM ingest_batches"
            params: tuple = ()
            if dict_type:
                query += " WHERE dict_type = ?"
                params = (dict_type,)
            query += " ORDER BY ingested_at DESC"
            return [dict(r) for r in c.execute(query, params).fetchall()]

    def count_entries(self, dict_type: DictionaryType) -> int:
        with self._conn() as c:
            row = c.execute(
                "SELECT COUNT(*) AS n FROM dictionary_entries WHERE dict_type = ?",
                (dict_type,),
            ).fetchone()
            return int(row["n"]) if row else 0
