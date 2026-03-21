"""Pluggable object storage for batch uploads (local / GCS / S3)."""

from __future__ import annotations

import os
from pathlib import Path

_STORE_TYPE = os.getenv("VANIK_OBJECT_STORE", "local").strip().lower()

# Dev default: vanik/data/batch; production: set VANIK_BATCH_LOCAL_DIR=/var/lib/vanik/batch
_LOCAL_ROOT = Path(
    os.getenv("VANIK_BATCH_LOCAL_DIR", str(Path(__file__).resolve().parent.parent / "data" / "batch"))
)


def upload(content: bytes, filename: str, job_id: str) -> str:
    """Store file bytes. Returns a retrieval key/path."""
    if _STORE_TYPE == "local":
        path = _LOCAL_ROOT / job_id / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return str(path.resolve())

    if _STORE_TYPE == "gcs":
        from google.cloud import storage  # noqa: PLC0415

        bucket_name = os.environ["GCS_BUCKET_NAME"]
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob_name = f"batch/{job_id}/{filename}"
        bucket.blob(blob_name).upload_from_string(content, content_type="text/csv")
        return f"gs://{bucket_name}/{blob_name}"

    if _STORE_TYPE == "s3":
        import boto3  # noqa: PLC0415

        key = f"batch/{job_id}/{filename}"
        s3 = boto3.client("s3")
        s3.put_object(Bucket=os.environ["S3_BUCKET_NAME"], Key=key, Body=content)
        return key

    raise ValueError(f"Unknown VANIK_OBJECT_STORE: {_STORE_TYPE!r} (use local, gcs, s3)")


def download(key: str) -> bytes:
    if _STORE_TYPE == "local":
        return Path(key).read_bytes()

    if _STORE_TYPE == "gcs":
        from google.cloud import storage  # noqa: PLC0415

        bucket_name = os.environ["GCS_BUCKET_NAME"]
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob_name = key
        if key.startswith("gs://"):
            without = key.removeprefix("gs://")
            blob_name = without.split("/", 1)[1] if "/" in without else ""
        elif key.startswith(f"{bucket_name}/"):
            blob_name = key.split("/", 1)[1]
        return bucket.blob(blob_name).download_as_bytes()

    if _STORE_TYPE == "s3":
        import boto3  # noqa: PLC0415

        s3 = boto3.client("s3")
        return s3.get_object(Bucket=os.environ["S3_BUCKET_NAME"], Key=key)["Body"].read()

    raise ValueError(f"Unknown VANIK_OBJECT_STORE: {_STORE_TYPE!r}")
