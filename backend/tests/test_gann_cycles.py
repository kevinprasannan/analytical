"""Gann time cycles (docs/05 §9e) — day-count projections from the previous
swing low/high, confluence clustering, and filling in what actually happened
at a projection date that's already in the loaded series."""

from __future__ import annotations

from datetime import date, timedelta

from analytical_core.gann_cycles import scan_gann_cycles

P = {"horizon_days": 400}  # wide horizon so the fixed test dates aren't filtered out


def _series(n: int, base=date(2025, 1, 1)):
    dates = [(base + timedelta(days=i)).isoformat() for i in range(n)]
    highs = [100.0 + i * 0.1 for i in range(n)]
    lows = [99.0 + i * 0.1 for i in range(n)]
    closes = [99.5 + i * 0.1 for i in range(n)]
    return dates, highs, lows, closes


def test_insufficient_data():
    dates, highs, lows, closes = _series(3)
    r = scan_gann_cycles(dates, highs, lows, closes, today="2025-01-05", params=P)
    assert r.status == "INSUFFICIENT_DATA"
    assert r.swing_low is None and r.swing_high is None


def test_swing_low_and_high_are_the_window_extremes():
    dates, highs, lows, closes = _series(20)
    # carve out a clear single low and single high
    lows[5] = 50.0  # lowest low
    highs[15] = 200.0  # highest high
    r = scan_gann_cycles(dates, highs, lows, closes, today=dates[-1], params=P)
    assert r.status == "OK"
    assert r.swing_low.anchor_date == dates[5]
    assert r.swing_low.price == 50.0
    assert r.swing_high.anchor_date == dates[15]
    assert r.swing_high.price == 200.0


def test_projection_dates_are_anchor_plus_cycle_days():
    dates, highs, lows, closes = _series(10)
    lows[2] = 10.0
    highs[7] = 200.0
    r = scan_gann_cycles(
        dates, highs, lows, closes, today=dates[-1], params={**P, "cycle_days": (45, 90)}
    )
    low_anchor = date.fromisoformat(dates[2])
    high_anchor = date.fromisoformat(dates[7])
    targets = {(p.anchor_kind, p.cycle_days): p.target_date for p in r.projections}
    assert targets[("LOW", 45)] == (low_anchor + timedelta(days=45)).isoformat()
    assert targets[("LOW", 90)] == (low_anchor + timedelta(days=90)).isoformat()
    assert targets[("HIGH", 45)] == (high_anchor + timedelta(days=45)).isoformat()
    assert targets[("HIGH", 90)] == (high_anchor + timedelta(days=90)).isoformat()


def test_days_from_today_is_signed():
    dates, highs, lows, closes = _series(5)
    lows[0] = 10.0
    highs[1] = 20.0
    r = scan_gann_cycles(
        dates, highs, lows, closes, today=dates[-1], params={**P, "cycle_days": (45,)}
    )
    for proj in r.projections:
        expected = (date.fromisoformat(proj.target_date) - date.fromisoformat(dates[-1])).days
        assert proj.days_from_today == expected


def test_horizon_filters_out_far_projections():
    dates, highs, lows, closes = _series(5)
    lows[0] = 10.0
    highs[1] = 20.0
    r = scan_gann_cycles(
        dates,
        highs,
        lows,
        closes,
        today=dates[-1],
        params={"cycle_days": (45, 360), "horizon_days": 60},
    )
    cycle_lens = {p.cycle_days for p in r.projections}
    assert 45 in cycle_lens
    assert 360 not in cycle_lens  # 360 days out is well beyond a 60-day horizon


def test_nearby_projections_from_different_anchors_cluster():
    # construct anchors so LOW+45d lands on the exact same date as HIGH+90d:
    # high_anchor = low_anchor - 45  =>  high_anchor + 90 == low_anchor + 45
    dates, highs, lows, closes = _series(300)
    lows[200] = 10.0  # low anchor near the end of the window
    low_anchor = date.fromisoformat(dates[200])
    high_anchor = low_anchor - timedelta(days=45)
    hi_idx = min(
        range(len(dates)), key=lambda i: abs((date.fromisoformat(dates[i]) - high_anchor).days)
    )
    highs[hi_idx] = 500.0  # make it the window's max high unambiguously
    r = scan_gann_cycles(
        dates, highs, lows, closes, today=dates[-1], params={**P, "cycle_days": (45, 90)}
    )
    assert r.status == "OK"
    assert len(r.clusters) == 1
    cluster = r.clusters[0]
    assert cluster.strength == 2
    kinds = {p.anchor_kind for p in cluster.projections}
    assert kinds == {"LOW", "HIGH"}


def test_no_cluster_when_projections_are_far_apart():
    dates, highs, lows, closes = _series(200)
    lows[10] = 10.0
    highs[180] = 500.0
    r = scan_gann_cycles(
        dates, highs, lows, closes, today=dates[-1], params={**P, "cycle_days": (45, 90)}
    )
    assert r.clusters == []


def test_past_projection_is_filled_with_the_actual_bar():
    # today sits well after the series ends, and the projection lands inside
    # the loaded series -> it should resolve to that exact bar
    dates, highs, lows, closes = _series(200)
    lows[0] = 10.0  # low anchor at dates[0]
    highs[50] = 500.0  # keep the high anchor far away so it doesn't interfere
    target_idx = 45  # anchor(dates[0]) + 45 calendar days == dates[45] (no gaps in this series)
    r = scan_gann_cycles(
        dates,
        highs,
        lows,
        closes,
        today=dates[-1],
        params={**P, "cycle_days": (45,)},
    )
    low_45 = next(p for p in r.projections if p.anchor_kind == "LOW" and p.cycle_days == 45)
    assert low_45.target_date == dates[target_idx]
    assert low_45.resolved_date == dates[target_idx]
    assert low_45.actual_close == round(closes[target_idx], 4)
    assert low_45.actual_high == round(highs[target_idx], 4)
    assert low_45.actual_low == round(lows[target_idx], 4)


def test_future_projection_beyond_the_series_is_not_filled():
    dates, highs, lows, closes = _series(50)
    lows[0] = 10.0
    highs[5] = 500.0
    # today = the series' last date, so a long cycle projects well past the
    # data we have -> nothing to fill in yet
    r = scan_gann_cycles(
        dates,
        highs,
        lows,
        closes,
        today=dates[-1],
        params={"cycle_days": (360,), "horizon_days": 400},
    )
    assert r.projections  # not filtered out (within the wide horizon)
    for p in r.projections:
        assert p.resolved_date is None
        assert p.actual_close is None
        assert p.actual_high is None
        assert p.actual_low is None


def test_weekend_target_date_resolves_to_the_next_trading_day():
    # skip Saturday/Sunday like real trading dates, so a projection can land
    # on a non-trading day and must resolve forward to the next session
    base = date(2025, 1, 6)  # a Monday
    dates: list[str] = []
    d = base
    while len(dates) < 120:
        if d.weekday() < 5:
            dates.append(d.isoformat())
        d += timedelta(days=1)
    highs = [100.0] * len(dates)
    lows = [99.0] * len(dates)
    closes = [99.5] * len(dates)
    lows[0] = 10.0  # low anchor on the first Monday
    highs[10] = 500.0
    r = scan_gann_cycles(
        dates, highs, lows, closes, today=dates[-1], params={**P, "cycle_days": (45,)}
    )
    low_45 = next(p for p in r.projections if p.anchor_kind == "LOW" and p.cycle_days == 45)
    target = date.fromisoformat(low_45.target_date)
    resolved = date.fromisoformat(low_45.resolved_date)
    assert resolved >= target
    assert resolved.weekday() < 5  # landed on an actual trading day
    assert low_45.actual_close is not None
