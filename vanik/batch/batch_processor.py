"""Run Vanik agent over many items with chunking, dedupe, and bounded concurrency."""

from __future__ import annotations

import asyncio
import copy
import os
from typing import Any

from agent.vanik_agent import vanik_agent

DEFAULT_CONCURRENCY = 5


def batch_max_items() -> int:
    """Maximum rows per batch job (upload + synchronous /v1/batch)."""
    try:
        return max(1, min(10000, int(os.getenv("VANIK_BATCH_MAX_ITEMS", "10000"))))
    except ValueError:
        return 10000


def batch_chunk_size() -> int:
    try:
        return max(50, min(2000, int(os.getenv("VANIK_BATCH_CHUNK_SIZE", "500"))))
    except ValueError:
        return 500


def _dedupe_key(item: dict[str, Any]) -> str:
    return f"{item.get('query', '')}\0{item.get('hs_code') or ''}"


async def _one(
    idx: int,
    item: dict[str, Any],
    *,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    query = item["query"]
    hs = item.get("hs_code")
    async with semaphore:
        if hs:
            result = await vanik_agent(query, hs_code_provided=hs)
            needs_review = False
        else:
            result = await vanik_agent(query, gate_selection="__auto__")
            needs_review = True
    row: dict[str, Any] = {
        "index": idx,
        "query": query,
        "hs_code_input": hs or "",
        "needs_review": needs_review,
        "ok": bool(result.get("ok")),
        "status": result.get("status"),
        "message": result.get("message"),
        "response": result,
    }
    if item.get("reference"):
        row["reference"] = item["reference"]
    return row


async def process_batch(
    items: list[dict[str, Any]],
    *,
    max_concurrent: int | None = None,
) -> list[dict[str, Any]]:
    limit = max_concurrent if max_concurrent is not None else int(
        os.getenv("VANIK_BATCH_CONCURRENCY", str(DEFAULT_CONCURRENCY))
    )
    limit = max(1, min(limit, 32))
    sem = asyncio.Semaphore(limit)
    chunk_sz = batch_chunk_size()
    cache: dict[str, dict[str, Any]] = {}
    ordered: list[dict[str, Any] | None] = [None] * len(items)

    async def run_at(global_idx: int, item: dict[str, Any]) -> None:
        key = _dedupe_key(item)
        if key in cache:
            base = copy.deepcopy(cache[key])
            base["index"] = global_idx
            base["query"] = item["query"]
            base["hs_code_input"] = item.get("hs_code") or ""
            if item.get("reference") is not None:
                base["reference"] = item["reference"]
            ordered[global_idx] = base
            return
        row = await _one(global_idx, item, semaphore=sem)
        cache[key] = copy.deepcopy(row)
        ordered[global_idx] = row

    for start in range(0, len(items), chunk_sz):
        chunk = items[start : start + chunk_sz]
        await asyncio.gather(
            *[run_at(start + j, chunk[j]) for j in range(len(chunk))],
        )
        await asyncio.sleep(0)

    return [r for r in ordered if r is not None]
