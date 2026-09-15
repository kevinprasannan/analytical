"""Option-structure suggestions from open-interest positioning (docs/05 §11.5).

**Owner-authorised 2026-09-03 — a deliberate, bounded revision of decision 15 /
hard rule 7.** This module (and only this module) emits option structures that
carry per-leg ``BUY`` / ``SELL`` actions and quantity ratios. Every payload is
framed as *illustrative analytical output derived from OI* — **not** investment
advice, **not** a recommendation, **not** an order — and every payload carries
:data:`DISCLAIMER`. The rest of the system stays non-execution: the scoring
engine still emits only the analytical labels ``STRONG_BEARISH … STRONG_BULLISH``.

Pure and deterministic: per-strike OI / dOI / LTP + spot + expiry + ``now`` in,
a :class:`StrategyBook` out. No IO, no charts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime

from analytical_core.options.chain import crowded_read, max_pain
from analytical_core.versioning import ALGO_VERSION

DISCLAIMER = (
    "Illustrative structures derived from open-interest positioning. Not investment "
    "advice, not a recommendation, not an order. Strikes, ratios and P/L are "
    "approximate and ignore costs, margin, liquidity, slippage and assignment risk."
)

VIEWS = (
    "RANGEBOUND",
    "LEAN_BULLISH",
    "LEAN_BEARISH",
    "TREND_BULLISH",
    "TREND_BEARISH",
    "VOL_EXPANSION",
)


@dataclass(frozen=True, slots=True)
class StrikeQuote:
    strike: float
    ce_oi: int | None = None
    ce_oi_change: int | None = None
    ce_ltp: float | None = None
    pe_oi: int | None = None
    pe_oi_change: int | None = None
    pe_ltp: float | None = None


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    wing_steps: int = 2  # strikes from a short leg out to its protective wing
    wing_points: float | None = None  # if set, wing width = this many index points instead
    max_suggestions: int = 8
    dominance: float = 1.3  # crowded-side test (one side's build beats the other xthis)
    neutral_pcr_lo: float = 0.90
    neutral_pcr_hi: float = 1.10
    tilt_pcr_lo: float = 0.85
    tilt_pcr_hi: float = 1.15
    near_expiry_days: int = 2
    rank_by_edge: bool = True  # order by pop x reward_risk (desc), best edge first
    high_pop: float = 0.70  # flag suggestions with pop >= this
    min_reward_risk: float = 0.0  # drop defined-risk suggestions below this (0 = keep all)

    def hashable(self) -> tuple:
        return (
            self.wing_steps,
            self.wing_points,
            self.max_suggestions,
            self.dominance,
            self.neutral_pcr_lo,
            self.neutral_pcr_hi,
            self.tilt_pcr_lo,
            self.tilt_pcr_hi,
            self.near_expiry_days,
            self.rank_by_edge,
            self.high_pop,
            self.min_reward_risk,
        )


@dataclass(frozen=True, slots=True)
class MarketView:
    label: str  # one of VIEWS
    confidence: float  # 0..1
    evidence: tuple[str, ...]
    spot: float
    atm_strike: float
    step: float
    support_wall: float | None  # strike carrying the most put OI
    resistance_wall: float | None  # strike carrying the most call OI
    max_pain: float | None
    pcr_oi: float | None
    net_ce_oi_change: int
    net_pe_oi_change: int
    crowded_side: str
    days_to_expiry: int


@dataclass(frozen=True, slots=True)
class StrategyLeg:
    action: str  # BUY | SELL
    lots: int  # relative quantity (the ratio)
    option_type: str  # CE | PE
    strike: float
    role: str  # short_body | long_wing | long_leg | short_leg
    ltp: float | None
    oi: int | None
    oi_change: int | None
    expiry: str | None = None  # ISO date; None => the book's near expiry (calendars only)


@dataclass(frozen=True, slots=True)
class StrategySuggestion:
    name: str
    family: str  # CONDOR_FLY | STRANGLE_STRADDLE | VERTICAL | RATIO | CALENDAR
    view: str
    direction_bias: str  # NEUTRAL | BULLISH | BEARISH
    risk: str  # DEFINED | UNDEFINED
    net: str  # CREDIT | DEBIT | UNKNOWN
    legs: tuple[StrategyLeg, ...]
    est_net_premium: float | None  # + credit received / - debit paid, index points, 1x set
    breakevens: tuple[float, ...]
    lower_breakeven: float | None  # min(breakevens)
    upper_breakeven: float | None  # max(breakevens) when there are two
    spot_inside_breakevens: bool | None  # spot within [lower, upper] (two-sided only)
    max_profit: float | None  # index points; None => unbounded / undefined
    max_loss: float | None
    reward_risk: float | None  # max_profit / |max_loss| when both defined
    pop: float | None  # probability of profit at expiry (lognormal, ATM IV)
    pop_basis: str  # LOGNORMAL_IV | LOGNORMAL_NEAR_RANGE | NONE
    edge_score: float | None  # pop x reward_risk — the ranking key
    high_pop: bool  # pop >= config.high_pop
    rationale: str
    caveats: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StrategyBook:
    underlying_symbol: str
    spot: float
    expiry: str  # ISO date
    days_to_expiry: int
    view: MarketView
    suggestions: tuple[StrategySuggestion, ...]
    atm_iv: float | None = None  # the vol the lognormal PoP used
    far_expiry: str | None = None  # the second expiry loaded for calendars (if any)
    ranked_by: str = "OI_VIEW"  # EDGE (pop x reward_risk) | OI_VIEW
    disclaimer: str = DISCLAIMER
    algo_version: str = field(default=ALGO_VERSION)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _infer_step(strikes: list[float]) -> float:
    diffs = [b - a for a, b in zip(strikes, strikes[1:], strict=False) if b - a > 0]
    return min(diffs) if diffs else 1.0


def _nearest(strikes: list[float], target: float) -> float:
    return min(strikes, key=lambda s: abs(s - target))


def _leg(
    action: str,
    lots: int,
    opt: str,
    strike: float,
    role: str,
    by_strike: dict[float, StrikeQuote],
    *,
    expiry: str | None = None,
) -> StrategyLeg:
    q = by_strike.get(strike)
    ltp = oi = oic = None
    if q is not None:
        if opt == "CE":
            ltp, oi, oic = q.ce_ltp, q.ce_oi, q.ce_oi_change
        else:
            ltp, oi, oic = q.pe_ltp, q.pe_oi, q.pe_oi_change
    return StrategyLeg(
        action=action,
        lots=lots,
        option_type=opt,
        strike=round(strike, 4),
        role=role,
        ltp=round(ltp, 4) if ltp is not None else None,
        oi=oi,
        oi_change=oic,
        expiry=expiry,
    )


def _net_premium(legs: tuple[StrategyLeg, ...]) -> float | None:
    """+ = net credit received, - = net debit paid, per one lot-set (index points)."""
    total = 0.0
    for lg in legs:
        if lg.ltp is None:
            return None
        total += lg.ltp * lg.lots * (1.0 if lg.action == "SELL" else -1.0)
    return round(total, 2)


# --- probability of profit (lognormal on the ATM IV) ------------------------


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _lognormal_cdf(s: float, s0: float, iv: float, t: float, r: float) -> float:
    """P(price_at_expiry <= s) under a lognormal with drift r and vol ``iv``."""
    if s <= 0.0:
        return 0.0
    if s0 <= 0.0 or iv <= 0.0 or t <= 0.0:
        return 1.0 if s >= s0 else 0.0
    mu = math.log(s0) + (r - 0.5 * iv * iv) * t
    sd = iv * math.sqrt(t)
    return _norm_cdf((math.log(s) - mu) / sd)


def _expiry_pnl(legs: tuple[StrategyLeg, ...], s: float) -> float | None:
    """Net P/L at *this book's* expiry for underlying price ``s`` — only valid
    when every leg settles at the same expiry (not calendars)."""
    prem = _net_premium(legs)
    if prem is None:
        return None
    pnl = prem
    for lg in legs:
        intrinsic = (s - lg.strike) if lg.option_type == "CE" else (lg.strike - s)
        intrinsic = max(0.0, intrinsic)
        pnl += lg.lots * intrinsic * (1.0 if lg.action == "BUY" else -1.0)
    return pnl


def _pop_at_expiry(
    legs: tuple[StrategyLeg, ...], spot: float, iv: float | None, t: float, r: float
) -> float | None:
    """Integrate the lognormal density over the price region where the
    piecewise-linear expiry payoff is positive. Same-expiry structures only."""
    if iv is None or iv <= 0.0 or t <= 0.0:
        return None
    if any(lg.expiry is not None for lg in legs):  # a calendar — handled elsewhere
        return None
    lo = spot * math.exp(-8.0 * iv * math.sqrt(t))
    hi = spot * math.exp(8.0 * iv * math.sqrt(t))
    pts = sorted({lo, hi, *(lg.strike for lg in legs)})
    pop = 0.0
    for a, b in zip(pts, pts[1:], strict=False):
        pa, pb = _expiry_pnl(legs, a), _expiry_pnl(legs, b)
        if pa is None or pb is None:
            return None
        segs: list[tuple[float, float]] = []
        if pa > 0 and pb > 0:
            segs.append((a, b))
        elif pa > 0 >= pb:
            segs.append((a, a + (b - a) * pa / (pa - pb)))
        elif pb > 0 >= pa:
            segs.append((a + (b - a) * pa / (pa - pb), b))
        for x0, x1 in segs:
            pop += _lognormal_cdf(x1, spot, iv, t, r) - _lognormal_cdf(x0, spot, iv, t, r)
    return max(0.0, min(1.0, round(pop, 4)))


def _classify(v: dict, cfg: StrategyConfig) -> tuple[str, float, list[str]]:
    """Score the six views off the OI evidence; return (label, confidence, why)."""
    spot = v["spot"]
    step = v["step"]
    pcr = v["pcr"]
    mp = v["max_pain"]
    net_ce = v["net_ce"]
    net_pe = v["net_pe"]
    sup = v["support_wall"]
    res = v["resistance_wall"]
    crowded = v["crowded_side"]
    dte = v["dte"]

    score = dict.fromkeys(VIEWS, 0.0)
    why: list[str] = []

    # --- option-writing flow (dOI) — the "what's happening now" signal, weighted high ---
    if net_ce < 0 and net_pe > 0:
        score["TREND_BULLISH"] += 2.0
        score["LEAN_BULLISH"] += 0.5
        why.append("calls unwinding while puts are written — directional up")
    elif net_pe < 0 and net_ce > 0:
        score["TREND_BEARISH"] += 2.0
        score["LEAN_BEARISH"] += 0.5
        why.append("puts unwinding while calls are written — directional down")
    elif net_ce < 0 and net_pe < 0:
        score["VOL_EXPANSION"] += 2.0
        why.append("OI coming off both sides — positioning unwinding")
    elif net_ce > 0 and net_pe > 0 and min(net_ce, net_pe) >= 0.45 * max(net_ce, net_pe):
        score["RANGEBOUND"] += 1.5
        why.append("both sides adding OI — two-way writing")
    elif net_pe > net_ce >= 0:
        score["LEAN_BULLISH"] += 1.25
        why.append(f"net put writing (+{net_pe:,} dOI vs calls {net_ce:+,})")
    elif net_ce > net_pe >= 0:
        score["LEAN_BEARISH"] += 1.25
        why.append(f"net call writing (+{net_ce:,} dOI vs puts {net_pe:+,})")

    # --- PCR level (positional, weighted low) ---
    if pcr is not None:
        if pcr >= cfg.tilt_pcr_hi:
            score["LEAN_BULLISH"] += 0.75
            why.append(f"PCR(OI) {pcr:.2f} — put-heavy")
        elif pcr <= cfg.tilt_pcr_lo:
            score["LEAN_BEARISH"] += 0.75
            why.append(f"PCR(OI) {pcr:.2f} — call-heavy")
        elif cfg.neutral_pcr_lo <= pcr <= cfg.neutral_pcr_hi:
            score["RANGEBOUND"] += 0.75
            why.append(f"PCR(OI) {pcr:.2f} — balanced")

    # --- max pain vs spot (positional, weighted low) ---
    if mp is not None and step > 0:
        steps = (mp - spot) / step
        if steps <= -2:
            score["LEAN_BEARISH"] += 0.75
            why.append(f"max-pain {mp:g} sits {abs(steps):.0f} strikes below spot")
        elif steps >= 2:
            score["LEAN_BULLISH"] += 0.75
            why.append(f"max-pain {mp:g} sits {steps:.0f} strikes above spot")
        elif abs(steps) <= 1:
            score["RANGEBOUND"] += 0.75
            why.append(f"max-pain {mp:g} near spot")
        if dte <= cfg.near_expiry_days and abs(steps) >= 3:
            score["VOL_EXPANSION"] += 1.5
            why.append(f"{dte}d to expiry and spot {abs(steps):.0f} strikes off max-pain")

    # --- crowded side (concentration of fresh OI) ---
    if crowded == "PUTS":
        score["LEAN_BULLISH"] += 0.5
    elif crowded == "CALLS":
        score["LEAN_BEARISH"] += 0.5

    # --- walls bracket spot ---
    if sup is not None and res is not None and sup < spot < res and (res - sup) >= 2 * step:
        score["RANGEBOUND"] += 1.0
        why.append(f"OI walls {sup:g} / {res:g} bracket spot")

    label = max(score, key=lambda k: score[k])
    if score[label] == 0:
        return "RANGEBOUND", 0.2, ["no strong OI signal — defaulting to a neutral read"]

    # a decisive directional / expansion flow signal overrides a positional read
    for flow in ("TREND_BULLISH", "TREND_BEARISH", "VOL_EXPANSION"):
        if score[flow] >= 2.0 and score[flow] >= score[label] - 0.75:
            label = flow
            break
    else:
        # a clean one-sided write beats a merely-neutral positional read
        if label == "RANGEBOUND":
            lean = max(("LEAN_BULLISH", "LEAN_BEARISH"), key=lambda k: score[k])
            if score[lean] >= 1.5 and score[lean] >= score["RANGEBOUND"] - 0.25:
                label = lean

    conf = max(0.2, min(0.95, score[label] / 4.0))
    return label, round(conf, 2), why


# ---------------------------------------------------------------------------
# strategy templates
# ---------------------------------------------------------------------------


def _pl_vertical_credit(width: float, credit: float | None) -> tuple[float | None, float | None]:
    if credit is None:
        return None, None
    return round(credit, 2), round(width - credit, 2)


def _pl_vertical_debit(width: float, debit: float | None) -> tuple[float | None, float | None]:
    if debit is None:  # debit is a positive number here
        return None, None
    return round(width - debit, 2), round(debit, 2)


def _suggestions(
    mv: MarketView,
    by_strike: dict[float, StrikeQuote],
    cfg: StrategyConfig,
    *,
    atm_iv: float | None = None,
    t_years: float = 0.0,
    risk_free_rate: float = 0.065,
    far_by_strike: dict[float, StrikeQuote] | None = None,
    far_expiry: str | None = None,
):
    strikes = sorted(by_strike)
    step = mv.step
    atm = mv.atm_strike
    wing = cfg.wing_points if cfg.wing_points is not None else cfg.wing_steps * step
    res = mv.resistance_wall if mv.resistance_wall and mv.resistance_wall > atm else atm + 2 * step
    sup = mv.support_wall if mv.support_wall and mv.support_wall < atm else atm - 2 * step
    res = _nearest(strikes, res)
    sup = _nearest(strikes, sup)
    res_w = _nearest(strikes, res + wing)
    sup_w = _nearest(strikes, sup - wing)
    near_expiry = mv.days_to_expiry <= cfg.near_expiry_days
    exp_cav = (
        (f"{mv.days_to_expiry}d to expiry — gamma / pin risk elevated",) if near_expiry else ()
    )

    def L(action, lots, opt, strike, role):
        return _leg(action, lots, opt, strike, role, by_strike)

    out: list[StrategySuggestion] = []

    def add(
        name,
        family,
        bias,
        risk,
        legs,
        *,
        rationale,
        breakevens=(),
        max_profit=None,
        max_loss=None,
        extra_caveats=(),
        pop=None,
        pop_basis="NONE",
    ):
        legs = tuple(legs)
        prem = _net_premium(legs)
        net = "UNKNOWN" if prem is None else ("CREDIT" if prem >= 0 else "DEBIT")
        cav = tuple(extra_caveats) + exp_cav
        if prem is None:
            cav = (*cav, "LTP unavailable for some legs — premium & P/L not computed")
        if risk == "UNDEFINED":
            cav = ("Undefined loss beyond the short strike(s) — margin-heavy", *cav)
        bes = tuple(round(b, 2) for b in breakevens)
        lower = min(bes) if bes else None
        upper = max(bes) if len(bes) >= 2 else None
        inside = (lower <= mv.spot <= upper) if (lower is not None and upper is not None) else None
        rr = (
            round(max_profit / abs(max_loss), 2)
            if (max_profit is not None and max_loss not in (None, 0))
            else None
        )
        if pop is None:
            pop = _pop_at_expiry(legs, mv.spot, atm_iv, t_years, risk_free_rate)
            pop_basis = "LOGNORMAL_IV" if pop is not None else "NONE"
        edge = round(pop * rr, 3) if (pop is not None and rr is not None) else None
        out.append(
            StrategySuggestion(
                name=name,
                family=family,
                view=mv.label,
                direction_bias=bias,
                risk=risk,
                net=net,
                legs=legs,
                est_net_premium=prem,
                breakevens=bes,
                lower_breakeven=lower,
                upper_breakeven=upper,
                spot_inside_breakevens=inside,
                max_profit=max_profit,
                max_loss=max_loss,
                reward_risk=rr,
                pop=pop,
                pop_basis=pop_basis,
                edge_score=edge,
                high_pop=bool(pop is not None and pop >= cfg.high_pop),
                rationale=rationale,
                caveats=cav,
            )
        )

    call_w = abs(res_w - res)
    put_w = abs(sup - sup_w)

    if mv.label == "RANGEBOUND":
        legs = [
            L("SELL", 1, "PE", sup, "short_leg"),
            L("BUY", 1, "PE", sup_w, "long_wing"),
            L("SELL", 1, "CE", res, "short_leg"),
            L("BUY", 1, "CE", res_w, "long_wing"),
        ]
        credit = _net_premium(tuple(legs))
        mp_, ml_ = _pl_vertical_credit(max(call_w, put_w), credit)
        add(
            "IRON_CONDOR",
            "CONDOR_FLY",
            "NEUTRAL",
            "DEFINED",
            legs,
            rationale=(
                f"OI walls {sup:g}/{res:g} bracket spot ({mv.spot:g}); "
                f"PCR {mv.pcr_oi:.2f}, max-pain {mv.max_pain:g}. Sell the walls, "
                f"buy {cfg.wing_steps}-strike wings."
            ),
            breakevens=(sup - (credit or 0), res + (credit or 0)),
            max_profit=mp_,
            max_loss=ml_,
        )
        legs = [
            L("SELL", 1, "PE", atm, "short_body"),
            L("SELL", 1, "CE", atm, "short_body"),
            L("BUY", 1, "PE", sup_w, "long_wing"),
            L("BUY", 1, "CE", res_w, "long_wing"),
        ]
        credit = _net_premium(tuple(legs))
        mp_, ml_ = _pl_vertical_credit(max(abs(res_w - atm), abs(atm - sup_w)), credit)
        add(
            "IRON_FLY",
            "CONDOR_FLY",
            "NEUTRAL",
            "DEFINED",
            legs,
            rationale=(
                f"Max-pain {mv.max_pain:g} near spot and two-way writing — sell the ATM "
                f"straddle, cap it with wings near the {sup:g}/{res:g} walls."
            ),
            breakevens=(atm - (credit or 0), atm + (credit or 0)),
            max_profit=mp_,
            max_loss=ml_,
        )
        legs = [L("SELL", 1, "PE", sup, "short_leg"), L("SELL", 1, "CE", res, "short_leg")]
        credit = _net_premium(tuple(legs))
        add(
            "SHORT_STRANGLE",
            "STRANGLE_STRADDLE",
            "NEUTRAL",
            "UNDEFINED",
            legs,
            rationale=f"Range conviction — sell the {sup:g}/{res:g} OI walls bare for max theta.",
            breakevens=(sup - (credit or 0), res + (credit or 0)),
            max_profit=credit if credit is not None else None,
        )

    elif mv.label in ("LEAN_BULLISH", "TREND_BULLISH"):
        short_p = _nearest(
            strikes, atm if mv.label == "TREND_BULLISH" else max(sup + step, atm - step)
        )
        long_p = _nearest(strikes, short_p - wing)
        legs = [
            L("SELL", 1, "PE", short_p, "short_leg"),
            L("BUY", 1, "PE", long_p, "long_wing"),
        ]
        credit = _net_premium(tuple(legs))
        mp_, ml_ = _pl_vertical_credit(abs(short_p - long_p), credit)
        add(
            "BULL_PUT_SPREAD",
            "VERTICAL",
            "BULLISH",
            "DEFINED",
            legs,
            rationale=(
                f"Put writing / support at {mv.support_wall or sup:g}; sell the {short_p:g} put, "
                f"buy the {long_p:g} for defined risk."
            ),
            breakevens=(short_p - (credit or 0),),
            max_profit=mp_,
            max_loss=ml_,
        )
        near_c = _nearest(strikes, atm)
        far_c = _nearest(strikes, res)
        legs = [
            L("BUY", 1, "CE", near_c, "long_leg"),
            L("SELL", 2, "CE", far_c, "short_leg"),
        ]
        prem = _net_premium(tuple(legs))
        add(
            "CALL_RATIO_SPREAD_1X2",
            "RATIO",
            "BULLISH",
            "UNDEFINED",
            legs,
            rationale=(
                f"Mild-up view — buy 1 ATM {near_c:g} call, sell 2 at the {far_c:g} call wall "
                "(the extra short is naked)."
            ),
            breakevens=(far_c + (far_c - near_c) + (prem or 0),),
            extra_caveats=(f"Naked short call past {far_c:g} — undefined upside risk",),
        )
        if mv.label == "TREND_BULLISH":
            long_c = _nearest(strikes, atm)
            sell_c = _nearest(strikes, res)
            legs = [
                L("BUY", 1, "CE", long_c, "long_leg"),
                L("SELL", 1, "CE", sell_c, "short_leg"),
            ]
            debit = _net_premium(tuple(legs))
            mp_, ml_ = _pl_vertical_debit(
                abs(sell_c - long_c), -debit if debit is not None else None
            )
            add(
                "BULL_CALL_SPREAD",
                "VERTICAL",
                "BULLISH",
                "DEFINED",
                legs,
                rationale=(
                    f"Directional up — buy the {long_c:g} call, sell the {sell_c:g} wall to fund."
                ),
                breakevens=(long_c + (-debit if debit is not None else 0),),
                max_profit=mp_,
                max_loss=ml_,
            )

    elif mv.label in ("LEAN_BEARISH", "TREND_BEARISH"):
        short_c = _nearest(
            strikes, atm if mv.label == "TREND_BEARISH" else min(res - step, atm + step)
        )
        long_c = _nearest(strikes, short_c + wing)
        legs = [
            L("SELL", 1, "CE", short_c, "short_leg"),
            L("BUY", 1, "CE", long_c, "long_wing"),
        ]
        credit = _net_premium(tuple(legs))
        mp_, ml_ = _pl_vertical_credit(abs(long_c - short_c), credit)
        add(
            "BEAR_CALL_SPREAD",
            "VERTICAL",
            "BEARISH",
            "DEFINED",
            legs,
            rationale=(
                f"Call writing / resistance at {mv.resistance_wall or res:g}; sell the {short_c:g} "
                f"call, buy the {long_c:g} for defined risk."
            ),
            breakevens=(short_c + (credit or 0),),
            max_profit=mp_,
            max_loss=ml_,
        )
        near_p = _nearest(strikes, atm)
        far_p = _nearest(strikes, sup)
        legs = [
            L("BUY", 1, "PE", near_p, "long_leg"),
            L("SELL", 2, "PE", far_p, "short_leg"),
        ]
        prem = _net_premium(tuple(legs))
        add(
            "PUT_RATIO_SPREAD_1X2",
            "RATIO",
            "BEARISH",
            "UNDEFINED",
            legs,
            rationale=(
                f"Mild-down view — buy 1 ATM {near_p:g} put, sell 2 at the {far_p:g} put wall "
                "(the extra short is naked)."
            ),
            breakevens=(far_p - (near_p - far_p) - (prem or 0),),
            extra_caveats=(f"Naked short put past {far_p:g} — large downside risk",),
        )
        if mv.label == "TREND_BEARISH":
            long_p = _nearest(strikes, atm)
            sell_p = _nearest(strikes, sup)
            legs = [
                L("BUY", 1, "PE", long_p, "long_leg"),
                L("SELL", 1, "PE", sell_p, "short_leg"),
            ]
            debit = _net_premium(tuple(legs))
            mp_, ml_ = _pl_vertical_debit(
                abs(long_p - sell_p), -debit if debit is not None else None
            )
            add(
                "BEAR_PUT_SPREAD",
                "VERTICAL",
                "BEARISH",
                "DEFINED",
                legs,
                rationale=(
                    f"Directional down — buy the {long_p:g} put, sell the {sell_p:g} wall to fund."
                ),
                breakevens=(long_p - (-debit if debit is not None else 0),),
                max_profit=mp_,
                max_loss=ml_,
            )

    elif mv.label == "VOL_EXPANSION":
        legs = [L("BUY", 1, "CE", atm, "long_leg"), L("BUY", 1, "PE", atm, "long_leg")]
        debit = _net_premium(tuple(legs))
        add(
            "LONG_STRADDLE",
            "STRANGLE_STRADDLE",
            "NEUTRAL",
            "DEFINED",
            legs,
            rationale=(
                "Positioning unwinding / spot far from max-pain — buy the ATM straddle for a break "
                "either way."
            ),
            breakevens=((atm + debit, atm - debit) if debit is not None else ()),
            max_loss=(-debit if debit is not None else None),
        )
        c = _nearest(strikes, atm + wing)
        p = _nearest(strikes, atm - wing)
        legs = [L("BUY", 1, "CE", c, "long_leg"), L("BUY", 1, "PE", p, "long_leg")]
        debit = _net_premium(tuple(legs))
        add(
            "LONG_STRANGLE",
            "STRANGLE_STRADDLE",
            "NEUTRAL",
            "DEFINED",
            legs,
            rationale=f"Cheaper expansion play — buy the {p:g} put and {c:g} call OTM.",
            breakevens=((c + debit, p - debit) if debit is not None else ()),
            max_loss=(-debit if debit is not None else None),
        )

    # --- calendars: only on a range read, and only with a second expiry loaded ---
    if (
        far_by_strike
        and far_expiry
        and mv.label in ("RANGEBOUND", "LEAN_BULLISH", "LEAN_BEARISH")
    ):
        far_atm = _nearest(sorted(far_by_strike), atm)
        for opt, near_lvl in (("CE", res), ("PE", sup)):
            k = atm if mv.label == "RANGEBOUND" else _nearest(strikes, near_lvl)
            fk = _nearest(sorted(far_by_strike), k)
            legs = [
                _leg("SELL", 1, opt, k, "short_leg", by_strike),
                _leg("BUY", 1, opt, fk, "long_leg", far_by_strike, expiry=far_expiry),
            ]
            debit = _net_premium(tuple(legs))  # usually negative (a net debit)
            # profit if price sits near k at the near expiry — approximate with the
            # lognormal probability of finishing within ±wing of k at t_near.
            pop_cal = None
            if atm_iv and t_years > 0:
                lo = _lognormal_cdf(k - wing, mv.spot, atm_iv, t_years, risk_free_rate)
                hi = _lognormal_cdf(k + wing, mv.spot, atm_iv, t_years, risk_free_rate)
                pop_cal = round(max(0.0, min(1.0, hi - lo)), 4)
            add(
                f"{'CALL' if opt == 'CE' else 'PUT'}_CALENDAR",
                "CALENDAR",
                "NEUTRAL",
                "DEFINED",
                legs,
                rationale=(
                    f"Range read — sell the {k:g} {opt} of the near expiry, buy the same "
                    f"strike of {far_expiry} to be long time-value. Profits if price sits "
                    f"near {k:g} into the near expiry."
                ),
                breakevens=(),  # depends on far IV at near expiry — not a clean expiry line
                max_loss=(round(abs(debit), 2) if debit is not None and debit < 0 else None),
                max_profit=None,
                pop=pop_cal,
                pop_basis="LOGNORMAL_NEAR_RANGE" if pop_cal is not None else "NONE",
                extra_caveats=(
                    "Two expiries — P/L at the near expiry depends on the far leg's IV then; "
                    "max profit is not a fixed number.",
                ),
            )

    # --- rank + filter -----------------------------------------------------
    if cfg.min_reward_risk > 0:
        out = [
            s for s in out if s.reward_risk is None or s.reward_risk >= cfg.min_reward_risk
        ]
    if cfg.rank_by_edge:
        out.sort(key=lambda s: (s.edge_score is not None, s.edge_score or 0.0), reverse=True)
    return out[: cfg.max_suggestions]


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def build_strategy_book(
    *,
    underlying_symbol: str,
    quotes: list[StrikeQuote],
    spot: float,
    expiry: date,
    now: datetime,
    config: StrategyConfig | None = None,
    atm_iv: float | None = None,  # annualised, fraction — for the lognormal PoP
    t_years: float = 0.0,  # time to the near expiry, years
    risk_free_rate: float = 0.065,
    far_quotes: list[StrikeQuote] | None = None,  # a second (later) expiry — enables calendars
    far_expiry: date | None = None,
) -> StrategyBook:
    cfg = config or StrategyConfig()
    by_strike = {round(q.strike, 4): q for q in quotes}
    strikes = sorted(by_strike)
    if not strikes:
        raise ValueError("no strikes")
    far_by_strike = (
        {round(q.strike, 4): q for q in far_quotes} if far_quotes and far_expiry else None
    )

    step = _infer_step(strikes)
    atm = _nearest(strikes, spot)
    ce_oi = {s: (by_strike[s].ce_oi or 0) for s in strikes}
    pe_oi = {s: (by_strike[s].pe_oi or 0) for s in strikes}
    ce_chg = {s: (by_strike[s].ce_oi_change or 0) for s in strikes}
    pe_chg = {s: (by_strike[s].pe_oi_change or 0) for s in strikes}
    tot_ce = sum(ce_oi.values())
    tot_pe = sum(pe_oi.values())
    pcr = round(tot_pe / tot_ce, 4) if tot_ce else None
    support = max(pe_oi, key=lambda k: pe_oi[k]) if any(pe_oi.values()) else None
    resistance = max(ce_oi, key=lambda k: ce_oi[k]) if any(ce_oi.values()) else None
    mp = max_pain(strikes, ce_oi, pe_oi)
    net_ce = sum(ce_chg.values())
    net_pe = sum(pe_chg.values())
    crowded = crowded_read(ce_chg, pe_chg, dominance=cfg.dominance)
    dte = max(0, (expiry - now.date()).days)

    label, conf, why = _classify(
        {
            "spot": spot,
            "step": step,
            "pcr": pcr,
            "max_pain": mp,
            "net_ce": net_ce,
            "net_pe": net_pe,
            "support_wall": support,
            "resistance_wall": resistance,
            "crowded_side": crowded.side,
            "dte": dte,
        },
        cfg,
    )
    view = MarketView(
        label=label,
        confidence=conf,
        evidence=tuple(why),
        spot=round(spot, 4),
        atm_strike=atm,
        step=step,
        support_wall=support,
        resistance_wall=resistance,
        max_pain=mp,
        pcr_oi=pcr,
        net_ce_oi_change=net_ce,
        net_pe_oi_change=net_pe,
        crowded_side=crowded.side,
        days_to_expiry=dte,
    )
    suggestions = tuple(
        _suggestions(
            view,
            by_strike,
            cfg,
            atm_iv=atm_iv,
            t_years=t_years,
            risk_free_rate=risk_free_rate,
            far_by_strike=far_by_strike,
            far_expiry=far_expiry.isoformat() if far_expiry else None,
        )
    )
    return StrategyBook(
        underlying_symbol=underlying_symbol,
        spot=round(spot, 4),
        expiry=expiry.isoformat(),
        days_to_expiry=dte,
        view=view,
        suggestions=suggestions,
        atm_iv=round(atm_iv, 6) if atm_iv is not None else None,
        far_expiry=far_expiry.isoformat() if far_expiry else None,
        ranked_by="EDGE" if cfg.rank_by_edge else "OI_VIEW",
    )


def strategy_book_to_dict(book: StrategyBook) -> dict:
    """Plain nested dict for API serialisation (tuples -> lists)."""
    from dataclasses import asdict

    return asdict(book)
