"""`analytical_core.options.oi_pulse` — pure, deterministic (docs/05 §11.2)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from analytical_core.options import (
    OI_PULSE_VERSION,
    OiLegSeries,
    OiPulseConfig,
    build_oi_pulse,
    oi_pulse_to_dict,
)

OPEN = datetime(2026, 9, 1, 3, 45, tzinfo=UTC)  # 09:15 IST
NOW = datetime(2026, 9, 1, 6, 30, tzinfo=UTC)  # 12:00 IST
EXPIRY = date(2026, 9, 4)


def _series(open_v, mid_v, now_v, *, base=OPEN):
    return (
        (base, open_v),
        (base + timedelta(minutes=90), mid_v),
        (NOW - timedelta(minutes=5), now_v),
    )


def _leg(strike, side, oi_open, oi_mid, oi_now, px_open, px_mid, px_now):
    return OiLegSeries(
        strike=float(strike),
        option_type=side,
        oi=_series(oi_open, oi_mid, oi_now),
        premium=_series(px_open, px_mid, px_now),
    )


def _basic_legs():
    # spot ~ 100. CE writing at 105 (OI up, premium down -> SHORT_BUILDUP),
    # PE covering at 95 (OI down, premium down -> LONG_UNWINDING).
    return [
        _leg(95, "PE", 1000, 1100, 900, 5.0, 4.5, 3.0),
        _leg(100, "CE", 2000, 2200, 2600, 3.0, 3.2, 3.6),
        _leg(100, "PE", 2000, 2100, 2050, 3.0, 2.9, 2.8),
        _leg(105, "CE", 800, 1200, 1800, 1.5, 1.2, 0.9),
    ]


def test_shape_and_versions():
    p = build_oi_pulse(
        underlying_symbol="NIFTY",
        spot=100.0,
        expiry=EXPIRY,
        now=NOW,
        session_open=OPEN,
        legs=_basic_legs(),
    )
    assert p.oi_pulse_version == OI_PULSE_VERSION
    assert [r.strike for r in p.rows] == [95.0, 100.0, 105.0]
    assert p.total_ce_oi == 2600 + 1800
    assert p.total_pe_oi == 900 + 2050
    # PCR = put OI / call OI
    assert p.pcr_oi_now == round((900 + 2050) / (2600 + 1800), 4)


def test_session_and_recent_deltas_and_buildup():
    p = build_oi_pulse(
        underlying_symbol="NIFTY",
        spot=100.0,
        expiry=EXPIRY,
        now=NOW,
        session_open=OPEN,
        legs=_basic_legs(),
    )
    ce105 = next(r.put or r.call for r in p.rows if r.strike == 105.0)
    assert ce105.oi_change_session == 1800 - 800
    assert ce105.buildup == "SHORT_BUILDUP"  # OI up, premium down

    pe95 = next(r.put for r in p.rows if r.strike == 95.0)
    assert pe95.oi_change_session == 900 - 1000
    assert pe95.buildup == "LONG_UNWINDING"  # OI down, premium down
    # session-window buildup + open premium are also exposed (0.2.0)
    assert ce105.buildup_session == "SHORT_BUILDUP"
    assert pe95.buildup_session == "LONG_UNWINDING"
    assert ce105.price_at_open is not None


def test_crowded_side_and_hot_strikes():
    p = build_oi_pulse(
        underlying_symbol="NIFTY",
        spot=100.0,
        expiry=EXPIRY,
        now=NOW,
        session_open=OPEN,
        legs=_basic_legs(),
    )
    # calls added +600 @100 and +1000 @105; puts net negative
    assert p.crowded_side == "CALLS"
    assert p.crowded_ce_strike == 105.0  # biggest call build
    hot = next(r.call for r in p.rows if r.strike == 105.0)
    assert hot.crowded is True
    assert p.crowded_ce_frac == round(1000 / (600 + 1000), 4)


def test_walls_bias_and_maxpain_shift():
    p = build_oi_pulse(
        underlying_symbol="NIFTY",
        spot=100.0,
        expiry=EXPIRY,
        now=NOW,
        session_open=OPEN,
        legs=_basic_legs(),
    )
    assert p.resistance_strike == 100.0  # max CE OI now (2600)
    assert p.support_strike == 100.0  # max PE OI now (2050)
    # calls added net +1600, puts net -150 -> call writing dominates
    assert p.net_ce_oi_change == (2600 - 2000) + (1800 - 800)
    assert p.bias == "CALL_WRITING"
    assert p.max_pain_now is not None and p.max_pain_open is not None
    assert p.max_pain_shift == round(p.max_pain_now - p.max_pain_open, 4)


def test_trace_is_ordered_and_serialisable():
    p = build_oi_pulse(
        underlying_symbol="NIFTY",
        spot=100.0,
        expiry=EXPIRY,
        now=NOW,
        session_open=OPEN,
        legs=_basic_legs(),
        config=OiPulseConfig(trace_step_min=30),
    )
    ts = [t.ts for t in p.trace]
    assert ts == sorted(ts) and len(ts) >= 2
    d = oi_pulse_to_dict(p)
    assert d["bias"] == "CALL_WRITING"
    assert len(d["rows"]) == 3 and len(d["trace"]) == len(p.trace)
    assert d["rows"][1]["call"]["buildup"]  # strike 100 CE present


def test_trace_time_series_columns():
    p = build_oi_pulse(
        underlying_symbol="NIFTY",
        spot=100.0,
        expiry=EXPIRY,
        now=NOW,
        session_open=OPEN,
        legs=_basic_legs(),
        spot_series=((OPEN, 99.0), (NOW, 100.5)),
        config=OiPulseConfig(trace_step_min=45),
    )
    last = p.trace[-1]
    # session totals reconcile with the last trace mark
    assert last.call_oi_change == p.net_ce_oi_change
    assert last.put_oi_change == p.net_pe_oi_change
    assert last.diff_oi == last.put_oi_change - last.call_oi_change
    assert last.coi_pcr == round(last.put_oi_change / last.call_oi_change, 4)
    assert last.spot == 100.5  # from spot_series
    # calls written harder than puts today -> DIFF negative -> Bearish
    assert last.diff_oi < 0 and last.sentiment == "Bearish"
    # per-mark deltas telescope back to the cumulative change
    assert sum(t.call_oi_change_delta for t in p.trace) == last.call_oi_change


def test_trace_stops_at_session_close():
    close = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)  # 15:30 IST
    after = datetime(2026, 9, 1, 12, 30, tzinfo=UTC)  # 18:00 IST — well after the bell
    legs = [
        OiLegSeries(
            strike=100.0,
            option_type="CE",
            oi=((OPEN, 1000), (close, 1400), (after, 1400)),
            premium=((OPEN, 3.0), (close, 2.4), (after, 2.4)),
        )
    ]
    p = build_oi_pulse(
        underlying_symbol="NIFTY",
        spot=100.0,
        expiry=EXPIRY,
        now=after,
        session_open=OPEN,
        session_close=close,
        legs=legs,
        config=OiPulseConfig(trace_step_min=60),
    )
    assert p.trace, "expected marks"
    last_ts = datetime.fromisoformat(p.trace[-1].ts)
    # never past the close + the closing-session grace (15:40 IST), never at `now`
    assert last_ts <= close + timedelta(minutes=10)
    assert last_ts < after
    # re-running later (a still-later `now`) gives the identical trace
    p2 = build_oi_pulse(
        underlying_symbol="NIFTY",
        spot=100.0,
        expiry=EXPIRY,
        now=after + timedelta(hours=2),
        session_open=OPEN,
        session_close=close,
        legs=legs,
        config=OiPulseConfig(trace_step_min=60),
    )
    assert [t.ts for t in p2.trace] == [t.ts for t in p.trace]


def _band_legs():
    # strikes 90..110 step 5, spot 100 -> ATM 100
    legs = []
    for k in (90, 95, 100, 105, 110):
        legs.append(_leg(k, "CE", 1000, 1000, 1200 + k, 3, 3, 3))
        legs.append(_leg(k, "PE", 1000, 1000, 900 + k, 3, 3, 3))
    return legs


def _pulse(legs, **kw):
    return build_oi_pulse(
        underlying_symbol="NIFTY",
        spot=100.0,
        expiry=EXPIRY,
        now=NOW,
        session_open=OPEN,
        legs=legs,
        config=OiPulseConfig(trace_step_min=45),
        **kw,
    )


def test_trace_window_symmetric_cuts_to_atm_band():
    legs = _band_legs()
    full = _pulse(legs)
    band = _pulse(legs, trace_window_up=1, trace_window_down=1)
    assert full.trace_window_up is None and full.trace_window_down is None
    assert band.trace_window_up == 1 and band.trace_window_down == 1
    assert band.trace_atm_strike == 100.0
    last_full, last_band = full.trace[-1], band.trace[-1]
    assert last_band.total_ce_oi < last_full.total_ce_oi
    # ATM ± 1 = {95, 100, 105}
    assert last_band.total_ce_oi == (1200 + 95) + (1200 + 100) + (1200 + 105)
    # ladder + top-level aggregates untouched
    assert [r.strike for r in band.rows] == [r.strike for r in full.rows]
    assert band.total_ce_oi == full.total_ce_oi


def test_trace_window_asymmetric_up_and_down():
    legs = _band_legs()
    # 2 above ATM, 0 below  ->  {100, 105, 110}
    up = _pulse(legs, trace_window_up=2, trace_window_down=0)
    assert up.trace_window_up == 2 and up.trace_window_down == 0
    assert up.trace[-1].total_ce_oi == (1200 + 100) + (1200 + 105) + (1200 + 110)

    # 1 below ATM only, up unlimited  ->  {95, 100, 105, 110}
    dn = _pulse(legs, trace_window_down=1)
    assert dn.trace_window_up is None and dn.trace_window_down == 1
    assert dn.trace[-1].total_ce_oi == sum(1200 + k for k in (95, 100, 105, 110))


def test_empty_legs_do_not_crash():
    p = build_oi_pulse(
        underlying_symbol="NIFTY",
        spot=100.0,
        expiry=EXPIRY,
        now=NOW,
        session_open=OPEN,
        legs=[],
    )
    assert p.rows == () and p.pcr_oi_now is None and p.bias == "BALANCED"
    assert p.trace == ()


def test_determinism():
    kw = dict(
        underlying_symbol="NIFTY",
        spot=100.0,
        expiry=EXPIRY,
        now=NOW,
        session_open=OPEN,
        legs=_basic_legs(),
    )
    assert oi_pulse_to_dict(build_oi_pulse(**kw)) == oi_pulse_to_dict(build_oi_pulse(**kw))
