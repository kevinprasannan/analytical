"""`analytical_core.options.oi_pulse` — pure, deterministic (docs/05 §11.2)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from analytical_core.options import (
    OI_PULSE_VERSION,
    OiLegSeries,
    OiPulseConfig,
    build_ltp_trace,
    build_oi_ladder,
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


def test_ltp_trace_pairs_each_option_tick_with_the_underlying_at_or_before_it():
    premium = _series(3.0, 3.2, 3.6)  # matches the 100-CE leg above
    spot_series = (
        (OPEN, 100.0),
        (OPEN + timedelta(minutes=90), 101.5),
        (NOW - timedelta(minutes=1), 102.0),  # after the last premium tick
    )
    trace = build_ltp_trace(premium, spot_series)
    assert len(trace) == len(premium)
    assert [p.option_ltp for p in trace] == [3.0, 3.2, 3.6]
    # each underlying value is the spot sample at/before that same tick
    assert [p.underlying_ltp for p in trace] == [100.0, 101.5, 101.5]
    assert [p.ts for p in trace] == [t.isoformat() for t, _ in premium]
    assert [p.oi for p in trace] == [None, None, None]  # no oi_series passed


def test_ltp_trace_underlying_none_when_no_spot_sample_yet():
    premium = ((OPEN, 3.0),)
    trace = build_ltp_trace(premium, spot_series=())
    assert trace[0].underlying_ltp is None


def test_ltp_trace_carries_oi_at_or_before_each_tick():
    premium = _series(3.0, 3.2, 3.6)
    oi_series = (
        (OPEN, 2000),
        (OPEN + timedelta(minutes=90), 2200),
        (NOW - timedelta(minutes=1), 2600),  # after the last premium tick
    )
    trace = build_ltp_trace(premium, spot_series=(), oi_series=oi_series)
    assert [p.oi for p in trace] == [2000, 2200, 2200]


def test_ltp_trace_oi_none_when_no_oi_sample_yet():
    premium = ((OPEN, 3.0),)
    trace = build_ltp_trace(premium, spot_series=(), oi_series=())
    assert trace[0].oi is None


def test_ltp_trace_oi_change_is_relative_to_the_oi_series_first_sample():
    premium = _series(3.0, 3.2, 3.6)
    oi_series = (
        (OPEN, 2000),  # the session's opening read
        (OPEN + timedelta(minutes=90), 2200),
        (NOW - timedelta(minutes=1), 2600),
    )
    trace = build_ltp_trace(premium, spot_series=(), oi_series=oi_series)
    # last premium tick is before the last oi sample -> oi (and its change)
    # carries forward from the mid sample, same as test_ltp_trace_carries_oi_...
    assert [p.oi_change for p in trace] == [0, 200, 200]


def test_ltp_trace_oi_change_none_when_no_oi_series():
    premium = ((OPEN, 3.0),)
    trace = build_ltp_trace(premium, spot_series=(), oi_series=())
    assert trace[0].oi_change is None


def test_ltp_trace_empty_premium_is_empty():
    assert build_ltp_trace((), spot_series=((OPEN, 100.0),)) == ()


def _min_leg(strike, side, ois, *, base=OPEN, premiums=None):
    return OiLegSeries(
        strike=float(strike),
        option_type=side,
        oi=tuple((base + timedelta(minutes=i), v) for i, v in enumerate(ois)),
        premium=(
            tuple((base + timedelta(minutes=i), v) for i, v in enumerate(premiums))
            if premiums is not None
            else ()
        ),
    )


def _marks(n, *, base=OPEN):
    return tuple(base + timedelta(minutes=i) for i in range(n))


def test_oi_ladder_reports_oi_and_delta_per_mark():
    legs = [_min_leg(100, "CE", [2000, 2200, 2600])]
    marks = _marks(3)
    ladder = build_oi_ladder(legs, marks, spot=100.0)
    assert len(ladder.rows) == 1
    row = ladder.rows[0]
    assert row.strike == 100.0
    assert [c.oi for c in row.call] == [2000, 2200, 2600]
    assert [c.oi_delta for c in row.call] == [None, 200, 400]
    # no PE leg for this strike -> all-None cells, same length as marks
    assert [c.oi for c in row.put] == [None, None, None]
    assert [c.ltp for c in row.put] == [None, None, None]


def test_oi_ladder_reports_option_ltp_per_mark():
    legs = [_min_leg(100, "CE", [2000, 2200, 2600], premiums=[3.0, 3.2, 3.6])]
    ladder = build_oi_ladder(legs, _marks(3), spot=100.0)
    assert [c.ltp for c in ladder.rows[0].call] == [3.0, 3.2, 3.6]


def test_oi_ladder_option_ltp_none_when_no_premium_supplied():
    legs = [_min_leg(100, "CE", [2000, 2200, 2600])]  # premiums omitted
    ladder = build_oi_ladder(legs, _marks(3), spot=100.0)
    assert [c.ltp for c in ladder.rows[0].call] == [None, None, None]


def test_oi_ladder_atm_strike_is_nearest_to_spot():
    legs = [
        _min_leg(95, "PE", [10, 20, 30]),
        _min_leg(100, "CE", [10, 20, 30]),
        _min_leg(105, "CE", [10, 20, 30]),
    ]
    ladder = build_oi_ladder(legs, _marks(3), spot=101.0)
    assert ladder.atm_strike == 100.0


def test_oi_ladder_window_restricts_rows_around_atm():
    legs = [_min_leg(s, "CE", [10, 20, 30]) for s in (90, 95, 100, 105, 110)]
    ladder = build_oi_ladder(legs, _marks(3), spot=100.0, window_up=1, window_down=1)
    assert [r.strike for r in ladder.rows] == [95.0, 100.0, 105.0]


def test_oi_ladder_no_window_keeps_every_strike():
    legs = [_min_leg(s, "CE", [10, 20, 30]) for s in (90, 95, 100, 105, 110)]
    ladder = build_oi_ladder(legs, _marks(3), spot=100.0)
    assert [r.strike for r in ladder.rows] == [90.0, 95.0, 100.0, 105.0, 110.0]


def test_oi_ladder_empty_legs_or_marks_is_empty():
    assert build_oi_ladder([], _marks(3), spot=100.0).rows == ()
    assert build_oi_ladder([_min_leg(100, "CE", [10])], (), spot=100.0).rows[0].call == ()


def test_oi_ladder_underlying_at_marks_resolved_at_or_before_each_mark():
    legs = [_min_leg(100, "CE", [10, 20, 30])]
    marks = _marks(3)
    underlying_series = (
        (OPEN, 24000.0),
        (OPEN + timedelta(minutes=1), 24010.5),
        # no sample at/after minute 2 -> carries the last known value forward
    )
    ladder = build_oi_ladder(legs, marks, spot=100.0, underlying_series=underlying_series)
    assert ladder.underlying_at_marks == (24000.0, 24010.5, 24010.5)


def test_oi_ladder_underlying_at_marks_empty_when_no_series_given():
    ladder = build_oi_ladder([_min_leg(100, "CE", [10, 20, 30])], _marks(3), spot=100.0)
    assert ladder.underlying_at_marks == (None, None, None)
