"""Pure sidereal-zodiac math (docs/13 §2) — no ephemeris."""

from __future__ import annotations

import pytest

from app.astro import vedic


def test_rashi_degree_boundaries():
    assert vedic.rashi_index(0.0) == 0
    assert vedic.rashi_name(0.0) == "Mesha"
    assert vedic.rashi_index(29.999) == 0
    assert vedic.rashi_index(30.0) == 1
    assert vedic.rashi_index(359.9) == 11
    assert vedic.rashi_index(360.0) == 0  # wraps
    assert vedic.degree_in_sign(93.75) == pytest.approx(3.75)


def test_nakshatra_pada():
    # Ashwini spans 0-13.333; pada 1 = 0-3.333
    assert vedic.nakshatra_pada(0.0) == (0, 1)
    assert vedic.nakshatra_pada(3.34) == (0, 2)
    assert vedic.nakshatra_pada(13.333) == (0, 4)  # still Ashwini (arc = 13.3333)
    assert vedic.nakshatra_pada(13.4) == (1, 1)  # Bharani p1
    ni, pada = vedic.nakshatra_pada(360.0 - 0.01)  # end of Revati
    assert ni == 26 and pada == 4
    assert vedic.NAKSHATRA_LORDS[0] == "KETU"
    assert vedic.NAKSHATRA_LORDS[8] == "MERCURY"
    assert vedic.NAKSHATRA_LORDS[9] == "KETU"  # cycle repeats every 9


def test_arc_distance_is_symmetric_and_folded():
    assert vedic.arc_distance(10, 350) == pytest.approx(20)
    assert vedic.arc_distance(0, 180) == pytest.approx(180)
    assert vedic.arc_distance(200, 20) == pytest.approx(180)
    assert vedic.arc_distance(45, 45) == 0


def test_navamsha_known_placements():
    # 0 Aries -> D9 Aries (movable sign starts from itself)
    assert vedic.varga_sign(0.5, "D9") == 0
    # last navamsha of Aries (26.67-30) -> 9th from Aries = Sagittarius (8)
    assert vedic.varga_sign(29.0, "D9") == 8
    # 0 Taurus (fixed) -> starts from 9th = Capricorn (9)
    assert vedic.varga_sign(30.5, "D9") == 9
    # 0 Gemini (dual) -> starts from 5th = Libra (6)
    assert vedic.varga_sign(60.5, "D9") == 6


def test_hora_drekkana_dwadashamsha():
    # D2: first half of Aries (odd) -> Leo
    assert vedic.varga_sign(5.0, "D2") == 4
    assert vedic.varga_sign(20.0, "D2") == 3  # second half -> Cancer
    assert vedic.varga_sign(5.0, "D3") == 0  # 1st drekkana -> same sign
    assert vedic.varga_sign(15.0, "D3") == 4  # 2nd -> 5th sign (Leo)
    assert vedic.varga_sign(25.0, "D3") == 8  # 3rd -> 9th sign (Sag)
    assert vedic.varga_sign(1.0, "D12") == 0
    assert vedic.varga_sign(3.0, "D12") == 1  # 2nd dwadashamsha -> next sign


def test_d1_dignity_exalt_debilitate_own():
    assert vedic.d1_dignity("SUN", 10.0) == "exalted"  # Aries 10
    assert vedic.d1_dignity("SUN", 190.0) == "debilitated"  # Libra 10
    assert vedic.d1_dignity("SUN", 130.0) == "moolatrikona"  # Leo 10 (MT 0-20)
    assert vedic.d1_dignity("SUN", 145.0) == "own"  # Leo 25 (own, past MT)
    assert vedic.d1_dignity("SATURN", 305.0) == "moolatrikona"  # Aquarius 5 (MT 0-20)
    assert vedic.d1_dignity("MARS", 5.0) == "moolatrikona"  # Aries 5 (MT 0-12)


def test_compound_relation_bounds():
    # Sun-Jupiter are natural friends; if also temporally friendly -> great friend (+2)
    r = vedic.compound_relation("SUN", "JUPITER", planet_sign=0, other_sign=3)  # 4th -> temp friend
    assert r == 2
    r2 = vedic.compound_relation("SUN", "SATURN", planet_sign=0, other_sign=4)  # enemy + 5th enemy
    assert r2 == -2


def test_natural_relation_labels():
    assert vedic.natural_relation("SUN", "JUPITER") == "friend"
    assert vedic.natural_relation("JUPITER", "MERCURY") == "enemy"
    assert vedic.natural_relation("SUN", "MERCURY") == "neutral"
    # case-insensitive + nodes are neutral with anything
    assert vedic.natural_relation("Sun", "jupiter") == "friend"
    assert vedic.natural_relation("RAHU", "SATURN") == "neutral"


def test_badhaka_house_by_sign_movability():
    # movable (Mesha 0) -> 11th, fixed (Vrishabha 1) -> 9th, dual (Mithuna 2) -> 7th
    assert vedic.sign_movability(0) == "MOVABLE"
    assert vedic.sign_movability(1) == "FIXED"
    assert vedic.sign_movability(2) == "DUAL"
    assert vedic.sign_movability(3) == "MOVABLE"  # Karka
    assert vedic.badhaka_house(0) == 11
    assert vedic.badhaka_house(4) == 9  # Simha, fixed
    assert vedic.badhaka_house(8) == 7  # Dhanu, dual


def test_badhaka_from_sign_and_lord():
    # Mesha lagna: badhaka = 11th = Kumbha, lord Saturn
    house, sign_i, lord = vedic.badhaka_from(0)
    assert (house, vedic.RASHIS[sign_i], lord) == (11, "Kumbha", "SATURN")
    # Simha lagna (fixed): 9th from Simha = Mesha, lord Mars
    house, sign_i, lord = vedic.badhaka_from(4)
    assert (house, vedic.RASHIS[sign_i], lord) == (9, "Mesha", "MARS")
    # Dhanu lagna (dual): 7th from Dhanu = Mithuna, lord Mercury
    house, sign_i, lord = vedic.badhaka_from(8)
    assert (house, vedic.RASHIS[sign_i], lord) == (7, "Mithuna", "MERCURY")


def test_chandra_masa_index_and_shoonya_tithi():
    # Sun in Meena (11) at the new moon -> Chaitra (0)
    assert vedic.chandra_masa_index_from_newmoon_sun(11) == 0
    assert vedic.MASA_NAMES[0] == "Chaitra"
    assert vedic.chandra_masa_index_from_newmoon_sun(0) == 1  # Sun in Mesha -> Vaishakha
    # Chaitra shunya tithis are 8 and 9, in either paksha
    assert vedic.shoonya_tithis_for_masa("Chaitra") == (8, 9)
    assert vedic.tithi_in_paksha(23) == 8  # krishna ashtami
    assert vedic.is_shoonya_tithi("Chaitra", 8) is True
    assert vedic.is_shoonya_tithi("Chaitra", 23) is True  # krishna paksha too
    assert vedic.is_shoonya_tithi("Chaitra", 10) is False
    assert vedic.is_shoonya_tithi("Vaishakha", 12) is True
    # an override table wins
    assert vedic.is_shoonya_tithi("Chaitra", 5, {"Chaitra": (5,)}) is True


def test_days_since_new_moon_bounds():
    assert vedic.days_since_new_moon(100.0, 100.0) == pytest.approx(0.0)
    # Moon 180° ahead of the Sun = full moon ≈ half a synodic month
    assert vedic.days_since_new_moon(180.0, 0.0) == pytest.approx(29.530588853 / 2)


def test_tithi_shoonya_rashis():
    R = vedic.RASHIS.index
    # Pratipada (1) & Dwadashi (12) → Tula, Makara — in either paksha
    assert vedic.tithi_shoonya_rashis(1) == (R("Tula"), R("Makara"))
    assert vedic.tithi_shoonya_rashis(12) == (R("Tula"), R("Makara"))
    assert vedic.tithi_shoonya_rashis(1 + 15) == (R("Tula"), R("Makara"))  # krishna pratipada
    # Chaturdashi (14) has four
    assert set(vedic.tithi_shoonya_rashis(14)) == {
        R("Mithuna"),
        R("Kanya"),
        R("Dhanu"),
        R("Meena"),
    }
    # Purnima / Amavasya (15) — none
    assert vedic.tithi_shoonya_rashis(15) == ()
    # Navami and Dashami share Simha + Vrischika
    assert vedic.tithi_shoonya_rashis(9) == vedic.tithi_shoonya_rashis(10) == (R("Simha"), R("Vrischika"))
    # names + override
    assert vedic.tithi_name(1) == "Pratipada"
    assert vedic.tithi_name(23) == "Ashtami"  # krishna ashtami
    assert vedic.tithi_shoonya_rashis(3, {3: (0,)}) == (0,)
