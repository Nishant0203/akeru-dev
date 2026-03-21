"""Batch ingestion: bounded concurrency, optional HS auto-gate, CSV/JSON I/O."""

from batch.batch_processor import process_batch
from batch.batch_reporter import results_to_csv

__all__ = ["process_batch", "results_to_csv"]
