"""Per-analysis result models — mirror the ``analytical_core`` engine output
(docs/05 §13, docs/07 §5). Enum fields come from ``analytical_core.enums``."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from analytical_core.enums import (
    AnalysisScope,
    AnalysisStatus,
    BollingerPosition,
    CandleBias,
    CandlePattern,
    CandleStrength,
    Direction,
    Divergence,
    MASlopeState,
    OIBehavior,
    OrderBlockBias,
    OrderBlockZoneState,
    RSIState,
    Timeframe,
    VolumeTrend,
    VolumeUpDownState,
)
from app.api.schemas.common import Provenance

# --- per-analysis `values` / `aux` ---------------------------------------


class RsiValues(BaseModel):
    rsi: float
    state: RSIState
    slope: float | None = None
    divergence: Divergence


class BollingerValues(BaseModel):
    basis: float
    upper: float
    lower: float
    percent_b: float
    bandwidth: float
    bandwidth_percentile: float | None = None
    squeeze: bool | None = None
    position: BollingerPosition


class Ema7Values(BaseModel):
    ema: float
    price_vs_ema: float
    price_above: bool
    slope: float | None = None
    slope_state: MASlopeState


class Ema7Aux(BaseModel):
    atr14: float | None = None
    close_stdev_n: float | None = None


class GoldenCrossValues(BaseModel):
    fast: float | None = None
    slow: float | None = None
    state: Literal["ABOVE", "BELOW"]
    cross_type: str
    cross_ts: str | None = None
    bars_since_cross: int | None = None
    separation: float | None = None
    recent: bool
    provisional: bool


class VolumeValues(BaseModel):
    volume: int
    vol_ma: float
    rvol: float | None = None
    spike: bool
    up_down_ratio: float | None = None
    up_down_state: VolumeUpDownState
    trend: VolumeTrend


class VolumeAux(BaseModel):
    price_change_pct_recent: float | None = None


class OpenInterestValues(BaseModel):
    oi: int
    oi_change: int
    oi_pct_change: float | None = None
    price_change: float | None = None
    price_pct_change: float | None = None
    price_direction: Direction
    oi_direction: Direction
    behavior: OIBehavior
    provider_oi_change: int | None = None


class OrderBlockZone(BaseModel):
    side: Literal["BULLISH", "BEARISH"]
    low: float
    high: float
    mid: float
    formed_ts: str
    bos_ts: str
    age_bars: int
    mitigated: bool
    mitigated_ts: str | None = None
    distance_pct: float | None = None


class OrderBlockValues(BaseModel):
    bias: OrderBlockBias
    zone_state: OrderBlockZoneState
    price: float
    atr: float | None = None
    n_active_bullish: int
    n_active_bearish: int
    nearest_bullish: OrderBlockZone | None = None
    nearest_bearish: OrderBlockZone | None = None
    zones: list[OrderBlockZone] = Field(default_factory=list)


class CandleHit(BaseModel):
    pattern: CandlePattern
    bias: CandleBias
    strength: CandleStrength
    trend_context: str  # UPTREND | DOWNTREND | SIDEWAYS
    bar_ts: str
    bars_ago: int
    open: float
    high: float
    low: float
    close: float


class CandlesValues(BaseModel):
    bias: CandleBias
    last_pattern: CandlePattern | None = None
    last_bias: CandleBias | None = None
    last_strength: CandleStrength | None = None
    last_bars_ago: int | None = None
    on_last_bar: bool
    n_bullish: int
    n_bearish: int
    bars_scanned: int
    patterns: list[CandleHit] = Field(default_factory=list)


VALUE_MODELS: dict[str, type[BaseModel]] = {
    "rsi": RsiValues,
    "bollinger": BollingerValues,
    "ema7": Ema7Values,
    "golden_cross": GoldenCrossValues,
    "volume": VolumeValues,
    "open_interest": OpenInterestValues,
    "order_block": OrderBlockValues,
    "candles": CandlesValues,
}
AUX_MODELS: dict[str, type[BaseModel]] = {"ema7": Ema7Aux, "volume": VolumeAux}


# --- the envelope every analysis endpoint returns ----------------------


#: typed view of `values`, populated on the single-analysis detail endpoint so
#: the per-analysis models + their enums are part of the OpenAPI contract.
TypedValues = (
    RsiValues
    | BollingerValues
    | Ema7Values
    | GoldenCrossValues
    | VolumeValues
    | OpenInterestValues
    | OrderBlockValues
    | CandlesValues
)


class AnalysisItem(BaseModel):
    instrument_id: int
    analysis_key: str
    scope: AnalysisScope
    timeframe: Timeframe | None = None
    session_date: date | None = None
    snapshot_ts: datetime | None = None
    status: AnalysisStatus
    as_of_ts: datetime
    reason: Annotated[
        str | None, Field(description="present for NOT_APPLICABLE / INSUFFICIENT_DATA")
    ] = None
    carried: bool = False
    values: dict[str, Any] = Field(default_factory=dict)
    typed_values: TypedValues | None = None
    aux: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    provenance: Provenance | None = None


class InstrumentAnalyses(BaseModel):
    instrument_id: int
    timeframe: Timeframe
    items: list[AnalysisItem]
