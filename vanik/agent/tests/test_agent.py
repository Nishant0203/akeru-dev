import asyncio
from unittest.mock import patch

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
        result = asyncio.run(vanik_agent("duty on brake parts from india to uk"))

    assert result["ok"] is True
    assert "data_part" in result


def test_agent_can_pause_for_confirmation_gate() -> None:
    result = asyncio.run(vanik_agent("duty on brake parts from india to uk", gate_selection=None))
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
        result = asyncio.run(vanik_agent("duty on brake parts from india to uk"))

    assert result["ok"] is True
    data = result["data_part"]["data"]["vanik.compliance.LandedCost"]
    assert data["eu_status"] == "unavailable"
    assert data["uk_status"] == "ok"
