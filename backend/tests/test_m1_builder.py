"""Pure M1-from-ticks builder (docs/02 §3.4, docs/05 §3)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from analytical_core.streaming import M1Accumulator, Tick

T0 = datetime(2026, 8, 31, 3, 45, 0, tzinfo=UTC)  # 09:15 IST, bar-open


def _t(iid, sec, ltp, cum, oi=None):
    return Tick(iid, T0 + timedelta(seconds=sec), ltp, cum, oi)


def test_single_minute_ohlcv_and_volume_delta():
    a = M1Accumulator(grace_seconds=90)
    assert a.on_tick(_t(1, 0, 100.0, 0)) == []
    assert a.on_tick(_t(1, 10, 102.0, 30)) == []
    assert a.on_tick(_t(1, 20, 99.0, 55)) == []
    assert a.on_tick(_t(1, 40, 101.0, 80)) == []
    # roll into the next minute
    bars = a.on_tick(_t(1, 65, 101.5, 90))
    assert len(bars) == 1
    b = bars[0]
    assert b.minute == T0
    assert (b.open, b.high, b.low, b.close) == (100.0, 102.0, 99.0, 101.0)
    assert b.volume == 80  # 80 (last cum in the minute) − 0 (carried)
    assert b.is_final is False  # only 5s past minute end, grace is 90s


def test_volume_is_delta_across_minutes():
    a = M1Accumulator()
    out = []
    for tk in (
        _t(1, 5, 100.0, 200),  # first tick: 200 already traded this session
        _t(1, 30, 100.0, 260),
        _t(1, 70, 100.0, 275),  # rolls minute 0 -> vol = 260 - 200 = 60
        _t(1, 130, 100.0, 300),  # rolls minute 1 -> vol = 275 - 260 = 15
    ):
        out += a.on_tick(tk)
    assert [b.volume for b in out] == [60, 15]


def test_oi_carries_when_tick_has_none():
    a = M1Accumulator()
    a.on_tick(_t(1, 0, 100.0, 0, oi=15_000))
    a.on_tick(_t(1, 20, 100.0, 10, oi=None))
    a.on_tick(_t(1, 40, 100.0, 20, oi=15_250))
    (b,) = a.on_tick(_t(1, 65, 100.0, 25))
    assert b.open_interest == 15_250


def test_out_of_order_tick_for_a_closed_minute_is_ignored():
    a = M1Accumulator()
    a.on_tick(_t(1, 10, 100.0, 10))
    rolled = a.on_tick(_t(1, 70, 105.0, 40))
    assert rolled and rolled[0].close == 100.0
    # a late tick timestamped back in minute 0 must not resurrect it
    assert a.on_tick(_t(1, 30, 999.0, 999)) == []
    assert a.pending()[0].minute == rolled[0].minute + timedelta(minutes=1)


def test_zero_tick_minute_produces_no_bar():
    a = M1Accumulator()
    a.on_tick(_t(1, 5, 100.0, 10))  # minute 0
    bars = a.on_tick(_t(1, 130, 101.0, 20))  # jumps straight to minute 2
    assert len(bars) == 1 and bars[0].minute == T0  # only minute 0 emitted
    # minute 1 (no ticks) yields nothing, ever
    assert all(b.minute != T0 + timedelta(minutes=1) for b in a.flush(T0 + timedelta(minutes=10)))


def test_flush_finalises_after_grace_and_drops_the_bucket():
    a = M1Accumulator(grace_seconds=90)
    a.on_tick(_t(1, 5, 100.0, 10))
    a.on_tick(_t(1, 40, 101.0, 55))
    # not yet: minute 0 ends at +60s, grace to +150s
    forming = a.flush(T0 + timedelta(seconds=120))
    assert len(forming) == 1 and forming[0].is_final is False
    final = a.flush(T0 + timedelta(seconds=151))
    assert len(final) == 1 and final[0].is_final is True
    assert final[0].volume == 45 and final[0].close == 101.0  # 55 - 10
    assert a.flush(T0 + timedelta(minutes=10)) == []  # bucket was dropped


def test_instruments_are_independent():
    a = M1Accumulator()
    a.on_tick(_t(1, 0, 100.0, 0))
    a.on_tick(_t(2, 0, 500.0, 0))
    a.on_tick(_t(1, 20, 110.0, 40))
    b1 = a.on_tick(_t(1, 65, 111.0, 45))
    assert b1[0].instrument_id == 1 and b1[0].high == 110.0
    pend = {b.instrument_id: b for b in a.pending()}
    assert pend[2].close == 500.0 and pend[1].open == 111.0
