"""Document ingestion pipeline with Gemini default."""

from __future__ import annotations

import os

from mcp_servers.vanik_docs.db import reset_and_insert
from mcp_servers.vanik_docs.ingest.gemini_parser import extract_tariff_schedule
from mcp_servers.vanik_docs.ingest.gemini_uploader import (
    delete_uploaded_file,
    upload_tariff_document,
)
from mcp_servers.vanik_docs.ingest.pandas_parser import extract_tariff_schedule_pandas


def ingest_document(file_path: str, doc_type: str = "cbic", allow_fallback: bool = True) -> dict:
    """Ingest tariff docs into SQLite, defaulting to Gemini parser."""
    parser = os.getenv("DOCS_PARSER", "gemini").strip().lower()

    if doc_type not in {"cbic", "taric"}:
        return {
            "ok": False,
            "error": {
                "code": "invalid_doc_type",
                "message": "doc_type must be 'cbic' or 'taric'",
            },
        }

    parser_used = parser
    try:
        if parser == "pandas":
            rows = extract_tariff_schedule_pandas(file_path, doc_type=doc_type)
        else:
            try:
                file_uri = upload_tariff_document(file_path)
                try:
                    rows = extract_tariff_schedule(file_uri, doc_type=doc_type)
                finally:
                    delete_uploaded_file(file_uri)
            except Exception:
                if not allow_fallback:
                    raise
                parser_used = "pandas"
                rows = extract_tariff_schedule_pandas(file_path, doc_type=doc_type)

        count = reset_and_insert(rows, doc_type=doc_type)
        return {
            "ok": True,
            "data": {
                "doc_type": doc_type,
                "file_path": file_path,
                "rows_inserted": count,
                "parser_used": parser_used,
            },
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": {
                "code": "ingestion_failed",
                "message": str(exc),
                "details": {"doc_type": doc_type, "file_path": file_path},
            },
        }
