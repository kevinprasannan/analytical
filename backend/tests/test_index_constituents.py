"""Index-constituent analytics (docs/15). Pure — weightage, contribution,
breadth, beta/correlation. Descriptive; no signal, no BUY/SELL."""

from __future__ import annotations

import pytest

from analytical_core.indices import (
    INDEX_CONSTITUENTS_VERSION,
    ConstituentQuote,
    WeightRow,
    beta_correlation,
    build_constituent_view,
    returns,
)
from analytical_core.versioning import ALGO_VERSION

W = [
    WeightRow("RELIANCE", "Reliance Industries", "Energy", 10.0),
    WeightRow("HDFCBANK", "HDFC Bank", "Financials", 9.0),
    WeightRow("ICICIBANK", "ICICI Bank", "Financials", 8.0),
    WeightRow("INFY", "Infosys", "IT", 6.0),
    WeightRow("TCS", "Tata Consultancy", "IT", 4.0),
    WeightRow("ITC", "ITC", "FMCG", 3.0),
]


def _view(**kw):
    return build_constituent_view(
        index_symbol="NIFTY 50", algo_version=ALGO_VERSION, weight_rows=W, **kw
    )


# ------------------------------------------------------------- weight / ordering


def test_sorted_by_weight_with_running_cumulative():
    v = _view()
    assert [c.symbol for c in v.items] == [
        "RELIANCE",
        "HDFCBANK",
        "ICICIBANK",
        "INFY",
        "TCS",
        "ITC",
    ]
    assert [c.rank for c in v.items] == [1, 2, 3, 4, 5, 6]
    assert v.items[0].cumulative_weight_pct == pytest.approx(10.0)
    assert v.items[-1].cumulative_weight_pct == pytest.approx(v.total_weight_pct)
    assert v.total_weight_pct == pytest.approx(40.0)
    assert v.index_constituents_version == INDEX_CONSTITUENTS_VERSION


def test_concentration_and_sector_rollup():
    v = _view()
    assert v.concentration.top1_pct == pytest.approx(10.0)
    assert v.concentration.top5_pct == pytest.approx(37.0)
    assert v.concentration.top10_pct == pytest.approx(40.0)  # only 6 names
    assert 0.0 < v.concentration.hhi < 1.0
    secs = {s.sector: s for s in v.sectors}
    assert secs["Financials"].weight_pct == pytest.approx(17.0)
    assert secs["Financials"].count == 2
    assert secs["Financials"].contribution_pct is None  # no quotes -> no contribution
    assert secs["Financials"].contribution_points is None
    # sectors are ordered by weight desc
    assert [s.weight_pct for s in v.sectors] == sorted(
        (s.weight_pct for s in v.sectors), reverse=True
    )


def test_sector_contribution_points_sum_from_members():
    q = [
        ConstituentQuote("RELIANCE", 102.0, 100.0),  # Energy  +2%  w10 -> cp 0.20
        ConstituentQuote("HDFCBANK", 99.0, 100.0),  # Financials -1% w9 -> cp -0.09
        ConstituentQuote("ICICIBANK", 101.0, 100.0),  # Financials +1% w8 -> cp 0.08
        ConstituentQuote("INFY", 100.0, 100.0),
        ConstituentQuote("TCS", 100.0, 100.0),
        ConstituentQuote("ITC", 100.0, 100.0),
    ]
    v = _view(quotes=q, index_prev_close=24000.0)
    by_sec = {s.sector: s for s in v.sectors}
    pts_by_sec: dict[str, float] = {}
    for c in v.items:
        if c.contribution_points is not None:
            pts_by_sec[c.sector] = pts_by_sec.get(c.sector, 0.0) + c.contribution_points
    for sec, s in by_sec.items():
        if sec in pts_by_sec:
            assert s.contribution_points == pytest.approx(pts_by_sec[sec])
    # Financials sector = HDFCBANK + ICICIBANK net contribution
    fin = by_sec["Financials"]
    assert fin.contribution_pct == pytest.approx(-0.09 + 0.08)
    assert fin.contribution_points == pytest.approx((-0.09 + 0.08) / 100 * 24000.0)


# ------------------------------------------------------------------ contribution


def test_contribution_points_and_ranks():
    q = [
        ConstituentQuote("RELIANCE", 101.0, 100.0),  # +1%  -> cp 0.10
        ConstituentQuote("HDFCBANK", 99.0, 100.0),  # -1%  -> cp -0.09
        ConstituentQuote(
            "ICICIBANK", 102.0, 100.0
        ),  # +2% * w8 -> cp +0.16 (biggest |contribution|)
        ConstituentQuote("INFY", 100.0, 100.0),  # flat
        ConstituentQuote(
            "TCS", 97.0, 100.0
        ),  # -3% * w4 -> cp -0.12 (biggest price move, not contribution)
        ConstituentQuote("ITC", 100.5, 100.0),  # +0.5%
    ]
    v = _view(quotes=q, index_prev_close=24000.0)
    by = {c.symbol: c for c in v.items}
    assert by["RELIANCE"].change_pct == pytest.approx(1.0)
    assert by["RELIANCE"].contribution_pct == pytest.approx(0.10)
    assert by["RELIANCE"].contribution_points == pytest.approx(0.10 / 100 * 24000.0)  # 24.0
    assert by["ICICIBANK"].contribution_rank == 1  # most positive contribution
    assert by["ICICIBANK"].abs_contribution_rank == 1  # and the biggest mover of the index
    assert by["TCS"].abs_contribution_rank == 2  # bigger price move, smaller weight
    # Σ contribution_pct == breadth.net (the index-move proxy)
    tot = sum(c.contribution_pct for c in v.items)
    assert v.breadth.net_contribution_pct == pytest.approx(tot)
    # Σ contribution_points == breadth.net_contribution_points (≈ index points)
    tot_pts = sum(c.contribution_points for c in v.items)
    assert v.breadth.net_contribution_points == pytest.approx(tot_pts)
    assert v.breadth.net_contribution_points == pytest.approx(tot / 100 * 24000.0)


def test_net_contribution_points_none_without_index_prev_close():
    q = [ConstituentQuote("RELIANCE", 101.0, 100.0)]
    v = _view(quotes=q)  # no index_prev_close -> no points
    assert v.breadth is not None
    assert v.breadth.net_contribution_pct is not None
    assert v.breadth.net_contribution_points is None


def test_contribution_points_need_index_prev_close():
    q = [ConstituentQuote("RELIANCE", 101.0, 100.0)]
    v = _view(quotes=q)  # no index_prev_close
    assert v.items[0].contribution_pct is not None
    assert v.items[0].contribution_points is None


def test_no_quotes_leaves_dynamic_fields_none():
    v = _view()
    assert v.breadth is None
    assert v.index_change_pct is None
    assert all(c.change_pct is None and c.contribution_pct is None for c in v.items)
    # static analytics still there
    assert v.concentration.top5_pct == pytest.approx(37.0)


# ----------------------------------------------------------------------- breadth


def test_breadth_counts_and_weighted_ad():
    q = [
        ConstituentQuote("RELIANCE", 101.0, 100.0),  # up, w10
        ConstituentQuote("HDFCBANK", 99.0, 100.0),  # dn, w9
        ConstituentQuote("ICICIBANK", 101.0, 100.0),  # up, w8
        ConstituentQuote("INFY", 100.0, 100.0),  # flat
        ConstituentQuote("TCS", 99.0, 100.0),  # dn, w4
        ConstituentQuote("ITC", 100.0, 100.0),  # flat
    ]
    b = _view(quotes=q).breadth
    assert (b.advances, b.declines, b.unchanged) == (2, 2, 2)
    assert b.covered == 6
    assert b.up_weight_pct == pytest.approx(18.0)  # 10 + 8
    assert b.down_weight_pct == pytest.approx(13.0)  # 9 + 4
    assert b.advance_decline_weight == pytest.approx(5.0)
    assert 0.0 <= b.top5_move_share <= 1.0


def test_index_change_from_index_quote_beats_proxy():
    q = [ConstituentQuote("RELIANCE", 101.0, 100.0)]
    v = _view(quotes=q, index_ltp=24030.0, index_prev_close=24000.0)
    assert v.index_change_pct == pytest.approx(0.125)  # real index quote, not Σ contribution
    assert v.index_ltp == 24030.0


# -------------------------------------------------------------- beta / correlation


def test_returns_helper():
    assert returns([100.0, 110.0, 99.0]) == pytest.approx([10.0, -10.0])
    assert returns([100.0]) == []


def test_beta_correlation_perfect_2x():
    idx = [1.0, -2.0, 3.0, -1.0, 2.0]
    stk = [2.0, -4.0, 6.0, -2.0, 4.0]  # exactly 2x the index
    bc = beta_correlation(idx, stk)
    assert bc is not None
    assert bc.beta == pytest.approx(2.0)
    assert bc.correlation == pytest.approx(1.0)
    assert bc.r_squared == pytest.approx(1.0)
    assert bc.n == 5


def test_beta_correlation_guards():
    assert beta_correlation([1.0], [1.0]) is None  # <2 points
    assert beta_correlation([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) is None  # zero index variance


def test_beta_wired_through_view():
    q = [ConstituentQuote(s.symbol, 100.0, 100.0) for s in W]
    hist = {
        "RELIANCE": [100.0, 102.0, 101.0, 104.0, 103.0, 106.0],
        "HDFCBANK": [100.0, 100.5, 100.2, 101.0, 100.8, 101.5],
    }
    idx_hist = [100.0, 101.0, 100.5, 102.0, 101.5, 103.0]
    v = _view(quotes=q, history=hist, index_history=idx_hist, beta_lookback=5)
    by = {c.symbol: c for c in v.items}
    assert by["RELIANCE"].beta is not None and by["RELIANCE"].correlation is not None
    assert by["ICICIBANK"].beta is None  # no history supplied
    assert v.beta_lookback == 5


def test_deterministic():
    q = [ConstituentQuote("RELIANCE", 101.0, 100.0), ConstituentQuote("TCS", 98.0, 100.0)]
    assert _view(quotes=q, index_prev_close=24000.0) == _view(quotes=q, index_prev_close=24000.0)


def test_empty_weight_rows_raise():
    with pytest.raises(ValueError, match="no weight rows"):
        build_constituent_view(index_symbol="x", algo_version=ALGO_VERSION, weight_rows=[])
