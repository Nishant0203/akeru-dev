import httpx

from mcp_servers.vanik_api.clients.wto import get_india_mfn_rate
from mcp_servers.vanik_api.config import settings


def test_wto_parses_rate_from_mock_payload(monkeypatch) -> None:
    monkeypatch.setattr(settings, "wto_api_key_primary", "test-primary")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"Dataset": [{"value": "15.0"}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        res = get_india_mfn_rate("870830", client=client)

    assert res.hs_code_6 == "870830"
    assert res.mfn_rate_pct == 15.0


def test_wto_uses_secondary_key_on_primary_auth_failure(monkeypatch) -> None:
    monkeypatch.setattr(settings, "wto_api_key_primary", "test-primary")
    monkeypatch.setattr(settings, "wto_api_key_secondary", "test-secondary")

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        key = request.headers.get("Ocp-Apim-Subscription-Key", "")
        calls.append(key)
        if key == settings.wto_api_key_primary:
            return httpx.Response(401, json={"error": "unauthorized"})
        return httpx.Response(200, json={"Dataset": [{"value": 12.5}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        res = get_india_mfn_rate("870830", client=client)

    assert res.mfn_rate_pct == 12.5
    assert calls[0] == settings.wto_api_key_primary
    assert calls[-1] == settings.wto_api_key_secondary
