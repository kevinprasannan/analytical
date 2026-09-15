"""Option pricing + chain — Black–Scholes, greeks, IV, PCR / max-pain (docs/05 §11)."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime

import pytest

from analytical_core.options import (
    LegInput,
    bs_greeks,
    bs_price,
    build_chain,
    crowded_read,
    implied_vol,
)
from analytical_core.versioning import ALGO_VERSION

S, R, T = 24000.0, 0.065, 30.0 / 365.0


# ---------------------------------------------------------------- Black–Scholes


def test_put_call_parity():
    for k in (22000.0, 24000.0, 26000.0):
        c = bs_price(S, k, T, R, 0.15, is_call=True)
        p = bs_price(S, k, T, R, 0.15, is_call=False)
        assert c - p == pytest.approx(S - k * math.exp(-R * T), abs=1e-6)


def test_price_is_monotone_in_vol_and_bounded_by_intrinsic():
    k = 24000.0
    lo = bs_price(S, k, T, R, 0.05, is_call=True)
    hi = bs_price(S, k, T, R, 0.35, is_call=True)
    assert lo < hi
    itm_call = bs_price(S, 23000.0, T, R, 0.15, is_call=True)
    assert itm_call >= S - 23000.0 * math.exp(-R * T) - 1e-9


def test_expiry_and_zero_vol_collapse_to_intrinsic():
    assert bs_price(S, 23500.0, 0.0, R, 0.2, is_call=True) == pytest.approx(500.0)
    assert bs_price(S, 24500.0, T, R, 0.0, is_call=False) == pytest.approx(500.0)


def test_greeks_signs_and_conventions():
    call = bs_greeks(S, S, T, R, 0.15, is_call=True)
    put = bs_greeks(S, S, T, R, 0.15, is_call=False)
    assert 0.0 < call.delta < 1.0 and -1.0 < put.delta < 0.0
    assert call.gamma > 0.0 and call.gamma == pytest.approx(
        put.gamma, rel=1e-9
    )  # gamma side-neutral
    assert call.vega > 0.0
    assert call.theta < 0.0  # long option bleeds; per-day
    # per-day theta magnitude is small vs the annualised figure
    assert abs(call.theta) < 50.0


def test_greeks_zero_after_expiry():
    g = bs_greeks(S, 23000.0, 0.0, R, 0.2, is_call=True)
    assert g.delta == 1.0 and g.gamma == 0.0 and g.vega == 0.0 and g.theta == 0.0


# ----------------------------------------------------------------------- IV


@pytest.mark.parametrize("vol", [0.08, 0.15, 0.30, 0.75])
@pytest.mark.parametrize("k", [22500.0, 24000.0, 25500.0])
@pytest.mark.parametrize("is_call", [True, False])
def test_iv_round_trips(vol, k, is_call):
    price = bs_price(S, k, T, R, vol, is_call=is_call)
    got = implied_vol(price, S, k, T, R, is_call=is_call)
    assert got == pytest.approx(vol, abs=1e-3)


def test_iv_none_outside_no_arb_band_or_expired():
    assert implied_vol(1e-6, S, 24000.0, T, R, is_call=True) is None  # below intrinsic
    assert implied_vol(S + 1.0, S, 24000.0, T, R, is_call=True) is None  # above spot
    assert implied_vol(100.0, S, 24000.0, 0.0, R, is_call=True) is None  # expired


def test_iv_is_deterministic():
    price = bs_price(S, 24100.0, T, R, 0.19, is_call=True)
    assert implied_vol(price, S, 24100.0, T, R, is_call=True) == implied_vol(
        price, S, 24100.0, T, R, is_call=True
    )


# --------------------------------------------------------------------- chain


def _legs():
    legs = []
    for k in (23800, 23900, 24000, 24100, 24200):
        legs.append(
            LegInput(
                float(k),
                "CE",
                bs_price(S, float(k), T, R, 0.14, is_call=True),
                10_000 + k,
                100,
                500,
            )
        )
        legs.append(
            LegInput(
                float(k),
                "PE",
                bs_price(S, float(k), T, R, 0.16, is_call=False),
                20_000 + k,
                120,
                400,
            )
        )
    return legs


def test_chain_assembly_shape_and_greeks():
    now = datetime(2026, 8, 29, 6, 0, tzinfo=UTC)
    ch = build_chain(
        underlying_symbol="NIFTY",
        spot=S,
        expiry=date(2026, 9, 29),
        now=now,
        risk_free_rate=R,
        legs=_legs(),
    )
    assert ch.algo_version == ALGO_VERSION
    assert [r.strike for r in ch.rows] == [23800.0, 23900.0, 24000.0, 24100.0, 24200.0]
    assert ch.atm_strike == 24000.0
    assert ch.days_to_expiry == 31
    mid = next(r for r in ch.rows if r.strike == 24000.0)
    # legs are priced at the module T; build_chain solves at its own calendar T
    # (a few % longer) — assembly recovers the vol to within ~1 vol point.
    assert mid.call.iv == pytest.approx(0.14, abs=0.01)
    assert mid.put.iv == pytest.approx(0.16, abs=0.01)
    assert mid.call.iv < mid.put.iv  # the skew we fed in survives
    assert 0.0 < mid.call.delta < 1.0 and mid.put.delta < 0.0


def test_open_at_high_low_flags():
    now = datetime(2026, 8, 29, 6, 0, tzinfo=UTC)
    legs = [
        LegInput(24000.0, "CE", 90.0, 100, 0, 0, day_open=120.0, day_high=120.0, day_low=80.0),
        LegInput(24000.0, "PE", 95.0, 100, 0, 0, day_open=60.0, day_high=140.0, day_low=60.0),
        LegInput(24100.0, "CE", 50.0, 100, 0, 0, day_open=55.0, day_high=70.0, day_low=40.0),
        LegInput(
            24100.0, "PE", 70.0, 100, 0, 0, day_open=70.0, day_high=70.0, day_low=70.0
        ),  # flat
    ]
    ch = build_chain(
        underlying_symbol="NIFTY",
        spot=S,
        expiry=date(2026, 9, 29),
        now=now,
        risk_free_rate=R,
        legs=legs,
    )
    by = {(r.strike, "CE"): r.call for r in ch.rows} | {(r.strike, "PE"): r.put for r in ch.rows}
    assert by[(24000.0, "CE")].open_at_high and not by[(24000.0, "CE")].open_at_low
    assert by[(24000.0, "PE")].open_at_low and not by[(24000.0, "PE")].open_at_high
    assert not by[(24100.0, "CE")].open_at_high and not by[(24100.0, "CE")].open_at_low
    # a flat bar (h == l) is never "open at high/low"
    assert not by[(24100.0, "PE")].open_at_high and not by[(24100.0, "PE")].open_at_low


def test_crowded_read_side_and_hot_strikes():
    # calls added a lot (mostly at 24000), puts added little
    ce = {23800.0: 1000, 23900.0: 2000, 24000.0: 12000, 24100.0: -500}
    pe = {23800.0: 300, 23900.0: 400, 24000.0: 200}
    cr = crowded_read(ce, pe)
    assert cr.side == "CALLS"
    assert cr.call_strike == 24000.0
    assert cr.put_strike == 23900.0  # biggest positive put build
    assert cr.call_frac == round(12000 / (1000 + 2000 + 12000), 4)  # -500 ignored
    assert cr.net_call_add == 15000 and cr.net_put_add == 900
    # near-parity -> BALANCED
    assert crowded_read({100.0: 1000}, {100.0: 950}).side == "BALANCED"
    # nothing added anywhere
    empty = crowded_read({100.0: -10}, {})
    assert empty.side == "BALANCED" and empty.call_strike is None


def test_chain_marks_crowded_strike_and_oi_change_pct():
    legs = [
        LegInput(24000.0, "CE", 90.0, 15000, 12000, 500),  # opening OI 3000 -> +400%
        LegInput(24100.0, "CE", 50.0, 4000, 500, 500),
        LegInput(24000.0, "PE", 95.0, 5000, 300, 400),
        LegInput(24100.0, "PE", 70.0, 4200, 200, 400),
    ]
    ch = build_chain(
        underlying_symbol="NIFTY",
        spot=24000.0,
        expiry=date(2026, 9, 29),
        now=datetime(2026, 8, 29, 6, 0, tzinfo=UTC),
        risk_free_rate=R,
        legs=legs,
    )
    assert ch.crowded_side == "CALLS" and ch.crowded_call_strike == 24000.0
    hot = next(r.call for r in ch.rows if r.strike == 24000.0)
    assert hot.crowded is True
    assert hot.oi_change_pct == round(12000 / 3000, 4)  # +400%
    cold = next(r.call for r in ch.rows if r.strike == 24100.0)
    assert cold.crowded is False


def test_pcr_and_max_pain():
    now = datetime(2026, 8, 29, 6, 0, tzinfo=UTC)
    ch = build_chain(
        underlying_symbol="NIFTY",
        spot=S,
        expiry=date(2026, 9, 29),
        now=now,
        risk_free_rate=R,
        legs=_legs(),
    )
    exp_pcr = sum(20_000 + k for k in (23800, 23900, 24000, 24100, 24200)) / sum(
        10_000 + k for k in (23800, 23900, 24000, 24100, 24200)
    )
    assert ch.pcr_oi == pytest.approx(round(exp_pcr, 4))
    assert ch.max_pain_strike in {23800.0, 23900.0, 24000.0, 24100.0, 24200.0}
    # max pain minimises total writer payout — verify against a brute check
    strikes = [23800.0, 23900.0, 24000.0, 24100.0, 24200.0]
    ce = {k: 10_000 + int(k) for k in strikes}
    pe = {k: 20_000 + int(k) for k in strikes}

    def pain(s):
        return sum(ce[k] * max(0.0, s - k) for k in strikes) + sum(
            pe[k] * max(0.0, k - s) for k in strikes
        )

    assert ch.max_pain_strike == min(strikes, key=pain)


def test_expired_chain_has_no_iv():
    ch = build_chain(
        underlying_symbol="NIFTY",
        spot=S,
        expiry=date(2026, 8, 29),
        now=datetime(2026, 8, 29, 12, 0, tzinfo=UTC),
        risk_free_rate=R,
        legs=_legs(),
    )
    assert ch.days_to_expiry == 0
    assert all(
        (r.call is None or r.call.iv is None) and (r.put is None or r.put.iv is None)
        for r in ch.rows
    )
