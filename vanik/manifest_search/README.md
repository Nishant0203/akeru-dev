# Manifest Search boundary helpers

## Entity stripper vs sanitiser

| Layer | Role |
|--------|------|
| **`nes.sanitiser`** | Structured patterns: PO#, `supplier:`, USD/unit, P/N, emails, phones. |
| **`manifest_search.entity_stripper`** | Unstructured proper nouns from `data/entity_registry.yaml` plus internal grades (e.g. S355) and legal suffixes. |

Both run in **`nes.orchestrator.ms_extract`** before **`extract_v2`** / **`llm_extract`**. The LLM (v3) only sees the **entity-stripped** string; **`_raw`** on entities is that cleaned form, not the original user text.

## Audit log

Set **`VANIK_SANITISATION_AUDIT_LOG`** to a `.jsonl` path to append one JSON object per extraction with `raw_query`, `sanitised`, `cleaned`, and combined `events` (each tagged with `layer`: `sanitiser` or `entity_stripper`).

## Registry

Edit **`vanik/data/entity_registry.yaml`** — `entities.<id>.canonical` and optional `variants[]`.
