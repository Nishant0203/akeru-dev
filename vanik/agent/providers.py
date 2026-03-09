"""Model provider abstraction layer."""

from __future__ import annotations

import os


def get_completion_client() -> object:
    """Return a real LLM client based on MODEL_PROVIDER."""
    provider = os.getenv("MODEL_PROVIDER", "anthropic").strip().lower()

    if provider == "anthropic":
        try:
            import anthropic  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError(
                "anthropic package not installed. Install project dependencies to use "
                "MODEL_PROVIDER=anthropic."
            ) from exc

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Add it to the Vanik runtime environment "
                "before enabling MODEL_PROVIDER=anthropic."
            )
        return anthropic.Anthropic(api_key=api_key)

    if provider == "openai":
        try:
            import openai  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError(
                "openai package not installed. Install project dependencies to use "
                "MODEL_PROVIDER=openai."
            ) from exc

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Add it to the Vanik runtime environment "
                "before enabling MODEL_PROVIDER=openai."
            )

        base_url = os.getenv("OPENAI_API_BASE") or None
        return openai.OpenAI(api_key=api_key, base_url=base_url)

    raise ValueError(f"Unknown MODEL_PROVIDER: {provider!r}")
