"""Pandas extraction fallback stub."""

from __future__ import annotations


def extract_tariff_schedule_pandas(file_path: str, doc_type: str = "cbic") -> list[dict]:
    """Return deterministic fallback rows."""
    _ = file_path
    if doc_type == "taric":
        return [{"hs_code": "8708301090", "description": "Disc brakes", "bcd_rate_pct": 3.0}]
    return [{"hs_code": "870830", "description": "Brakes", "bcd_rate_pct": 15.0}]
