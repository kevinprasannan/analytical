"""Classical Parashari Shadbala (six-fold planetary strength).

Implemented from BPHS / B.V. Raman *Graha and Bhava Balas*. Units are **virupas**
(60 virupa = 1 rupa). Computed for the seven planets only (Rahu/Ketu carry no
classical Shadbala).

Documented method choices / simplifications (docs/13 §4):
  * Saptavargaja uses the *compound* (natural + temporal) relationship, temporal
    taken from D1 sign positions.
  * Houses for Kendradi / aspect counting are **whole-sign** from the lagna
    rasi; Dig Bala uses equal-house cusps from the exact ascendant degree.
  * Nathonnatha uses local **mean** solar time (equation-of-time omitted;
    <= ~1.3 virupa effect).
  * Drik Bala uses the discrete Parashari graha-drishti fractions (1/4, 1/2,
    3/4, full) rather than the continuous Sphuta-drishti curve.
  * Graha-yuddha (planetary war) correction is **not applied** — only flagged
    (`graha_yuddha`); its classical formula is not standardised and it bites
    only on sub-1 deg conjunctions.

Cross-check the totals against Jagannatha Hora (JHora) desktop before relying on
them for analysis — see docs/13 §6.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import swisseph as swe

from app.astro import vedic
from app.astro.ephemeris import AstroEngine, BodyPosition

_PLANETS = vedic.SHADBALA_GRAHAS  # SUN..SATURN

_NAISARGIKA = {  # virupas — 60 * n/7
    "SUN": 60.0,
    "MOON": 60.0 * 6 / 7,
    "VENUS": 60.0 * 5 / 7,
    "JUPITER": 60.0 * 4 / 7,
    "MERCURY": 60.0 * 3 / 7,
    "MARS": 60.0 * 2 / 7,
    "SATURN": 60.0 * 1 / 7,
}

_REQUIRED_RUPA = {  # minimum Shadbala for a planet to be deemed adequately strong
    "SUN": 5.0,
    "MOON": 6.0,
    "MARS": 5.0,
    "MERCURY": 7.0,
    "JUPITER": 6.5,
    "VENUS": 5.5,
    "SATURN": 5.0,
}

_WEEKDAY_LORD = ("MOON", "MARS", "MERCURY", "JUPITER", "VENUS", "SATURN", "SUN")  # Mon..Sun
_CHALDEAN = ("SATURN", "JUPITER", "MARS", "SUN", "VENUS", "MERCURY", "MOON")

_DIGNITY_POINTS = vedic._DIGNITY_POINTS


# ======================================================================================
# context
# ======================================================================================


@dataclass(slots=True)
class _Ctx:
    engine: AstroEngine
    dt: datetime
    lat: float
    lon: float
    pos: dict[str, BodyPosition]
    asc_lon: float
    asc_sign: int
    sunrise: datetime
    sunset: datetime
    next_sunrise: datetime
    is_day: bool
    ayan: float
    _ingress_memo: dict = field(default_factory=dict)

    def weekday_lord(self) -> str:
        # vedic day starts at sunrise; at 09:00 IST we are always past sunrise
        return _WEEKDAY_LORD[self.dt.astimezone(_IST).weekday()]


_IST = UTC  # replaced at runtime below with a real +5:30 tzinfo
from datetime import timezone as _tz  # noqa: E402

_IST = _tz(timedelta(hours=5, minutes=30))


def _build_ctx(engine: AstroEngine, dt: datetime, lat: float, lon: float) -> _Ctx:
    pos = {p.graha: p for p in engine.positions(dt)}
    asc = engine.ascendant(dt, lat, lon)
    d = dt.astimezone(_IST).date()
    sr, ssunset = engine.sunrise_sunset(d, lat, lon)
    nsr, _ = engine.sunrise_sunset(d + timedelta(days=1), lat, lon)
    u = dt.astimezone(UTC)
    is_day = sr <= u < ssunset
    return _Ctx(
        engine=engine,
        dt=dt,
        lat=lat,
        lon=lon,
        pos=pos,
        asc_lon=asc,
        asc_sign=vedic.rashi_index(asc),
        sunrise=sr,
        sunset=ssunset,
        next_sunrise=nsr,
        is_day=is_day,
        ayan=engine.ayanamsha(dt),
    )


# ======================================================================================
# 1. Sthana bala
# ======================================================================================


def _uccha_bala(planet: str, lon: float) -> float:
    debil = (vedic.EXALTATION_DEG[planet] + 180.0) % 360.0
    return vedic.arc_distance(lon, debil) / 3.0


def _compound_points(planet: str, sign: int, deg_in_sign: float | None, ctx: _Ctx) -> float:
    mt = vedic.MOOLATRIKONA[planet]
    if deg_in_sign is not None and sign == mt[0] and mt[1] <= deg_in_sign < mt[2]:
        return _DIGNITY_POINTS["moolatrikona"]
    if sign in vedic.OWN_SIGNS[planet]:
        return _DIGNITY_POINTS["own"]
    lord = vedic.RASHI_LORDS[sign]
    if lord == planet:
        return _DIGNITY_POINTS["own"]
    rel = vedic.compound_relation(
        planet, lord, ctx.pos[planet].rashi_index, ctx.pos[lord].rashi_index
    )
    return {
        2: _DIGNITY_POINTS["great_friend"],
        1: _DIGNITY_POINTS["friend"],
        0: _DIGNITY_POINTS["neutral"],
        -1: _DIGNITY_POINTS["enemy"],
        -2: _DIGNITY_POINTS["great_enemy"],
    }[rel]


def _saptavargaja_bala(planet: str, lon: float, ctx: _Ctx) -> float:
    total = 0.0
    for i, chart in enumerate(vedic.SAPTAVARGA):
        sign = vedic.varga_sign(lon, chart)
        deg = vedic.degree_in_sign(lon) if i == 0 else None
        total += _compound_points(planet, sign, deg, ctx)
    return total


def _oja_yugma_bala(planet: str, lon: float) -> float:
    d1_sign = vedic.rashi_index(lon)
    d9_sign = vedic.varga_sign(lon, "D9")
    d1_odd = d1_sign % 2 == 0
    d9_odd = d9_sign % 2 == 0
    if planet in ("MOON", "VENUS"):
        return (0.0 if d1_odd else 15.0) + (0.0 if d9_odd else 15.0)
    return (15.0 if d1_odd else 0.0) + (15.0 if d9_odd else 0.0)


def _kendradi_bala(planet: str, ctx: _Ctx) -> float:
    house = ((ctx.pos[planet].rashi_index - ctx.asc_sign) % 12) + 1
    if house in (1, 4, 7, 10):
        return 60.0
    if house in (2, 5, 8, 11):
        return 30.0
    return 15.0


def _drekkana_bala(planet: str, lon: float) -> float:
    third = int(vedic.degree_in_sign(lon) // 10.0)  # 0,1,2
    groups = {0: ("SUN", "JUPITER", "MARS"), 1: ("SATURN", "MERCURY"), 2: ("MOON", "VENUS")}
    return 15.0 if planet in groups[third] else 0.0


def _sthana_bala(planet: str, ctx: _Ctx) -> dict[str, float]:
    lon = ctx.pos[planet].longitude
    return {
        "uccha": _uccha_bala(planet, lon),
        "saptavargaja": _saptavargaja_bala(planet, lon, ctx),
        "oja_yugma": _oja_yugma_bala(planet, lon),
        "kendradi": _kendradi_bala(planet, ctx),
        "drekkana": _drekkana_bala(planet, lon),
    }


# ======================================================================================
# 2. Dig bala
# ======================================================================================

_DIG_STRONG_HOUSE = {
    "SUN": 10,
    "MARS": 10,
    "JUPITER": 1,
    "MERCURY": 1,
    "MOON": 4,
    "VENUS": 4,
    "SATURN": 7,
}


def _dig_bala(planet: str, ctx: _Ctx) -> float:
    powerless_house = (_DIG_STRONG_HOUSE[planet] + 6 - 1) % 12 + 1
    powerless_cusp = vedic.norm360(ctx.asc_lon + (powerless_house - 1) * 30.0)
    return vedic.arc_distance(ctx.pos[planet].longitude, powerless_cusp) / 3.0


# ======================================================================================
# 3. Kala bala
# ======================================================================================

_DIURNAL = ("SUN", "JUPITER", "VENUS")
_NOCTURNAL = ("MOON", "MARS", "SATURN")


def _local_mean_day_fraction(ctx: _Ctx) -> float:
    u = ctx.dt.astimezone(UTC)
    lmt = u + timedelta(hours=ctx.lon / 15.0)
    secs = lmt.hour * 3600 + lmt.minute * 60 + lmt.second
    return secs / 86400.0


def _nathonnatha_bala(planet: str, ctx: _Ctx) -> float:
    if planet == "MERCURY":
        return 60.0
    frac = _local_mean_day_fraction(ctx)
    noonness = 1.0 - 2.0 * abs(frac - 0.5)  # 0 at midnight, 1 at local noon
    if planet in _DIURNAL:
        return 60.0 * noonness
    return 60.0 * (1.0 - noonness)


def _is_benefic(planet: str, ctx: _Ctx) -> bool:
    if planet in ("JUPITER", "VENUS", "MERCURY"):
        return True
    if planet == "MOON":
        elong = (ctx.pos["MOON"].longitude - ctx.pos["SUN"].longitude) % 360.0
        return 0.0 < elong < 180.0  # waxing
    return False


def _paksha_bala(planet: str, ctx: _Ctx) -> float:
    elong = vedic.arc_distance(ctx.pos["MOON"].longitude, ctx.pos["SUN"].longitude)  # 0..180
    benefic_raw = elong / 3.0  # 0..60
    if _is_benefic(planet, ctx):
        return benefic_raw * 2.0
    return 60.0 - benefic_raw


def _tribhaga_bala(planet: str, ctx: _Ctx) -> float:
    if planet == "JUPITER":
        return 60.0
    u = ctx.dt.astimezone(UTC)
    if ctx.is_day:
        span = (ctx.sunset - ctx.sunrise) / 3
        idx = int((u - ctx.sunrise) / span)
        rulers = ("MERCURY", "SUN", "SATURN")
    else:
        start = ctx.sunset if u >= ctx.sunset else ctx.sunset - timedelta(days=1)
        end = ctx.next_sunrise if u >= ctx.sunset else ctx.sunrise
        span = (end - start) / 3
        idx = int((u - start) / span)
        rulers = ("MOON", "VENUS", "MARS")
    idx = min(max(idx, 0), 2)
    return 60.0 if planet == rulers[idx] else 0.0


#: process-wide cache of Sun's sidereal sign by date ordinal (noon IST) — shared
#: across every date in a backfill run so the varsha/masa walk-backs are cheap.
_SUN_SIGN_BY_ORDINAL: dict[int, int] = {}


def _sun_sign_on(ctx: _Ctx, d_ordinal: int) -> int:
    hit = _SUN_SIGN_BY_ORDINAL.get(d_ordinal)
    if hit is None:
        g = datetime.fromordinal(d_ordinal)
        probe = datetime(g.year, g.month, g.day, 12, 0, tzinfo=_IST)
        hit = ctx.engine.position(probe, "SUN").rashi_index
        _SUN_SIGN_BY_ORDINAL[d_ordinal] = hit
    return hit


def _sun_sidereal_sign_ingress_weekday_lord(ctx: _Ctx, *, year_start: bool) -> str:
    """Weekday lord of the day the Sun most recently entered its current sidereal
    sign (masa) or sidereal Aries (varsha)."""
    key = ("varsha" if year_start else "masa", ctx.dt.date().toordinal())
    if key in ctx._ingress_memo:
        return ctx._ingress_memo[key]
    today = ctx.dt.date().toordinal()
    d = today
    if year_start:
        steps = 0
        while _sun_sign_on(ctx, d) != 0 and steps < 380:
            d -= 1
            steps += 1
        while _sun_sign_on(ctx, d - 1) == 0 and steps < 400:
            d -= 1
            steps += 1
        ingress = d
    else:
        target = ctx.pos["SUN"].rashi_index
        while today - d < 40 and _sun_sign_on(ctx, d - 1) == target:
            d -= 1
        ingress = d
    lord = _WEEKDAY_LORD[datetime.fromordinal(ingress).weekday()]
    ctx._ingress_memo[key] = lord
    return lord


def _year_month_day_hour_bala(planet: str, ctx: _Ctx) -> dict[str, float]:
    vara = ctx.weekday_lord()
    # planetary hour
    u = ctx.dt.astimezone(UTC)
    if ctx.is_day:
        hora_span = (ctx.sunset - ctx.sunrise) / 12.0
        h_idx = int((u - ctx.sunrise) / hora_span)
    else:
        start = ctx.sunset if u >= ctx.sunset else ctx.sunset - timedelta(days=1)
        end = ctx.next_sunrise if u >= ctx.sunset else ctx.sunrise
        hora_span = (end - start) / 12.0
        h_idx = 12 + int((u - start) / hora_span)
    start_lord = _CHALDEAN.index(vara)
    hora_lord = _CHALDEAN[(start_lord + max(h_idx, 0)) % 7]
    masa = _sun_sidereal_sign_ingress_weekday_lord(ctx, year_start=False)
    varsha = _sun_sidereal_sign_ingress_weekday_lord(ctx, year_start=True)
    return {
        "varsha": 15.0 if planet == varsha else 0.0,
        "masa": 30.0 if planet == masa else 0.0,
        "vara": 45.0 if planet == vara else 0.0,
        "hora": 60.0 if planet == hora_lord else 0.0,
    }


def _ayana_bala(planet: str, ctx: _Ctx) -> float:
    dec = ctx.engine.declination(ctx.dt, planet)
    s = -1.0 if planet in ("MOON", "SATURN") else 1.0
    val = (24.0 + s * dec) * 60.0 / 48.0
    val = min(max(val, 0.0), 60.0)
    if planet == "SUN":
        val *= 2.0
    return val


def _in_graha_yuddha(planet: str, ctx: _Ctx) -> bool:
    if planet in ("SUN", "MOON"):
        return False
    for other in ("MARS", "MERCURY", "JUPITER", "VENUS", "SATURN"):
        if (
            other != planet
            and vedic.arc_distance(ctx.pos[planet].longitude, ctx.pos[other].longitude) < 1.0
        ):
            return True
    return False


def _kala_bala(planet: str, ctx: _Ctx) -> dict[str, float]:
    out = {
        "nathonnatha": _nathonnatha_bala(planet, ctx),
        "paksha": _paksha_bala(planet, ctx),
        "tribhaga": _tribhaga_bala(planet, ctx),
        "ayana": _ayana_bala(planet, ctx),
        "yuddha": 0.0,
    }
    out.update(_year_month_day_hour_bala(planet, ctx))
    return out


# ======================================================================================
# 4. Cheshta bala
# ======================================================================================


def _cheshta_bala(planet: str, ctx: _Ctx, ayana_bala: float, paksha_bala: float) -> float:
    if planet == "SUN":
        return ayana_bala
    if planet == "MOON":
        return paksha_bala
    jd = ctx.engine.julday_ut(ctx.dt)
    planet_trop = vedic.norm360(ctx.pos[planet].longitude + ctx.ayan)
    if planet in ("MARS", "JUPITER", "SATURN"):
        seeghrocha = vedic.norm360(ctx.pos["SUN"].longitude + ctx.ayan)
    else:  # MERCURY, VENUS -> heliocentric longitude
        body = {"MERCURY": swe.MERCURY, "VENUS": swe.VENUS}[planet]
        xx, _r, _s = swe.calc_ut(jd, body, swe.FLG_SWIEPH | swe.FLG_HELCTR)
        seeghrocha = vedic.norm360(xx[0])
    kendra = vedic.norm360(seeghrocha - planet_trop)
    if kendra > 180.0:
        kendra = 360.0 - kendra
    return kendra / 3.0


# ======================================================================================
# 6. Drik bala
# ======================================================================================

_SPECIAL_FULL = {  # houses (from aspecting planet) that get FULL aspect beyond the 7th
    "MARS": (4, 8),
    "JUPITER": (5, 9),
    "SATURN": (3, 10),
}
_FRACTION_BY_HOUSE = {3: 0.25, 10: 0.25, 5: 0.5, 9: 0.5, 4: 0.75, 8: 0.75, 7: 1.0}


def _drishti_virupa(src: str, src_sign: int, tgt_sign: int) -> float:
    house = ((tgt_sign - src_sign) % 12) + 1
    if house in _SPECIAL_FULL.get(src, ()):
        return 60.0
    frac = _FRACTION_BY_HOUSE.get(house, 0.0)
    return frac * 60.0


def _drik_bala(planet: str, ctx: _Ctx) -> float:
    tgt_sign = ctx.pos[planet].rashi_index
    total = 0.0
    for src in _PLANETS:
        if src == planet:
            continue
        v = _drishti_virupa(src, ctx.pos[src].rashi_index, tgt_sign)
        if v == 0.0:
            continue
        total += v if _is_benefic(src, ctx) else -v
    return total / 4.0


# ======================================================================================
# result + top-level
# ======================================================================================


@dataclass(frozen=True, slots=True)
class ShadbalaResult:
    graha: str
    sthana: dict[str, float]
    dig: float
    kala: dict[str, float]
    cheshta: float
    naisargika: float
    drik: float
    sthana_total: float
    kala_total: float
    total_virupa: float
    total_rupa: float
    required_rupa: float
    ratio: float
    rank: int
    ishta_phala: float
    kashta_phala: float
    graha_yuddha: bool

    def flat(self) -> dict[str, float]:
        """Flattened virupa components for storage / inspection."""
        d = {f"sthana_{k}": v for k, v in self.sthana.items()}
        d.update({f"kala_{k}": v for k, v in self.kala.items()})
        d.update(
            sthana_total=self.sthana_total,
            dig=self.dig,
            kala_total=self.kala_total,
            cheshta=self.cheshta,
            naisargika=self.naisargika,
            drik=self.drik,
            total_virupa=self.total_virupa,
        )
        return d


def compute_shadbala(
    engine: AstroEngine, dt: datetime, lat: float, lon: float
) -> dict[str, ShadbalaResult]:
    ctx = _build_ctx(engine, dt, lat, lon)
    raw: dict[str, dict] = {}
    for p in _PLANETS:
        sthana = _sthana_bala(p, ctx)
        kala = _kala_bala(p, ctx)
        cheshta = _cheshta_bala(p, ctx, kala["ayana"], kala["paksha"])
        raw[p] = {
            "sthana": sthana,
            "dig": _dig_bala(p, ctx),
            "kala": kala,
            "cheshta": cheshta,
            "naisargika": _NAISARGIKA[p],
            "drik": _drik_bala(p, ctx),
            "yuddha": _in_graha_yuddha(p, ctx),
        }

    totals = {
        p: sum(r["sthana"].values())
        + r["dig"]
        + sum(r["kala"].values())
        + r["cheshta"]
        + r["naisargika"]
        + r["drik"]
        for p, r in raw.items()
    }
    order = sorted(totals, key=lambda p: totals[p], reverse=True)
    ranks = {p: i + 1 for i, p in enumerate(order)}

    out: dict[str, ShadbalaResult] = {}
    for p, r in raw.items():
        sthana_total = sum(r["sthana"].values())
        kala_total = sum(r["kala"].values())
        tv = totals[p]
        uccha = r["sthana"]["uccha"]
        ishta = math.sqrt(max(uccha, 0.0) * max(r["cheshta"], 0.0))
        kashta = math.sqrt(max(60.0 - uccha, 0.0) * max(60.0 - r["cheshta"], 0.0))
        out[p] = ShadbalaResult(
            graha=p,
            sthana=r["sthana"],
            dig=r["dig"],
            kala=r["kala"],
            cheshta=r["cheshta"],
            naisargika=r["naisargika"],
            drik=r["drik"],
            sthana_total=sthana_total,
            kala_total=kala_total,
            total_virupa=tv,
            total_rupa=tv / 60.0,
            required_rupa=_REQUIRED_RUPA[p],
            ratio=(tv / 60.0) / _REQUIRED_RUPA[p],
            rank=ranks[p],
            ishta_phala=ishta,
            kashta_phala=kashta,
            graha_yuddha=bool(r["yuddha"]),
        )
    return out
