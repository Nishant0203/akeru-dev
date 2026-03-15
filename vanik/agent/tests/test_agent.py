import asyncio
from unittest.mock import AsyncMock, patch

from agent.vanik_agent import vanik_agent


def _fake_rate(hs_code: str, destination: str) -> dict:
    rates = {"GB": 2.0, "EU": 3.0, "IN": 15.0}
    sources = {
        "GB": "UK Trade Tariff API",
        "EU": "EU XI Tariff API",
        "IN": "WTO Timeseries API",
    }
    return {
        "ok": True,
        "data": {
            "hs_code": hs_code,
            "mfn_rate_pct": rates[destination],
            "source": sources[destination],
        },
    }


def _partial_rate(hs_code: str, destination: str) -> dict:
    if destination == "EU":
        return {"ok": False, "error": {"code": "upstream_error", "source": "EU"}}
    return _fake_rate(hs_code, destination)


def test_agent_smoke() -> None:
    with patch("agent.vanik_agent.get_mfn_rate", side_effect=_fake_rate):
        result = asyncio.run(
            vanik_agent("duty on brake parts from india to uk", hs_code_provided="8708301090")
        )

    assert result["ok"] is True
    assert "data_part" in result


def test_agent_can_pause_for_confirmation_gate() -> None:
    # Stub options so agent reaches gate (search_hs_schedule returns [] when DB empty)
    _stub_options = [
        {"commodity_code": "8708301090", "description": "Brakes and servo-brakes: disc brakes"},
        {"commodity_code": "8708309000", "description": "Brakes and servo-brakes: other"},
    ]
    with patch("agent.vanik_agent.search_hs_schedule", return_value=_stub_options):
        result = asyncio.run(
            vanik_agent("duty on brake parts from india to uk", gate_selection=None)
        )
    assert result["status"] == "awaiting_confirmation"
    assert result["options"]


def test_agent_requests_clarification_when_route_missing() -> None:
    with patch(
        "agent.vanik_agent.ms_extract",
        return_value={
            "product_terms": ["brake parts"],
            "hs_code_provided": None,
            "origin": None,
            "destination": None,
        },
    ):
        result = asyncio.run(vanik_agent("duty on brake parts"))

    assert result["status"] == "needs_clarification"
    assert set(result["missing"]) == {"origin", "destination"}


def test_agent_rejects_invalid_hs_code() -> None:
    result = asyncio.run(vanik_agent("anything", hs_code_provided="87A830"))
    assert result["status"] == "invalid_input"


def test_agent_returns_partial_result_when_one_corridor_fails() -> None:
    with patch("agent.vanik_agent.get_mfn_rate", side_effect=_partial_rate):
        result = asyncio.run(
            vanik_agent("duty on brake parts from india to uk", hs_code_provided="8708301090")
        )

    assert result["ok"] is True
    data = result["data_part"]["data"]["vanik.compliance.LandedCost"]
    assert data["eu_status"] == "unavailable"
    assert data["uk_status"] == "ok"


def test_agent_uses_gate_option_description_in_synthesised_output() -> None:
    entities = {
        "product_terms": ["brake parts"],
        "hs_code_provided": None,
        "origin": "IN",
        "destination": "GB",
    }
    options = [
        {
            "commodity_code": "8708301090",
            "description": "Brake linings and pads for motor vehicles",
        }
    ]
    with patch("agent.vanik_agent.get_mfn_rate", side_effect=_fake_rate):
        result = asyncio.run(
            vanik_agent(
                "duty on brake parts from india to uk",
                gate_selection="1",
                precomputed_entities=entities,
                gate_options=options,
            )
        )

    data = result["data_part"]["data"]["vanik.compliance.LandedCost"]
    assert data["description"] == "Brake linings and pads for motor vehicles"


def test_agent_blocks_invalid_synthesiser_payload() -> None:
    bad_payload = {
        "ok": True,
        "narrative": "test",
        "data_part": {
            "kind": "data",
            "data": {
                "vanik.compliance.LandedCost": {
                    "hs_code": "BAD",
                    "mfn_rate_pct": 2.0,
                    "uk_mfn_rate_pct": 2.0,
                    "eu_mfn_rate_pct": 3.0,
                    "india_mfn_rate_pct": 15.0,
                }
            },
        },
    }
    with (
        patch("agent.vanik_agent.get_mfn_rate", side_effect=_fake_rate),
        patch("agent.vanik_agent.build", new_callable=AsyncMock, return_value=bad_payload),
    ):
        result = asyncio.run(
            vanik_agent("duty on brake parts from india to uk", hs_code_provided="8708301090")
        )

    assert result["ok"] is False
    assert result["status"] == "guardrail_violation"
