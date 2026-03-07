"""Tool layer for MFN lookup and corridor metadata."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime

from mcp_servers.vanik_api.clients.eu_tariff import get_eu_mfn_rate
from mcp_servers.vanik_api.clients.uk_tariff import get_uk_mfn_rate
from mcp_servers.vanik_api.clients.wto import get_india_mfn_rate
from mcp_servers.vanik_api.config import settings
from mcp_servers.vanik_api.errors import VanikAPIError
from mcp_servers.vanik_api.runtime import CircuitBreaker, TTLRateCache

try:
    from nes.feedback_store import fallback_rate_24h, v3_invocations_24h
except Exception:  # pragma: no cover
    fallback_rate_24h = None
    v3_invocations_24h = None

rate_cache = TTLRateCache(ttl_seconds=settings.rate_cache_ttl_seconds)

_breakers = {
    "IN": CircuitBreaker(
        failure_threshold=settings.circuit_failure_threshold,
        failure_window_seconds=settings.circuit_failure_window_seconds,
        probe_timeout_seconds=settings.circuit_probe_timeout_seconds,
    ),
    "GB": CircuitBreaker(
        failure_threshold=settings.circuit_failure_threshold,
        failure_window_seconds=settings.circuit_failure_window_seconds,
        probe_timeout_seconds=settings.circuit_probe_timeout_seconds,
    ),
    "EU": CircuitBreaker(
        failure_threshold=settings.circuit_failure_threshold,
        failure_window_seconds=settings.circuit_failure_window_seconds,
        probe_timeout_seconds=settings.circuit_probe_timeout_seconds,
    ),
}


def _ok(payload: dict) -> dict:
    return {"ok": True, "data": payload}


def _err(exc: VanikAPIError) -> dict:
    return {"ok": False, "error": exc.to_dict()}


def _cache_key(hs_code: str, destination: str) -> str:
    day = datetime.now(UTC).date().isoformat()
    return f"mfn:{hs_code}:{destination}:{day}"


def _is_circuit_counted_failure(exc: VanikAPIError) -> bool:
    return exc.code in {"upstream_unreachable", "upstream_error", "parse_error"}


def _fetch_live_rate(hs_code: str, destination: str) -> dict:
    if destination == "IN":
        record = get_india_mfn_rate(hs_code[:6])
        return {
            **asdict(record),
            "destination": "IN",
            "retrieved_at": datetime.now(UTC).isoformat(),
        }

    if destination == "GB":
        record = get_uk_mfn_rate(hs_code)
        return {
            **asdict(record),
            "destination": "GB",
            "retrieved_at": datetime.now(UTC).isoformat(),
        }

    if destination == "EU":
        record = get_eu_mfn_rate(hs_code)
        return {
            **asdict(record),
            "destination": "EU",
            "retrieved_at": datetime.now(UTC).isoformat(),
        }

    raise VanikAPIError(
        code="unsupported_destination",
        message=f"Destination '{destination}' is not supported",
        source="vanik_api",
        details={"supported": ["GB", "EU", "IN"]},
    )


def get_mfn_rate(hs_code: str, destination: str) -> dict:
    """Return normalized MFN data for GB/EU/IN destinations."""
    destination = destination.upper().strip()
    if not hs_code:
        return {
            "ok": False,
            "error": {
                "code": "invalid_hs_code",
                "message": "HS code is required",
                "source": "vanik_api",
            },
        }

    if destination not in {"GB", "EU", "IN"}:
        return {
            "ok": False,
            "error": {
                "code": "unsupported_destination",
                "message": f"Destination '{destination}' is not supported",
                "source": "vanik_api",
                "details": {"supported": ["GB", "EU", "IN"]},
            },
        }

    key = _cache_key(hs_code, destination)
    cached = rate_cache.get(key)
    if cached:
        return _ok(
            {
                **cached,
                "cache_hit": True,
                "cached_at": cached.get("retrieved_at"),
                "circuit_open": _breakers[destination].snapshot()["state"] == "open",
            }
        )

    breaker = _breakers[destination]
    if not breaker.allow_request():
        return {
            "ok": False,
            "error": {
                "code": "circuit_open",
                "message": f"{destination} tariff API is temporarily unavailable. Try again in a few minutes.",
                "source": "vanik_api",
            },
        }

    try:
        payload = _fetch_live_rate(hs_code, destination)
        payload["cache_hit"] = False
        payload["circuit_open"] = False
        rate_cache.set(key, payload)
        breaker.record_success()
        return _ok(payload)
    except VanikAPIError as exc:
        if _is_circuit_counted_failure(exc):
            breaker.record_failure()
        return _err(exc)


def get_supported_corridors() -> dict:
    """Return currently supported origin-destination pairs."""
    return {
        "ok": True,
        "data": {
            "corridors": [
                {"origin": "IN", "destination": "GB"},
                {"origin": "IN", "destination": "EU"},
                {"origin": "WORLD", "destination": "IN"},
            ]
        },
    }


def get_health() -> dict:
    """Return lightweight runtime health diagnostics."""
    api_status = "ok"
    breaker_state = {k: b.snapshot() for k, b in _breakers.items()}
    if any(v["state"] == "open" for v in breaker_state.values()):
        api_status = "degraded"

    ms_block: dict = {
        "fallback_rate_24h_pct": None,
        "v3_invocations_24h": None,
    }
    if callable(fallback_rate_24h) and callable(v3_invocations_24h):
        ms_block = {
            "fallback_rate_24h_pct": round(float(fallback_rate_24h()) * 100.0, 2),
            "v3_invocations_24h": int(v3_invocations_24h()),
        }

    return {
        "status": "ok",
        "timestamp": datetime.now(UTC).isoformat(),
        "components": {
            "vanik_api": {
                "status": api_status,
                "rate_cache": rate_cache.metrics(),
                "circuit_breakers": breaker_state,
            },
            "manifest_search": {
                "status": "ok",
                **ms_block,
            },
        },
    }
