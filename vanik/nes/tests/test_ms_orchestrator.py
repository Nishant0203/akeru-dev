import asyncio

from nes.orchestrator import ms_extract


def test_ms_orchestrator_returns_entities() -> None:
    entities = asyncio.run(ms_extract("duty on brake parts india to uk"))
    assert entities["product_terms"]
