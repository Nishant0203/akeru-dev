"""Language detection for Manifest Search queries."""

from __future__ import annotations

# Devanagari Unicode block: U+0900–U+097F
_DEVANAGARI_START = 0x0900
_DEVANAGARI_END = 0x097F

# Minimum fraction of Devanagari chars to classify as Hindi
_HINDI_THRESHOLD = 0.10


def detect_language(text: str) -> str:
    """Detect query language. Returns BCP-47 code.

    Current support:
      'hi' — Hindi (Devanagari script detected above threshold)
      'en' — English / unknown (default)

    Detection is script-based: a query is classified as Hindi if at least 10%
    of its non-whitespace characters fall in the Devanagari Unicode block.
    """
    if not text:
        return "en"

    chars = [c for c in text if not c.isspace()]
    if not chars:
        return "en"

    devanagari_count = sum(
        1 for c in chars
        if _DEVANAGARI_START <= ord(c) <= _DEVANAGARI_END
    )

    if devanagari_count / len(chars) >= _HINDI_THRESHOLD:
        return "hi"

    return "en"


# Shorter alias used across architecture docs / call sites
detect_lang = detect_language
