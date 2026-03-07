"""MCP server entrypoint for vanik_api."""

from __future__ import annotations

from mcp_servers.vanik_api.config import settings
from mcp_servers.vanik_api.tools.lookup_mfn import get_health, get_mfn_rate, get_supported_corridors
from mcp_servers.vanik_api.tools.search_hs_schedule import search_hs_schedule

try:
    from mcp.server.fastmcp import FastMCP
except Exception:  # pragma: no cover - dependency may be absent in local scaffold
    FastMCP = None


def build_server() -> object | None:
    """Build FastMCP app when dependency is available."""
    if FastMCP is None:
        return None

    app = FastMCP("vanik_api")
    app.add_tool(get_mfn_rate)
    app.add_tool(get_supported_corridors)
    app.add_tool(search_hs_schedule)
    app.add_tool(get_health)
    return app


def main() -> None:
    """Run FastMCP app or print fallback instructions."""
    app = build_server()
    if app is None:
        print("FastMCP not installed. Available tools: get_mfn_rate, get_supported_corridors, search_hs_schedule, get_health")
        return

    try:
        app.run(transport=settings.mcp_transport)
    except TypeError:
        app.run()


if __name__ == "__main__":
    main()
