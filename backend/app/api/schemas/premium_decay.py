"""Premium decay response (docs/07 §4.23, docs/05 §11.6). Table only — no charts.

Descriptive decay-vs-move read (``decay_state``) only — never BUY/SELL.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DecayLeg(BaseModel):
    option_type: str  # CE | PE
    ltp: float | None = None
    price_at_open: float | None = None
    iv: float | None = None
    theta: float | None = None  # per unit, per calendar day
    theta_per_lot: float | None = None
    theta_pct_of_premium: float | None = None  # theta / ltp — normalised decay rate
    expected_decay: float | None = None  # theta-implied move since the session open
    actual_change: float | None = None  # ltp - price_at_open
    decay_gap: float | None = None  # actual_change - expected_decay
    # AS_EXPECTED | DECAYING_FASTER | OFFSET_BY_MOVE | NO_DATA
    decay_state: str


class DecayRow(BaseModel):
    strike: float
    call: DecayLeg | None = None
    put: DecayLeg | None = None


class PremiumDecayResponse(BaseModel):
    underlying_id: int
    underlying_symbol: str
    spot: float
    expiry: str
    expiries: list[str] = Field(default_factory=list)
    days_to_expiry: int
    fast_decay_zone: bool
    as_of: str
    session_open: str
    elapsed_session_minutes: float
    elapsed_calendar_days: float
    atm_strike: float | None = None
    atm_call_theta_per_lot: float | None = None
    atm_put_theta_per_lot: float | None = None
    atm_straddle_theta_per_lot: float | None = None
    algo_version: str
    decay_version: str
    rows: list[DecayRow] = Field(default_factory=list)
