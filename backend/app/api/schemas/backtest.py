"""Opening-range breakout backtest response (docs/07 §4.15, docs/16).

Descriptive research over historical bars — no signal, no label, no BUY/SELL.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class OrbConfigOut(BaseModel):
    range_start: int  # IST minute-of-day
    range_end: int
    break_start: int
    break_end: int
    measure_until: int
    target_mults: list[float] = Field(default_factory=list)


class OrbTargetOutcome(BaseModel):
    mult: float
    hit: bool
    minutes_to_hit: int | None = None  # from the breakout minute
    stopped_first: bool


class OrbDayResult(BaseModel):
    date: str
    weekday: int  # 0 = Monday
    range_high: float | None = None
    range_low: float | None = None
    range_size: float | None = None
    direction: str  # LONG | SHORT | NONE
    break_minute: int | None = None
    break_immediate: bool
    entry_level: float | None = None
    stop_level: float | None = None
    stop_hit: bool
    stop_minute: int | None = None
    mfe_r: float | None = None  # max favourable excursion from entry, in range units
    mae_r: float | None = None
    targets: list[OrbTargetOutcome] = Field(default_factory=list)
    note: str | None = None


class OrbTargetStat(BaseModel):
    mult: float
    hits: int
    hit_rate: float  # hits / n_breakout
    avg_minutes_to_hit: float | None = None


class OrbWeekdayStat(BaseModel):
    weekday: int
    n: int
    n_breakout: int
    per_target_hit_rate: list[tuple[float, float]] = Field(default_factory=list)  # (mult, rate)


class OrbAggregateOut(BaseModel):
    n_days: int
    n_with_range: int
    n_breakout: int
    breakout_rate: float
    n_long: int
    n_short: int
    n_immediate: int
    stop_rate: float
    avg_range_size: float | None = None
    avg_mfe_r: float | None = None
    avg_mae_r: float | None = None
    per_target: list[OrbTargetStat] = Field(default_factory=list)
    by_weekday: list[OrbWeekdayStat] = Field(default_factory=list)


class OrbBacktestResponse(BaseModel):
    index_id: int
    underlying_symbol: str
    timeframe: str  # M1 | M15
    start: str  # ISO date
    end: str
    config: OrbConfigOut
    aggregate: OrbAggregateOut
    days: list[OrbDayResult] = Field(default_factory=list)
    index_orb_version: str
    algo_version: str
