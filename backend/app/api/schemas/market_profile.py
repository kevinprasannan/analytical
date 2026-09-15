"""Market Profile response (docs/07 §4.4, resolves M25)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from analytical_core.enums import MarketProfileShape


class ProfileBins(BaseModel):
    bins: list[dict] = Field(default_factory=list)


class MPEvent(BaseModel):
    id: str
    category: str
    state: str
    strength: str
    level: str | None = None
    direction: str | None = None
    degraded: bool = False
    confirmed_close_only: bool = False
    last_bracket: int | None = None
    history: list[dict] = Field(default_factory=list)
    meta: dict = Field(default_factory=dict)


class MPDayType(BaseModel):
    day_type: str
    provisional: bool
    silhouette: str
    candidates: list[dict] = Field(default_factory=list)


class MPEventsBlock(BaseModel):
    """Market Profile event layer (docs/14) — analytical states, never directives."""

    version: str
    status: str  # OK | INSUFFICIENT_DATA | ERROR
    reason: str | None = None
    day_type: MPDayType | None = None
    events: list[MPEvent] = Field(default_factory=list)
    tensions: list[dict] = Field(default_factory=list)
    facts: dict | None = None


class MarketProfileResponse(BaseModel):
    instrument_id: int
    session_date: date
    is_session_complete: bool
    bin_size: float | None = None
    poc: float | None = None
    vah: float | None = None
    val: float | None = None
    ib_high: float | None = None
    ib_low: float | None = None
    session_high: float | None = None
    session_low: float | None = None
    profile_shape: MarketProfileShape | None = None
    close: float | None = None
    close_vs_poc: str | None = None
    close_vs_vah: str | None = None
    close_vs_val: str | None = None
    close_in_value_area: bool | None = None
    profiles: dict[str, ProfileBins] = Field(default_factory=dict)
    events: MPEventsBlock | None = None  # docs/14 event layer
