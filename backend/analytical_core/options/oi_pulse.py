"""Intraday **OI pulse** (docs/05 §11.4) — trending open interest for one expiry.

Pure + deterministic, no IO. Per-strike CE/PE open-interest and premium series in;
out comes a strike ladder with session / recent OI change and a positioning label,
PCR and max-pain **now vs. at the open**, the OI support / resistance walls, a
net option-writing bias, and a tabular session trace.

Analytical labels only — the buildup / bias vocabulary describes *positioning*
(who is writing or covering), never a BUY / SELL instruction (decision 15).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from dataclasses import replace as _dc_replace
from datetime import datetime, timedelta

from analytical_core.enums import Direction, OIBehavior
from analytical_core.indicators.open_interest import classify_oi_behavior
from analytical_core.options.chain import crowded_read, max_pain
from analytical_core.versioning import ALGO_VERSION

OI_PULSE_VERSION = (
    "0.2.0"  # 0.2.0: per-leg buildup_session + price_at_open / session % (2026-09-10)
)

_CE, _PE = "CE", "PE"


@dataclass(frozen=True, slots=True)
class OiLegSeries:
    """One option leg's intraday history (ascending ts, may be empty).

    ``volume`` is that leg's per-minute traded volume — summed to a running
    session total inside the trace.
    """

    strike: float
    option_type: str  # "CE" | "PE"
    oi: tuple[tuple[datetime, int], ...]
    premium: tuple[tuple[datetime, float], ...]
    volume: tuple[tuple[datetime, int], ...] = ()


@dataclass(frozen=True, slots=True)
class OiPulseConfig:
    recent_window_min: int = 15
    trace_step_min: int = 5
    price_epsilon_pct: float = 0.0005
    oi_epsilon_abs: float = 0.0
    #: |net side OI change| below this fraction of total OI ⇒ bias == BALANCED
    bias_epsilon_frac: float = 0.01
    #: |DIFF in ΔOI| below this fraction of (|callΔ|+|putΔ|) ⇒ trace sentiment Neutral
    sentiment_epsilon_frac: float = 0.05
    #: minutes of grace past the session close for the last trace mark (closing-
    #: session prints land a few minutes after 15:30) — trace ends at 15:40 IST
    trace_end_grace_min: int = 10

    def hashable(self) -> dict:
        return {
            "recent_window_min": self.recent_window_min,
            "trace_step_min": self.trace_step_min,
            "price_epsilon_pct": self.price_epsilon_pct,
            "oi_epsilon_abs": self.oi_epsilon_abs,
            "bias_epsilon_frac": self.bias_epsilon_frac,
            "sentiment_epsilon_frac": self.sentiment_epsilon_frac,
            "trace_end_grace_min": self.trace_end_grace_min,
        }


@dataclass(frozen=True, slots=True)
class OiPulseLeg:
    option_type: str
    oi: int
    oi_at_open: int
    oi_change_session: int
    oi_change_session_pct: float | None
    oi_change_recent: int
    ltp: float | None
    price_at_open: float | None
    price_change_recent_pct: float | None
    price_change_session_pct: float | None
    buildup: str  # positioning over the *recent* window (OIBehavior value, or "NO_DATA")
    buildup_session: str  # positioning over the whole session (OI vs open, premium vs open)
    crowded: bool = False  # this strike carries an outsized share of its side's fresh OI


@dataclass(frozen=True, slots=True)
class OiPulseRow:
    strike: float
    call: OiPulseLeg | None
    put: OiPulseLeg | None


@dataclass(frozen=True, slots=True)
class OiTracePoint:
    """One time mark of the session's OI pulse (docs/05 §11.4).

    ``*_oi_change`` are cumulative since the session open; ``*_delta`` is the
    move versus the previous mark. ``diff_oi`` = put ΔOI − call ΔOI (negative =
    calls being written / puts unwinding faster → resistance-heavy).
    """

    ts: str  # ISO
    spot: float | None
    call_oi_change: int
    call_oi_change_delta: int
    put_oi_change: int
    put_oi_change_delta: int
    diff_oi: int
    diff_pct: float | None
    dir_of_change: int  # diff_oi − previous mark's diff_oi
    pcr_oi: float | None  # total put OI / total call OI at this mark
    coi_pcr: float | None  # put ΔOI / call ΔOI (change-in-OI PCR)
    vol_pcr: float | None  # cumulative put volume / call volume
    total_ce_oi: int
    total_pe_oi: int
    max_pain: float | None
    sentiment: str  # "Bullish" | "Bearish" | "Neutral"


@dataclass(frozen=True, slots=True)
class OiPulse:
    underlying_symbol: str
    spot: float
    expiry: str  # ISO date
    as_of: str  # ISO
    session_open: str  # ISO
    rows: tuple[OiPulseRow, ...]
    pcr_oi_now: float | None
    pcr_oi_open: float | None
    max_pain_now: float | None
    max_pain_open: float | None
    max_pain_shift: float | None
    support_strike: float | None
    resistance_strike: float | None
    total_ce_oi: int
    total_pe_oi: int
    net_ce_oi_change: int
    net_pe_oi_change: int
    bias: str
    crowded_side: str = "BALANCED"  # CALLS | PUTS | BALANCED — which side drew the fresh OI
    crowded_ce_strike: float | None = None
    crowded_pe_strike: float | None = None
    crowded_ce_frac: float | None = None  # hot strike's share of the call side's OI build
    crowded_pe_frac: float | None = None
    trace: tuple[OiTracePoint, ...] = ()
    trace_atm_strike: float | None = None
    trace_window_up: int | None = None  # strikes above ATM kept in the trace (None = all)
    trace_window_down: int | None = None  # strikes below ATM kept in the trace (None = all)
    algo_version: str = field(default=ALGO_VERSION)
    oi_pulse_version: str = field(default=OI_PULSE_VERSION)


# ----------------------------------------------------------------------------- helpers


def _at_or_before(series: tuple[tuple[datetime, float], ...], ts: datetime):
    """Value of the latest sample at/again before ``ts``; else the first sample; else None."""
    if not series:
        return None
    chosen = None
    for t, v in series:  # ascending
        if t <= ts:
            chosen = v
        else:
            break
    return chosen if chosen is not None else series[0][1]


def _last(series: tuple[tuple[datetime, float], ...]):
    return series[-1][1] if series else None


def _sum_at_or_before(series: tuple[tuple[datetime, float], ...], ts: datetime) -> float:
    """Running total of every sample at/again before ``ts`` (per-minute → session sum)."""
    return sum(v for t, v in series if t <= ts)


def _dir(delta: float, eps: float) -> Direction:
    if delta > eps:
        return Direction.UP
    if delta < -eps:
        return Direction.DOWN
    return Direction.FLAT


def _pcr(ce: int, pe: int) -> float | None:
    return round(pe / ce, 4) if ce else None


def _px_move(ltp, base, eps_pct: float):
    """(signed % change, Direction) of ``ltp`` vs ``base``; (None, FLAT) if no base."""
    if ltp is not None and base is not None and base > 0:
        return round((ltp - base) / base, 6), _dir(ltp - base, eps_pct * abs(base))
    return None, Direction.FLAT


# ----------------------------------------------------------------------------- build


def build_oi_pulse(
    *,
    underlying_symbol: str,
    spot: float,
    expiry,  # datetime.date
    now: datetime,
    session_open: datetime,
    legs: list[OiLegSeries],
    spot_series: tuple[tuple[datetime, float], ...] = (),
    session_close: datetime | None = None,
    trace_window_up: int | None = None,
    trace_window_down: int | None = None,
    config: OiPulseConfig | None = None,
) -> OiPulse:
    cfg = config or OiPulseConfig()
    recent_cut = now - timedelta(minutes=cfg.recent_window_min)

    by_strike: dict[float, dict[str, OiPulseLeg]] = {}
    oi_now_by: dict[str, dict[float, int]] = {_CE: {}, _PE: {}}
    oi_open_by: dict[str, dict[float, int]] = {_CE: {}, _PE: {}}

    for leg in legs:
        side = leg.option_type
        oi_now = int(_last(leg.oi) or 0)
        oi_open = int(_at_or_before(leg.oi, session_open) or (leg.oi[0][1] if leg.oi else 0))
        oi_recent = int(_at_or_before(leg.oi, recent_cut) or oi_open)
        ltp = _last(leg.premium)
        px_recent = _at_or_before(leg.premium, recent_cut)
        px_open = _at_or_before(leg.premium, session_open)

        oi_chg_session = oi_now - oi_open
        oi_chg_recent = oi_now - oi_recent
        oi_pct = round(oi_chg_session / oi_open, 4) if oi_open else None

        px_pct = px_pct_session = None
        buildup = buildup_session = "NO_DATA"
        if leg.oi:
            px_pct, price_dir = _px_move(ltp, px_recent, cfg.price_epsilon_pct)
            oi_dir = _dir(float(oi_chg_recent), cfg.oi_epsilon_abs)
            beh = classify_oi_behavior(price_dir, oi_dir)
            buildup = beh.value if isinstance(beh, OIBehavior) else str(beh)

            px_pct_session, price_dir_s = _px_move(ltp, px_open, cfg.price_epsilon_pct)
            oi_dir_s = _dir(float(oi_chg_session), cfg.oi_epsilon_abs)
            beh_s = classify_oi_behavior(price_dir_s, oi_dir_s)
            buildup_session = beh_s.value if isinstance(beh_s, OIBehavior) else str(beh_s)

        by_strike.setdefault(leg.strike, {})[side] = OiPulseLeg(
            option_type=side,
            oi=oi_now,
            oi_at_open=oi_open,
            oi_change_session=oi_chg_session,
            oi_change_session_pct=oi_pct,
            oi_change_recent=oi_chg_recent,
            ltp=round(ltp, 4) if ltp is not None else None,
            price_at_open=round(px_open, 4) if px_open is not None else None,
            price_change_recent_pct=px_pct,
            price_change_session_pct=px_pct_session,
            buildup=buildup,
            buildup_session=buildup_session,
        )
        oi_now_by[side][leg.strike] = oi_now
        oi_open_by[side][leg.strike] = oi_open

    # crowded read — which side drew the fresh OI, and each side's hottest strike
    ce_chg = {s: d[_CE].oi_change_session for s, d in by_strike.items() if _CE in d}
    pe_chg = {s: d[_PE].oi_change_session for s, d in by_strike.items() if _PE in d}
    cr = crowded_read(ce_chg, pe_chg)
    for s, side in ((cr.call_strike, _CE), (cr.put_strike, _PE)):
        if s is not None and s in by_strike and side in by_strike[s]:
            by_strike[s][side] = _dc_replace(by_strike[s][side], crowded=True)

    strikes = sorted(by_strike)
    rows = tuple(
        OiPulseRow(strike=s, call=by_strike[s].get(_CE), put=by_strike[s].get(_PE)) for s in strikes
    )

    tot_ce = sum(oi_now_by[_CE].values())
    tot_pe = sum(oi_now_by[_PE].values())
    tot_ce_open = sum(oi_open_by[_CE].values())
    tot_pe_open = sum(oi_open_by[_PE].values())

    mp_now = max_pain(strikes, oi_now_by[_CE], oi_now_by[_PE])
    mp_open = max_pain(strikes, oi_open_by[_CE], oi_open_by[_PE])
    mp_shift = round(mp_now - mp_open, 4) if (mp_now is not None and mp_open is not None) else None

    support = max(oi_now_by[_PE], key=oi_now_by[_PE].get, default=None) if oi_now_by[_PE] else None
    resistance = (
        max(oi_now_by[_CE], key=oi_now_by[_CE].get, default=None) if oi_now_by[_CE] else None
    )

    net_ce = sum(lg.call.oi_change_session for lg in rows if lg.call)
    net_pe = sum(lg.put.oi_change_session for lg in rows if lg.put)
    bias = _bias(net_ce, net_pe, tot_ce + tot_pe, cfg.bias_epsilon_frac)

    # the trace stops at the session close (+ a short grace for closing-session
    # prints, so ~15:40 IST) — after that it is fixed, one full set of marks;
    # only the strike ladder / LTP keep refreshing.
    trace_end = now
    if session_close is not None:
        trace_end = min(now, session_close + timedelta(minutes=cfg.trace_end_grace_min))

    # optionally cut the trace to an ATM band — N strikes above and/or below,
    # asymmetric (the ladder / top-level aggregates stay full-chain). A None side
    # means "no limit that way".
    atm = min(strikes, key=lambda s: abs(s - spot)) if strikes else None
    trace_legs = legs
    applied_up = applied_dn = None
    if (trace_window_up is not None or trace_window_down is not None) and atm is not None:
        gaps = sorted(
            {round(b - a, 6) for a, b in zip(strikes, strikes[1:], strict=False) if b > a}
        )
        step = gaps[0] if gaps else 0.0
        if step > 0.0:
            hi = atm + trace_window_up * step + step * 0.5 if trace_window_up is not None else None
            lo = (
                atm - trace_window_down * step - step * 0.5
                if trace_window_down is not None
                else None
            )
            trace_legs = [
                lg
                for lg in legs
                if (hi is None or lg.strike <= hi) and (lo is None or lg.strike >= lo)
            ]
            applied_up, applied_dn = trace_window_up, trace_window_down

    trace = _build_trace(trace_legs, session_open, trace_end, cfg, spot_series, spot)

    return OiPulse(
        underlying_symbol=underlying_symbol,
        spot=round(spot, 4),
        expiry=expiry.isoformat(),
        as_of=now.isoformat(),
        session_open=session_open.isoformat(),
        rows=rows,
        pcr_oi_now=_pcr(tot_ce, tot_pe),
        pcr_oi_open=_pcr(tot_ce_open, tot_pe_open),
        max_pain_now=mp_now,
        max_pain_open=mp_open,
        max_pain_shift=mp_shift,
        support_strike=support,
        resistance_strike=resistance,
        total_ce_oi=tot_ce,
        total_pe_oi=tot_pe,
        net_ce_oi_change=net_ce,
        net_pe_oi_change=net_pe,
        bias=bias,
        crowded_side=cr.side,
        crowded_ce_strike=cr.call_strike,
        crowded_pe_strike=cr.put_strike,
        crowded_ce_frac=cr.call_frac,
        crowded_pe_frac=cr.put_frac,
        trace=trace,
        trace_atm_strike=atm,
        trace_window_up=applied_up,
        trace_window_down=applied_dn,
    )


def _bias(net_ce: int, net_pe: int, total_oi: int, eps_frac: float) -> str:
    eps = eps_frac * total_oi
    dominant, sign_val = (_CE, net_ce) if abs(net_ce) >= abs(net_pe) else (_PE, net_pe)
    if sign_val == 0 or abs(sign_val) < max(eps, 1.0):
        return "BALANCED"
    if dominant == _CE:
        return "CALL_WRITING" if sign_val > 0 else "CALL_UNWINDING"
    return "PUT_WRITING" if sign_val > 0 else "PUT_UNWINDING"


def _ratio(num: float, den: float) -> float | None:
    return round(num / den, 4) if den else None


def _sentiment(diff_oi: float, ce_chg: float, pe_chg: float, eps_frac: float) -> str:
    eps = max(eps_frac * (abs(ce_chg) + abs(pe_chg)), 1.0)
    if diff_oi > eps:
        return "Bullish"  # puts written / calls unwound faster → support-heavy
    if diff_oi < -eps:
        return "Bearish"  # calls written / puts unwound faster → resistance-heavy
    return "Neutral"


def _build_trace(
    legs: list[OiLegSeries],
    session_open: datetime,
    end: datetime,
    cfg: OiPulseConfig,
    spot_series: tuple[tuple[datetime, float], ...],
    spot_now: float,
) -> tuple[OiTracePoint, ...]:
    if end <= session_open:
        return ()
    strikes = sorted({lg.strike for lg in legs})
    # each leg's open OI, captured once
    open_oi = {
        id(lg): int(_at_or_before(lg.oi, session_open) or (lg.oi[0][1] if lg.oi else 0))
        for lg in legs
    }

    marks: list[datetime] = []
    t = session_open
    step = timedelta(minutes=max(1, cfg.trace_step_min))
    while t < end:
        marks.append(t)
        t += step
    if not marks or marks[-1] != end:  # final mark at the cutoff (no duplicate)
        marks.append(end)

    out: list[OiTracePoint] = []
    prev_ce_chg = prev_pe_chg = prev_diff = 0
    for m in marks:
        ce_by: dict[float, int] = {}
        pe_by: dict[float, int] = {}
        ce_chg = pe_chg = 0
        ce_vol = pe_vol = 0.0
        any_data = False
        for lg in legs:
            v = _at_or_before(lg.oi, m)
            if v is None:
                continue
            if lg.oi[0][0] <= m:
                any_data = True
            oi_v = int(v)
            chg = oi_v - open_oi[id(lg)]
            vol = _sum_at_or_before(lg.volume, m)
            if lg.option_type == _CE:
                ce_by[lg.strike] = oi_v
                ce_chg += chg
                ce_vol += vol
            else:
                pe_by[lg.strike] = oi_v
                pe_chg += chg
                pe_vol += vol
        if not any_data:
            continue
        ce = sum(ce_by.values())
        pe = sum(pe_by.values())
        diff = pe_chg - ce_chg
        out.append(
            OiTracePoint(
                ts=m.isoformat(),
                spot=(
                    round(_at_or_before(spot_series, m), 4)
                    if spot_series and _at_or_before(spot_series, m) is not None
                    else (round(spot_now, 4) if m == end else None)
                ),
                call_oi_change=ce_chg,
                call_oi_change_delta=ce_chg - prev_ce_chg,
                put_oi_change=pe_chg,
                put_oi_change_delta=pe_chg - prev_pe_chg,
                diff_oi=diff,
                diff_pct=_ratio(diff, abs(ce_chg) + abs(pe_chg)),
                dir_of_change=diff - prev_diff,
                pcr_oi=_pcr(ce, pe),
                coi_pcr=_ratio(pe_chg, ce_chg),
                vol_pcr=_ratio(pe_vol, ce_vol),
                total_ce_oi=ce,
                total_pe_oi=pe,
                max_pain=max_pain(strikes, ce_by, pe_by),
                sentiment=_sentiment(diff, ce_chg, pe_chg, cfg.sentiment_epsilon_frac),
            )
        )
        prev_ce_chg, prev_pe_chg, prev_diff = ce_chg, pe_chg, diff
    return tuple(out)


# ----------------------------------------------------------------------------- serialise


def _slots(o) -> dict:
    return {s: getattr(o, s) for s in o.__slots__}


def oi_pulse_to_dict(p: OiPulse) -> dict:
    d = {k: v for k, v in _slots(p).items() if k not in ("rows", "trace")}
    d["rows"] = [
        {
            "strike": r.strike,
            "call": _slots(r.call) if r.call else None,
            "put": _slots(r.put) if r.put else None,
        }
        for r in p.rows
    ]
    d["trace"] = [_slots(t) for t in p.trace]
    return d
