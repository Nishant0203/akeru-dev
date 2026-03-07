"""Output guardrails for agent responses."""

from __future__ import annotations

from typing import Any


def _is_valid_hs(code: Any) -> bool:
    value = str(code or "")
    return value.isdigit() and len(value) in {6, 8, 10}


def _is_optional_rate(value: Any) -> bool:
    """Accept None or a numeric rate in [0.0, 100.0] for compliance."""
    if value is None:
        return True
    if not isinstance(value, (int, float)):
        return False
    rate = float(value)
    return 0.0 <= rate <= 100.0


def validate_agent_output(payload: dict[str, Any]) -> tuple[bool, str | None]:
    """Validate minimum response schema before releasing agent output."""
    if not isinstance(payload, dict):
        return False, "agent output must be an object"
    if payload.get("ok") is not True:
        return False, "agent output must be successful before synthesis release"

    narrative = payload.get("narrative")
    if not isinstance(narrative, str) or not narrative.strip():
        return False, "narrative must be a non-empty string"

    data_part = payload.get("data_part")
    if not isinstance(data_part, dict):
        return False, "data_part is required"
    if data_part.get("kind") != "data":
        return False, "data_part.kind must be 'data'"

    data = data_part.get("data")
    if not isinstance(data, dict):
        return False, "data_part.data must be an object"

    landed_cost = data.get("vanik.compliance.LandedCost")
    if not isinstance(landed_cost, dict):
        return False, "vanik.compliance.LandedCost block is required"

    if not _is_valid_hs(landed_cost.get("hs_code")):
        return False, "landed cost hs_code must be a 6/8/10-digit code"

    for field in ("uk_mfn_rate_pct", "eu_mfn_rate_pct", "india_mfn_rate_pct", "mfn_rate_pct"):
        if not _is_optional_rate(landed_cost.get(field)):
            return False, f"{field} must be numeric or null"

    return True, None
