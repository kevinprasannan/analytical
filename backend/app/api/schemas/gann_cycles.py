"""Gann time cycles (docs/07 §4.25, docs/05 §9e).

Day-count projections from the previous swing low / high, plus confluence
clusters where several projections land close together. Computed on read,
not persisted, not scored — descriptive, no BUY/SELL.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class GannAnchor(BaseModel):
    kind: str  # LOW | HIGH
    anchor_date: str
    price: float


class GannProjection(BaseModel):
    anchor_kind: str  # LOW | HIGH
    anchor_date: str
    anchor_price: float
    cycle_days: int
    target_date: str
    days_from_today: int  # signed; negative = past, positive = upcoming
    # what actually happened, filled only when target_date already has a bar
    # (nearest trading date on/after it) — null for a still-future projection
    resolved_date: str | None = None
    actual_close: float | None = None
    actual_high: float | None = None
    actual_low: float | None = None


class GannCluster(BaseModel):
    cluster_date: str
    days_from_today: int
    strength: int
    projections: list[GannProjection] = Field(default_factory=list)


class GannCyclesResponse(BaseModel):
    instrument_id: int
    contract_key: str
    instrument_type: str
    generated_at: str
    status: str  # OK | INSUFFICIENT_DATA | NOT_APPLICABLE
    reason: str | None = None
    swing_low: GannAnchor | None = None
    swing_high: GannAnchor | None = None
    projections: list[GannProjection] = Field(default_factory=list)
    clusters: list[GannCluster] = Field(default_factory=list)
    gann_cycles_version: str
