"""Output formatter/synthesiser stub."""

from __future__ import annotations

from datetime import UTC, datetime


def _rate_or_unavailable(rate: dict, err: dict | None) -> tuple[float | None, str | None]:
    if err:
        return None, f"unavailable ({err.get('code', 'error')})"
    return rate.get("mfn_rate_pct"), None


def build(
    commodity_code: str,
    uk_rate: dict,
    eu_rate: dict,
    in_rate: dict,
    corridor_errors: dict[str, dict | None],
    human_confirmed: bool,
    hs_code_source: str,
    origin: str,
    destination: str,
    description: str = "",
) -> dict:
    """Build narrative + structured LandedCost output."""
    destination = destination.upper()

    uk_val, uk_note = _rate_or_unavailable(uk_rate, corridor_errors.get("GB"))
    eu_val, eu_note = _rate_or_unavailable(eu_rate, corridor_errors.get("EU"))
    in_val, in_note = _rate_or_unavailable(in_rate, corridor_errors.get("IN"))

    rate_by_destination = {"GB": uk_val, "EU": eu_val, "IN": in_val}
    selected_rate = rate_by_destination.get(destination)

    def fmt(value: float | None, note: str | None) -> str:
        if value is not None:
            return f"{value}%"
        return note or "unavailable"

    narrative = (
        f"MFN rates for HS {commodity_code}: "
        f"GB {fmt(uk_val, uk_note)} (UK Trade Tariff API), "
        f"EU {fmt(eu_val, eu_note)} (EU XI Tariff API), "
        f"IN {fmt(in_val, in_note)} (WTO Timeseries API)."
    )

    return {
        "ok": True,
        "narrative": narrative,
        "audit": {
            "human_confirmed": human_confirmed,
            "hs_code_source": hs_code_source,
            "calculated_at": datetime.now(UTC).isoformat(),
            "sources": [uk_rate.get("source"), eu_rate.get("source"), in_rate.get("source")],
            "corridor_errors": corridor_errors,
        },
        "data_part": {
            "kind": "data",
            "data": {
                "vanik.compliance.LandedCost": {
                    "hs_code": commodity_code,
                    "description": description,
                    "origin": origin,
                    "destination": destination,
                    "mfn_rate_pct": selected_rate,
                    "uk_mfn_rate_pct": uk_val,
                    "eu_mfn_rate_pct": eu_val,
                    "india_mfn_rate_pct": in_val,
                    "uk_status": "ok" if uk_val is not None else "unavailable",
                    "eu_status": "ok" if eu_val is not None else "unavailable",
                    "in_status": "ok" if in_val is not None else "unavailable",
                }
            },
        },
    }
