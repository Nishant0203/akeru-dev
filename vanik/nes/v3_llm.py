"""Manifest Search v3: LLM extraction via Claude Haiku."""

from __future__ import annotations

import asyncio
import json
import logging

from agent.providers import get_completion_client
from nes.language import detect_language

logger = logging.getLogger(__name__)

_SYSTEM = """You are a trade compliance entity extractor.
Given a natural language trade query, extract the following fields and respond
with ONLY a valid JSON object - no preamble, no markdown, no explanation.

Fields:
  product_terms   : list[str]   - key product words/phrases (e.g. ["ceramic tiles"])
  hs_code_provided: str | null  - HS code if explicitly stated, else null
  origin          : str | null  - ISO-2 country code of export origin, or null
  destination     : str | null  - ISO-2 country code OR "EU" for EU bloc, or null
  quantity        : number | null
  unit_value_usd  : number | null

Destination rules:
  - Any EU member state as destination -> "EU"
  - United Kingdom / UK / Britain / GB -> "GB"
  - India / IN -> "IN"

Origin rules:
  - Resolve country names to ISO-2 codes
  - "UK" / "Britain" / "United Kingdom" as origin -> "GB"

If a field cannot be determined, use null."""

_USER_TMPL = "Query: {query}"

_CREDENTIAL_ERRORS = (
    "api_key", "authentication", "unauthorized",
    "permission", "api key", "invalid x-api-key",
)


def _is_credential_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(k in msg for k in _CREDENTIAL_ERRORS)


def _empty_result(query: str) -> dict:
    return {
        "product_terms": [],
        "hs_code_provided": None,
        "origin": None,
        "destination": None,
        "quantity": None,
        "unit_value_usd": None,
        "_lang": detect_language(query),
    }


def _extract_text_content(response: object) -> str:
    parts = getattr(response, "content", []) or []
    chunks: list[str] = []
    for part in parts:
        text = getattr(part, "text", None)
        if text:
            chunks.append(text)
    return "".join(chunks).strip()


def _strip_markdown_fences(raw: str) -> str:
    text = raw.strip()
    if not text.startswith("```"):
        return text

    text = text[3:]
    if text.lower().startswith("json"):
        text = text[4:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


async def llm_extract(raw_query: str) -> dict:
    """Extract trade entities from raw_query using Claude Haiku."""
    text = raw_query.strip()
    if not text:
        return _empty_result("")

    try:
        client = get_completion_client()
    except RuntimeError as exc:
        logger.error("v3_llm client init failed: %s", exc)
        return {
            "_extraction_error": "configuration",
            **_empty_result(text),
        }

    raw = ""
    try:
        response = await asyncio.to_thread(
            client.messages.create,
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            system=_SYSTEM,
            messages=[{"role": "user", "content": _USER_TMPL.format(query=text)}],
        )
        raw = _strip_markdown_fences(_extract_text_content(response))
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("v3_llm JSON parse failed: %s - raw: %r", exc, raw)
        result = {}
    except Exception as exc:
        if _is_credential_error(exc):
            logger.error("v3_llm credential error: %s", exc)
            return {
                "_extraction_error": "credential",
                **_empty_result(text),
            }
        logger.error("v3_llm call failed (transient): %s", exc)
        result = {}

    def _coerce_product_terms(val: object) -> list[str]:
        if val is None:
            return []
        if isinstance(val, str) and val.strip():
            return [val.strip()]
        if isinstance(val, list):
            out = [str(x).strip() for x in val if str(x).strip()]
            return out
        return []

    pts = _coerce_product_terms(result.get("product_terms"))
    # Never substitute the full raw query as product_terms (avoids FTS / search poisoning).

    return {
        "product_terms": pts,
        "hs_code_provided": result.get("hs_code_provided"),
        "origin": result.get("origin"),
        "destination": result.get("destination"),
        "quantity": result.get("quantity"),
        "unit_value_usd": result.get("unit_value_usd"),
        "_lang": detect_language(text),
    }
