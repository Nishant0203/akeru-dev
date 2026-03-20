"""Strip sensitive or noisy tokens before NER / LLM (InformationFilter-lite)."""

from __future__ import annotations

import re

# PO / invoice style references (architecture Section 3 — InformationFilter)
_PO_LIKE = re.compile(
    r"\b(?:PO|INV|INVOICE|SO|ORDER)[\s#:.-]*[A-Z0-9][A-Z0-9/-]{3,}\b",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
# Long digit runs that look like phone / fax (not HS codes — those are 6–10 digit word boundaries)
_PHONEISH = re.compile(r"\b\+?\d[\d\s().-]{8,}\d\b")


def sanitise(raw: str) -> str:
    """Return a cleaned query safe to log and send to extractors / Haiku."""
    text = (raw or "").strip()
    if not text:
        return ""
    text = _EMAIL.sub("[redacted-email]", text)
    text = _PHONEISH.sub("[redacted-phone]", text)
    text = _PO_LIKE.sub("[ref]", text)
    return re.sub(r"\s+", " ", text).strip()
