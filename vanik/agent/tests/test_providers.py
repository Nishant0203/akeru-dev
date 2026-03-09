from __future__ import annotations

import sys
from types import ModuleType

import pytest

from agent.providers import get_completion_client


class _AnthropicClient:
    def __init__(self, *, api_key: str) -> None:
        self.api_key = api_key


class _OpenAIClient:
    def __init__(self, *, api_key: str, base_url: str | None = None) -> None:
        self.api_key = api_key
        self.base_url = base_url


def test_get_completion_client_returns_anthropic_client(monkeypatch: pytest.MonkeyPatch) -> None:
    module = ModuleType("anthropic")
    module.Anthropic = _AnthropicClient
    monkeypatch.setitem(sys.modules, "anthropic", module)
    monkeypatch.setenv("MODEL_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    client = get_completion_client()

    assert isinstance(client, _AnthropicClient)
    assert client.api_key == "test-key"


def test_get_completion_client_returns_openai_client(monkeypatch: pytest.MonkeyPatch) -> None:
    module = ModuleType("openai")
    module.OpenAI = _OpenAIClient
    monkeypatch.setitem(sys.modules, "openai", module)
    monkeypatch.setenv("MODEL_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_API_BASE", "https://example.invalid")

    client = get_completion_client()

    assert isinstance(client, _OpenAIClient)
    assert client.api_key == "test-key"
    assert client.base_url == "https://example.invalid"


def test_get_completion_client_requires_anthropic_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = ModuleType("anthropic")
    module.Anthropic = _AnthropicClient
    monkeypatch.setitem(sys.modules, "anthropic", module)
    monkeypatch.setenv("MODEL_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY is not set"):
        get_completion_client()


def test_get_completion_client_requires_openai_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    module = ModuleType("openai")
    module.OpenAI = _OpenAIClient
    monkeypatch.setitem(sys.modules, "openai", module)
    monkeypatch.setenv("MODEL_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY is not set"):
        get_completion_client()
