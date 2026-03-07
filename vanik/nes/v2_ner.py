"""Manifest Search v2: encoder NER stub."""

from __future__ import annotations

import re

HS_PATTERN = re.compile(r"\b\d{6}(?:\d{2})?(?:\d{2})?\b")

ORIGIN_PATTERNS: dict[str, str] = {
    r"\bindia\b": "IN",
    r"\bchina\b": "CN",
    r"\bgermany\b": "DE",
}


def _origin_candidates(text: str) -> list[str]:
    lower = text.lower()
    found: list[str] = []
    for pattern, code in ORIGIN_PATTERNS.items():
        if re.search(pattern, lower):
            found.append(code)
    return found


def extract_v2(raw_query: str) -> dict:
    """Fast local extractor stub that represents fine-tuned NER behaviour."""
    text = raw_query.strip()
    hs_match = HS_PATTERN.search(text)
    origin_candidates = _origin_candidates(text)

    origin = origin_candidates[0] if len(origin_candidates) == 1 else None
    destination = "GB" if "uk" in text.lower() or "gb" in text.lower() else None

    return {
        "product_terms": [text] if text else [],
        "hs_code_provided": hs_match.group(0) if hs_match else None,
        "origin": origin,
        "_origin_candidates": origin_candidates,
        "destination": destination,
        "quantity": None,
        "unit_value_usd": None,
    }
