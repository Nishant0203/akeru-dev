"""Haiku / GPT-4o-mini extraction for MS v3 — via call_llm + parse_llm_json."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from agent.json_parser import parse_llm_json
from agent.prompts import MS_V3_EXTRACTION
from agent.providers import call_llm, get_completion_client, get_model_name
from nes.language import detect_language

logger = logging.getLogger(__name__)

_extraction_error: str | None = None

_CREDENTIAL_ERRORS = (
    "api_key",
    "authentication",
    "unauthorized",
    "permission",
    "api key",
    "invalid x-api-key",
)


def _is_credential_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(k in msg for k in _CREDENTIAL_ERRORS)


def _get_extraction_error() -> str | None:
    return _extraction_error


def _set_extraction_error(msg: str | None) -> None:
    global _extraction_error
    _extraction_error = msg


def _empty_result(query: str) -> dict[str, Any]:
    return {
        "product_terms": [],
        "hs_code_provided": None,
        "origin": None,
        "destination": None,
        "quantity": None,
        "unit_value_usd": None,
        "_lang": detect_language(query),
    }


def _coerce_product_terms(val: object) -> list[str]:
    if val is None:
        return []
    if isinstance(val, str) and val.strip():
        return [val.strip()]
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    return []


def extract_ms_v3_llm(sanitised_query: str) -> dict[str, Any]:
    """
    Call configured extraction model. Returns parsed dict or {} on failure.
    Sets _extraction_error for debugging; use llm_extract() for full entity shape.
    """
    _set_extraction_error(None)
    q = (sanitised_query or "").strip()
    if not q:
        return {}

    try:
        client = get_completion_client()
    except Exception as exc:
        _set_extraction_error(str(exc))
        logger.warning("v3_llm: no client: %s", exc)
        return {}

    model = get_model_name("extraction")
    max_tokens = int(os.getenv("VANIK_EXTRACTION_MAX_TOKENS", "512"))

    try:
        text = call_llm(
            client,
            system=MS_V3_EXTRACTION,
            user=q,
            model=model,
            max_tokens=max_tokens,
            temperature=0.1,
        )
    except Exception as exc:
        _set_extraction_error(str(exc))
        logger.warning("v3_llm: call failed: %s", exc)
        return {}

    parsed = parse_llm_json(text)
    if not isinstance(parsed, dict):
        _set_extraction_error("parse_llm_json returned non-dict")
        return {}

    return parsed


async def llm_extract(raw_query: str) -> dict[str, Any]:
    """Extract trade entities using the configured extraction model (threaded)."""
    text = (raw_query or "").strip()
    if not text:
        return _empty_result("")

    try:
        get_completion_client()
    except (RuntimeError, ValueError) as exc:
        logger.error("v3_llm client init failed: %s", exc)
        return {"_extraction_error": "configuration", **_empty_result(text)}
    except Exception as exc:
        logger.error("v3_llm client init failed: %s", exc)
        return {"_extraction_error": "configuration", **_empty_result(text)}

    def _run() -> dict[str, Any]:
        try:
            return extract_ms_v3_llm(text)
        except Exception as exc:
            if _is_credential_error(exc):
                raise
            logger.error("v3_llm extract failed: %s", exc)
            return {}

    try:
        result = await asyncio.to_thread(_run)
    except Exception as exc:
        if _is_credential_error(exc):
            logger.error("v3_llm credential error: %s", exc)
            return {"_extraction_error": "credential", **_empty_result(text)}
        logger.error("v3_llm call failed (transient): %s", exc)
        result = {}

    pts = _coerce_product_terms(result.get("product_terms"))

    return {
        "product_terms": pts,
        "hs_code_provided": result.get("hs_code_provided"),
        "origin": result.get("origin"),
        "destination": result.get("destination"),
        "quantity": result.get("quantity"),
        "unit_value_usd": result.get("unit_value_usd"),
        "_lang": detect_language(text),
    }
