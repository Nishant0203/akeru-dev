"""Re-export NES sanitiser for doc-aligned imports (`manifest_search.sanitiser`)."""

from __future__ import annotations

from nes.sanitiser import sanitise_with_log

__all__ = ["sanitise_with_log"]
