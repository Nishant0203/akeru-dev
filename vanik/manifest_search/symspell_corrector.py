"""Domain spell correction — wordlist + rapidfuzz (SymSpell-style suggestions)."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterable

from rapidfuzz import fuzz, process

log = logging.getLogger(__name__)

_WORDS: set[str] = set()
_LOADED = False
_VANIK_ROOT = Path(__file__).resolve().parent.parent


def _tokenize_phrase(phrase: str) -> list[str]:
    return [t for t in re.split(r"[^\w]+", phrase.lower()) if len(t) > 1]


def _load_tariff_dictionary_file(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip().lower()
        if line and not line.startswith("#"):
            _WORDS.add(line)


def _words_from_product_yaml(path: Path) -> None:
    if not path.is_file():
        return
    try:
        import yaml  # noqa: PLC0415

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        products = data.get("products") or {}
        for entry in products.values():
            if not isinstance(entry, dict):
                continue
            for key in ("canonical", "aliases", "common_misspellings"):
                vals = entry.get(key) or []
                if isinstance(vals, str):
                    vals = [vals]
                if not isinstance(vals, list):
                    continue
                for v in vals:
                    for tok in _tokenize_phrase(str(v)):
                        if len(tok) > 2:
                            _WORDS.add(tok)
    except Exception as exc:
        log.warning("symspell: could not load product yaml: %s", exc)


def refresh_wordlist(
    *,
    tariff_dictionary_path: Path | None = None,
    product_registry_path: Path | None = None,
) -> int:
    """Rebuild in-memory word set. Returns token count."""
    global _WORDS, _LOADED
    _WORDS = set()
    td = tariff_dictionary_path or (_VANIK_ROOT / "data" / "tariff_dictionary.txt")
    pr = product_registry_path or (_VANIK_ROOT / "data" / "product_registry.yaml")
    _load_tariff_dictionary_file(td)
    _words_from_product_yaml(pr)
    _LOADED = True
    return len(_WORDS)


def _ensure_loaded() -> None:
    global _LOADED
    if not _LOADED:
        refresh_wordlist()


def suggest_token(token: str, *, score_cutoff: int = 88) -> str | None:
    """Return best matching dictionary token or None."""
    _ensure_loaded()
    t = token.lower().strip()
    if len(t) < 3 or not _WORDS:
        return None
    if t in _WORDS:
        return None
    choices = sorted(_WORDS)
    hit = process.extractOne(t, choices, scorer=fuzz.ratio, score_cutoff=score_cutoff)
    return hit[0] if hit else None


def correct(term: str, *, score_cutoff: int = 88) -> str:
    """
    Correct a multi-word phrase token-by-token (lightweight domain fixer).
    Unknown short tokens are left unchanged.
    """
    _ensure_loaded()
    raw = (term or "").strip()
    if not raw:
        return raw
    parts = re.split(r"(\s+)", raw)
    out: list[str] = []
    for p in parts:
        if not p.strip():
            out.append(p)
            continue
        if re.fullmatch(r"\d[\w.-]*", p):
            out.append(p)
            continue
        sug = suggest_token(p, score_cutoff=score_cutoff)
        out.append(sug if sug else p)
    return "".join(out)


def wordlist_size() -> int:
    _ensure_loaded()
    return len(_WORDS)
