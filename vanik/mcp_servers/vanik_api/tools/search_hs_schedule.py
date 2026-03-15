"""Tool: search_hs_schedule — UK Trade Tariff API search."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any


def search_hs_schedule(product_terms: list[str] | str, top_k: int = 3) -> list[dict[str, Any]]:
    """Search UK Trade Tariff API for commodity codes."""
    query = " ".join(product_terms) if isinstance(product_terms, list) else product_terms
    query = (query or "").strip()
    if not query:
        return []

    try:
        url = "https://www.trade-tariff.service.gov.uk/api/v2/search?" + urllib.parse.urlencode(
            {"q": query}
        )
        req = urllib.request.Request(url, headers={"User-Agent": "vanik/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())

        results = []
        for item in data.get("data", [])[:top_k]:
            attrs = item.get("attributes", {})
            code = attrs.get("goods_nomenclature_item_id", "")
            desc = attrs.get("description", "")
            if code and desc:
                results.append(
                    {
                        "commodity_code": code,
                        "description": desc,
                    }
                )
        return results

    except Exception:
        # Fallback to DB if API unavailable
        try:
            from mcp_servers.vanik_docs.db import search_tariff_rows_by_description

            rows = search_tariff_rows_by_description(query, limit=top_k)
            return [
                {"commodity_code": r.get("hs_code", ""), "description": r.get("description", "")}
                for r in rows
            ]
        except Exception:
            return []
