import asyncio
from unittest.mock import patch

from nes.orchestrator import ms_extract


def test_ms_orchestrator_returns_entities() -> None:
    entities = asyncio.run(ms_extract("duty on brake parts india to uk"))
    assert entities["product_terms"]


def test_ms_orchestrator_sets_raw_on_v3_fallback() -> None:
    with (
        patch(
            "nes.orchestrator.extract_v2",
            return_value={
                "product_terms": ["brake parts"],
                "origin": "IN",
                "destination": None,
                "hs_code_provided": None,
            },
        ),
        patch(
            "nes.orchestrator.llm_extract",
            return_value={
                "product_terms": ["brake parts"],
                "origin": "IN",
                "destination": "GB",
                "hs_code_provided": None,
            },
        ),
    ):
        entities = asyncio.run(ms_extract("duty on brake parts from india"))

    assert entities["_raw"] == "duty on brake parts from india"
