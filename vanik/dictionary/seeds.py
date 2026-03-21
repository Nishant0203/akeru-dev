"""Seed built-in dictionaries from YAML/JSON via the ingestion pipeline."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dictionary.ingestor import DictionaryEntry, DictionaryIngestor

log = logging.getLogger("vanik.dictionary")


def _vanik_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _default_index_path() -> Path:
    env = (os.getenv("VANIK_DICTIONARY_DB") or "").strip()
    return Path(env) if env else _vanik_root() / "var" / "dictionary.db"


def entity_yaml_to_entries(path: Path) -> list[DictionaryEntry]:
    """Parse entity_registry.yaml into DictionaryEntry rows (dict_type=entity)."""
    import yaml  # noqa: PLC0415

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entities = data.get("entities") or {}
    out: list[DictionaryEntry] = []
    for _key, entry in entities.items():
        if not isinstance(entry, dict):
            continue
        canonical = entry.get("canonical")
        names: list[str] = []
        if isinstance(canonical, str) and canonical.strip():
            names.append(canonical.strip())
        variants = entry.get("variants") or []
        if isinstance(variants, list):
            names.extend(str(v).strip() for v in variants if str(v).strip())
        if not names:
            continue
        canon = names[0]
        aliases = [n for n in names[1:] if n.lower() != canon.lower()]
        out.append(
            DictionaryEntry(
                canonical=canon,
                dict_type="entity",
                aliases=aliases,
                metadata={"registry_key": _key},
            )
        )
    return out


def product_yaml_to_entries(path: Path) -> list[DictionaryEntry]:
    """Parse product_registry.yaml products map into DictionaryEntry rows."""
    import yaml  # noqa: PLC0415

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    products = data.get("products") or {}
    out: list[DictionaryEntry] = []
    for key, entry in products.items():
        if not isinstance(entry, dict):
            continue
        canon = str(entry.get("canonical") or "").strip()
        if not canon:
            continue
        aliases = [str(a).strip() for a in (entry.get("aliases") or []) if str(a).strip()]
        miss = [str(a).strip() for a in (entry.get("common_misspellings") or []) if str(a).strip()]
        for m in miss:
            if m.lower() not in {a.lower() for a in aliases} and m.lower() != canon.lower():
                aliases.append(m)
        meta: dict = {
            "registry_key": key,
            "aliases": aliases,
        }
        if entry.get("chapter"):
            meta["chapter"] = str(entry["chapter"])
        if entry.get("hs_heading"):
            meta["hs_heading"] = str(entry["hs_heading"])
        out.append(
            DictionaryEntry(
                canonical=canon,
                dict_type="product",
                aliases=aliases,
                metadata=meta,
            )
        )
    return out


def load_product_registry_into_index(
    registry_path: str | Path | None = None,
    *,
    index_path: str | Path | None = None,
) -> str:
    """Ingest product_registry.yaml (replaces dict_type=product). Returns batch_id."""
    path = Path(registry_path) if registry_path else _vanik_root() / "data" / "product_registry.yaml"
    db = Path(index_path) if index_path else _default_index_path()
    if not path.is_file():
        log.warning("product registry missing: %s", path)
        return ""
    entries = product_yaml_to_entries(path)
    ingestor = DictionaryIngestor(db)
    return ingestor.ingest_entries(entries, "product", source_name=str(path))


def load_entity_registry_into_index(
    registry_path: str | Path | None = None,
    *,
    index_path: str | Path | None = None,
) -> str:
    """
    Ingest entity registry YAML into the dictionary DB (replaces all dict_type=entity).
    Returns batch_id.
    """
    path = Path(registry_path) if registry_path else _vanik_root() / "data" / "entity_registry.yaml"
    db = Path(index_path) if index_path else _default_index_path()
    if not path.is_file():
        log.warning("entity registry missing: %s", path)
        return ""
    entries = entity_yaml_to_entries(path)
    ingestor = DictionaryIngestor(db)
    return ingestor.ingest_entries(entries, "entity", source_name=str(path))


def ensure_builtin_entity_seed(index_path: str | Path | None = None) -> str | None:
    """
    If there are no entity rows, ingest default entity_registry.yaml.
    Called at app startup. Returns batch_id if seeded, else None.
    """
    root = _vanik_root()
    db_path = Path(index_path) if index_path else _default_index_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    ingestor = DictionaryIngestor(db_path)
    # Use a lightweight count via new connection
    from dictionary.dictionary_index import DictionaryIndex

    idx = DictionaryIndex(str(db_path))
    if idx.count_entries("entity") > 0:
        return None
    yaml_path = root / "data" / "entity_registry.yaml"
    if not yaml_path.is_file():
        return None
    bid = load_entity_registry_into_index(yaml_path, index_path=db_path)
    log.info("dictionary: seeded entity registry batch=%s", bid)
    return bid


def ensure_builtin_product_seed(index_path: str | Path | None = None) -> str | None:
    """If there are no product rows, ingest default product_registry.yaml."""
    root = _vanik_root()
    db_path = Path(index_path) if index_path else _default_index_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    DictionaryIngestor(db_path)
    from dictionary.dictionary_index import DictionaryIndex

    idx = DictionaryIndex(str(db_path))
    if idx.count_entries("product") > 0:
        return None
    yaml_path = root / "data" / "product_registry.yaml"
    if not yaml_path.is_file():
        return None
    bid = load_product_registry_into_index(yaml_path, index_path=db_path)
    log.info("dictionary: seeded product registry batch=%s", bid)
    return bid
