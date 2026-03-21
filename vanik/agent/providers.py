"""Model provider abstraction layer — clients, model routing, call_llm()."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

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

        azure_ep = (os.getenv("AZURE_OPENAI_ENDPOINT") or "").strip()
        if azure_ep:
            return openai.AzureOpenAI(
                azure_endpoint=azure_ep.rstrip("/"),
                api_version=os.getenv("OPENAI_API_VERSION", "2024-02-15-preview"),
                api_key=api_key,
            )
        base = (os.getenv("OPENAI_API_BASE") or "").strip()
        if base:
            return openai.OpenAI(api_key=api_key, base_url=base.rstrip("/"))
        return openai.OpenAI(api_key=api_key)

    if provider == "mistral":
        try:
            from mistralai import Mistral  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError(
                "mistralai package not installed. pip install mistralai or use MODEL_PROVIDER=anthropic|openai."
            ) from exc
        key = os.getenv("MISTRAL_API_KEY", "")
        if not key:
            raise RuntimeError("MISTRAL_API_KEY is not set.")
        return Mistral(api_key=key)

    raise ValueError(
        f"Unknown MODEL_PROVIDER: {provider!r}. Use anthropic, openai, or mistral."
    )


def get_model_name(task: str) -> str:
    """
    task: "extraction" | "synthesis" | "synthesis_hindi"
    """
    provider = os.getenv("MODEL_PROVIDER", "anthropic").strip().lower()
    models: dict[str, dict[str, str]] = {
        "anthropic": {
            "extraction": "claude-haiku-4-5-20251001",
            "synthesis": "claude-sonnet-4-20250514",
            "synthesis_hindi": "claude-haiku-4-5-20251001",
        },
        "openai": {
            "extraction": os.getenv("OPENAI_EXTRACTION_MODEL", "gpt-4o-mini"),
            "synthesis": os.getenv("OPENAI_SYNTHESIS_MODEL", "gpt-4o"),
            "synthesis_hindi": os.getenv("OPENAI_EXTRACTION_MODEL", "gpt-4o-mini"),
        },
        "mistral": {
            "extraction": os.getenv("MISTRAL_EXTRACTION_MODEL", "mistral-small-latest"),
            "synthesis": os.getenv("MISTRAL_SYNTHESIS_MODEL", "mistral-large-latest"),
            "synthesis_hindi": os.getenv("MISTRAL_EXTRACTION_MODEL", "mistral-small-latest"),
        },
    }
    table = models.get(provider, models["anthropic"])
    return table.get(task, table["extraction"])


def call_llm(
    client: Any,
    *,
    system: str,
    user: str,
    model: str,
    max_tokens: int = 512,
    temperature: float = 0.1,
) -> str:
    """Provider-agnostic completion. Returns assistant text."""
    if hasattr(client, "messages") and hasattr(client.messages, "create"):
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        parts = getattr(resp, "content", []) or []
        chunks = [getattr(p, "text", "") or "" for p in parts]
        return "".join(chunks).strip()

    chat = getattr(client, "chat", None)
    if chat is not None and hasattr(chat, "completions"):
        resp = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        msg = resp.choices[0].message
        return (msg.content or "").strip()

    if chat is not None and hasattr(chat, "complete"):
        resp = client.chat.complete(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return (resp.choices[0].message.content or "").strip()

    raise ValueError(f"Unknown LLM client type: {type(client)!r}")
