"""Global pytest fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _set_ms_metric_log_paths(tmp_path, monkeypatch):
    """Keep manifest-search metric writes inside per-test temp paths."""
    monkeypatch.setenv("VANIK_MS_FEEDBACK_LOG", str(tmp_path / "ms_feedback.jsonl"))
    monkeypatch.setenv("VANIK_MS_INVOCATIONS_LOG", str(tmp_path / "ms_invocations.jsonl"))
