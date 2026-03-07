"""Structured error types for vanik_api tools and clients."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class VanikAPIError(Exception):
    """Domain error with a serializable payload for MCP tool responses."""

    code: str
    message: str
    source: str
    http_status: int | None = None
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "source": self.source,
        }
        if self.http_status is not None:
            payload["http_status"] = self.http_status
        if self.details:
            payload["details"] = self.details
        return payload
