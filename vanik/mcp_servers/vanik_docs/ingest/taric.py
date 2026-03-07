"""TARIC ingestion stub."""

from __future__ import annotations


def extract_taric_rows(file_path: str) -> list[dict]:
    """Return a minimal TARIC row set."""
    _ = file_path
    return [{"hs_code": "8708301090", "description": "Disc brakes", "bcd_rate_pct": 3.0}]
