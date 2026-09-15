# 13 — Astro Cross-Check (sidereal positions + Shadbala)

**Status:** built 2026-08-30 (owner-authorised). Optional side module. Does **not**
touch `analytical_core`, the deterministic engine, scoring, or the run model.

**Purpose.** Produce a reproducible, local, offline dataset of Vedic (sidereal,
Lahiri) planetary state — one snapshot per weekday — so planetary position and
strength can be joined to market data by calendar date for an *astro × market*
study. This is exploratory research tooling, not part of V1 decision-support
output.

---

## 1. Scope

| | |
|---|---|
| Bodies | Sun, Moon, Mars, Mercury, Jupiter, Venus, Saturn, **Rahu** (mean node), **Ketu** (Rahu + 180°) |
| Zodiac | **Sidereal**, **Lahiri** ayanamsha (`swe.SIDM_LAHIRI` — Indian Calendar Reform Committee / Chitrapaksha) |
| Frame | **Geocentric**, apparent ecliptic longitude of date |
| Instant | **09:00 IST** (`astro_hour_ist`), every **Mon–Fri** (Sat/Sun excluded; NSE trading holidays are *not* excluded) |
| Range | **2000-01-01 → today** (`astro_start_date`); Swiss Ephemeris covers 1800–2399 from the bundled files |
| Location | **19.076090 N, 72.877426 E** (Mumbai) — `astro_latitude` / `astro_longitude` |
| Strength | Classical **Parashari Shadbala** (six balas) for the seven planets; Rahu/Ketu carry no Shadbala |

Location does **not** affect geocentric planetary longitudes; it is used for the
ascendant, sunrise/sunset and the place-dependent Kāla balas, and is stored for
provenance.

## 2. Positions — method

- Engine: **Swiss Ephemeris** via `pysweph` (`import swisseph`), the maintained
  fork of `pyswisseph` — same API, ships a Python 3.13 wheel. **AGPL-3.0**
  (acceptable for internal, non-distributed use; revisit if Analytical is ever
  shipped or hosted for third parties).
- Data files `sepl_18.se1` + `semo_18.se1` (1800–2399 CE) are **bundled** under
  `backend/app/astro/ephe/` → calculation is fully offline and deterministic. No
  Moshier fallback.
- `swe.calc_ut(jd, body, FLG_SWIEPH | FLG_SIDEREAL | FLG_SPEED)`.
- Rahu = `MEAN_NODE`. Ketu = Rahu longitude + 180°, latitude negated. Mean node
  is always retrograde.
- Retrograde = longitudinal speed < 0 (always true for Rahu/Ketu).
- **Rashi** = ⌊lon / 30°⌋. **Degree** = lon mod 30°. **Nakshatra** = ⌊lon / 13°20′⌋.
  **Pada** = ⌊(lon mod 13°20′) / 3°20′⌋ + 1. **Nakshatra lord** = Vimshottari order.
- **Dignity** (D1): exalted / debilitated (within 1° of the deep point),
  moolatrikona, own, else friend / neutral / enemy by natural relationship to the
  sign lord.

## 3. Vargas

`app/astro/vedic.py` computes the classical Parashari divisional sign for the
Saptavarga set — **D1, D2 (Hora), D3 (Drekkana), D7 (Saptamsha), D9 (Navamsha),
D12 (Dwadashamsha), D30 (Trimshamsha)** — used by Shadbala's Saptavargaja
component.

## 4. Shadbala — method and documented choices

Classical six-fold strength (BPHS / B.V. Raman *Graha and Bhava Balas*), in
**virupas** (60 virupa = 1 rupa):

| Bala | Components |
|---|---|
| **Sthāna** | Uccha, Saptavargaja, Oja-Yugma (rasi + navamsha), Kendradi, Drekkana |
| **Dig** | distance of the planet from its powerless bhava cusp / 3 |
| **Kāla** | Nathonnatha, Paksha, Tribhaga, Varsha (15) / Masa (30) / Vara (45) / Hora (60) lords, Ayana, Yuddha |
| **Cheshta** | seeghra-kendra / 3 for Mars–Saturn; Sun ← its Ayana bala; Moon ← its Paksha bala |
| **Naisargika** | fixed ladder 60 · n/7 (Sun 60 … Saturn 8.57) |
| **Drik** | (Σ benefic graha-drishti − Σ malefic graha-drishti) / 4 |

`total_virupa` = Σ of the six; `total_rupa` = /60; `strength_ratio` =
`total_rupa` / required (Sun 5, Moon 6, Mars 5, Mercury 7, Jupiter 6.5, Venus 5.5,
Saturn 5). `ishta_phala` = √(uccha · cheshta); `kashta_phala` = √((60−uccha)·(60−cheshta)).
`rank` 1–7 by `total_virupa` (1 = strongest).

**Documented method choices / simplifications:**

1. Saptavargaja uses the **compound** (natural + temporal) relationship; the
   temporal part is taken from D1 sign positions.
2. Houses for Kendradi and graha-drishti counting are **whole-sign** from the
   lagna rasi. Dig Bala uses **equal-house** cusps from the exact ascendant.
3. Nathonnatha uses **local mean solar time** (equation-of-time omitted;
   ≤ ~1.3 virupa effect).
4. Drik Bala uses the **discrete** Parashari graha-drishti fractions
   (¼, ½, ¾, full) with the planet-specific full aspects (Mars 4/8, Jupiter 5/9,
   Saturn 3/10, all 7th), **not** the continuous Sphuta-drishti curve.
5. Benefic Paksha Bala is **doubled** (per BPHS). Mercury is treated as benefic.
6. **Graha-yuddha** (planetary war, sub-1° conjunction) is **flagged only**
   (`graha_yuddha`); no bala correction is applied — the classical formula is not
   standardised and it bites rarely at a 09:00 snapshot.

These choices are deterministic and reproducible but **will differ in detail from
Jagannatha Hora / Parashara's Light**, which themselves disagree on Tribhaga,
Ayana/Paksha doubling and the drishti curve. Treat the totals as a *consistent
internal strength index*, not as canonical BPHS values.

## 5. Storage & generation

Three side tables, no FK into the market schema, joined to market data by
`as_of_date`:

- **`astro_positions`** (migration `0002`) — one row per `(as_of_date, body)`:
  longitude, latitude, speed, retrograde, rashi (+index), degree, nakshatra
  (+index), pada, nakshatra_lord, dignity, ayanamsha, source. `as_of_ts` = the
  03:30 UTC instant.
- **`astro_shadbala`** (migration `0002`) — one row per `(as_of_date, graha)`:
  the six balas, total virupa/rupa, required, ratio, rank, ishta/kashta,
  `graha_yuddha`, and a `components` JSONB with the full flat virupa breakdown.
- **`astro_days`** (migration `0003`) — one row per date (denormalised scalars
  for the study): `day_name` / `weekday_lord`, **lagna** (ascendant) longitude +
  rashi/nakshatra/pada, Moon rashi/nakshatra/pada/lord, Sun rashi, **tithi** +
  **paksha**, sunrise/sunset, ayanamsha.

Generation (`app/astro/backfill.py`, CLI `analytical-astro`):

```
analytical-astro build                       # 2000-01-01 -> today, weekdays; positions + Shadbala + days
analytical-astro build --start 2023-08-30 --no-shadbala
analytical-astro build --days-only           # (re)build astro_days only
analytical-astro build --resume              # continue after the last stored date
analytical-astro show 2024-01-01             # positions + Shadbala for one date
analytical-astro study --json study.json     # astro x NIFTY-daily descriptive stats
```

Idempotent per key — re-running refreshes. Full 2000→2026 run ≈ 6,955 weekdays
→ ~62.6k position rows + ~48.7k Shadbala rows + ~7.0k day rows, a few minutes,
fully offline.

### 5.4 Daily catch-up (worker)

`analytical-worker serve` keeps the dataset current on its own so the "today"
row is always present without a manual `build`. `app/astro/daily.run_catch_up`
fills every missing weekday from `max(astro_positions.as_of_date)` to today
(IST); `app/worker/scheduler` runs it **once on start** and then on a slow timer
(`astro_catchup_interval_seconds`, default 6 h). It is a separate APScheduler job
(`analytical-astro-catchup`) — offline, deterministic, idempotent, and fully
isolated from the deterministic engine cycle; a failure is logged and never
touches a run. Disable with `astro_daily_catchup=false` (then manage the dataset
only via the CLI). This supersedes the "manual scheduled `--resume`" note in §7.

### 5.1 The astro × market study (`app/astro/study.py`)

`run_study(session, underlying="NIFTY-INDEX", start=None, end=None)` inner-joins
NIFTY D1 candles to `astro_days` and reports, per bucket, **descriptive
statistics of the same-day close-to-close return** (%): count, mean, median,
population std, % up-days, mean intraday range, cumulative (simple sum), best,
worst. Buckets: weekday, weekday lord, Moon nakshatra, Moon nakshatra lord,
lagna rashi, Moon rashi, tithi, paksha — each against an "all days" baseline.

**This is exploratory description, not prediction.** It reports what the sample
did; it makes no forecast and emits no trading instruction (decision 15). With
~6.6k days and 27 nakshatra / 12 rashi buckets (~250 / ~550 days each), bucket
means are noisy — differences of a few basis points are not significant. Treat
it as a data-exploration surface, not a signal.

### 5.2 The day log (`app/astro/daylog.py`)

`run_daylog(session, underlying="NIFTY-INDEX", start=None, end=None,
filters=None, sort="-ret", limit=50, offset=0)` returns the **individual days**
behind the buckets, not the aggregate. Same `astro_days ⋈ ohlcv_bars` join; one
row per trading day carrying the date, that day's `ret_pct` (close-to-close),
`range_pct` (high-low vs prior close, intraday only), `gap_pct` (open vs prior
close — the overnight move, added 2026-09-05 to sort/spot big gap-up and
gap-down days against the day's astro conditions), and its 09:00 IST chart
scalars (weekday + lord, tithi + paksha, Moon nakshatra + lord + rashi + pada,
lagna rashi, Sun rashi).

- **Filters** (exact, case-insensitive, all optional): `weekday` (int 0–4 or a
  day name), `weekday_lord`, `month` (1–12, the calendar month), `day` (1–31,
  day of month — pair with `month` for "8 September, every year", ~20 rows over
  the 2000→now dataset), `tithi` (1–30), `paksha`, `moon_nakshatra`,
  `moon_nakshatra_lord`, `moon_rashi`, `moon_pada` (1–4), `lagna_rashi`,
  `sun_rashi`. Passing several together (e.g. August + Wednesday + Rohini, or
  `month=9&day=8`) is how a specific combination is turned into a
  market-performance report. Same `day` filter on `/astro/almanac`.
- **`summary`** — one `study.Bucket` computed over the **entire filtered set**
  (before pagination): `n, mean_ret, median_ret, std_ret, pct_up, mean_range,
  best, worst`. When no day matches, `summary` is zeroed (`n=0`) and `first` /
  `last` are `null` — an empty combination is a valid answer, not an error.
- **`sort`** — `d` / `ret` / `range` / `gap` / `close` / `tithi` / `pada`, `-`
  prefix for descending; default `-ret` (biggest up-days first). `-gap` /
  `gap` surfaces the biggest gap-up / gap-down days first — the way to line up
  a big overnight move against that day's nakshatra, tithi, weekday, etc.
  Applied in Python over the filtered rows, then `offset` / `limit` slice the
  page.

Exposed as `GET /astro/days` (docs/07 §4.9); the frontend Astro page has a
"Day log" view with a filter bar, the `summary` strip, and a paged sortable
table, plus click-through from every Patterns bucket.

### 5.3 The single-day drill-down (`daylog.day_detail`)

`day_detail(session, underlying="NIFTY-INDEX", d=<date>)` gathers one date onto
one screen:

- **market.d1** — that date's D1 bar (`open/high/low/close/volume`, `prev_close`,
  `ret_pct`, `range_pct`), or `null` on a non-trading date.
- **market.hourly** / **market.m15** / **market.m5** — the session's `H1`,
  `M15` and `M5` bars (`ts` bar-open, OHLC, volume), ordered; all aggregated
  from M1, empty before the Jan 2022 M1 floor or for a pre-aggregation gap. The
  day screen's intraday panel switches between them with a **1 hour / 15 min /
  5 min** dropdown. **Extended 2026-09-15 (owner):** the bar table gained
  **`MD` / `AD` / `PD`** columns — the mahadasha / antardasha / pratyantar
  dasha lord running at each bar's own clock time (the frontend looks it up
  client-side from the same `astro.moon_dasha` period tree the session-dasha
  plot draws, by minutes-from-open; no new API field). `frontend/.../astro/AstroDay.tsx`
  `dashaAt()`.
- **astro.day** — the `astro_days` scalars (panchang: weekday + lord, tithi +
  paksha, Moon rashi/nakshatra/pada/lord, lagna rashi/nakshatra/pada, Sun rashi,
  sunrise/sunset, ayanamsha).
- **astro.positions** — the **Lagna** (ascendant) as a synthetic first row
  (`body: "Lagna"`, derived from `astro_days.lagna_longitude` — `retrograde
  false`, `speed_longitude null`) then the nine `astro_positions` rows ordered
  Sun→Ketu (longitude, degree-in-sign, rashi, nakshatra + pada + lord,
  retrograde, speed, dignity). Each also carries the **whole-sign** house it
  holds from **three reference points** — `house_from_lagna` / `house_from_moon`
  / `house_from_sun`, `((rashi_index − reference_rashi_index) mod 12) + 1` — and
  the matching **purushartha trikona** for each: `house_group_lagna` /
  `house_group_moon` / `house_group_sun` ∈ `Dharma` (1·5·9), `Artha` (2·6·10),
  `Kama` (3·7·11), `Moksha` (4·8·12); the group index is just `(house − 1) mod
  4`. The lagna is the classical frame; Moon = Chandra lagna, Sun = Surya lagna.
  Plus `house_from_lagna_deg` / `house_group_lagna_deg` — the **equal house
  anchored on the exact ascendant degree** (Sripati-style):
  `floor(((longitude − day.lagna_longitude) mod 360) / 30) + 1`, so house 1 runs
  from the lagna point for 30°, and a graha a few degrees *before* the lagna
  degree sits in the 12th even when it shares the lagna's sign.
  Plus `house_from_naklord_deg` / `house_group_naklord_deg` (owner-authorised
  2026-09-05) — the same equal-house math anchored on the **exact degree of
  the Moon's current nakshatra-lord** instead of the ascendant: whichever
  graha rules the nakshatra the Moon occupies that day (e.g. Ashlesha/Ayilyam
  → Mercury, Ardra → Rahu, Moola → Ketu — `vedic.NAKSHATRA_LORDS`), looked up
  by name among that day's `astro_positions`; `null` if that lord's own
  longitude isn't resolvable. The reference graha itself changes day to day
  as the Moon moves nakshatra to nakshatra — it is not a fixed point like the
  lagna.
  Each graha also carries a **day-over-day diff** against `astro.prev_date` (the
  previous weekday): `changed_rashi` / `changed_nakshatra` / `changed_pada` /
  `changed_retrograde` (bool) plus the `prev_*` values — so the day screen can
  highlight what shifted since yesterday (a sign / house change, a new
  nakshatra or pada, a retrograde station). All `false` / `null` for the first
  stored row.
- **astro.house_frames** — one entry per frame (`lagna`, `lagna_deg`,
  `naklord_deg`, `moon`, `sun`) `{frame, reference, groups}` where `groups` is
  the four trikonas rolled up `{group, houses, bodies}`. `bodies` lists every
  graha whose house (whole-sign for `lagna`/`moon`/`sun`, degree-based for
  `lagna_deg`/`naklord_deg`) from that reference lands in the trikona; the
  `lagna*` frames also inject a synthetic `"Lagna"` in house 1 (`Dharma`).
  `naklord_deg`'s `reference` is the fixed label `"Moon's nakshatra-lord (by
  degree)"` — the day scalar `moon_nakshatra_lord` names which graha it
  actually is that day; the frame is omitted entirely if that lord's longitude
  isn't resolvable. A compact "where does everything sit relative to the
  lagna / Moon / Sun / Moon's nakshatra-lord" view.
- **astro.shadbala** — the seven `astro_shadbala` rows, ordered by `rank` (the
  six balas in virupas, `total_rupa`, `required_rupa`, `strength_ratio`,
  `ishta`/`kashta`).
- **astro.kp_chains** (added 2026-09-06) — `{ lagna, moon }`, each the
  `dasha.kp_chain` (§5.6.1) `sign → star → sub → sub-sub` for that point's
  longitude (or `null` if the longitude is missing). The Moon's chain also
  rides each `astro.moon_dasha[i].kp_chain`; this pairs it with the Lagna's.
  Frontend: a "KP lords — Lagna & Moon" panel below the Panchang.
- **astro.badhaka** (added 2026-09-08) — the **Baadhagaadhipathi**: one entry
  per reference (`lagna`, `moon`, `naklord` = the Moon's current
  nakshatra-lord), `{frame, reference, reference_sign, movability
  (MOVABLE/FIXED/DUAL), badhaka_house (11/9/7), badhaka_sign, badhaka_lord,
  badhaka_lord_house_from_ref}`. Rule: movable reference sign → 11th house is
  badhaka, fixed → 9th, dual → 7th; the lord of that house's sign is the
  Baadhagaadhipathi. `naklord` collapses onto the Moon frame on days the Moon
  is in one of its own nakshatras. Pure `vedic.badhaka_from`.
- **astro.tithi_shoonya** (added 2026-09-08, extended 2026-09-09) —
  `{chandra_masa, chandra_masa_approx (always true), paksha, tithi (1–30),
  tithi_in_paksha (1–15), tithi_name, shoonya_tithis, is_shoonya,
  shoonya_rashis: [{index, name}], bodies_in_shoonya: [{body, rashi}]}`. Two
  distinct classical checks:
  - **Tithi Shoonya Rashi** — `TITHI_SHOONYA_RASHIS_BY_TITHI` maps each
    tithi-in-paksha (1–15, both pakshas) to the sign(s) held *void* for it
    (owner-supplied table 2026-09-09: Pratipada/Dwadashi → Tula, Makara;
    Chaturdashi → Mithuna, Kanya, Dhanu, Meena; …). `shoonya_rashis` is today's
    set; **`bodies_in_shoonya`** is which of the Lagna / grahas actually sit in
    one today (from `positions`) — the actionable read (that body is blunted).
    Overridable. Tritiya/Trayodashi default to Scorpio+Leo (varies by text).
  - **Masa Shunya Tithi** — `is_shoonya` / `shoonya_tithis` from
    `SHOONYA_TITHIS_BY_MASA` (the Muhurta-shloka list, one/two tithis per amanta
    masa). `chandra_masa` is the **amanta** month, named after the sidereal sign
    the Sun held at the new moon that began it, back-estimated from the current
    Sun–Moon elongation (`vedic.days_since_new_moon`) — a month boundary within
    ~a day of a sankranti can be off, adhika months not split (`chandra_masa_approx`).
    `day.chandra_masa` mirrors it. Needs one cached Swiss-Ephemeris Sun position.
  Pure `vedic.{tithi_shoonya_rashis,is_shoonya_tithi,tithi_name}`. Frontend: the
  "Badhaka & Tithi Shoonyam" panel below the Panchang lists the shoonya rashis,
  the bodies caught in one (rose), and the masa-void-tithi verdict. Descriptive
  — not a forecast.

Returns `None` (→ `404`) only when the date has neither a D1 bar nor an
`astro_days` row. Exposed as `GET /astro/days/{d}` (docs/07 §4.9); the frontend
route `/astro/day/:date` renders it as stacked panels, reached by clicking any
date in the Day log **or the Almanac**. For a **future / untraded** date the
market panels are empty and the panchang / positions / Shadbala panels render
normally — the sky is deterministic, so the drill-down works for any date the
dataset covers (`analytical-astro build --end <future>` extends it; §5).

### 5.5 The almanac (`daylog.run_almanac`)

`run_almanac(session, underlying, start=None, end=None, filters, sort, limit,
offset)` lists **every `astro_days` row** — `astro_days` **left**-joined to D1,
so days the market has not traded (future dates, holidays) are included. `start`
defaults to today (IST) so the natural view is "the sky for the days ahead".
Each item carries the panchang scalars plus `has_candle` and, when true,
`close` / `ret_pct` / `range_pct`. Same text filters as the day log (weekday,
month, tithi, paksha, Moon nakshatra / rashi, lagna, Sun rashi); `sort` ∈ `d`
(default) / `tithi` / `pada`. Exposed as `GET /astro/almanac` (docs/07 §4.9);
the frontend **Almanac** tab renders it as a paged table whose dates open the
drill-down.

### 5.6 Vimshottari dasha grid (`app/astro/dasha.py`)

Pure arithmetic, no DB, no ephemeris — a small deterministic helper, separate
from the study/day-log/almanac reads. The nine lords rule in the fixed
Vimshottari proportion **Ketu 7 · Venus 20 · Sun 6 · Moon 10 · Mars 7 ·
Rahu 18 · Jupiter 16 · Saturn 19 · Mercury 17 = 120 years**. An antardasha
(sub-period) of lord *b* inside the mahadasha of lord *a* lasts
`years[a] · years[b] / 120`.

`vimshottari_grid(total_minutes=390.0, *, start_lord="Ketu") -> dict` returns
the full 9×9 mahadasha × antardasha table. `total_minutes` linearly scales the
120-year cycle onto a session window (the NSE cash session is ≈ 390 min), so
every cell is reported **both** as years (`years`, `years_label` e.g.
`"1y 2m"`) and, when `total_minutes` is given, as `H:MM:SS` of that session
(`minutes`, `hms`). `total_minutes=None` ⇒ years only. `start_lord` rotates the
mahadasha sequence (pass the Moon's nakshatra lord to anchor a real chart);
unknown lord ⇒ `ValueError`. Antardasha **columns** are always the fixed lord
order for grid alignment with a printed panchang; `row.antardasha_sequence`
gives the chronological order within a period (which begins with the period
lord).

Exposed as `GET /astro/dasha?minutes=&start_lord=` (docs/07 §4.9); the frontend
**Dasha** tab renders the grid with a session-length input and a start-lord
selector, each cell showing the scaled time over its year value.

#### 5.6.1 Moon-anchored dasha (`moon_dasha`, `moon_dasha_head`)

The grid above uses an *arbitrary* start lord. The Moon-anchored variant is the
**standard balance-of-dasha calculation** driven off a real day's sky:

```
Moon sidereal longitude (09:00 IST, from astro_positions)
  → nakshatra  = floor(lon / 13°20')                     (27, Ashwini→Ketu)
  → lord       = VIM_ORDER[nakshatra % 9]                 (the running mahadasha)
  → elapsed_fraction = (lon mod 13°20') / 13°20'          (exact, not the pada)
  → md_full    = cycle_minutes · years[lord] / 120
  → balance    = md_full · (1 − elapsed_fraction)         (un-elapsed part)
```

`cycle_minutes` **replaces the 120 years** — 390 or 400, passed explicitly,
never silently defaulted; this is the only non-standard element and it is a
linear rescale, not a different rule. `moon_dasha(moon_longitude, *,
cycle_minutes=390.0, levels=2, session_open="09:15")` returns the headline
scalars plus a `periods` tree that **tiles `[0, cycle_minutes)`**: the first
mahadasha is the `balance` (so `partial=true`), full mahadashas follow in
`VIM_ORDER`, wrapping past the ninth back into the Moon's lord for the leftover
(the elapsed part — it fell before the session opened). `levels` 1/2/3 =
mahadasha / +antardasha / +pratyantar; each level subdivides its parent by the
same `years[x]/120` ratio, and the *first* sub-period of the balance mahadasha
also starts mid-sequence (nested balance — again off the exact Moon position,
not the pada). Every node carries `minutes`/`hms`, `years`/`years_label`, and a
`start_clock`/`end_clock` (`"HH:MM"` IST) anchored on `session_open` — a pure
label shift (`"09:00"` vs `"09:15"` etc.), it does **not** change the sky (always
the 09:00 IST snapshot) or any duration. `moon_dasha_head` is the cheap path —
just the mahadasha + antardasha lords and balances running at session open, for
the day-log column.

The response also carries `kp_chain` (added 2026-09-05) — the **KP lord chain**
for the Moon's exact longitude: `sign_lord → star_lord → sub_lord →
sub_sub_lord` (each with an `_abbr`). `dasha.kp_chain(longitude)` is pure: sign
lord from `RASHI_LORDS`, star lord = the nakshatra lord (= the running
mahadasha), then `_sub_of` walks `VIM_ORDER` from the parent lord cutting the
span into the nine `years[x]/120` proportions — once inside the nakshatra for
the sub, once inside the sub for the sub-sub. Standard KP subdivision, no new
constant.

**Session KP timeline** (`app/astro/kp_timeline.py`, added 2026-09-06).
`kp_session_timeline(engine, *, d, lat, lon, end="15:40", level="sub")` samples
the sky **minute by minute, 09:00 IST → `end`**, computing `kp_chain` for the
**Lagna** (`engine.ascendant`, ~1°/4min so its sub / sub-sub lord turn over
through the session) and the **Moon** (`engine.position`, near-static), and
emits one **change bracket** (`start`/`end` `HH:MM`) per stretch during which
neither chain's lord changes at `level` — `"sub"` (the KP-decisive sub lord,
default; ~60 brackets/session) or `"sub_sub"` (every sub-sub turn; ~350). Each
row carries both chains at the bracket start, `star_sub_relation` per chain
(the Parashari natural relation of the sub lord to the star lord —
`vedic.natural_relation`, `friend`/`neutral`/`enemy`; Rahu/Ketu neutral with
all), and `lagna_houses` — the **whole-sign house from the Lagna** (ascendant =
house 1) of the Lagna chain's `sign` / `star` / `sub` lord grahas, e.g.
`11-9-10` (graha rashis off one 09:00 snapshot; the Lagna rashi is the
bracket-start instant, so these numbers step when the Lagna crosses a sign
~2-3× a session). When the endpoint also
loads that date's **M1 bars** for `underlying` (`NIFTY-INDEX` by default), each
bracket gets a `market` — the index's **open→close** move over the bracket
(`open`, `close`, `change`, `change_pct`), `null` where no bar falls in the
window. Sky computed live from the ephemeris, **nothing stored**. `GET
/astro/days/{d}/kp-timeline?end=HH:MM&level=&underlying=` (`422` on `end ≤
09:00`, a bad time, or a bad `level`). Frontend: the "KP lords — Lagna & Moon"
panel — a scrollable bracket table with a `09:00 → 15:30 / 15:40` dropdown, a
`sub-lord / sub-sub` toggle, per-level 〃 de-duplication, a `houses
(sign·star·sub)` column, `mkt O→C` + `price`, and a collapsible
session-H1-bars table.

Exposed as `GET /astro/dasha/moon?d=&minutes=&levels=&session_open=` (docs/07
§4.9, `404` when no `astro_positions` Moon row for the date, `422` on a bad
`session_open`). The day drill-down (§5.3) embeds a default view under
`astro.moon_dasha` (one entry per basis, 390 and 400, `levels=3`, `09:15`);
the day log (§5.2) carries `dasha_lord` / `dasha_sub_lord` / `dasha_balance_hms`
(390-min basis, at open). Frontend: a "Dasha — Moon-anchored" panel on the day
screen with an **open-time picker (`09:00` / `09:15`) and a session-length
picker (`390` / `400`)** that refetch the endpoint, plus the MD/AD/PD depth
toggle, per-row expand/collapse triangles, and a **"show until" dropdown
(`15:30` / `15:40` / full, default `15:40`)** that hides periods starting at or
after the chosen wall-clock time (view-only, no refetch); and a `dasha @open`
column in the Day-log table. Below the period table it renders the `kp_chain`
as a `sign → star → sub → sub-sub` strip. The panel also shows, for each
period's lord, its **house from the lagna** in both conventions — by exact
degree (equal 30° houses on the ascendant point) and whole-sign — read straight
off that graha's `house_from_lagna_deg` / `house_from_lagna` in the same
response (§5.3), no extra computation.

**Session price path (`SessionDashaPlot`, frontend).** The one chart in V1
(decision 11 narrowed, owner 2026-09-03; line, not candles, extended same day):
a deliberately rough hand-drawn inline SVG — no charting library — on the astro
day screen's intraday panel. It draws the session's **open-price line** (of the
`H1`, `M15` or `M5` bars, whichever the panel's timeframe dropdown selects) on a
`session-minutes-from-09:15` x-axis, with the `level ≥ 1` mahadasha periods as
bands behind it and repeated in a lane below — each mahadasha tagged
**`H<by-degree>/<whole-sign>`**, that lord's house from the lagna on the day
(e.g. a Moon mahadasha on 2026-09-02 reads `Ch H7/8`), plus an **approximate %
move** over the period's clock window (first bar open → last bar close within
it) — then thin antardasha (AD) and pratyantar (PD) lanes. A bottom **planet-places lane** shows the
09:00 IST sky as a 0–360° zodiac strip (12 rashi cells) with each graha — and
the Lagna — plotted at its sidereal longitude, retrograde in red, labels
staggered on collision; the **running mahadasha lord** is picked out in amber
with a dashed link to the Lagna tick labelled with its house from the lagna
(by degree / whole-sign). It is a single daily snapshot, not a session series.
Uses the 390-minute basis. Approximate by intent — H1 is hourly, ~6–7 points
span the session; it exists to read price *against* the dasha and the day's
graha placement, not for precision.

## 6. Cross-check procedure

Before using these numbers in any analysis:

1. **Positions** — spot-check ~10 scattered dates against JPL Horizons
   (subtract the stored `ayanamsha` to compare to tropical) or any Lahiri
   ephemeris. Sub-arcminute agreement is expected.
2. **Shadbala** — reproduce the same date/time/place in **Jagannatha Hora**
   desktop and compare the six balas and the total. Small component differences
   are expected (see §4); a large divergence is a bug.

## 7. Not in scope (yet)

- Bhava Bala, Ashtakavarga, Yogas.
- Dasha beyond pratyantar (§5.6.1 goes mahadasha → antardasha → pratyantar);
  calendar-date dasha (real years/months, not the session rescale); dasha
  wired into scoring.
- Any wiring into scoring. The astro×market join is done ad hoc against the two
  tables (read API: §5.1–5.3).

*(The "append today's snapshot" gap is now closed — see §5.4, the worker daily
catch-up.)*
