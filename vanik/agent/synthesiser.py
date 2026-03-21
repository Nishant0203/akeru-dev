"""Output formatter/synthesiser — LLM narrative + rich template fallback."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from agent.prompts import SYNTHESIS_NARRATIVE_EN, SYNTHESIS_NARRATIVE_HI
from agent.providers import call_llm, get_completion_client, get_model_name

logger = logging.getLogger(__name__)

_HINDI_TRANSLATE_SYSTEM = """You are a trade compliance assistant. Given a short English passage about MFN tariff rates for an HS code, translate it into fluent Hindi (Devanagari script). Preserve structure and numbers. Return ONLY the Hindi translation — no preamble, no explanation."""


def _rate_or_unavailable(rate: dict, err: dict | None) -> tuple[float | None, str | None]:
    if err:
        code = err.get("code", "error")
        msg = err.get("message", "")
        detail = msg if msg and msg != code else code
        return None, detail
    return rate.get("mfn_rate_pct"), None


def _fmt_rate_line(val: float | None, note: str | None, api_label: str) -> str:
    if val is not None:
        return f"{val}% ({api_label})"
    reason = (note or "unknown").strip()
    return f"unavailable — {reason} ({api_label})"


def _template_narrative(
    *,
    commodity_code: str,
    uk_val: float | None,
    uk_note: str | None,
    eu_val: float | None,
    eu_note: str | None,
    in_val: float | None,
    in_note: str | None,
    origin: str,
    destination: str,
    description: str,
    product_terms: list[str] | None,
) -> str:
    """Ordered narrative: what was asked, MFN meaning, rates, IGST, missing-corridor actions."""
    terms = product_terms if isinstance(product_terms, list) else None
    product_label = (description or "").strip() or (
        " ".join(str(t).strip() for t in terms if str(t).strip()) if terms else ""
    )
    if not product_label:
        product_label = "the selected product"

    corridor_label = ""
    if origin and destination:
        corridor_label = f"{origin} → {destination}"

    context_line = (
        f"Tariff lookup for {product_label} (HS {commodity_code})"
        + (f", corridor {corridor_label}" if corridor_label else "")
        + "."
    )

    mfn_line = (
        "MFN (Most Favoured Nation) rates are the standard import duties applied to goods "
        "from countries without a preferential trade agreement. These are baseline rates — "
        "no India–UK or India–EU FTA is currently in force for these lines, so MFN applies."
    )

    rates_line = (
        "Rates: "
        f"GB {_fmt_rate_line(uk_val, uk_note, 'UK Trade Tariff API')}, "
        f"EU {_fmt_rate_line(eu_val, eu_note, 'EU XI Tariff API')}, "
        f"IN {_fmt_rate_line(in_val, in_note, 'WTO Timeseries API')}."
    )

    igst_line = (
        "India import rate shown is Basic Customs Duty only. IGST (typically 18% or 28% "
        "depending on sub-classification) and cess apply additionally — verify the full "
        "duty stack before calculating landed cost."
    )

    missing_lines: list[str] = []
    if eu_val is None:
        missing_lines.append(
            "EU rate could not be retrieved. Landed cost for the EU cannot be confirmed "
            "from this lookup. Check trade-tariff.service.gov.uk/xi for the XI tariff "
            "directly, or retry — the EU XI API occasionally returns no data for specific codes."
        )
    if uk_val is None:
        missing_lines.append(
            "UK rate could not be retrieved. Retry or check trade-tariff.service.gov.uk "
            "manually for the UK Trade Tariff."
        )
    if in_val is None:
        missing_lines.append(
            "India import rate could not be retrieved from WTO. Check cbic.gov.in for the "
            "current BCD rate or retry later."
        )

    parts = [context_line, mfn_line, rates_line, igst_line, *missing_lines]
    return " ".join(parts)


def _facts_user_block(
    *,
    commodity_code: str,
    description: str,
    origin: str,
    destination: str,
    product_terms: list[str] | None,
    uk_val: float | None,
    uk_note: str | None,
    eu_val: float | None,
    eu_note: str | None,
    in_val: float | None,
    in_note: str | None,
    failed_corridors: list[str] | None,
    uk_rate: dict,
    eu_rate: dict,
    in_rate: dict,
) -> str:
    pt = " | ".join(str(t) for t in (product_terms or []) if str(t).strip())
    lines = [
        f"HS code: {commodity_code}",
        f"Description: {description or '(none)'}",
        f"Product terms: {pt or '(none)'}",
        f"Route context: origin={origin}, selected destination={destination}",
        f"UK (GB) MFN: {uk_val if uk_val is not None else uk_note} source={uk_rate.get('source')}",
        f"EU MFN: {eu_val if eu_val is not None else eu_note} source={eu_rate.get('source')}",
        f"India import MFN: {in_val if in_val is not None else in_note} source={in_rate.get('source')}",
    ]
    if failed_corridors:
        lines.append(f"Failed corridors: {', '.join(failed_corridors)}")
    return "\n".join(lines)


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
    product_terms: list[str] | None = None,
) -> dict:
    """Build narrative + structured LandedCost output. LLM narrative with template fallback."""
    destination = destination.upper()
    origin_u = (origin or "").upper()

    uk_val, uk_note = _rate_or_unavailable(uk_rate, corridor_errors.get("GB"))
    eu_val, eu_note = _rate_or_unavailable(eu_rate, corridor_errors.get("EU"))
    in_val, in_note = _rate_or_unavailable(in_rate, corridor_errors.get("IN"))

    rate_by_destination = {"GB": uk_val, "EU": eu_val, "IN": in_val}
    selected_rate = rate_by_destination.get(destination)

    template_en = _template_narrative(
        commodity_code=commodity_code,
        uk_val=uk_val,
        uk_note=uk_note,
        eu_val=eu_val,
        eu_note=eu_note,
        in_val=in_val,
        in_note=in_note,
        origin=origin_u,
        destination=destination,
        description=description,
        product_terms=product_terms,
    )

    facts = _facts_user_block(
        commodity_code=commodity_code,
        description=description,
        origin=origin_u,
        destination=destination,
        product_terms=product_terms,
        uk_val=uk_val,
        uk_note=uk_note,
        eu_val=eu_val,
        eu_note=eu_note,
        in_val=in_val,
        in_note=in_note,
        failed_corridors=failed_corridors,
        uk_rate=uk_rate,
        eu_rate=eu_rate,
        in_rate=in_rate,
    )

    narrative = template_en
    if lang == "hi":
        system = SYNTHESIS_NARRATIVE_HI
        model_task = "synthesis_hindi"
    else:
        system = SYNTHESIS_NARRATIVE_EN
        model_task = "synthesis"

    try:
        client = get_completion_client()
        model = get_model_name(model_task)

        def _call() -> str:
            return call_llm(
                client,
                system=system,
                user=f"FACTS:\n{facts}",
                model=model,
                max_tokens=512,
                temperature=0.2,
            )

        llm_text = (await asyncio.to_thread(_call)).strip()
        if llm_text:
            narrative = llm_text
    except Exception as exc:
        logger.warning("synthesiser LLM narrative failed, using template/translate: %s", exc)
        narrative = template_en
        if lang == "hi":
            try:
                client = get_completion_client()

                def _translate() -> str:
                    return call_llm(
                        client,
                        system=_HINDI_TRANSLATE_SYSTEM,
                        user=template_en,
                        model=get_model_name("synthesis_hindi"),
                        max_tokens=512,
                        temperature=0.2,
                    )

                hindi_text = (await asyncio.to_thread(_translate)).strip()
                if hindi_text:
                    narrative = hindi_text
            except Exception as exc2:
                logger.warning("synthesiser Hindi translate fallback failed: %s", exc2)

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
                    "origin": origin_u,
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
