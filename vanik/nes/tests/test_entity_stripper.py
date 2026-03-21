"""Entity stripper — dictionary index + regex fallbacks."""

from __future__ import annotations

import pytest


def test_strip_tata_steel_and_grade(tmp_path, monkeypatch) -> None:
    pytest.importorskip("yaml")
    db = tmp_path / "dict.db"
    monkeypatch.setenv("VANIK_DICTIONARY_DB", str(db))
    from dictionary.entity_stripper import reset_dictionary_index_cache

    reset_dictionary_index_cache()

    reg = tmp_path / "entity_registry.yaml"
    reg.write_text(
        """
entities:
  tata:
    canonical: "Tata Steel"
    variants: []
""",
        encoding="utf-8",
    )
    import manifest_search.entity_stripper as es

    es.load_entity_patterns(reg)

    text = "Tata Steel grade S355 hot rolled coils from India to UK"
    cleaned, log = es.strip_entities(text)
    assert "Tata Steel" not in cleaned
    assert "S355" not in cleaned
    assert "hot rolled coils" in cleaned.lower()
    types = {e["type"] for e in log}
    assert "entity" in types
    assert "product_grade" in types


def test_strip_grade_without_named_entities(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("VANIK_DICTIONARY_DB", str(tmp_path / "d.db"))
    from dictionary.entity_stripper import reset_dictionary_index_cache

    reset_dictionary_index_cache()
    import manifest_search.entity_stripper as es

    cleaned, log = es.strip_entities("grade S355 coils")
    assert "S355" not in cleaned
    assert any(e["type"] == "product_grade" for e in log)


def test_hs_prefix_not_stripped_as_grade(tmp_path, monkeypatch) -> None:
    pytest.importorskip("yaml")
    db = tmp_path / "dict.db"
    monkeypatch.setenv("VANIK_DICTIONARY_DB", str(db))
    from dictionary.entity_stripper import reset_dictionary_index_cache

    reset_dictionary_index_cache()
    import manifest_search.entity_stripper as es

    es.load_entity_patterns(es._default_registry_path())
    cleaned, _ = es.strip_entities("HS 6103220000 cotton shirts from India to UK")
    assert "6103220000" in cleaned.replace(" ", "")
    assert "cotton" in cleaned.lower()
