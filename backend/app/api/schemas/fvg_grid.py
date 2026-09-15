"""ICT swing Fair Value Gaps per timeframe (docs/07 §4.21, docs/05 §9c).

The 'left-side' FVGs that form into a swing high / low and act as inversion
arrays, for 5m / 15m / 30m / 1h. Computed on read, not persisted, not scored —
descriptive, no BUY/SELL.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SwingFvg(BaseModel):
    kind: str  # BULLISH | BEARISH — the gap's original polarity
    inversion_kind: str  # what it acts as after the swing (the opposite)
    swing: str  # HIGH | LOW — the swing it formed into
    top: float
    bottom: float
    ce: float  # consequent encroachment (50 %)
    formed_ts: str | None = None
    swing_ts: str | None = None
    bars_since_swing: int
    state: str  # PRIMED | TESTED | RESPECTED | BREACHED
    reached_ce: bool
    wick_violated: bool
    body_respected: bool
    distance_pct: float  # signed % from last price to the near edge (0 = price inside)


class FvgColumn(BaseModel):
    timeframe: str  # M5 | M15 | M30 | H1
    status: str  # OK | INSUFFICIENT_DATA | NOT_APPLICABLE
    as_of_ts: str | None = None
    reason: str | None = None
    last_price: float | None = None
    bias: str = "NEUTRAL"  # soft lean = inversion_kind of the nearest active gap
    n_active: int = 0
    nearest_above: SwingFvg | None = None
    nearest_below: SwingFvg | None = None
    fvgs: list[SwingFvg] = Field(default_factory=list)


class FvgGridResponse(BaseModel):
    instrument_id: int
    contract_key: str
    instrument_type: str
    generated_at: str
    columns: list[FvgColumn] = Field(default_factory=list)
    fvg_grid_version: str
