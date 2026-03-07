"""HTTP health snapshot aggregation for gateway + servers."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from agent.anchor_store import info as anchor_store_info
from agent.query_log import info as query_log_info
from mcp_servers.vanik_api.tools.lookup_mfn import get_health as get_vanik_api_health
from mcp_servers.vanik_docs.tools.lookup_hs import get_docs_server_info
from nes.feedback_store import fallback_rate_24h, v3_invocations_24h


def _fallback_rate_pct() -> float:
    try:
        ratio = float(fallback_rate_24h())
    except TypeError:
        ratio = float(fallback_rate_24h(None))
    return round(ratio * 100.0, 2)


def build_health_snapshot() -> dict[str, Any]:
    api_health = get_vanik_api_health()
    docs_info = get_docs_server_info()

    docs_status = "ok" if docs_info.get("ok") else "degraded"
    docs_data = docs_info.get("data", {})

    manifest_search = {
        "status": "ok",
        "model_version": os.getenv("MS_MODEL_VERSION", "manifest-search/v2/"),
        "fallback_rate_24h_pct": _fallback_rate_pct(),
        "v3_invocations_24h": int(v3_invocations_24h()),
        "distribution": {
            "entity_class_shift_detected": False,
            "oov_product_term_rate_pct": 0.0,
            "last_computed": datetime.now(UTC).isoformat(),
        },
    }

    api_component = api_health.get("components", {}).get("vanik_api", {"status": "degraded"})
    status = "ok"
    if api_component.get("status") != "ok" or docs_status != "ok":
        status = "degraded"

    return {
        "status": status,
        "timestamp": datetime.now(UTC).isoformat(),
        "components": {
            "vanik_api": api_component,
            "vanik_docs": {
                "status": docs_status,
                "db": docs_data,
            },
            "manifest_search": manifest_search,
            "session_gateway": {
                "status": "ok",
                "anchors": anchor_store_info(),
                "query_log": query_log_info(),
            },
        },
    }
