"""Normalise MCP / tool results before synthesis — no raw exceptions to synthesiser."""

from __future__ import annotations

import asyncio


def normalise_rate_result(raw: dict | Exception, corridor: str) -> dict:
    """
    corridor: logical key "GB" | "EU" | "IN" (maps to lookup destination).
    """
    if isinstance(raw, asyncio.TimeoutError):
        return {"corridor": corridor, "status": "unavailable", "reason": "timeout"}

    if isinstance(raw, Exception):
        return {
            "corridor": corridor,
            "status": "unavailable",
            "reason": str(raw)[:120],
        }

    if isinstance(raw, dict) and raw.get("ok") is False:
        err = raw.get("error", {})
        return {
            "corridor": corridor,
            "status": "unavailable",
            "reason": err.get("message", "upstream_error"),
            "code": err.get("code", "unknown"),
        }

    data = raw.get("data", {}) if isinstance(raw, dict) else {}
    return {
        "corridor": corridor,
        "status": "ok",
        "mfn_rate_pct": data.get("mfn_rate_pct"),
        "source": data.get("source"),
        "measure_type": data.get("measure_type"),
        "retrieved_at": data.get("retrieved_at"),
        "fta_available": data.get("fta_available", False),
        "igst_note": data.get("igst_note"),
        "indicator": data.get("indicator"),
        "year": data.get("year"),
    }


def to_synthesis_rate(norm: dict) -> dict:
    """Shape expected by synthesiser.build uk_rate / eu_rate / in_rate (inner data fields)."""
    if norm.get("status") != "ok":
        return {}
    return {
        "mfn_rate_pct": norm.get("mfn_rate_pct"),
        "source": norm.get("source"),
        "measure_type": norm.get("measure_type"),
        "retrieved_at": norm.get("retrieved_at"),
        "fta_available": norm.get("fta_available", False),
        "igst_note": norm.get("igst_note"),
        "indicator": norm.get("indicator"),
        "year": norm.get("year"),
    }


def to_corridor_error(norm: dict) -> dict | None:
    if norm.get("status") == "ok":
        return None
    return {
        "code": norm.get("code", "unavailable"),
        "message": norm.get("reason", "unavailable"),
        "source": norm.get("corridor", ""),
    }
