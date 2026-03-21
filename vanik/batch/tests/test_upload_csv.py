"""Tests for PO-style batch CSV parsing."""

from batch.batch_parser import parse_upload_csv


def test_parse_upload_csv_builds_query() -> None:
    csv = (
        "product,origin,destination,hs_code\n"
        "cotton shirts,IN,GB,\n"
        "brake callipers,IN,GB,8708301090\n"
    )
    rows = parse_upload_csv(csv)
    assert len(rows) == 2
    assert rows[0]["query"] == "cotton shirts from India to UK"
    assert rows[0]["hs_code"] is None
    assert rows[1]["hs_code"] == "8708301090"
