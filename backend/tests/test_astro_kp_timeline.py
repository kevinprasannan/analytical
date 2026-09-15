"""KP-lord session change-brackets (docs/13 §5.6.1) — shape + ephemeris wiring."""

from __future__ import annotations

from datetime import date

import pytest

from app.astro.ephemeris import AstroEngine
from app.astro.kp_timeline import _parse_hm, kp_session_timeline

_MUMBAI = (19.076090, 72.877426)
_LORDS = {"Ketu", "Venus", "Sun", "Moon", "Mars", "Rahu", "Jupiter", "Saturn", "Mercury"}
_RELS = {"friend", "neutral", "enemy"}


def test_parse_hm_bounds():
    assert _parse_hm("15:40") == 940
    for bad in ("09:00", "08:59", "24:00", "9:0", "nope"):
        with pytest.raises(ValueError):
            _parse_hm(bad)


def test_level_guard():
    with pytest.raises(ValueError, match="level"):
        kp_session_timeline(AstroEngine(), d=date(2026, 3, 3), lat=_MUMBAI[0], lon=_MUMBAI[1], level="x")


def test_sub_sub_makes_more_brackets_than_sub():
    eng = AstroEngine()
    kw = dict(d=date(2026, 8, 12), lat=_MUMBAI[0], lon=_MUMBAI[1], end="15:40")
    n_sub = len(kp_session_timeline(eng, level="sub", **kw)["rows"])
    n_deep = len(kp_session_timeline(eng, level="sub_sub", **kw)["rows"])
    assert n_deep > n_sub > 5


def test_brackets_shape_and_values():
    eng = AstroEngine()
    r = kp_session_timeline(eng, d=date(2026, 8, 12), lat=_MUMBAI[0], lon=_MUMBAI[1], end="15:30")
    assert r["date"] == "2026-08-12"
    assert r["end"] == "15:30"
    assert r["level"] == "sub"
    rows = r["rows"]
    assert rows, "expected at least one bracket"
    # first bracket opens at 09:00, last closes at the session end, contiguous
    assert rows[0]["start"] == "09:00"
    assert rows[-1]["end"] == "15:30"
    for a, b in zip(rows, rows[1:]):
        assert a["end"] == b["start"], "brackets must tile without gaps"
        assert a["start"] < a["end"]
    for row in rows:
        for pt in (row["lagna"], row["moon"]):
            assert {pt["sign_lord"], pt["star_lord"], pt["sub_lord"], pt["sub_sub_lord"]} <= _LORDS
            assert 0.0 <= pt["longitude"] < 360.0
            assert pt["star_sub_relation"] in _RELS
        lh = row["lagna_houses"]
        assert {lh["sign"], lh["star"], lh["sub"]} <= set(range(1, 13))
        assert row["market"] is None  # no bars passed in this test
    # every bracket boundary is a real change in one of the two chains
    def key(row):
        k = lambda p: (p["sign_lord"], p["star_lord"], p["sub_lord"], p["sub_sub_lord"])
        return (k(row["lagna"]), k(row["moon"]))

    for a, b in zip(rows, rows[1:]):
        assert key(a) != key(b)
    # the Moon's star lord is constant across a single session
    assert len({row["moon"]["star_lord"] for row in rows}) == 1
    # the Lagna sweeps > one sign -> several brackets
    assert len(rows) >= 4


def test_deterministic():
    eng = AstroEngine()
    a = kp_session_timeline(eng, d=date(2026, 3, 3), lat=_MUMBAI[0], lon=_MUMBAI[1])
    b = kp_session_timeline(eng, d=date(2026, 3, 3), lat=_MUMBAI[0], lon=_MUMBAI[1])
    assert a == b


def test_bracket_market_open_close():
    from app.astro.kp_timeline import _bracket_market

    bars = {m: (100.0 + m, 100.5 + m) for m in range(540, 560)}
    r = _bracket_market(bars, 545, 550)  # minutes 545..549
    assert r == {"open": 645.0, "close": 649.5, "change": 4.5, "change_pct": round(4.5 / 645 * 100, 3)}
    assert _bracket_market(bars, 700, 720) is None
    assert _bracket_market(None, 545, 550) is None


def test_house_from_lagna():
    from app.astro.kp_timeline import _house_from_lagna

    rof = {"SUN": 3, "JUPITER": 0, "MERCURY": 11}
    # Lagna at 5° Aries (rashi 0): Sun in Cancer -> 4th, Jupiter in Aries -> 1st
    assert _house_from_lagna(5.0, "Sun", rof) == 4
    assert _house_from_lagna(5.0, "Jupiter", rof) == 1
    assert _house_from_lagna(5.0, "Mercury", rof) == 12  # Pisces from Aries
    # Lagna at 40° (rashi 1, Taurus): Sun (Cancer) -> 3rd
    assert _house_from_lagna(40.0, "Sun", rof) == 3
    assert _house_from_lagna(5.0, "Ketu", rof) is None  # not in the map
