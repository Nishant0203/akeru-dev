"""Model provider abstraction layer."""

from __future__ import annotations

import os


def get_completion_client() -> object:
    """Return a provider marker object for scaffold usage."""
    provider = os.getenv("MODEL_PROVIDER", "anthropic")

    if provider == "anthropic":
        return {"provider": "anthropic"}
    if provider == "openai":
        return {
            "provider": "openai",
            "base": os.getenv("OPENAI_API_BASE"),
            "deployment": os.getenv("OPENAI_DEPLOYMENT_NAME"),
        }

    raise ValueError(f"Unknown MODEL_PROVIDER: {provider}")
