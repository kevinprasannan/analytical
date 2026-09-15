"""Swiss Ephemeris wrapper (docs/13) — sidereal Lahiri positions.

Reference values are Swiss Ephemeris output for 2024-01-01 09:00 IST, spot-checked
against known astronomy (Sun mid-Sagittarius in early January, Mercury stationary
-> retrograde around then, Lahiri ayanamsha ~24.19 deg for 2024).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.astro.ephemeris import AstroEngine
from app.astro.vedic import norm360

IST = timezone(timedelta(hours=5, minutes=30))
DT = datetime(2024, 1, 1, 9, 0, tzinfo=IST)

_EXPECTED = {
    # graha: (sidereal_longitude, retrograde)
    "SUN": (255.997, False),
    "MOON": (133.528, False),
    "MARS": (243.226, False),
    "MERCURY": (238.066, True),
    "JUPITER": (11.392, False),
    "VENUS": (218.599, False),
    "SATURN": (309.066, False),
    "RAHU": (356.678, True),
}


@pytest.fixture(scope="module")
def engine() -> AstroEngine:
    return AstroEngine()


def test_ayanamsha_is_lahiri_range(engine):
    assert engine.ayanamsha(DT) == pytest.approx(24.192, abs=0.01)
    # Lahiri drifts ~50.3"/yr -> ~0.014 deg/yr
    a2000 = engine.ayanamsha(datetime(2000, 1, 1, 9, 0, tzinfo=IST))
    assert 23.8 < a2000 < 23.95


def test_positions_match_reference(engine):
    got = {p.graha: p for p in engine.positions(DT)}
    for graha, (lon, retro) in _EXPECTED.items():
        assert got[graha].longitude == pytest.approx(lon, abs=0.01), graha
        assert got[graha].retrograde is retro, graha


def test_ketu_is_opposite_rahu(engine):
    got = {p.graha: p for p in engine.positions(DT)}
    assert norm360(got["KETU"].longitude - got["RAHU"].longitude) == pytest.approx(180.0, abs=1e-6)
    assert got["KETU"].retrograde and got["RAHU"].retrograde  # mean node: always


def test_derived_fields_consistent_with_longitude(engine):
    for p in engine.positions(DT):
        assert p.rashi_index == int(p.longitude // 30) % 12
        assert 0 <= p.degree < 30
        assert p.degree == pytest.approx(p.longitude % 30, abs=1e-6)
        assert 0 <= p.nakshatra_index <= 26
        assert 1 <= p.pada <= 4
        assert (p.speed_long < 0) == p.retrograde or p.graha in ("RAHU", "KETU")


def test_saturn_in_aquarius_moolatrikona(engine):
    sat = next(p for p in engine.positions(DT) if p.graha == "SATURN")
    assert sat.rashi == "Kumbha"
    assert sat.dignity == "moolatrikona"


def test_sunrise_sunset_mumbai(engine):
    sr, ss = engine.sunrise_sunset(DT.date(), 19.076090, 72.877426)
    sr_ist, ss_ist = sr.astimezone(IST), ss.astimezone(IST)
    # Mumbai 2024-01-01: sunrise ~07:11, sunset ~18:11 IST
    assert sr_ist.hour == 7 and 5 <= sr_ist.minute <= 20
    assert ss_ist.hour == 18 and 0 <= ss_ist.minute <= 20


def test_deterministic(engine):
    a = engine.positions(DT)
    b = AstroEngine().positions(DT)
    assert [(p.graha, p.longitude) for p in a] == [(p.graha, p.longitude) for p in b]
