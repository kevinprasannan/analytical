"""Pure sidereal-zodiac math — rashi, nakshatra, pada, vargas, dignities.

No ephemeris, no IO, stdlib only. Everything here is a deterministic function of
a sidereal ecliptic longitude (degrees, 0-360, ayanamsha already applied).

Conventions (docs/13 §2): 12 rashis of 30 deg from 0 deg sidereal Aries; 27
nakshatras of 13 deg 20', 4 padas of 3 deg 20' each; Vimshottari nakshatra
lords; classical Parashari varga rules for the Saptavarga set (D1, D2, D3, D7,
D9, D12, D30).
"""

from __future__ import annotations

from dataclasses import dataclass

GRAHAS: tuple[str, ...] = (
    "SUN",
    "MOON",
    "MARS",
    "MERCURY",
    "JUPITER",
    "VENUS",
    "SATURN",
    "RAHU",
    "KETU",
)
#: the seven that carry classical Shadbala (Rahu/Ketu do not).
SHADBALA_GRAHAS: tuple[str, ...] = GRAHAS[:7]

RASHIS: tuple[str, ...] = (
    "Mesha",
    "Vrishabha",
    "Mithuna",
    "Karka",
    "Simha",
    "Kanya",
    "Tula",
    "Vrischika",
    "Dhanu",
    "Makara",
    "Kumbha",
    "Meena",
)

NAKSHATRAS: tuple[str, ...] = (
    "Ashwini",
    "Bharani",
    "Krittika",
    "Rohini",
    "Mrigashira",
    "Ardra",
    "Punarvasu",
    "Pushya",
    "Ashlesha",
    "Magha",
    "Purva Phalguni",
    "Uttara Phalguni",
    "Hasta",
    "Chitra",
    "Swati",
    "Vishakha",
    "Anuradha",
    "Jyeshtha",
    "Mula",
    "Purva Ashadha",
    "Uttara Ashadha",
    "Shravana",
    "Dhanishta",
    "Shatabhisha",
    "Purva Bhadrapada",
    "Uttara Bhadrapada",
    "Revati",
)

#: Vimshottari dasha lords, repeating every 9 nakshatras.
_VIM_LORDS = ("KETU", "VENUS", "SUN", "MOON", "MARS", "RAHU", "JUPITER", "SATURN", "MERCURY")
NAKSHATRA_LORDS: tuple[str, ...] = tuple(_VIM_LORDS[i % 9] for i in range(27))

#: rashi (sign) lords, index 0 = Mesha/Aries.
RASHI_LORDS: tuple[str, ...] = (
    "MARS",
    "VENUS",
    "MERCURY",
    "MOON",
    "SUN",
    "MERCURY",
    "VENUS",
    "MARS",
    "JUPITER",
    "SATURN",
    "SATURN",
    "JUPITER",
)

_NAK_ARC = 360.0 / 27.0  # 13 deg 20'
_PADA_ARC = _NAK_ARC / 4.0  # 3 deg 20'


def norm360(x: float) -> float:
    return x % 360.0


def arc_distance(a: float, b: float) -> float:
    """Shortest separation of two longitudes, 0-180."""
    d = abs(norm360(a) - norm360(b)) % 360.0
    return 360.0 - d if d > 180.0 else d


def rashi_index(lon: float) -> int:
    """0-11."""
    return int(norm360(lon) // 30.0) % 12


def rashi_name(lon: float) -> str:
    return RASHIS[rashi_index(lon)]


def degree_in_sign(lon: float) -> float:
    return norm360(lon) % 30.0


def nakshatra_index(lon: float) -> int:
    """0-26."""
    return int(norm360(lon) // _NAK_ARC) % 27


def nakshatra_pada(lon: float) -> tuple[int, int]:
    """(nakshatra_index 0-26, pada 1-4)."""
    lon = norm360(lon)
    ni = int(lon // _NAK_ARC) % 27
    pada = int((lon % _NAK_ARC) // _PADA_ARC) + 1
    return ni, min(pada, 4)


# ---------------------------------------------------------------------------
# Badhaka (house of obstruction) and its lord — reckoned from a reference sign.
#   movable  sign (Mesha, Karka, Tula, Makara)      -> 11th house is badhaka
#   fixed    sign (Vrishabha, Simha, Vrischika, Kumbha) -> 9th house
#   dual     sign (Mithuna, Kanya, Dhanu, Meena)    -> 7th house
# The lord of that house's sign is the Baadhagaadhipathi.
# ---------------------------------------------------------------------------

SIGN_MOVABILITY: tuple[str, ...] = ("MOVABLE", "FIXED", "DUAL")  # by rashi_index % 3
_BADHAKA_HOUSE_BY_MOVABILITY = {0: 11, 1: 9, 2: 7}


def sign_movability(rashi_index_: int) -> str:
    """'MOVABLE' | 'FIXED' | 'DUAL' for a 0-11 sign index (chara / sthira / dwiswabhava)."""
    return SIGN_MOVABILITY[rashi_index_ % 3]


def badhaka_house(reference_rashi_index: int) -> int:
    """The badhaka house number (11 / 9 / 7) counted from a reference sign."""
    return _BADHAKA_HOUSE_BY_MOVABILITY[reference_rashi_index % 3]


def badhaka_from(reference_rashi_index: int) -> tuple[int, int, str]:
    """(badhaka_house, badhaka_sign_index, badhaka_lord) from a reference sign."""
    house = badhaka_house(reference_rashi_index)
    sign = (reference_rashi_index + house - 1) % 12
    return house, sign, RASHI_LORDS[sign]


# ---------------------------------------------------------------------------
# Chandra masa (amanta lunar month) + Masa Shunya Tithi.
#
# ``chandra_masa_index_from_newmoon_sun`` names the month after the sidereal
# sign the Sun occupies at the new moon that begins it (Sun in Meena -> Chaitra).
#
# ``SHOONYA_TITHIS_BY_MASA`` is the classical "void / dead tithi" list from the
# Muhurta shloka (Chaitre nava cha ashtau …): the tithi number (1-15, within a
# paksha, both pakshas) that is shunya for that month. Traditions vary — this is
# a documented default, overridable via ``astro.shoonya_tithis_by_masa`` config.
# ---------------------------------------------------------------------------

MASA_NAMES: tuple[str, ...] = (
    "Chaitra",
    "Vaishakha",
    "Jyeshtha",
    "Ashadha",
    "Shravana",
    "Bhadrapada",
    "Ashwina",
    "Kartika",
    "Margashirsha",
    "Pausha",
    "Magha",
    "Phalguna",
)

SHOONYA_TITHIS_BY_MASA: dict[str, tuple[int, ...]] = {
    "Chaitra": (8, 9),
    "Vaishakha": (12,),
    "Jyeshtha": (13,),
    "Ashadha": (6,),
    "Shravana": (5,),
    "Bhadrapada": (4,),
    "Ashwina": (11,),
    "Kartika": (10,),
    "Margashirsha": (3,),
    "Pausha": (2,),
    "Magha": (7,),
    "Phalguna": (4,),
}

_SYNODIC_MONTH_DAYS = 29.530588853


def chandra_masa_index_from_newmoon_sun(sun_rashi_index_at_newmoon: int) -> int:
    """Amanta month index 0-11 (0 = Chaitra) from the Sun's sign at the new moon."""
    return (sun_rashi_index_at_newmoon + 1) % 12


def days_since_new_moon(moon_longitude: float, sun_longitude: float) -> float:
    """Approximate elapsed days of the current synodic month from the Sun-Moon
    elongation (0 at new moon, ~29.53 just before the next)."""
    return (norm360(moon_longitude) - norm360(sun_longitude)) % 360.0 / 360.0 * _SYNODIC_MONTH_DAYS


def tithi_in_paksha(tithi: int) -> int:
    """1-15 within the current paksha (tithi is 1-30 over the whole month)."""
    return tithi if tithi <= 15 else tithi - 15


def shoonya_tithis_for_masa(
    masa: str, table: dict[str, tuple[int, ...]] | None = None
) -> tuple[int, ...]:
    return tuple((table or SHOONYA_TITHIS_BY_MASA).get(masa, ()))


def is_shoonya_tithi(
    masa: str, tithi: int, table: dict[str, tuple[int, ...]] | None = None
) -> bool:
    """Is this month's ``tithi`` (1-30) a Masa Shunya Tithi?"""
    return tithi_in_paksha(tithi) in shoonya_tithis_for_masa(masa, table)


# ---------------------------------------------------------------------------
# Tithi Shoonya Rashi — the sign(s) held "void / weak" for a given tithi
# (Muhurta / KP; owner-supplied table 2026-09-09). Keyed by tithi-in-paksha
# 1-15 (applies in both pakshas); a body or the lagna sitting in one of these
# rashis on that tithi is read as blunted. Overridable via config.
# Tritiya / Trayodashi vary by text (Scorpio here; Taurus in some) — default
# to Scorpio + Leo.
# ---------------------------------------------------------------------------

TITHI_NAMES: tuple[str, ...] = (
    "Pratipada",
    "Dwitiya",
    "Tritiya",
    "Chaturthi",
    "Panchami",
    "Shashthi",
    "Saptami",
    "Ashtami",
    "Navami",
    "Dashami",
    "Ekadashi",
    "Dwadashi",
    "Trayodashi",
    "Chaturdashi",
    "Purnima/Amavasya",
)

#: tithi-in-paksha (1-15) -> rashi indices that are shoonya for it
TITHI_SHOONYA_RASHIS_BY_TITHI: dict[int, tuple[int, ...]] = {
    1: (6, 9),  # Pratipada  — Tula, Makara
    2: (8, 11),  # Dwitiya    — Dhanu, Meena
    3: (7, 4),  # Tritiya    — Vrischika, Simha
    4: (10, 1),  # Chaturthi  — Kumbha, Vrishabha
    5: (2, 5),  # Panchami   — Mithuna, Kanya
    6: (0, 4),  # Shashthi   — Mesha, Simha
    7: (8, 3),  # Saptami    — Dhanu, Karka
    8: (2, 5),  # Ashtami    — Mithuna, Kanya
    9: (4, 7),  # Navami     — Simha, Vrischika
    10: (4, 7),  # Dashami    — Simha, Vrischika
    11: (8, 11),  # Ekadashi   — Dhanu, Meena
    12: (6, 9),  # Dwadashi   — Tula, Makara
    13: (7, 4),  # Trayodashi — Vrischika, Simha
    14: (2, 5, 8, 11),  # Chaturdashi — Mithuna, Kanya, Dhanu, Meena
    15: (),  # Purnima / Amavasya — none
}


def tithi_name(tithi: int) -> str:
    """Name of a 1-30 tithi (by its 1-15 position in the paksha)."""
    return TITHI_NAMES[tithi_in_paksha(tithi) - 1]


def tithi_shoonya_rashis(
    tithi: int, table: dict[int, tuple[int, ...]] | None = None
) -> tuple[int, ...]:
    """Rashi indices (0-11) held shoonya for this ``tithi`` (1-30). The mapping
    is by tithi-in-paksha and applies in both the Shukla and Krishna paksha."""
    return tuple((table or TITHI_SHOONYA_RASHIS_BY_TITHI).get(tithi_in_paksha(tithi), ()))


# ---------------------------------------------------------------------------
# Divisional charts (vargas) — classical Parashari.  Returns the 0-11 sign the
# planet occupies in the D-n chart.
# ---------------------------------------------------------------------------


def _d1(sign: int, deg: float) -> int:
    return sign


def _d2_hora(sign: int, deg: float) -> int:
    # Odd sign: first 15 deg -> Leo (Sun), last 15 -> Cancer (Moon). Even: reversed.
    first_half = deg < 15.0
    odd = sign % 2 == 0  # sign index 0 (Aries) is the 1st = odd
    leo, cancer = 4, 3
    if odd:
        return leo if first_half else cancer
    return cancer if first_half else leo


def _d3_drekkana(sign: int, deg: float) -> int:
    part = int(deg // 10.0)  # 0,1,2
    return (sign + (0, 4, 8)[part]) % 12


def _d7_saptamsha(sign: int, deg: float) -> int:
    part = int(deg // (30.0 / 7.0))  # 0..6
    start = sign if sign % 2 == 0 else (sign + 6) % 12
    return (start + part) % 12


def _d9_navamsha(sign: int, deg: float) -> int:
    part = int(deg // (30.0 / 9.0))  # 0..8
    mod = sign % 3
    if mod == 0:  # movable -> from same sign
        start = sign
    elif mod == 1:  # fixed -> from 9th
        start = (sign + 8) % 12
    else:  # dual -> from 5th
        start = (sign + 4) % 12
    return (start + part) % 12


def _d12_dwadashamsha(sign: int, deg: float) -> int:
    part = int(deg // 2.5)  # 0..11
    return (sign + part) % 12


def _d30_trimshamsha(sign: int, deg: float) -> int:
    odd = sign % 2 == 0
    if odd:
        # Mars 0-5, Saturn 5-10, Jupiter 10-18, Mercury 18-25, Venus 25-30
        if deg < 5:
            return 0  # Aries (Mars)
        if deg < 10:
            return 10  # Aquarius (Saturn)
        if deg < 18:
            return 8  # Sagittarius (Jupiter)
        if deg < 25:
            return 2  # Gemini (Mercury)
        return 6  # Libra (Venus)
    # even: Venus 0-5, Mercury 5-12, Jupiter 12-20, Saturn 20-25, Mars 25-30
    if deg < 5:
        return 1  # Taurus (Venus)
    if deg < 12:
        return 5  # Virgo (Mercury)
    if deg < 20:
        return 11  # Pisces (Jupiter)
    if deg < 25:
        return 9  # Capricorn (Saturn)
    return 7  # Scorpio (Mars)


#: the seven vargas used by Saptavargaja bala, in order.
SAPTAVARGA = ("D1", "D2", "D3", "D7", "D9", "D12", "D30")
_VARGA_FN = {
    "D1": _d1,
    "D2": _d2_hora,
    "D3": _d3_drekkana,
    "D7": _d7_saptamsha,
    "D9": _d9_navamsha,
    "D12": _d12_dwadashamsha,
    "D30": _d30_trimshamsha,
}


def varga_sign(lon: float, chart: str) -> int:
    """0-11 sign of a planet at sidereal ``lon`` in divisional chart ``chart``."""
    lon = norm360(lon)
    sign = int(lon // 30.0) % 12
    deg = lon % 30.0
    return _VARGA_FN[chart](sign, deg)


# ---------------------------------------------------------------------------
# Dignities / friendships (BPHS) — used by Sthana bala's Saptavargaja component.
# ---------------------------------------------------------------------------

#: deep-exaltation longitude (sidereal degrees) per graha (BPHS).
EXALTATION_DEG: dict[str, float] = {
    "SUN": 10.0,  # Aries 10
    "MOON": 33.0,  # Taurus 3
    "MARS": 298.0,  # Capricorn 28
    "MERCURY": 165.0,  # Virgo 15
    "JUPITER": 95.0,  # Cancer 5
    "VENUS": 357.0,  # Pisces 27
    "SATURN": 200.0,  # Libra 20
}

#: own signs (0-11) per graha.
OWN_SIGNS: dict[str, tuple[int, ...]] = {
    "SUN": (4,),
    "MOON": (3,),
    "MARS": (0, 7),
    "MERCURY": (2, 5),
    "JUPITER": (8, 11),
    "VENUS": (1, 6),
    "SATURN": (9, 10),
}

#: moolatrikona: (sign 0-11, start_deg, end_deg).
MOOLATRIKONA: dict[str, tuple[int, float, float]] = {
    "SUN": (4, 0.0, 20.0),
    "MOON": (1, 3.0, 30.0),
    "MARS": (0, 0.0, 12.0),
    "MERCURY": (5, 15.0, 20.0),
    "JUPITER": (8, 0.0, 10.0),
    "VENUS": (6, 0.0, 15.0),
    "SATURN": (10, 0.0, 20.0),
}

#: naisargika (permanent) relationships. Anything unlisted is neutral.
_NAISARGIKA_FRIENDS: dict[str, frozenset[str]] = {
    "SUN": frozenset({"MOON", "MARS", "JUPITER"}),
    "MOON": frozenset({"SUN", "MERCURY"}),
    "MARS": frozenset({"SUN", "MOON", "JUPITER"}),
    "MERCURY": frozenset({"SUN", "VENUS"}),
    "JUPITER": frozenset({"SUN", "MOON", "MARS"}),
    "VENUS": frozenset({"MERCURY", "SATURN"}),
    "SATURN": frozenset({"MERCURY", "VENUS"}),
}
_NAISARGIKA_ENEMIES: dict[str, frozenset[str]] = {
    "SUN": frozenset({"VENUS", "SATURN"}),
    "MOON": frozenset(),
    "MARS": frozenset({"MERCURY"}),
    "MERCURY": frozenset({"MOON"}),
    "JUPITER": frozenset({"MERCURY", "VENUS"}),
    "VENUS": frozenset({"SUN", "MOON"}),
    "SATURN": frozenset({"SUN", "MOON", "MARS"}),
}

#: Saptavargaja points per relationship tier (BPHS, virupas).
_DIGNITY_POINTS = {
    "moolatrikona": 45.0,
    "own": 30.0,
    "great_friend": 22.5,
    "friend": 15.0,
    "neutral": 7.5,
    "enemy": 3.75,
    "great_enemy": 1.875,
}


def _naisargika_relation(planet: str, other: str) -> int:
    if other in _NAISARGIKA_FRIENDS.get(planet, ()):
        return 1
    if other in _NAISARGIKA_ENEMIES.get(planet, ()):
        return -1
    return 0


def natural_relation(planet: str, other: str) -> str:
    """Parashari naisargika (permanent) relation of ``other`` to ``planet`` as a
    label: ``"friend"`` / ``"neutral"`` / ``"enemy"``. Rahu / Ketu are unlisted
    → ``"neutral"`` with any graha. Names are the uppercase VIM spelling."""
    r = _naisargika_relation(planet.upper(), other.upper())
    return "friend" if r > 0 else "enemy" if r < 0 else "neutral"


def temporal_relation(planet_sign: int, other_sign: int) -> int:
    """Tatkalika: +1 if ``other`` sits in houses 2,3,4,10,11,12 from ``planet``."""
    house = ((other_sign - planet_sign) % 12) + 1
    return 1 if house in (2, 3, 4, 10, 11, 12) else -1


def compound_relation(planet: str, other: str, planet_sign: int, other_sign: int) -> int:
    """5-tier compound friendship: -2 great enemy .. +2 great friend."""
    if planet == other:
        return 2
    return _naisargika_relation(planet, other) + temporal_relation(planet_sign, other_sign)


def dignity_points(planet: str, sign: int, deg_in_sign: float | None, other_lord: str) -> float:
    """Saptavargaja points for ``planet`` occupying ``sign`` (whose lord is
    ``other_lord``). ``deg_in_sign`` enables the moolatrikona check for D1."""
    mt = MOOLATRIKONA[planet]
    if deg_in_sign is not None and sign == mt[0] and mt[1] <= deg_in_sign < mt[2]:
        return _DIGNITY_POINTS["moolatrikona"]
    if sign in OWN_SIGNS[planet]:
        return _DIGNITY_POINTS["own"]
    # relationship to the sign lord, using natural relationship only for varga
    rel = _naisargika_relation(planet, other_lord)
    return {
        1: _DIGNITY_POINTS["friend"],
        0: _DIGNITY_POINTS["neutral"],
        -1: _DIGNITY_POINTS["enemy"],
    }[rel]


@dataclass(frozen=True, slots=True)
class PlacementDignity:
    """Human-readable dignity of a planet in D1 (for the positions table)."""

    label: str  # exalted | moolatrikona | own | friend | neutral | enemy | debilitated


def d1_dignity(planet: str, lon: float) -> str:
    sign = rashi_index(lon)
    deg = degree_in_sign(lon)
    ex = EXALTATION_DEG[planet]
    if arc_distance(lon, ex) <= 1.0:
        return "exalted"
    if arc_distance(lon, (ex + 180.0) % 360.0) <= 1.0:
        return "debilitated"
    mt = MOOLATRIKONA[planet]
    if sign == mt[0] and mt[1] <= deg < mt[2]:
        return "moolatrikona"
    if sign in OWN_SIGNS[planet]:
        return "own"
    rel = _naisargika_relation(planet, RASHI_LORDS[sign])
    return {1: "friend", 0: "neutral", -1: "enemy"}[rel]
