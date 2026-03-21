"""Run Vanik agent over many items with bounded concurrency."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from agent.vanik_agent import vanik_agent

DEFAULT_CONCURRENCY = 5


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
    return {
        "index": idx,
        "query": query,
        "hs_code_input": hs or "",
        "needs_review": needs_review,
        "ok": bool(result.get("ok")),
        "status": result.get("status"),
        "message": result.get("message"),
        "response": result,
    }


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
    tasks = [_one(i, row, semaphore=sem) for i, row in enumerate(items)]
    return await asyncio.gather(*tasks)
