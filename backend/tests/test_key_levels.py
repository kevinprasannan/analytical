"""Key levels from the last two sessions' profiles (docs/05 §10.12).

Pure, deterministic. Descriptive — proximity tiers + acceptance, no bias / BUY-SELL.
"""

from __future__ import annotations

import pytest

from analytical_core.market_profile import (
    KEY_LEVELS_VERSION,
    Bands,
    LevelSession,
    RecentBar,
    build_key_levels,
)

_B = Bands(at=15.0, near=30.0, approaching=45.0)


def _d1() -> LevelSession:
    return LevelSession(
        label="D-1",
        date="2026-09-04",
        shape="NORMAL",
        day_type="RANGE",
        poc=24000.0,
        vah=24060.0,
        val=23940.0,
        ib_high=24040.0,
        ib_low=23960.0,
        high=24085.0,
        low=23915.0,
        close=24050.0,
        complete=True,
    )


def _d2() -> LevelSession:
    return LevelSession(
        label="D-2",
        date="2026-09-03",
        shape="TREND_UP",
        day_type="TREND_UP",
        poc=23900.0,
        vah=23950.0,
        val=23850.0,
        ib_high=23930.0,
        ib_low=23860.0,
        high=23980.0,
        low=23820.0,
        close=23970.0,
        complete=True,
    )


def test_bands_validate():
    with pytest.raises(ValueError):
        build_key_levels([_d1()], last_price=24000.0, bands=Bands(30, 15, 45))


def test_levels_extracted_and_sorted_desc():
    v = build_key_levels([_d1(), _d2()], last_price=24010.0, bands=_B)
    assert v.key_levels_version == KEY_LEVELS_VERSION
    # 7 levels per session (all fields present)
    assert len(v.levels) == 14
    assert [x.price for x in v.levels] == sorted((x.price for x in v.levels), reverse=True)
    kinds = {x.kind for x in v.levels}
    assert kinds == {"POC", "VAH", "VAL", "IB_HIGH", "IB_LOW", "HIGH", "LOW"}


def test_proximity_tiers_and_side():
    # price 24010: D-1 IB_HIGH 24040 -> +30 -> NEAR/APPROACHING boundary
    v = build_key_levels([_d1()], last_price=24010.0, bands=_B)
    by = {(x.kind, x.session): x for x in v.levels}
    poc = by[("POC", "D-1")]  # 24000, -10 -> AT, below
    assert poc.tier == "AT" and poc.side == "BELOW" and poc.distance == -10.0
    vah = by[("VAH", "D-1")]  # 24060, +50 -> FAR, above
    assert vah.tier == "FAR" and vah.side == "ABOVE"
    ibh = by[("IB_HIGH", "D-1")]  # 24040, +30 -> NEAR (<=30)
    assert ibh.tier == "NEAR"


def test_alerts_are_non_far_nearest_first():
    v = build_key_levels([_d1(), _d2()], last_price=24010.0, bands=_B)
    assert all(a.tier != "FAR" for a in v.alerts)
    d = [abs(a.distance) for a in v.alerts]
    assert d == sorted(d)


def test_nearest_above_below():
    v = build_key_levels([_d1(), _d2()], last_price=24010.0, bands=_B)
    assert v.nearest_above is not None and v.nearest_above.side == "ABOVE"
    assert v.nearest_below is not None and v.nearest_below.side == "BELOW"
    assert v.nearest_above.distance == min(
        x.distance for x in v.levels if x.side == "ABOVE"
    )
    assert v.nearest_below.distance == max(
        x.distance for x in v.levels if x.side == "BELOW"
    )


def test_close_vs_value_per_session():
    v = build_key_levels([_d1(), _d2()], last_price=24010.0, bands=_B)
    s1, s2 = v.sessions
    assert s1["close_vs_value"] == "INSIDE"  # 24050 within 23940–24060
    assert s2["close_vs_value"] == "ABOVE"  # 23970 > VAH 23950


def test_acceptance_accepted_above():
    # last 3 M5 closes all above D-1 POC 24000, price above + near it -> ACCEPTED_ABOVE
    recent = [RecentBar(24008, 23996, 24004), RecentBar(24014, 24001, 24010), RecentBar(24020, 24006, 24016)]
    v = build_key_levels([_d1()], last_price=24016.0, bands=_B, recent=recent)
    poc = next(x for x in v.levels if x.kind == "POC")
    assert poc.tier == "NEAR" and poc.acceptance == "ACCEPTED_ABOVE"


def test_acceptance_rejected_from_above():
    # price was above POC, a bar poked higher then closed back under, now under it
    # — the recent closes are NOT all below (so it isn't a clean accept-below),
    # but a bar's high cleared the level and closed back -> REJECTED_FROM_ABOVE
    recent = [
        RecentBar(24012, 23998, 24008),  # close above
        RecentBar(24016, 23990, 23996),  # high > 24000, close back below
        RecentBar(23999, 23982, 23990),
    ]
    v = build_key_levels([_d1()], last_price=23992.0, bands=_B, recent=recent)
    poc = next(x for x in v.levels if x.kind == "POC")
    assert poc.acceptance == "REJECTED_FROM_ABOVE"


def test_acceptance_none_for_far_levels():
    v = build_key_levels([_d1()], last_price=24010.0, bands=_B, recent=[RecentBar(1, 1, 1)])
    far = [x for x in v.levels if x.tier == "FAR"]
    assert far and all(x.acceptance is None for x in far)


def test_deterministic():
    a = build_key_levels([_d1(), _d2()], last_price=24010.0, bands=_B)
    b = build_key_levels([_d1(), _d2()], last_price=24010.0, bands=_B)
    assert a == b


def test_missing_session_fields_skipped():
    thin = LevelSession(
        label="D-1", date="2026-09-04", shape=None, day_type=None,
        poc=24000.0, vah=None, val=None, ib_high=None, ib_low=None,
        high=None, low=None, close=None, complete=False,
    )
    v = build_key_levels([thin], last_price=24010.0, bands=_B)
    assert [x.kind for x in v.levels] == ["POC"]
    assert v.sessions[0]["close_vs_value"] is None
