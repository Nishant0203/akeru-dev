"""
vanik/tests/test_batch_demo.py
─────────────────────────────────────────────────────────────────────
TestClient tests for GET /v1/batch/demo

Run:
    cd vanik
    pytest tests/test_batch_demo.py -v

These tests cover the static response path (no ?run=true) so they
run without any external API calls or a live Vanik stack.

The live path (?run=true) is tested with mocks so CI does not hit
real MCP servers; ``analyse_corridors`` is mocked as well.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

from agent.batch_demo import _build_summary, _enrich_result_row, _synthetic_static_row
from agent.session_gw import app
from data.batch_demo_pos import DEMO_POS


# ── Shared fixture ────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def client():
    """Starlette TestClient — reused across all tests in this module."""
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ── Static response tests (no API calls) ─────────────────────────────


class TestBatchDemoStatic:
    """
    GET /v1/batch/demo (no ?run=true)
    Returns pre-computed static results immediately.
    No vanik_agent calls, no MCP calls.
    """

    def test_returns_200(self, client):
        resp = client.get("/v1/batch/demo")
        assert resp.status_code == 200

    def test_response_is_json(self, client):
        resp = client.get("/v1/batch/demo")
        assert resp.headers["content-type"].startswith("application/json")

    def test_ok_field_true(self, client):
        body = client.get("/v1/batch/demo").json()
        assert body["ok"] is True

    def test_results_is_list(self, client):
        body = client.get("/v1/batch/demo").json()
        assert isinstance(body.get("results"), list)

    def test_summary_present(self, client):
        body = client.get("/v1/batch/demo").json()
        assert "summary" in body

    def test_summary_has_required_keys(self, client):
        summary = client.get("/v1/batch/demo").json()["summary"]
        for key in ("total", "succeeded", "failed", "needs_review"):
            assert key in summary, f"summary missing key: {key}"

    def test_compliance_note_present(self, client):
        body = client.get("/v1/batch/demo").json()
        assert "compliance_note" in body
        assert isinstance(body["compliance_note"], str)

    def test_static_returns_without_run_param(self, client):
        """Static path must not trigger vanik_agent calls."""
        with patch("agent.vanik_agent.vanik_agent") as mock_agent:
            client.get("/v1/batch/demo")
            mock_agent.assert_not_called()


# ── Result row schema tests ───────────────────────────────────────────


class TestBatchDemoResultSchema:
    """
    Each result row must carry required fields (flat + landed_cost mirror).
    Tests run against the static preview rows.
    """

    REQUIRED_FIELDS = {
        "po",
        "product",
        "origin",
        "destination",
        "hs_code",
        "ok",
        "status",
        "needs_review",
        "landed_cost",
        "hs_provided",
        "incoterms",
    }

    @pytest.fixture(scope="class")
    def results(self, client):
        return client.get("/v1/batch/demo").json().get("results", [])

    def test_results_not_empty(self, results):
        assert len(results) > 0

    def test_each_row_has_required_fields(self, results):
        for row in results:
            missing = self.REQUIRED_FIELDS - set(row.keys())
            assert not missing, f"Row {row.get('po')} missing fields: {missing}"

    def test_po_field_is_string(self, results):
        for row in results:
            assert isinstance(row["po"], str)
            assert row["po"].startswith("PO-")

    def test_ok_is_bool(self, results):
        for row in results:
            assert isinstance(row["ok"], bool)

    def test_needs_review_is_bool(self, results):
        for row in results:
            assert isinstance(row["needs_review"], bool)

    def test_landed_cost_is_dict(self, results):
        for row in results:
            assert isinstance(row["landed_cost"], dict)

    def test_landed_cost_has_calculable_field(self, results):
        for row in results:
            assert "calculable" in row["landed_cost"], (
                f"Row {row.get('po')} landed_cost missing 'calculable'"
            )

    def test_calculable_rows_have_totals(self, results):
        for row in results:
            lc = row["landed_cost"]
            if lc.get("calculable"):
                assert "total_landed_usd" in lc, (
                    f"Row {row['po']} calculable but missing total_landed_usd"
                )
                assert "total_duty_usd" in lc, (
                    f"Row {row['po']} calculable but missing total_duty_usd"
                )
                assert lc["total_landed_usd"] >= lc["total_duty_usd"], (
                    f"Row {row['po']} landed < duty — impossible"
                )

    def test_ddp_rows_flagged(self, results):
        """DDP rows should carry a basis note mentioning DDP."""
        ddp_rows = [r for r in results if r.get("incoterms") == "DDP"]
        for row in ddp_rows:
            lc = row["landed_cost"]
            if lc.get("calculable"):
                assert "DDP" in lc.get("basis", ""), (
                    f"Row {row['po']} is DDP but basis note does not say so"
                )

    def test_needs_review_true_when_no_hs_provided(self, results):
        """
        Rows where hs_code was not provided upfront and status is ok
        should be flagged needs_review (auto-selected HS code).
        """
        for row in results:
            if row["ok"] and not row.get("hs_provided"):
                assert row["needs_review"] is True, (
                    f"Row {row['po']}: ok=True, hs_provided=False "
                    f"but needs_review=False"
                )

    def test_hs_provided_rows_not_needs_review(self, results):
        """Rows with hs_code provided upfront and ok=True must not need review.

        DDP rows are excluded: the demo intentionally flags them for verification.
        """
        for row in results:
            if row["ok"] and row.get("hs_provided"):
                if row.get("incoterms") == "DDP":
                    continue
                assert row["needs_review"] is False, (
                    f"Row {row['po']}: hs_provided=True but needs_review=True"
                )


# ── Summary arithmetic tests ──────────────────────────────────────────


class TestBatchDemoSummary:
    @pytest.fixture(scope="class")
    def body(self, client):
        return client.get("/v1/batch/demo").json()

    def test_total_matches_full_dataset(self, body):
        """Static mode: summary covers all POs; ``results`` is an 11-row preview."""
        assert body["summary"]["total"] == body["results_full_count"]
        assert body["results_full_count"] == 100

    def test_succeeded_plus_failed_lte_total(self, body):
        s = body["summary"]
        assert s["succeeded"] + s["failed"] <= s["total"]

    def test_total_landed_gte_total_duty(self, body):
        s = body["summary"]
        goods = s.get("total_goods_usd", 0) or 0
        duty = s.get("total_duty_usd", 0) or 0
        landed = s.get("total_landed_usd", 0) or 0
        if goods > 0:
            assert landed >= duty
            assert landed >= goods

    def test_needs_review_count_consistent_with_full_static(self, body):
        """Recompute full 100-row static set; summary must match."""
        full: list = []
        for i, r in enumerate(DEMO_POS):
            row = _synthetic_static_row(i, r)
            _enrich_result_row(row)
            full.append(row)
        expected = _build_summary(full)
        assert body["summary"]["needs_review"] == expected["needs_review"]


# ── Live run tests (mocked) ───────────────────────────────────────────


_MIN_CORRIDOR_OK = {
    "ok": True,
    "hs_code": "6205200000",
    "destination": "GB",
    "ranked": [],
    "corridors": [],
}


class TestBatchDemoLiveRun:
    """
    GET /v1/batch/demo?run=true
    vanik_agent and analyse_corridors are mocked.
    """

    MOCK_AGENT_RESULT = {
        "ok": True,
        "status": "ok",
        "message": "",
        "narrative": "MFN rates for HS 6205200000: GB 12.0%.",
        "audit": {"hs_code_source": "auto_selected", "human_confirmed": False},
        "data_part": {
            "kind": "data",
            "data": {
                "vanik.compliance.LandedCost": {
                    "hs_code": "6205200000",
                    "description": "Men's shirts, of cotton",
                    "origin": "IN",
                    "destination": "GB",
                    "mfn_rate_pct": 12.0,
                    "uk_mfn_rate_pct": 12.0,
                    "eu_mfn_rate_pct": 12.0,
                    "india_mfn_rate_pct": 10.0,
                    "uk_source": "UK Trade Tariff API",
                    "eu_source": "EU XI Tariff API",
                    "in_source": "WTO Timeseries API",
                    "uk_status": "ok",
                    "eu_status": "ok",
                    "in_status": "ok",
                }
            },
        },
    }

    def test_live_run_calls_vanik_agent(self, client):
        with (
            patch(
                "agent.batch_demo.vanik_agent",
                new=AsyncMock(return_value=self.MOCK_AGENT_RESULT),
            ) as mock_agent,
            patch(
                "agent.batch_demo.analyse_corridors",
                new=AsyncMock(return_value=_MIN_CORRIDOR_OK),
            ),
        ):
            resp = client.get("/v1/batch/demo?run=true")
            assert resp.status_code == 200
            assert mock_agent.call_count == 100

    def test_live_run_response_structure(self, client):
        with (
            patch(
                "agent.batch_demo.vanik_agent",
                new=AsyncMock(return_value=self.MOCK_AGENT_RESULT),
            ),
            patch(
                "agent.batch_demo.analyse_corridors",
                new=AsyncMock(return_value=_MIN_CORRIDOR_OK),
            ),
        ):
            body = client.get("/v1/batch/demo?run=true").json()
            assert body["ok"] is True
            assert len(body["results"]) == 100
            assert body["summary"]["total"] == 100

    def test_live_run_calculates_totals(self, client):
        with (
            patch(
                "agent.batch_demo.vanik_agent",
                new=AsyncMock(return_value=self.MOCK_AGENT_RESULT),
            ),
            patch(
                "agent.batch_demo.analyse_corridors",
                new=AsyncMock(return_value=_MIN_CORRIDOR_OK),
            ),
        ):
            body = client.get("/v1/batch/demo?run=true").json()
            summary = body["summary"]
            assert summary.get("total_duty_usd", 0) > 0
            assert summary.get("total_landed_usd", 0) > 0

    def test_live_run_handles_agent_exception(self, client):
        """Partial failure — one exception must not abort the batch."""

        async def _side_effect(*args, **kwargs):
            _side_effect.calls += 1  # type: ignore[attr-defined]
            if _side_effect.calls == 5:
                raise RuntimeError("MCP timeout")
            return TestBatchDemoLiveRun.MOCK_AGENT_RESULT

        _side_effect.calls = 0  # type: ignore[attr-defined]

        with (
            patch("agent.batch_demo.vanik_agent", side_effect=_side_effect),
            patch(
                "agent.batch_demo.analyse_corridors",
                new=AsyncMock(return_value=_MIN_CORRIDOR_OK),
            ),
        ):
            body = client.get("/v1/batch/demo?run=true").json()
            assert body["ok"] is True
            assert body["summary"]["total"] == 100
            assert body["summary"]["succeeded"] == 99
            assert body["summary"]["failed"] == 1


# ── CORS header tests ─────────────────────────────────────────────────


class TestBatchDemoCORS:
    """Verify CORS headers are present after the CORS middleware fix."""

    def test_cors_header_present_for_akeru_origin(self, client):
        resp = client.get(
            "/v1/batch/demo",
            headers={"Origin": "https://akeru.dev"},
        )
        assert "access-control-allow-origin" in resp.headers

    def test_options_preflight_returns_200(self, client):
        resp = client.options(
            "/v1/batch/demo",
            headers={
                "Origin": "https://akeru.dev",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code in (200, 204)
