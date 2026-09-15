"""Top-N constituents — levels + indicators (docs/07 §4.20, docs/15).

Per top-weight index member: prev-day CPR / pivots, the 52-week range, RSI
(D1 + H1), Bollinger (D1) and the MA trend. Every candle fetched live from the
provider on read (constituents are not ingested). Descriptive — no BUY/SELL.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class StockPivot(BaseModel):
    p: float
    tc: float
    bc: float
    r1: float
    r2: float
    r3: float
    s1: float
    s2: float
    s3: float
    cpr_width_pct: float
    width_band: str  # NARROW | AVERAGE | WIDE
    close_vs_pivot: str  # ABOVE | AT | BELOW


class StockRange52(BaseModel):
    high: float
    low: float
    pct_from_high: float | None = None
    pct_from_low: float | None = None
    position: float | None = None  # 0 = at the 52w low, 1 = at the high


class StockRsi(BaseModel):
    value: float
    state: str  # OVERBOUGHT | OVERSOLD | NEUTRAL


class StockBollinger(BaseModel):
    pct_b: float | None = None
    position: str | None = None  # ABOVE_UPPER | UPPER_HALF | MIDDLE | LOWER_HALF | BELOW_LOWER
    squeeze: bool | None = None


class StockMa(BaseModel):
    ema20: float | None = None
    ema50: float | None = None
    sma50: float | None = None
    sma200: float | None = None
    price_vs_ema20: str | None = None  # ABOVE | AT | BELOW
    price_vs_ema50: str | None = None
    cross_state: str | None = None  # ABOVE | BELOW  (50 SMA vs 200 SMA)
    cross_type: str | None = None  # GOLDEN | DEATH | NONE_IN_WINDOW
    bars_since_cross: int | None = None
    recent_cross: bool = False


class ConstituentLevels(BaseModel):
    rank: int
    symbol: str
    name: str
    sector: str
    weight_pct: float
    cumulative_weight_pct: float
    last_price: float
    prev_close: float
    day_change_pct: float | None = None
    pivot: StockPivot
    range52: StockRange52
    rsi_d1: StockRsi | None = None
    rsi_h1: StockRsi | None = None
    bollinger_d1: StockBollinger | None = None
    ma: StockMa
    hint: str


class ConstituentLevelsError(BaseModel):
    symbol: str
    reason: str


class ConstituentLevelsResponse(BaseModel):
    index_id: int
    contract_key: str
    weights_effective_date: str | None = None
    generated_at: str
    n: int
    stocks: list[ConstituentLevels] = Field(default_factory=list)
    errors: list[ConstituentLevelsError] = Field(default_factory=list)
    constituent_levels_version: str
