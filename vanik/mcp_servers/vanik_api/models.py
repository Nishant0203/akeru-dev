"""Shared response models for vanik_api."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class WTOResult:
    hs_code_6: str
    mfn_rate_pct: float
    year: int
    indicator: str = "HS_A_0010"
    reporter: str = "356"
    partner: str | None = None
    source: str = "WTO Timeseries API"


@dataclass(slots=True)
class TariffResult:
    commodity_code_10: str
    mfn_rate_pct: float
    measure_type: str
    source: str
