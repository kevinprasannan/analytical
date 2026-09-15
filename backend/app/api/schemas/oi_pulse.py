"""OI-pulse response (docs/07 §4.11, docs/05 §11.4). Table only — no charts.

Analytical positioning labels only (``buildup`` / ``bias``); never BUY/SELL.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class OiPulseLeg(BaseModel):
    option_type: str
    oi: int
    oi_at_open: int
    oi_change_session: int
    oi_change_session_pct: float | None = None
    oi_change_recent: int
    ltp: float | None = None
    price_change_recent_pct: float | None = None
    # LONG_BUILDUP | SHORT_BUILDUP | LONG_UNWINDING | SHORT_COVERING | INDETERMINATE | NO_DATA
    buildup: str
    crowded: bool = False  # this strike carries an outsized share of its side's fresh OI


class OiPulseRow(BaseModel):
    strike: float
    call: OiPulseLeg | None = None
    put: OiPulseLeg | None = None


class OiTracePoint(BaseModel):
    ts: str
    spot: float | None = None
    call_oi_change: int
    call_oi_change_delta: int
    put_oi_change: int
    put_oi_change_delta: int
    diff_oi: int
    diff_pct: float | None = None
    dir_of_change: int
    pcr_oi: float | None = None  # total put OI / total call OI at this mark
    coi_pcr: float | None = None  # put ΔOI / call ΔOI
    vol_pcr: float | None = None  # cumulative put volume / call volume
    total_ce_oi: int
    total_pe_oi: int
    max_pain: float | None = None
    sentiment: str  # Bullish | Bearish | Neutral


class OiPulseResponse(BaseModel):
    underlying_id: int
    underlying_symbol: str
    spot: float
    expiry: str
    expiries: list[str] = Field(default_factory=list)
    as_of: str
    session_open: str
    pcr_oi_now: float | None = None
    pcr_oi_open: float | None = None
    max_pain_now: float | None = None
    max_pain_open: float | None = None
    max_pain_shift: float | None = None
    support_strike: float | None = None
    resistance_strike: float | None = None
    total_ce_oi: int
    total_pe_oi: int
    net_ce_oi_change: int
    net_pe_oi_change: int
    bias: str  # CALL_WRITING | PUT_WRITING | CALL_UNWINDING | PUT_UNWINDING | BALANCED
    crowded_side: str = "BALANCED"  # CALLS | PUTS | BALANCED — side drawing the fresh OI
    crowded_ce_strike: float | None = None
    crowded_pe_strike: float | None = None
    crowded_ce_frac: float | None = None
    crowded_pe_frac: float | None = None
    trace_atm_strike: float | None = None
    trace_window_up: int | None = None  # strikes above ATM kept in the trace (null = all)
    trace_window_down: int | None = None  # strikes below ATM kept in the trace (null = all)
    algo_version: str
    oi_pulse_version: str
    rows: list[OiPulseRow] = Field(default_factory=list)
    trace: list[OiTracePoint] = Field(default_factory=list)
