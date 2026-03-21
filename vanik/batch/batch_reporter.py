"""Serialise batch results to CSV (Lane B reference columns first when provided)."""

from __future__ import annotations

import csv
import io
import json
from typing import Any


def _collect_ref_keys(rows: list[dict[str, Any]], lane_b: list[dict[str, Any] | None] | None) -> list[str]:
    seen: set[str] = set()
    keys: list[str] = []
    for r in rows:
        ref = r.get("reference") or {}
        if isinstance(ref, dict):
            for k in ref:
                ks = str(k)
                if ks not in seen:
                    seen.add(ks)
                    keys.append(ks)
    if lane_b:
        for rb in lane_b:
            if not isinstance(rb, dict):
                continue
            for k in rb:
                ks = str(k)
                if ks not in seen:
                    seen.add(ks)
                    keys.append(ks)
    return keys


def results_to_csv(
    rows: list[dict[str, Any]],
    *,
    lane_b: list[dict[str, Any] | None] | None = None,
) -> str:
    """CSV with optional Lane B columns, then standard result columns."""
    ref_keys = _collect_ref_keys(rows, lane_b)

    base_fields = [
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
    fieldnames = ref_keys + base_fields
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    w.writeheader()

    for i, r in enumerate(rows):
        ref: dict[str, Any] = {}
        if lane_b and i < len(lane_b) and lane_b[i]:
            ref.update(lane_b[i] or {})
        row_ref = r.get("reference")
        if isinstance(row_ref, dict):
            for k, v in row_ref.items():
                ref.setdefault(k, v)

        resp = r.get("response") or {}
        lc = (
            resp.get("data_part", {})
            .get("data", {})
            .get("vanik.compliance.LandedCost", {})
        )
        narrative = resp.get("narrative", "") if isinstance(resp, dict) else ""
        row_out: dict[str, Any] = {}
        for k in ref_keys:
            row_out[k] = ref.get(k, "")
        row_out.update(
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
        w.writerow(row_out)
    return buf.getvalue()
