"""Gemini File API upload/delete stubs."""

from __future__ import annotations


def upload_tariff_document(file_path: str) -> str:
    """Return a fake file URI for local scaffold."""
    return f"gemini://uploaded/{file_path.split('/')[-1]}"


def delete_uploaded_file(file_uri: str) -> None:
    """No-op delete for stub."""
    _ = file_uri
