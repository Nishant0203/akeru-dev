"""Manifest Search v2: encoder NER stub."""

from __future__ import annotations

import re

HS_PATTERN = re.compile(r"\b\d{6}(?:\d{2})?(?:\d{2})?\b")


def extract_v2(raw_query: str) -> dict:
    """Fast local extractor stub that represents fine-tuned NER behaviour."""
    text = raw_query.strip()
    hs_match = HS_PATTERN.search(text)

    origin = "IN" if "india" in text.lower() else None
    destination = "GB" if "uk" in text.lower() or "gb" in text.lower() else None

    return {
        "product_terms": [text] if text else [],
        "hs_code_provided": hs_match.group(0) if hs_match else None,
        "origin": origin,
        "destination": destination,
        "quantity": None,
        "unit_value_usd": None,
    }
