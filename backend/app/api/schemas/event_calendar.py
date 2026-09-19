"""Economic event calendar (docs/07 §4.27, docs/05 §9g).

A small set of recurring-date event types (not live news) with a
before/after price read on the instrument being viewed. Computed on read,
not persisted, not scored — descriptive, no BUY/SELL.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class EventOccurrence(BaseModel):
    event_type: str  # US_JOBS_REPORT | INDIA_GST_COLLECTION | FNO_EXPIRY
    event_date: str
    prior_close: float | None = None
    close: float | None = None
    change_pct: float | None = None
    next_close: float | None = None
    next_change_pct: float | None = None


class EventTypeSummary(BaseModel):
    event_type: str
    n_occurrences: int
    n_resolved: int
    mean_abs_change_pct: float | None = None
    median_abs_change_pct: float | None = None
    pct_notable_move: float | None = None
    up_count: int
    down_count: int


class EventCalendarResponse(BaseModel):
    instrument_id: int
    contract_key: str
    instrument_type: str
    generated_at: str
    status: str  # OK | INSUFFICIENT_DATA | NOT_APPLICABLE
    reason: str | None = None
    notable_move_pct: float
    summaries: list[EventTypeSummary] = Field(default_factory=list)
    occurrences: list[EventOccurrence] = Field(default_factory=list)
    event_calendar_version: str
