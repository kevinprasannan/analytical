"""Per-day chart scalars (docs/13 §5) — no DB."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.astro.daily import compute_day_chart
from app.astro.ephemeris import AstroEngine

IST = timezone(timedelta(hours=5, minutes=30))
LAT, LON = 19.076090, 72.877426


@pytest.fixture(scope="module")
def engine() -> AstroEngine:
    return AstroEngine()


def test_day_chart_2024_01_01(engine):
    dt = datetime(2024, 1, 1, 9, 0, tzinfo=IST)
    c = compute_day_chart(engine, dt, LAT, LON)
    assert c.weekday == 0 and c.day_name == "Monday" and c.weekday_lord == "MOON"
    assert c.lagna_rashi == "Makara"  # ascendant ~282 deg
    assert 1 <= c.lagna_pada <= 4
    assert c.moon_rashi == "Simha" and c.moon_nakshatra == "Purva Phalguni"
    assert 1 <= c.tithi <= 30
    assert c.paksha in ("Shukla", "Krishna")
    assert c.paksha == ("Shukla" if c.tithi <= 15 else "Krishna")
    assert c.sunrise_ts < c.sunset_ts
    assert 23.9 < c.ayanamsha < 24.5


def test_weekday_lords_cycle(engine):
    lords = []
    for day in range(2, 9):  # 2024-01-02 (Tue) .. 2024-01-08 (Mon)
        dt = datetime(2024, 1, day, 9, 0, tzinfo=IST)
        lords.append(compute_day_chart(engine, dt, LAT, LON).weekday_lord)
    assert lords == ["MARS", "MERCURY", "JUPITER", "VENUS", "SATURN", "SUN", "MOON"]


def test_tithi_grows_then_wraps(engine):
    # over ~30 days tithi should span a full lunar month and wrap
    seen = set()
    for day in range(1, 31):
        dt = datetime(2024, 1, day, 9, 0, tzinfo=IST)
        seen.add(compute_day_chart(engine, dt, LAT, LON).tithi)
    assert len(seen) >= 25  # most tithis touched
    assert max(seen) <= 30 and min(seen) >= 1
