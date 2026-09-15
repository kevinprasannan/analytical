"""CPR + classic pivots — daily / weekly / monthly (docs/07 §4.18, docs/05 §10.13).

Forward-looking support / resistance from the last completed period's H/L/C:
the CPR band (TC / pivot / BC) and classic floor R1-R3 / S1-S3, per period,
with ~3 months of history and the developing (in-progress) period. Computed on
read, not persisted, not scored — descriptive, no BUY/SELL.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PivotFromPeriod(BaseModel):
    start: str  # ISO date (IST)
    end: str
    sessions: int
    high: float
    low: float
    close: float


class PivotRealized(BaseModel):
    """What price actually did on a calendar-date (daily_on) session."""

    open: float
    high: float
    low: float
    close: float
    prev_close: float
    ret_pct: float | None = None
    range_pct: float | None = None
    close_vs_pivot: str  # ABOVE | AT | BELOW
    touched_r1: bool
    touched_s1: bool


class PivotPeriod(BaseModel):
    from_period: PivotFromPeriod
    pivot: float
    tc: float  # 2·P − BC (by formula)
    bc: float  # (high + low) / 2
    cpr_top: float  # max(tc, bc) — the band's upper line
    cpr_bottom: float  # min(tc, bc)
    cpr_width: float
    cpr_width_pct: float
    width_band: str  # NARROW | AVERAGE | WIDE
    r1: float
    r2: float
    r3: float
    s1: float
    s2: float
    s3: float
    # HIGHER_VALUE | LOWER_VALUE | OVERLAPPING | INSIDE_VALUE | OUTSIDE_VALUE | UNCHANGED
    vs_prev: str | None = None
    # set only on the `next` period:
    for_label: str | None = None  # "next session (2026-09-09)" / "next week" / "next month"
    for_date: str | None = None  # ISO date the daily `next` / calendar-date pivots apply to
    provisional: bool | None = None  # true while the source period is still open
    # set only on calendar-date (daily_on) history rows:
    year: int | None = None
    realized: PivotRealized | None = None


class PivotLevelRow(BaseModel):
    timeframe: str  # DAILY | WEEKLY | MONTHLY
    name: str  # R3 | R2 | R1 | TC | P | BC | S1 | S2 | S3
    price: float
    distance: float  # signed points, level − last_price
    distance_pct: float | None = None
    tier: str  # AT | NEAR | FAR
    side: str  # ABOVE | BELOW | AT


class PivotTimeframe(BaseModel):
    current: PivotPeriod | None = None  # levels in force now (from the last completed period)
    next: PivotPeriod | None = None  # levels for the upcoming period ("tomorrow" for DAILY)
    history: list[PivotPeriod] = Field(default_factory=list)  # completed periods, newest first


class PivotsResponse(BaseModel):
    instrument_id: int
    contract_key: str
    instrument_type: str
    generated_at: str
    last_price: float | None = None
    last_price_ts: str | None = None
    bands: dict[str, float]  # at / near, in points
    d1_bars_used: int
    daily_history_mode: str = "RECENT"  # RECENT | CALENDAR_DATE
    daily_on: str | None = None  # echoed "MM-DD" when the calendar-date view is active
    timeframes: dict[str, PivotTimeframe]  # DAILY / WEEKLY / MONTHLY
    nearest_above: PivotLevelRow | None = None
    nearest_below: PivotLevelRow | None = None
    alerts: list[PivotLevelRow] = Field(default_factory=list)  # tier != FAR, nearest first
    pivots_version: str
