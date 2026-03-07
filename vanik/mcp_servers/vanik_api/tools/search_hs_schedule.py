"""Tool: search_hs_schedule (DB description search when available, else stub)."""

from __future__ import annotations

from typing import Any

try:
    from mcp_servers.vanik_docs.db import search_tariff_rows_by_description
except ImportError:  # pragma: no cover - vanik_docs optional
    search_tariff_rows_by_description = None


def embed(text: str) -> list[float]:
    """Placeholder embedding call."""
    if not text.strip():
        return []
    return [0.1, 0.2, 0.3]


def search_hs_schedule(product_terms: list[str] | str, top_k: int = 3) -> list[dict[str, Any]]:
    """Return top-k HS candidates from vanik_docs DB (LIKE on description) or stub."""
    query = " ".join(product_terms) if isinstance(product_terms, list) else product_terms
    query = (query or "").strip()

    if search_tariff_rows_by_description and query:
        rows = search_tariff_rows_by_description(query, limit=top_k)
        if rows:
            return [
                {
                    "commodity_code": r.get("hs_code", ""),
                    "description": r.get("description") or "",
                }
                for r in rows
            ]

    # Stub when DB unavailable or no matches
    _ = embed(query)
    candidates = [
        {"commodity_code": "8708301090", "description": "Brakes and servo-brakes: disc brakes"},
        {"commodity_code": "8708309000", "description": "Brakes and servo-brakes: other"},
        {"commodity_code": "8708991000", "description": "Other parts and accessories (residual)"},
    ]
    return candidates[:top_k]
