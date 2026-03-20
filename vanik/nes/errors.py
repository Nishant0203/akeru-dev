"""Bilingual user messages for NES / agent layers (architecture v2.0).

Canonical definitions live in ``agent.errors``; this module re-exports ``msg``
so NES code can ``from nes.errors import msg`` without duplicating strings.
"""

from __future__ import annotations

from agent.errors import msg

__all__ = ["msg"]
