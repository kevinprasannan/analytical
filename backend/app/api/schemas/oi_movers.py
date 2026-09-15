"""Big OI movement — options only (docs/07 §4.22, docs/05 §11.4).

The near-expiry option strikes that added / reduced the most open interest today,
each with the session ΔOI, the last-15-min ΔOI, and a positioning (buildup)
label. Positioning vocabulary only — no BUY/SELL, no order.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class OiMover(BaseModel):
    strike: float
    option_type: str  # CE | PE
    moneyness: str  # DEEP_ITM | ITM | ATM | OTM | DEEP_OTM
    dist_from_spot: float  # strike − spot, points
    oi: int
    oi_at_open: int
    oi_change_session: int
    oi_change_session_pct: float | None = None
    oi_change_recent: int  # last recent_window_min minutes
    ltp: float | None = None
    price_change_session_pct: float | None = None
    price_change_recent_pct: float | None = None
    # positioning over the SESSION (consistent with the added / reduced split)
    # LONG_BUILDUP | SHORT_BUILDUP | LONG_UNWINDING | SHORT_COVERING | INDETERMINATE | NO_DATA
    buildup: str
    buildup_now: str  # same vocabulary, over just the last recent_window_min minutes
    crowded: bool = False


class OiMoversResponse(BaseModel):
    underlying_id: int
    underlying_symbol: str
    spot: float
    expiry: str
    as_of: str
    session_open: str
    recent_window_min: int  # 3 | 5 | 10 | 15 — the 'Δ recent' time band
    moneyness_filter: list[str] = Field(default_factory=list)  # echoed; empty = all
    pcr_oi_now: float | None = None
    max_pain_now: float | None = None
    support_strike: float | None = None
    resistance_strike: float | None = None
    crowded_side: str  # CALLS | PUTS | BALANCED
    net_ce_oi_change: int
    net_pe_oi_change: int
    top: int
    added: list[OiMover] = Field(default_factory=list)  # biggest OI increases, largest first
    reduced: list[OiMover] = Field(default_factory=list)  # biggest OI decreases, largest first
    oi_pulse_version: str
