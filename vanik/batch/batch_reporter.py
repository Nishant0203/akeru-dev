"""Serialise batch results to CSV."""

from __future__ import annotations

import csv
import io
import json
from typing import Any


def results_to_csv(rows: list[dict[str, Any]]) -> str:
    """CSV with needs_review and a JSON column for the full agent response."""
    buf = io.StringIO()
    fieldnames = [
        "index",
        "query",
        "hs_code_input",
        "needs_review",
        "ok",
        "status",
        "message",
        "narrative",
        "hs_code_out",
        "response_json",
    ]
    w = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        resp = r.get("response") or {}
        lc = (
            resp.get("data_part", {})
            .get("data", {})
            .get("vanik.compliance.LandedCost", {})
        )
        narrative = resp.get("narrative", "") if isinstance(resp, dict) else ""
        w.writerow(
            {
                "index": r.get("index", ""),
                "query": r.get("query", ""),
                "hs_code_input": r.get("hs_code_input", ""),
                "needs_review": "true" if r.get("needs_review") else "false",
                "ok": "true" if r.get("ok") else "false",
                "status": r.get("status", ""),
                "message": (r.get("message") or "")[:500],
                "narrative": (narrative or "")[:2000],
                "hs_code_out": lc.get("hs_code", "") if isinstance(lc, dict) else "",
                "response_json": json.dumps(resp, ensure_ascii=False)[:8000],
            }
        )
    return buf.getvalue()
