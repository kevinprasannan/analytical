"""OHLCV + open-interest read models (docs/07 §4.3)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from analytical_core.enums import AnalysisStatus, Timeframe


class Bar(BaseModel):
    ts: datetime  # bar-open, UTC
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    is_final: bool


class BarsResponse(BaseModel):
    instrument_id: int
    timeframe: Timeframe
    items: list[Bar]
    total: int
    limit: int
    offset: int
    next_cursor: str | None = None


class OiPoint(BaseModel):
    ts: datetime
    oi: int
    provider_oi_change: int | None = None
    is_final: bool


class OpenInterestResponse(BaseModel):
    instrument_id: int
    timeframe: Timeframe | None = None
    status: AnalysisStatus = AnalysisStatus.OK
    reason: str | None = None
    items: list[OiPoint] = []
    total: int = 0
    limit: int = 0
    offset: int = 0
