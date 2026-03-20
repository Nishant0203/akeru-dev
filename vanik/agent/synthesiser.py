"""Output formatter/synthesiser."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

_HINDI_SYSTEM = """You are a trade compliance assistant. Given a short English sentence describing MFN tariff rates for an HS code, translate it into fluent Hindi (Devanagari script). Return ONLY the Hindi translation — no preamble, no explanation."""


def _rate_or_unavailable(rate: dict, err: dict | None) -> tuple[float | None, str | None]:
    if err:
        return None, f"unavailable ({err.get('code', 'error')})"
    return rate.get("mfn_rate_pct"), None


def _extract_text_content(response: object) -> str:
    parts = getattr(response, "content", []) or []
    chunks: list[str] = []
    for part in parts:
        text = getattr(part, "text", None)
        if text:
            chunks.append(text)
    return "".join(chunks).strip()


async def build(
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
    lang: str = "en",
    failed_corridors: list[str] | None = None,
) -> dict:
    """Build narrative + structured LandedCost output. Hindi path uses LLM for fluent text."""
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

    narrative_en = (
        f"MFN rates for HS {commodity_code}: "
        f"GB {fmt(uk_val, uk_note)} (UK Trade Tariff API), "
        f"EU {fmt(eu_val, eu_note)} (EU XI Tariff API), "
        f"IN {fmt(in_val, in_note)} (WTO Timeseries API)."
    )
    narrative_en += (
        " India import: IGST and cess depend on sub-classification (typically 18% or 28% IGST "
        "bracket); MFN shown is baseline — verify FTA / preferential schemes separately."
    )

    if failed_corridors:
        narrative_en += (
            " Rates for "
            + ", ".join(failed_corridors)
            + " could not be retrieved (timeout or API error)."
        )

    narrative = narrative_en
    if lang == "hi":
        try:
            from agent.providers import get_completion_client

            client = get_completion_client()
            response = await asyncio.to_thread(
                client.messages.create,
                model="claude-haiku-4-5-20251001",
                max_tokens=256,
                system=_HINDI_SYSTEM,
                messages=[{"role": "user", "content": narrative_en}],
            )
            hindi_text = _extract_text_content(response)
            if hindi_text:
                narrative = hindi_text
        except Exception as exc:
            logger.warning("synthesiser Hindi path failed, using English: %s", exc)

    return {
        "ok": True,
        "narrative": narrative,
        "audit": {
            "human_confirmed": human_confirmed,
            "hs_code_source": hs_code_source,
            "calculated_at": datetime.now(UTC).isoformat(),
            "sources": [uk_rate.get("source"), eu_rate.get("source"), in_rate.get("source")],
            "corridor_errors": corridor_errors,
            "lang": lang,
            "failed_corridors": failed_corridors or [],
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
                    "uk_source": uk_rate.get("source"),
                    "eu_source": eu_rate.get("source"),
                    "in_source": in_rate.get("source"),
                    "uk_measure_type": uk_rate.get("measure_type"),
                    "eu_measure_type": eu_rate.get("measure_type"),
                    "in_indicator": in_rate.get("indicator"),
                    "in_year": in_rate.get("year"),
                    "uk_status": "ok" if uk_val is not None else "unavailable",
                    "eu_status": "ok" if eu_val is not None else "unavailable",
                    "in_status": "ok" if in_val is not None else "unavailable",
                }
            },
        },
    }
