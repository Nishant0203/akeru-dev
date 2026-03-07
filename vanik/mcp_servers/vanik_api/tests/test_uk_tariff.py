import httpx

from mcp_servers.vanik_api.clients.uk_tariff import get_uk_mfn_rate


def test_uk_parses_mfn_rate_from_included_duty_expression() -> None:
    payload = {
        "included": [
            {
                "id": "m1",
                "type": "measure",
                "attributes": {"measure_type_id": "103"},
                "relationships": {"duty_expression": {"data": [{"id": "d1", "type": "duty_expression"}]}} ,
            },
            {"id": "d1", "type": "duty_expression", "attributes": {"base": "2.0 %"}},
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        res = get_uk_mfn_rate("8708301090", client=client)

    assert res.commodity_code_10 == "8708301090"
    assert res.mfn_rate_pct == 2.0
