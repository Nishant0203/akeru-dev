"""Parse batch input from JSON body or embedded CSV string."""

from __future__ import annotations

import csv
import io
import json
from typing import Any


def parse_batch_body(body: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Accept:
    - {"items": [{"query": "...", "hs_code": "..." | null}, ...]}
    - {"format": "csv", "data": "query,hs_code\\nfoo,\\n"}  (header row required)
    """
    fmt = str(body.get("format", "json")).lower().strip()
    if fmt == "csv":
        raw = body.get("data") or body.get("csv") or ""
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("CSV batch requires non-empty 'data' or 'csv' string")
        return _parse_csv_string(raw)

    items = body.get("items")
    if not isinstance(items, list):
        raise ValueError("JSON batch requires an 'items' array")
    out: list[dict[str, Any]] = []
    for i, row in enumerate(items):
        if not isinstance(row, dict):
            raise ValueError(f"items[{i}] must be an object")
        q = row.get("query") or row.get("text") or row.get("q")
        if not q or not str(q).strip():
            raise ValueError(f"items[{i}] needs query/text/q")
        hs = row.get("hs_code") or row.get("hs_code_provided")
        out.append(
            {
                "query": str(q).strip(),
                "hs_code": str(hs).strip() if hs not in (None, "") else None,
            }
        )
    return out


def _parse_csv_string(data: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(data))
    if not reader.fieldnames:
        raise ValueError("CSV must include a header row")
    fields = {h.strip().lower(): h for h in reader.fieldnames if h}
    qkey = fields.get("query") or fields.get("text") or fields.get("q")
    if not qkey:
        raise ValueError("CSV header must include query, text, or q column")
    hskey = fields.get("hs_code") or fields.get("hs") or fields.get("hs_code_provided")
    rows: list[dict[str, Any]] = []
    for row in reader:
        q = (row.get(qkey) or "").strip()
        if not q:
            continue
        hs_raw = (row.get(hskey) or "").strip() if hskey else ""
        rows.append({"query": q, "hs_code": hs_raw or None})
    return rows


def parse_batch_bytes(content_type: str | None, raw: bytes) -> list[dict[str, Any]]:
    """Parse raw POST body: application/json or text/csv."""
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct == "text/csv":
        return _parse_csv_string(raw.decode("utf-8", errors="replace"))
    if ct in ("application/json", "") or ct == "application/json; charset=utf-8":
        body = json.loads(raw.decode("utf-8"))
        if isinstance(body, list):
            return parse_batch_body({"items": body})
        if isinstance(body, dict):
            return parse_batch_body(body)
        raise ValueError("JSON body must be object or array")
    raise ValueError(f"Unsupported content type: {content_type!r}")
