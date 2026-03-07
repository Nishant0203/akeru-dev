"""Generate synthetic Manifest Search training examples (stub)."""

from __future__ import annotations

import json
from pathlib import Path


async def generate_training_data(n: int = 100) -> list[dict]:
    """Return deterministic synthetic examples for scaffold usage."""
    examples = [
        {
            "query": "duty on brake parts from india to uk",
            "entities": {
                "product_terms": ["brake parts", "brakes"],
                "hs_code_provided": None,
                "origin": "IN",
                "destination": "GB",
                "quantity": None,
                "unit_value_usd": None,
            },
        }
    ]
    payload = examples[: max(1, min(n, len(examples)))]

    out = Path(__file__).resolve().parents[1] / "nes" / "training_data" / "synthetic.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload
