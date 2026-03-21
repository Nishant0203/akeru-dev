"""Strip sensitive or noisy tokens before NER / LLM (InformationFilter-lite)."""

from __future__ import annotations

import re

_PO_LIKE = re.compile(
    r"\b(?:PO|INV|INVOICE|SO|ORDER)[\s#:.-]*[A-Z0-9][A-Z0-9/-]{3,}\b",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_PHONEISH = re.compile(r"\b\+?\d[\d\s().-]{8,}\d\b")

_STRIP_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bP/?O\s*#?\s*[\w\-]+", re.I), "po_number"),
    (re.compile(r"USD\s*[\d,]+\.?\d*\s*/?\s*(unit|pc|kg|MT)", re.I), "unit_price"),
    (
        re.compile(r"\b(supplier|vendor|shipper|consignee)\s*:\s*\S+", re.I),
        "counterparty",
    ),
    (re.compile(r"\bP/?N\s*[\w\-]+", re.I), "part_number"),
    (re.compile(r"\b\d{5,}\s*(units?|pcs?|pieces?)\b", re.I), "quantity_ref"),
    (re.compile(r"\b[A-Z]{2,4}-\d{4,}-[A-Z0-9]+\b"), "internal_ref"),
]


def sanitise_with_log(raw_query: str) -> tuple[str, list[dict]]:
    """
    Strip sensitive fields before any external LLM call.
    Returns (sanitised_query, strip_log) for optional audit JSONL.
    """
    text = (raw_query or "").strip()
    strip_log: list[dict] = []

    if not text:
        return "", strip_log

    text = _EMAIL.sub("[redacted-email]", text)
    text = _PHONEISH.sub("[redacted-phone]", text)
    text = _PO_LIKE.sub("[ref]", text)

    for pattern, name in _STRIP_PATTERNS:
        for m in pattern.finditer(text):
            strip_log.append({"field": name, "match": m.group(0)[:200]})
        text = pattern.sub("[REDACTED]", text)

    text = re.sub(r"\s+", " ", text).strip()
    return text, strip_log


def sanitise(raw: str) -> str:
    """Return a cleaned query safe to log and send to extractors / Haiku."""
    out, _ = sanitise_with_log(raw)
    return out
