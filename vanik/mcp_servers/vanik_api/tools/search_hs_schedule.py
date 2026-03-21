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


def _search_api(query: str, top_k: int) -> list[dict[str, Any]]:
    """Single search query against UK Trade Tariff API."""
    url = (
        "https://www.trade-tariff.service.gov.uk/api/v2/search?"
        + urllib.parse.urlencode({"q": query})
    )
    data = _api_get(url)
    data_block = data.get("data", {})

    if isinstance(data_block, dict):
        attrs = data_block.get("attributes", {})
        search_type = attrs.get("type", "")

        # Fuzzy match — extract commodities directly
        if search_type == "fuzzy_match":
            matches = attrs.get("goods_nomenclature_match", {})
            results: list[dict[str, Any]] = []
            seen: set[str] = set()
            for item in matches.get("commodities", [])[: top_k * 2]:
                src = item.get("_source", {})
                code = src.get("goods_nomenclature_item_id", "")
                desc = src.get("description", "")
                if code and desc and code not in seen:
                    results.append({"commodity_code": code, "description": desc})
                    seen.add(code)
                if len(results) >= top_k:
                    break
            return results

        # Exact match — expand to heading
        if search_type == "exact_match":
            entry = attrs.get("entry", {})
            code = entry.get("id", "")
            if code and entry.get("endpoint") == "commodities":
                heading = code[:4]
                results = _fetch_heading_commodities(heading, top_k)
                return results if results else [{"commodity_code": code, "description": query}]

        # Legacy: no type, try entry for exact match
        entry = attrs.get("entry", {})
        code = entry.get("id", "")
        if code and entry.get("endpoint") == "commodities":
            heading = code[:4]
            results = _fetch_heading_commodities(heading, top_k)
            return results if results else [{"commodity_code": code, "description": query}]

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


def search_hs_schedule(product_terms: list[str] | str, top_k: int = 3) -> list[dict[str, Any]]:
    """Search UK Trade Tariff API. Full phrase first; if few results, also try fuzzy with words."""
    query = " ".join(product_terms) if isinstance(product_terms, list) else product_terms
    query = (query or "").strip()
    if not query:
        return []

    results: list[dict[str, Any]] = []
    try:
        results = _search_api(query, top_k)
        seen_codes = {r.get("commodity_code", "") for r in results}

        # If exact match returned few options, also try fuzzy with meaningful words
        words = [w for w in query.split() if len(w) > 3]
        if len(words) > 1 and len(results) < top_k:
            for r in _search_api(" ".join(words), top_k):
                code = r.get("commodity_code", "")
                if code and code not in seen_codes:
                    results.append(r)
                    seen_codes.add(code)

        results = results[:top_k]
    except Exception:
        results = []

    if not results:
        try:
            from mcp_servers.vanik_docs.db import search_tariff_rows

            rows = search_tariff_rows(query, limit=top_k)
            return [
                {"commodity_code": r.get("hs_code", ""), "description": r.get("description", "")}
                for r in rows
                if r.get("hs_code") and r.get("description")
            ]
        except Exception:
            return []
    return results
