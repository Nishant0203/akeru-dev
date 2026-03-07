"""MCP server entrypoint for vanik_docs."""

from __future__ import annotations

from mcp_servers.vanik_docs.config import settings
from mcp_servers.vanik_docs.tools.lookup_hs import (
    get_docs_server_info,
    ingest_cbic_document,
    ingest_taric_document,
    lookup_hs_cbic,
    lookup_hs_taric,
)

try:
    from mcp.server.fastmcp import FastMCP
except Exception:  # pragma: no cover
    FastMCP = None


def build_server() -> object | None:
    """Build FastMCP app when dependency is available."""
    if FastMCP is None:
        return None

    app = FastMCP("vanik_docs")
    app.add_tool(lookup_hs_cbic)
    app.add_tool(lookup_hs_taric)
    app.add_tool(ingest_cbic_document)
    app.add_tool(ingest_taric_document)
    app.add_tool(get_docs_server_info)
    return app


def main() -> None:
    """Run FastMCP app or print fallback instructions."""
    app = build_server()
    if app is None:
        print("FastMCP not installed. Available tools: lookup_hs_cbic, lookup_hs_taric, ingest_cbic_document, ingest_taric_document, get_docs_server_info")
        return

    try:
        app.run(transport=settings.mcp_transport)
    except TypeError:
        app.run()


if __name__ == "__main__":
    main()
