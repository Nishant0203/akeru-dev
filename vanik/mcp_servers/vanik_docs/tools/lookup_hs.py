"""vanik_docs lookup and ingestion tools."""

from __future__ import annotations

from mcp_servers.vanik_docs.db import db_info, lookup_hs
from mcp_servers.vanik_docs.ingest.pipeline import ingest_document


def lookup_hs_cbic(hs_code: str) -> dict:
    """Lookup CBIC rows by HS code."""
    rows = lookup_hs(hs_code, doc_type="cbic")
    return {"ok": True, "data": {"rows": rows, "count": len(rows), "doc_type": "cbic"}}


def lookup_hs_taric(hs_code: str) -> dict:
    """Lookup TARIC rows by HS code."""
    rows = lookup_hs(hs_code, doc_type="taric")
    return {"ok": True, "data": {"rows": rows, "count": len(rows), "doc_type": "taric"}}


def ingest_cbic_document(file_path: str, allow_fallback: bool = True) -> dict:
    """Ingest CBIC schedule into SQLite."""
    return ingest_document(file_path=file_path, doc_type="cbic", allow_fallback=allow_fallback)


def ingest_taric_document(file_path: str, allow_fallback: bool = True) -> dict:
    """Ingest TARIC schedule into SQLite."""
    return ingest_document(file_path=file_path, doc_type="taric", allow_fallback=allow_fallback)


def get_docs_server_info() -> dict:
    """Return docs DB diagnostics."""
    return {"ok": True, "data": db_info()}
