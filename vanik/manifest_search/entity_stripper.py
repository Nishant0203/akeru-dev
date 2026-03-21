"""Strip unstructured proper nouns and product grades before v2/v3 extraction."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_ENTITY_PATTERNS: list[re.Pattern[str]] = []
_LOADED = False

# Material / internal grades (S355, P265GH). Avoid matching "HS" + digits (tariff headings).
_GRADE_PATTERN = re.compile(
    r"\b(?!HS\b)[A-Z]{1,4}[\s-]?\d{2,4}[A-Z0-9\-]*\b",
    re.IGNORECASE,
)

# Aluminium-style grades often digit-led
_ALLOY_GRADE_PATTERN = re.compile(r"\b\d{4}[\s-]?[AT]\d\b", re.IGNORECASE)

_LEGAL_SUFFIXES = re.compile(
    r"\b(?:Ltd|Limited|Inc|GmbH|Pvt|Private|Corp|Corporation|"
    r"Holdings|Group|Industries|Enterprises|International)\b\.?",
    re.IGNORECASE,
)


def _default_registry_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "entity_registry.yaml"


def load_entity_patterns(registry_path: str | Path | None = None) -> None:
    """Load regex patterns from entity registry (idempotent)."""
    global _ENTITY_PATTERNS, _LOADED
    path = Path(registry_path) if registry_path else _default_registry_path()
    patterns: list[re.Pattern[str]] = []
    if path.is_file():
        try:
            import yaml  # noqa: PLC0415

            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            entities = (data or {}).get("entities") or {}
            for _key, entry in entities.items():
                if not isinstance(entry, dict):
                    continue
                canonical = entry.get("canonical")
                names: list[str] = []
                if isinstance(canonical, str) and canonical.strip():
                    names.append(canonical.strip())
                variants = entry.get("variants") or []
                if isinstance(variants, list):
                    names.extend(str(v).strip() for v in variants if str(v).strip())
                for name in names:
                    escaped = re.escape(name)
                    patterns.append(re.compile(r"\b" + escaped + r"\b", re.IGNORECASE))
        except Exception as exc:
            logger.warning("entity_stripper: could not load %s: %s", path, exc)
    _ENTITY_PATTERNS = patterns
    _LOADED = True


def _ensure_loaded() -> None:
    if not _LOADED:
        load_entity_patterns()


def strip_entities(query: str) -> tuple[str, list[dict[str, Any]]]:
    """
    Remove registry entity names, typical product grades, and stray legal suffixes.
    Returns (cleaned_query, strip_log). Complements nes.sanitiser (structured patterns).
    """
    _ensure_loaded()
    result = (query or "").strip()
    strip_log: list[dict[str, Any]] = []

    for pattern in _ENTITY_PATTERNS:
        for m in pattern.finditer(result):
            strip_log.append({"type": "entity_name", "match": m.group(0)[:200]})
        result = pattern.sub(" ", result)

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
    """Append one JSON line if VANIK_SANITISATION_AUDIT_LOG is set (path to .jsonl)."""
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
