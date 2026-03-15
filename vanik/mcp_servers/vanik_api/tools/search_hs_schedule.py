"""Tool: search_hs_schedule — UK Trade Tariff API search."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any


def _api_get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "vanik/1.0"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read())


def _fetch_heading_commodities(heading_code: str, top_k: int) -> list[dict[str, Any]]:
    """Fetch all declarable commodity codes under a heading."""
    url = f"https://www.trade-tariff.service.gov.uk/api/v2/headings/{heading_code}"
    data = _api_get(url)
    results: list[dict[str, Any]] = []
    for item in data.get("included", []):
        if item.get("type") != "commodity":
            continue
        attrs = item.get("attributes", {})
        code = attrs.get("goods_nomenclature_item_id", "")
        desc = attrs.get("description", "")
        declarable = attrs.get("declarable", False)
        if code and desc and declarable:
            results.append({"commodity_code": code, "description": desc})
        if len(results) >= top_k:
            break
    return results


def search_hs_schedule(product_terms: list[str] | str, top_k: int = 3) -> list[dict[str, Any]]:
    """Search UK Trade Tariff API for commodity codes."""
    query = " ".join(product_terms) if isinstance(product_terms, list) else product_terms
    query = (query or "").strip()
    if not query:
        return []

    try:
        url = (
            "https://www.trade-tariff.service.gov.uk/api/v2/search?"
            + urllib.parse.urlencode({"q": query})
        )
        data = _api_get(url)

        data_block = data.get("data", {})

        # Exact match — expand to full heading for options
        if isinstance(data_block, dict):
            attrs = data_block.get("attributes", {})
            entry = attrs.get("entry", {})
            code = entry.get("id", "")
            if code and entry.get("endpoint") == "commodities":
                heading = code[:4]
                results = _fetch_heading_commodities(heading, top_k)
                return results if results else [{"commodity_code": code, "description": query}]

        # List response
        if isinstance(data_block, list):
            results = []
            for item in data_block[:top_k]:
                attrs = item.get("attributes", {})
                code = attrs.get("goods_nomenclature_item_id", "")
                desc = attrs.get("description", "")
                if code and desc:
                    results.append({"commodity_code": code, "description": desc})
            return results

        return []

    except Exception:
        # Fallback to DB
        try:
            from mcp_servers.vanik_docs.db import search_tariff_rows_by_description

            rows = search_tariff_rows_by_description(query, limit=top_k)
            return [
                {"commodity_code": r.get("hs_code", ""), "description": r.get("description", "")}
                for r in rows
            ]
        except Exception:
            return []
