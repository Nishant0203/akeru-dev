"""Feedback and invocation logging for Manifest Search metrics."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from nes.sufficiency import FailureReason


def _feedback_store_path() -> Path:
    raw = os.getenv("VANIK_MS_FEEDBACK_LOG")
    if raw:
        return Path(raw).expanduser().resolve()
    return Path(__file__).resolve().parent / "training_data" / "feedback.jsonl"


def _invocation_store_path() -> Path:
    raw = os.getenv("VANIK_MS_INVOCATIONS_LOG")
    if raw:
        return Path(raw).expanduser().resolve()
    return Path(__file__).resolve().parent / "training_data" / "invocations.jsonl"


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _load_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _append(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload) + "\n")


def log_ms_invocation(raw_query: str, used_v3: bool) -> None:
    """Append one manifest-search invocation record."""
    _append(
        _invocation_store_path(),
        {
            "raw_query": raw_query,
            "used_v3": used_v3,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )


def log_feedback(
    raw_query: str,
    v2_output: dict,
    v3_output: dict,
    failure_reason: FailureReason = "unknown",
) -> None:
    """Append one fallback event for human review and future retraining."""
    _append(
        _feedback_store_path(),
        {
            "raw_query": raw_query,
            "v2_output": v2_output,
            "v3_output": v3_output,
            "failure_reason": failure_reason,
            "timestamp": datetime.now(UTC).isoformat(),
            "reviewed": False,
        },
    )


def _count_last_24h(path: Path, *, field: str | None = None, value: Any = None) -> int:
    cutoff = datetime.now(UTC) - timedelta(hours=24)
    count = 0
    for rec in _load_records(path):
        ts = _parse_ts(rec.get("timestamp"))
        if not ts or ts < cutoff:
            continue
        if field is not None and rec.get(field) != value:
            continue
        count += 1
    return count


def total_ms_calls_24h() -> int:
    """Count manifest-search invocations in the last 24h."""
    return _count_last_24h(_invocation_store_path())


def v3_invocations_24h() -> int:
    """Count fallback invocations in last 24 hours."""
    invocation_based = _count_last_24h(_invocation_store_path(), field="used_v3", value=True)
    feedback_based = _count_last_24h(_feedback_store_path())
    return max(invocation_based, feedback_based)


def fallback_rate_24h(total_calls_24h: int | None = None) -> float:
    """Fallback ratio for last 24h. Returns a value in [0.0, 1.0]. Callers that display as percentage must multiply by 100."""
    denominator = total_calls_24h if total_calls_24h is not None else total_ms_calls_24h()
    if denominator <= 0:
        return 0.0
    return v3_invocations_24h() / denominator
