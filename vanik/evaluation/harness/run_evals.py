"""Evaluation harness scaffold."""

from __future__ import annotations

import json
from pathlib import Path


def run() -> dict:
    """Load ground truth records and return a stub report."""
    records_file = Path(__file__).resolve().parents[1] / "ground_truth" / "records.json"
    if not records_file.exists():
        return {"total_records": 0, "passed": 0, "failed": 0, "note": "No ground truth records yet."}

    records = json.loads(records_file.read_text())
    return {
        "total_records": len(records),
        "passed": 0,
        "failed": 0,
        "note": "Scaffold only. Implement live MCP checks here.",
    }


if __name__ == "__main__":
    print(run())
