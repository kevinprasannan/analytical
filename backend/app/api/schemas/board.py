"""Market board response (docs/07 §4.11, docs/08 §4.1) — a compact data-first
row per tracked INDEX / FUTURE."""

from __future__ import annotations

from pydantic import BaseModel


class BoardRow(BaseModel):
    instrument_id: int
    contract_key: str
    symbol: str
    instrument_type: str
    expiry_date: str | None = None
    d1_from: str | None = None
    d1_through: str | None = None
    d1_bars: int | None = None
    m1_from: str | None = None
    m1_through: str | None = None
    history_ok: bool | None = None
    last_price: float | None = None
    last_ts: str | None = None
    staleness_seconds: float | None = None
    prev_close: float | None = None
    day_open: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    day_change_pct: float | None = None
    day_range_pct: float | None = None
    oi: int | None = None
    oi_ts: str | None = None
    label_d1: str | None = None
    score_d1: float | None = None
    label_h1: str | None = None
    label_m5: str | None = None


class MarketBoard(BaseModel):
    rows: list[BoardRow] = []
