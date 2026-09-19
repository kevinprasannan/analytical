"""Gap-fade streak study (docs/05 §9f) — down-streak length after a
gap-up-then-close-down day, up-streak length after a gap-down-then-close-up
day (the mirror reversal), consolidation box, and breakout direction."""

from __future__ import annotations

from datetime import date, timedelta

from analytical_core.gap_fade_study import scan_gap_fade_study

P = {
    "gap_up_min_pct": 0.5,
    "chg_down_max_pct": -0.5,
    "gap_down_max_pct": -0.5,
    "chg_up_min_pct": 0.5,
    "box_days": 3,
    "breakout_buffer_pct": 0.3,
}


def _dates(n: int, base=date(2025, 1, 1)) -> list[str]:
    return [(base + timedelta(days=i)).isoformat() for i in range(n)]


def _flat_series(n: int, price: float = 100.0):
    dates = _dates(n)
    opens = [price] * n
    highs = [price + 1] * n
    lows = [price - 1] * n
    closes = [price] * n
    return dates, opens, highs, lows, closes


def _summary(r, direction):
    return next(s for s in r.summaries if s.direction == direction)


def test_insufficient_data():
    dates, o, h, low, c = _flat_series(3)
    r = scan_gap_fade_study(dates, o, h, low, c, params=P)
    assert r.status == "INSUFFICIENT_DATA"


def test_no_qualifying_days_gives_empty_occurrences():
    dates, o, h, low, c = _flat_series(30)
    r = scan_gap_fade_study(dates, o, h, low, c, params=P)
    assert r.status == "OK"
    assert r.occurrences == []
    assert _summary(r, "UP").n_occurrences == 0
    assert _summary(r, "DOWN").n_occurrences == 0


def test_gap_up_fade_day_starts_a_streak_of_at_least_one():
    n = 20
    dates, o, h, low, c = _flat_series(n)
    # day 5: gap up 1% then closes down 1% vs prior close, no further down days after
    c[4] = 100.0
    o[5] = 101.0
    c[5] = 99.0
    h[5] = 101.5
    low[5] = 98.8
    # day 6 closes UP vs day 5 -> streak ends immediately at 1 day
    c[6] = 99.5
    r = scan_gap_fade_study(dates, o, h, low, c, params=P)
    occ = next(x for x in r.occurrences if x.event_date == dates[5])
    assert occ.direction == "UP"
    assert occ.streak_days == 1
    assert occ.streak_end_date == dates[5]
    assert abs(occ.gap_pct - 1.0) < 1e-6
    assert abs(occ.change_pct - (-1.0)) < 1e-6


def test_gap_down_fade_day_is_the_mirror_bullish_reversal():
    n = 20
    dates, o, h, low, c = _flat_series(n)
    # day 5: gap down 1% then closes up 1% vs prior close (a bullish reversal)
    c[4] = 100.0
    o[5] = 99.0
    c[5] = 101.0
    h[5] = 101.2
    low[5] = 98.5
    # day 6 closes DOWN vs day 5 -> up-streak ends immediately at 1 day
    c[6] = 100.5
    r = scan_gap_fade_study(dates, o, h, low, c, params=P)
    occ = next(x for x in r.occurrences if x.event_date == dates[5])
    assert occ.direction == "DOWN"
    assert occ.streak_days == 1
    assert occ.streak_end_date == dates[5]
    assert abs(occ.gap_pct - (-1.0)) < 1e-6
    assert abs(occ.change_pct - 1.0) < 1e-6


def test_multi_day_down_streak_is_counted_and_ends_correctly():
    n = 30
    dates, o, h, low, c = _flat_series(n)
    c[4] = 100.0
    o[5] = 101.0
    c[5] = 99.0  # event day, down day #1
    c[6] = 97.0  # down day #2
    c[7] = 95.0  # down day #3
    c[8] = 96.0  # up -> streak ends after day 7 (3 down days)
    r = scan_gap_fade_study(dates, o, h, low, c, params=P)
    occ = next(x for x in r.occurrences if x.event_date == dates[5])
    assert occ.streak_days == 3
    assert occ.streak_end_date == dates[7]


def test_multi_day_up_streak_is_counted_and_ends_correctly():
    n = 30
    dates, o, h, low, c = _flat_series(n)
    c[4] = 100.0
    o[5] = 99.0
    c[5] = 101.0  # event day, up day #1
    c[6] = 103.0  # up day #2
    c[7] = 105.0  # up day #3
    c[8] = 104.0  # down -> streak ends after day 7 (3 up days)
    r = scan_gap_fade_study(dates, o, h, low, c, params=P)
    occ = next(x for x in r.occurrences if x.event_date == dates[5])
    assert occ.direction == "DOWN"
    assert occ.streak_days == 3
    assert occ.streak_end_date == dates[7]


def test_streak_ongoing_when_data_runs_out():
    n = 10
    dates, o, h, low, c = _flat_series(n)
    c[n - 2] = 100.0
    o[n - 1] = 101.0
    c[n - 1] = 99.0  # event on the very last bar -> nothing follows
    r = scan_gap_fade_study(dates, o, h, low, c, params=P)
    occ = next(x for x in r.occurrences if x.event_date == dates[n - 1])
    assert occ.status == "STREAK_ONGOING"
    assert occ.box_start_date is None


def test_breakout_up_detected_beyond_the_buffer():
    n = 30
    dates, o, h, low, c = _flat_series(n, price=100.0)
    c[4] = 100.0
    o[5] = 101.0
    c[5] = 99.0  # event, streak ends same day (day 6 closes up)
    c[6] = 99.5
    # box days 6,7,8 -> use their high/low as-is (flat at 100/98)
    for i in (6, 7, 8):
        h[i] = 100.0
        low[i] = 98.0
        c[i] = 99.0
    # day 9 breaks the box high (100) by more than the 0.3% buffer
    c[9] = 100.5
    r = scan_gap_fade_study(dates, o, h, low, c, params=P)
    occ = next(x for x in r.occurrences if x.event_date == dates[5])
    assert occ.status == "BREAKOUT_UP"
    assert occ.breakout_date == dates[9]
    assert occ.box_high == 100.0
    assert occ.box_low == 98.0
    # box spans days 6-8 (3 days), day 9 is the breakout itself -> 3 consolidation days
    assert occ.consolidation_days == 3


def test_breakout_down_detected_beyond_the_buffer():
    n = 30
    dates, o, h, low, c = _flat_series(n, price=100.0)
    c[4] = 100.0
    o[5] = 101.0
    c[5] = 99.0
    c[6] = 99.5
    for i in (6, 7, 8):
        h[i] = 100.0
        low[i] = 98.0
        c[i] = 99.0
    c[9] = 97.5  # breaks below box_low (98) by more than 0.3%
    r = scan_gap_fade_study(dates, o, h, low, c, params=P)
    occ = next(x for x in r.occurrences if x.event_date == dates[5])
    assert occ.status == "BREAKOUT_DOWN"
    assert occ.breakout_date == dates[9]


def test_still_consolidating_when_no_breakout_within_search_window():
    n = 40
    dates, o, h, low, c = _flat_series(n, price=100.0)
    c[4] = 100.0
    o[5] = 101.0
    c[5] = 99.0
    c[6] = 99.5
    for i in range(6, n):
        h[i] = 100.0
        low[i] = 98.0
        c[i] = 99.0  # stays inside the box forever
    r = scan_gap_fade_study(dates, o, h, low, c, params={**P, "max_breakout_search_days": 10})
    occ = next(x for x in r.occurrences if x.event_date == dates[5])
    assert occ.status == "CONSOLIDATING"
    assert occ.breakout_date is None


def test_summary_aggregates_across_occurrences_per_direction():
    n = 60
    dates, o, h, low, c = _flat_series(n, price=100.0)
    # two independent UP (gap-up-fade) events, both resolving to a 1-day streak and an UP breakout
    for start in (5, 20):
        c[start - 1] = 100.0
        o[start] = 101.0
        c[start] = 99.0
        c[start + 1] = 99.5
        for i in (start + 1, start + 2, start + 3):
            h[i] = 100.0
            low[i] = 98.0
            c[i] = 99.0
        c[start + 4] = 100.5
    r = scan_gap_fade_study(dates, o, h, low, c, params=P)
    up = _summary(r, "UP")
    down = _summary(r, "DOWN")
    assert up.n_occurrences == 2
    assert up.n_breakout_resolved == 2
    assert up.breakout_up_count == 2
    assert up.breakout_down_count == 0
    assert up.breakout_up_pct == 100.0
    assert up.mean_streak_days == 1.0
    assert down.n_occurrences == 0


def test_up_and_down_reversals_are_tracked_independently():
    n = 60
    dates, o, h, low, c = _flat_series(n, price=100.0)
    # a UP event at day 5 (gap up, closes down)
    c[4] = 100.0
    o[5] = 101.0
    c[5] = 99.0
    c[6] = 99.5
    # a DOWN event at day 20 (gap down, closes up) -- unrelated window
    c[19] = 100.0
    o[20] = 99.0
    c[20] = 101.0
    c[21] = 100.5
    r = scan_gap_fade_study(dates, o, h, low, c, params=P)
    up_dates = {x.event_date for x in r.occurrences if x.direction == "UP"}
    down_dates = {x.event_date for x in r.occurrences if x.direction == "DOWN"}
    assert dates[5] in up_dates
    assert dates[20] in down_dates
    assert dates[5] not in down_dates
    assert dates[20] not in up_dates
