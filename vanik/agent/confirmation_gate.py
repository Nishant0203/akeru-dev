"""Human confirmation gate logic."""

from __future__ import annotations

RESIDUAL_KEYWORDS = ("other", "not elsewhere specified", "nes", "residual")


def is_residual(description: str) -> bool:
    """Flag residual catch-all categories for user visibility."""
    text = description.lower()
    return any(k in text for k in RESIDUAL_KEYWORDS)


def format_options(results: list[dict]) -> list[dict]:
    """Prepare result set for display in confirmation step."""
    formatted: list[dict] = []
    for row in results:
        formatted.append(
            {
                "commodity_code": row["commodity_code"],
                "description": row["description"],
                "residual_flag": is_residual(row["description"]),
            }
        )
    return formatted


def resolve_selection(selection: str, options: list[dict]) -> str:
    """Resolve gate input into a commodity code.

    Supports:
    - numeric index (1-based)
    - direct 6/8/10-digit HS code
    """
    token = selection.strip()
    if token.isdigit() and len(token) in {6, 8, 10}:
        return token

    if token.isdigit():
        idx = int(token) - 1
        if 0 <= idx < len(options):
            return str(options[idx]["commodity_code"])

    raise ValueError("Invalid gate selection. Enter an option number or a 6/8/10-digit code.")
