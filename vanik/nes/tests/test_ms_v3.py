import asyncio
from types import SimpleNamespace

import nes.v3_llm as v3_llm
from nes.v3_llm import llm_extract


class _FakeMessages:
    def __init__(self, text: str, *, error: Exception | None = None) -> None:
        self._text = text
        self._error = error

    def create(self, **_: object) -> SimpleNamespace:
        if self._error:
            raise self._error
        return SimpleNamespace(content=[SimpleNamespace(text=self._text)])


class _FakeClient:
    def __init__(self, text: str, *, error: Exception | None = None) -> None:
        self.messages = _FakeMessages(text, error=error)


def test_ms_v3_fallback_shape(monkeypatch) -> None:
    monkeypatch.setattr(
        v3_llm,
        "get_completion_client",
        lambda: _FakeClient('{"product_terms":["random query"],"origin":"IN","destination":"GB"}'),
    )
    entities = asyncio.run(llm_extract("random query"))
    assert "product_terms" in entities


def test_ms_v3_strips_markdown_fences(monkeypatch) -> None:
    monkeypatch.setattr(
        v3_llm,
        "get_completion_client",
        lambda: _FakeClient(
            '```json\n{"product_terms":["ceramic tiles"],"origin":"IN","destination":"EU"}\n```'
        ),
    )

    entities = asyncio.run(llm_extract("ceramic tiles from india to germany"))

    assert entities["product_terms"] == ["ceramic tiles"]
    assert entities["origin"] == "IN"
    assert entities["destination"] == "EU"


def test_ms_v3_falls_back_on_parse_failure(monkeypatch) -> None:
    monkeypatch.setattr(v3_llm, "get_completion_client", lambda: _FakeClient("not json"))

    entities = asyncio.run(llm_extract("random query"))

    assert entities["product_terms"] == ["random query"]
    assert entities["origin"] is None
    assert entities["destination"] is None


def test_ms_v3_falls_back_on_client_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        v3_llm,
        "get_completion_client",
        lambda: _FakeClient("", error=RuntimeError("boom")),
    )

    entities = asyncio.run(llm_extract("random query"))

    assert entities["product_terms"] == ["random query"]
    assert entities["hs_code_provided"] is None
