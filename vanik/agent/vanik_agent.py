"""Single-agent orchestrator."""

from __future__ import annotations

import asyncio
import warnings

from mcp_servers.vanik_api.tools.lookup_mfn import get_mfn_rate
from mcp_servers.vanik_api.tools.search_hs_schedule import search_hs_schedule
from nes.orchestrator import ms_extract
from nes.query_builder import DisambiguationRequired, build_hs_search_terms

from agent.confirmation_gate import format_options, resolve_selection
from agent.errors import msg
from agent.guardrails import validate_agent_output
from agent.result_normaliser import normalise_rate_result, to_corridor_error, to_synthesis_rate
from agent.synthesiser import build

MCP_TIMEOUT = 8.0
_AUTO_GATE_SELECTION = "__auto__"


def _no_match_search_label(entities: dict, user_query: str) -> str:
    """User-visible fragment for no_match — extracted terms, else sanitised raw query."""
    terms = entities.get("product_terms")
    if isinstance(terms, list) and terms:
        parts = [str(t).strip() for t in terms if str(t).strip()]
        if parts:
            return " ".join(parts)
    raw = (entities.get("_raw") or user_query or "").strip()
    return raw if raw else "your search"


def is_valid_hs_format(code: str) -> bool:
    """HS format guardrail: allow 6/8/10-digit numeric codes."""
    return code.isdigit() and len(code) in {6, 8, 10}


def _missing_route_fields(entities: dict) -> list[str]:
    missing: list[str] = []
    if not entities.get("origin"):
        missing.append("origin")
    if not entities.get("destination"):
        missing.append("destination")
    return missing


async def _lookup_corridor(hs_code: str, destination: str) -> dict | Exception:
    """Run one blocking corridor lookup in a thread with timeout boundary."""
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(get_mfn_rate, hs_code, destination),
            timeout=MCP_TIMEOUT,
        )
    except Exception as exc:  # includes timeout
        return exc


async def _lookup_and_synthesise(
    *,
    entities: dict,
    confirmed_code: str,
    human_confirmed: bool,
    hs_code_source: str,
    description: str | None = None,
) -> dict:
    hs6 = confirmed_code[:6]

    uk_raw, eu_raw, in_raw = await asyncio.gather(
        _lookup_corridor(confirmed_code, "GB"),
        _lookup_corridor(confirmed_code, "EU"),
        _lookup_corridor(hs6, "IN"),
    )

    uk_n = normalise_rate_result(uk_raw, "GB")
    eu_n = normalise_rate_result(eu_raw, "EU")
    in_n = normalise_rate_result(in_raw, "IN")

    uk_rate, uk_error = to_synthesis_rate(uk_n), to_corridor_error(uk_n)
    eu_rate, eu_error = to_synthesis_rate(eu_n), to_corridor_error(eu_n)
    in_rate, in_error = to_synthesis_rate(in_n), to_corridor_error(in_n)

    errors = {"GB": uk_error, "EU": eu_error, "IN": in_error}
    _lang = entities.get("_lang") or "en"
    failed_corridors = [c for c in ("GB", "EU", "IN") if errors.get(c)]

    if all(errors.values()):
        resolved_description = (description or "").strip()
        if not resolved_description:
            terms = entities.get("product_terms")
            if isinstance(terms, list) and terms:
                resolved_description = str(terms[0])
        product_bits = resolved_description or "the selected product"
        narrative = (
            f"Rates for HS {confirmed_code} ({product_bits}) could not be retrieved from any "
            "source. This is usually a temporary API or network issue. "
            f"UK: {uk_n.get('reason', 'unavailable')}. "
            f"EU: {eu_n.get('reason', 'unavailable')}. "
            f"IN: {in_n.get('reason', 'unavailable')}. "
            "Try again in a few minutes, or check trade-tariff.service.gov.uk directly "
            "for the UK rate."
        )
        return {
            "ok": False,
            "status": "rates_unavailable",
            "hs_code": confirmed_code,
            "message": narrative,
            "narrative": narrative,
            "errors": [errors["GB"], errors["EU"], errors["IN"]],
            "corridor_norm": {"GB": uk_n, "EU": eu_n, "IN": in_n},
        }

    resolved_description = description or ""
    if not resolved_description:
        terms = entities.get("product_terms")
        if isinstance(terms, list) and terms:
            resolved_description = str(terms[0])

    pt = entities.get("product_terms")
    product_terms_list = pt if isinstance(pt, list) else None

    synthesized = await build(
        commodity_code=confirmed_code,
        uk_rate=uk_rate or {},
        eu_rate=eu_rate or {},
        in_rate=in_rate or {},
        corridor_errors=errors,
        human_confirmed=human_confirmed,
        hs_code_source=hs_code_source,
        origin=str(entities.get("origin") or "").upper(),
        destination=str(entities.get("destination") or "").upper(),
        description=resolved_description,
        lang=_lang,
        failed_corridors=failed_corridors,
        product_terms=product_terms_list,
    )

    valid, reason = validate_agent_output(synthesized)
    if not valid:
        return {
            "ok": False,
            "status": "guardrail_violation",
            "message": "Generated response failed output guardrail validation.",
            "error": {"code": "output_guardrail_violation", "message": reason or "unknown"},
        }

    return synthesized


async def vanik_agent(
    user_query: str,
    hs_code_provided: str | None = None,
    *,
    gate_selection: str | None = None,
    precomputed_entities: dict | None = None,
    gate_options: list[dict] | None = None,
) -> dict:
    """Run full lifecycle: Manifest Search -> search -> gate -> lookup -> synthesis.

    Gate behaviour:
    - gate_selection == "__auto__": select first option (legacy compatibility)
    - gate_selection is None: return awaiting_confirmation payload
    - otherwise: parse user gate selection and continue
    """
    if hs_code_provided and not is_valid_hs_format(hs_code_provided):
        return {
            "ok": False,
            "status": "invalid_input",
            "message": msg("invalid_hs_format", "en", code=hs_code_provided or ""),
        }

    entities = dict(precomputed_entities or await ms_extract(user_query))

    if entities.get("_extraction_error"):
        _lang = entities.get("_lang") or "en"
        return {
            "ok": False,
            "status": "extraction_error",
            "message": msg("extraction_service_unavailable", _lang),
        }

    if hs_code_provided or entities.get("hs_code_provided"):
        confirmed_code = hs_code_provided or entities.get("hs_code_provided")
        human_confirmed = False
        hs_code_source = "caller_supplied" if hs_code_provided else "query_supplied"
        if not is_valid_hs_format(str(confirmed_code)):
            _lang = entities.get("_lang") or "en"
            return {
                "ok": False,
                "status": "invalid_input",
                "message": msg("invalid_hs_format", _lang, code=str(confirmed_code)),
            }

        return await _lookup_and_synthesise(
            entities=entities,
            confirmed_code=str(confirmed_code),
            human_confirmed=human_confirmed,
            hs_code_source=hs_code_source,
        )

    missing = _missing_route_fields(entities)
    if missing:
        _lang = entities.get("_lang") or "en"
        if not entities.get("origin") and not entities.get("destination"):
            key = "needs_clarification_both"
        elif not entities.get("origin"):
            key = "needs_clarification_origin"
        else:
            key = "needs_clarification_destination"
        return {
            "ok": False,
            "status": "needs_clarification",
            "missing": missing,
            "message": msg(key, _lang),
        }

    options = gate_options
    if options is None:
        plan = build_hs_search_terms(entities)
        if isinstance(plan, DisambiguationRequired):
            _lang = entities.get("_lang") or "en"
            return {
                "ok": False,
                "status": "awaiting_disambiguation",
                "message": plan.question,
                "options": plan.options,
                "original_term": plan.original_term,
                "chapter_hint": plan.chapter_hint,
                "entities": entities,
                "_lang": _lang,
            }
        options = format_options(search_hs_schedule(product_terms=plan))

    if not options:
        _lang = entities.get("_lang") or "en"
        searched = _no_match_search_label(entities, user_query)
        return {
            "ok": False,
            "status": "no_match",
            "message": msg("no_match", _lang, searched=searched),
            "allow_manual_hs": True,
        }

    if gate_selection is None:
        _lang = entities.get("_lang") or "en"
        return {
            "ok": False,
            "status": "awaiting_confirmation",
            "message": msg("gate_prompt", _lang),
            "options": options,
            "allow_manual_hs": True,
            "entities": entities,
        }

    if gate_selection == _AUTO_GATE_SELECTION:
        warnings.warn(
            "_AUTO_GATE_SELECTION (__auto__) is deprecated; gate should always require explicit confirmation.",
            DeprecationWarning,
            stacklevel=2,
        )
        confirmed_code = str(options[0]["commodity_code"])
        selected_description = str(options[0].get("description", ""))
        return await _lookup_and_synthesise(
            entities=entities,
            confirmed_code=confirmed_code,
            human_confirmed=False,
            hs_code_source="auto_selected",
            description=selected_description,
        )
    else:
        try:
            confirmed_code = resolve_selection(gate_selection, options)
        except ValueError as exc:
            _lang = entities.get("_lang") or "en"
            err_msg = msg("invalid_gate_selection", _lang)
            return {
                "ok": False,
                "status": "awaiting_confirmation",
                "message": err_msg,
                "options": options,
                "allow_manual_hs": True,
                "error": {"code": "invalid_gate_selection", "message": err_msg},
                "entities": entities,
            }
        selected_description = next(
            (str(option.get("description", "")) for option in options if str(option["commodity_code"]) == confirmed_code),
            "",
        )

    return await _lookup_and_synthesise(
        entities=entities,
        confirmed_code=confirmed_code,
        human_confirmed=True,
        hs_code_source="human_confirmed",
        description=selected_description,
    )
