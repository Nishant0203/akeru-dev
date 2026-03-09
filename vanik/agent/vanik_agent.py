"""Single-agent orchestrator."""

from __future__ import annotations

import asyncio
import warnings

from mcp_servers.vanik_api.tools.lookup_mfn import get_mfn_rate
from mcp_servers.vanik_api.tools.search_hs_schedule import search_hs_schedule
from nes.orchestrator import ms_extract

from agent.confirmation_gate import format_options, resolve_selection
from agent.guardrails import validate_agent_output
from agent.synthesiser import build

MCP_TIMEOUT = 8.0
_AUTO_GATE_SELECTION = "__auto__"


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


def _unwrap_tool_result(result: dict) -> tuple[dict | None, dict | None]:
    if result.get("ok"):
        return result.get("data", {}), None
    return None, result.get("error", {"code": "unknown_error", "message": "Unknown error"})


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

    def normalize(raw: dict | Exception, corridor: str) -> tuple[dict | None, dict | None]:
        if isinstance(raw, Exception):
            return None, {
                "code": "timeout_or_transport_error",
                "message": str(raw),
                "source": corridor,
            }
        return _unwrap_tool_result(raw)

    uk_rate, uk_error = normalize(uk_raw, "GB")
    eu_rate, eu_error = normalize(eu_raw, "EU")
    in_rate, in_error = normalize(in_raw, "IN")

    errors = {"GB": uk_error, "EU": eu_error, "IN": in_error}
    if all(errors.values()):
        return {
            "ok": False,
            "status": "upstream_error",
            "hs_code": confirmed_code,
            "errors": [errors["GB"], errors["EU"], errors["IN"]],
        }

    resolved_description = description or ""
    if not resolved_description:
        terms = entities.get("product_terms")
        if isinstance(terms, list) and terms:
            resolved_description = str(terms[0])

    synthesized = build(
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
            "message": f"HS code '{hs_code_provided}' is not a valid 6/8/10-digit code",
        }

    entities = dict(precomputed_entities or await ms_extract(user_query))

    if hs_code_provided or entities.get("hs_code_provided"):
        confirmed_code = hs_code_provided or entities.get("hs_code_provided")
        human_confirmed = False
        hs_code_source = "caller_supplied" if hs_code_provided else "query_supplied"
        if not is_valid_hs_format(str(confirmed_code)):
            return {
                "ok": False,
                "status": "invalid_input",
                "message": f"HS code '{confirmed_code}' is not a valid 6/8/10-digit code",
            }

        return await _lookup_and_synthesise(
            entities=entities,
            confirmed_code=str(confirmed_code),
            human_confirmed=human_confirmed,
            hs_code_source=hs_code_source,
        )

    missing = _missing_route_fields(entities)
    if missing:
        return {
            "ok": False,
            "status": "needs_clarification",
            "missing": missing,
            "message": "Please provide origin and destination country codes (e.g., IN, GB).",
        }

    options = gate_options
    if options is None:
        options = format_options(search_hs_schedule(product_terms=entities["product_terms"]))

    if not options:
        return {
            "ok": False,
            "status": "no_match",
            "message": "No close HS match found. Provide a simpler product term or enter a 10-digit code.",
            "allow_manual_hs": True,
        }

    if gate_selection is None:
        return {
            "ok": False,
            "status": "awaiting_confirmation",
            "message": "Select one option or enter a 10-digit commodity code.",
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
    else:
        try:
            confirmed_code = resolve_selection(gate_selection, options)
        except ValueError as exc:
            return {
                "ok": False,
                "status": "awaiting_confirmation",
                "message": str(exc),
                "options": options,
                "allow_manual_hs": True,
                "error": {"code": "invalid_gate_selection", "message": str(exc)},
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
