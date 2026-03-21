#!/usr/bin/env python3
"""
Build vanik/data/tariff_dictionary.txt from a tariff SQLite (e.g. VANIK_DOCS_DB).

Usage (from vanik/):
  VANIK_DOCS_DB=/path/to/docs.db python scripts/build_tariff_dictionary.py

Counts word frequencies from description-like columns and writes one token per line.
"""
from __future__ import annotations

import os
import re
import sqlite3
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_OUT = _ROOT / "data" / "tariff_dictionary.txt"

_TOKEN = re.compile(r"[A-Za-z]{3,}")


def main() -> None:
    db_path = (os.getenv("VANIK_DOCS_DB") or "").strip()
    if not db_path:
        print("Set VANIK_DOCS_DB to the vanik_docs SQLite path.")
        raise SystemExit(1)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    texts: list[str] = []
    for t in tables:
        try:
            rows = cur.execute(f"SELECT * FROM {t} LIMIT 50000").fetchall()
        except sqlite3.Error:
            continue
        for row in rows:
            for cell in row:
                if isinstance(cell, str) and len(cell) > 10:
                    texts.append(cell.lower())
    conn.close()

    ctr: Counter[str] = Counter()
    for blob in texts:
        for m in _TOKEN.finditer(blob):
            ctr[m.group(0).lower()] += 1

    top = [w for w, _ in ctr.most_common(20000)]
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    header = (
        f"# Generated from {db_path} — {len(top)} tokens. "
        "Do not edit by hand unless adding domain words.\n"
    )
    _OUT.write_text(header + "\n".join(top) + "\n", encoding="utf-8")
    print(f"Wrote {_OUT} ({len(top)} tokens)")


if __name__ == "__main__":
    main()
