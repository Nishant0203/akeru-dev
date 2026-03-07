import importlib
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from agent.tests.sse_test_utils import collect_sse_events


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


def _build_test_client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("VANIK_ANCHORS_DB", str(tmp_path / "anchors.db"))
    monkeypatch.setenv("VANIK_QUERY_LOG", str(tmp_path / "query_log.jsonl"))
    monkeypatch.setenv("VANIK_MS_FEEDBACK_LOG", str(tmp_path / "ms_feedback.jsonl"))
    monkeypatch.setenv("VANIK_MS_INVOCATIONS_LOG", str(tmp_path / "ms_invocations.jsonl"))

    import agent.anchor_store as anchor_store
    import agent.health as health
    import agent.query_log as query_log
    import agent.session_gw as session_gw
    import nes.feedback_store as feedback_store

    importlib.reload(feedback_store)
    importlib.reload(anchor_store)
    importlib.reload(query_log)
    importlib.reload(health)
    importlib.reload(session_gw)

    return TestClient(session_gw.app)


def test_session_message_gate_then_selection(tmp_path, monkeypatch) -> None:
    client = _build_test_client(tmp_path, monkeypatch)

    with patch("agent.vanik_agent.get_mfn_rate", side_effect=_fake_rate):
        create = client.post("/sessions", json={"user_id": "usr_1", "session_type": "new"})
        assert create.status_code == 201
        session_id = create.json()["session_id"]

        sent = client.post(
            f"/sessions/{session_id}/msg",
            json={"role": "user", "content": "duty on brake parts from india to uk"},
        )
        assert sent.status_code == 202

        gate_events = collect_sse_events(
            client=client,
            url=f"/sessions/{session_id}/sse",
            stop_type="gate",
            timeout_seconds=5.0,
        )
        gate_types = [event.get("type") for event in gate_events]
        assert "gate" in gate_types

        selected = client.post(
            f"/sessions/{session_id}/msg",
            json={"role": "user", "content": "1"},
        )
        assert selected.status_code == 202

        done_events = collect_sse_events(
            client=client,
            url=f"/sessions/{session_id}/sse",
            stop_type="done",
            timeout_seconds=5.0,
        )
        done_types = [event.get("type") for event in done_events]
        assert "token" in done_types
        assert "done" in done_types
        assert done_types[-1] == "done"

        state_after = client.get(f"/sessions/{session_id}")
        assert state_after.status_code == 200
        assert state_after.json()["pending_gate"] is False

        anchors = client.get("/anchors", params={"user_id": "usr_1"})
        assert anchors.status_code == 200
        assert len(anchors.json()) >= 1


def test_sse_timeout_on_stalled_agent(tmp_path, monkeypatch) -> None:
    client = _build_test_client(tmp_path, monkeypatch)

    import agent.session_gw as session_gw

    async def mock_stalled_agent(*args, **kwargs) -> dict:
        _ = args, kwargs
        return {
            "ok": False,
            "status": "awaiting_confirmation",
            "message": "stalled at gate",
            "options": [],
            "allow_manual_hs": True,
            "entities": {"origin": "IN", "destination": "GB"},
        }

    async def noop_welcome(_session) -> None:
        pass

    monkeypatch.setattr(session_gw, "vanik_agent", mock_stalled_agent)
    monkeypatch.setattr(session_gw, "emit_welcome", noop_welcome)

    create = client.post("/sessions", json={"user_id": "usr_2", "session_type": "new"})
    assert create.status_code == 201
    session_id = create.json()["session_id"]

    sent = client.post(
        f"/sessions/{session_id}/msg",
        json={"role": "user", "content": "duty on brake parts from india to uk"},
    )
    assert sent.status_code == 202

    try:
        collect_sse_events(
            client=client,
            url=f"/sessions/{session_id}/sse",
            stop_type="done",
            timeout_seconds=1.0,
        )
        pytest.fail("Expected timeout did not occur; stream received 'done' within 1s")
    except pytest.fail.Exception as exc:
        assert "Received event types" in str(exc)


def test_api_mode_query_endpoint(tmp_path, monkeypatch) -> None:
    client = _build_test_client(tmp_path, monkeypatch)

    with patch("agent.vanik_agent.get_mfn_rate", side_effect=_fake_rate):
        response = client.post(
            "/v1/query",
            json={
                "query": "duty on brake parts from india to uk",
                "hs_code": "8708301090",
                "quantity": 1000,
                "unit_value_usd": 45.0,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["commodity_code"] == "8708301090"
    assert payload["audit"]["hs_code_source"] == "caller_supplied"
    assert payload["audit"]["human_confirmed"] is False
    assert payload["corridors"]["IN_to_GB"]["mfn_rate_pct"] == 2.0


def test_health_endpoint_shape(tmp_path, monkeypatch) -> None:
    client = _build_test_client(tmp_path, monkeypatch)
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert "status" in payload
    assert "components" in payload
    assert "manifest_search" in payload["components"]
