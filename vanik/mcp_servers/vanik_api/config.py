"""Configuration helpers for vanik_api."""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_WTO_API_KEY_PRIMARY = "00f6f3818f8a459e9353ff5b6404dfaa"
DEFAULT_WTO_API_KEY_SECONDARY = "bd1c83d01aad435c802ce7bfbec71dd5"


@dataclass(slots=True)
class Settings:
    mcp_transport: str
    model_provider: str
    embedding_provider: str
    embedding_model: str

    wto_base_url: str
    wto_api_key_primary: str | None
    wto_api_key_secondary: str | None
    wto_timeout_seconds: float
    wto_indicator: str
    wto_reporter_code: str
    wto_partner_code: str
    wto_default_year: int

    uk_base_url: str
    eu_base_url: str
    hmrc_accept_header: str
    hmrc_timeout_seconds: float

    rate_cache_ttl_seconds: int
    circuit_failure_threshold: int
    circuit_failure_window_seconds: int
    circuit_probe_timeout_seconds: int


def load_settings() -> Settings:
    """Load settings from environment variables with sensible defaults."""
    return Settings(
        mcp_transport=os.getenv("MCP_TRANSPORT", "stdio"),
        model_provider=os.getenv("MODEL_PROVIDER", "anthropic"),
        embedding_provider=os.getenv("EMBEDDING_PROVIDER", "openai"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
        wto_base_url=os.getenv("WTO_BASE_URL", "https://api.wto.org/timeseries/v1"),
        wto_api_key_primary=os.getenv("WTO_API_KEY", DEFAULT_WTO_API_KEY_PRIMARY),
        wto_api_key_secondary=os.getenv("WTO_SECONDARY_API_KEY", DEFAULT_WTO_API_KEY_SECONDARY),
        wto_timeout_seconds=float(os.getenv("WTO_TIMEOUT_SECONDS", "20")),
        wto_indicator=os.getenv("WTO_MFN_INDICATOR", "HS_A_0010"),
        wto_reporter_code=os.getenv("WTO_REPORTER_CODE", "356"),
        wto_partner_code=os.getenv("WTO_PARTNER_CODE", "000"),
        wto_default_year=int(os.getenv("WTO_DEFAULT_YEAR", "2023")),
        uk_base_url=os.getenv("UK_TARIFF_BASE_URL", "https://www.trade-tariff.service.gov.uk/uk/api/v2"),
        eu_base_url=os.getenv("EU_TARIFF_BASE_URL", "https://www.trade-tariff.service.gov.uk/xi/api/v2"),
        hmrc_accept_header=os.getenv("HMRC_ACCEPT_HEADER", "application/vnd.hmrc.2.0+json"),
        hmrc_timeout_seconds=float(os.getenv("HMRC_TIMEOUT_SECONDS", "20")),
        rate_cache_ttl_seconds=int(os.getenv("RATE_CACHE_TTL_SECONDS", "86400")),
        circuit_failure_threshold=int(os.getenv("CIRCUIT_FAILURE_THRESHOLD", "3")),
        circuit_failure_window_seconds=int(os.getenv("CIRCUIT_FAILURE_WINDOW_SECONDS", "60")),
        circuit_probe_timeout_seconds=int(os.getenv("CIRCUIT_PROBE_TIMEOUT_SECONDS", "30")),
    )


settings = load_settings()
