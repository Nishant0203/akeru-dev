"""Resolve product trade terms: ambiguous gate → dictionary index → unknown."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dictionary.entity_stripper import get_dictionary_index

from manifest_search.product_registry_data import ambiguous_terms_map


@dataclass
class ProductResolution:
    status: str  # resolved | ambiguous | unknown
    canonical: str | None = None
    chapter_hint: str | None = None
    hs_heading: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    match_method: str | None = None
    score: float = 1.0
    aliases: list[str] = field(default_factory=list)
    clarification_question: str | None = None
    clarification_options: list[dict[str, Any]] = field(default_factory=list)


def _normalise_phrase_key(term: str) -> str:
    return " ".join((term or "").lower().split())


def resolve(term: str) -> ProductResolution:
    """
    1) Ambiguous single-token / exact-key terms from product_registry.yaml
    2) Dictionary lookup (product slice)
    3) unknown
    """
    raw = (term or "").strip()
    if not raw:
        return ProductResolution(status="unknown")

    amb = ambiguous_terms_map()
    nk = _normalise_phrase_key(raw)
    # Exact phrase match on ambiguous key
    if nk in amb:
        spec = amb[nk]
        return ProductResolution(
            status="ambiguous",
            clarification_question=str(spec.get("question") or "Which option fits best?"),
            clarification_options=list(spec.get("options") or []),
            chapter_hint=None,
        )
    # Single token matches ambiguous key (e.g. "steel")
    tokens = nk.split()
    if len(tokens) == 1 and tokens[0] in amb:
        spec = amb[tokens[0]]
        return ProductResolution(
            status="ambiguous",
            clarification_question=str(spec.get("question") or "Which option fits best?"),
            clarification_options=list(spec.get("options") or []),
            chapter_hint=None,
        )

    idx = get_dictionary_index()
    result = idx.lookup(raw, "product")
    if result.found:
        meta = dict(result.metadata or {})
        aliases = meta.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        if not isinstance(aliases, list):
            aliases = []
        aliases = [str(a) for a in aliases if str(a).strip()]
        return ProductResolution(
            status="resolved",
            canonical=result.canonical,
            chapter_hint=meta.get("chapter"),
            hs_heading=meta.get("hs_heading"),
            metadata=meta,
            match_method=result.match_method,
            score=result.score,
            aliases=aliases,
        )
    return ProductResolution(status="unknown")
