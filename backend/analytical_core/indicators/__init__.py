"""Deterministic technical indicators (docs/05 §4–§9).

Pure: series + params in, `AnalysisResult` out. No IO, no `Instrument`, no DB.
Same inputs + same effective params + same `ALGO_VERSION` ⇒ identical output
under the pinned numeric stack (`docs/05` §1.2).
"""

from __future__ import annotations

from analytical_core.indicators.bollinger import bollinger
from analytical_core.indicators.candles import candles
from analytical_core.indicators.ema import ema7
from analytical_core.indicators.golden_cross import golden_cross
from analytical_core.indicators.open_interest import open_interest
from analytical_core.indicators.order_block import order_block
from analytical_core.indicators.rsi import rsi
from analytical_core.indicators.volume import volume

INDICATORS = {
    "rsi": rsi,
    "bollinger": bollinger,
    "ema7": ema7,
    "golden_cross": golden_cross,
    "volume": volume,
    "open_interest": open_interest,
    "order_block": order_block,
    "candles": candles,
}

__all__ = [
    "INDICATORS",
    "rsi",
    "bollinger",
    "ema7",
    "golden_cross",
    "volume",
    "open_interest",
    "order_block",
    "candles",
]
