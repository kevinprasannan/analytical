"""Key levels from the last two sessions' profiles (docs/07 §4.16, docs/05 §10.12).

Descriptive — POC / VAH / VAL / IB / session high-low from the previous two
completed sessions, each tagged with signed distance from the latest price and a
proximity tier, plus an acceptance / rejection read. No bias, no BUY/SELL.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

_Tier = str  # AT | NEAR | APPROACHING | FAR
_Side = str  # ABOVE | BELOW | AT
_Acc = str  # ACCEPTED_ABOVE | ACCEPTED_BELOW | REJECTED_FROM_ABOVE | REJECTED_FROM_BELOW | TESTING | UNTOUCHED


class KeyLevel(BaseModel):
    price: float
    kind: str  # POC | VAH | VAL | IB_HIGH | IB_LOW | HIGH | LOW
    session: str  # "D-1" | "D-2"
    session_date: str
    distance: float  # signed points (level − last_price)
    distance_pct: float
    tier: _Tier
    side: _Side
    acceptance: _Acc | None = None


class KeyLevelSession(BaseModel):
    label: str
    date: str
    shape: str | None = None
    day_type: str | None = None
    poc: float | None = None
    vah: float | None = None
    val: float | None = None
    ib_high: float | None = None
    ib_low: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    close_vs_value: str | None = None  # ABOVE | INSIDE | BELOW
    complete: bool


class KeyLevelsResponse(BaseModel):
    instrument_id: int
    contract_key: str
    last_price: float
    bands: dict[str, float]  # at / near / approaching, in points
    sessions: list[KeyLevelSession] = Field(default_factory=list)
    levels: list[KeyLevel] = Field(default_factory=list)
    alerts: list[KeyLevel] = Field(default_factory=list)  # tier != FAR, nearest first
    nearest_above: KeyLevel | None = None
    nearest_below: KeyLevel | None = None
    key_levels_version: str
