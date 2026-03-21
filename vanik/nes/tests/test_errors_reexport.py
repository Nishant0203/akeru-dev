"""nes.errors re-exports agent.errors (architecture v2.0)."""

from nes.errors import msg


def test_nes_errors_msg() -> None:
    text = msg("no_match", "en", searched="widgets")
    assert "widgets" in text
    assert "hs" in text.lower() or "code" in text.lower()
