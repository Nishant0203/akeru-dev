"""Schema adapter CSV → Lane A + Lane B."""

from __future__ import annotations

from schema.schema_adapter import adapt_upload_csv, load_schema_adapter


def test_load_generic_schema() -> None:
    a = load_schema_adapter("generic")
    assert a is not None
    assert a.customer_id == "generic"


def test_adapt_upload_garment_co() -> None:
    csv = (
        "product,origin_country,destination,tariff_code,po_number,supplier\n"
        "cotton shirts,IN,GB,,PO-1,Acme\n"
    )
    rows = adapt_upload_csv(csv, "garment_co")
    assert len(rows) == 1
    assert "India" in rows[0]["query"]
    assert rows[0]["reference"].get("po_number") == "PO-1"
    assert rows[0]["reference"].get("supplier") == "Acme"
