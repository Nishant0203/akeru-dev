# Vanik / Akeru — Session Consolidated Change List
**Version:** 3.0 (Final session review)
**Date:** 2026-03-21
**Status:** Awaiting repo file confirmation on items marked [VERIFY]

This document consolidates ALL changes discussed in this session.
It supersedes v1.0 and v2.0.

Items are marked:
  [NEW]     — file does not exist in repo today
  [REPLACE] — file exists, entire content replaced
  [MODIFY]  — file exists, targeted changes only
  [VERIFY]  — need current file contents to confirm exact diff
  [CONFIG]  — environment variable or deployment change only

---

## Commit Map — 10 Commits

```
Commit 1  — Foundation              providers.py, prompts.py, json_parser.py
Commit 2  — Pipeline correctness    v3_llm.py, synthesiser.py
Commit 3  — Boundary enforcement    sanitiser.py, entity_stripper.py,
                                    boundary_extractor.py, result_normaliser.py
Commit 4  — Resolution layer        Dictionary pipeline, product/entity
                                    registries, query_builder.py
Commit 5  — Synthesis output        Narrative quality, double-gate fix,
                                    rates_unavailable, no_match message
Commit 6  — Schema adapter          Customer schema config, two-lane batch
Commit 7  — Batch ingestion         batch/ package, job_store Lane B,
                                    chunked processing, deduplicated LLM
Commit 8  — φ² post page
Commit 9  — Frontend navigation     Homepage star click targets
Commit 10 — VPS / infra             CX23 → CX43, Ollama setup
```

---

## Commit 1 — Foundation

### `vanik/agent/providers.py` [REPLACE]

**Why:** Returns a dict instead of a real client. Every LLM call crashes
with AttributeError. Also adds Mistral and Ollama providers, and `call_llm()`
— a single provider-agnostic completion function used by all call sites.

Key changes from current file:
- `get_completion_client()` returns real client objects for all four providers
- `get_model_name(task)` routes correct model per provider and task
- `call_llm()` — new function, handles Anthropic/OpenAI/Mistral/Ollama response shapes
- Azure AI Foundry: uses `OpenAI(base_url=...)` not `AzureOpenAI()` — Microsoft deprecated AzureOpenAI for Foundry in May 2026
- Ollama: HTTP via httpx, no SDK

Supported providers via `MODEL_PROVIDER` env var:
```
anthropic  → claude-haiku-4-5-20251001 (extraction), claude-sonnet-4-6 (synthesis)
openai     → gpt-4o-mini (extraction), gpt-4o (synthesis)
           → also Azure AI Foundry: set OPENAI_API_BASE to Foundry endpoint
           → also Phi-2: OPENAI_EXTRACTION_MODEL=microsoft-phi-2
mistral    → mistral-small-latest (extraction), mistral-large-latest (synthesis)
ollama     → phi4-mini (extraction), llama3.1:8b or deepseek-r1:7b (synthesis)
           → qwen2.5:7b recommended for Hindi synthesis
```

Note on SLMs: Cloud SLMs (Phi-2 on Foundry, Mistral Small API) still cross
the network boundary. Only Ollama running locally provides genuine on-premise
inference with no boundary crossing.

---

### `vanik/agent/prompts.py` [NEW]

**Why:** LLM prompts currently scattered across stub files. Single registry
with one prompt per task, written to SLM constraints (short, example-driven,
explicit format). Works for all models — no per-model variants needed.

```
MS_V3_EXTRACTION       — entity extraction, 8 rules, one example
COMPLIANCE_SYNTHESIS   — structured JSON + 2-3 sentence narrative
COMPLIANCE_SYNTHESIS_HI — Hindi version
PROMPT_VERSION         — "vanik-prompts-v1.0" logged per request
```

---

### `vanik/agent/json_parser.py` [NEW]

**Why:** SLM models produce malformed JSON (trailing commas, markdown fences,
leading text). Robust extraction from any LLM output regardless of model.

Three-pass: direct parse → extract first `{...}` block → fix trailing commas.
Returns `None` if no valid JSON found — caller escalates, never silently
passes wrong data.

---

## Commit 2 — Pipeline Correctness

### `vanik/nes/v3_llm.py` [REPLACE]

**Why:** Stub returning hardcoded `origin=IN, destination=GB` on every call.
Because `ner_is_sufficient()` returns True for IN+GB, the stub failure is
invisible — wrong extractions reach the synthesiser silently.

Changes:
- Real provider-agnostic Haiku/GPT-4o-mini call via `call_llm()`
- Uses `MS_V3_EXTRACTION` prompt from prompts.py
- `parse_llm_json()` for robust output parsing
- Empty dict on failure — orchestrator SufficiencyCheck catches it
- `temperature=0.0` — JSON tasks must be deterministic

---

### `vanik/agent/synthesiser.py` [REPLACE]

**Why:** Template-only, no LLM call, no product context in narrative,
MFN not explained, missing corridor data not explained, no Hindi path,
IGST note present but not explained.

Changes:
- `build()` becomes async — real LLM synthesis via `call_llm()`
- Template `_template_build()` stays as named fallback
- `synthesis_method` field in output: `"llm"` | `"template"` | `"template_fallback"`
- Narrative now includes:
  - Product + corridor context: "Tariff lookup for cotton shirts (HS 6205200000), corridor IN → GB"
  - MFN explained in plain English
  - IGST note always present for IN corridor
  - Per-unavailable-corridor implication + next action
- `product_terms` parameter added — narrative opens with what was asked
- `_lang` parameter added — routes to Hindi synthesis path
- Hindi: `COMPLIANCE_SYNTHESIS_HI` prompt + `synthesis_hindi` model task

---

## Commit 3 — Boundary Enforcement

**Principle:** Keep-list over strip-list. Primary enforcement extracts only
permitted fields. Sanitiser and entity stripper are secondary defence.

### `vanik/manifest_search/sanitiser.py` [NEW]

Strips structured sensitive patterns before any external LLM call.
Returns `(sanitised_query, strip_log)`.
strip_log → `sanitisation_audit_log.jsonl` (separate from query log).

Patterns: PO numbers, unit pricing, counterparty labels, internal part
numbers, bulk quantity references, internal reference codes.

---

### `vanik/manifest_search/entity_stripper.py` [NEW]

Strips unstructured proper nouns (entity names, product grades, legal
suffixes) found in `entity_registry.yaml` before any LLM call.

Uses sliding window (4-word → 3-word → 2-word phrases) against
DictionaryIndex rather than hardcoded patterns. Also strips:
- Internal grade codes matching `[A-Z]{1,4}[\s-]?\d{2,4}` pattern
- Legal suffixes: Ltd, Limited, Inc, GmbH, Pvt, Corp, etc.

Returns `(cleaned_query, strip_log)` — combined with sanitiser log
into single `sanitisation_audit_log.jsonl` entry per query.

---

### `vanik/manifest_search/boundary_extractor.py` [NEW]

**The primary boundary enforcement layer.**

Does not strip — keeps only permitted fields, discards everything else.
Permitted fields: product category words, origin ISO-2, destination ISO-2.

Keep rules:
- Discard: any token containing a digit (codes, prices, quantities)
- Discard: Title Case tokens mid-sentence (proper nouns, entity names)
- Discard: corridor words (from, to, export, import, origin, destination)
- Discard: tariff vocabulary (duty, rate, tariff, hs, classify)
- Keep: lowercase common nouns that remain

For structured batch input (SchemaAdapter), BoundaryExtractor is not needed
— fields are already separated by schema. BoundaryExtractor is the fallback
for unstructured conversational input.

---

### `vanik/agent/result_normaliser.py` [NEW]

Synthesiser never sees raw API JSON or Python exception objects.

Converts every raw MCP response to a normalised struct:
```python
{"corridor": "IN_to_GB", "status": "ok", "mfn_rate_pct": 12.0, ...}
# or
{"corridor": "IN_to_GB", "status": "unavailable", "reason": "timeout"}
```

Handles: asyncio.TimeoutError, generic Exception, MCP error dict, success.

Wire in `vanik_agent.py`: replaces inline `normalize()` lambda.

---

### `vanik/nes/orchestrator.py` [MODIFY] [VERIFY]

Wire boundary enforcement chain:

```python
# Step 1 — structured pattern stripping
sanitised, sanitise_log = sanitise(raw_query)

# Step 2 — entity name and grade stripping
cleaned, entity_log = strip_entities(sanitised)

# Step 3 — write combined audit log
_write_sanitisation_log(raw_query, cleaned, sanitise_log + entity_log)

# Step 4 — deterministic extraction on clean query
v2_entities = extract_v2(cleaned)
v2_entities["_raw"] = cleaned   # sanitised version, not original
```

---

### `vanik/agent/vanik_agent.py` [MODIFY] [VERIFY]

Multiple wiring changes — all in one commit:

```python
# 1. Wire BoundaryExtractor for conversational input
from manifest_search.boundary_extractor import extract_permitted
sanitised, _ = sanitise(user_query)
cleaned = extract_permitted(sanitised)  # keep-list enforcement
entities = dict(precomputed_entities or await ms_extract(cleaned))

# 2. Wire result_normaliser (replaces inline normalize lambda)
from agent.result_normaliser import normalise_rate_result
uk_rate = normalise_rate_result(uk_raw, "IN_to_GB")
eu_rate = normalise_rate_result(eu_raw, "IN_to_EU")
in_rate = normalise_rate_result(in_raw, "world_to_IN")

# 3. All-unavailable check before synthesiser
if all(r["status"] == "unavailable" for r in [uk_rate, eu_rate, in_rate]):
    return {
        "ok": False, "status": "rates_unavailable",
        "hs_code": confirmed_code,
        "narrative": (
            f"Rates for HS {confirmed_code} could not be retrieved. "
            f"UK: {uk_rate.get('reason')}. EU: {eu_rate.get('reason')}. "
            f"IN: {in_rate.get('reason')}. "
            f"Retry or check trade-tariff.service.gov.uk directly."
        ),
    }

# 4. Pass description from gate options (bug fix)
confirmed_desc = next(
    (o["description"] for o in options
     if str(o["commodity_code"]) == confirmed_code), ""
)

# 5. Pass _lang and product_terms to synthesiser
return await _lookup_and_synthesise(
    entities=entities,
    confirmed_code=confirmed_code,
    human_confirmed=True,
    hs_code_source="human_confirmed",
    description=confirmed_desc,
    lang=entities.get("_lang", "en"),
    product_terms=entities.get("product_terms", []),
)
```

---

## Commit 4 — Resolution Layer

Product terms treated as named entities — same resolution stack as supplier
names. Lookup before any probabilistic processing.

### `vanik/dictionary/` [NEW PACKAGE]

**`ingestor.py`** — Generic dictionary ingestion pipeline.
- Accepts CSV, JSON, or Python list of `DictionaryEntry` objects
- Normalises to common schema: canonical, dict_type, aliases, metadata
- Atomic replace per dict_type (DELETE old + INSERT new in transaction)
- FTS5 virtual table with porter tokenizer for stemmed search
- Version tracking: batch_id = `{dict_type}_{hash}_{timestamp}`
- Returns batch_id for audit trail

**`dictionary_index.py`** — Query interface for all dictionary types.
- `lookup(term, dict_type)` → `LookupResult`
- Four-tier resolution per lookup:
  1. Exact canonical match
  2. Alias exact match
  3. FTS5 porter stemmed match
  4. Fuzzy token sort ratio ≥ 85 (rapidfuzz)
- `list_batches()` — health check, shows what is loaded and when

**`entity_stripper.py`** — Queries DictionaryIndex for entity types.
Replaces `manifest_search/entity_stripper.py` — same interface,
backed by DictionaryIndex instead of YAML patterns.

---

### `vanik/data/product_registry.yaml` [NEW]

Seed data for product dictionary. Ingested at startup.

Structure per entry: canonical name, chapter hint, hs_heading,
aliases (synonyms and variant descriptions), common_misspellings.

Seed entries: cotton_shirts, cotton_shorts, brake_callipers,
titanium_fasteners, hot_rolled_coils, steel_wire_rod.

Ambiguous terms list: steel, cotton, aluminium, plastic, parts,
components, materials — these trigger disambiguation gate.

Disambiguation prompts: per ambiguous term, a clarification question
and structured options (e.g. "What form is the steel in?").

---

### `vanik/data/entity_registry.yaml` [NEW]

Seed data for entity dictionary. Supplier names, known business units,
legal entities. Ingested at startup.

Separate from product_registry — entity names are stripped by
entity_stripper, never resolved to HS codes.

---

### `vanik/manifest_search/product_resolver.py` [NEW]

Queries DictionaryIndex for dict_type="product".

Returns `ProductResolution` with status: `resolved` | `ambiguous` | `unknown`.

Ambiguous: returns clarification_question + clarification_options
from product_registry.yaml disambiguation section.

---

### `vanik/manifest_search/symspell_corrector.py` [NEW]

Domain-specific spell correction using dictionary built from 16,597
tariff descriptions. Runs before product resolver.

`build_tariff_dictionary(db_path, output_path)` — run once after DB ingest.
Extracts word frequencies from tariff descriptions → tariff_dictionary.txt.

`correct(term)` — "coton" → "cotton", "callipars" → "callipers".
Falls back to original if no suggestion at edit distance ≤ 2.

---

### `vanik/nes/query_builder.py` [MODIFY] [VERIFY]

Module 2 updated to use resolution layer before building search strategies.

```python
from manifest_search.product_resolver import resolve, ProductResolution
from manifest_search.symspell_corrector import correct as spellcorrect

def build_search_plan(extraction_result) -> SearchPlan | DisambiguationRequired:
    for term in extraction_result.product_terms:
        corrected  = spellcorrect(term)
        resolution = resolve(corrected)

        if resolution.status == "ambiguous":
            return DisambiguationRequired(
                original_term=term,
                question=resolution.clarification_question,
                options=resolution.clarification_options,
                chapter_hint=resolution.chapter_hint,
            )

        if resolution.status == "resolved":
            # FTS5 query expands to canonical + top 2 aliases
            search_terms = [resolution.canonical] + resolution.aliases[:2]
            chapter_hint = resolution.chapter_hint
        else:
            search_terms = [corrected]
            chapter_hint = _lookup_chapter_hint(corrected)

        strategies.append(SearchStrategy(
            type="fts", terms=search_terms, chapter_hint=chapter_hint
        ))

    strategies.append(SearchStrategy(type="uk_api_search", ...))
    return SearchPlan(strategies=strategies, min_results=3)
```

`DisambiguationRequired` dataclass added.

---

### `vanik/nes/v2_ner.py` [MODIFY] [VERIFY]

`_extract_product_terms()` currently passes raw query as product_terms —
the root cause of the cotton shirts → brake callipers failure.

Fix: strip corridor words only, preserve material adjectives.

```python
def _extract_product_terms(raw: str) -> list[str]:
    text     = _CORRIDOR_RE.sub("", raw).strip()    # strip "from India to UK"
    text     = _STOPWORD_RE.sub("", text).strip()   # strip "duty/tariff/rate"
    primary  = text.strip()                          # "cotton shirts" — preserves adjective
    words    = primary.split()
    fallback = words[-1] if len(words) > 1 else None # "shirts" — last noun only
    terms    = [primary] if primary else []
    if fallback and fallback != primary:
        terms.append(fallback)
    return terms
```

Before fix: `["cotton shirts from India to UK"]` → LIKE match fails → no results
After fix:  `["cotton shirts", "shirts"]` → FTS5 finds 6205 codes

---

### Admin endpoints [NEW — in session_gw.py]

```
POST /v1/admin/dictionary/ingest
  Header: X-Dictionary-Type: product|entity|grade|business_unit
  Body: multipart CSV or JSON file
  Auth: VANIK_ADMIN_KEY
  Returns: {batch_id, type, entry_count}

GET /v1/admin/dictionary/status
  Returns: loaded batches per dict_type with timestamps
```

---

## Commit 5 — Synthesis Output Quality

### `vanik/agent/session_gw.py` [MODIFY] [VERIFY]

**Double gate bug:** Classification gate renders twice for the same query.
Cause: gate events replayed on SSE reconnect.

```python
# Events excluded from SSE reconnect replay
REPLAY_EXCLUDED_TYPES = {
    "awaiting_confirmation",
    "awaiting_disambiguation",
    "error",
}

def _emit(self, event: dict) -> None:
    if event.get("type") not in REPLAY_EXCLUDED_TYPES:
        self.last_response_events.append(event)
    self.event_queue.put_nowait(event)
```

---

### `vanik/agent/vanik_agent.py` [MODIFY] [VERIFY]

**No-match message:** Currently references "ceramic tiles" as example —
hardcoded, unrelated to the user's actual query.

```python
# Fix — echo back what was actually searched
return {
    "ok": False,
    "status": "no_match",
    "message": (
        f"No HS code match found for "
        f"'{' '.join(entities.get('product_terms', [user_query]))}'. "
        f"Try entering a 6, 8, or 10-digit HS code directly."
    ),
    "allow_manual_hs": True,
}
```

**DisambiguationRequired handling:** New return path from query_builder.

```python
search_plan = build_search_plan(entities)
if isinstance(search_plan, DisambiguationRequired):
    return {
        "ok": False,
        "status": "awaiting_disambiguation",
        "message": search_plan.question,
        "options": search_plan.options,
        "original_term": search_plan.original_term,
        "chapter_hint": search_plan.chapter_hint,
    }
```

---

## Commit 6 — Schema Adapter

### `vanik/schema/schema_adapter.py` [NEW]

Customer-specific two-lane batch processing.

**Lane A** — permitted fields: product_category, origin, destination, hs_code.
These enter the pipeline.

**Lane B** — reference fields: PO number, supplier, quantity, price, etc.
These are held in `AdaptedRow.reference` and never forwarded to any
LLM call or pipeline stage. Joined back at the reporter.

Schema defined per customer in a YAML config file:

```yaml
customer_id: garment_co
field_mapping:
  product_category: {source_column: product}
  origin:           {source_column: origin_country, transform: iso2_normalise}
  destination:      {source_column: destination,    transform: iso2_normalise}
  hs_code:          {source_column: tariff_code}
reference_fields:
  - po_number
  - supplier
  - quantity
  - unit_price
  - style_code
```

`adapt_batch()` returns list of AdaptedRow — Lane B preserved but isolated.
No code change per customer — schema YAML is the entire implementation.

---

### `vanik/config/schemas/` [NEW DIRECTORY]

Customer schema YAML files. One per customer type.
`generic.yaml` — default for ad-hoc uploads with no customer config.

Admin endpoint:
```
POST /v1/admin/schemas/{schema_id}  — upload new schema YAML
GET  /v1/admin/schemas              — list available schemas
```

---

## Commit 7 — Batch Ingestion (Revised)

This commit supersedes the batch design in v2.0 of the consolidated doc.
Key changes: durable Lane B in SQLite, chunked processing, deduplicated
LLM calls, template synthesis for batch output.

### `vanik/batch/__init__.py` [NEW]

### `vanik/batch/batch_processor.py` [NEW]

**Key architectural changes from previous design:**

**1 — No per-row LLM calls.**
LLM called only for unique unresolved product terms across the batch.
50 unique unresolved terms in 10,000 rows = ≤ 50 LLM calls, not 10,000.

```python
# Deduplicate before any LLM call
term_resolutions = await _resolve_all_terms(items)
# _resolve_all_terms: ProductResolver first, LLM only for unknown terms
```

**2 — Template synthesis for batch output.**
Batch output is a CSV. LLM synthesis is for conversational narrative quality.
Template is correct for structured batch output — faster, cheaper, consistent.

**3 — Chunked processing for scale.**
```python
CHUNK_SIZE = 500   # bounded memory footprint regardless of batch size
for chunk in range(0, len(items), CHUNK_SIZE):
    await asyncio.gather(*[_one(item) for item in chunk])
    await asyncio.sleep(0)   # yield between chunks
```
Handles 100,000 rows without creating 100,000 coroutines simultaneously.
At `MAX_CONCURRENT=5`, rate lookups are the bottleneck — parallelised per chunk.

**4 — Parallelise rate lookups, not extractions.**
The I/O-bound operation in batch is the three MCP rate lookups per row.
This is what `MAX_CONCURRENT` should serve.

**5 — Resumable on restart.**
```python
completed = store.get_completed_row_indices(job_id)
pending   = [i for i in items if i.row_index not in completed]
# Skips already-done rows on restart
```

---

### `vanik/batch/batch_parser.py` [NEW]

CSV and JSON parsing. `schema_path` parameter for SchemaAdapter integration.
Streaming parse for large batches — yields chunks, does not load full file.

---

### `vanik/batch/batch_reporter.py` [NEW]

Output CSV joins Lane A results + Lane B reference data.
Reference columns appear first — for direct matching to customer PO system.
`needs_review` column flags auto-selected HS codes and unavailable corridors.

---

### `vanik/batch/batch_analyser.py` [NEW]

Optional — surfaces insights from joined output.
No LLM. Pure computation on BatchResult list.

Insights surfaced:
- `needs_review` items grouped by supplier (from Lane B reference)
- EU unavailable items listed by PO number
- Failed items with error reason

Customer receives actionable follow-up list with their own identifiers.

---

### `vanik/batch/object_store.py` [NEW]

Stores input CSV and output CSV. `VANIK_OBJECT_STORE` controls backend:
- `local` — `/var/lib/vanik/batch/` (VPS filesystem, current)
- `gcs` — Google Cloud Storage
- `s3` — S3-compatible (Hetzner Object Storage when needed)

---

### `vanik/batch/job_store.py` [NEW]

Three SQLite tables in `/var/lib/vanik/batch_jobs.db`:

```sql
batch_jobs        — job metadata, status, counts
batch_row_refs    — Lane B reference payload per row (durable)
batch_row_state   — per-row processing state (resumable)

-- Required index
CREATE INDEX idx_row_state_job_status
ON batch_row_state (job_id, status);
```

Lane B written atomically before processing starts.
`join_results(job_id)` — single query joins row state + Lane B.
`cleanup_job(job_id)` — deletes Lane B and row state after download.
No retention of customer reference data beyond delivery.

**Scale limits:**
- SQLite: up to ~50,000 rows before write contention
- asyncio chunked: handles 100,000 rows with CHUNK_SIZE=500
- Hard limit `VANIK_BATCH_MAX_ITEMS=10000` per request
- Customers with 100K+ invoices split into multiple requests
- Migration path: SQLite → Redis for row state at enterprise scale

---

### Batch endpoints in `vanik/agent/session_gw.py` [MODIFY]

```
POST /v1/batch/upload
  Accepts: multipart CSV + optional schema_id
  Returns: {job_id, status: "queued", total_rows}
  Max: VANIK_BATCH_MAX_ITEMS rows

GET  /v1/batch/jobs/{job_id}
  Returns: status, counts, download_url when done

GET  /v1/batch/jobs/{job_id}/download
  Returns: CSV stream, triggers cleanup_job after delivery

POST /v1/admin/batch/retry/{job_id}
  Re-queues failed job — reads input from object store
```

**Startup hook:**
```python
async def _resume_interrupted_batches() -> None:
    # Re-queue jobs in "processing" state on server restart
```

---

## Commit 8 — φ² Post Page

### `phi2/index.html` [NEW]

Post: *What Are You Actually Sharing When You Use AI at Work?*

Five Vidhi anchor concepts:

| Key | Label | Opening mode |
|---|---|---|
| `boundary-problem` | the boundary | answer |
| `information-filter` | InformationFilter | answer |
| `minimum-sufficient-input` | minimum sufficient input | answer |
| `hs-code-bypass` | HS code provided directly | answer |
| `on-premise-path` | on-premise alternative | answer |

Inline concept registry `<script type="application/json">`.
Same structure as `phi1/index.html`.
Swap for server-side CR when `concept_resolution.py` is deployed.

### `shared/concepts/phi2.yaml` [NEW]

Server-side concept registry for φ² — loaded by `concept_resolution.py`
for Tier 1 resolution.

---

## Commit 9 — Frontend Navigation

### `index.html` [MODIFY] [VERIFY]

Remove: hover-reveal Vanik name on λ Ori Meissa
Remove: hover notes on φ¹ Orionis and φ² Orionis
Remove: "Invoke Vanik" hover-revealed link

Add: direct click navigation on all three stars

```javascript
meissaStar.addEventListener("click", () => {
    window.location.href = "/vanik/";
});
phi1Star.addEventListener("click", () => {
    window.location.href = "/phi1/";
});
phi2Star.addEventListener("click", () => {
    window.location.href = "/phi2/";
});
```

Stars are entry points. No hover interaction, no labels.

---

## Commit 10 — VPS / Infrastructure

### [CONFIG] CX43 rescale

VPS rescaled from CX23 (2 vCPU, 4GB) to CX43 (8 vCPU, 16GB) this session.
No code changes. ENV vars to update for increased capacity:

```bash
VANIK_BATCH_CONCURRENCY=5    # can increase to 8 on CX43
VANIK_BATCH_MAX_ITEMS=10000  # was 20 for initial release
VANIK_BATCH_CHUNK_SIZE=500
```

### [CONFIG] Ollama setup (when MODEL_PROVIDER=ollama)

```bash
# Install Ollama on CX43
curl -fsSL https://ollama.ai/install.sh | sh

# Pull models
ollama pull phi4-mini          # extraction (2.5GB RAM)
ollama pull llama3.1:8b        # synthesis  (5.0GB RAM)
ollama pull qwen2.5:7b         # Hindi synthesis (4.5GB RAM)

# ENV vars
MODEL_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_EXTRACTION_MODEL=phi4-mini
OLLAMA_SYNTHESIS_MODEL=llama3.1:8b
```

RAM budget on CX43 (16GB):
- OS + system: ~1GB
- Vanik (uvicorn): ~500MB
- Vidhi (uvicorn): ~500MB
- phi4-mini loaded: ~2.5GB
- llama3.1:8b loaded: ~5.0GB
- Remaining headroom: ~6.5GB
Fits comfortably. Both models can be loaded simultaneously.

---

## Complete File Change Summary

```
NEW FILES (23)
  vanik/agent/prompts.py
  vanik/agent/json_parser.py
  vanik/agent/result_normaliser.py
  vanik/manifest_search/sanitiser.py
  vanik/manifest_search/boundary_extractor.py
  vanik/manifest_search/product_resolver.py
  vanik/manifest_search/symspell_corrector.py
  vanik/dictionary/__init__.py
  vanik/dictionary/ingestor.py
  vanik/dictionary/dictionary_index.py
  vanik/dictionary/entity_stripper.py
  vanik/schema/__init__.py
  vanik/schema/schema_adapter.py
  vanik/config/schemas/generic.yaml
  vanik/data/product_registry.yaml
  vanik/data/entity_registry.yaml
  vanik/data/tariff_dictionary.txt      (generated — run build_tariff_dictionary())
  vanik/batch/__init__.py
  vanik/batch/batch_processor.py
  vanik/batch/batch_parser.py
  vanik/batch/batch_reporter.py
  vanik/batch/batch_analyser.py
  vanik/batch/object_store.py
  vanik/batch/job_store.py
  phi2/index.html
  shared/concepts/phi2.yaml

REPLACED FILES (3)
  vanik/agent/providers.py
  vanik/nes/v3_llm.py
  vanik/agent/synthesiser.py

MODIFIED FILES (6) [VERIFY against current repo]
  vanik/nes/v2_ner.py               _extract_product_terms fix
  vanik/nes/orchestrator.py          boundary chain wiring
  vanik/nes/query_builder.py         resolution layer + disambiguation
  vanik/agent/vanik_agent.py         multiple wiring changes (see Commit 3+5)
  vanik/agent/session_gw.py          double-gate fix, batch endpoints, startup hook
  index.html                         star click navigation
```

---

## ENV Vars — Complete List

```bash
# ── Provider ─────────────────────────────────────────────────────────
MODEL_PROVIDER=anthropic          # anthropic | openai | mistral | ollama

# Anthropic (default)
ANTHROPIC_API_KEY=sk-ant-api-...

# OpenAI / Azure AI Foundry
OPENAI_API_KEY=...
OPENAI_API_BASE=                  # Azure Foundry: https://<resource>.services.ai.azure.com/models
OPENAI_EXTRACTION_MODEL=gpt-4o-mini
OPENAI_SYNTHESIS_MODEL=gpt-4o

# Mistral
MISTRAL_API_KEY=...
MISTRAL_EXTRACTION_MODEL=mistral-small-latest
MISTRAL_SYNTHESIS_MODEL=mistral-large-latest

# Ollama (on-premise, no boundary crossing)
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_EXTRACTION_MODEL=phi4-mini
OLLAMA_SYNTHESIS_MODEL=llama3.1:8b
# Hindi: OLLAMA_SYNTHESIS_MODEL=qwen2.5:7b

# ── Batch ─────────────────────────────────────────────────────────────
VANIK_OBJECT_STORE=local          # local | gcs | s3
VANIK_BATCH_CONCURRENCY=5
VANIK_BATCH_MAX_ITEMS=10000
VANIK_BATCH_CHUNK_SIZE=500
VANIK_BATCH_DB=/var/lib/vanik/batch_jobs.db
GCS_BUCKET_NAME=vanik-batch-jobs
S3_BUCKET_NAME=vanik-batch-jobs
# Hetzner Object Storage:
# AWS_ENDPOINT_URL=https://fsn1.your-objectstorage.com

# ── Dictionary ────────────────────────────────────────────────────────
VANIK_DICTIONARY_DB=/var/lib/vanik/dictionary.db
VANIK_ADMIN_KEY=...               # for admin endpoints

# ── Vidhi ─────────────────────────────────────────────────────────────
VIDHI_ARCH_DOC_PATH=/opt/akeru-dev/vidhi/vidhi_agent/vanik_architecture.txt
VIDHI_CONCEPTS_DIR=/opt/akeru-dev/shared/concepts
VIDHI_GEMINI_UNLOCK_CODE=...
VIDHI_RATE_LIMIT_PER_MIN=20
VIDHI_QUERY_LOG_PATH=/var/log/vanik/vidhi_query_log.jsonl
```

---

## Architecture Decisions Added This Session

| Decision | Principle |
|---|---|
| Product terms are named entities | Same resolution stack as supplier names — registry exact match → fuzzy token sort → LLM → gate. Not free text for stemming. |
| Disambiguation before search | Ambiguous terms trigger clarification gate before any search. Not after zero results — before. |
| Keep-list over strip-list | Primary boundary enforcement keeps only permitted fields. Stripping fails on unrecognised patterns. Keeping fails closed. |
| Schema-enforced boundary for batch | Customer schema YAML defines permitted fields at data entry. Confidential columns structurally absent from pipeline. |
| Two-lane batch processing | Lane A (permitted) enters pipeline. Lane B (reference) held in SQLite, joined at output. vanik_agent never receives Lane B. |
| No per-row LLM in batch | LLM called per unique unresolved product term, not per row. 50 unique terms in 10K rows = ≤ 50 calls. Template synthesis for batch output. |
| Chunked processing bounds memory | CHUNK_SIZE=500 — memory footprint constant regardless of batch size. SQLite + chunked asyncio handles 100K rows. |
| Lane B cleanup on download | Customer reference data deleted after output delivered. No retention beyond delivery. |
| SLM on-premise = Ollama only | Cloud SLMs still cross network boundary. Ollama on VPS is the genuine on-premise path. |
| Azure Foundry via OpenAI() client | AzureOpenAI() deprecated May 2026. Use OpenAI(base_url=...) for all Azure Foundry models. |
| Single SLM-constrained prompt | One prompt per task works for all models. No per-model variant switching. |
| Palantir Ontology parallel | Boundary enforcement at data model level (schema YAML) not query level (strip patterns). Schema config is the customer deliverable. |

---

## Repo alignment (akeru-dev) — snapshot (updated 2026-03-21)

| Doc reference | In repo today |
|---------------|----------------|
| `manifest_search/sanitiser.py` | **Re-export** of `nes.sanitiser.sanitise_with_log` |
| `manifest_search/entity_stripper.py` | **Thin wrapper** → `dictionary/entity_stripper.py` |
| `dictionary/*` + `data/product_registry.yaml` | **Present**; product + entity seed on gateway startup |
| `manifest_search/product_resolver.py` | **`resolved` / `ambiguous` / `unknown`** + YAML-driven disambiguation |
| `manifest_search/symspell_corrector.py` | **Present** (rapidfuzz + `tariff_dictionary.txt` + product tokens) |
| `manifest_search/boundary_extractor.py` | **Present** (`extract_permitted`) — optional; not wired into `ms_extract` (would strip corridor cues) |
| `nes/query_builder.py` | **Present** — `build_hs_search_terms`, `DisambiguationRequired` |
| `schema/schema_adapter`, `config/schemas/*.yaml` | **Present** (`generic`, `garment_co` example) |
| `batch/batch_analyser.py`, Lane B SQLite | **Present** (`batch_row_refs`, CSV columns, cleanup on download) |
| Batch chunking + dedupe | **`process_batch`** chunk size + identical query cache |
| Admin routes | **Dictionary**, **batch retry**, **schema list/upload** (`X-Admin-Key`) |
| `phi2/`, `shared/concepts/phi2.yaml` | **Present** at repo root |
| Resumable batch row state (full v3) | **Not** implemented — jobs are single-pass; retry re-queues from stored CSV |

Use this file as the **spec**; remaining enterprise items are called out in the last row.
