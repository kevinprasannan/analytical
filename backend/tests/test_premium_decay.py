"""`analytical_core.options.decay` — pure, deterministic (docs/05 §11.6)."""

from __future__ import annotations

from datetime import UTC, datetime

from analytical_core.options import (
    DECAY_VERSION,
    DecayLegInput,
    build_premium_decay,
    premium_decay_to_dict,
)

OPEN = datetime(2026, 9, 1, 3, 45, tzinfo=UTC)  # 09:15 IST
NOW = OPEN.replace(hour=9, minute=45)  # 6h exactly -> 0.25 calendar days elapsed


def _leg(strike, otype, ltp, theta, px_open, *, iv=0.15, lot=75):
    return DecayLegInput(
        strike=float(strike),
        option_type=otype,
        ltp=ltp,
        iv=iv,
        theta=theta,
        lot_size=lot,
        price_at_open=px_open,
    )


def test_shape_and_versions():
    legs = [
        _leg(100, "CE", 10.0, -4.0, 12.0),
        _leg(100, "PE", 9.0, -3.0, 8.5),
    ]
    d = build_premium_decay(
        underlying_symbol="NIFTY",
        spot=100.0,
        expiry="2026-09-04",
        days_to_expiry=3,
        atm_strike=100.0,
        now=NOW,
        session_open=OPEN,
        legs=legs,
    )
    assert d.decay_version == DECAY_VERSION
    assert d.fast_decay_zone is True  # dte <= 5
    assert d.elapsed_calendar_days == 0.25
    assert [r.strike for r in d.rows] == [100.0]
    call, put = d.rows[0].call, d.rows[0].put
    assert call is not None and put is not None
    # theta_per_lot = theta * lot_size
    assert call.theta_per_lot == -300.0
    assert put.theta_per_lot == -225.0
    assert d.atm_call_theta_per_lot == -300.0
    assert d.atm_put_theta_per_lot == -225.0
    assert d.atm_straddle_theta_per_lot == -525.0


def test_decaying_faster_when_loss_exceeds_theta():
    # theta alone predicts -1.0 over the elapsed window; actual lost 3.5 -> extra bleed
    leg = _leg(100, "CE", 8.5, -4.0, 12.0)  # expected = -4*0.25 = -1.0; actual = 8.5-12=-3.5
    d = build_premium_decay(
        underlying_symbol="NIFTY",
        spot=100.0,
        expiry="2026-09-04",
        days_to_expiry=10,
        atm_strike=100.0,
        now=NOW,
        session_open=OPEN,
        legs=[leg],
    )
    call = d.rows[0].call
    assert call.expected_decay == -1.0
    assert call.actual_change == -3.5
    assert call.decay_gap == -2.5
    assert call.decay_state == "DECAYING_FASTER"
    assert d.fast_decay_zone is False  # dte=10


def test_offset_by_move_when_premium_holds_up():
    # theta predicts a small loss but the premium actually rose -> a move outweighed decay
    leg = _leg(100, "CE", 13.0, -4.0, 12.0)  # expected = -1.0; actual = +1.0
    d = build_premium_decay(
        underlying_symbol="NIFTY",
        spot=100.0,
        expiry="2026-09-04",
        days_to_expiry=10,
        atm_strike=100.0,
        now=NOW,
        session_open=OPEN,
        legs=[leg],
    )
    call = d.rows[0].call
    assert call.decay_state == "OFFSET_BY_MOVE"


def test_as_expected_within_epsilon():
    # expected = -1.0; actual = -1.1 -> within the default epsilon band
    leg = _leg(100, "CE", 10.9, -4.0, 12.0)
    d = build_premium_decay(
        underlying_symbol="NIFTY",
        spot=100.0,
        expiry="2026-09-04",
        days_to_expiry=10,
        atm_strike=100.0,
        now=NOW,
        session_open=OPEN,
        legs=[leg],
    )
    assert d.rows[0].call.decay_state == "AS_EXPECTED"


def test_no_data_when_theta_or_open_price_missing():
    legs = [
        _leg(100, "CE", 10.0, None, 12.0),  # no theta
        _leg(105, "PE", 9.0, -3.0, None),  # no price at open
    ]
    d = build_premium_decay(
        underlying_symbol="NIFTY",
        spot=100.0,
        expiry="2026-09-04",
        days_to_expiry=10,
        atm_strike=None,
        now=NOW,
        session_open=OPEN,
        legs=legs,
    )
    rows = {r.strike: r for r in d.rows}
    assert rows[100.0].call.decay_state == "NO_DATA"
    assert rows[100.0].call.expected_decay is None
    assert rows[105.0].put.decay_state == "NO_DATA"
    assert rows[105.0].put.actual_change is None


def test_theta_pct_of_premium():
    leg = _leg(100, "CE", 8.0, -4.0, 12.0)
    d = build_premium_decay(
        underlying_symbol="NIFTY",
        spot=100.0,
        expiry="2026-09-04",
        days_to_expiry=10,
        atm_strike=100.0,
        now=NOW,
        session_open=OPEN,
        legs=[leg],
    )
    assert d.rows[0].call.theta_pct_of_premium == -0.5  # -4 / 8


def test_no_buy_sell_language():
    leg = _leg(100, "CE", 10.0, -4.0, 12.0)
    d = build_premium_decay(
        underlying_symbol="NIFTY",
        spot=100.0,
        expiry="2026-09-04",
        days_to_expiry=10,
        atm_strike=100.0,
        now=NOW,
        session_open=OPEN,
        legs=[leg],
    )
    blob = str(premium_decay_to_dict(d)).lower()
    assert "buy" not in blob
    assert "sell" not in blob
