"""Model provider abstraction layer."""

from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = lambda _: None  # noqa: ARG005

# Ensure .env is loaded when this module is used (e.g. by vanik_agent), not only when gateway runs
_vanik_root = Path(__file__).resolve().parent.parent
_env_file = _vanik_root / ".env"
_alt_env = _vanik_root / "Vanik_connections.env"
load_dotenv(_env_file)
if not _env_file.exists() and _alt_env.exists():
    load_dotenv(_alt_env)


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
