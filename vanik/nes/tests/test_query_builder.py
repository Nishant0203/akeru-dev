"""Query builder: spell correction, product resolution, disambiguation."""

from __future__ import annotations

from pathlib import Path

import pytest

from nes.query_builder import DisambiguationRequired, build_hs_search_terms


def test_disambiguation_steel() -> None:
    plan = build_hs_search_terms({"product_terms": ["steel"]})
    assert isinstance(plan, DisambiguationRequired)
    assert "steel" in plan.question.lower() or "form" in plan.question.lower()
    assert plan.options


def test_resolve_cotton_shirts(tmp_path, monkeypatch) -> None:
    pytest.importorskip("yaml")
    db = tmp_path / "d.db"
    monkeypatch.setenv("VANIK_DICTIONARY_DB", str(db))
    from dictionary.entity_stripper import reset_dictionary_index_cache
    from dictionary.seeds import load_product_registry_into_index

    reset_dictionary_index_cache()
    load_product_registry_into_index()

    plan = build_hs_search_terms({"product_terms": ["cotton shirts"]})
    assert isinstance(plan, list)
    assert len(plan) >= 1
    assert any("cotton" in p.lower() for p in plan)
