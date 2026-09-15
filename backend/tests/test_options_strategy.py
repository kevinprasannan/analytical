"""OI-based option-strategy suggestions (docs/05 §11.5). Pure, deterministic.

These structures carry BUY/SELL legs — a bounded, owner-authorised exception to
decision 15 (see the module docstring). Every book still ships the disclaimer.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from analytical_core.options.strategy import (
    DISCLAIMER,
    StrategyConfig,
    StrikeQuote,
    build_strategy_book,
)
from analytical_core.versioning import ALGO_VERSION

NOW = datetime(2026, 9, 3, 6, 0, tzinfo=UTC)
EXPIRY = date(2026, 9, 10)


def _chain(spot, ce_chg, pe_chg, *, ce_wall=24400, pe_wall=23600, wall=80_000):
    """A symmetric 100-pt chain around 24000; ΔOI supplied per side by a fn."""
    out = []
    for k in range(23200, 24801, 100):
        d = abs(k - 24000)
        out.append(
            StrikeQuote(
                strike=float(k),
                ce_oi=max(1000, 200_000 - d * 40 + (wall if k == ce_wall else 0)),
                ce_oi_change=ce_chg(k),
                ce_ltp=max(5.0, 240 - d * 0.5),
                pe_oi=max(1000, 200_000 - d * 40 + (wall if k == pe_wall else 0)),
                pe_oi_change=pe_chg(k),
                pe_ltp=max(5.0, 240 - d * 0.5),
            )
        )
    return out


def _book(spot, ce_chg, pe_chg, **kw):
    return build_strategy_book(
        underlying_symbol="NIFTY",
        quotes=_chain(spot, ce_chg, pe_chg, **kw),
        spot=spot,
        expiry=EXPIRY,
        now=NOW,
    )


# --------------------------------------------------------------- view classifier


def test_two_way_writing_reads_rangebound():
    b = _book(24012, lambda k: 3000, lambda k: 3200)
    assert b.view.label == "RANGEBOUND"
    names = {s.name for s in b.suggestions}
    assert {"IRON_CONDOR", "IRON_FLY", "SHORT_STRANGLE"} <= names


def test_calls_unwind_puts_written_reads_trend_up():
    b = _book(24012, lambda k: -4000, lambda k: 6000)
    assert b.view.label == "TREND_BULLISH"
    assert [s.name for s in b.suggestions][0] == "BULL_PUT_SPREAD"
    assert any(s.name == "CALL_RATIO_SPREAD_1X2" for s in b.suggestions)


def test_puts_unwind_calls_written_reads_trend_down():
    b = _book(24012, lambda k: 6000, lambda k: -4000)
    assert b.view.label == "TREND_BEARISH"
    assert any(s.name == "PUT_RATIO_SPREAD_1X2" for s in b.suggestions)


def test_both_unwinding_reads_vol_expansion():
    b = _book(24012, lambda k: -5000, lambda k: -5000)
    assert b.view.label == "VOL_EXPANSION"
    assert {s.name for s in b.suggestions} == {"LONG_STRADDLE", "LONG_STRANGLE"}


def test_flat_chain_defaults_neutral():
    b = _book(24012, lambda k: 0, lambda k: 0)
    assert b.view.label == "RANGEBOUND"
    assert b.view.confidence <= 0.8


# --------------------------------------------------------------- structure shape


def test_iron_condor_legs_and_pl():
    b = _book(24012, lambda k: 3000, lambda k: 3200)
    ic = next(s for s in b.suggestions if s.name == "IRON_CONDOR")
    assert ic.risk == "DEFINED"
    assert len(ic.legs) == 4
    acts = sorted((lg.action, lg.option_type) for lg in ic.legs)
    assert acts == [("BUY", "CE"), ("BUY", "PE"), ("SELL", "CE"), ("SELL", "PE")]
    # short strikes inside the long wings
    ce = sorted(lg.strike for lg in ic.legs if lg.option_type == "CE")
    pe = sorted(lg.strike for lg in ic.legs if lg.option_type == "PE")
    assert ce[0] < ce[1]  # short call < long call
    assert pe[0] < pe[1]  # long put < short put
    if ic.max_profit is not None and ic.max_loss is not None:
        assert ic.max_profit > 0 and ic.max_loss > 0


def test_ratio_spread_is_one_by_two_and_flagged_undefined():
    b = _book(24012, lambda k: -4000, lambda k: 6000)
    rs = next(s for s in b.suggestions if s.name == "CALL_RATIO_SPREAD_1X2")
    buys = [lg for lg in rs.legs if lg.action == "BUY"]
    sells = [lg for lg in rs.legs if lg.action == "SELL"]
    assert sum(lg.lots for lg in buys) == 1
    assert sum(lg.lots for lg in sells) == 2
    assert rs.risk == "UNDEFINED"
    assert any("naked" in c.lower() or "undefined" in c.lower() for c in rs.caveats)


def test_long_straddle_is_two_long_atm_legs():
    b = _book(24012, lambda k: -5000, lambda k: -5000)
    ls = next(s for s in b.suggestions if s.name == "LONG_STRADDLE")
    assert all(lg.action == "BUY" for lg in ls.legs)
    assert len({lg.strike for lg in ls.legs}) == 1  # same ATM strike
    assert {lg.option_type for lg in ls.legs} == {"CE", "PE"}
    assert ls.net == "DEBIT"


# --------------------------------------------------------------- contract / provenance


def test_every_book_and_suggestion_carries_the_disclaimer_and_version():
    b = _book(24012, lambda k: 3000, lambda k: 3200)
    assert b.disclaimer == DISCLAIMER
    assert "not investment advice" in b.disclaimer.lower()
    assert b.algo_version == ALGO_VERSION
    assert b.expiry == EXPIRY.isoformat()
    assert b.days_to_expiry == 7


def test_deterministic():
    a = _book(24012, lambda k: 3000, lambda k: 3200)
    c = _book(24012, lambda k: 3000, lambda k: 3200)
    assert a == c


def test_no_strikes_raises():
    with pytest.raises(ValueError, match="no strikes"):
        build_strategy_book(underlying_symbol="NIFTY", quotes=[], spot=1.0, expiry=EXPIRY, now=NOW)


def test_missing_ltp_leaves_premium_none_with_caveat():
    qs = _chain(24012, lambda k: 3000, lambda k: 3200)
    qs = [
        StrikeQuote(
            strike=q.strike,
            ce_oi=q.ce_oi,
            ce_oi_change=q.ce_oi_change,
            ce_ltp=None,
            pe_oi=q.pe_oi,
            pe_oi_change=q.pe_oi_change,
            pe_ltp=None,
        )
        for q in qs
    ]
    b = build_strategy_book(
        underlying_symbol="NIFTY", quotes=qs, spot=24012, expiry=EXPIRY, now=NOW
    )
    for s in b.suggestions:
        assert s.est_net_premium is None
        assert s.net == "UNKNOWN"
        assert any("ltp unavailable" in c.lower() for c in s.caveats)


def test_wing_steps_config_widens_the_wings():
    narrow = build_strategy_book(
        underlying_symbol="NIFTY",
        quotes=_chain(24012, lambda k: 3000, lambda k: 3200),
        spot=24012,
        expiry=EXPIRY,
        now=NOW,
        config=StrategyConfig(wing_steps=1),
    )
    wide = build_strategy_book(
        underlying_symbol="NIFTY",
        quotes=_chain(24012, lambda k: 3000, lambda k: 3200),
        spot=24012,
        expiry=EXPIRY,
        now=NOW,
        config=StrategyConfig(wing_steps=4),
    )
    n_fly = next(s for s in narrow.suggestions if s.name == "IRON_FLY")
    w_fly = next(s for s in wide.suggestions if s.name == "IRON_FLY")
    n_span = max(lg.strike for lg in n_fly.legs) - min(lg.strike for lg in n_fly.legs)
    w_span = max(lg.strike for lg in w_fly.legs) - min(lg.strike for lg in w_fly.legs)
    assert w_span > n_span


# ------------------------------------------------------------ PoP / edge / bands


def _far(spot, ce_chg, pe_chg, **kw):
    """A later-expiry chain — richer premiums (more time value)."""
    return [
        StrikeQuote(
            strike=q.strike,
            ce_oi=1000, ce_oi_change=0, ce_ltp=(q.ce_ltp or 5) * 1.7,
            pe_oi=1000, pe_oi_change=0, pe_ltp=(q.pe_ltp or 5) * 1.7,
        )
        for q in _chain(spot, ce_chg, pe_chg, **kw)
    ]


def test_defined_risk_suggestions_carry_pop_reward_risk_and_edge():
    b = build_strategy_book(
        underlying_symbol="NIFTY",
        quotes=_chain(24012, lambda k: 3000, lambda k: 3200),
        spot=24012.0,
        expiry=EXPIRY,
        now=NOW,
        atm_iv=0.12,
        t_years=7 / 365,
        risk_free_rate=0.065,
    )
    defs = [s for s in b.suggestions if s.risk == "DEFINED" and s.max_loss and s.max_profit]
    assert defs, "expected at least one defined-risk suggestion"
    for s in defs:
        assert 0.0 <= s.pop <= 1.0 and s.pop_basis == "LOGNORMAL_IV"
        assert s.reward_risk == round(s.max_profit / abs(s.max_loss), 2)
        assert s.edge_score == round(s.pop * s.reward_risk, 3)
    # book is ranked best-edge first
    ed = [s.edge_score for s in b.suggestions if s.edge_score is not None]
    assert ed == sorted(ed, reverse=True)
    assert b.ranked_by == "EDGE" and b.atm_iv == 0.12


def test_band_framing_lower_upper_and_inside_flag():
    b = build_strategy_book(
        underlying_symbol="NIFTY",
        quotes=_chain(24012, lambda k: 3000, lambda k: 3200),
        spot=24012.0, expiry=EXPIRY, now=NOW, atm_iv=0.12, t_years=7 / 365,
    )
    ic = next(s for s in b.suggestions if s.name == "IRON_CONDOR")
    assert ic.lower_breakeven == min(ic.breakevens)
    assert ic.upper_breakeven == max(ic.breakevens)
    assert ic.spot_inside_breakevens is (ic.lower_breakeven <= 24012.0 <= ic.upper_breakeven)


def test_wing_points_overrides_strike_steps():
    common = dict(
        underlying_symbol="NIFTY", spot=24012.0, expiry=EXPIRY, now=NOW,
        quotes=_chain(24012, lambda k: 3000, lambda k: 3200),
    )
    steps = build_strategy_book(**common, config=StrategyConfig(wing_steps=2))
    pts = build_strategy_book(**common, config=StrategyConfig(wing_points=500))
    ic_s = next(s for s in steps.suggestions if s.name == "IRON_CONDOR")
    ic_p = next(s for s in pts.suggestions if s.name == "IRON_CONDOR")
    span = lambda s: max(l.strike for l in s.legs) - min(l.strike for l in s.legs)
    assert span(ic_p) > span(ic_s)


def test_calendars_only_with_a_far_expiry_and_a_range_read():
    kw = dict(
        underlying_symbol="NIFTY", spot=24012.0, expiry=EXPIRY, now=NOW,
        atm_iv=0.12, t_years=7 / 365,
    )
    # range read, no far chain -> no calendars
    b1 = build_strategy_book(quotes=_chain(24012, lambda k: 3000, lambda k: 3200), **kw)
    assert not [s for s in b1.suggestions if s.family == "CALENDAR"]
    # range read + far chain -> calendars appear
    b2 = build_strategy_book(
        quotes=_chain(24012, lambda k: 3000, lambda k: 3200),
        far_quotes=_far(24012, lambda k: 3000, lambda k: 3200),
        far_expiry=date(2026, 9, 17),
        **kw,
    )
    cals = [s for s in b2.suggestions if s.family == "CALENDAR"]
    assert {s.name for s in cals} == {"CALL_CALENDAR", "PUT_CALENDAR"}
    for s in cals:
        assert s.risk == "DEFINED" and s.max_loss and s.max_loss > 0
        assert s.pop_basis == "LOGNORMAL_NEAR_RANGE" and 0.0 <= s.pop <= 1.0
        assert any(lg.expiry == "2026-09-17" for lg in s.legs)
        assert any("Two expiries" in c for c in s.caveats)
    assert b2.far_expiry == "2026-09-17"
    # a strong directional read leaves calendars out
    b3 = build_strategy_book(
        quotes=_chain(24012, lambda k: -6000, lambda k: 8000),
        far_quotes=_far(24012, lambda k: -6000, lambda k: 8000),
        far_expiry=date(2026, 9, 17),
        **kw,
    )
    assert not [s for s in b3.suggestions if s.family == "CALENDAR"]


def test_min_reward_risk_filters_defined_suggestions():
    kw = dict(
        underlying_symbol="NIFTY", spot=24012.0, expiry=EXPIRY, now=NOW,
        quotes=_chain(24012, lambda k: 3000, lambda k: 3200), atm_iv=0.12, t_years=7 / 365,
    )
    loose = build_strategy_book(**kw, config=StrategyConfig(min_reward_risk=0.0))
    tight = build_strategy_book(**kw, config=StrategyConfig(min_reward_risk=5.0))
    kept = [s for s in tight.suggestions if s.reward_risk is not None]
    assert all(s.reward_risk >= 5.0 for s in kept)
    assert len(tight.suggestions) <= len(loose.suggestions)


def test_pop_none_when_no_iv():
    b = _book(24012, lambda k: 3000, lambda k: 3200)  # no atm_iv passed
    for s in b.suggestions:
        assert s.pop is None and s.edge_score is None and s.pop_basis == "NONE"
    assert b.ranked_by == "EDGE"  # still ranked, just all edge None -> stable order
