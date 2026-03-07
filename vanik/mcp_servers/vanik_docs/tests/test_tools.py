from mcp_servers.vanik_docs.tools.lookup_hs import (
    get_docs_server_info,
    ingest_cbic_document,
    ingest_taric_document,
    lookup_hs_cbic,
    lookup_hs_taric,
)


def test_ingest_and_lookup_cbic_roundtrip() -> None:
    ingest = ingest_cbic_document("/tmp/cbic.xlsx")
    assert ingest["ok"] is True

    out = lookup_hs_cbic("870830")
    assert out["ok"] is True
    assert out["data"]["count"] >= 1


def test_ingest_and_lookup_taric_roundtrip() -> None:
    ingest = ingest_taric_document("/tmp/taric.xlsx")
    assert ingest["ok"] is True

    out = lookup_hs_taric("8708301090")
    assert out["ok"] is True
    assert out["data"]["count"] >= 1


def test_docs_server_info() -> None:
    info = get_docs_server_info()
    assert info["ok"] is True
    assert "db_path" in info["data"]
