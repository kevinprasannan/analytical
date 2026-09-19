"""Candle Range Theory per timeframe (docs/07 §4.24, docs/05 §9d).

A reference candle's High-Low range and how price has behaved around it since
— acceptance / rejection / expansion — for 5m / 15m / 30m / 1h. Computed on
read, not persisted, not scored — descriptive, no BUY/SELL.
"""

from __future__ import annotations

from pydantic import BaseModel


class CrtRead(BaseModel):
    reference_ts: str | None = None
    ref_high: float
    ref_low: float
    ref_range: float
    ref_midpoint: float
    is_inside_candle: bool  # reference candle sat fully inside its own prior ("mother") bar
    mother_high: float | None = None
    mother_low: float | None = None
    last_ts: str | None = None
    last_close: float
    current_position: str  # ABOVE_HIGH | BELOW_LOW | INSIDE | AT_MIDPOINT
    breakout_direction: str  # NONE | HIGH | LOW
    breakout_ts: str | None = None
    close_outside: bool
    returned_inside: bool
    retested: bool
    holds_beyond: bool
    expansion_points: float | None = None
    expansion_multiple: float | None = None
    volume_confirms: bool | None = None
    signal: str  # BULLISH_CONTINUATION | BEARISH_CONTINUATION | HIGH_REJECTION | LOW_REJECTION |
    # RANGE_EXPANSION_UP | RANGE_EXPANSION_DOWN | COMPRESSION | NEUTRAL
    bars_scanned: int


class CrtColumn(BaseModel):
    timeframe: str  # M5 | M15 | M30 | H1
    status: str  # OK | INSUFFICIENT_DATA | NOT_APPLICABLE
    as_of_ts: str | None = None
    reason: str | None = None
    read: CrtRead | None = None


class CrtGridResponse(BaseModel):
    instrument_id: int
    contract_key: str
    instrument_type: str
    generated_at: str
    columns: list[CrtColumn]
    crt_grid_version: str
