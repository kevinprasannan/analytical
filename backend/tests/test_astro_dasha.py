"""Pure Vimshottari dasha grid (docs/13 §5.6) — arithmetic only, no IO."""

from __future__ import annotations

import pytest

from app.astro.dasha import (
    NAK_SPAN_DEG,
    VIM_ORDER,
    VIM_TOTAL_YEARS,
    VIM_YEARS,
    kp_chain,
    moon_dasha,
    moon_dasha_head,
    vimshottari_grid,
)


def test_years_sum_to_120():
    assert sum(VIM_YEARS.values()) == VIM_TOTAL_YEARS == 120


def test_grid_shape_and_default_anchor():
    g = vimshottari_grid()  # 390 min, start Ketu
    assert g["total_years"] == 120
    assert g["total_minutes"] == 390.0
    assert g["total_hms"] == "6:30:00"
    assert g["start_lord"] == "Ketu"
    assert [r["lord"] for r in g["rows"]] == list(VIM_ORDER)  # Ketu-anchored == canonical
    assert all(len(r["antardashas"]) == 9 for r in g["rows"])
    # antardasha columns are the fixed order on every row (grid alignment)
    for r in g["rows"]:
        assert [c["lord"] for c in r["antardashas"]] == list(VIM_ORDER)


def test_mahadasha_minutes_scale_to_session():
    g = vimshottari_grid(390.0)
    by_lord = {r["lord"]: r for r in g["rows"]}
    # Ketu 7y of 120 over 390 min -> 22.75 min
    assert by_lord["Ketu"]["minutes"] == pytest.approx(22.75)
    assert by_lord["Ketu"]["hms"] == "0:22:45"
    # every mahadasha minute total sums back to the session
    assert sum(r["minutes"] for r in g["rows"]) == pytest.approx(390.0)
    # every mahadasha year total sums back to 120
    assert sum(r["years"] for r in g["rows"]) == 120


def test_antardasha_ratio():
    g = vimshottari_grid(390.0)
    ketu = next(r for r in g["rows"] if r["lord"] == "Ketu")
    cells = {c["lord"]: c for c in ketu["antardashas"]}
    # Ke-Ve = 7 * 20 / 120 years -> of 390 min: 22.75 * 20/120 = 3.7916..
    assert cells["Venus"]["minutes"] == pytest.approx(22.75 * 20 / 120)
    assert cells["Venus"]["hms"] == "0:03:48"
    # antardashas of a period sum back to that period
    assert sum(c["minutes"] for c in ketu["antardashas"]) == pytest.approx(ketu["minutes"])
    assert sum(c["years"] for c in ketu["antardashas"]) == pytest.approx(ketu["years"])


def test_saturn_saturn_cell():
    g = vimshottari_grid(390.0)
    sat = next(r for r in g["rows"] if r["lord"] == "Saturn")
    sa_sa = next(c for c in sat["antardashas"] if c["lord"] == "Saturn")
    # 19 * 19 / 120 years -> 390 * (19/120) * (19/120) min
    assert sa_sa["minutes"] == pytest.approx(390.0 * (19 / 120) * (19 / 120))
    assert sa_sa["hms"] == "0:09:47"


def test_start_lord_rotation():
    g = vimshottari_grid(390.0, start_lord="Moon")
    assert g["rows"][0]["lord"] == "Moon"
    assert g["order"][0] == "Moon"
    assert g["order"] == [
        "Moon",
        "Mars",
        "Rahu",
        "Jupiter",
        "Saturn",
        "Mercury",
        "Ketu",
        "Venus",
        "Sun",
    ]
    # antardasha grid columns stay canonical regardless of anchor
    assert [c["lord"] for c in g["rows"][0]["antardashas"]] == list(VIM_ORDER)
    # but the chronological sub-sequence starts with the period lord
    assert g["rows"][0]["antardasha_sequence"][0] == "Moon"


def test_years_only_mode():
    g = vimshottari_grid(None)
    assert g["total_minutes"] is None
    assert g["total_hms"] is None
    for r in g["rows"]:
        assert r["minutes"] is None and r["hms"] is None
        assert r["years"] == VIM_YEARS[r["lord"]]
        for c in r["antardashas"]:
            assert c["minutes"] is None and c["hms"] is None


def test_400_minute_session():
    g = vimshottari_grid(400.0)
    assert sum(r["minutes"] for r in g["rows"]) == pytest.approx(400.0)
    ketu = next(r for r in g["rows"] if r["lord"] == "Ketu")
    assert ketu["minutes"] == pytest.approx(400.0 * 7 / 120)


def test_bad_lord_raises():
    with pytest.raises(ValueError, match="unknown lord"):
        vimshottari_grid(390.0, start_lord="Pluto")


# ---------------------------------------------------------------------------
# Moon-anchored dasha (balance-of-dasha compressed onto a session)
# ---------------------------------------------------------------------------

# Moon 75% through Rohini (nakshatra idx 3 -> lord Moon); Rohini starts at 40°.
ROHINI_75 = 3 * NAK_SPAN_DEG + 0.75 * NAK_SPAN_DEG


def test_moon_dasha_identifies_nakshatra_lord_and_balance():
    d = moon_dasha(ROHINI_75, cycle_minutes=390.0, levels=2)
    assert d["calculation_method"] == "MOON_BASED"
    assert d["subdivision_minutes"] == 390.0
    assert d["nakshatra"] == "Rohini"
    assert d["pada"] in (3, 4)  # ~75% through the 4 padas
    assert d["dasha_lord"] == "Moon"
    assert d["elapsed_fraction"] == pytest.approx(0.75)
    assert d["remaining_fraction"] == pytest.approx(0.25)
    # Moon MD full over 390 = 390 * 10/120 = 32.5 min; balance = 25% of that
    assert d["balance_minutes"] == pytest.approx(32.5 * 0.25)
    assert d["balance_years"] == pytest.approx(10 * 0.25)  # 2.5 y


def test_moon_dasha_periods_tile_the_whole_session():
    for cyc in (390.0, 400.0):
        d = moon_dasha(ROHINI_75, cycle_minutes=cyc, levels=2)
        assert sum(p["minutes"] for p in d["periods"]) == pytest.approx(cyc)
        assert d["periods"][0]["start_min"] == 0.0
        assert d["periods"][-1]["end_min"] == pytest.approx(cyc)
        # first period is the balance -> partial, and it is the Moon's lord
        assert d["periods"][0]["lord"] == "Moon"
        assert d["periods"][0]["partial"] is True
        assert d["periods"][0]["minutes"] == pytest.approx(cyc * 10 / 120 * 0.25)
        # antardashas of every mahadasha sum back to that mahadasha
        for p in d["periods"]:
            if p["children"]:
                assert sum(c["minutes"] for c in p["children"]) == pytest.approx(p["minutes"])


def test_moon_dasha_first_full_period_is_next_lord():
    d = moon_dasha(ROHINI_75, cycle_minutes=390.0, levels=1)
    # after the partial Moon balance, the next lord in VIM_ORDER is Mars
    assert d["periods"][1]["lord"] == "Mars"
    assert d["periods"][1]["partial"] is False
    assert d["periods"][1]["minutes"] == pytest.approx(390.0 * 7 / 120)


def test_moon_dasha_balance_sub_period_starts_mid_sequence():
    # the balance mahadasha's antardashas begin partway through, not at the MD lord
    d = moon_dasha(ROHINI_75, cycle_minutes=390.0, levels=2)
    md0 = d["periods"][0]
    # 75% of the Moon MD elapsed -> Moon/Mars/Rahu/Jup/Sat/Merc ADs gone, Ketu current
    assert md0["children"][0]["lord"] == "Ketu"
    assert md0["children"][0]["partial"] is True
    assert [c["lord"] for c in md0["children"]] == ["Ketu", "Venus", "Sun"]


def test_moon_dasha_start_of_nakshatra_has_full_balance():
    d = moon_dasha(3 * NAK_SPAN_DEG, cycle_minutes=390.0, levels=1)
    assert d["elapsed_fraction"] == pytest.approx(0.0, abs=1e-6)
    assert d["balance_minutes"] == pytest.approx(390.0 * 10 / 120)
    assert d["periods"][0]["lord"] == "Moon"
    assert d["periods"][0]["partial"] is False  # a whole Moon MD fits


def test_moon_dasha_390_and_400_differ():
    a = moon_dasha(ROHINI_75, cycle_minutes=390.0, levels=1)
    b = moon_dasha(ROHINI_75, cycle_minutes=400.0, levels=1)
    assert a["balance_minutes"] != b["balance_minutes"]
    assert a["balance_years"] == pytest.approx(b["balance_years"])  # years ratio unchanged
    assert a["session_open"] == "09:15"


def test_moon_dasha_clock_is_session_anchored():
    d = moon_dasha(ROHINI_75, cycle_minutes=390.0, levels=1)
    assert d["periods"][0]["start_clock"] == "09:15"
    assert d["periods"][-1]["end_clock"] == "15:45"  # 09:15 + 390 min


def test_moon_dasha_session_open_shifts_only_the_clock():
    a = moon_dasha(ROHINI_75, cycle_minutes=390.0, levels=2, session_open="09:00")
    b = moon_dasha(ROHINI_75, cycle_minutes=390.0, levels=2, session_open="09:15")
    assert a["session_open"] == "09:00"
    assert a["periods"][0]["start_clock"] == "09:00"
    assert a["periods"][-1]["end_clock"] == "15:30"  # 09:00 + 390
    assert b["periods"][0]["start_clock"] == "09:15"

    # only the wall-clock labels move — every lord / minute / year is identical
    def _shape(nodes):
        return [
            (p["lord"], p["minutes"], p["years"], p["partial"], _shape(p["children"]))
            for p in nodes
        ]

    assert _shape(a["periods"]) == _shape(b["periods"])
    assert a["balance_minutes"] == b["balance_minutes"]


def test_moon_dasha_400_minute_session_open_0900():
    d = moon_dasha(ROHINI_75, cycle_minutes=400.0, levels=1, session_open="09:00")
    assert d["periods"][-1]["end_clock"] == "15:40"  # 09:00 + 400 min


def test_moon_dasha_levels_guard():
    with pytest.raises(ValueError, match="levels"):
        moon_dasha(ROHINI_75, levels=4)
    with pytest.raises(ValueError, match="cycle_minutes"):
        moon_dasha(ROHINI_75, cycle_minutes=0)
    with pytest.raises(ValueError, match="session_open"):
        moon_dasha(ROHINI_75, session_open="24:00")


def test_moon_dasha_head_matches_full_tree():
    lon = ROHINI_75
    head = moon_dasha_head(lon, 390.0)
    full = moon_dasha(lon, cycle_minutes=390.0, levels=2)
    assert head["dasha_lord"] == full["periods"][0]["lord"]
    assert head["dasha_balance_hms"] == full["balance_hms"]
    assert head["sub_lord"] == full["periods"][0]["children"][0]["lord"]


def test_moon_dasha_pratyantar_level():
    d = moon_dasha(ROHINI_75, cycle_minutes=390.0, levels=3)
    md = next(p for p in d["periods"] if not p["partial"])
    ad = md["children"][0]
    assert ad["children"], "level 3 should populate pratyantar"
    assert sum(pd["minutes"] for pd in ad["children"]) == pytest.approx(ad["minutes"])
    assert ad["children"][0]["level"] == 3


# -- KP lord chain (docs/13 §5.6.1) -----------------------------------------


def test_kp_chain_start_of_zodiac_is_all_ketu():
    # 0deg Aries: sign Mars, nakshatra Ashwini (Ketu), and KP subs open with the
    # star lord -> Ketu / Ketu / Ketu
    c = kp_chain(0.0)
    assert c["sign_lord"] == "Mars"
    assert c["star_lord"] == c["sub_lord"] == c["sub_sub_lord"] == "Ketu"
    assert c["star_lord_abbr"] == "Ke"


def test_kp_chain_sign_and_star_lords_are_standard():
    # 20deg Libra -> sign Venus, Swati nakshatra -> Rahu
    c = kp_chain(200.0)
    assert c["sign_lord"] == "Venus"
    assert c["star_lord"] == "Rahu"
    # 15deg Taurus -> sign Venus, Rohini -> Moon
    c2 = kp_chain(45.0)
    assert c2["sign_lord"] == "Venus"
    assert c2["star_lord"] == "Moon"


def test_kp_chain_first_sub_is_the_star_lord():
    # just inside every nakshatra, the first KP sub is the star lord itself
    for i in range(27):
        lon = i * NAK_SPAN_DEG + 0.001
        c = kp_chain(lon)
        assert c["sub_lord"] == c["star_lord"], f"nakshatra {i}"


def test_kp_chain_sub_spans_sum_to_the_nakshatra():
    # walking VIM_ORDER from the star lord, the nine sub-arcs must tile 13deg20'
    from app.astro.dasha import _rotated, _sub_of

    star = kp_chain(0.0)["star_lord"]
    total = 0.0
    for ld in _rotated(VIM_ORDER, star):
        total += NAK_SPAN_DEG * VIM_YEARS[ld] / VIM_TOTAL_YEARS
    assert total == pytest.approx(NAK_SPAN_DEG)
    # _sub_of at the very end of the arc returns the last lord, not an overflow
    lord, start, span = _sub_of(NAK_SPAN_DEG - 1e-9, NAK_SPAN_DEG, star)
    assert lord == _rotated(VIM_ORDER, star)[-1]
    assert start + span == pytest.approx(NAK_SPAN_DEG)


def test_kp_chain_matches_moon_dasha_star_lord():
    # star lord in the chain == the running mahadasha lord for the same longitude
    d = moon_dasha(45.0, cycle_minutes=390.0, levels=1)
    assert d["kp_chain"]["star_lord"] == d["dasha_lord"]


def test_kp_chain_deterministic():
    assert kp_chain(123.456) == kp_chain(123.456)
