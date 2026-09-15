"""Phase 2.4 — M1 → session-anchored M5/M15/H1 aggregation (docs/05 §3.3–§3.6)."""

from __future__ import annotations

import random
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest

from analytical_core.enums import Timeframe
from app.ingestion.aggregation import AGGREGATE_SOURCE, aggregate_all, aggregate_m1
from app.ingestion.session import (
    expected_grid_len,
    nse_session_window,
    session_grid,
    trading_date_of,
)
from app.providers.base import OHLCVBar

DAY = date(2026, 8, 27)
WIN = nse_session_window(DAY)
AFTER_CLOSE = WIN.close_utc + timedelta(minutes=10)
SRC = "upstox:v3/historical-candle"


def _m1(
    minute_offset: int,
    *,
    day: date = DAY,
    price: int | None = None,
    volume: int = 10,
    is_final: bool = True,
    oi: int | None = None,
    source: str = SRC,
) -> OHLCVBar:
    win = nse_session_window(day)
    ts = win.open_utc + timedelta(minutes=minute_offset)
    p = Decimal(100 + (minute_offset % 10) if price is None else price)
    return OHLCVBar(
        ts=ts,
        open=p,
        high=p + 2,
        low=p - 3,
        close=p + 1,
        volume=volume,
        is_final=is_final,
        source=source,
        open_interest=oi,
    )


def _full_session(day: date = DAY, **kw) -> list[OHLCVBar]:
    return [_m1(i, day=day, oi=5000 + i, **kw) for i in range(375)]


# ======================================================================================
# 1. aggregation contract / DTOs
# ======================================================================================


def test_result_shape_and_output_is_ohlcvbar():
    r = aggregate_m1(_full_session(), Timeframe.M5, now=AFTER_CLOSE)
    assert r.timeframe is Timeframe.M5
    assert r.empty_periods == []
    assert all(isinstance(b, OHLCVBar) for b in r.bars)
    assert all(b.source.startswith(AGGREGATE_SOURCE) for b in r.bars)
    assert all(b.source != "STUB_FIXTURE" for b in r.bars)


def test_target_must_be_an_aggregated_timeframe():
    for bad in (Timeframe.M1, Timeframe.D1):
        with pytest.raises(ValueError):
            aggregate_m1(_full_session(), bad, now=AFTER_CLOSE)


def test_empty_input_yields_no_bars():
    r = aggregate_m1([], Timeframe.H1, now=AFTER_CLOSE)
    assert r.bars == [] and r.empty_periods == []


def test_naive_timestamps_are_rejected():
    naive = OHLCVBar(
        ts=datetime(2026, 8, 27, 4, 0),
        open=Decimal(1),
        high=Decimal(1),
        low=Decimal(1),
        close=Decimal(1),
        volume=0,
        is_final=True,
        source=SRC,
    )
    with pytest.raises(ValueError):
        aggregate_m1([naive], Timeframe.M5, now=AFTER_CLOSE)


def test_synthetic_origin_stays_visible_in_source():
    r = aggregate_m1(_full_session(source="STUB_FIXTURE"), Timeframe.H1, now=AFTER_CLOSE)
    assert all("STUB_FIXTURE" in b.source for b in r.bars)


# ======================================================================================
# 2. session grid
# ======================================================================================


def test_session_window_is_0915_1530_ist_in_utc():
    assert WIN.open_utc == datetime(2026, 8, 27, 3, 45, tzinfo=UTC)
    assert WIN.close_utc == datetime(2026, 8, 27, 10, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("tf", "count", "last_partial"),
    [(Timeframe.M5, 75, False), (Timeframe.M15, 25, False), (Timeframe.H1, 7, True)],
)
def test_default_session_grid_counts(tf, count, last_partial):
    grid = session_grid(WIN, tf)
    assert len(grid) == count == expected_grid_len(WIN, tf)
    assert grid[0].start_utc == WIN.open_utc
    assert grid[-1].end_utc == WIN.close_utc
    assert grid[-1].is_partial is last_partial
    # contiguous, non-overlapping
    for a, b in zip(grid, grid[1:], strict=False):
        assert a.end_utc == b.start_utc


def test_h1_grid_matches_the_documented_boundaries():
    grid = session_grid(WIN, Timeframe.H1)
    starts = [p.start_utc.strftime("%H:%M") for p in grid]
    assert starts == ["03:45", "04:45", "05:45", "06:45", "07:45", "08:45", "09:45"]
    assert [p.is_partial for p in grid] == [False] * 6 + [True]
    assert grid[-1].end_utc - grid[-1].start_utc == timedelta(minutes=15)


def test_shortened_session_uses_the_generic_floor_plus_partial_rule():
    short = nse_session_window(DAY, close_ist=time(13, 0))  # 225-minute session
    h1 = session_grid(short, Timeframe.H1)
    assert [p.is_partial for p in h1] == [False, False, False, True]  # floor(225/60)=3 + partial
    assert h1[-1].end_utc - h1[-1].start_utc == timedelta(minutes=45)
    m15 = session_grid(short, Timeframe.M15)
    assert len(m15) == 15 and not any(p.is_partial for p in m15)  # 225/15 exact


def test_session_grid_rejects_non_aggregated_timeframe():
    for bad in (Timeframe.M1, Timeframe.D1):
        with pytest.raises(ValueError):
            session_grid(WIN, bad)


# ======================================================================================
# 3–5. M5 / M15 / H1 aggregation values
# ======================================================================================


@pytest.mark.parametrize(
    ("tf", "n_bars", "children_per_bar"),
    [(Timeframe.M5, 75, 5), (Timeframe.M15, 25, 15), (Timeframe.H1, 7, 60)],
)
def test_ohlc_volume_oi_folding_rule(tf, n_bars, children_per_bar):
    r = aggregate_m1(_full_session(), tf, now=AFTER_CLOSE)
    assert len(r.bars) == n_bars

    first = r.bars[0]
    # children 0..children_per_bar-1 for the first period
    kids = _full_session()[:children_per_bar]
    assert first.ts == WIN.open_utc  # anchored to the grid, not the first child
    assert first.open == kids[0].open
    assert first.close == kids[-1].close
    assert first.high == max(k.high for k in kids)
    assert first.low == min(k.low for k in kids)
    assert first.volume == sum(k.volume for k in kids)
    assert first.open_interest == kids[-1].open_interest  # last child OI (a level)


def test_h1_has_six_full_bars_then_a_15_minute_partial():
    r = aggregate_m1(_full_session(volume=10), Timeframe.H1, now=AFTER_CLOSE)
    assert [b.ts.strftime("%H:%M") for b in r.bars] == [
        "03:45",
        "04:45",
        "05:45",
        "06:45",
        "07:45",
        "08:45",
        "09:45",
    ]
    assert [b.volume for b in r.bars] == [600] * 6 + [150]  # 60 vs 15 M1 children
    assert r.bars[-1].ts == datetime(2026, 8, 27, 9, 45, tzinfo=UTC)


def test_bar_ts_is_grid_anchor_even_when_the_period_opens_with_a_gap():
    # only minutes 3 and 4 of the first M5 period are present
    bars = [_m1(3, oi=1), _m1(4, oi=2)]
    r = aggregate_m1(bars, Timeframe.M5, now=AFTER_CLOSE)
    assert len(r.bars) == 1
    assert r.bars[0].ts == WIN.open_utc  # 03:45Z, not 03:48Z
    assert r.bars[0].open == bars[0].open and r.bars[0].close == bars[1].close


def test_timestamps_stay_bar_open_utc():
    r = aggregate_all(_full_session(), now=AFTER_CLOSE)
    for res in r.values():
        for b in res.bars:
            assert b.ts.tzinfo is UTC
            assert b.ts.second == 0 and b.ts.microsecond == 0


def test_input_order_does_not_matter():
    src = _full_session()
    shuffled = src[:]
    random.Random(7).shuffle(shuffled)
    a = aggregate_m1(src, Timeframe.H1, now=AFTER_CLOSE)
    b = aggregate_m1(shuffled, Timeframe.H1, now=AFTER_CLOSE)
    assert a.bars == b.bars


def test_multi_day_input_is_grouped_by_ist_session_date():
    day2 = date(2026, 8, 28)
    bars = _full_session(DAY) + _full_session(day2)
    r = aggregate_m1(
        bars, Timeframe.H1, now=nse_session_window(day2).close_utc + timedelta(hours=1)
    )
    dates = sorted({trading_date_of(b.ts) for b in r.bars})
    assert dates == [DAY, day2]
    assert len(r.bars) == 14  # 7 per session


# ======================================================================================
# 6. partial-session / empty-interval handling
# ======================================================================================


def test_empty_periods_are_reported_but_never_emitted():
    # one M1 bar in the first M15 period, nothing else
    r = aggregate_m1([_m1(2, oi=9)], Timeframe.M15, now=AFTER_CLOSE)
    assert len(r.bars) == 1
    assert len(r.empty_periods) == 24  # 25 periods, 1 filled
    assert all(p.timeframe is Timeframe.M15 for p in r.empty_periods)
    # nothing fabricated for the gaps
    assert r.bars[0].ts == WIN.open_utc


def test_sparse_session_emits_only_periods_with_a_child():
    # M1 bars only in periods 0, 3 and the last (partial) H1 period
    offsets = [0, 1, 180, 181, 370, 374]
    r = aggregate_m1([_m1(o, oi=o) for o in offsets], Timeframe.H1, now=AFTER_CLOSE)
    kept = [b.ts.strftime("%H:%M") for b in r.bars]
    assert kept == ["03:45", "06:45", "09:45"]
    assert len(r.empty_periods) == 4


def test_pre_open_and_post_close_bars_are_excluded():
    pre = _m1(-5, oi=1)  # 09:10 IST
    post = OHLCVBar(
        ts=WIN.close_utc + timedelta(minutes=1),
        open=Decimal(1),
        high=Decimal(1),
        low=Decimal(1),
        close=Decimal(1),
        volume=99,
        is_final=True,
        source=SRC,
        open_interest=1,
    )
    inside = _m1(0, oi=2)
    r = aggregate_m1([pre, inside, post], Timeframe.M5, now=AFTER_CLOSE)
    assert len(r.bars) == 1
    assert r.bars[0].volume == inside.volume  # 99-volume post-close bar not folded in


def test_shortened_session_partial_bar_is_produced():
    def session_for(d: date):
        return nse_session_window(d, close_ist=time(13, 0))  # 225-minute session

    bars = [_m1(i, oi=1) for i in range(225)]  # 09:15–12:59 IST, one per minute
    r = aggregate_m1(
        bars,
        Timeframe.H1,
        session_for=session_for,
        now=datetime(2026, 8, 27, 8, 0, tzinfo=UTC),
    )
    assert len(r.bars) == 4  # floor(225/60) = 3 full + 1 partial
    assert r.bars[-1].ts == datetime(2026, 8, 27, 6, 45, tzinfo=UTC)  # 12:15 IST
    assert r.bars[-1].volume == 45 * 10  # 45 one-minute children, default volume 10


# ======================================================================================
# 7. is_final behaviour
# ======================================================================================


def test_is_final_requires_all_children_final_and_period_plus_grace():
    r = aggregate_m1(_full_session(), Timeframe.H1, now=AFTER_CLOSE, finalize_grace_seconds=90)
    assert all(b.is_final for b in r.bars)


def test_not_final_before_grace_elapses():
    # now = exactly the first H1 period end (04:45Z) — grace not yet elapsed
    r = aggregate_m1(
        _full_session(),
        Timeframe.H1,
        now=WIN.open_utc + timedelta(hours=1),
        finalize_grace_seconds=90,
    )
    assert r.bars[0].is_final is False
    r2 = aggregate_m1(
        _full_session(),
        Timeframe.H1,
        now=WIN.open_utc + timedelta(hours=1, seconds=90),
        finalize_grace_seconds=90,
    )
    assert r2.bars[0].is_final is True


def test_a_single_non_final_child_makes_the_period_non_final():
    bars = _full_session()
    bars[2] = _m1(2, oi=5002, is_final=False)  # inside the first M5/M15/H1 period
    r = aggregate_m1(bars, Timeframe.M5, now=AFTER_CLOSE)
    assert r.bars[0].is_final is False
    assert r.bars[1].is_final is True  # later period unaffected


def test_forming_last_partial_h1_bar_is_not_final_mid_session():
    # session still open: now is 15:20 IST, last (partial) period ends 15:30 IST
    mid = datetime(2026, 8, 27, 9, 50, tzinfo=UTC)
    present = [_m1(i, oi=i, is_final=(i < 370)) for i in range(374)]
    r = aggregate_m1(present, Timeframe.H1, now=mid)
    assert r.bars[-1].ts == datetime(2026, 8, 27, 9, 45, tzinfo=UTC)  # the partial period
    assert r.bars[-1].is_final is False  # period end 10:00Z is in the future


# ======================================================================================
# aggregate_all
# ======================================================================================


def test_aggregate_all_covers_the_three_timeframes_consistently():
    got = aggregate_all(_full_session(), now=AFTER_CLOSE)
    assert set(got) == {Timeframe.M5, Timeframe.M15, Timeframe.H1}
    assert [len(got[tf].bars) for tf in (Timeframe.M5, Timeframe.M15, Timeframe.H1)] == [75, 25, 7]
    # same source of truth as calling aggregate_m1 directly
    assert (
        got[Timeframe.H1].bars == aggregate_m1(_full_session(), Timeframe.H1, now=AFTER_CLOSE).bars
    )
