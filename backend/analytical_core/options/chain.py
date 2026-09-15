"""Assemble an option chain from raw per-strike quotes (docs/05 §11, docs/07 §4.4).

Pure: raw legs (strike, side, LTP, OI, OI-change, volume) + spot + expiry + rate
in, an :class:`OptionChain` (IV, greeks per leg; PCR and max-pain aggregates) out.
No IO. Table only — no charts (decision 11).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from analytical_core.options.black_scholes import bs_greeks
from analytical_core.options.iv import implied_vol
from analytical_core.versioning import ALGO_VERSION

_IST = ZoneInfo("Asia/Kolkata")
_SESSION_CLOSE = (15, 30)  # IST; expiry settles at the close


@dataclass(frozen=True, slots=True)
class CrowdedRead:
    """Which side (calls / puts) is drawing the fresh OI, and where it piles up."""

    side: str  # "CALLS" | "PUTS" | "BALANCED"
    call_strike: float | None  # strike with the biggest positive OI build on the call side
    put_strike: float | None
    call_frac: float | None  # that strike's share of the side's total positive build (0..1)
    put_frac: float | None
    net_call_add: int  # Σ positive ΔOI across call strikes
    net_put_add: int


def crowded_read(
    ce_change: dict[float, int],
    pe_change: dict[float, int],
    *,
    dominance: float = 1.3,
    floor: int = 0,
) -> CrowdedRead:
    """From per-strike ΔOI maps: the crowded side (one side's positive build must
    beat the other's by ``dominance``×, else BALANCED) and each side's hottest
    strike + how concentrated it is."""

    def _hot(chg: dict[float, int]):
        pos = {k: v for k, v in chg.items() if v > 0}
        if not pos:
            return None, None, 0
        s = max(pos, key=pos.get)
        tot = sum(pos.values())
        return s, (round(pos[s] / tot, 4) if tot else None), int(tot)

    cs, cf, ctot = _hot(ce_change)
    ps, pf, ptot = _hot(pe_change)
    side = "BALANCED"
    if ctot > max(floor, ptot * dominance):
        side = "CALLS"
    elif ptot > max(floor, ctot * dominance):
        side = "PUTS"
    return CrowdedRead(side, cs, ps, cf, pf, ctot, ptot)


@dataclass(frozen=True, slots=True)
class LegInput:
    strike: float
    option_type: str  # "CE" | "PE"
    ltp: float | None
    oi: int | None
    oi_change: int | None
    volume: int | None
    day_open: float | None = None
    day_high: float | None = None
    day_low: float | None = None


@dataclass(frozen=True, slots=True)
class ChainLeg:
    strike: float
    option_type: str
    ltp: float | None
    oi: int | None
    oi_change: int | None
    volume: int | None
    day_open: float | None  # this contract's OHLC for the trading day
    day_high: float | None
    day_low: float | None
    day_close: float | None  # last traded (== ltp); named for a clean O/H/L/C set
    open_at_high: bool  # premium opened at the session high — topped at the bell, faded
    open_at_low: bool  # premium opened at the session low — bottomed at the bell, rose
    oi_change_pct: float | None  # ΔOI as a fraction of the opening OI (0.42 == +42%)
    crowded: bool  # this strike carries an outsized share of its side's fresh OI
    iv: float | None  # annualised, as a fraction (0.1523 == 15.23%)
    delta: float | None
    gamma: float | None
    theta: float | None  # per calendar day
    vega: float | None  # per 1% vol


@dataclass(frozen=True, slots=True)
class ChainRow:
    strike: float
    call: ChainLeg | None
    put: ChainLeg | None


@dataclass(frozen=True, slots=True)
class OptionChain:
    underlying_symbol: str
    spot: float
    expiry: str  # ISO date
    days_to_expiry: int
    t_years: float
    risk_free_rate: float
    atm_strike: float | None
    rows: tuple[ChainRow, ...]
    pcr_oi: float | None
    pcr_volume: float | None
    max_pain_strike: float | None
    total_call_oi: int
    total_put_oi: int
    crowded_side: str = "BALANCED"  # CALLS | PUTS | BALANCED — which side drew the fresh OI
    crowded_call_strike: float | None = None
    crowded_put_strike: float | None = None
    crowded_call_frac: float | None = None  # hot strike's share of the call side's OI build
    crowded_put_frac: float | None = None
    algo_version: str = field(default=ALGO_VERSION)


def _t_years(now: datetime, expiry: date) -> float:
    close = datetime(
        expiry.year, expiry.month, expiry.day, *_SESSION_CLOSE, tzinfo=_IST
    ).astimezone(UTC)
    return max(0.0, (close - now.astimezone(UTC)).total_seconds() / (365.0 * 24.0 * 3600.0))


def _leg(inp: LegInput, spot: float, t: float, r: float, q: float) -> ChainLeg:
    is_call = inp.option_type == "CE"
    iv = greeks = None
    if inp.ltp and inp.ltp > 0.0 and t > 0.0:
        iv = implied_vol(inp.ltp, spot, inp.strike, t, r, is_call=is_call, q=q)
        if iv is not None:
            greeks = bs_greeks(spot, inp.strike, t, r, iv, is_call=is_call, q=q)
    _r = lambda v: round(v, 4) if v is not None else None  # noqa: E731
    o, h, low = _r(inp.day_open), _r(inp.day_high), _r(inp.day_low)
    # a genuine range is needed — a single-print / no-move bar is not "open at high"
    has_range = o is not None and h is not None and low is not None and h > low
    opening_oi = (
        (inp.oi - inp.oi_change) if (inp.oi is not None and inp.oi_change is not None) else None
    )
    oi_pct = (
        round(inp.oi_change / opening_oi, 4)
        if (inp.oi_change is not None and opening_oi not in (None, 0))
        else None
    )
    return ChainLeg(
        strike=round(inp.strike, 4),
        option_type=inp.option_type,
        ltp=_r(inp.ltp),
        oi=inp.oi,
        oi_change=inp.oi_change,
        volume=inp.volume,
        day_open=o,
        day_high=h,
        day_low=low,
        day_close=_r(inp.ltp),
        open_at_high=bool(has_range and o == h),
        open_at_low=bool(has_range and o == low),
        oi_change_pct=oi_pct,
        crowded=False,
        iv=iv,
        delta=round(greeks.delta, 6) if greeks else None,
        gamma=round(greeks.gamma, 8) if greeks else None,
        theta=round(greeks.theta, 6) if greeks else None,
        vega=round(greeks.vega, 6) if greeks else None,
    )


def max_pain(
    strikes: list[float], ce_oi: dict[float, int], pe_oi: dict[float, int]
) -> float | None:
    """Strike that minimises total option-writer payout given the OI distribution."""
    if not strikes:
        return None
    best_s, best_loss = None, None
    for s in strikes:
        loss = 0.0
        for k in strikes:
            if s > k:
                loss += ce_oi.get(k, 0) * (s - k)
            if k > s:
                loss += pe_oi.get(k, 0) * (k - s)
        if best_loss is None or loss < best_loss:
            best_s, best_loss = s, loss
    return best_s


def build_chain(
    *,
    underlying_symbol: str,
    spot: float,
    expiry: date,
    now: datetime,
    risk_free_rate: float,
    legs: list[LegInput],
    dividend_yield: float = 0.0,
) -> OptionChain:
    t = _t_years(now, expiry)
    dte = max(0, (expiry - now.astimezone(_IST).date()).days)

    by_strike: dict[float, dict[str, ChainLeg]] = {}
    ce_oi: dict[float, int] = {}
    pe_oi: dict[float, int] = {}
    tot_ce_oi = tot_pe_oi = tot_ce_vol = tot_pe_vol = 0
    for inp in legs:
        leg = _leg(inp, spot, t, risk_free_rate, dividend_yield)
        by_strike.setdefault(leg.strike, {})[leg.option_type] = leg
        if leg.option_type == "CE":
            ce_oi[leg.strike] = inp.oi or 0
            tot_ce_oi += inp.oi or 0
            tot_ce_vol += inp.volume or 0
        else:
            pe_oi[leg.strike] = inp.oi or 0
            tot_pe_oi += inp.oi or 0
            tot_pe_vol += inp.volume or 0

    # crowded read — which side is drawing fresh OI, and the hot strike each side
    ce_chg = {
        inp.strike: inp.oi_change for inp in legs if inp.option_type == "CE" and inp.oi_change
    }
    pe_chg = {
        inp.strike: inp.oi_change for inp in legs if inp.option_type == "PE" and inp.oi_change
    }
    cr = crowded_read(ce_chg, pe_chg)
    for s, side in ((cr.call_strike, "CE"), (cr.put_strike, "PE")):
        if s is not None and s in by_strike and side in by_strike[s]:
            by_strike[s][side] = replace(by_strike[s][side], crowded=True)

    strikes = sorted(by_strike)
    rows = tuple(
        ChainRow(strike=s, call=by_strike[s].get("CE"), put=by_strike[s].get("PE")) for s in strikes
    )
    atm = min(strikes, key=lambda s: abs(s - spot)) if strikes else None
    return OptionChain(
        underlying_symbol=underlying_symbol,
        spot=round(spot, 4),
        expiry=expiry.isoformat(),
        days_to_expiry=dte,
        t_years=round(t, 8),
        risk_free_rate=risk_free_rate,
        atm_strike=atm,
        rows=rows,
        pcr_oi=round(tot_pe_oi / tot_ce_oi, 4) if tot_ce_oi else None,
        pcr_volume=round(tot_pe_vol / tot_ce_vol, 4) if tot_ce_vol else None,
        max_pain_strike=max_pain(strikes, ce_oi, pe_oi),
        total_call_oi=tot_ce_oi,
        total_put_oi=tot_pe_oi,
        crowded_side=cr.side,
        crowded_call_strike=cr.call_strike,
        crowded_put_strike=cr.put_strike,
        crowded_call_frac=cr.call_frac,
        crowded_put_frac=cr.put_frac,
    )
