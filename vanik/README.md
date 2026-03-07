# Vanik (Akeru)

Vanik is Akeru's trade tariff intelligence agent.

Architecture baseline in this workspace is aligned to `vanik_architecture-8.md` (`v0.12.0`) with:
- Manifest Search (MS) orchestration (`v2` NER + `v3` LLM fallback)
- Human confirmation gate before rate lookup
- MCP-grounded tariff retrieval via `vanik_api`
- Gemini-default docs ingestion path in `vanik_docs`

## Quick start

1. Create env file from `.env.example`.
2. Install deps: `pip install -e .[dev]`
3. Build HS index: `python scripts/build_hs_index.py --provider openai`
4. Start MCP server: `python -m mcp_servers.vanik_api.server`

## Notes

- `DOCS_PARSER=gemini` is default.
- WTO keys support primary/secondary failover in `mcp_servers/vanik_api/config.py`.
- This repository is a reference scaffold; some components are intentionally stubbed.
