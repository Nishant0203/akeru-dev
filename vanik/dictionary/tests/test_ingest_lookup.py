"""Dictionary ingestor + index + product resolver."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dictionary.ingestor import DictionaryEntry, DictionaryIngestor
from dictionary.dictionary_index import DictionaryIndex


@pytest.fixture()
def dict_db(tmp_path: Path) -> Path:
    return tmp_path / "dictionary.db"


def test_ingest_entries_lookup_exact_alias_fts_fuzzy(dict_db: Path, monkeypatch) -> None:
    monkeypatch.setenv("VANIK_DICTIONARY_DB", str(dict_db))
    from dictionary.entity_stripper import reset_dictionary_index_cache

    reset_dictionary_index_cache()

    ing = DictionaryIngestor(dict_db)
    entries = [
        DictionaryEntry(
            canonical="Cotton shirts",
            dict_type="product",
            aliases=["shirts of cotton", "woven cotton shirts"],
            metadata={"chapter": "62", "hs_heading": "6205"},
        )
    ]
    bid = ing.ingest_entries(entries, "product", source_name="test")
    assert bid

    idx = DictionaryIndex(str(dict_db))
    r1 = idx.lookup("cotton shirts", "product")
    assert r1.found and r1.match_method == "exact"

    r2 = idx.lookup("shirts of cotton", "product")
    assert r2.found and r2.match_method in ("alias", "fts", "exact")

    r3 = idx.lookup("woven cotton shirt", "product")
    assert r3.found and r3.metadata.get("chapter") == "62"


def test_product_resolver_unknown(dict_db: Path, monkeypatch) -> None:
    monkeypatch.setenv("VANIK_DICTIONARY_DB", str(dict_db))
    from dictionary.entity_stripper import reset_dictionary_index_cache
    from manifest_search.product_resolver import resolve

    reset_dictionary_index_cache()
    DictionaryIngestor(dict_db).ingest_entries([], "product", source_name="empty")

    pr = resolve("anything")
    assert pr.status == "unknown"


def test_product_resolver_resolved(dict_db: Path, monkeypatch) -> None:
    monkeypatch.setenv("VANIK_DICTIONARY_DB", str(dict_db))
    from dictionary.entity_stripper import reset_dictionary_index_cache
    from manifest_search.product_resolver import resolve

    reset_dictionary_index_cache()
    DictionaryIngestor(dict_db).ingest_entries(
        [
            DictionaryEntry(
                canonical="Brake calliper",
                dict_type="product",
                aliases=["brake caliper"],
                metadata={"chapter": "87"},
            )
        ],
        "product",
    )
    pr = resolve("brake caliper")
    assert pr.status == "resolved"
    assert pr.canonical == "Brake calliper"
    assert pr.chapter_hint == "87"


def test_ingest_json_csv(dict_db: Path) -> None:
    ing = DictionaryIngestor(dict_db)
    jpath = dict_db.parent / "p.json"
    jpath.write_text(
        json.dumps(
            [
                {
                    "canonical": "Widget A",
                    "aliases": ["widget-a"],
                    "sku": "W1",
                }
            ]
        ),
        encoding="utf-8",
    )
    ing.ingest_json(jpath, "product")
    idx = DictionaryIndex(str(dict_db))
    assert idx.lookup("Widget A", "product").found

    csv_path = dict_db.parent / "e.csv"
    csv_path.write_text("canonical,aliases,country\nAcme Corp,\"ACME,Acme\",US\n", encoding="utf-8")
    ing.ingest_csv(csv_path, "entity", metadata_cols=["country"])
    er = idx.lookup("acme", "entity")
    assert er.found
    assert er.metadata.get("country") == "US"
