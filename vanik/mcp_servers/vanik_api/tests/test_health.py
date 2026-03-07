from mcp_servers.vanik_api.tools import lookup_mfn


def test_health_includes_docs_and_distribution_blocks(monkeypatch) -> None:
    monkeypatch.setattr(lookup_mfn, "fallback_rate_24h", lambda: 0.15)
    monkeypatch.setattr(lookup_mfn, "v3_invocations_24h", lambda: 12)
    monkeypatch.setattr(
        lookup_mfn,
        "get_docs_server_info",
        lambda: {"ok": True, "data": {"db_path": "/tmp/docs.db", "row_count": 42, "is_current": True}},
    )

    payload = lookup_mfn.get_health()

    assert payload["status"] in {"ok", "degraded"}
    assert "vanik_docs" in payload["components"]
    assert payload["components"]["vanik_docs"]["status"] == "ok"
    assert payload["components"]["vanik_docs"]["db"]["row_count"] == 42
    assert payload["components"]["manifest_search"]["fallback_rate_24h_pct"] == 15.0
    assert payload["components"]["manifest_search"]["distribution"]["oov_product_term_rate_pct"] == 0.0
