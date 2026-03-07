"""Tool: search_hs_schedule (stubbed semantic retrieval)."""

from __future__ import annotations

from typing import Any


def embed(text: str) -> list[float]:
    """Placeholder embedding call."""
    if not text.strip():
        return []
    return [0.1, 0.2, 0.3]


def search_hs_schedule(product_terms: list[str] | str, top_k: int = 3) -> list[dict[str, Any]]:
    """Return top-k HS candidates from a stub index."""
    _ = embed(" ".join(product_terms) if isinstance(product_terms, list) else product_terms)

    candidates = [
        {"commodity_code": "8708301090", "description": "Brakes and servo-brakes: disc brakes"},
        {"commodity_code": "8708309000", "description": "Brakes and servo-brakes: other"},
        {"commodity_code": "8708991000", "description": "Other parts and accessories (residual)"},
    ]
    return candidates[:top_k]
