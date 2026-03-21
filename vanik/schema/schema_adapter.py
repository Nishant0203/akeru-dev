"""YAML-driven field mapping: Lane A (pipeline) vs Lane B (reference only)."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_VANIK_ROOT = Path(__file__).resolve().parent.parent

_ISO_TO_EN: dict[str, str] = {
    "IN": "India",
    "GB": "UK",
    "UK": "UK",
    "EU": "the EU",
    "DE": "Germany",
    "FR": "France",
    "US": "USA",
    "CN": "China",
}


def _expand_place(code: str) -> str:
    u = (code or "").strip().upper()
    return _ISO_TO_EN.get(u, (code or "").strip())


@dataclass
class AdaptedRow:
    """Lane A fields enter the agent; Lane B is opaque reference data."""

    row_index: int
    query: str
    hs_code: str | None = None
    quantity: float | None = None
    unit_value_usd: float | None = None
    reference: dict[str, Any] = field(default_factory=dict)


def _iso2_normalise(val: str) -> str:
    u = (val or "").strip().upper()
    if u in {"UK", "UNITED KINGDOM", "GREAT BRITAIN"}:
        return "GB"
    if u in {"USA", "US", "UNITED STATES"}:
        return "US"
    return u[:2] if len(u) == 2 else val.strip()


_TRANSFORMS = {"iso2_normalise": _iso2_normalise}


class SchemaAdapter:
    def __init__(self, config: dict[str, Any]) -> None:
        self.customer_id = str(config.get("customer_id") or "generic")
        self.field_mapping: dict[str, Any] = dict(config.get("field_mapping") or {})
        self.reference_fields: set[str] = {
            str(x).strip().lower() for x in (config.get("reference_fields") or []) if str(x).strip()
        }

    @classmethod
    def from_path(cls, path: str | Path) -> SchemaAdapter:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls(data)

    def _apply_transform(self, val: str, name: str | None) -> str:
        if not name:
            return val
        fn = _TRANSFORMS.get(str(name))
        return fn(val) if fn else val

    def _mapped_sources(self) -> set[str]:
        out: set[str] = set()
        for spec in self.field_mapping.values():
            if isinstance(spec, dict):
                out.add(str(spec.get("source_column") or "").strip().lower())
            elif isinstance(spec, str):
                out.add(spec.strip().lower())
        return {x for x in out if x}

    def _cell(self, row: dict[str, str], spec: Any) -> str:
        if spec is None:
            return ""
        if isinstance(spec, dict):
            src = str(spec.get("source_column") or "")
            transform = spec.get("transform")
            raw = (row.get(src) or "").strip()
            return self._apply_transform(raw, str(transform) if transform else None)
        if isinstance(spec, str):
            return (row.get(spec) or "").strip()
        return ""

    def adapt_csv_row(self, row: dict[str, str], row_index: int) -> AdaptedRow | None:
        fm = self.field_mapping
        product = self._cell(row, fm.get("product_category") or fm.get("product"))
        origin = self._cell(row, fm.get("origin"))
        dest = self._cell(row, fm.get("destination"))
        if not product:
            return None
        if not origin or not dest:
            return None

        hs_spec = fm.get("hs_code")
        hs_raw = self._cell(row, hs_spec) if hs_spec else ""

        query = f"{product} from {_expand_place(origin)} to {_expand_place(dest)}"

        mapped = self._mapped_sources()
        ref: dict[str, Any] = {}
        for h, v in row.items():
            hl = (h or "").strip().lower()
            if not hl or not str(v).strip():
                continue
            if hl in mapped:
                continue
            if self.reference_fields:
                if hl in self.reference_fields:
                    ref[h] = str(v).strip()
            else:
                ref[h] = str(v).strip()

        return AdaptedRow(
            row_index=row_index,
            query=query,
            hs_code=hs_raw or None,
            reference=ref,
        )


def load_schema_adapter(schema_id: str | None) -> SchemaAdapter | None:
    sid = (schema_id or "generic").strip() or "generic"
    path = _VANIK_ROOT / "config" / "schemas" / f"{sid}.yaml"
    if not path.is_file():
        return None
    return SchemaAdapter.from_path(path)


def adapt_upload_csv(data: str, schema_id: str | None = None) -> list[dict[str, Any]]:
    """
    Parse CSV using SchemaAdapter when schema exists; else default PO parser.
    """
    adapter = load_schema_adapter(schema_id)
    if adapter is None:
        from batch.batch_parser import parse_upload_csv

        return parse_upload_csv(data)

    reader = csv.DictReader(io.StringIO(data))
    if not reader.fieldnames:
        raise ValueError("CSV must include a header row")
    out: list[dict[str, Any]] = []
    for i, row in enumerate(reader):
        adapted = adapter.adapt_csv_row({k: (v or "") for k, v in row.items()}, i)
        if adapted is None:
            continue
        item: dict[str, Any] = {"query": adapted.query, "hs_code": adapted.hs_code}
        if adapted.reference:
            item["reference"] = adapted.reference
        out.append(item)
    return out
