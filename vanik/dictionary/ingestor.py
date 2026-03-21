"""Generic dictionary ingestion into a dedicated SQLite + FTS5 index."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

log = logging.getLogger("vanik.dictionary")

DictionaryType = Literal[
    "product",
    "entity",
    "grade",
    "business_unit",
]


@dataclass
class DictionaryEntry:
    canonical: str
    dict_type: DictionaryType
    aliases: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class DictionaryIngestor:
    """
    Load external dictionaries (CSV, JSON, or in-memory entries) into DictionaryIndex storage.
    Each ingest for a dict_type replaces existing rows for that type atomically (per connection).
    """

    def __init__(self, index_path: str | Path) -> None:
        self.index_path = str(index_path)
        Path(self.index_path).parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with sqlite3_conn(self.index_path) as c:
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS dictionary_entries (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    canonical     TEXT    NOT NULL,
                    dict_type     TEXT    NOT NULL,
                    metadata_json TEXT    DEFAULT '{}',
                    created_at    TEXT,
                    batch_id      TEXT
                );

                CREATE TABLE IF NOT EXISTS dictionary_aliases (
                    alias         TEXT NOT NULL,
                    canonical     TEXT NOT NULL,
                    dict_type     TEXT NOT NULL,
                    batch_id      TEXT,
                    PRIMARY KEY (alias, dict_type)
                );

                CREATE TABLE IF NOT EXISTS ingest_batches (
                    batch_id      TEXT PRIMARY KEY,
                    dict_type     TEXT,
                    source_hash   TEXT,
                    entry_count   INTEGER,
                    ingested_at   TEXT,
                    source_name   TEXT
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS dictionary_fts
                USING fts5(
                    canonical,
                    aliases_concat,
                    dict_type UNINDEXED,
                    batch_id UNINDEXED,
                    tokenize = "porter ascii"
                );
                """
            )

    def ingest_csv(
        self,
        path: str | Path,
        dict_type: DictionaryType,
        *,
        canonical_col: str = "canonical",
        aliases_col: str = "aliases",
        metadata_cols: list[str] | None = None,
        source_name: str | None = None,
    ) -> str:
        content = Path(path).read_bytes()
        text = content.decode("utf-8-sig")
        entries: list[DictionaryEntry] = []
        for row in csv.DictReader(io.StringIO(text)):
            raw_aliases = row.get(aliases_col) or ""
            aliases = [a.strip() for a in raw_aliases.split(",") if a.strip()]
            metadata: dict = {}
            for col in metadata_cols or []:
                if col in row and row[col]:
                    metadata[col] = row[col]
            canon = (row.get(canonical_col) or "").strip()
            if not canon:
                continue
            entries.append(
                DictionaryEntry(
                    canonical=canon,
                    dict_type=dict_type,
                    aliases=aliases,
                    metadata=metadata,
                )
            )
        return self._load(entries, dict_type, content, source_name or str(path))

    def ingest_json(
        self,
        path: str | Path,
        dict_type: DictionaryType,
        source_name: str | None = None,
    ) -> str:
        content = Path(path).read_bytes()
        raw = json.loads(content.decode("utf-8-sig"))
        if not isinstance(raw, list):
            raise ValueError("JSON dictionary must be a list of objects")
        entries: list[DictionaryEntry] = []
        for r in raw:
            if not isinstance(r, dict):
                continue
            canon = str(r.get("canonical", "")).strip()
            if not canon:
                continue
            aliases = r.get("aliases") or []
            if not isinstance(aliases, list):
                aliases = []
            meta = {k: v for k, v in r.items() if k not in ("canonical", "aliases")}
            entries.append(
                DictionaryEntry(
                    canonical=canon,
                    dict_type=dict_type,
                    aliases=[str(a).strip() for a in aliases if str(a).strip()],
                    metadata=meta,
                )
            )
        return self._load(entries, dict_type, content, source_name or str(path))

    def ingest_entries(
        self,
        entries: list[DictionaryEntry],
        dict_type: DictionaryType,
        source_name: str = "programmatic",
    ) -> str:
        content = json.dumps([{"canonical": e.canonical} for e in entries]).encode()
        return self._load(entries, dict_type, content, source_name)

    def _load(
        self,
        entries: list[DictionaryEntry],
        dict_type: DictionaryType,
        source_bytes: bytes,
        source_name: str,
    ) -> str:
        source_hash = hashlib.md5(source_bytes).hexdigest()[:8]
        batch_id = f"{dict_type}_{source_hash}_{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}"
        ingested_at = datetime.now(UTC).isoformat()

        with sqlite3_conn(self.index_path) as c:
            c.execute("DELETE FROM dictionary_fts WHERE dict_type = ?", (dict_type,))
            c.execute("DELETE FROM dictionary_aliases WHERE dict_type = ?", (dict_type,))
            c.execute("DELETE FROM dictionary_entries WHERE dict_type = ?", (dict_type,))

            count = 0
            for entry in entries:
                if not entry.canonical.strip():
                    continue
                count += 1
                c.execute(
                    """
                    INSERT INTO dictionary_entries
                        (canonical, dict_type, metadata_json, created_at, batch_id)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        entry.canonical,
                        entry.dict_type,
                        json.dumps(entry.metadata),
                        ingested_at,
                        batch_id,
                    ),
                )
                for alias in entry.aliases:
                    a = alias.strip()
                    if not a:
                        continue
                    c.execute(
                        """
                        INSERT OR REPLACE INTO dictionary_aliases
                            (alias, canonical, dict_type, batch_id)
                        VALUES (?, ?, ?, ?)
                        """,
                        (a.lower(), entry.canonical, dict_type, batch_id),
                    )

                aliases_concat = " ".join(entry.aliases)
                c.execute(
                    """
                    INSERT INTO dictionary_fts
                        (canonical, aliases_concat, dict_type, batch_id)
                    VALUES (?, ?, ?, ?)
                    """,
                    (entry.canonical, aliases_concat, dict_type, batch_id),
                )

            c.execute(
                """
                INSERT INTO ingest_batches
                    (batch_id, dict_type, source_hash, entry_count, ingested_at, source_name)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (batch_id, dict_type, source_hash, count, ingested_at, source_name),
            )

        log.info(
            "[dictionary] Ingested %s entries type=%s batch=%s source=%s",
            count,
            dict_type,
            batch_id,
            source_name,
        )
        return batch_id


def sqlite3_conn(path: str):
    import sqlite3

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn
