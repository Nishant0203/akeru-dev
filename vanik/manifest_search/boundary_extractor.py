"""Keep-list style trimming for conversational product surface (secondary to sanitiser)."""

from __future__ import annotations

import re

# Tariff / query vocabulary — dropped from the kept product span
_TARIFF_VOCAB = re.compile(
    r"\b(?:duty|duties|tariff|tariffs|rate|rates|hs|h\.s\.|classify|classification|"
    r"commodity\s+code|import|export|clearance)\b",
    re.IGNORECASE,
)

# Corridor glue words (product_terms already strip many; this is extra safety)
_CORRIDOR_GLUE = re.compile(
    r"\b(?:from|to|into|via|between|origin|destination|heading|for)\b",
    re.IGNORECASE,
)

# Tokens with digits (prices, codes, quantities) removed from kept span
_DIGIT_TOKEN = re.compile(r"\S*\d\S*")


def extract_permitted(text: str) -> str:
    """
    Keep a looser product-description surface: drop digit-bearing tokens,
    tariff vocabulary, and corridor glue. Does **not** remove country names
    (v2 NER still runs on the orchestrator pipeline's cleaned string).

    Intended for optional refinement or logging — primary enforcement remains
    structured sanitiser + entity dictionary + NER.
    """
    s = (text or "").strip()
    if not s:
        return ""
    s = _TARIFF_VOCAB.sub(" ", s)
    s = _CORRIDOR_GLUE.sub(" ", s)
    parts: list[str] = []
    for tok in s.split():
        if _DIGIT_TOKEN.fullmatch(tok):
            continue
        if len(tok.strip(".,;:!?\"'")) < 2:
            continue
        parts.append(tok)
    return re.sub(r"\s{2,}", " ", " ".join(parts)).strip()
