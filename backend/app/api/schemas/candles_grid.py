"""Multi-timeframe candle-pattern grid (docs/07 §4.17, docs/05 §9b).

5m / 15m / 30m / 1h columns, the last N major candlestick patterns per column,
newest first. M30 is folded on read from M5 (no M30 in the engine grid,
decision 4). Computed on read, not persisted, not scored — descriptive only,
no BUY/SELL.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CandleGridHit(BaseModel):
    pattern: str
    bias: str  # BULLISH | BEARISH | NEUTRAL
    strength: str  # WEAK | MODERATE | STRONG
    trend_context: str  # UPTREND | DOWNTREND | SIDEWAYS
    bar_ts: str
    bars_ago: int
    open: float
    high: float
    low: float
    close: float


class CandleGridColumn(BaseModel):
    timeframe: str  # M5 | M15 | M30 | H1
    status: str  # OK | INSUFFICIENT_DATA | NOT_APPLICABLE
    as_of_ts: str | None = None
    reason: str | None = None
    bias: str | None = None
    last_pattern: str | None = None
    last_bias: str | None = None
    last_strength: str | None = None
    last_bars_ago: int | None = None
    on_last_bar: bool = False
    n_bullish: int = 0
    n_bearish: int = 0
    bars_scanned: int = 0
    patterns: list[CandleGridHit] = Field(default_factory=list)


class CandlesGridResponse(BaseModel):
    instrument_id: int
    contract_key: str
    instrument_type: str
    generated_at: str
    limit: int
    columns: list[CandleGridColumn] = Field(default_factory=list)
    candles_grid_version: str
