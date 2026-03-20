"""Manifest Search v2: fast regex NER."""

from __future__ import annotations

import re

from nes.language import detect_language

HS_PATTERN = re.compile(r"\b\d{6}(?:\d{2})?(?:\d{2})?\b")

_COUNTRY_PATTERNS: list[tuple[str, str]] = [
    ("IN", r"\bindia\b"),
    ("IN", r"\bindian\b"),
    ("IN", r"\bbharat\b"),
    ("CN", r"\bchina\b"),
    ("CN", r"\bchinese\b"),
    ("CN", r"\bprc\b"),
    ("DE", r"\bgermany\b"),
    ("DE", r"\bgerman\b"),
    ("GB", r"\buk\b"),
    ("GB", r"\bgb\b"),
    ("GB", r"\bbritain\b"),
    ("GB", r"\bbritish\b"),
    ("GB", r"\bunited kingdom\b"),
    ("FR", r"\bfrance\b"),
    ("FR", r"\bfrench\b"),
    ("IT", r"\bitaly\b"),
    ("IT", r"\bitalian\b"),
    ("ES", r"\bspain\b"),
    ("ES", r"\bspanish\b"),
    ("NL", r"\bnetherlands\b"),
    ("NL", r"\bdutch\b"),
    ("BE", r"\bbelgium\b"),
    ("BE", r"\bbelgian\b"),
    ("PL", r"\bpoland\b"),
    ("PL", r"\bpolish\b"),
    ("SE", r"\bsweden\b"),
    ("SE", r"\bswedish\b"),
    ("US", r"\busa\b"),
    ("US", r"\bamerica\b"),
    ("US", r"\bamerican\b"),
    ("US", r"\bunited states\b"),
    ("JP", r"\bjapan\b"),
    ("JP", r"\bjapanese\b"),
    ("KR", r"\bsouth korea\b"),
    ("KR", r"\bkorean\b"),
    ("TW", r"\btaiwan\b"),
    ("VN", r"\bvietnam\b"),
    ("VN", r"\bvietnamese\b"),
    ("TR", r"\bturkey\b"),
    ("TR", r"\bturkish\b"),
    ("BD", r"\bbangladesh\b"),
]

_EU_CODES = {
    "DE",
    "FR",
    "IT",
    "ES",
    "NL",
    "BE",
    "PL",
    "SE",
    "AT",
    "PT",
    "CZ",
    "HU",
    "RO",
    "DK",
    "FI",
    "SK",
    "HR",
    "IE",
    "BG",
    "SI",
    "LT",
    "LV",
    "EE",
    "CY",
    "LU",
    "MT",
}

_EU_DEST_RE = re.compile(r"\b(eu|europe|european union|eurozone)\b", re.IGNORECASE)

_FROM_RE = re.compile(
    r"\bfrom\s+([\w][\w\s\-]*?)(?=\s+to\b|\s+into\b|\s+for\b|,|\.|$)",
    re.IGNORECASE,
)
_TO_RE = re.compile(
    r"\b(?:to|into|entering|selling\s+(?:in|to)|importing\s+(?:into|to)|"
    r"destined\s+for|headed\s+(?:to|for))\s+([\w][\w\s\-]*?)(?=\s+from\b|,|\.|$)",
    re.IGNORECASE,
)
_MADE_IN_RE = re.compile(
    r"\b(?:made|manufactured|produced|sourced|origin(?:ating)?)\s+in\s+"
    r"([\w][\w\s\-]*?)(?=\s|,|\.|$)",
    re.IGNORECASE,
)


def _resolve_country(text_fragment: str) -> str | None:
    """Return ISO-2 code for a text fragment, or None."""
    fragment = text_fragment.strip().lower()
    for code, pattern in _COUNTRY_PATTERNS:
        if re.search(pattern, fragment):
            return code
    return None


def _resolve_destination(code: str | None) -> str | None:
    """Normalise destination code - EU member states resolve to EU."""
    if code is None:
        return None
    if code in _EU_CODES:
        return "EU"
    return code


def _all_country_mentions(text: str) -> list[str]:
    """Return all ISO-2 country mentions in order of first detection."""
    seen: list[str] = []
    for code, pattern in _COUNTRY_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE) and code not in seen:
            seen.append(code)
    return seen


# Corridor / logistics words — strip from product phrase (not ISO corridor itself)
_CORRIDOR_RE = re.compile(
    r"\b(from|to|into|exported?|imported?|origin|destination|"
    r"shipped?|between|via|through)\b",
    re.IGNORECASE,
)

# Stopwords + common country / region names so they do not become "product_terms"
_STOPWORD_SET: frozenset[str] = frozenset(
    {
        "what",
        "is",
        "the",
        "import",
        "imports",
        "export",
        "exports",
        "duty",
        "duties",
        "tariff",
        "rate",
        "for",
        "how",
        "much",
        "does",
        "do",
        "cost",
        "on",
        "a",
        "an",
        "of",
        "in",
        "at",
        "by",
        "with",
        "and",
        "or",
        "when",
        "where",
        "are",
        "can",
        "will",
        "would",
        "should",
        "could",
        "tell",
        "me",
        "find",
        "show",
        "please",
        "help",
        "calculate",
        "check",
        "lookup",
        "look",
        "up",
        "india",
        "indian",
        "china",
        "chinese",
        "germany",
        "german",
        "uk",
        "gb",
        "britain",
        "british",
        "eu",
        "europe",
        "usa",
        "us",
        "america",
        "american",
        "bharat",
    }
)


def _extract_product_terms(text: str) -> list[str]:
    """Core product phrase only: no HS corridor noise, no stopwords or country names."""
    # 1. Strip HS codes (search uses separate hs_code_provided)
    stripped = HS_PATTERN.sub(" ", text)
    # 2. Strip corridor / logistics tokens
    stripped = _CORRIDOR_RE.sub(" ", stripped)
    # 3. Tokenise; drop short tokens and stopwords
    tokens: list[str] = []
    for w in stripped.split():
        t = w.lower().strip(".,;:!?\"'")
        if len(t) > 2 and t not in _STOPWORD_SET:
            tokens.append(t)
    primary = " ".join(tokens).strip()
    return [primary] if primary else []


def extract_v2(raw_query: str) -> dict:
    """Fast local regex extractor."""
    text = raw_query.strip()
    lower = text.lower()
    hs_match = HS_PATTERN.search(text)

    origin: str | None = None
    destination: str | None = None

    from_match = _FROM_RE.search(lower)
    to_match = _TO_RE.search(lower)
    made_in_match = _MADE_IN_RE.search(lower)

    if from_match:
        origin = _resolve_country(from_match.group(1))
    if made_in_match and origin is None:
        origin = _resolve_country(made_in_match.group(1))
    if to_match:
        destination = _resolve_destination(_resolve_country(to_match.group(1)))

    if destination is None and _EU_DEST_RE.search(lower):
        destination = "EU"

    if origin is None or destination is None:
        all_codes = _all_country_mentions(lower)

        if origin is None and destination is None:
            if len(all_codes) == 2:
                origin = all_codes[0]
                destination = _resolve_destination(all_codes[1])
            elif len(all_codes) == 1:
                if re.search(r"\bimport", lower):
                    destination = _resolve_destination(all_codes[0])
                else:
                    origin = all_codes[0]
        elif origin is None:
            for code in all_codes:
                resolved = _resolve_destination(code)
                if resolved != destination:
                    origin = code
                    break
        elif destination is None:
            for code in all_codes:
                if code != origin:
                    destination = _resolve_destination(code)
                    break

    if origin is None and _EU_DEST_RE.search(lower):
        if destination and destination != "EU":
            origin = "EU"

    product_terms = _extract_product_terms(text)
    return {
        "product_terms": product_terms,
        "hs_code_provided": hs_match.group(0) if hs_match else None,
        "origin": origin,
        "_origin_candidates": _all_country_mentions(lower),
        "destination": destination,
        "quantity": None,
        "unit_value_usd": None,
        "_lang": detect_language(raw_query),
    }
