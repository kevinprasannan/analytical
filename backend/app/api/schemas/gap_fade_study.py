"""Gap-fade streak study (docs/07 §4.26, docs/05 §9f).

What tends to happen after a day that gaps one way but closes the other —
both reversal directions (UP: gap up, closes down; DOWN: gap down, closes
up) — the resulting streak length, the consolidation box that follows, and
which way it eventually breaks, aggregated per direction across every
historical occurrence. Not a backtest (no entry/exit/target/stop), a
descriptive historical study. Computed on read, not persisted, not scored —
no BUY/SELL.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class GapFadeOccurrence(BaseModel):
    event_date: str
    direction: str  # UP (gap up, closed down) | DOWN (gap down, closed up)
    gap_pct: float
    change_pct: float
    streak_days: int
    streak_end_date: str
    status: str  # STREAK_ONGOING | INSUFFICIENT_BOX_DATA | CONSOLIDATING | BREAKOUT_UP/DOWN
    box_start_date: str | None = None
    box_high: float | None = None
    box_low: float | None = None
    consolidation_days: int | None = None
    breakout_date: str | None = None
    breakout_direction: str | None = None  # UP | DOWN


class GapFadeSummary(BaseModel):
    direction: str  # UP | DOWN
    n_occurrences: int
    n_streak_resolved: int
    mean_streak_days: float | None = None
    median_streak_days: float | None = None
    streak_day_histogram: dict[str, int] = Field(default_factory=dict)
    n_breakout_resolved: int = 0
    mean_consolidation_days: float | None = None
    median_consolidation_days: float | None = None
    breakout_up_count: int = 0
    breakout_down_count: int = 0
    breakout_up_pct: float | None = None


class GapFadeStudyResponse(BaseModel):
    instrument_id: int
    contract_key: str
    instrument_type: str
    generated_at: str
    status: str  # OK | INSUFFICIENT_DATA | NOT_APPLICABLE
    reason: str | None = None
    params: dict = Field(default_factory=dict)
    summaries: list[GapFadeSummary] = Field(default_factory=list)
    occurrences: list[GapFadeOccurrence] = Field(default_factory=list)
    gap_fade_study_version: str
