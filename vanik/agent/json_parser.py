"""Robust JSON extraction from LLM output (fences, trailing commas, preamble)."""

from __future__ import annotations

import json
import re


def parse_llm_json(text: str) -> dict | None:
    """Extract first valid JSON object from LLM response. Returns None if not found."""
    if not text or not str(text).strip():
        return None
    text = re.sub(r"```(?:json)?", "", text, flags=re.I).strip().rstrip("`").strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    cleaned = re.sub(r",\s*([}\]])", r"\1", text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    return None
