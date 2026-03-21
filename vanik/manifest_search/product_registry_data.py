"""Load product_registry.yaml ambiguous_terms (cached)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

_YAML_PATH = Path(__file__).resolve().parent.parent / "data" / "product_registry.yaml"
_CACHE: dict[str, Any] | None = None


def product_registry_path() -> Path:
    return _YAML_PATH


def load_product_registry_yaml() -> dict[str, Any]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    if not _YAML_PATH.is_file():
        _CACHE = {"products": {}, "ambiguous_terms": {}}
        return _CACHE
    import yaml  # noqa: PLC0415

    _CACHE = yaml.safe_load(_YAML_PATH.read_text(encoding="utf-8")) or {}
    return _CACHE


def ambiguous_terms_map() -> dict[str, dict[str, Any]]:
    data = load_product_registry_yaml()
    raw = data.get("ambiguous_terms") or {}
    if not isinstance(raw, dict):
        return {}
    return {str(k).lower(): v for k, v in raw.items() if isinstance(v, dict)}


def reload_product_registry_cache() -> None:
    """Test helper."""
    global _CACHE
    _CACHE = None
