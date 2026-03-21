"""Strip dictionary-backed entities (and regex grades / legal suffixes) before v2/v3."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dictionary.dictionary_index import DictionaryIndex
from dictionary.ingestor import DictionaryIngestor

logger = logging.getLogger(__name__)

_INDEX: DictionaryIndex | None = None

_STRIP_TYPES: tuple[str, ...] = ("entity", "business_unit")

_GRADE_PATTERN = re.compile(
    r"\b(?!HS\b)[A-Z]{1,4}[\s-]?\d{2,4}[A-Z0-9\-]*\b",
    re.IGNORECASE,
)
_ALLOY_GRADE_PATTERN = re.compile(r"\b\d{4}[\s-]?[AT]\d\b", re.IGNORECASE)
_LEGAL_SUFFIXES = re.compile(
    r"\b(?:Ltd|Limited|Inc|GmbH|Pvt|Private|Corp|Corporation|"
    r"Holdings|Group|Industries|Enterprises|International)\b\.?",
    re.IGNORECASE,
)


def _default_db_path() -> Path:
    root = Path(__file__).resolve().parent.parent
    env = (os.getenv("VANIK_DICTIONARY_DB") or "").strip()
    return Path(env) if env else root / "var" / "dictionary.db"


def get_dictionary_index() -> DictionaryIndex:
    global _INDEX
    if _INDEX is None:
        p = _default_db_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        DictionaryIngestor(p)
        _INDEX = DictionaryIndex(str(p))
    return _INDEX


def dictionary_db_path_str() -> str:
    """Resolved path to dictionary.db (respects VANIK_DICTIONARY_DB)."""
    return str(_default_db_path())


def reset_dictionary_index_cache() -> None:
    """Test helper: clear lazy index singleton."""
    global _INDEX
    _INDEX = None


def strip_entities(query: str) -> tuple[str, list[dict[str, Any]]]:
    """
    Remove entity / business_unit phrases resolved via DictionaryIndex, then grades and legal suffixes.
    Returns (cleaned_query, strip_log).
    """
    index = get_dictionary_index()
    result = (query or "").strip()
    strip_log: list[dict[str, Any]] = []

    words = result.split()
    matched: set[str] = set()
    for n in (4, 3, 2, 1):
        for i in range(max(0, len(words) - n + 1)):
            phrase = " ".join(words[i : i + n])
            if not phrase.strip():
                continue
            for dt in _STRIP_TYPES:
                res = index.lookup(phrase, dt)  # type: ignore[arg-type]
                if res.found and phrase not in matched:
                    matched.add(phrase)
                    strip_log.append(
                        {
                            "type": dt,
                            "match": phrase[:200],
                            "canonical": res.canonical,
                            "method": res.match_method,
                        }
                    )
                    result = re.sub(re.escape(phrase), " ", result, flags=re.IGNORECASE)

    for pattern in (_GRADE_PATTERN, _ALLOY_GRADE_PATTERN):
        for m in pattern.finditer(result):
            strip_log.append({"type": "product_grade", "match": m.group(0)[:200]})
        result = pattern.sub(" ", result)

    for m in _LEGAL_SUFFIXES.finditer(result):
        strip_log.append({"type": "legal_suffix", "match": m.group(0)[:200]})
    result = _LEGAL_SUFFIXES.sub(" ", result)

    result = re.sub(r"\s{2,}", " ", result).strip()
    return result, strip_log


def append_sanitisation_audit(
    *,
    raw_query: str,
    sanitised: str,
    cleaned: str,
    events: list[dict[str, Any]],
) -> None:
    path = (os.getenv("VANIK_SANITISATION_AUDIT_LOG") or "").strip()
    if not path:
        return
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now(UTC).isoformat(),
            "raw_query": raw_query[:4000],
            "sanitised": sanitised[:4000],
            "cleaned": cleaned[:4000],
            "events": events,
        }
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.warning("sanitisation audit append failed: %s", exc)
