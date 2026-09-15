"""Daily digest response (docs/07 §4.12). One row per trading day: D1 OHLC,
previous-day-high / previous-day-low break flags, and the day's TPO profile
(where a `market_profile_sessions` row exists). Table only — no charts.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DigestRow(BaseModel):
    d: str  # ISO date
    weekday: str
    open: float
    high: float
    low: float
    close: float
    prev_close: float
    change_pct: float
    range_pct: float
    gap_pct: float

    pdh: float
    pdl: float
    pdh_broken: bool
    pdl_broken: bool
    pdh_close_above: bool
    pdl_close_below: bool
    inside_day: bool
    outside_day: bool
    range_type: str  # INSIDE | PDH_BREAK | PDL_BREAK | OUTSIDE

    # D1 day-type — classified from the candle for every day (MPDayType vocab:
    # TREND_UP/DOWN, NEUTRAL, NEUTRAL_EXTREME, NORMAL, NORMAL_VARIATION, RANGE,
    # LARGE_RANGE, UNDETERMINED)
    d1_day_type: str
    close_range_pos: float | None = None  # 0 = closed on the low, 1 = on the high
    d1_range_ratio: float | None = None  # today's range / trailing-14 mean range

    # TPO profile — null where no market_profile_sessions row for the day
    profile_shape: str | None = None
    day_type: str | None = None
    poc: float | None = None
    vah: float | None = None
    val: float | None = None
    ib_high: float | None = None
    ib_low: float | None = None
    close_vs_value: str | None = None  # ABOVE | INSIDE | BELOW
    close_vs_poc: str | None = None  # ABOVE | AT | BELOW
    profile_complete: bool | None = None


class DigestSummary(BaseModel):
    days: int
    pdh_breaks: int
    pdl_breaks: int
    inside_days: int
    outside_days: int
    pdh_close_above: int
    pdl_close_below: int
    mean_range_pct: float
    mean_gap_pct: float
    mean_change_pct: float
    days_with_profile: int
    d1_day_type_counts: dict[str, int] = Field(default_factory=dict)


class DailyDigestResponse(BaseModel):
    instrument_id: int
    contract_key: str
    symbol: str
    first: str | None = None
    last: str | None = None
    total: int
    limit: int
    offset: int
    sort: str
    gap_min_pct: float | None = None  # echoed filter — gap_pct >= this
    gap_max_pct: float | None = None  # gap_pct <= this
    chg_min_pct: float | None = None  # change_pct >= this
    chg_max_pct: float | None = None  # change_pct <= this
    summary: DigestSummary
    items: list[DigestRow] = Field(default_factory=list)
