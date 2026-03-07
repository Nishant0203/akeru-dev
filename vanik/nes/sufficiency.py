"""Manifest Search sufficiency checks and failure taxonomy."""

from __future__ import annotations

import re
from typing import Literal

FailureReason = Literal[
    "no_product_terms",
    "no_corridor",
    "hs_code_missed",
    "low_token_coverage",
    "unknown",
]

HS_PATTERN = re.compile(r"\b\d{6}(?:\d{2})?(?:\d{2})?\b")


def ner_is_sufficient(entities: dict) -> tuple[bool, FailureReason | None]:
    """Return sufficiency with explicit failure reason taxonomy."""
    if not entities.get("product_terms"):
        return False, "no_product_terms"

    if not entities.get("origin") and not entities.get("destination"):
        return False, "no_corridor"

    raw_query = str(entities.get("_raw", ""))
    if raw_query and HS_PATTERN.search(raw_query) and not entities.get("hs_code_provided"):
        return False, "hs_code_missed"

    coverage = entities.get("_token_coverage")
    if isinstance(coverage, (float, int)) and float(coverage) < 0.30:
        return False, "low_token_coverage"

    return True, None
