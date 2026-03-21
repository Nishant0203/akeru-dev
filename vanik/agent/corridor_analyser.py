"""Multi-origin landed-cost comparison for one HS code and destination market."""

from __future__ import annotations

import asyncio
from typing import Any

from agent.result_normaliser import normalise_rate_result
from mcp_servers.vanik_api.tools.lookup_mfn import get_mfn_rate
from mcp_servers.vanik_api.tools.lookup_preference_scheme import (
    effective_duty_pct,
    get_preference_scheme,
)

MCP_TIMEOUT = 12.0

# Origins to compare for each primary destination (import market)
ANALYSIS_ORIGINS: dict[str, list[str]] = {
    "GB": ["IN", "BD", "PK", "VN", "CN", "LK", "KH"],
    "EU": ["IN", "BD", "PK", "VN", "CN", "LK", "KH"],
    "IN": ["CN", "DE", "JP", "KR", "US", "TW"],
}

# Illustrative supplier FOB prices by origin (USD/unit) for garment-style demos
_ORIGIN_UNIT_PRICE_GARMENT: dict[str, float] = {
    "IN": 12.5,
    "BD": 9.8,
    "PK": 9.2,
    "VN": 10.2,
    "CN": 11.8,
    "LK": 10.9,
    "KH": 10.4,
}

_ORIGIN_UNIT_PRICE_GENERIC: dict[str, float] = {
    "IN": 100.0,
    "BD": 92.0,
    "PK": 88.0,
    "VN": 95.0,
    "CN": 90.0,
    "LK": 93.0,
    "KH": 91.0,
    "DE": 120.0,
    "JP": 130.0,
    "KR": 115.0,
    "US": 125.0,
    "TW": 105.0,
}


def _unit_price_for_origin(origin: str, default_unit: float, garment: bool) -> float:
    table = _ORIGIN_UNIT_PRICE_GARMENT if garment else _ORIGIN_UNIT_PRICE_GENERIC
    return table.get(origin, default_unit)


def _landed_parts(unit_value: float, mfn_pct: float | None) -> dict[str, float | None]:
    if unit_value is None or mfn_pct is None:
        return {"duty_per_unit_usd": None, "landed_per_unit_usd": None}
    duty = round(unit_value * (mfn_pct / 100.0), 4)
    return {
        "duty_per_unit_usd": duty,
        "landed_per_unit_usd": round(unit_value + duty, 4),
    }


async def _lookup(hs_code: str, destination: str) -> dict | Exception:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(get_mfn_rate, hs_code, destination),
            timeout=MCP_TIMEOUT,
        )
    except Exception as exc:
        return exc


async def analyse_corridors(
    hs_code: str,
    destination: str,
    *,
    unit_value_usd: float | None = None,
    quantity: float | None = None,
    garment_pricing: bool = False,
) -> dict[str, Any]:
    """
    Parallel MFN fetch for the destination, then per-origin effective duty (preference overlay)
    and illustrative landed cost.
    """
    dest = (destination or "").strip().upper()
    if dest == "UK":
        dest = "GB"
    hs = (hs_code or "").strip()
    if not hs or dest not in ANALYSIS_ORIGINS:
        return {
            "ok": False,
            "error": {"code": "invalid_input", "message": "Need HS code and destination GB|EU|IN"},
        }

    raw = await _lookup(hs, dest)
    norm = normalise_rate_result(raw, dest)
    mfn_headline = norm.get("mfn_rate_pct") if norm.get("status") == "ok" else None

    qty = float(quantity) if quantity is not None else 1.0
    base_unit = float(unit_value_usd) if unit_value_usd is not None else 12.5

    origins = ANALYSIS_ORIGINS[dest]
    corridors: list[dict[str, Any]] = []

    for origin in origins:
        eff_pct, basis = effective_duty_pct(mfn_headline, origin, dest)
        unit = _unit_price_for_origin(origin, base_unit, garment_pricing)
        parts = _landed_parts(unit, eff_pct)
        corridors.append(
            {
                "origin": origin,
                "destination": dest,
                "mfn_rate_pct": mfn_headline,
                "effective_duty_pct": eff_pct,
                "duty_basis": basis,
                "unit_value_usd": unit,
                "duty_per_unit_usd": parts["duty_per_unit_usd"],
                "landed_per_unit_usd": parts["landed_per_unit_usd"],
                "total_duty_usd": round((parts["duty_per_unit_usd"] or 0) * qty, 2)
                if parts["duty_per_unit_usd"] is not None
                else None,
                "total_landed_usd": round((parts["landed_per_unit_usd"] or 0) * qty, 2)
                if parts["landed_per_unit_usd"] is not None
                else None,
                "preference": get_preference_scheme(origin, dest),
            }
        )

    calculable = [c for c in corridors if c.get("landed_per_unit_usd") is not None]
    calculable.sort(key=lambda c: float(c["landed_per_unit_usd"]))

    base = next((c for c in calculable if c["origin"] == "IN"), calculable[0] if calculable else None)
    best = calculable[0] if calculable else None

    savings = None
    if base and best and base.get("landed_per_unit_usd") is not None and best.get("landed_per_unit_usd"):
        if best["origin"] != base["origin"]:
            savings = {
                "vs_base_per_unit": round(
                    float(base["landed_per_unit_usd"]) - float(best["landed_per_unit_usd"]),
                    4,
                ),
                "vs_base_total": round(
                    (float(base["total_landed_usd"] or 0) - float(best["total_landed_usd"] or 0)),
                    2,
                ),
                "best_origin": best["origin"],
                "base_origin": base["origin"],
            }

    return {
        "ok": True,
        "hs_code": hs,
        "destination": dest,
        "headline_mfn_pct": mfn_headline,
        "rate_status": norm.get("status"),
        "corridors": corridors,
        "ranked": calculable,
        "recommended": best,
        "base_origin_row": base,
        "savings_vs_base": savings,
    }
