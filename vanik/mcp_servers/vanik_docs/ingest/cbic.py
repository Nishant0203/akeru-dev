"""CBIC ingestion stub."""

from __future__ import annotations


def extract_cbic_rows(file_path: str) -> list[dict]:
    """Return a minimal CBIC row set."""
    _ = file_path
    return [{"hs_code": "870830", "description": "Brakes", "bcd_rate_pct": 15.0}]
