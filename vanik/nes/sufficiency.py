"""Manifest Search sufficiency checks and failure taxonomy."""

from __future__ import annotations

import re
from typing import Literal

FailureReason = Literal[
    "no_product_terms",
    "no_corridor",
    "ambiguous_origin",
    "hs_code_missed",
    "low_token_coverage",
    "unknown",
]

HS_PATTERN = re.compile(r"\b\d{6}(?:\d{2})?(?:\d{2})?\b")


def _normalize_codes(value: object) -> list[str]:
    if isinstance(value, str):
        normalized = value.strip().upper()
        return [normalized] if normalized else []
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for item in value:
            text = str(item).strip().upper()
            if text:
                out.append(text)
        return out
    return []


def ner_is_sufficient(entities: dict) -> tuple[bool, FailureReason | None]:
    """Return sufficiency with explicit failure reason taxonomy."""
    if not entities.get("product_terms"):
        return False, "no_product_terms"

    explicit_origin_codes = set(_normalize_codes(entities.get("origin")))
    if len(explicit_origin_codes) > 1:
        return False, "ambiguous_origin"

    candidate_origin_codes = set(
        _normalize_codes(entities.get("_origin_candidates") or entities.get("origin_candidates"))
    )
    if len(candidate_origin_codes) > 1 and not explicit_origin_codes:
        return False, "ambiguous_origin"

    if not entities.get("origin") and not entities.get("destination"):
        return False, "no_corridor"

    raw_query = str(entities.get("_raw", ""))
    if raw_query and HS_PATTERN.search(raw_query) and not entities.get("hs_code_provided"):
        return False, "hs_code_missed"

    coverage = entities.get("_token_coverage")
    if isinstance(coverage, (float, int)) and float(coverage) < 0.30:
        return False, "low_token_coverage"

    return True, None
