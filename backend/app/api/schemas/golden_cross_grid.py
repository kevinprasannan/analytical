"""Golden Cross per timeframe (docs/07 §4.19, docs/05 §7).

The 50 / 200 SMA cross state + the last cross for 5m / 15m / 1h / 1D side by
side. Computed on read, not persisted, not scored — descriptive, no BUY/SELL.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class GoldenCrossColumn(BaseModel):
    timeframe: str  # M5 | M15 | H1 | D1
    status: str  # OK | INSUFFICIENT_DATA | NOT_APPLICABLE
    as_of_ts: str | None = None
    reason: str | None = None
    fast: float | None = None  # fast MA (50) at the last bar
    slow: float | None = None  # slow MA (200)
    state: str | None = None  # ABOVE | BELOW  (fast vs slow)
    cross_type: str | None = None  # GOLDEN | DEATH | NONE_IN_WINDOW
    cross_ts: str | None = None
    bars_since_cross: int | None = None
    separation: float | None = None  # (fast - slow) / slow
    recent: bool = False  # cross within recent_window bars
    provisional: bool = False
    # price read against the MAs as dynamic support / resistance
    last_price: float | None = None
    dist_to_fast_pct: float | None = None  # (last_price - fast) / fast, signed
    dist_to_slow_pct: float | None = None  # (last_price - slow) / slow, signed
    near_fast: bool = False  # |dist_to_fast_pct| <= near_ma_pct
    near_slow: bool = False
    nearest_ma: str | None = None  # FAST | SLOW — whichever is near, nearer wins
    nearest_ma_side: str | None = None  # SUPPORT (MA below price) | RESISTANCE (above)


class GoldenCrossGridResponse(BaseModel):
    instrument_id: int
    contract_key: str
    instrument_type: str
    generated_at: str
    fast_period: int
    slow_period: int
    ma_type: str  # SMA | EMA
    near_ma_pct: float  # proximity band used for near_fast / near_slow
    columns: list[GoldenCrossColumn] = Field(default_factory=list)
    golden_cross_grid_version: str
