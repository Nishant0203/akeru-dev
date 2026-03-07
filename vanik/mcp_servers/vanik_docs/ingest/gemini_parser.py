"""Gemini extraction stubs."""

from __future__ import annotations


def extract_tariff_schedule(file_uri: str, doc_type: str = "cbic") -> list[dict]:
    """Return extracted tariff rows as stubbed data."""
    _ = file_uri
    if doc_type == "taric":
        return [{"hs_code": "8708301090", "description": "Disc brakes", "bcd_rate_pct": 3.0}]
    return [{"hs_code": "870830", "description": "Brakes", "bcd_rate_pct": 15.0}]
