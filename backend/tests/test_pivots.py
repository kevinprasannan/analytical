"""CPR + classic floor pivots (docs/05 §10.13) — pure math."""

from __future__ import annotations

import pytest

from analytical_core.pivots import (
    CprRelation,
    CprWidth,
    compute_pivots,
    cpr_relation,
    width_band,
)


def test_classic_pivot_and_sr_formulae():
    p = compute_pivots(110.0, 90.0, 105.0)
    piv = (110 + 90 + 105) / 3
    assert p.pivot == pytest.approx(piv)
    assert p.r1 == pytest.approx(2 * piv - 90)
    assert p.s1 == pytest.approx(2 * piv - 110)
    assert p.r2 == pytest.approx(piv + (110 - 90))
    assert p.s2 == pytest.approx(piv - (110 - 90))
    assert p.r3 == pytest.approx(110 + 2 * (piv - 90))
    assert p.s3 == pytest.approx(90 - 2 * (110 - piv))
    # ordering: R3 > R2 > R1 > P > S1 > S2 > S3
    names = [n for n, _ in p.levels()]
    prices = [v for _, v in p.levels()]
    assert names == ["R3", "R2", "R1", "TC", "P", "BC", "S1", "S2", "S3"]
    assert prices == sorted(prices, reverse=True)


def test_cpr_band_and_width():
    p = compute_pivots(110.0, 90.0, 105.0)
    piv = (110 + 90 + 105) / 3
    bc = (110 + 90) / 2
    tc = 2 * piv - bc
    assert p.bc == pytest.approx(bc)
    assert p.tc == pytest.approx(tc)
    assert p.cpr_top == pytest.approx(max(tc, bc))
    assert p.cpr_bottom == pytest.approx(min(tc, bc))
    assert p.cpr_width == pytest.approx(abs(tc - bc))
    assert p.cpr_width_pct == pytest.approx(abs(tc - bc) / piv * 100)


def test_weak_close_flips_tc_below_bc_but_band_stays_ordered():
    # close near the low → TC < BC by formula; cpr_top/bottom still max/min
    p = compute_pivots(110.0, 90.0, 91.0)
    assert p.tc < p.bc
    assert p.cpr_top >= p.cpr_bottom
    assert p.cpr_width >= 0


def test_cpr_relation_higher_lower_overlap():
    base = compute_pivots(110.0, 90.0, 104.0)  # close off the midpoint → real CPR band
    higher = compute_pivots(150.0, 130.0, 144.0)
    lower = compute_pivots(70.0, 50.0, 64.0)
    nudged = compute_pivots(111.0, 91.0, 104.6)  # band shifted a hair, still overlaps
    assert cpr_relation(higher, base) is CprRelation.HIGHER_VALUE
    assert cpr_relation(lower, base) is CprRelation.LOWER_VALUE
    assert cpr_relation(nudged, base) is CprRelation.OVERLAPPING
    assert cpr_relation(base, base) is CprRelation.UNCHANGED


def test_cpr_relation_inside_and_outside():
    wide = compute_pivots(160.0, 40.0, 130.0)  # big range + strong close → wide CPR band
    tight = compute_pivots(103.0, 99.0, 101.5)  # small range → narrow band inside it
    assert cpr_relation(tight, wide) is CprRelation.INSIDE_VALUE
    assert cpr_relation(wide, tight) is CprRelation.OUTSIDE_VALUE


def test_width_band_thresholds():
    assert width_band(0.1) is CprWidth.NARROW
    assert width_band(0.5) is CprWidth.AVERAGE
    assert width_band(1.0) is CprWidth.WIDE
    assert width_band(0.3, narrow=0.4) is CprWidth.NARROW


def test_rejects_bad_range():
    with pytest.raises(ValueError):
        compute_pivots(90.0, 110.0, 100.0)
