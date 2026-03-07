"""Model provider abstraction layer.

TODO: Stub only. When LLM calls are wired, this must return an actual client
(e.g. anthropic.Anthropic(), openai.OpenAI()) — not a dict. Do not route
production extraction or completion through this until implemented.
"""

from __future__ import annotations

import os


def get_completion_client() -> object:
    """Stub: returns a dict. Replace with real client before LLM activation."""
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
