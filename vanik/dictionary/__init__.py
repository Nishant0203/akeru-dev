"""Generic dictionary ingestion and query index (independent of tariff FTS)."""

from dictionary.dictionary_index import DictionaryIndex, LookupResult
from dictionary.ingestor import DictionaryEntry, DictionaryIngestor, DictionaryType

__all__ = [
    "DictionaryEntry",
    "DictionaryIngestor",
    "DictionaryIndex",
    "DictionaryType",
    "LookupResult",
]
