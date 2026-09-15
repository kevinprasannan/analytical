"""Opening-range breakout backtest (docs/16). Pure — descriptive, no signal."""

from __future__ import annotations

import pytest

from analytical_core.backtest import Bar, DayBars, OrbConfig, run_orb

# range 09:40-09:55 = minute 580..595 (exclusive), breakout 595..615, measure to 615
CFG = OrbConfig(range_start=580, range_end=595, break_start=595, break_end=615, measure_until=615)


def _day(date: str, wd: int, extra: list[tuple]) -> DayBars:
    """A flat 100–102 range in the range window, then the given breakout-window bars."""
    rng = [(m, 101.0, 102.0, 100.0, 101.0) for m in range(580, 595)]
    return DayBars(
        date=date,
        weekday=wd,
        bars=tuple(Bar(m, o, h, low, c) for (m, o, h, low, c) in rng + extra),
    )


def test_long_breakout_hits_both_targets():
    d = _day(
        "2026-01-05",
        0,
        [
            (600, 102.0, 103.0, 102.0, 103.0),  # 0.5x target (103) hit here
            (608, 103.0, 104.2, 103.0, 104.0),  # 1.0x target (104) hit here
            (612, 104.0, 104.0, 103.0, 103.5),
        ],
    )
    r = run_orb([d], CFG).days[0]
    assert r.direction == "LONG"
    assert (r.break_minute, r.break_immediate) == (600, False)
    assert r.entry_level == 102.0 and r.stop_level == 100.0
    assert r.stop_hit is False
    assert r.targets[0].hit and r.targets[0].minutes_to_hit == 0
    assert r.targets[1].hit and r.targets[1].minutes_to_hit == 8
    assert r.mfe_r == pytest.approx(1.1)  # high 104.2, entry 102, /2
    assert r.mae_r == pytest.approx(0.0)


def test_short_breakout_half_then_stopped():
    d = _day(
        "2026-01-06",
        1,
        [
            (598, 100.0, 100.0, 99.4, 99.6),
            (603, 99.6, 99.6, 99.0, 99.2),  # 0.5x (99.0) hit
            (609, 99.2, 102.1, 99.2, 102.0),  # stop (102) hit; 1.0x (98) never
        ],
    )
    r = run_orb([d], CFG).days[0]
    assert r.direction == "SHORT"
    assert r.break_minute == 598
    assert r.targets[0].hit and r.targets[0].minutes_to_hit == 5
    assert r.targets[1].hit is False and r.targets[1].stopped_first is True
    assert r.stop_hit and r.stop_minute == 609
    assert r.mae_r == pytest.approx(1.05)  # ran to 102.1 against a 100 entry


def test_no_breakout_is_direction_none():
    d = _day("2026-01-07", 2, [(m, 101.0, 101.5, 100.5, 101.0) for m in range(600, 615, 5)])
    r = run_orb([d], CFG).days[0]
    assert r.direction == "NONE"
    assert r.range_size == pytest.approx(2.0)  # range still computed
    assert r.note == "no breakout in the window"
    assert all(not t.hit for t in r.targets)


def test_immediate_breakout_when_already_outside():
    d = _day(
        "2026-01-08",
        3,
        [(595, 103.0, 104.0, 102.5, 103.5), (605, 103.5, 105.0, 103.0, 104.5)],
    )
    r = run_orb([d], CFG).days[0]
    assert r.direction == "LONG"
    assert r.break_immediate is True and r.break_minute == 595


def test_intrabar_tie_scores_stop_first():
    # after a clean LONG break at 600, the next bar spans both the 0.5x target
    # (103) and the stop (100) — stop wins
    d = _day(
        "2026-01-09",
        4,
        [(600, 102.0, 102.3, 102.0, 102.2), (605, 102.2, 103.5, 99.9, 100.1)],
    )
    r = run_orb([d], CFG).days[0]
    assert r.direction == "LONG" and r.break_minute == 600
    assert r.stop_hit is True and r.stop_minute == 605
    assert r.targets[0].hit is False and r.targets[0].stopped_first is True


def test_close_beyond_both_edges_is_decided_by_the_close():
    # a bar wicks through both edges; only the close (99.8, below r_lo) counts
    d = _day("2026-01-12", 0, [(600, 101.0, 102.5, 99.5, 99.8)])
    r = run_orb([d], CFG).days[0]
    assert r.direction == "SHORT" and r.break_minute == 600


def test_wick_shakeout_without_a_confirming_close_does_not_flip_the_call():
    # bar 1: wicks below the low (99.9) but CLOSES back inside -> not a breakout
    # bar 2: real breakout up, confirmed by its close -> LONG at 605
    d = _day(
        "2026-01-13",
        1,
        [
            (600, 101.0, 101.5, 99.9, 101.0),  # wick below 100, closes at 101 (inside)
            (605, 101.2, 103.0, 101.0, 102.8),  # closes above 102 -> confirmed LONG
        ],
    )
    r = run_orb([d], CFG).days[0]
    assert r.direction == "LONG"
    assert r.break_minute == 605  # not 600 — the wick alone didn't count


def test_immediate_breakout_requires_the_open_bar_to_also_close_confirmed():
    # opens above the high (103 > 102) but closes back inside the range -> no
    # immediate breakout; falls through to the normal scan
    d = _day(
        "2026-01-14",
        2,
        [
            (595, 103.0, 103.5, 101.5, 101.8),  # opened above, closed back inside
            (605, 101.8, 103.2, 101.5, 103.1),  # confirmed breakout here instead
        ],
    )
    r = run_orb([d], CFG).days[0]
    assert r.direction == "LONG"
    assert r.break_immediate is False
    assert r.break_minute == 605


def test_no_range_bars_note():
    d = DayBars(
        date="2026-01-13",
        weekday=1,
        bars=(Bar(600, 101, 102, 100, 101),),  # nothing in 580..595
    )
    r = run_orb([d], CFG).days[0]
    assert r.direction == "NONE" and r.note == "no bars in the range window"


def test_measure_until_cuts_the_path():
    # 1.0x would be reached at minute 620, but measure_until is 615
    cfg = OrbConfig(
        range_start=580, range_end=595, break_start=595, break_end=615, measure_until=615
    )
    d = _day(
        "2026-01-14",
        2,
        [(600, 102.0, 103.0, 102.0, 103.0), (620, 103.0, 106.0, 103.0, 105.0)],
    )
    r = run_orb([d], cfg).days[0]
    assert r.targets[0].hit is True  # 0.5x at 600
    assert r.targets[1].hit is False  # 1.0x only after the cutoff


def test_aggregate_rates():
    days = [
        _day("2026-01-05", 0, [(600, 102, 105, 102, 104)]),  # LONG, both targets
        _day("2026-01-06", 1, [(600, 102, 103, 102, 103)]),  # LONG, only 0.5x
        _day("2026-01-07", 2, [(m, 101, 101.5, 100.5, 101) for m in (600, 610)]),  # NONE
    ]
    a = run_orb(days, CFG).aggregate
    assert a.n_days == 3
    assert a.n_with_range == 3
    assert a.n_breakout == 2
    assert a.breakout_rate == pytest.approx(2 / 3, abs=1e-3)
    assert (a.n_long, a.n_short) == (2, 0)
    assert a.per_target[0].hit_rate == pytest.approx(1.0)  # 0.5x: 2/2
    assert a.per_target[1].hit_rate == pytest.approx(0.5)  # 1.0x: 1/2
    wd0 = next(w for w in a.by_weekday if w.weekday == 0)
    assert wd0.n_breakout == 1


def test_config_validation():
    with pytest.raises(ValueError, match="range_start must be"):
        run_orb([], OrbConfig(600, 590, 600, 620, 620))
    with pytest.raises(ValueError, match="minute-of-day"):
        run_orb([], OrbConfig(580, 595, 595, 615, 2000))
    with pytest.raises(ValueError, match="target_mults"):
        run_orb([], OrbConfig(580, 595, 595, 615, 615, target_mults=(0.0,)))


def test_deterministic():
    d = _day("2026-01-05", 0, [(600, 102, 105, 102, 104)])
    assert run_orb([d], CFG) == run_orb([d], CFG)
