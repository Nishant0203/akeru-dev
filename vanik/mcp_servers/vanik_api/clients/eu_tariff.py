"""EU XI Tariff client."""

from __future__ import annotations

import re
from typing import Any

import httpx

from mcp_servers.vanik_api.config import settings
from mcp_servers.vanik_api.errors import VanikAPIError
from mcp_servers.vanik_api.models import TariffResult

_SOURCE = "EU XI Tariff API"
_MEASURE_TYPE = "105"
_PREFERRED_GEO_IDS = {"1011"}


def _to_list(data: Any) -> list[dict[str, Any]]:
    if data is None:
        return []
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def _measure_type_id(measure: dict[str, Any]) -> str | None:
    attrs = measure.get("attributes") or {}
    if attrs.get("measure_type_id") is not None:
        return str(attrs.get("measure_type_id"))

    rel = (measure.get("relationships") or {}).get("measure_type", {}).get("data")
    refs = _to_list(rel)
    if refs:
        return str(refs[0].get("id"))
    return None


def _geo_area_id(measure: dict[str, Any]) -> str | None:
    rel = (measure.get("relationships") or {}).get("geographical_area", {}).get("data")
    refs = _to_list(rel)
    if refs:
        return str(refs[0].get("id"))
    return None


def _duty_bases(measure: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> list[str]:
    rel = (measure.get("relationships") or {}).get("duty_expression", {}).get("data")
    refs = _to_list(rel)
    bases: list[str] = []
    for ref in refs:
        expr = by_id.get(str(ref.get("id")))
        if not expr:
            continue
        base = (expr.get("attributes") or {}).get("base")
        if base:
            bases.append(str(base))
    return bases


def _parse_percent(text: str) -> float | None:
    match = re.search(r"\d+(?:\.\d+)?", text)
    return float(match.group(0)) if match else None


def _parse_rate_from_commodity(payload: dict[str, Any], measure_type: str) -> float:
    """Extract measure rate from HMRC XI commodity payload."""
    included = payload.get("included") or []
    if not isinstance(included, list):
        raise VanikAPIError(
            code="parse_error",
            message="EU payload missing included array",
            source=_SOURCE,
        )

    by_id: dict[str, dict[str, Any]] = {}
    for item in included:
        item_id = item.get("id")
        if item_id is not None:
            by_id[str(item_id)] = item

    candidates: list[tuple[int, float]] = []

    for item in included:
        if item.get("type") != "measure":
            continue
        mt_id = _measure_type_id(item)
        if mt_id != measure_type:
            continue

        geo = _geo_area_id(item)
        score = 1 if geo in _PREFERRED_GEO_IDS else 0
        for base in _duty_bases(item, by_id):
            value = _parse_percent(base)
            if value is not None:
                candidates.append((score, value))

    if not candidates:
        raise VanikAPIError(
            code="no_data",
            message=f"No MFN measure type {measure_type} found for commodity code",
            source=_SOURCE,
        )

    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return candidates[0][1]


def get_eu_mfn_rate(commodity_code_10: str, *, client: httpx.Client | None = None) -> TariffResult:
    """Fetch EU XI MFN rate for a 10-digit declarable commodity code."""
    if not commodity_code_10.isdigit() or len(commodity_code_10) != 10:
        raise VanikAPIError(
            code="invalid_hs_code",
            message="EU destination requires a 10-digit commodity code",
            source=_SOURCE,
            details={"hs_code": commodity_code_10},
        )

    close_client = client is None
    http_client = client or httpx.Client(timeout=settings.hmrc_timeout_seconds)

    try:
        response = http_client.get(
            f"{settings.eu_base_url.rstrip('/')}/commodities/{commodity_code_10}",
            headers={"Accept": settings.hmrc_accept_header},
        )
    except httpx.HTTPError as exc:
        raise VanikAPIError(
            code="upstream_unreachable",
            message="Failed to connect to EU XI Tariff API",
            source=_SOURCE,
            details={"error": str(exc)},
        ) from exc
    finally:
        if close_client:
            http_client.close()

    if response.status_code >= 400:
        raise VanikAPIError(
            code="upstream_error",
            message="EU XI Tariff API returned an error",
            source=_SOURCE,
            http_status=response.status_code,
            details={"body": response.text[:500]},
        )

    rate = _parse_rate_from_commodity(response.json(), _MEASURE_TYPE)
    return TariffResult(
        commodity_code_10=commodity_code_10,
        mfn_rate_pct=rate,
        measure_type=_MEASURE_TYPE,
        source=_SOURCE,
    )
