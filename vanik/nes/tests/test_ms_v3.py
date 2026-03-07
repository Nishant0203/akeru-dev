import asyncio

from nes.v3_llm import llm_extract


def test_ms_v3_fallback_shape() -> None:
    entities = asyncio.run(llm_extract("random query"))
    assert "product_terms" in entities
