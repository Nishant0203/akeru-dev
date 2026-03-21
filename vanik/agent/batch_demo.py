"""Batch demo: 100 synthetic POs, static snapshot, optional live run, corridor analysis."""

from __future__ import annotations

import asyncio
from typing import Any

from agent.corridor_analyser import analyse_corridors
from agent.vanik_agent import vanik_agent
from batch.batch_parser import _expand_place
from data.batch_demo_pos import DEMO_POS

_DEMO_SEM = asyncio.Semaphore(5)


def _enrich_result_row(r: dict[str, Any]) -> dict[str, Any]:
    """
    Add calculable / total_* fields on landed, flat PO fields, and landed_cost alias
    (stable contract for API clients and tests).
    """
    L = r.get("landed")
    if L is None:
        r["landed"] = {"calculable": False}
        L = r["landed"]
    elif not L:
        L["calculable"] = False
    else:
        lu = L.get("landed_usd")
        du = L.get("duty_usd")
        if lu is not None and du is not None:
            L["calculable"] = True
            L.setdefault("total_landed_usd", lu)
            L.setdefault("total_duty_usd", du)
        else:
            L["calculable"] = False

    m = r.get("demo_meta") or {}
    r["product"] = m.get("product")
    r["origin"] = m.get("origin")
    r["destination"] = m.get("destination")
    r["hs_code"] = m.get("hs_code") or L.get("hs_code")
    r["hs_provided"] = bool(m.get("hs_code"))
    r["incoterms"] = m.get("incoterm")
    r["landed_cost"] = L
    return r


def pos_row_to_agent_item(row: dict[str, Any]) -> dict[str, Any]:
    q = (
        f"{row['product']} from {_expand_place(row['origin'])} "
        f"to {_expand_place(row['destination'])}"
    )
    item: dict[str, Any] = {
        "query": q,
        "hs_code": row.get("hs_code") or None,
        "demo_po": row["po"],
        "demo_meta": {
            "product": row["product"],
            "origin": row["origin"],
            "destination": row["destination"],
            "hs_code": row.get("hs_code"),
            "quantity": row.get("quantity"),
            "unit_value_usd": row.get("unit_value_usd"),
            "incoterm": row.get("incoterm", "FOB"),
            "notes": row.get("notes"),
            "tags": row.get("tags", []),
            "flags": row.get("flags", []),
        },
    }
    if row.get("quantity") is not None:
        item["quantity"] = row["quantity"]
    if row.get("unit_value_usd") is not None:
        item["unit_value_usd"] = row["unit_value_usd"]
    return item


def _landed_from_agent(resp: dict[str, Any], dest: str) -> dict[str, Any]:
    """Extract corridor rates from successful agent payload."""
    out: dict[str, Any] = {
        "uk_mfn_rate_pct": None,
        "eu_mfn_rate_pct": None,
        "india_mfn_rate_pct": None,
        "hs_code_out": None,
        "description": "",
    }
    if not resp.get("ok"):
        return out
    lc = (
        resp.get("data_part", {})
        .get("data", {})
        .get("vanik.compliance.LandedCost", {})
    )
    if isinstance(lc, dict):
        out["hs_code_out"] = lc.get("hs_code")
        out["description"] = str(lc.get("description", ""))[:500]
        out["uk_mfn_rate_pct"] = lc.get("uk_mfn_rate_pct")
        out["eu_mfn_rate_pct"] = lc.get("eu_mfn_rate_pct")
        out["india_mfn_rate_pct"] = lc.get("india_mfn_rate_pct")
    return out


def _synthetic_static_row(idx: int, row: dict[str, Any]) -> dict[str, Any]:
    """Deterministic demo row without calling external tariff APIs."""
    meta = pos_row_to_agent_item(row)
    flags = row.get("flags") or []
    po = row["po"]
    uv = float(row.get("unit_value_usd") or 10.0)
    qty = float(row.get("quantity") or 1.0)
    dest = row["destination"].upper()

    if "ambiguous" in flags:
        return {
            "index": idx,
            "po": po,
            "ok": False,
            "status": "awaiting_disambiguation",
            "needs_review": True,
            "query": meta["query"],
            "demo_meta": meta["demo_meta"],
            "message": "Ambiguous product term — disambiguation required (demo static).",
            "spell_note": None,
            "landed": {},
            "response": {"ok": False, "status": "awaiting_disambiguation"},
        }

    if "ddp" in flags:
        rate = 12.0 if dest in ("GB", "EU") else 10.0
        duty = uv * qty * (rate / 100.0) * 0.0
        return {
            "index": idx,
            "po": po,
            "ok": True,
            "status": "ok",
            "needs_review": True,
            "query": meta["query"],
            "demo_meta": meta["demo_meta"],
            "message": "DDP — duty embedded in price; rates shown for verification only.",
            "spell_note": None,
            "landed": {
                "hs_code": row.get("hs_code") or "n/a",
                "verification_rate_pct": rate,
                "goods_value_usd": round(uv * qty, 2),
                "duty_usd": 0.0,
                "landed_usd": round(uv * qty, 2),
                "basis": "DDP — seller responsible for import clearance",
            },
            "response": {"ok": True, "narrative": meta["demo_meta"].get("notes", "")},
        }

    hs = row.get("hs_code") or "6205200000"
    mfn = 12.0 if dest in ("GB", "EU") else 15.0
    if row.get("tags") and "steel" in row["tags"]:
        mfn = 0.0
    if row.get("tags") and "pharma" in row["tags"]:
        mfn = 0.0

    duty = uv * qty * (mfn / 100.0)
    spell_note = None
    if "typo" in flags:
        spell_note = "Spell correction: coton→cotton / callipars→callipers (demo)"

    return {
        "index": idx,
        "po": po,
        "ok": True,
        "status": "ok",
        "needs_review": not bool(row.get("hs_code")),
        "query": meta["query"],
        "demo_meta": meta["demo_meta"],
        "message": "",
        "spell_note": spell_note,
        "landed": {
            "hs_code": hs,
            "mfn_rate_pct": mfn,
            "goods_value_usd": round(uv * qty, 2),
            "duty_usd": round(duty, 2),
            "landed_usd": round(uv * qty + duty, 2),
            "duty_per_unit_usd": round(uv * (mfn / 100.0), 4),
            "landed_per_unit_usd": round(uv * (1 + mfn / 100.0), 4),
            "incoterm": row.get("incoterm", "FOB"),
        },
        "response": {
            "ok": True,
            "narrative": f"Static demo tariff at {mfn}% MFN to {dest} for illustration.",
        },
    }


def _build_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    ok_n = sum(1 for r in results if r.get("ok"))
    review = sum(1 for r in results if r.get("needs_review"))
    failed = sum(1 for r in results if not r.get("ok"))
    goods = 0.0
    duty = 0.0
    landed = 0.0
    rates = 0
    for r in results:
        L = r.get("landed") or {}
        if L.get("goods_value_usd") is not None:
            try:
                goods += float(L["goods_value_usd"])
            except (TypeError, ValueError):
                pass
        if L.get("duty_usd") is not None:
            try:
                duty += float(L["duty_usd"])
            except (TypeError, ValueError):
                pass
        if L.get("landed_usd") is not None:
            try:
                landed += float(L["landed_usd"])
            except (TypeError, ValueError):
                pass
        if r.get("ok") and L.get("mfn_rate_pct") is not None:
            rates += 1
        if r.get("ok") and L.get("verification_rate_pct") is not None:
            rates += 1

    return {
        "total_rows": total,
        "ok": ok_n,
        "failed": failed,
        "needs_review": review,
        "rates_found": rates,
        "hs_provided": sum(
            1 for r in results if (r.get("demo_meta") or {}).get("hs_code")
        ),
        "total_goods_value_usd": round(goods, 2),
        "total_duty_usd": round(duty, 2),
        "total_landed_usd": round(landed, 2),
        # Aliases for HTTP clients / tests
        "total": total,
        "succeeded": ok_n,
        "total_goods_usd": round(goods, 2),
    }


def static_demo_payload() -> dict[str, Any]:
    full = [_synthetic_static_row(i, r) for i, r in enumerate(DEMO_POS)]
    for row in full:
        _enrich_result_row(row)
    summary = _build_summary(full)
    corridor = _static_corridor_snapshot()
    return {
        "ok": True,
        "mode": "static",
        "compliance_note": (
            "Static snapshot for instant UI load (11 illustrative rows + full summary). "
            "Add ?run=true to execute all 100 rows against live tariff tools."
        ),
        "summary": summary,
        "results": demo_sample_rows(full),
        "results_full_count": len(full),
        "corridor_analysis": corridor,
    }


def _static_corridor_snapshot() -> dict[str, Any]:
    """Illustrative multi-origin table for cotton shirts HS → GB/EU (no API)."""
    mfn = 12.0
    origins = [
        ("IN", 12.5, mfn, "MFN"),
        ("BD", 9.8, 0.0, "EBA illustrative 0%"),
        ("PK", 9.2, 0.0, "GSP+ illustrative 0%"),
        ("VN", 10.2, mfn, "MFN"),
        ("CN", 11.8, mfn, "MFN"),
    ]
    blocks = []
    for dest in ("GB", "EU"):
        rows = []
        for o, uv, eff, note in origins:
            duty = uv * (eff / 100.0)
            rows.append(
                {
                    "origin": o,
                    "destination": dest,
                    "unit_value_usd": uv,
                    "effective_duty_pct": eff,
                    "duty_basis": note,
                    "landed_per_unit_usd": round(uv + duty, 4),
                }
            )
        rows.sort(key=lambda x: x["landed_per_unit_usd"])
        blocks.append(
            {
                "product": "cotton shirts (illustrative)",
                "hs_code": "6205200000",
                "destination": dest,
                "ranked": rows,
                "recommended": rows[0] if rows else None,
            }
        )
    return {"products": blocks, "note": "Illustrative preference overlay; live tab uses API when run."}


async def _demo_one(idx: int, item: dict[str, Any]) -> dict[str, Any]:
    meta = item["demo_meta"]
    try:
        async with _DEMO_SEM:
            hs = item.get("hs_code")
            if hs:
                res = await vanik_agent(item["query"], hs_code_provided=str(hs))
            else:
                res = await vanik_agent(item["query"], gate_selection="__auto__")
    except Exception as exc:  # noqa: BLE001 — batch row isolation
        return {
            "index": idx,
            "po": item["demo_po"],
            "ok": False,
            "status": "error",
            "needs_review": True,
            "query": item["query"],
            "demo_meta": meta,
            "message": str(exc)[:800],
            "spell_note": None,
            "landed": {},
            "response": {"ok": False, "error": str(exc)},
        }

    dest = meta["destination"].upper()
    lc = _landed_from_agent(res, dest)
    uv = float(meta.get("unit_value_usd") or 0.0)
    qty = float(meta.get("quantity") or 0.0)
    rate = None
    if dest == "GB":
        rate = lc.get("uk_mfn_rate_pct")
    elif dest == "EU":
        rate = lc.get("eu_mfn_rate_pct")
    elif dest == "IN":
        rate = lc.get("india_mfn_rate_pct")

    duty = None
    landed = None
    if rate is not None and uv and qty:
        duty = uv * qty * (float(rate) / 100.0)
        landed = uv * qty + duty

    flags = meta.get("flags") or []
    needs_review = bool(res.get("status") == "awaiting_disambiguation") or (
        not hs and res.get("ok")
    )
    if "ddp" in flags:
        needs_review = True

    spell_note = None
    if "typo" in flags and res.get("ok"):
        spell_note = "Check narrative for corrected product wording (live run)."

    msg = str(res.get("message", "") or "")[:800]
    if "ddp" in flags:
        msg = (meta.get("notes") or "DDP — rate for verification.")[:800]

    return {
        "index": idx,
        "po": item["demo_po"],
        "ok": bool(res.get("ok")),
        "status": res.get("status", "unknown"),
        "needs_review": needs_review,
        "query": item["query"],
        "demo_meta": meta,
        "message": msg,
        "spell_note": spell_note,
        "landed": {
            "hs_code": lc.get("hs_code_out") or hs,
            "description": lc.get("description", ""),
            "mfn_rate_pct": rate,
            "goods_value_usd": round(uv * qty, 2) if uv and qty else None,
            "duty_usd": round(duty, 2) if duty is not None else None,
            "landed_usd": round(landed, 2) if landed is not None else None,
            "incoterm": meta.get("incoterm", "FOB"),
        },
        "response": res,
    }


async def _corridor_from_live_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    tasks: list[Any] = []
    keys: list[str] = []
    for r in results:
        if not r.get("ok"):
            continue
        hs = (r.get("landed") or {}).get("hs_code") or r.get("demo_meta", {}).get("hs_code")
        dest = r.get("demo_meta", {}).get("destination", "").upper()
        if not hs or dest not in ("GB", "EU"):
            continue
        k = f"{hs}|{dest}"
        if k in seen or len(seen) >= 6:
            continue
        seen.add(k)
        uv = r.get("demo_meta", {}).get("unit_value_usd")
        garment = "garment" in (r.get("demo_meta", {}).get("tags") or [])
        keys.append(k)
        tasks.append(
            analyse_corridors(
                str(hs),
                dest,
                unit_value_usd=float(uv) if uv is not None else None,
                quantity=1.0,
                garment_pricing=garment,
            )
        )
    if not tasks:
        return {"products": [], "note": "No GB/EU rows with HS for corridor comparison."}
    out = await asyncio.gather(*tasks, return_exceptions=True)
    products = []
    for k, block in zip(keys, out):
        if isinstance(block, Exception):
            continue
        if isinstance(block, dict) and block.get("ok"):
            hs, dest = k.split("|", 1)
            products.append(
                {
                    "product_key": k,
                    "hs_code": hs,
                    "destination": dest,
                    "analysis": block,
                }
            )
    return {"products": products, "note": "Live multi-origin comparison for sampled HS codes."}


async def run_demo_batch() -> dict[str, Any]:
    items = [pos_row_to_agent_item(r) for r in DEMO_POS]
    results: list[dict[str, Any]] = []
    chunk = 25
    for i in range(0, len(items), chunk):
        part = items[i : i + chunk]
        chunk_res = await asyncio.gather(
            *[_demo_one(i + j, part[j]) for j in range(len(part))],
        )
        results.extend(chunk_res)
        await asyncio.sleep(0)

    for row in results:
        _enrich_result_row(row)

    summary = _build_summary(results)
    corridor = await _corridor_from_live_results(results)
    return {
        "ok": True,
        "mode": "live",
        "compliance_note": (
            "Live run uses tariff APIs and auto gate selection where no HS was provided; "
            "results may vary with network and data availability."
        ),
        "summary": summary,
        "results": results,
        "results_full_count": len(results),
        "corridor_analysis": corridor,
        "sample_indices": list(range(min(11, len(results)))),
    }


def demo_sample_rows(full_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """First 11 illustrative rows for initial table paint."""
    ix = [0, 1, 2, 10, 20, 50, 85, 86, 95, 96, 99]
    out = []
    for i in ix:
        if 0 <= i < len(full_results):
            out.append(full_results[i])
    return out
