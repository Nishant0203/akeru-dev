"""Build HS search term lists from extraction + spell correction + product dictionary."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from manifest_search.product_resolver import ProductResolution, resolve
from manifest_search.symspell_corrector import correct, refresh_wordlist


@dataclass
class DisambiguationRequired:
    original_term: str
    question: str
    options: list[dict[str, Any]]
    chapter_hint: str | None = None


def _dedupe_preserve(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        xl = x.lower().strip()
        if not xl or xl in seen:
            continue
        seen.add(xl)
        out.append(x.strip())
    return out


def _expand_resolution(res: ProductResolution) -> list[str]:
    if res.status != "resolved" or not res.canonical:
        return []
    terms = [res.canonical]
    for a in (res.aliases or [])[:2]:
        a = str(a).strip()
        if a and a.lower() != res.canonical.lower():
            terms.append(a)
    return terms


def build_hs_search_terms(entities: dict[str, Any]) -> list[str] | DisambiguationRequired:
    """
    Turn v2/v3 ``product_terms`` into search strings for ``search_hs_schedule``.

    Spell-corrects each term, then resolves via product dictionary.
    Returns ``DisambiguationRequired`` if an ambiguous registry term is hit.
    """
    refresh_wordlist()
    raw_terms = entities.get("product_terms") or []
    if not isinstance(raw_terms, list):
        raw_terms = [str(raw_terms).strip()] if raw_terms else []
    terms = [str(t).strip() for t in raw_terms if str(t).strip()]
    if not terms:
        return []

    expanded: list[str] = []
    for i, t in enumerate(terms):
        fixed = correct(t)
        res = resolve(fixed)
        if res.status == "ambiguous":
            # Only gate on the primary term; fallbacks (e.g. last-token "parts") keep search flowing.
            if i == 0:
                return DisambiguationRequired(
                    original_term=t,
                    question=res.clarification_question or "Which option fits best?",
                    options=list(res.clarification_options or []),
                    chapter_hint=res.chapter_hint,
                )
            expanded.append(fixed)
            continue
        if res.status == "resolved":
            expanded.extend(_expand_resolution(res))
        else:
            expanded.append(fixed)

    out = _dedupe_preserve(expanded)
    return out if out else terms
