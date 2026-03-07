"""WTO Timeseries client."""

from __future__ import annotations

import re
from typing import Any

import httpx

from mcp_servers.vanik_api.config import settings
from mcp_servers.vanik_api.errors import VanikAPIError
from mcp_servers.vanik_api.models import WTOResult

_SOURCE = "WTO Timeseries API"


def _extract_rate(payload: dict[str, Any]) -> float:
    """Extract a numeric rate from common WTO payload shapes."""
    rows = payload.get("Dataset") or payload.get("value") or payload.get("data") or []
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list) or not rows:
        raise VanikAPIError(
            code="parse_error",
            message="WTO response did not contain dataset rows",
            source=_SOURCE,
            details={"keys": list(payload.keys())[:12]},
        )

    row = rows[0]
    candidates = [
        row.get("value"),
        row.get("Value"),
        row.get("OBS_VALUE"),
        row.get("obs_value"),
        row.get("rate"),
    ]
    for value in candidates:
        if value is None:
            continue
        if isinstance(value, (float, int)):
            return float(value)
        if isinstance(value, str):
            match = re.search(r"\d+(?:\.\d+)?", value)
            if match:
                return float(match.group(0))

    raise VanikAPIError(
        code="parse_error",
        message="Unable to parse WTO MFN rate from dataset row",
        source=_SOURCE,
        details={"row": row},
    )


def _request_wto(
    http_client: httpx.Client,
    *,
    hs_code_6: str,
    year: int,
    api_key: str,
) -> httpx.Response:
    params = {
        "i": settings.wto_indicator,
        "r": settings.wto_reporter_code,
        "ps": str(year),
        "pc": hs_code_6,
        "fmt": "json",
    }
    headers = {"Ocp-Apim-Subscription-Key": api_key}
    return http_client.get(f"{settings.wto_base_url.rstrip('/')}/data", params=params, headers=headers)


def get_india_mfn_rate(
    hs_code_6: str,
    *,
    year: int | None = None,
    client: httpx.Client | None = None,
) -> WTOResult:
    """Fetch India's MFN rate (BCD) for a 6-digit HS code from WTO Timeseries."""
    if not hs_code_6.isdigit() or len(hs_code_6) != 6:
        raise VanikAPIError(
            code="invalid_hs_code",
            message="India destination requires a 6-digit HS code",
            source=_SOURCE,
            details={"hs_code": hs_code_6},
        )

    keys: list[str] = [k for k in [settings.wto_api_key_primary, settings.wto_api_key_secondary] if k]
    if not keys:
        raise VanikAPIError(
            code="missing_api_key",
            message="Set WTO_API_KEY and/or WTO_SECONDARY_API_KEY for WTO calls",
            source=_SOURCE,
        )

    close_client = client is None
    http_client = client or httpx.Client(timeout=settings.wto_timeout_seconds)
    target_year = year or settings.wto_default_year

    try:
        response: httpx.Response | None = None
        for index, api_key in enumerate(keys):
            try:
                response = _request_wto(http_client, hs_code_6=hs_code_6, year=target_year, api_key=api_key)
            except httpx.HTTPError as exc:
                if index < len(keys) - 1:
                    continue
                raise VanikAPIError(
                    code="upstream_unreachable",
                    message="Failed to connect to WTO Timeseries API",
                    source=_SOURCE,
                    details={"error": str(exc)},
                ) from exc

            if response.status_code in (401, 403) and index < len(keys) - 1:
                continue
            break
    finally:
        if close_client:
            http_client.close()

    assert response is not None

    if response.status_code == 204:
        raise VanikAPIError(
            code="no_data",
            message="No WTO notification data available for this HS code/year",
            source=_SOURCE,
            http_status=204,
        )
    if response.status_code >= 400:
        raise VanikAPIError(
            code="upstream_error",
            message="WTO Timeseries API returned an error",
            source=_SOURCE,
            http_status=response.status_code,
            details={"body": response.text[:500]},
        )

    payload = response.json()
    rate = _extract_rate(payload)

    return WTOResult(
        hs_code_6=hs_code_6,
        mfn_rate_pct=rate,
        year=target_year,
        indicator=settings.wto_indicator,
        reporter=settings.wto_reporter_code,
        partner=None,
    )
