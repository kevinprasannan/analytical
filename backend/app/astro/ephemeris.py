"""Swiss Ephemeris wrapper — sidereal (Lahiri) positions + supporting geometry.

Thin, deterministic layer over ``pysweph`` (imported as ``swisseph``). All
inputs are tz-aware datetimes; all longitudes returned are **sidereal** (Lahiri
ayanamsha applied) unless a name says otherwise. Ephemeris data files
(``sepl_18.se1`` / ``semo_18.se1``, 1800-2399 CE) are bundled under
``app/astro/ephe`` so the calculation is fully offline and reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import cached_property
from pathlib import Path

import swisseph as swe

from app.astro import vedic

_EPHE_DIR = Path(__file__).resolve().parent / "ephe"

_SWE_BODY: dict[str, int] = {
    "SUN": swe.SUN,
    "MOON": swe.MOON,
    "MARS": swe.MARS,
    "MERCURY": swe.MERCURY,
    "JUPITER": swe.JUPITER,
    "VENUS": swe.VENUS,
    "SATURN": swe.SATURN,
    "RAHU": swe.MEAN_NODE,  # mean lunar node (docs/13 §2 — mean, not true)
}


@dataclass(frozen=True, slots=True)
class BodyPosition:
    graha: str
    longitude: float  # sidereal ecliptic longitude, 0-360
    latitude: float
    speed_long: float  # deg/day (sidereal); < 0 => retrograde
    retrograde: bool
    rashi_index: int  # 0-11
    rashi: str
    degree: float  # degrees within the sign, 0-30
    nakshatra_index: int  # 0-26
    nakshatra: str
    pada: int  # 1-4
    nakshatra_lord: str
    dignity: str  # exalted | moolatrikona | own | friend | neutral | enemy | debilitated


class AstroEngine:
    """Reusable engine. Swiss Ephemeris global state (ephe path, sidereal mode)
    is set once per process on construction."""

    def __init__(self, *, ayanamsha: int = swe.SIDM_LAHIRI, ephe_dir: Path | None = None) -> None:
        swe.set_ephe_path(str(ephe_dir or _EPHE_DIR))
        swe.set_sid_mode(ayanamsha, 0.0, 0.0)
        self._ayanamsha = ayanamsha
        self._calc_flags = swe.FLG_SWIEPH | swe.FLG_SIDEREAL | swe.FLG_SPEED

    # -- time --------------------------------------------------------------
    @staticmethod
    def julday_ut(dt: datetime) -> float:
        u = dt.astimezone(UTC)
        hour = u.hour + u.minute / 60.0 + (u.second + u.microsecond / 1e6) / 3600.0
        return swe.julday(u.year, u.month, u.day, hour, swe.GREG_CAL)

    # -- ayanamsha -------------------------------------------------------
    def ayanamsha(self, dt: datetime) -> float:
        return swe.get_ayanamsa_ut(self.julday_ut(dt))

    # -- one body ------------------------------------------------------
    def _raw_longitude(self, jd: float, graha: str) -> tuple[float, float, float]:
        """(sidereal_longitude, latitude, speed_long) for a real SE body."""
        xx, _retflag, _serr = swe.calc_ut(jd, _SWE_BODY[graha], self._calc_flags)
        return xx[0], xx[1], xx[3]

    def position(self, dt: datetime, graha: str) -> BodyPosition:
        jd = self.julday_ut(dt)
        if graha == "KETU":
            lon_r, lat, spd = self._raw_longitude(jd, "RAHU")
            lon = vedic.norm360(lon_r + 180.0)
            lat = -lat
        else:
            lon, lat, spd = self._raw_longitude(jd, graha)
            lon = vedic.norm360(lon)
        ni, pada = vedic.nakshatra_pada(lon)
        retro = graha in ("RAHU", "KETU") or spd < 0.0
        dignity = "" if graha in ("RAHU", "KETU") else vedic.d1_dignity(graha, lon)
        return BodyPosition(
            graha=graha,
            longitude=lon,
            latitude=lat,
            speed_long=spd,
            retrograde=retro,
            rashi_index=vedic.rashi_index(lon),
            rashi=vedic.rashi_name(lon),
            degree=vedic.degree_in_sign(lon),
            nakshatra_index=ni,
            nakshatra=vedic.NAKSHATRAS[ni],
            pada=pada,
            nakshatra_lord=vedic.NAKSHATRA_LORDS[ni],
            dignity=dignity,
        )

    def positions(self, dt: datetime) -> list[BodyPosition]:
        return [self.position(dt, g) for g in vedic.GRAHAS]

    # -- equatorial declination (tropical frame) — for Ayana bala -------
    def declination(self, dt: datetime, graha: str) -> float:
        jd = self.julday_ut(dt)
        body = "RAHU" if graha == "KETU" else graha
        flags = swe.FLG_SWIEPH | swe.FLG_EQUATORIAL
        xx, _r, _s = swe.calc_ut(jd, _SWE_BODY[body], flags)
        dec = xx[1]
        return -dec if graha == "KETU" else dec

    # -- ascendant + equal houses (sidereal) --------------------------
    def ascendant(self, dt: datetime, lat: float, lon_deg: float) -> float:
        jd = self.julday_ut(dt)
        # 'W' = whole-sign; ascmc[0] is the ascendant in the tropical frame.
        _cusps, ascmc = swe.houses_ex(jd, lat, lon_deg, b"W", swe.FLG_SIDEREAL)
        return vedic.norm360(ascmc[0])

    # -- sunrise / sunset --------------------------------------------
    @cached_property
    def _rise_flags(self) -> int:
        return swe.CALC_RISE | swe.BIT_DISC_CENTER | swe.BIT_NO_REFRACTION

    def _rise_trans(self, jd_start: float, lat: float, lon_deg: float, rising: bool) -> float:
        rsmi = (swe.CALC_RISE if rising else swe.CALC_SET) | swe.BIT_DISC_CENTER
        # signature: rise_trans(tjdut, body, rsmi, geopos, atpress, attemp, flags)
        _res, tret = swe.rise_trans(
            jd_start, swe.SUN, rsmi, (lon_deg, lat, 0.0), 0.0, 0.0, swe.FLG_SWIEPH
        )
        return tret[0]

    def sunrise_sunset(self, d: date, lat: float, lon_deg: float) -> tuple[datetime, datetime]:
        jd0 = swe.julday(d.year, d.month, d.day, 0.0, swe.GREG_CAL)
        jd_rise = self._rise_trans(jd0, lat, lon_deg, rising=True)
        jd_set = self._rise_trans(jd_rise, lat, lon_deg, rising=False)
        return _jd_to_dt(jd_rise), _jd_to_dt(jd_set)


def _jd_to_dt(jd: float) -> datetime:
    y, m, d, h = swe.revjul(jd, swe.GREG_CAL)
    hh = int(h)
    mm = int((h - hh) * 60)
    ss = int(round((((h - hh) * 60) - mm) * 60))
    if ss == 60:
        ss = 59
    return datetime(y, m, d, hh, mm, ss, tzinfo=UTC)
