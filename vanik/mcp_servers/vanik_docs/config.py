"""Configuration for vanik_docs MCP server."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class Settings:
    mcp_transport: str
    docs_parser: str
    db_path: Path


def load_settings() -> Settings:
    default_db = Path("/tmp/vanik_docs.db")
    db_path = Path(os.getenv("VANIK_DOCS_DB", str(default_db))).expanduser().resolve()

    return Settings(
        mcp_transport=os.getenv("MCP_TRANSPORT", "stdio"),
        docs_parser=os.getenv("DOCS_PARSER", "gemini").strip().lower(),
        db_path=db_path,
    )


settings = load_settings()
