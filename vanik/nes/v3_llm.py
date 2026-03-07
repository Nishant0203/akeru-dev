"""Manifest Search v3: LLM fallback stub."""

from __future__ import annotations


async def llm_extract(raw_query: str) -> dict:
    """Structured fallback extractor stub (Haiku/GPT-4o-mini in real impl)."""
    text = raw_query.strip()
    return {
        "product_terms": [text] if text else ["unknown product"],
        "hs_code_provided": None,
        "origin": "IN",
        "destination": "GB",
        "quantity": None,
        "unit_value_usd": None,
    }
