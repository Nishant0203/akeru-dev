"""Tool: lookup_landed_cost (stub)."""

from __future__ import annotations


def lookup_landed_cost(base_value_usd: float, mfn_rate_pct: float) -> dict:
    """Compute simple landed cost estimate."""
    estimated_duty = base_value_usd * (mfn_rate_pct / 100.0)
    total = base_value_usd + estimated_duty
    return {
        "base_value_usd": base_value_usd,
        "mfn_rate_pct": mfn_rate_pct,
        "estimated_duty_usd": round(estimated_duty, 2),
        "total_landed_cost_usd": round(total, 2),
    }
