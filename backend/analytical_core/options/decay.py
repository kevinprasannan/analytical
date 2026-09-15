"""Premium decay — theta-implied decay vs. the session's actual move (docs/05
§11.6, docs/07 §4.23).

Pure: the live per-leg Greeks (theta, from the existing ``chain`` build) + each
leg's premium at today's session open in; per strike, the decay theta alone
would predict for the time elapsed since the open, set against what the
premium actually did. A **read view** — descriptive positioning only, never a
BUY/SELL instruction (decision 15).

Modelling note (kept deliberately simple): ``theta`` is *per calendar day*,
evaluated at the option's *current* spot/IV/time-to-expiry — it is the
marginal decay rate right now, not a re-priced value from this morning.
``expected_decay = theta * elapsed_calendar_days`` since the session open is
therefore a linear back-of-envelope estimate, not a full re-pricing across the
elapsed window. On all but the quietest sessions the actual move dwarfs this —
that gap is the point of the screen: it shows how much of today's premium
move is time decay versus everything else (price / IV).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from analytical_core.versioning import ALGO_VERSION

DECAY_VERSION = "0.1.0"

_CE, _PE = "CE", "PE"


class DecayState(StrEnum):
    AS_EXPECTED = "AS_EXPECTED"  # actual move ~= theta-implied decay
    DECAYING_FASTER = "DECAYING_FASTER"  # lost more than theta alone predicts
    OFFSET_BY_MOVE = "OFFSET_BY_MOVE"  # a price/IV move outweighed the theta bleed
    NO_DATA = "NO_DATA"


@dataclass(frozen=True, slots=True)
class DecayConfig:
    price_epsilon_abs: float = 0.5  # ₹ — floor on the "as expected" band
    gap_epsilon_frac: float = 0.3  # + this fraction of |expected_decay|


@dataclass(frozen=True, slots=True)
class DecayLegInput:
    strike: float
    option_type: str  # "CE" | "PE"
    ltp: float | None
    iv: float | None
    theta: float | None  # per unit, per calendar day
    lot_size: int | None
    price_at_open: float | None


@dataclass(frozen=True, slots=True)
class DecayLeg:
    option_type: str
    ltp: float | None
    price_at_open: float | None
    iv: float | None
    theta: float | None  # per unit, per calendar day
    theta_per_lot: float | None  # theta * lot_size, per calendar day
    theta_pct_of_premium: float | None  # theta / ltp — normalised decay rate (negative)
    expected_decay: float | None  # theta * elapsed_calendar_days (signed)
    actual_change: float | None  # ltp - price_at_open (signed)
    decay_gap: float | None  # actual_change - expected_decay
    decay_state: str


@dataclass(frozen=True, slots=True)
class DecayRow:
    strike: float
    call: DecayLeg | None
    put: DecayLeg | None


@dataclass(frozen=True, slots=True)
class PremiumDecay:
    underlying_symbol: str
    spot: float
    expiry: str  # ISO date
    days_to_expiry: int
    fast_decay_zone: bool  # inside the last few DTE, where theta accelerates
    as_of: str
    session_open: str
    elapsed_session_minutes: float
    elapsed_calendar_days: float
    atm_strike: float | None
    atm_call_theta_per_lot: float | None
    atm_put_theta_per_lot: float | None
    atm_straddle_theta_per_lot: float | None
    rows: tuple[DecayRow, ...]
    algo_version: str = field(default=ALGO_VERSION)
    decay_version: str = field(default=DECAY_VERSION)


def _decay_state(expected: float | None, actual: float | None, cfg: DecayConfig) -> DecayState:
    if expected is None or actual is None:
        return DecayState.NO_DATA
    eps = max(cfg.price_epsilon_abs, cfg.gap_epsilon_frac * abs(expected))
    gap = actual - expected
    if abs(gap) <= eps:
        return DecayState.AS_EXPECTED
    return DecayState.DECAYING_FASTER if gap < 0 else DecayState.OFFSET_BY_MOVE


def build_premium_decay(
    *,
    underlying_symbol: str,
    spot: float,
    expiry: str,
    days_to_expiry: int,
    atm_strike: float | None,
    now: datetime,
    session_open: datetime,
    legs: list[DecayLegInput],
    config: DecayConfig | None = None,
) -> PremiumDecay:
    cfg = config or DecayConfig()
    elapsed_seconds = max(0.0, (now - session_open).total_seconds())
    elapsed_days = elapsed_seconds / 86_400.0
    elapsed_minutes = elapsed_seconds / 60.0

    by_strike: dict[float, dict[str, DecayLeg]] = {}
    for li in legs:
        theta_per_lot = (
            round(li.theta * li.lot_size, 4) if (li.theta is not None and li.lot_size) else None
        )
        theta_pct = (
            round(li.theta / li.ltp, 6)
            if (li.theta is not None and li.ltp not in (None, 0))
            else None
        )
        expected = round(li.theta * elapsed_days, 4) if li.theta is not None else None
        actual = (
            round(li.ltp - li.price_at_open, 4)
            if (li.ltp is not None and li.price_at_open is not None)
            else None
        )
        gap = round(actual - expected, 4) if (actual is not None and expected is not None) else None
        state = _decay_state(expected, actual, cfg)
        by_strike.setdefault(li.strike, {})[li.option_type] = DecayLeg(
            option_type=li.option_type,
            ltp=round(li.ltp, 4) if li.ltp is not None else None,
            price_at_open=round(li.price_at_open, 4) if li.price_at_open is not None else None,
            iv=li.iv,
            theta=li.theta,
            theta_per_lot=theta_per_lot,
            theta_pct_of_premium=theta_pct,
            expected_decay=expected,
            actual_change=actual,
            decay_gap=gap,
            decay_state=state.value,
        )

    strikes = sorted(by_strike)
    rows = tuple(
        DecayRow(strike=s, call=by_strike[s].get(_CE), put=by_strike[s].get(_PE)) for s in strikes
    )

    atm_row = by_strike.get(atm_strike) if atm_strike is not None else None
    atm_call = atm_row.get(_CE) if atm_row else None
    atm_put = atm_row.get(_PE) if atm_row else None
    atm_call_theta_lot = atm_call.theta_per_lot if atm_call else None
    atm_put_theta_lot = atm_put.theta_per_lot if atm_put else None
    straddle = (
        round(atm_call_theta_lot + atm_put_theta_lot, 4)
        if (atm_call_theta_lot is not None and atm_put_theta_lot is not None)
        else None
    )

    return PremiumDecay(
        underlying_symbol=underlying_symbol,
        spot=round(spot, 4),
        expiry=expiry,
        days_to_expiry=days_to_expiry,
        fast_decay_zone=days_to_expiry <= 5,
        as_of=now.isoformat(),
        session_open=session_open.isoformat(),
        elapsed_session_minutes=round(elapsed_minutes, 1),
        elapsed_calendar_days=round(elapsed_days, 4),
        atm_strike=atm_strike,
        atm_call_theta_per_lot=atm_call_theta_lot,
        atm_put_theta_per_lot=atm_put_theta_lot,
        atm_straddle_theta_per_lot=straddle,
        rows=rows,
    )


def _slots(o) -> dict:
    return {s: getattr(o, s) for s in o.__slots__}


def premium_decay_to_dict(p: PremiumDecay) -> dict:
    d = {k: v for k, v in _slots(p).items() if k != "rows"}
    d["rows"] = [
        {
            "strike": r.strike,
            "call": _slots(r.call) if r.call else None,
            "put": _slots(r.put) if r.put else None,
        }
        for r in p.rows
    ]
    return d
