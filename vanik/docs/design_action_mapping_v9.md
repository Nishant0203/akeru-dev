# Vanik Traceability Document
## Design Recommendations vs Actions Taken

Document version: 1.1  
Snapshot date: 2026-03-07  
Codebase: `/Users/nishantkumar/Documents/Akeru/vanik`  
Reference inputs:
- `/Users/nishantkumar/Downloads/vanik_architecture-9.md`
- `/Users/nishantkumar/Downloads/agentic_design_considerations.md`

---

## 1) Solution Components Created

| Component | Purpose | Key paths | Status |
|---|---|---|---|
| `vanik_api` MCP server | Exposes tariff lookup tools to agent via MCP | `mcp_servers/vanik_api/server.py`, `mcp_servers/vanik_api/tools/lookup_mfn.py` | Implemented |
| WTO client | India MFN retrieval (WTO Timeseries) with key failover | `mcp_servers/vanik_api/clients/wto.py` | Implemented |
| UK tariff client | GB MFN retrieval (HMRC UK API) | `mcp_servers/vanik_api/clients/uk_tariff.py` | Implemented |
| EU tariff client | EU MFN retrieval (HMRC XI API) | `mcp_servers/vanik_api/clients/eu_tariff.py` | Implemented |
| Runtime resilience | In-process TTL cache + per-corridor circuit breakers | `mcp_servers/vanik_api/runtime.py` | Implemented |
| API health diagnostics | Runtime status/caches/breakers + MS metrics block | `mcp_servers/vanik_api/tools/lookup_mfn.py` (`get_health`) | Implemented (partial metrics) |
| `vanik_docs` MCP server | Document ingest + HS lookup tools | `mcp_servers/vanik_docs/server.py`, `mcp_servers/vanik_docs/tools/lookup_hs.py` | Implemented |
| Docs storage | SQLite tariff row store + lookup | `mcp_servers/vanik_docs/db.py` | Implemented |
| Ingestion pipeline | Gemini-default parser with fallback parser | `mcp_servers/vanik_docs/ingest/pipeline.py` | Implemented |
| Manifest Search v2 | Fast local extraction stub (encoder placeholder) | `nes/v2_ner.py` | Implemented (stub logic) |
| Manifest Search v3 fallback | LLM fallback extraction stub | `nes/v3_llm.py` | Implemented (stub logic) |
| MS sufficiency + taxonomy | Sufficiency gate and explicit failure reasons | `nes/sufficiency.py` | Implemented |
| MS orchestrator | v2 -> sufficiency -> v3 fallback path | `nes/orchestrator.py` | Implemented |
| Feedback logging | JSONL fallback feedback and 24h counters | `nes/feedback_store.py` | Implemented |
| Single-agent orchestration | End-to-end agent flow + parallel corridor calls | `agent/vanik_agent.py` | Implemented |
| Human confirmation gate | Residual category tagging and formatting | `agent/confirmation_gate.py` | Implemented |
| Output synthesiser | Narrative + structured `LandedCost` output block | `agent/synthesiser.py` | Implemented |
| Provider abstraction | `MODEL_PROVIDER`-driven model adapter marker | `agent/providers.py` | Implemented |
| Session Gateway service | Session lifecycle, SSE stream, chat/API mode endpoints | `agent/session_gw.py` | Implemented (v1) |
| Session store | In-memory session state + TTL lifecycle | `agent/session_store.py` | Implemented (v1) |
| Anchor store | Durable task-anchor persistence (SQLite) | `agent/anchor_store.py` | Implemented (v1) |
| Query log | Append-only query audit trail | `agent/query_log.py` | Implemented (v1) |
| Gateway health aggregator | `/health` payload composition across components | `agent/health.py` | Implemented (v1) |
| SSE test harness utility | Incremental SSE consumer with timeout and diagnostics | `agent/tests/sse_test_utils.py` | Implemented |
| Evaluation harness | Ground-truth loader/report scaffold | `evaluation/harness/run_evals.py` | Implemented (scaffold) |
| Test suite | Unit tests for clients, agent, docs, MS, gateway | `mcp_servers/**/tests`, `agent/tests`, `nes/tests` | Implemented |

---

## 2) Mapping: Design Recommendation -> Action Taken

Legend:
- `Implemented`: coded and runnable in repo
- `Partial`: present but not fully aligned with target design
- `Gap`: not implemented yet

| Design recommendation | Source | Actions taken in codebase | Evidence | Status | Notes / correction target |
|---|---|---|---|---|---|
| Separation of concerns across retrieval/reasoning | DDIA Ch.1 framing in both docs | Split into MCP servers (`vanik_api`, `vanik_docs`), Manifest Search (`nes`), and agent orchestration (`agent`) | Repo module boundaries | Implemented | Good baseline decomposition |
| Fail loudly with structured errors | DDIA Ch.1 | Introduced `VanikAPIError` and normalized `{"ok": False, "error": ...}` envelopes | `mcp_servers/vanik_api/errors.py`, `lookup_mfn.py` | Implemented | Structured client errors available end-to-end in tariff lookups |
| Human confirmation gate before lookup | Architecture Section 6 | Gate formatting and selection path in agent flow | `agent/confirmation_gate.py`, `agent/vanik_agent.py` | Implemented | Route completeness guard now enforced before lookup |
| Parallelize independent corridor calls | Huyen AI Eng Ch.5 | UK/EU/IN rate calls run concurrently via `asyncio.gather` | `agent/vanik_agent.py` | Implemented | Matches latency guidance |
| Timeout-bound each external call | DDIA partial failure / Huyen latency | Each corridor lookup wrapped in `wait_for` with timeout | `agent/vanik_agent.py` | Implemented | Prevents single hanging upstream from stalling request |
| Response cache in front of APIs | Architecture Section 5.1 | Added in-process TTL cache keyed by `(hs,destination,date)` | `mcp_servers/vanik_api/runtime.py`, `lookup_mfn.py` | Implemented | Cache metadata included in response |
| Circuit breaker per external dependency | Architecture Section 6.6 | Added independent breakers for `IN`, `GB`, `EU` | `lookup_mfn.py`, `runtime.py` | Implemented | Isolates corridor degradation |
| Health endpoint / diagnostics | DDIA operability | Added gateway `/health` and API diagnostics block | `agent/health.py`, `agent/session_gw.py`, `lookup_mfn.py` | Partial | Distribution and index-currentness signals still stubbed |
| MS v2 default + v3 fallback | Architecture Section 3.1 | Implemented orchestrator calling v2 first and v3 on insufficiency | `nes/orchestrator.py` | Implemented | Correct fallback control flow exists |
| Explicit fallback failure taxonomy | Architecture update | Added reason taxonomy and logging (`no_product_terms`, etc.) | `nes/sufficiency.py`, `nes/feedback_store.py` | Implemented | Aligned with requirement |
| Feedback loop for retraining signal | Huyen continual learning | Logs fallback and invocation counts; computes 24h fallback rate | `nes/feedback_store.py` | Partial | Retrain trigger wiring still pending |
| Session Gateway as stateful boundary | Architecture Section 7.9 | Implemented session endpoints, resume, SSE, anchors API | `agent/session_gw.py` | Implemented (v1) | Redis-backed store and multi-instance behavior pending |
| Task anchors durable store | Architecture Section 7.9.7 | Implemented SQLite anchor store with CRUD and schema version field | `agent/anchor_store.py` | Implemented (v1) | Shared-store migration (Postgres) pending |
| SSE streaming contract | Architecture Section 7.9.2 | Gateway emits event stream; tests consume incrementally with done-break | `agent/session_gw.py`, `agent/tests/sse_test_utils.py` | Implemented | Endpoint intentionally remains persistent |
| Model-agnostic provider selection | Architecture principle | Added `MODEL_PROVIDER` abstraction in agent provider layer | `agent/providers.py` | Partial | Marker-level adapter, not full LLM integration |
| Gemini default for docs ingest | User-requested + architecture updates | Set docs parser default to Gemini in settings/env and pipeline | `mcp_servers/vanik_docs/config.py`, `.env.example` | Implemented | Fallback parser retained for resilience |
| Derived data indexed in SQLite for point lookups | DDIA Ch.3 | Implemented tariff row schema and indexed lookup | `mcp_servers/vanik_docs/db.py` | Implemented | Point-query path established |
| Schema evolution by rebuild for derived data | DDIA Ch.4 | Re-ingest pattern resets doc type then reinserts | `db.py`, `pipeline.py` | Partial | Full rebuild contract/version manifest pending |
| Guardrails at boundaries (input + output) | Huyen Ch.8 | Input HS format guardrail present | `agent/vanik_agent.py` | Partial | Output guardrail layer not yet implemented |
| Append-only audit/query log | DDIA Ch.11 | Added append-only query logging for session and API mode | `agent/query_log.py`, `agent/session_gw.py` | Implemented (v1) | Needs idempotent dedupe policy for retries |
| Distribution monitoring and covariate shift | Huyen DMLS Ch.8 | Placeholder fields in health payload | `agent/health.py` | Gap | Add live OOV/entity shift computations |
| Retrain trigger with dual conditions | Huyen DMLS Ch.9 | Not yet present | N/A | Gap | Add `new_reviewed_examples` + fallback threshold gate |
| Startup recovery and ingestion-state marker | DDIA partial-failure handling | Not yet present | N/A | Gap | Add `.ingestion_state` lifecycle and startup check |
| A2A-compatible structured output data part | Architecture section 5 | Added stable `vanik.compliance.LandedCost` data block | `agent/synthesiser.py` | Implemented | Transport-level A2A remains deferred |
| Evaluation by slice and judge patterns | Huyen DMLS/AIE | Ground-truth harness and record file created | `evaluation/harness/run_evals.py`, `evaluation/ground_truth/records.json` | Partial | Slice metrics/judge evaluator not yet built |
| Naming consistency (`nes/` vs `manifest_search/`) | Architecture repo structure section | Current implementation still uses `nes/` module path | repo structure | Gap | Rename package + imports to `manifest_search/` across repo |

---

## 3) Additional Design Considerations Implemented (Not Explicitly Requested)

1. Primary/secondary WTO key failover in client call path.
2. Thread-safety for runtime cache and circuit breaker via `Lock` to prevent concurrent corruption.
3. Corridor-isolated breaker design so one degraded upstream does not penalize others.
4. Uniform tool response envelope (`ok/data/error`) for easier downstream handling.
5. Deterministic and offline-testable external API parsing using `httpx.MockTransport`.
6. Strict HS code format checks (6/8/10 digits) before expensive retrieval path.
7. Environment-driven operational tuning for cache TTL, breaker thresholds, and timeouts.
8. Fallback parser retained in docs ingestion to avoid hard failure when default parser path errors.

---

## 4) Current Corrections Recommended (Priority)

1. Remove hardcoded API keys from source/env templates and rotate exposed keys.
2. Complete output guardrails and schema validation before response release.
3. Add covariate-shift and OOV metrics backed by real MS telemetry.
4. Make docs ingest replace path atomic with explicit SQLite transaction boundaries (`BEGIN IMMEDIATE` -> delete + insert -> `COMMIT`, `ROLLBACK` on failure).
5. Add retrain trigger automation (`new_reviewed_examples >= 100` AND `fallback_rate_24h >= 15%`).
6. Rename `nes/` package to `manifest_search/` and update all imports/tests/docs.

---

## 5) Verification Snapshot

- Unit tests currently pass (`pytest`): `24 passed`.
- Static lint (`ruff`) was not runnable in current environment because `ruff` is not installed.

---

## 6) Section 7.9.2 Annotation

Section 7.9.2 (`SSE with POST messages`) annotation for implementation notes:
- The Session Gateway SSE endpoint remains a persistent open connection by design; no consumer limit/timeout logic is added to endpoint behavior for tests.
- Streaming correctness is verified by the shared test harness utility at `/Users/nishantkumar/Documents/Akeru/vanik/agent/tests/sse_test_utils.py`, which performs incremental consumption, terminates on terminal event (`done`/target type), and enforces bounded timeout diagnostics.

---

## 7) Architecture Deltas Pending (to patch `vanik_architecture-9.md`)

| Gap | Severity | Required architecture update |
|---|---|---|
| `nes/` vs `manifest_search/` naming not called out as open migration | Medium | Add explicit pending-rename note in repo structure or implementation status section |
| Session gateway components not reflected in traceability earlier | High | Keep Section 7.9 implementation status synced with gateway/session/anchor modules |
| WTO key failover behavior not explicitly documented | Medium | Add to Section 4 (WTO source) or 6.6 (resilience): primary->secondary key fallback contract |
| Uniform `ok/data/error` response envelope not formalized | Medium | Add to Section 3 or 5 (tool contract) as canonical response envelope |
| `httpx.MockTransport` testing pattern not documented | Low | Add to Section 10 testing strategy note for deterministic upstream mocking |
| Secrets management principle under-specified | High | Add explicit secret-handling constraint to architecture principles section (Section 12 target per review) |
| Ingestion atomicity correction lacked precision | Medium | Specify SQLite transactional replace semantics in correction/action text |
