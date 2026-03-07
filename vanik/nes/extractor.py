"""Manifest Search (MS) compatibility wrapper."""

from __future__ import annotations

import re

HS_PATTERN = re.compile(r"\b\d{6}(?:\d{2})?(?:\d{2})?\b")


def extract_entities(user_query: str) -> dict:
    """Backward-compatible alias for Manifest Search extraction."""
    text = user_query.strip()
    hs_match = HS_PATTERN.search(text)

    origin = "IN" if "india" in text.lower() or " in " in text.lower() else None
    destination = "GB" if "uk" in text.lower() or "gb" in text.lower() else None

    return {
        "product_terms": [text],
        "hs_code_provided": hs_match.group(0) if hs_match else None,
        "origin": origin,
        "destination": destination,
        "quantity": None,
        "unit_value_usd": None,
    }
