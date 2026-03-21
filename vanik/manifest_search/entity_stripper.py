"""Strip entities before NER — delegates to ``dictionary`` index + regex fallbacks."""

from __future__ import annotations

from pathlib import Path

from dictionary.entity_stripper import append_sanitisation_audit
from dictionary.entity_stripper import reset_dictionary_index_cache
from dictionary.entity_stripper import strip_entities
from dictionary.seeds import load_entity_registry_into_index


def _default_registry_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "entity_registry.yaml"


def load_entity_patterns(registry_path: str | Path | None = None) -> str:
    """
    Reload entity registry YAML into the dictionary DB (replaces ``dict_type=entity``).

    Resets the in-process index handle so subsequent lookups use the updated database.
    Returns ``batch_id`` from ingestion, or empty string if the registry file is missing.
    """
    reset_dictionary_index_cache()
    return load_entity_registry_into_index(registry_path)


__all__ = [
    "append_sanitisation_audit",
    "load_entity_patterns",
    "strip_entities",
    "_default_registry_path",
]
