"""Astro x market study response (docs/07 §4.9, docs/13 §5.1). Descriptive
statistics only — no forecast, no execution label."""

from __future__ import annotations

from pydantic import BaseModel, Field


class StudyBucket(BaseModel):
    key: str
    n: int
    mean_ret: float  # % close-to-close, mean over the bucket
    median_ret: float
    std_ret: float  # population std of daily % return
    pct_up: float  # share of up-days, 0-100
    mean_range: float  # % (high-low)/prior close
    total_ret: float  # simple sum of daily % (not compounded)
    best: float
    worst: float


class AstroStudyResponse(BaseModel):
    underlying: str
    first: str  # ISO date
    last: str
    n_days: int
    baseline: StudyBucket
    by_weekday: list[StudyBucket] = Field(default_factory=list)
    by_weekday_lord: list[StudyBucket] = Field(default_factory=list)
    by_moon_nakshatra: list[StudyBucket] = Field(default_factory=list)
    by_moon_nakshatra_lord: list[StudyBucket] = Field(default_factory=list)
    by_lagna_rashi: list[StudyBucket] = Field(default_factory=list)
    by_moon_rashi: list[StudyBucket] = Field(default_factory=list)
    by_tithi: list[StudyBucket] = Field(default_factory=list)
    by_paksha: list[StudyBucket] = Field(default_factory=list)


class DayLogRow(BaseModel):
    d: str  # ISO date
    month: int  # 1..12
    day: int  # 1..31 (day of month)
    close: float
    prev_close: float
    ret_pct: float  # % close-to-close vs prior day
    range_pct: float  # % (high-low)/prior close, intraday only
    gap_pct: float  # % open vs prior close — the overnight move
    weekday: int  # 0=Mon .. 6=Sun
    day_name: str
    weekday_lord: str
    tithi: int  # 1..30
    paksha: str  # Shukla | Krishna
    moon_nakshatra: str
    moon_nakshatra_lord: str
    moon_rashi: str
    moon_pada: int  # 1..4
    lagna_rashi: str
    sun_rashi: str
    # Moon-anchored dasha running at session open (390-min basis); null pre-2000
    dasha_lord: str | None = None
    dasha_sub_lord: str | None = None
    dasha_balance_hms: str | None = None


class DayLogResponse(BaseModel):
    underlying: str
    first: str | None = None  # first date in the filtered set
    last: str | None = None
    total: int  # matching days (before pagination)
    limit: int
    offset: int
    sort: str
    filters: dict[str, str] = Field(default_factory=dict)
    summary: StudyBucket  # descriptive stats over the whole filtered set
    items: list[DayLogRow] = Field(default_factory=list)


# -- almanac (the sky for any day, candle or not) --------------------------


class AlmanacRow(BaseModel):
    d: str  # ISO date
    month: int
    day: int  # 1..31 (day of month)
    weekday: int
    day_name: str
    weekday_lord: str
    tithi: int
    paksha: str
    moon_nakshatra: str
    moon_nakshatra_lord: str
    moon_rashi: str
    moon_pada: int
    lagna_rashi: str
    lagna_nakshatra: str
    sun_rashi: str
    sunrise_ts: str | None = None
    sunset_ts: str | None = None
    has_candle: bool
    close: float | None = None
    ret_pct: float | None = None
    range_pct: float | None = None


class AlmanacResponse(BaseModel):
    underlying: str
    first: str | None = None
    last: str | None = None
    total: int
    with_candle: int
    limit: int
    offset: int
    sort: str
    filters: dict[str, str] = Field(default_factory=dict)
    items: list[AlmanacRow] = Field(default_factory=list)


# -- single-day drill-down (docs/13 §5.2) ------------------------------------


class DayD1(BaseModel):
    ts: str | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: float | None = None
    prev_close: float | None = None
    ret_pct: float | None = None  # % close vs prior close (open-to-close + gap)
    range_pct: float | None = None  # % (high-low) vs prior close — intraday only
    gap_pct: float | None = None  # % open vs prior close — the overnight move


class DayHourBar(BaseModel):
    ts: str
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: float | None = None


class DayMarket(BaseModel):
    d1: DayD1 | None = None
    hourly: list[DayHourBar] = Field(default_factory=list)  # H1 bars
    m15: list[DayHourBar] = Field(default_factory=list)  # M15 bars (same session)
    m5: list[DayHourBar] = Field(default_factory=list)  # M5 bars (same session)


class DayChartScalars(BaseModel):
    weekday: int
    day_name: str
    weekday_lord: str
    tithi: int
    paksha: str
    moon_nakshatra: str
    moon_nakshatra_lord: str
    moon_rashi: str
    moon_rashi_index: int
    moon_pada: int
    lagna_longitude: float | None = None  # sidereal ascendant, degrees 0–360
    lagna_rashi: str
    lagna_rashi_index: int
    lagna_nakshatra: str
    lagna_pada: int
    sun_rashi: str
    sun_rashi_index: int
    sunrise_ts: str | None = None
    sunset_ts: str | None = None
    ayanamsha: float | None = None
    chandra_masa: str | None = None  # amanta lunar month (approx — see tithi_shoonya)


class DayPlanet(BaseModel):
    body: str
    longitude: float
    degree: float
    rashi: str
    rashi_index: int
    nakshatra: str
    nakshatra_index: int
    pada: int
    nakshatra_lord: str
    retrograde: bool
    speed_longitude: float | None = None
    dignity: str | None = None
    # whole-sign house counted from each reference point + its trikona group
    house_from_lagna: int | None = None
    house_group_lagna: str | None = None  # Dharma | Artha | Kama | Moksha
    # equal house anchored on the exact lagna degree (Sripati-style)
    house_from_lagna_deg: int | None = None
    house_group_lagna_deg: str | None = None
    # equal house anchored on the exact degree of the Moon's current
    # nakshatra-lord (the reference graha itself changes as the Moon moves
    # nakshatra to nakshatra)
    house_from_naklord_deg: int | None = None
    house_group_naklord_deg: str | None = None
    house_from_moon: int | None = None
    house_group_moon: str | None = None
    house_from_sun: int | None = None
    house_group_sun: str | None = None
    # what shifted since the previous weekday (astro.prev_date)
    prev_rashi: str | None = None
    prev_nakshatra: str | None = None
    prev_pada: int | None = None
    prev_retrograde: bool | None = None
    changed_rashi: bool = False
    changed_nakshatra: bool = False
    changed_pada: bool = False
    changed_retrograde: bool = False


class DayHouseGroup(BaseModel):
    group: str  # Dharma (1·5·9) | Artha (2·6·10) | Kama (3·7·11) | Moksha (4·8·12)
    houses: list[int]
    bodies: list[str]  # reference point + grahas whose whole-sign house falls here


class DayHouseFrame(BaseModel):
    frame: str  # lagna | lagna_deg | naklord_deg | moon | sun
    reference: str  # Lagna | Lagna (by degree) | Moon's nakshatra-lord (by degree) | Moon | Sun
    groups: list[DayHouseGroup]


class DayBadhaka(BaseModel):
    frame: str  # lagna | moon | naklord
    reference: str  # Lagna | Moon | Moon's nakshatra-lord (<graha>)
    reference_sign: str
    movability: str  # MOVABLE | FIXED | DUAL  (→ 11th / 9th / 7th is badhaka)
    badhaka_house: int  # 11 | 9 | 7 from the reference
    badhaka_sign: str
    badhaka_lord: str  # the Baadhagaadhipathi
    badhaka_lord_house_from_ref: int | None = None  # where that lord currently sits


class DayShoonyaRashi(BaseModel):
    index: int  # 0–11
    name: str


class DayBodyInShoonya(BaseModel):
    body: str
    rashi: str


class DayTithiShoonya(BaseModel):
    chandra_masa: str | None = None  # amanta lunar month
    chandra_masa_approx: bool = True
    paksha: str
    tithi: int  # 1–30
    tithi_in_paksha: int  # 1–15
    tithi_name: str = ""
    shoonya_tithis: list[int] = Field(default_factory=list)  # void tithis (1–15) this masa
    is_shoonya: bool = False
    # rashi(s) held void for this tithi + which bodies (Lagna / grahas) sit in one today
    shoonya_rashis: list[DayShoonyaRashi] = Field(default_factory=list)
    bodies_in_shoonya: list[DayBodyInShoonya] = Field(default_factory=list)


class DayShadbala(BaseModel):
    graha: str
    sthana_bala: float
    dig_bala: float
    kala_bala: float
    cheshta_bala: float
    naisargika_bala: float
    drik_bala: float
    total_virupa: float
    total_rupa: float
    required_rupa: float
    strength_ratio: float
    rank: int
    ishta_phala: float
    kashta_phala: float
    graha_yuddha: bool


class DayAstro(BaseModel):
    day: DayChartScalars | None = None
    positions: list[DayPlanet] = Field(default_factory=list)
    shadbala: list[DayShadbala] = Field(default_factory=list)
    house_frames: list[DayHouseFrame] = Field(default_factory=list)  # from lagna / Moon / Sun
    prev_date: str | None = None  # previous weekday the `changed_*` flags compare to
    # Moon-anchored dasha timeline, one entry per session-length basis (390, 400)
    moon_dasha: list[MoonDasha] = Field(default_factory=list)
    kp_chains: DayKpChains | None = None  # KP lord chain for the Lagna and the Moon
    badhaka: list[DayBadhaka] = Field(default_factory=list)  # from Lagna / Moon / Moon-nak-lord
    tithi_shoonya: DayTithiShoonya | None = None  # Masa Shunya Tithi check


class DayDetailResponse(BaseModel):
    date: str
    underlying: str
    market: DayMarket
    astro: DayAstro


# -- Vimshottari dasha (docs/13 §5.6) --------------------------------------


class DashaCell(BaseModel):
    lord: str
    abbr: str
    years: float
    years_label: str  # e.g. "1y 2m"
    minutes: float | None = None
    hms: str | None = None  # e.g. "0:03:48"


class DashaRow(BaseModel):
    lord: str
    abbr: str
    years: float
    years_label: str
    minutes: float | None = None
    hms: str | None = None
    antardashas: list[DashaCell] = Field(default_factory=list)  # fixed lord order (grid)
    antardasha_sequence: list[str] = Field(default_factory=list)  # chronological (from the MD lord)


class DashaResponse(BaseModel):
    total_years: int  # 120
    total_minutes: float | None = None
    total_hms: str | None = None
    start_lord: str
    order: list[str]  # mahadasha sequence from start_lord
    abbr: dict[str, str]
    years: dict[str, int]
    rows: list[DashaRow] = Field(default_factory=list)


# -- Moon-anchored dasha (balance-of-dasha compressed onto a session) ------


class MoonDashaPeriod(BaseModel):
    lord: str
    abbr: str
    level: int  # 1 mahadasha · 2 antardasha · 3 pratyantar
    start_min: float  # minutes from session open
    end_min: float
    minutes: float
    hms: str  # e.g. "0:08:08"
    start_clock: str  # "HH:MM" IST, session-open-anchored
    end_clock: str
    years: float  # same ratio, expressed in Vimshottari years
    years_label: str
    partial: bool  # entered or left mid-stream (balance / session edge)
    children: list[MoonDashaPeriod] = Field(default_factory=list)


class KpChain(BaseModel):
    """The KP lord chain for one sidereal longitude — each level cuts the one
    above by the Vimshottari proportions (docs/13 §5.6.1)."""

    sign_lord: str
    sign_lord_abbr: str
    star_lord: str  # = the nakshatra lord (for the Moon, also the running mahadasha)
    star_lord_abbr: str
    sub_lord: str
    sub_lord_abbr: str
    sub_sub_lord: str
    sub_sub_lord_abbr: str


class DayKpChains(BaseModel):
    """KP chains for the day's two reference points."""

    lagna: KpChain | None = None
    moon: KpChain | None = None


class KpTimelinePoint(KpChain):
    longitude: float  # sidereal, this instant
    star_sub_relation: str  # friend | neutral | enemy — sub lord to star lord


class LagnaHouses(BaseModel):
    """Whole-sign house from the Lagna (ascendant = 1) of the Lagna chain's
    sign / star / sub lord grahas — e.g. 11 / 9 / 10."""

    sign: int | None = None
    star: int | None = None
    sub: int | None = None


class KpBracketMarket(BaseModel):
    open: float
    close: float
    change: float  # close − open, over the bracket
    change_pct: float | None = None


class KpTimelineRow(BaseModel):
    start: str  # "HH:MM" IST — first minute of this bracket
    end: str  # "HH:MM" IST — first minute of the next bracket (or the session end)
    lagna: KpTimelinePoint
    moon: KpTimelinePoint
    lagna_houses: LagnaHouses  # sign / star / sub lord's house from the Lagna
    market: KpBracketMarket | None = None  # bracket open→close move, when M1 bars exist


class KpTimelineResponse(BaseModel):
    date: str
    end: str  # "HH:MM" IST — session end
    level: str  # "sub" | "sub_sub" — the lord level brackets are cut on
    rows: list[KpTimelineRow] = Field(default_factory=list)  # KP-chain change brackets


class MoonDasha(BaseModel):
    calculation_method: str  # "MOON_BASED"
    subdivision_minutes: float  # 390 | 400 | configured — replaces the 120 years
    cycle_years: int  # 120
    levels: int
    session_open: str  # "09:15"
    moon_longitude: float  # sidereal, degrees
    nakshatra: str
    nakshatra_index: int
    pada: int
    position_in_nakshatra_deg: float  # 0–13.333
    elapsed_fraction: float  # of the nakshatra the Moon has crossed
    remaining_fraction: float
    dasha_lord: str  # the Moon's nakshatra lord — the running mahadasha
    dasha_lord_abbr: str
    balance_minutes: float  # un-elapsed part of the ruling mahadasha
    balance_hms: str
    balance_years: float
    balance_years_label: str
    order: list[str]  # mahadasha sequence from the Moon's lord
    abbr: dict[str, str]
    years: dict[str, int]
    kp_chain: KpChain | None = None  # sign → star → sub → sub-sub for the Moon
    periods: list[MoonDashaPeriod] = Field(default_factory=list)


class MoonDashaResponse(MoonDasha):
    date: str
    underlying: str


MoonDashaPeriod.model_rebuild()
DayAstro.model_rebuild()  # resolves the forward ref to MoonDasha (defined after it)
