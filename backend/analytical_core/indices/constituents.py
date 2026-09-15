"""Index constituents: weightage, contribution, breadth, beta/correlation.

Pure and deterministic — takes the seeded weight rows plus (optionally) a quote
per name and a short close history, returns a :class:`ConstituentView`. No IO,
no charts. Descriptive: it explains *which names carry the index today* and
*how tightly each tracks it* — it is not a signal and emits no BUY/SELL.

Contribution model (approximate, price-return only): a constituent with
free-float weight ``w`` (percent) that moved ``r`` percent on the day adds
``w * r / 100`` **index percent** to the move, i.e. ``Σ contribution_pct`` ≈ the
index's own change %. Multiplied by the index's previous close it becomes index
points. It ignores the divisor, corporate actions and intraday weight drift.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

INDEX_CONSTITUENTS_VERSION = "0.1.0"


@dataclass(frozen=True, slots=True)
class WeightRow:
    symbol: str
    name: str
    sector: str
    weight_pct: float  # free-float index weight, percent (0..100)


@dataclass(frozen=True, slots=True)
class ConstituentQuote:
    symbol: str
    ltp: float | None = None
    prev_close: float | None = None


@dataclass(frozen=True, slots=True)
class Constituent:
    symbol: str
    name: str
    sector: str
    rank: int  # 1 = heaviest weight
    weight_pct: float
    cumulative_weight_pct: float  # running Σ down the weight-sorted list
    ltp: float | None
    prev_close: float | None
    change_pct: float | None
    contribution_pct: float | None  # index percent added by this name today
    contribution_points: float | None  # ≈ index points (needs index prev close)
    contribution_rank: int | None  # 1 = most positive contribution
    abs_contribution_rank: int | None  # 1 = biggest mover of the index either way
    beta: float | None  # vs the index, over the supplied history
    correlation: float | None
    r_squared: float | None


@dataclass(frozen=True, slots=True)
class Concentration:
    top1_pct: float
    top5_pct: float
    top10_pct: float
    hhi: float  # Herfindahl on weight fractions (0..1); ~0.02 = evenly spread


@dataclass(frozen=True, slots=True)
class SectorWeight:
    sector: str
    weight_pct: float
    count: int
    contribution_pct: float | None  # sector's share of today's index move, index %
    contribution_points: float | None  # ... and in index points


@dataclass(frozen=True, slots=True)
class Breadth:
    covered: int  # names with a usable quote
    advances: int
    declines: int
    unchanged: int
    up_weight_pct: float  # Σ weight of advancing names
    down_weight_pct: float
    advance_decline_weight: float  # up_weight_pct − down_weight_pct
    net_contribution_pct: float | None  # Σ contribution_pct (≈ index change %)
    net_contribution_points: float | None  # Σ contribution_points (≈ index points today)
    top5_move_share: float | None  # |Σ top-5 contribution| / Σ|contribution| (0..1)


@dataclass(frozen=True, slots=True)
class BetaCorr:
    n: int
    beta: float
    correlation: float
    r_squared: float
    alpha_daily: float  # mean stock return − beta·mean index return


@dataclass(frozen=True, slots=True)
class ConstituentView:
    index_symbol: str
    as_of: str | None  # ISO ts of the quote snapshot, if any
    weights_effective_date: str | None
    source: str  # "seed" | provider name — where the numbers came from
    n_constituents: int
    total_weight_pct: float
    index_ltp: float | None
    index_prev_close: float | None
    index_change_pct: float | None
    concentration: Concentration
    sectors: tuple[SectorWeight, ...]
    breadth: Breadth | None
    items: tuple[Constituent, ...]
    beta_lookback: int | None
    algo_version: str
    index_constituents_version: str = field(default=INDEX_CONSTITUENTS_VERSION)


# --------------------------------------------------------------------------- math


def returns(closes: Sequence[float]) -> list[float]:
    """Simple period-over-period percentage returns."""
    out: list[float] = []
    for a, b in zip(closes, closes[1:], strict=False):
        out.append((b - a) / a * 100.0 if a else 0.0)
    return out


def beta_correlation(
    index_returns: Sequence[float], stock_returns: Sequence[float]
) -> BetaCorr | None:
    """OLS of stock on index: ``beta`` = cov/var(index), Pearson ``correlation``,
    ``r_squared`` = correlation². ``None`` if fewer than 2 aligned points or the
    index return series has zero variance."""
    n = min(len(index_returns), len(stock_returns))
    if n < 2:
        return None
    xs = list(index_returns[-n:])
    ys = list(stock_returns[-n:])
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    if sxx == 0.0:
        return None
    beta = sxy / sxx
    corr = 0.0 if syy == 0.0 else sxy / math.sqrt(sxx * syy)
    return BetaCorr(
        n=n,
        beta=round(beta, 4),
        correlation=round(corr, 4),
        r_squared=round(corr * corr, 4),
        alpha_daily=round(my - beta * mx, 4),
    )


def _change_pct(q: ConstituentQuote | None) -> float | None:
    if q is None or q.ltp is None or q.prev_close in (None, 0):
        return None
    return (q.ltp - q.prev_close) / q.prev_close * 100.0


# ----------------------------------------------------------------------- assemble


def build_constituent_view(
    *,
    index_symbol: str,
    algo_version: str,
    weight_rows: Sequence[WeightRow],
    weights_effective_date: str | None = None,
    source: str = "seed",
    quotes: Sequence[ConstituentQuote] | None = None,
    as_of: str | None = None,
    index_ltp: float | None = None,
    index_prev_close: float | None = None,
    history: dict[str, Sequence[float]] | None = None,
    index_history: Sequence[float] | None = None,
    beta_lookback: int | None = None,
) -> ConstituentView:
    if not weight_rows:
        raise ValueError("no weight rows")

    rows = sorted(weight_rows, key=lambda r: (-r.weight_pct, r.symbol))
    total_w = sum(r.weight_pct for r in rows)
    q_by = {q.symbol: q for q in (quotes or [])}

    idx_ret = list(index_history) if index_history is not None else None
    idx_ret_series = returns(idx_ret) if idx_ret is not None else None

    # first pass: change % + raw contribution %
    raw: list[dict] = []
    cum = 0.0
    for i, r in enumerate(rows, start=1):
        cum += r.weight_pct
        chg = _change_pct(q_by.get(r.symbol))
        contrib_pct = None if chg is None else r.weight_pct * chg / 100.0
        bc = None
        if history is not None and idx_ret_series is not None and r.symbol in history:
            bc = beta_correlation(idx_ret_series, returns(history[r.symbol]))
        raw.append(
            {
                "row": r,
                "rank": i,
                "cum": cum,
                "chg": chg,
                "contrib_pct": contrib_pct,
                "bc": bc,
            }
        )

    # contribution ranks (only over names with a value)
    valued = [x for x in raw if x["contrib_pct"] is not None]
    by_signed = sorted(valued, key=lambda x: -x["contrib_pct"])
    by_abs = sorted(valued, key=lambda x: -abs(x["contrib_pct"]))
    signed_rank = {id(x): n for n, x in enumerate(by_signed, start=1)}
    abs_rank = {id(x): n for n, x in enumerate(by_abs, start=1)}

    items: list[Constituent] = []
    for x in raw:
        r: WeightRow = x["row"]
        q = q_by.get(r.symbol)
        cp = x["contrib_pct"]
        pts = None if (cp is None or index_prev_close is None) else cp / 100.0 * index_prev_close
        bc: BetaCorr | None = x["bc"]
        items.append(
            Constituent(
                symbol=r.symbol,
                name=r.name,
                sector=r.sector,
                rank=x["rank"],
                weight_pct=round(r.weight_pct, 4),
                cumulative_weight_pct=round(x["cum"], 4),
                ltp=q.ltp if q else None,
                prev_close=q.prev_close if q else None,
                change_pct=None if x["chg"] is None else round(x["chg"], 4),
                contribution_pct=None if cp is None else round(cp, 5),
                contribution_points=None if pts is None else round(pts, 3),
                contribution_rank=signed_rank.get(id(x)),
                abs_contribution_rank=abs_rank.get(id(x)),
                beta=bc.beta if bc else None,
                correlation=bc.correlation if bc else None,
                r_squared=bc.r_squared if bc else None,
            )
        )

    # concentration
    fr = [r.weight_pct / total_w for r in rows] if total_w else [0.0] * len(rows)
    conc = Concentration(
        top1_pct=round(rows[0].weight_pct, 4) if rows else 0.0,
        top5_pct=round(sum(r.weight_pct for r in rows[:5]), 4),
        top10_pct=round(sum(r.weight_pct for r in rows[:10]), 4),
        hhi=round(sum(f * f for f in fr), 6),
    )

    # sector rollup
    pts_by_sym = {c.symbol: c.contribution_points for c in items}
    sec_w: dict[str, list[float]] = {}
    sec_c: dict[str, float] = {}
    sec_p: dict[str, float] = {}
    for x in raw:
        r = x["row"]
        sec_w.setdefault(r.sector, [0.0, 0.0])
        sec_w[r.sector][0] += r.weight_pct
        sec_w[r.sector][1] += 1
        if x["contrib_pct"] is not None:
            sec_c[r.sector] = sec_c.get(r.sector, 0.0) + x["contrib_pct"]
        p = pts_by_sym.get(r.symbol)
        if p is not None:
            sec_p[r.sector] = sec_p.get(r.sector, 0.0) + p
    sectors = tuple(
        SectorWeight(
            sector=s,
            weight_pct=round(w, 4),
            count=int(c),
            contribution_pct=round(sec_c[s], 5) if s in sec_c else None,
            contribution_points=round(sec_p[s], 3) if s in sec_p else None,
        )
        for s, (w, c) in sorted(sec_w.items(), key=lambda kv: -kv[1][0])
    )

    # breadth
    breadth = None
    if valued:
        adv = sum(1 for x in valued if x["chg"] > 0)
        dec = sum(1 for x in valued if x["chg"] < 0)
        unch = sum(1 for x in valued if x["chg"] == 0)
        up_w = sum(x["row"].weight_pct for x in valued if x["chg"] > 0)
        dn_w = sum(x["row"].weight_pct for x in valued if x["chg"] < 0)
        net_cp = sum(x["contrib_pct"] for x in valued)
        tot_abs = sum(abs(x["contrib_pct"]) for x in valued)
        top5_abs = sum(abs(x["contrib_pct"]) for x in by_abs[:5])
        pts = [c.contribution_points for c in items if c.contribution_points is not None]
        breadth = Breadth(
            covered=len(valued),
            advances=adv,
            declines=dec,
            unchanged=unch,
            up_weight_pct=round(up_w, 4),
            down_weight_pct=round(dn_w, 4),
            advance_decline_weight=round(up_w - dn_w, 4),
            net_contribution_pct=round(net_cp, 5),
            net_contribution_points=round(sum(pts), 3) if pts else None,
            top5_move_share=round(top5_abs / tot_abs, 4) if tot_abs else None,
        )

    idx_chg = None
    if index_ltp is not None and index_prev_close not in (None, 0):
        idx_chg = round((index_ltp - index_prev_close) / index_prev_close * 100.0, 4)
    elif breadth is not None:
        idx_chg = breadth.net_contribution_pct  # Σ contribution — the best available proxy

    return ConstituentView(
        index_symbol=index_symbol,
        as_of=as_of,
        weights_effective_date=weights_effective_date,
        source=source,
        n_constituents=len(rows),
        total_weight_pct=round(total_w, 4),
        index_ltp=index_ltp,
        index_prev_close=index_prev_close,
        index_change_pct=idx_chg,
        concentration=conc,
        sectors=sectors,
        breadth=breadth,
        items=tuple(items),
        beta_lookback=beta_lookback,
        algo_version=algo_version,
    )
