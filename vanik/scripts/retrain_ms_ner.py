"""Retrain Manifest Search NER from reviewed examples (stub)."""

from __future__ import annotations

from pathlib import Path


def main() -> None:
    reviewed = Path(__file__).resolve().parents[1] / "nes" / "training_data" / "reviewed.json"
    print(f"retrain_ms_ner stub: would train using {reviewed}")


if __name__ == "__main__":
    main()
