"""Manifest Search orchestrator with v2 -> v3 fallback."""

from __future__ import annotations

from manifest_search.entity_stripper import append_sanitisation_audit, strip_entities
from nes.feedback_store import log_feedback, log_ms_invocation
from nes.sanitiser import sanitise_with_log
from nes.sufficiency import ner_is_sufficient
from nes.v2_ner import extract_v2
from nes.v3_llm import llm_extract


def _combine_strip_events(
    sanitise_log: list[dict],
    entity_log: list[dict],
) -> list[dict]:
    out: list[dict] = []
    for e in sanitise_log:
        out.append({"layer": "sanitiser", **e})
    for e in entity_log:
        out.append({"layer": "entity_stripper", **e})
    return out


async def ms_extract(raw_query: str) -> dict:
    """Run Manifest Search extraction: sanitise → entity strip → v2 → optional v3."""
    sanitised, sanitise_log = sanitise_with_log(raw_query)
    cleaned, entity_log = strip_entities(sanitised)
    combined_log = _combine_strip_events(sanitise_log, entity_log)
    append_sanitisation_audit(
        raw_query=raw_query,
        sanitised=sanitised,
        cleaned=cleaned,
        events=combined_log,
    )

    v2_entities = extract_v2(cleaned)
    v2_entities["_raw"] = cleaned
    v2_entities["_strip_log"] = combined_log

    is_sufficient, failure_reason = ner_is_sufficient(v2_entities)
    if is_sufficient:
        log_ms_invocation(raw_query=cleaned, used_v3=False)
        return v2_entities

    v3_entities = await llm_extract(cleaned)
    v3_entities["_raw"] = cleaned
    v3_entities["_strip_log"] = combined_log
    v3_entities["_lang"] = v2_entities.get("_lang", "en")
    log_ms_invocation(raw_query=cleaned, used_v3=True)
    log_feedback(
        raw_query=cleaned,
        v2_output=v2_entities,
        v3_output=v3_entities,
        failure_reason=failure_reason or "unknown",
    )
    return v3_entities
