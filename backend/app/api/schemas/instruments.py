"""Instrument + coverage models (docs/07 §4.2)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from analytical_core.enums import (
    ExpiryKind,
    InstrumentSegment,
    InstrumentType,
    OptionType,
    Timeframe,
    WatermarkStatus,
)


class ProviderMapSummary(BaseModel):
    provider: str
    provider_symbol: str
    is_active: bool


class InstrumentSummary(BaseModel):
    id: int
    contract_key: str
    symbol: str
    display_name: str | None = None
    exchange: str
    segment: InstrumentSegment
    instrument_type: InstrumentType
    underlying_id: int | None = None
    expiry_date: date | None = None
    expiry_kind: ExpiryKind | None = None
    strike_price: Decimal | None = None
    option_type: OptionType | None = None
    lot_size: int | None = None
    tick_size: Decimal | None = None
    is_active: bool
    is_tracked: bool
    has_volume: bool
    has_intraday_oi: bool


class InstrumentDetail(InstrumentSummary):
    profile_bin_size: Decimal | None = None
    provider_map: list[ProviderMapSummary] = []
    applicable_analyses: list[str] = []


class InstrumentPatch(BaseModel):
    is_tracked: bool | None = None
    profile_bin_size: Decimal | None = None


class InstrumentCreate(BaseModel):
    instrument_type: InstrumentType
    segment: InstrumentSegment
    provider_symbol: str  # the active provider's key, e.g. "NSE_INDEX|Nifty 50"
    symbol: str | None = None
    display_name: str | None = None
    exchange: str = "NSE"
    underlying_contract_key: str | None = None  # required for FUTURE / OPTION
    underlying_symbol: str | None = None
    expiry_date: date | None = None
    expiry_kind: ExpiryKind | None = None
    strike_price: Decimal | None = None
    option_type: OptionType | None = None
    is_tracked: bool = True


class InstrumentCreated(BaseModel):
    instrument_id: int
    contract_key: str
    provider: str


class InstrumentDeleted(BaseModel):
    instrument_id: int
    contract_key: str
    children: dict[str, int] = {}


class CatalogItem(BaseModel):
    provider_symbol: str
    name: str
    trading_symbol: str
    instrument_type: str
    segment: str
    exchange: str
    underlying_symbol: str | None = None
    expiry_date: str | None = None
    expiry_kind: str | None = None
    strike_price: float | None = None
    option_type: str | None = None
    in_db: bool = False


class InstrumentCatalog(BaseModel):
    query: str
    count: int
    available: bool  # false when no master files are present
    items: list[CatalogItem] = []


class TimeframeCoverage(BaseModel):
    timeframe: Timeframe
    earliest_bar_ts: datetime | None = None
    latest_bar_ts: datetime | None = None
    latest_is_final: bool | None = None
    bar_count: int
    watermark_status: WatermarkStatus | None = None
    watermark_last_complete_ts: datetime | None = None
    watermark_last_verified_ts: datetime | None = None


class InstrumentCoverage(BaseModel):
    instrument_id: int
    timeframes: list[TimeframeCoverage]
    last_oi_ts: datetime | None = None
    last_oi: int | None = None
