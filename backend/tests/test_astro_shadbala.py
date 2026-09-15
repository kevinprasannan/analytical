"""Classical Parashari Shadbala (docs/13 §4).

No external reference implementation is available in this environment (PyJHora's
native deps are blocked), so these tests pin the *formulas* (hand-computable
components) and the *structural invariants* of the aggregate. Totals should be
cross-checked against Jagannatha Hora before analytical use (docs/13 §6).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from app.astro import shadbala as sb
from app.astro.ephemeris import AstroEngine
from app.astro.vedic import EXALTATION_DEG, SHADBALA_GRAHAS

IST = timezone(timedelta(hours=5, minutes=30))
DT = datetime(2024, 1, 1, 9, 0, tzinfo=IST)
LAT, LON = 19.076090, 72.877426


@pytest.fixture(scope="module")
def result() -> dict:
    return sb.compute_shadbala(AstroEngine(), DT, LAT, LON)


def test_uccha_bala_endpoints():
    for g in SHADBALA_GRAHAS:
        ex = EXALTATION_DEG[g]
        assert sb._uccha_bala(g, ex) == pytest.approx(60.0, abs=1e-9)
        assert sb._uccha_bala(g, (ex + 180.0) % 360.0) == pytest.approx(0.0, abs=1e-9)
        assert sb._uccha_bala(g, (ex + 90.0) % 360.0) == pytest.approx(30.0, abs=1e-9)


def test_naisargika_bala_fixed_ladder():
    assert sb._NAISARGIKA["SUN"] == pytest.approx(60.0)
    assert sb._NAISARGIKA["SATURN"] == pytest.approx(60.0 / 7)
    assert sb._NAISARGIKA["MOON"] == pytest.approx(60.0 * 6 / 7)
    # strictly descending Sun>Moon>Venus>Jupiter>Mercury>Mars>Saturn
    order = ["SUN", "MOON", "VENUS", "JUPITER", "MERCURY", "MARS", "SATURN"]
    vals = [sb._NAISARGIKA[g] for g in order]
    assert vals == sorted(vals, reverse=True)


def test_totals_and_ranks_are_consistent(result):
    ranks = sorted(r.rank for r in result.values())
    assert ranks == [1, 2, 3, 4, 5, 6, 7]
    for r in result.values():
        parts = r.sthana_total + r.dig + r.kala_total + r.cheshta + r.naisargika + r.drik
        assert r.total_virupa == pytest.approx(parts, abs=1e-6)
        assert r.total_rupa == pytest.approx(r.total_virupa / 60.0, abs=1e-9)
        assert r.ratio == pytest.approx(r.total_rupa / r.required_rupa, abs=1e-9)
        assert r.sthana_total == pytest.approx(sum(r.sthana.values()), abs=1e-6)
        assert r.kala_total == pytest.approx(sum(r.kala.values()), abs=1e-6)
    # rank 1 really is the max
    top = min(result.values(), key=lambda r: r.rank)
    assert top.total_virupa == max(r.total_virupa for r in result.values())


def test_ishta_kashta_definition(result):
    for r in result.values():
        uccha = r.sthana["uccha"]
        assert r.ishta_phala == pytest.approx(math.sqrt(uccha * r.cheshta), abs=1e-6)
        assert r.kashta_phala == pytest.approx(math.sqrt((60 - uccha) * (60 - r.cheshta)), abs=1e-6)


def test_sun_moon_cheshta_identities(result):
    # documented: Sun's cheshta bala = its ayana bala; Moon's = its paksha bala
    assert result["SUN"].cheshta == pytest.approx(result["SUN"].kala["ayana"], abs=1e-9)
    assert result["MOON"].cheshta == pytest.approx(result["MOON"].kala["paksha"], abs=1e-9)


def test_components_in_plausible_virupa_ranges(result):
    for r in result.values():
        assert 0 <= r.sthana["uccha"] <= 60
        assert 0 <= r.sthana["oja_yugma"] <= 30
        assert r.sthana["kendradi"] in (15.0, 30.0, 60.0)
        assert r.sthana["drekkana"] in (0.0, 15.0)
        assert 0 <= r.dig <= 60
        assert 0 <= r.cheshta <= 60
        assert 0 <= r.kala["ayana"] <= 120  # Sun's is doubled
        assert 3.0 <= r.total_rupa <= 12.0  # sane Shadbala envelope


def test_deterministic(result):
    again = sb.compute_shadbala(AstroEngine(), DT, LAT, LON)
    for g in SHADBALA_GRAHAS:
        assert again[g].total_virupa == pytest.approx(result[g].total_virupa, abs=1e-9)
