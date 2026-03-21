"""Manifest Search orchestrator with v2 -> v3 fallback."""

from __future__ import annotations

from nes.feedback_store import log_feedback, log_ms_invocation
from nes.sanitiser import sanitise, sanitise_with_log
from nes.sufficiency import ner_is_sufficient
from nes.v2_ner import extract_v2
from nes.v3_llm import llm_extract


async def ms_extract(raw_query: str) -> dict:
    """Run Manifest Search extraction with sufficiency-gated fallback."""
    sanitised, strip_log = sanitise_with_log(raw_query)
    v2_entities = extract_v2(sanitised)
    v2_entities["_raw"] = sanitised
    v2_entities["_strip_log"] = strip_log

    is_sufficient, failure_reason = ner_is_sufficient(v2_entities)
    if is_sufficient:
        log_ms_invocation(raw_query=sanitised, used_v3=False)
        return v2_entities

    v3_entities = await llm_extract(sanitised)
    v3_entities["_raw"] = sanitised
    v3_entities["_strip_log"] = strip_log
    v3_entities["_lang"] = v2_entities.get("_lang", "en")
    log_ms_invocation(raw_query=sanitised, used_v3=True)
    log_feedback(
        raw_query=sanitised,
        v2_output=v2_entities,
        v3_output=v3_entities,
        failure_reason=failure_reason or "unknown",
    )
    return v3_entities
