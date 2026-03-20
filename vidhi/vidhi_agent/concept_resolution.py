"""
vidhi/vidhi_agent/concept_resolution.py
────────────────────────────────────────────────────────────────
Concept Resolution (CR) — ResolutionPipeline for Vidhi anchor mode.

Resolves a (concept_key, post_id) pair to a ConceptContext.
The client sends only the key — never seed text. This file owns
the seed, not the frontend. (Architecture v2.0, Section 5.3)

Two-tier resolution:
  Tier 1 — YAML curated lookup (zero latency, zero cost)
  Tier 2 — Arch doc section keyword retrieval (fallback)

The resolution_tier is logged on every request so we can measure
the Tier 2 growth rate — a rising rate means the YAML needs new entries.

Usage (in agent.py):
    from vidhi.vidhi_agent.concept_resolution import resolve_concept, load_registry

    # At startup — call once per post:
    load_registry("phi1")
    load_registry("phi2")

    # Per request:
    result = resolve_concept("query-poisoning", "phi1")
    if not result.resolved:
        raise ConceptNotFoundError(result.failure_reason)
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

log = logging.getLogger("vidhi.cr")

# ── Registry storage (L3 → L2 on startup) ────────────────────────────
_REGISTRIES:      dict[str, dict] = {}   # post_id → parsed concept dict
_REGISTRY_HASHES: dict[str, str]  = {}  # post_id → md5[:8] of raw YAML
_ARCH_DOC_CACHE:  str = ""              # loaded once, reused for Tier 2

# ── Failure taxonomy ──────────────────────────────────────────────────
FailureReason = Literal[
    "key_not_found",
    "empty_context",
    "context_too_short",
    "post_registry_missing",
    "registry_load_error",
]


# ── Output contracts ──────────────────────────────────────────────────

@dataclass
class ConceptContext:
    concept_key:     str
    post_id:         str
    label:           str
    section:         str           # maps to SECTION_ADDENDUM key in agent.py
    context:         str           # seed text for the ANCHOR_PREAMBLE
    opening_mode:    str           # "answer" | "options"
    options:         list[str] = field(default_factory=list)
    resolution_tier: int = 1       # 1 = curated YAML, 2 = arch doc retrieval


@dataclass
class ResolutionResult:
    resolved:       bool
    tier:           int
    concept:        ConceptContext | None
    failure_reason: FailureReason | None
    registry_hash:  str = ""      # md5[:8] — goes into every query log entry


# ── Startup loader ────────────────────────────────────────────────────

def _registry_path(post_id: str) -> Path:
    """
    Locate shared/concepts/{post_id}.yaml.
    Production: VIDHI_CONCEPTS_DIR env var → /opt/akeru-dev/shared/concepts
    Dev:        relative to this file    → ../../../shared/concepts
    """
    base = os.environ.get(
        "VIDHI_CONCEPTS_DIR",
        str(Path(__file__).parent.parent.parent / "shared" / "concepts"),
    )
    return Path(base) / f"{post_id}.yaml"


def load_registry(post_id: str) -> bool:
    """
    Parse and cache the YAML registry for post_id.
    Returns True on success. Call once per post at agent startup.
    """
    path = _registry_path(post_id)
    if not path.exists():
        log.warning(f"[CR] Registry missing: post_id='{post_id}' path={path}")
        return False
    try:
        raw = path.read_text(encoding="utf-8")
        _REGISTRIES[post_id]      = _parse_yaml(raw)
        _REGISTRY_HASHES[post_id] = hashlib.md5(raw.encode()).hexdigest()[:8]
        log.info(
            f"[CR] Loaded '{post_id}': "
            f"{len(_REGISTRIES[post_id])} concepts, "
            f"hash={_REGISTRY_HASHES[post_id]}"
        )
        return True
    except Exception as exc:
        log.error(f"[CR] Load error for '{post_id}': {exc}")
        return False


def registry_hash(post_id: str) -> str:
    """Return the hash of the loaded registry — for query log entries."""
    return _REGISTRY_HASHES.get(post_id, "unloaded")


def registry_status() -> dict[str, dict]:
    """For /vidhi/health: loaded flag + content hash per curated post."""
    return {
        pid: {"loaded": pid in _REGISTRIES, "hash": registry_hash(pid)}
        for pid in ("phi1", "phi2")
    }


# ── Main resolution entry point ───────────────────────────────────────

def resolve_concept(concept_key: str, post_id: str) -> ResolutionResult:
    """
    Resolve (concept_key, post_id) → ResolutionResult.

    Tier 1: YAML curated lookup — deterministic, zero cost.
    Tier 2: Arch doc keyword retrieval — fallback, logs for YAML expansion.
    """
    r_hash = _REGISTRY_HASHES.get(post_id, "")

    # Lazy load if registry not yet in memory
    if post_id not in _REGISTRIES:
        if not load_registry(post_id):
            return ResolutionResult(
                resolved=False, tier=1, concept=None,
                failure_reason="post_registry_missing",
                registry_hash=r_hash,
            )

    # ── Tier 1 ───────────────────────────────────────────────────
    entry = _REGISTRIES.get(post_id, {}).get(concept_key)
    if entry:
        ctx = ConceptContext(
            concept_key=concept_key,
            post_id=post_id,
            label=entry.get("label", concept_key),
            section=entry.get("section", "general"),
            context=entry.get("context", "").strip(),
            opening_mode=entry.get("opening_mode", "answer"),
            options=entry.get("options", []),
            resolution_tier=1,
        )
        ok, reason = _is_sufficient(ctx)
        if ok:
            return ResolutionResult(
                resolved=True, tier=1, concept=ctx,
                failure_reason=None, registry_hash=_REGISTRY_HASHES.get(post_id, ""),
            )
        log.warning(f"[CR] Tier 1 entry '{concept_key}' failed sufficiency: {reason}")

    # ── Tier 2 ───────────────────────────────────────────────────
    log.info(f"[CR] Tier 2 fallback: concept='{concept_key}' post='{post_id}'")
    ctx2 = _arch_doc_retrieval(concept_key, post_id)
    if ctx2:
        ok2, _ = _is_sufficient(ctx2)
        if ok2:
            return ResolutionResult(
                resolved=True, tier=2, concept=ctx2,
                failure_reason=None, registry_hash=r_hash,
            )

    return ResolutionResult(
        resolved=False, tier=2, concept=None,
        failure_reason="key_not_found", registry_hash=r_hash,
    )


# ── Sufficiency check (Pattern 5) ─────────────────────────────────────

def _is_sufficient(ctx: ConceptContext) -> tuple[bool, FailureReason | None]:
    if not ctx.context.strip():
        return False, "empty_context"
    if len(ctx.context.strip()) < 50:
        return False, "context_too_short"
    return True, None


# ── Tier 2 — arch doc keyword retrieval ──────────────────────────────

def _get_arch_doc() -> str:
    global _ARCH_DOC_CACHE
    if not _ARCH_DOC_CACHE:
        doc_path = Path(
            os.environ.get(
                "VIDHI_ARCH_DOC_PATH",
                str(Path(__file__).parent / "vanik_architecture.txt"),
            )
        )
        _ARCH_DOC_CACHE = doc_path.read_text(encoding="utf-8") if doc_path.exists() else ""
    return _ARCH_DOC_CACHE


def _arch_doc_retrieval(concept_key: str, post_id: str) -> ConceptContext | None:
    """
    Score arch doc sections by keyword match on concept_key slug tokens.
    Returns top-2 sections (up to 3000 chars) as a ConceptContext.
    """
    arch_doc = _get_arch_doc()
    if not arch_doc:
        return None

    keywords = [w for w in re.split(r"[-_\s]+", concept_key.lower()) if len(w) >= 3]
    if not keywords:
        return None

    sections = re.split(r"\n(?=#{1,3} )", arch_doc)
    scored: list[tuple[int, str]] = []
    for sec in sections:
        score = sum(sec.lower().count(kw) for kw in keywords)
        if score > 0:
            scored.append((score, sec))

    if not scored:
        return None

    scored.sort(key=lambda t: t[0], reverse=True)
    budget, chosen = 3000, []
    for _, sec in scored[:2]:
        if budget <= 0:
            break
        snippet = sec[:budget].strip()
        chosen.append(snippet)
        budget -= len(snippet)

    if not chosen:
        return None

    label = concept_key.replace("-", " ")
    context = (
        f"The reader highlighted '{label}'. "
        f"Relevant sections from the Vanik architecture document:\n\n"
        + "\n\n".join(chosen)
    )

    # Derive section key from top result heading
    heading = re.search(r"^#{1,3}\s+(.+)$", scored[0][1], re.MULTILINE)
    h = heading.group(1).lower() if heading else ""
    section_key = (
        "manifest-search" if "manifest" in h
        else "mcp"          if "mcp" in h
        else "model-selection" if "model" in h
        else "general"
    )

    return ConceptContext(
        concept_key=concept_key,
        post_id=post_id,
        label=label,
        section=section_key,
        context=context,
        opening_mode="answer",
        resolution_tier=2,
    )


# ── Minimal YAML parser ───────────────────────────────────────────────

def _parse_yaml(raw: str) -> dict:
    """
    Parse shared/concepts/{post_id}.yaml using PyYAML (soft dependency).
    Falls back to an empty dict if PyYAML unavailable — agent startup
    logs the error and Tier 2 handles all resolution.
    """
    try:
        import yaml
        data = yaml.safe_load(raw)
        concepts_raw = data.get("concepts", {}) if isinstance(data, dict) else {}
        result: dict = {}
        for key, entry in concepts_raw.items():
            if not isinstance(entry, dict):
                continue
            context = str(entry.get("context", "")).strip()
            options = entry.get("options", [])
            result[str(key)] = {
                "label":        str(entry.get("label", key)),
                "section":      str(entry.get("section", "general")),
                "opening_mode": str(entry.get("opening_mode", "answer")),
                "context":      context,
                "options":      [str(o) for o in (options if isinstance(options, list) else [])],
            }
        return result
    except ImportError:
        log.error("[CR] PyYAML not installed — concept registry unavailable. Run: pip install pyyaml")
        return {}
    except Exception as exc:
        log.error(f"[CR] YAML parse error: {exc}")
        return {}


# ── Exception ─────────────────────────────────────────────────────────

class ConceptNotFoundError(Exception):
    def __init__(self, reason: FailureReason | None, concept_key: str = "", post_id: str = ""):
        self.reason       = reason
        self.concept_key  = concept_key
        self.post_id      = post_id
        super().__init__(
            f"Concept '{concept_key}' not resolved in '{post_id}'. Reason: {reason}"
        )
