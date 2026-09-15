"""Score models (docs/07 §4.5). Analytical labels only — never BUY/SELL."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from analytical_core.enums import AnalysisScope, SignalLabel, Timeframe


class ScoreListItem(BaseModel):
    instrument_id: int
    contract_key: str
    symbol: str
    timeframe: Timeframe
    composite_score: float
    raw_label: SignalLabel
    effective_label: SignalLabel
    confidence: float
    low_confidence: bool
    as_of_ts: datetime
    run_id: int
    delta_vs_previous: float | None = None
    warnings: list[str] = Field(default_factory=list)


class ScoreFactorItem(BaseModel):
    analysis_key: str
    scope: AnalysisScope
    raw_values: dict[str, Any] = Field(default_factory=dict)
    sub_score: float
    confidence: float
    weight: float
    contribution: float
    reason: str | None = None
    rationale: dict[str, Any] = Field(default_factory=dict)


class ScoreDetail(BaseModel):
    instrument_id: int
    timeframe: Timeframe
    composite_score: float
    raw_label: SignalLabel
    effective_label: SignalLabel
    confidence: float
    low_confidence: bool
    as_of_ts: datetime
    run_id: int
    strategy: str
    scoring_version: str
    params_hash: str
    weights: dict[str, float] = Field(default_factory=dict)
    denom: float | None = None
    delta_vs_previous: float | None = None
    warnings: list[str] = Field(default_factory=list)
    explanation: str | None = None
    factors: list[ScoreFactorItem] = Field(default_factory=list)


class ScoreHistoryPoint(BaseModel):
    run_id: int
    as_of_ts: datetime
    composite_score: float
    raw_label: SignalLabel
    effective_label: SignalLabel
    confidence: float
    low_confidence: bool


class ScoreHistory(BaseModel):
    instrument_id: int
    timeframe: Timeframe
    points: list[ScoreHistoryPoint]
