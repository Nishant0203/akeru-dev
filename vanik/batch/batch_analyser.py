"""Non-LLM summaries over batch results + optional Lane B references."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def summarise_batch(
    rows: list[dict[str, Any]],
    *,
    lane_b: list[dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """
    Group outcomes for customer follow-up (needs_review, failures, EU issues).
    """
    needs_review: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    by_supplier: dict[str, list[int]] = defaultdict(list)

    for i, r in enumerate(rows):
        ref = (lane_b[i] if lane_b and i < len(lane_b) else None) or r.get("reference") or {}
        supplier = str(ref.get("supplier") or ref.get("Supplier") or "").strip()
        idx = int(r.get("index", i))
        if not r.get("ok"):
            failed.append({"index": idx, "status": r.get("status"), "message": r.get("message"), "reference": ref})
        elif r.get("needs_review"):
            entry = {"index": idx, "query": r.get("query"), "reference": ref}
            needs_review.append(entry)
            if supplier:
                by_supplier[supplier].append(idx)

    return {
        "total": len(rows),
        "succeeded": sum(1 for r in rows if r.get("ok")),
        "failed_count": len(failed),
        "needs_review_count": len(needs_review),
        "failed": failed[:200],
        "needs_review": needs_review[:200],
        "needs_review_by_supplier": {k: v[:50] for k, v in by_supplier.items()},
    }
