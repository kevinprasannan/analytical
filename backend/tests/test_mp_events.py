"""Market Profile event layer (docs/14) — pure engine. No DB.

Golden scenarios + the two contract properties: determinism and no-look-ahead
(state as of bracket k derived only from brackets 0..k).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from analytical_core.enums import InstrumentType, Timeframe
from analytical_core.market_profile.config import MarketProfileConfig
from analytical_core.market_profile.engine import session_periods
from analytical_core.market_profile.events import (
    MP_EVENTS_VERSION,
    MPEventConfig,
    MPState,
    PriorProfile,
    run_event_engine,
)
from analytical_core.series import OHLCVSeries

IST = timezone(timedelta(hours=5, minutes=30))
SES_OPEN = datetime(2026, 9, 1, 9, 15, tzinfo=IST)  # a Tuesday
SES_CLOSE = datetime(2026, 9, 1, 15, 30, tzinfo=IST)

# small synthetic sessions: relax the profile-builder minimums
CFG = MarketProfileConfig(min_bins=4, min_periods_for_result=2, ib_periods=1)
EVCFG = MPEventConfig()


def _session_series(bracket_centers: list[float], *, half_width: float = 12.0) -> OHLCVSeries:
    """One M5 series for the whole session. ``bracket_centers[k]`` is the price the
    auction sits at during 30-min bracket k; each bracket gets 6 M5 bars (3 for the
    trailing 15-min partial) all spanning ``center ± half_width``."""
    periods = session_periods(SES_OPEN, SES_CLOSE, CFG.tpo_minutes, CFG.partial_period_policy)
    ts: list[datetime] = []
    o: list[float] = []
    h: list[float] = []
    lo: list[float] = []
    c: list[float] = []
    for p in periods:
        center = bracket_centers[min(p.index, len(bracket_centers) - 1)]
        n_bars = int((p.end - p.start).total_seconds() // 300)
        for b in range(n_bars):
            ts.append(p.start + timedelta(minutes=5 * b))
            o.append(center)
            h.append(center + half_width)
            lo.append(center - half_width)
            c.append(center)
    n = len(ts)
    return OHLCVSeries(
        timeframe=Timeframe.M5,
        ts=tuple(ts),
        open=tuple(o),
        high=tuple(h),
        low=tuple(lo),
        close=tuple(c),
        volume=tuple(0 for _ in range(n)),
        is_final=tuple(True for _ in range(n)),
        expected_grid_len=n,
    )


def _prior(vah=24000.0, val=23960.0, poc=23980.0, high=24010.0, low=23950.0, close=23985.0):
    return PriorProfile("2026-08-31", poc, vah, val, high, low, close)


def _run(centers, *, now=SES_CLOSE, prior=None, half_width=12.0, atr=120.0):
    return run_event_engine(
        _session_series(centers, half_width=half_width),
        config=CFG,
        evcfg=EVCFG,
        session_open=SES_OPEN,
        session_close=SES_CLOSE,
        session_date="2026-09-01",
        instrument_type=InstrumentType.INDEX,
        has_volume=False,
        price_ref=24000.0,
        underlying_symbol="NIFTY",
        prior=prior or _prior(),
        atr=atr,
        now=now,
    )


def _ev(res, ev_id):
    return next((e for e in res.events if e.id == ev_id), None)


# --------------------------------------------------------------------------------------


def test_insufficient_data_when_no_brackets():
    res = _run([24000.0], now=SES_OPEN)  # nothing has elapsed
    assert res.status == "INSUFFICIENT_DATA"
    assert res.events == []
    assert res.day_type is None


def test_acceptance_above_prev_vah_confirms_strong():
    # A,B just below prior VAH (24000); C.. sit at 24060 — every bin well above 24000
    centers = [23985, 23990] + [24060] * 11
    res = _run(centers)
    e = _ev(res, "MP-010")
    assert e is not None, [x.id for x in res.events]
    assert e.state == MPState.CONFIRMED.value
    assert e.strength == "STRONG"
    kinds = [h["evidence"].get("kind") for h in e.state_history]
    assert "ACCEPTANCE" in kinds
    # the downside acceptance event should not have fired
    assert _ev(res, "MP-011") is None or _ev(res, "MP-011").state != MPState.CONFIRMED.value


def test_failed_acceptance_above_prev_vah_invalidates():
    # break + develop above VAH, then fall back below and drag the POC down
    centers = [23990, 23990, 24060, 24060, 23930, 23930, 23930, 23930, 23930, 23930, 23930, 23930]
    res = _run(centers)
    e = _ev(res, "MP-010")
    assert e is not None
    assert e.state == MPState.INVALIDATED.value
    assert e.state_history[-1]["evidence"].get("kind") == "FAILED_ACCEPTANCE"


def test_opening_events_reflect_prior_range():
    res = _run([24200] * 13, prior=_prior())  # gap far above prior high (24010)
    o1 = _ev(res, "MP-001")
    o2 = _ev(res, "MP-002")
    assert o1.meta["location"] == "ABOVE_RANGE"
    assert o2.meta["above_prev_high"] is True and o2.meta["below_prev_low"] is False


def test_value_migration_up_when_session_trades_higher():
    centers = [24050] * 13  # whole session above prior value (VAH 24000)
    res = _run(centers)
    vm = _ev(res, "MP-030")
    assert vm is not None
    assert vm.meta["direction"] in ("UP", "UP_SKEW")
    assert vm.meta["topology"] in ("FULLY_ABOVE", "OVERLAP_HIGH")
    # developing value entirely outside prior VA should also have fired
    dvo = _ev(res, "MP-015")
    assert dvo is not None and dvo.direction == "UP"


def test_balance_session_reports_overlap_and_range_ish_day():
    # sit inside prior value all day
    res = _run([23980] * 13, half_width=10.0)
    vm = _ev(res, "MP-030")
    assert vm.meta["direction"] in ("OVERLAP", "UNCHANGED")
    assert res.day_type is not None
    assert res.day_type.day_type in {
        "NORMAL",
        "RANGE",
        "NORMAL_VARIATION",
        "UNDETERMINED",
    }


def test_day_type_and_silhouette_enum_valid():
    res = _run([23900, 23950, 24000, 24050, 24100, 24150, 24200, 24250, 24300, 24350, 24400, 24450])
    dt = res.day_type
    assert dt.day_type in {
        "NORMAL",
        "NORMAL_VARIATION",
        "TREND_UP",
        "TREND_DOWN",
        "DOUBLE_DISTRIBUTION",
        "NEUTRAL",
        "NEUTRAL_EXTREME",
        "RANGE",
        "LARGE_RANGE",
        "UNDETERMINED",
    }
    assert dt.silhouette in {
        "BALANCED_D",
        "P_SHAPE",
        "B_SHAPE",
        "THIN_I",
        "BIMODAL",
        "UNDETERMINED",
    }
    assert all(c["conditions_met"] <= c["conditions_total"] for c in dt.candidates)


# ---- contract properties -----------------------------------------------------------


def _serialise(res):
    return json.dumps(
        [
            {
                "id": e.id,
                "state": e.state,
                "strength": e.strength,
                "history": [(h["state"], h["bracket_index"]) for h in e.state_history],
            }
            for e in res.events
        ],
        sort_keys=True,
    )


def test_determinism_same_inputs_same_events():
    centers = [23990, 24060, 24060, 23930, 24070, 24070, 24070, 23950, 23950, 23950, 23950, 23950]
    a = _run(centers)
    b = _run(centers)
    assert _serialise(a) == _serialise(b)
    assert a.params_hash == b.params_hash


def test_params_hash_changes_with_config():
    centers = [24050] * 13
    base = _run(centers)
    other = run_event_engine(
        _session_series(centers),
        config=CFG,
        evcfg=MPEventConfig(accept_brackets=3),
        session_open=SES_OPEN,
        session_close=SES_CLOSE,
        session_date="2026-09-01",
        instrument_type=InstrumentType.INDEX,
        has_volume=False,
        price_ref=24000.0,
        underlying_symbol="NIFTY",
        prior=_prior(),
        atr=120.0,
        now=SES_CLOSE,
    )
    assert base.params_hash != other.params_hash


@pytest.mark.parametrize("k", [3, 5, 7, 9])
def test_no_look_ahead_state_as_of_bracket_k_is_a_prefix(k):
    """The MP-010 state_history produced with ``now`` at bracket k's close must be
    an exact prefix (by state + bracket_index) of the full-session history."""
    centers = [23990, 23990, 24060, 24060, 24060, 24060, 23920, 23920, 23920, 23920, 23920, 23920]
    periods = session_periods(SES_OPEN, SES_CLOSE, CFG.tpo_minutes, CFG.partial_period_policy)
    full = _ev(_run(centers), "MP-010")
    partial_res = _run(centers, now=periods[k].end)
    part = _ev(partial_res, "MP-010")
    if part is None:
        # nothing triggered yet by bracket k — allowed, but then full must not have
        # a transition at bracket <= k
        assert all(
            (h["bracket_index"] is None or h["bracket_index"] > k) for h in full.state_history
        )
        return
    fh = [
        (h["state"], h["bracket_index"])
        for h in full.state_history
        if (h["bracket_index"] or 0) <= k
    ]
    ph = [
        (h["state"], h["bracket_index"])
        for h in part.state_history
        if (h["bracket_index"] or 0) <= k
    ]
    assert ph == fh


def test_version_constant_semver():
    parts = MP_EVENTS_VERSION.split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts)


# ---- more golden coverage --------------------------------------------------------


def test_ib_acceptance_up_and_extension_sidedness():
    # IB = bracket A only (ib_periods=1) around 24000; then drive straight up
    centers = [24000, 24000, 24080, 24150, 24220, 24290, 24290, 24290, 24290, 24290, 24290, 24290]
    res = _run(centers, half_width=10.0)
    e19 = _ev(res, "MP-019")
    assert e19 is not None
    assert e19.state in (MPState.CONFIRMED.value, MPState.DEVELOPING.value)
    e52 = _ev(res, "MP-052")
    assert e52 is not None
    assert e52.meta["sidedness"] in ("ONE_SIDED_UP", "SOME", "TWO_SIDED")
    e51 = _ev(res, "MP-051")
    assert e51.meta["broken"] in ("UP", "BOTH")


def test_accept_above_prev_high_is_range_extreme_event():
    # prior high 24010; whole session at 24080 — accepts beyond the prior range
    res = _run([24080] * 13, half_width=8.0)
    e = _ev(res, "MP-016")
    assert e is not None
    assert e.state in (MPState.CONFIRMED.value, MPState.DEVELOPING.value)
    assert e.direction == "UP"


def test_narrative_rollup_present_after_upside_acceptance():
    centers = [23985, 23990] + [24060] * 11
    res = _run(centers)
    n = _ev(res, "MP-060")
    assert n is not None
    assert n.meta["outcome"].startswith("ACCEPTANCE") or n.meta["outcome"].startswith("ATTEMPTING")


def test_structure_event_reads_extremes_three_way():
    res = _run([23980] * 13, half_width=10.0)
    st = _ev(res, "MP-070")
    assert st is not None
    assert st.meta["high"] in ("EXCESS", "POOR", "NEITHER")
    assert st.meta["low"] in ("EXCESS", "POOR", "NEITHER")


def test_no_events_when_prior_profile_unavailable():
    res = _run([24050] * 13, prior=PriorProfile("2026-08-31", None, None, None, None, None, None))
    # opening events still fire as CONTEXT; acceptance/value/POC-vs-prior do not
    ids = {e.id for e in res.events}
    assert {"MP-001", "MP-002", "MP-003"} <= ids
    assert "MP-010" not in ids and "MP-030" not in ids and "MP-040" not in ids
    assert res.events and res.status == "OK"
