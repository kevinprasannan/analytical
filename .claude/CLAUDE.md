# CLAUDE.md — Working Agreement for the "Analytical" Repo

Guidance for future Claude Code sessions and human contributors. Read it first.
Keep it current.

---

## 1. What this project is

**Analytical** is a web-based **analytical decision-support system** for NSE
(Indian) index and derivatives markets. It ingests market data on an intraday
schedule, runs a deterministic analysis engine, normalises each analysis into a
factor score, and combines those into a composite score with a confidence value
and a deterministic explainable hint. Results are exposed through a REST API and
a table-based React UI.

**V1 has no charts** — one narrow exception (owner, 2026-09-03): a single rough
inline SVG on the astro day screen (see decision 11 / §3b). Everything else is
numeric and tabular.

**The scoring engine is not an execution system.** It never emits BUY / SELL /
entry / exit / target / stop. Its discrete outputs are analytical labels:
`STRONG_BEARISH, BEARISH, NEUTRAL, BULLISH, STRONG_BULLISH`. **One bounded
exception (owner, 2026-09-03):** the OI-based *option-strategy suggestions*
resource (`analytical_core.options.strategy`, `GET
/instruments/{id}/option-strategies`) returns illustrative option structures
with per-leg BUY/SELL + ratio, each payload carrying a "not advice / not an
order" disclaimer. It is isolated to that one module + endpoint + UI panel; see
decision 15 / §3b.

---

## 2. Current phase

**Core build complete against the stub provider; live Upstox + frontend build
unverified.** `provider-validation-gate` is CLEAR.

Done (each behind an explicit owner authorisation; see `docs/DEVELOPMENT.md` and
the auto-memory `phase-status.md` for detail):

- **Phase 0** spec (revised v2) and **Phase 1** foundations.
- **Phase 1.5** provider validation — PASSED; PV-3/4/5/6/7 `CONFIRMED`,
  PV-1/2/8 `ACCEPTED_FALLBACK`; branches PV-2 `AGGREGATE_FROM_M1`, PV-4
  `A_PER_CANDLE`.
- **Phase 2** — Upstox v3 auth + candle adapter (M1/D1), M1→M5/M15/H1
  aggregation, historical backfill, live INGEST in the cycle.
- **Phase 3** — deterministic engine: RSI, Bollinger, EMA(+ATR), Golden Cross,
  Volume, Open Interest; `ALGO_VERSION` + engine-output snapshot guard.
- **Order blocks** (`docs/05` §9a, owner-authorised 2026-09-07): pure
  `analytical_core.indicators.order_block` — last opposing candle before a
  close-confirmed **Break of Structure**, volatility-gated impulse, mitigation
  + ageing, `bias` / `zone_state` / zones. `PER_TIMEFRAME`, **INDEX + FUTURE**
  (`NOT_APPLICABLE` on OPTION); weight `1.00` in `weighted_v1`, added to
  `expected_analyses`. `ALGO_VERSION` 3.2.0→**3.3.0**, `SCORING_VERSION`
  1.0.0→**1.1.0**, snapshot regenerated. Analytical only — no BUY/SELL, no
  entry/target/stop. Migration `0006` widens `ck_analysis_results_analysis_key_known`
  — applied to the live DB via a constraint-only script (row count unchanged),
  alembic stamped `0006`.
- **Candlestick patterns** (`docs/05` §9b, owner-authorised 2026-09-07): pure
  `analytical_core.indicators.candles` — names the major 1/2/3-bar pattern
  (hammer / inverted hammer / hanging man / shooting star / engulfing / harami /
  piercing / dark-cloud / morning-&-evening star / doji / marubozu) on each of
  the last `scan_bars` finished bars, with `WEAK/MODERATE/STRONG` strength and
  trend context; `last_pattern` + `on_last_bar` drive the frontend panel
  highlight ("alert"). `PER_TIMEFRAME` (5m/15m/1h/1D — no M30, not an aggregated
  grid), **INDEX + FUTURE** (`NOT_APPLICABLE` on OPTION); weight `0.75` in
  `weighted_v1`, added to `expected_analyses`. `ALGO_VERSION` 3.3.0→**3.4.0**,
  `SCORING_VERSION` 1.1.0→**1.2.0**, snapshot regenerated. Descriptive labels
  only — no BUY/SELL, no entry/target/stop. Migration `0007` widens
  `ck_analysis_results_analysis_key_known` — applied to the live DB via a
  constraint-only script (row count unchanged), alembic stamped `0007`.
  - **Candles multi-timeframe read grid** (`docs/05` §9b.4 / `docs/07` §4.17,
    owner-authorised 2026-09-08): `GET /instruments/{id}/candles-grid` +
    `CandlesGridPanel` — the same pure `candles` scan run over **5m / 15m / 30m /
    1h** as parallel columns, last 5 hits each. M5/M15/H1 read stored bars; M30
    is folded on read from M5 (session-anchored) since there is no M30 in the
    engine grid (decision 4). Computed on read, **not persisted, not scored**,
    not in `expected_analyses`; `candles_grid_version` 0.1.0 (module-local).
    INDEX + FUTURE only. No version bump.
  - **Frozen-tape bug fix** (`docs/05` §9b.2a, owner-flagged 2026-09-11 —
    "candlestick patterns … its not perfectly deliver"): the NSE_INDEX
    intraday feed carries the same LTP forward as `O=H=L=C` for several M1
    bars near the close, then snaps to the real close in one step — this was
    being scored as a genuine `MARUBOZU`/`EVENING_STAR`. `candles()` now skips
    a candidate preceded by `≥ frozen_run_min_bars` (2) identical zero-range
    bars, and `_three_bar`'s "star" now requires a non-zero-range middle bar.
    Fixes **M5**; **M15/M30/H1 still show the artifact** — at those bucket
    widths the ~15 min freeze fits inside one bucket, invisible without M1
    context (a bigger fix touching the shared ingestion/orchestration
    pipeline — not done, flagged to the owner). `ALGO_VERSION`
    3.4.0→**3.4.1** (`SCORING_VERSION` unchanged), snapshot regenerated.
  - **Gravestone / dragonfly doji** (`docs/05` §9b.2, owner-authorised
    2026-09-12): the doji family is sub-classed by which wick is negligible —
    `GRAVESTONE_DOJI` (tiny body, negligible lower wick, long upper — bearish
    reversal, `STRONG` in an uptrend) / `DRAGONFLY_DOJI` (mirror, bullish) /
    plain `DOJI` when neither wick is negligible (was: every small-bodied bar
    reported as generic `DOJI`). New `CandlePattern` enum values (contract/API-
    only, no PG type — `docs/12`); `_score_candles` needed no change (generic
    on bias/strength). `ALGO_VERSION` 3.4.1→**3.5.0**, snapshot regenerated.
  - **Reversal-pattern alert widened** (`docs/08`, owner-authorised
    2026-09-15 — "recheck if reversal pattern need alert"): `CandlesGridPanel`
    now also tints a column when a `STRONG` reversal-type pattern (engulfing /
    harami / hammer / star family / piercing / dark-cloud / morning-evening
    star — not doji family or marubozu) appears **anywhere in the scanned
    window**, not only the just-closed bar. Pure frontend read of the existing
    `patterns[]` array — no API/schema/backend change.
- **CPR & pivots read view** (`docs/05` §10.13 / `docs/07` §4.18,
  owner-authorised 2026-09-08): pure `analytical_core.pivots` (`compute_pivots`
  = classic floor R1-3/S1-3 + CPR band TC/P/BC + `width_band` + `cpr_relation`)
  + `app.api.services.pivots_view` (folds D1 bars into daily / ISO-week /
  calendar-month periods, IST) + `GET /instruments/{id}/pivots` +
  `PivotsPanel` on instrument-detail. Per timeframe: `current` (last completed
  period), `developing` (in-progress), `history` (66 daily ≈ 3mo / 13 weekly /
  4 monthly). Proximity tiers reuse the §10.12 per-instrument point bands.
  **All instrument types.** Computed on read — **not persisted, not scored**, no
  version bump, no migration. `pivots_version` 0.1.0.
- **Phase 4** — Market Profile (TPO + Volume profile, POC, value area, IB,
  shape classifier).
  **Borrowed FUTURE volume for INDEX Volume Profile** (owner-authorised
  2026-09-17 — "FOR MARKET PROFILE ADD WITH FUTURE VOLUME", read layer only,
  no engine/migration/version change): an INDEX carries no genuine traded
  volume (a calculated value, never itself bought/sold — bars report
  `volume=0` even though the `has_volume` DB flag happens to default `true`
  on seeded rows), so `build_profile(..., VOLUME)` always returns `None` for
  it and the `VOLUME` tab was simply absent. `services.market_profile_view`
  now, when an INDEX session has no VOLUME row of its own, looks up the
  nearest linked FUTURE contract (`underlying_id` match, soonest
  `expiry_date >= session_date`) and folds in *that* contract's own
  already-persisted Volume Profile for the same `session_date` — no new
  computation, just a second `SELECT` against data the regular cycle already
  builds for the future. Response gains `volume_source`/
  `volume_source_contract_key` (`"FUTURE"` / e.g. `"NIFTY-FUT-2026-09"`,
  both `null` when VOLUME is the instrument's own) so this is disclosed, never
  silently presented as the index's native data. **Caught and fixed a bug
  before shipping**: the initial implementation filtered the DB query by the
  caller's `?profile_type=` *before* attempting the borrow, so requesting
  `?profile_type=VOLUME` on an index with no own volume returned empty and
  404'd before the borrow logic ever ran — fixed by fetching unfiltered,
  merging, then filtering last. `MarketProfilePanel.tsx` shows an amber
  `from <contract-key>` badge next to the TPO/VOLUME tab switcher when the
  active tab is a borrowed one. Backend 715 pass unchanged (service/router-
  layer change only, no new pure function); `vite build` clean. Live-verified
  on NIFTY: `GET /instruments/2/market-profile` now returns `profiles:
  [TPO, VOLUME]` with `volume_source: FUTURE` / `NIFTY-FUT-2026-09` (37
  volume bins), NIFTY-FUT's own `/market-profile` unaffected
  (`volume_source: null`), and both `?profile_type=TPO`/`?profile_type=VOLUME`
  filters confirmed still correct after the fix.
  **TPO/VOLUME tabs merged into one table same day** (owner — "VOLUME & tpo
  TWO COLUMN MERGE IT ONE WITH SMALL BAR"): `MarketProfilePanel.tsx` dropped
  the tab switcher entirely — the table now has one row per `price_low`
  (union of both profiles' bins, joined by price, since a borrowed-future
  volume profile can sit on a slightly different grid than the index's own
  TPO) with the classic Price/IB/period-letter/TPO-count columns immediately
  followed by a **Volume** column: a small CSS-width `<div>` bar scaled to
  the session's busiest price, plus the raw number — no chart library, no
  SVG, still table-only (decision 11). The "from `<contract>`" disclosure
  badge moved from "next to the tab switcher" to sitting above the table
  outright, since there's no longer a VOLUME-specific tab to gate it on.
  Frontend-only, no backend/schema change. `vite build` clean; screenshotted
  both NIFTY-INDEX (borrowed bars + badge) and NIFTY-FUT-2026-09 (native
  bars, no badge) — both render TPO letters and Volume bars together
  correctly, zero console errors on either.
- **Scoring** — `weighted_v1` → composite + confidence + labels + per-factor
  breakdown + `explanation`.
- **API** — instruments / analyses / scores / runs (async `POST /runs` +
  `Idempotency-Key`) / config / calendar / health / meta.
- **`app_settings` merge**, **scheduler loop** (`analytical-worker serve`),
  **run-completed hook**, **`/meta/versions`** completion, **Docker Compose**
  deploy, **frontend source** (`frontend/`, not yet built — needs Node).
- **Worker side jobs** (owner-authorised 2026-09-09, `docs/02` §3.7): on the
  same APScheduler — `analytical-universe-roll` (re-download the Upstox master +
  re-roll the tracked option universe against live spot every 6 h + on start, so
  strikes follow the money and new weeklies appear; `app.instruments.roll`,
  toggle `UNIVERSE_DAILY_ROLL`) and `analytical-db-backup` (nightly `pg_dump -Fc`
  → `DB_BACKUP_DIR` default `deploy/backups/`, keep newest 14; `app.ops.backup`,
  toggle `DB_BACKUP_ENABLED`; `pg_dump` auto-found on Windows). CLI:
  `analytical-instruments build-universe --refresh-master`, `python -m
  app.ops.backup`.
- **Phase S — S0/S1/S2** (streaming ingestion, lock lifted 2026-08-30): pure
  `analytical_core.streaming` M1-from-ticks builder, `StreamingMarketDataProvider`
  seam + `StubMarketFeed`, `app/ingestion/stream.py` `StreamIngestor`,
  `analytical-worker stream`. End-to-end on the stub feed; 483 tests pass.
- **Astro cross-check** (`docs/13`, owner-authorised 2026-08-30): `app/astro/`
  (Swiss Ephemeris via `pysweph`) + `astro_positions` / `astro_shadbala` side
  tables (migration `0002`) + `analytical-astro` CLI. Sidereal Lahiri positions
  + Parashari Shadbala, weekdays 2000→now at 09:00 IST / Mumbai, for joining to
  market data. Separate from the engine; not V1 decision-support output.
  Day-log / day-detail read API + views (`docs/13` §5.2/5.3). **Daily
  catch-up** (`docs/13` §5.4, owner-authorised 2026-09-01): the worker
  `analytical-astro-catchup` job keeps the dataset current to today. Day-detail
  also carries KP lord chains, whole-sign/degree house frames, Moon-anchored
  dasha, and (2026-09-08) **`astro.badhaka`** (Baadhagaadhipathi from Lagna /
  Moon / Moon-nakshatra-lord) + **`astro.tithi_shoonya`** (Masa Shunya Tithi —
  amanta `chandra_masa` back-estimated from Sun–Moon elongation, classical
  overridable per-masa void-tithi list). Pure `app/astro/vedic.py`; frontend
  "Badhaka & Tithi Shoonyam" panel. Read-only, descriptive.
- **Options: chain-only** (owner-authorised 2026-09-01). Tracked NIFTY /
  BANKNIFTY / SENSEX option contracts (ATM ± `strike_window`, next
  `max_expiries`) ingest M1 + OI only and, in ANALYZE, run **only**
  `open_interest` — every premium-series technical is `NOT_APPLICABLE` and
  `expected_analyses(OPTION) = {open_interest}` (`docs/04` §2.3/§4). Read views:
  **option chain** (IV/greeks/PCR/max-pain, `docs/05` §11.3) and **OI pulse**
  (trending OI: strike-ladder ΔOI + buildup, PCR/max-pain vs. open, OI walls,
  net bias, 5-min session time-series trace — `docs/05` §11.4, `docs/07` §4.11).
  Pure `analytical_core.options`; computed on read, not persisted.
  **Big OI movers** (owner-authorised 2026-09-10, `docs/05` §11.4 / `docs/07`
  §4.22): `GET /instruments/{id}/oi-movers` — the near-expiry option strikes that
  added / reduced the most session OI, two split lists, each row with session
  ΔOI + last-15-min ΔOI + buildup label + moneyness; a thin re-shape of the
  OI-pulse ladder (`services.oi_movers`). `/instruments/:id/oi-movers` screen.
  Options only, positioning labels only.
  **CE/PE split** (owner-authorised 2026-09-17 — "CE PE sepearte box"):
  `OiMovers.tsx` splits each Added/Reduced panel into side-by-side `Calls
  (CE)` / `Puts (PE)` boxes (`CePeBoxes`) instead of one mixed table; the two
  Added/Reduced panels stack full-width rather than sitting side by side so
  each CE/PE box keeps a full half-page width for its 8-column table.
  **LTP trace tab** (owner-authorised 2026-09-17 — "oI price build more one
  area hope fully they will sl some where will find liquidity can u give
  another tab with time ltp and nifty ltp"): new pure
  `analytical_core.options.build_ltp_trace` (reuses `oi_pulse`'s existing
  `_at_or_before` lookup) pairs one strike's session M1 premium ticks with
  the underlying's own LTP at/just-before the same instant — no indicator,
  no resampling, no positioning label, just the raw time/price/price triple
  a trader watches to see where a crowded strike's premium tracks or breaks
  from the underlying. `services.oi_mover_ltp_trace` resolves the option
  instrument for `(strike, option_type)` on the same near expiry as
  `oi-movers`/`oi-pulse`. `GET
  /instruments/{id}/oi-movers/ltp-trace?strike=&option_type=`. Frontend adds
  a `Movers` / `LTP trace` tab switcher to `OiMovers.tsx`; clicking a strike
  in the Movers tab jumps straight to its trace (`onSelect` on
  `MoversTable`), or it can be picked from a dropdown defaulting to today's
  top OI add. Backend **711 pass** (was 708); ruff/black clean. `vite build`
  clean. Live-verified on NIFTY: 385 per-minute ticks for the top add
  (23,300 PE), option LTP and NIFTY LTP correctly paired tick-for-tick,
  zero console errors on screenshot.
  **OI column added same day** (owner — "Strike LTP trace WITH oi NEEDED"):
  `build_ltp_trace` gained an `oi_series` param (`LtpTracePoint.oi`, same
  `_at_or_before` fallback as the underlying side); `oi_mover_ltp_trace`
  loads the resolved option instrument's `OpenInterest` rows the same way
  `oi_pulse` already does and threads them through. Table gained an **OI**
  column between time and LTP, colour-coded vs. the previous tick like the
  price columns. Backend **713 pass** (was 711). Live-verified: strike OI
  moved 67,85,155 → 75,71,460 across the trace, correctly aligned tick-for-
  tick with LTP/NIFTY LTP; zero console errors on screenshot.
  **OI Δ column added same day** (owner — "aDD oi CHANGE ALSO"):
  `LtpTracePoint.oi_change` = `oi` minus the passed-in `oi_series`'s own
  first sample (not a fresh session-open lookup — `oi_series` is already
  pre-filtered to `ts >= session_open` by the caller, same convention as
  `option_premium`/`spot_series`, so its first entry already *is* the
  session-open read). Table gained an **OI Δ** column between OI and LTP,
  signed + colour-coded, reusing the existing `sInt` helper. Backend
  **715 pass** (was 713); one black reformat on `oi_pulse.py`. `vite build`
  clean. Live-verified: `oi_change` reads `0` at the trace's first tick and
  `+35,54,915` by 15:39 IST for the 23,300 PE, tracking `oi` correctly at
  every tick; zero console errors on screenshot.
  **Tick-to-tick OI Δ column added same day** (owner — "PREVIOUS ROW -
  CURRENT ONE COLUMN ADDITONAL NEED", distinct from the cumulative
  `oi_change` above): pure frontend, no backend/schema change — the table
  already has the full ordered series client-side, so "row above it" is
  computed inline (`oiTickDelta`) the same way the existing colour-coding
  already compared adjacent rows. Renamed the existing column `OI Δ` →
  `OI Δ (session)` and added `OI Δ (prev)` beside it so the two are never
  confused. `vite build` clean; live-verified the two columns disagree in
  sign on down-ticks (e.g. `OI Δ (prev) -2,74,430` while `OI Δ (session)`
  stays positive), confirming they're reading different baselines; zero
  console errors on screenshot.
  **1-minute recent-band added + SENSEX near-expiry bug fixed** (owner —
  "ONE MORE FILTER 1MIN OR3 MIN 5 MIN OR10 MIN OR 15 MIN" / "SENSEX SHOWING
  11:45 AM ONLY?"): `time_band`/`recent_window_min` now accepts `1` (router
  `_TIME_BANDS`, frontend `TIME_BANDS`) alongside 3/5/10/15. Separately
  investigated and confirmed the SENSEX report was a real bug, not a
  perception issue — live DB check showed SENSEX's OI for its own weekly
  expiry (2026-09-17, landing that trading day) genuinely stopped updating
  at 11:45/11:46 IST, the exact moment `app.instruments.roll`'s periodic
  universe roll dropped those contracts from `is_tracked` and moved tracking
  to the next expiries (2026-09-24/10-01, both fresh to 15:39); NIFTY never
  hit this since its own near weekly (2026-09-22) wasn't expiring that day.
  Root cause: `services.option_expiries()` never filtered on `is_tracked`,
  so "pick the nearest expiry ≥ today" (used by `option_chain`/`oi_pulse`/
  `oi_mover_ltp_trace` whenever no `?expiry=` is given) kept silently
  resolving to that now-frozen, no-longer-ingesting expiry since its rows
  are still in the table. Fixed with `option_expiries(..., only_tracked=)`
  + a new `services._pick_near_expiry` helper (prefers the nearest tracked
  expiry, falls back to the full list only if nothing at all is tracked),
  wired into all three auto-pick call sites; the full `expiries[]` list
  returned to the frontend is unchanged (still browsable/pickable
  explicitly). Backend 715 pass unchanged (service-layer fix, no new pure
  function); ruff/black clean. Live-verified: `GET
  /instruments/255/oi-movers` now returns `expiry: "2026-09-24"` (was
  `"2026-09-17"`), NIFTY's own `expiry: "2026-09-22"` unaffected, `422`
  still correctly rejects an invalid `time_band`; screenshotted both the
  `1m` band button and SENSEX's corrected expiry live, zero console errors.
  **LTP trace grouping with a low–high band** (owner — "i NEED FILTRATION
  IN ltp TRACE IF LTP LOW HIGH BAND LIKE IF 5 MIN MULTIPLE PRICE MEANS"):
  100% frontend, no backend/schema change. New `bucketTrace(series,
  bucketMin)` in `OiMovers.tsx` groups the raw 1-min `series` into
  session-open-anchored N-min windows (`1m` = 1:1 passthrough, the default);
  each window reports `optLow`/`optHigh`/`optClose` (+ the underlying's own
  low/high/close) and the window's *last* tick's OI/`oi_change` (a running
  value, not banded). A new `band(lo, hi, fmt)` helper renders a single
  price when `lo === hi`, a `low–high` string otherwise — directly matching
  the request ("if 5 min multiple price means" → show the band, else just
  the one price). Row up/down colouring compares each window's **close**
  (last tick) to the previous window's close, not high-to-high — avoids a
  fragile `||`-chained fallback an earlier draft used and was caught before
  shipping. New `group` button row (`1/3/5/10/15m`, same values as the
  Movers tab's recent-band) sits next to the strike picker; time column
  becomes a range (`15:35–15:39`) once grouped; column headers gain
  `(low–high)` while grouped. `vite build` clean. Live-verified on NIFTY
  23,300 PE: 385 ticks → 77 rows at `5m` (385/5, exact), e.g. `15:35–15:39`
  showing PE LTP `99.00–104.70` and NIFTY LTP `23,270.60` (single value —
  NIFTY didn't move within that window); zero console errors on either
  granularity screenshotted.
  **LTP Δ / underlying Δ price-difference columns added same day** (owner —
  "CAN U ADD PRICE DIFFERNCE IN ltp TRACE"): new `sPrice` signed-price
  formatter (mirrors the existing `sInt`); `optDelta`/`undDelta` = each
  row's `optClose`/`undClose` minus the previous row's (the same close
  fields the grouping feature already computes for colouring — no new
  data, just surfaced as its own cell), rendered right after their
  respective LTP/band columns. `vite build` clean; screenshotted both `1m`
  and `5m` showing signed deltas alongside the bands (e.g. `5m` window
  `15:35–15:39`: PE LTP `99.00–104.70`, `LTP Δ -7.70`), zero console errors.
  **OI ladder — a new third tab** (2026-09-18, owner: "OI Delta only that
  time change only ... like this one more display option in LTP Trace [/]
  oi movers", pasted a mocked-up time × price grid — confirmed via
  `AskUserQuestion` before building as a classic CE | strike | PE
  option-chain ladder, mirrored, showing OI **change between time columns**
  rather than a snapshot). New pure `analytical_core.options.build_oi_ladder`
  (+ `OiLadder`/`OiLadderRow`/`OiLadderCell` dataclasses) in `oi_pulse.py`:
  per strike, CE/PE OI at each of N ascending time marks via `_at_or_before`,
  each cell's `oi_delta` = that mark's OI minus the mark before it (`None`
  on the first column — deliberately delta-only per the owner's framing, not
  raw OI), optionally windowed to strikes within `window_up`/`window_down`
  of ATM (reuses the same step-inference convention as `build_oi_pulse`'s
  own `trace_window_up`/`_down`). New `services.oi_ladder` generates
  `n_marks` `step_min`-spaced times ending at `min(now, session_close)`
  (default 3 marks, 1 min apart — matches the owner's pasted mock exactly),
  resolves the near expiry via yesterday's `_pick_near_expiry` fix, loads
  only each strike's OI series (no premium/volume needed for an OI-only
  view). New `GET /instruments/{id}/oi-ladder?marks=&step_min=&window_up=
  &window_down=` (`OiLadderResponse`/`OiLadderRow`/`OiLadderCell` schemas,
  `422` on a bad `step_min`, `404` on no options/spot) registered in the
  existing `oi_movers.py` router (same screen family as `oi-movers`/`oi-
  movers/ltp-trace`). Tests: `tests/test_oi_pulse.py` grew 18→23 (per-mark
  OI+delta shape, ATM-nearest-to-spot, window restricts rows, no-window
  keeps every strike, empty legs/marks) — all passed first run. Backend
  **720 pass** (was 715); ruff/black clean. `vite build` clean. Frontend:
  third `OI ladder` tab in `OiMovers.tsx` (`OiLadderPanel`) — `step`
  (1/3/5/10/15m) and `columns` (3/4/5/6) controls, a **Calls (CE) OI Δ |
  strike | Puts (PE) OI Δ** table with calls reading left→right (oldest →
  newest, toward the strike column) and puts right→left (mirrored, newest
  closest to the strike column, achieved by reversing both the PE header
  marks and each row's own `put` cell array together so they stay aligned),
  ATM row amber-highlighted, rows sorted highest-strike-first (classic
  ladder convention). Live-verified on real NIFTY: default view (±6 strikes,
  1m×3 columns) showed 13 rows, ATM 23,300 correctly highlighted; switching
  to 5m×5 columns showed genuine non-zero OI-Δ values varying by both strike
  and column (e.g. CE 23,350 `+2,37,055` at one mark, `+13,975` at the next)
  — confirming the per-strike-per-mark math is live and not just structurally
  correct; zero console errors on either screenshot.
  **Per-column max-|Δ| elevation added same day** (owner — "each maximum no
  oI change back ground color elevate"): new `maxAbsDeltaStrikePerColumn`
  (per time column, per side, finds the strike with the single biggest
  `|oi_delta|`) and `ladderCellCls` helper — that cell gets an elevated
  background (`bg-emerald-100`/`bg-rose-100` + bold) on top of the usual
  text colour, so the standout mover in each column is visible at a glance
  rather than requiring the reader to scan every number. A `0` delta is
  never elevated regardless of the max-per-column math (an early return in
  `ladderCellCls`), since a flat column has no meaningful "biggest" mover.
  PE-side elevation required mapping the reversed render index back to the
  original `marks` column index (`r.put.length - 1 - i`) so the highlighted
  cell aligns with the correct column even though puts render right→left —
  got this right on the first pass by reusing the exact same index-mapping
  reasoning already needed for the PE header/cell alignment when the tab was
  first built. `vite build` clean; live-verified on real NIFTY at 15m×6
  columns with genuinely varying non-zero deltas — each column's biggest
  mover (e.g. CE `+9,41,460` at one mark, PE `+17,70,925` at another)
  visibly highlighted, zero console errors.
  **Defaults widened** (owner — "default 3 min and 6 columns and add
  another strike above and below"): `OiLadderPanel`'s initial state changed
  `stepMin` 1→**3**, `marks` 3→**6**, and the (previously hardcoded,
  unexposed) `windowUp`/`windowDown` 6→**7** each — one more strike above
  and below ATM. Frontend-only, no backend/schema change (the API's own
  `marks`/`step_min`/`window_up`/`window_down` query defaults are untouched
  — this only changes what the frontend widget requests on first load).
  `vite build` clean; had to restart the dev server mid-verification since
  an unrelated earlier fix that session (binding Vite to the LAN interface
  for `192.168.0.235:5173` access) had dropped the `VITE_SHARE_MODE=0`
  bypass, so the passcode gate briefly blocked the Playwright screenshot —
  restarted with it set, then confirmed live: default view now shows 15
  rows (22,950–23,650, ±7 around ATM 23,300) with `3m`/`6` correctly
  highlighted as the active step/column buttons, zero console errors.
  **Widened again to ±10 + underlying LTP on hover** (owner — "±10 around
  ATM and mouse hover can we show price"): frontend window default 7→**10**
  each side (21 rows now, not 15). Backend: `OiLadder` gained
  `underlying_at_marks: tuple[float | None, ...]`; `build_oi_ladder` gained
  an `underlying_series` param resolved via the same `_at_or_before` lookup
  already used for OI — the underlying's own LTP at/just-before each mark,
  disclosed for hover context, not part of the OI-only cell data.
  `services.oi_ladder` loads the underlying's M1 close series the same way
  `oi_pulse` already does for its own spot series, passes it through.
  Schema: `underlying_at_marks: list[float | None]` added to
  `OiLadderResponse`. Tests: `tests/test_oi_pulse.py` grew 23→25
  (`underlying_at_marks` resolves at/before each mark and carries the last
  known value forward on a gap; all-`None` when no series is given) — both
  passed first run. Backend **722 pass** (was 720); ruff/black clean.
  `vite build` clean. Frontend: each time-column header (both CE ascending
  and PE reversed, using the same original-column-index mapping the
  elevation feature already established) gets a dotted-underline
  `cursor-help` style and a native `title` tooltip — `"NIFTY 23,323.55 @
  12:34"` — no chart, no new UI chrome, a plain hover disclosure. Live-
  verified on real NIFTY: 21 rows (22,850–23,850, ±10 around ATM 23,350),
  header hover confirmed via Playwright reading the `title` attribute
  directly (`"NIFTY 23,323.55 @ 12:34"`), elevation still correct at the
  wider window; zero console errors.
  **Per-cell tooltip + option LTP, replacing the broken native one** (owner
  — "tool tip is a good idea if possible add option price also and tool tip
  not working showing symbol '?'"): the header `title` from the previous
  turn only ever showed the `cursor-help` question-mark cursor to the
  owner, no visible text — native browser tooltips are unreliable to style/
  trigger consistently. Replaced entirely with a real CSS tooltip
  (`group`/`group-hover:block`) on every OI-Δ **cell**. Backend:
  `OiLadderCell` gained `ltp: float | None`; `build_oi_ladder` resolves it
  per mark via `_at_or_before(lg.premium, mk)`; `services.oi_ladder` now
  also loads each option's M1 close series (mirrors the existing OI-series
  query) and passes it into `OiLegSeries.premium` (previously always `()`
  for this endpoint, since it was thought to be OI-only). Schema:
  `OiLadderCell.ltp` added. Tests: `tests/test_oi_pulse.py` grew 25→27
  (option LTP resolves per mark; `None` when no premium series supplied) —
  passed first run. Backend **724 pass** (was 722); ruff clean, one black
  reformat. `vite build` clean. Frontend: new `LadderCell` component
  wrapping each `<td>` in `group relative`, with a `bg-slate-900` tooltip
  showing strike/side/time, OI (+ Δ), LTP, and the underlying's LTP —
  removed the header `title`/`cursor-help` entirely. **Caught and fixed two
  real clipping bugs by screenshotting the actual edge cases, not by
  inspection**: (1) a centred (`left-1/2 -translate-x-1/2`) tooltip on the
  table's outermost columns got cut off by the table's own
  `overflow-x-auto` wrapper — fixed by anchoring to the cell's own edge
  instead (`left-0` for CE cells, `right-0` for PE cells, since CE sits on
  the ladder's left half and PE on its right); (2) a downward (`top-full`)
  tooltip on the table's last row got clipped too — `overflow-x-auto` alone
  computes `overflow-y: auto` per the CSS spec's automatic axis-pairing
  rule (confirmed via `getComputedStyle` in a debug script, not assumed),
  so a tooltip escaping the wrapper's bottom edge is invisible; fixed by
  flipping only the last row's tooltips to open upward (`openUpward` prop,
  `bottom-full` instead of `top-full`). Live-verified on real NIFTY: hover
  tooltips fully visible and correctly positioned at all four extremes
  tested (top-left cell, a middle cell, the last row) — e.g. `"22,850 PE ·
  15:15 / OI 30,50,320 / LTP 6.30 / NIFTY 23,341.85"` for the last row, no
  longer clipped; zero console errors throughout.
  **Premium decay** (owner-authorised 2026-09-11, `docs/05` §11.6 / `docs/07`
  §4.23): `GET /instruments/{id}/premium-decay` — per strike, the theta-implied
  decay since today's session open (linear estimate at the option's current
  Greeks) vs. the premium's actual move, with a `decay_state` (`AS_EXPECTED` /
  `DECAYING_FASTER` / `OFFSET_BY_MOVE` / `NO_DATA`); ATM call/put/straddle
  θ-per-lot + a `fast_decay_zone` flag (`dte ≤ 5`). Built on `option_chain`
  (`analytical_core.options.decay`). `/instruments/:id/premium-decay` screen
  (CALLS\|STRIKE\|PUTS ladder). Options only, descriptive only — no BUY/SELL.
- **Golden-cross-grid MA-proximity alert** (owner-authorised 2026-09-15 —
  "need alert like 200 moving average near by support and resistance",
  `docs/05` §7 / `docs/07` §4.19): each of the grid's 5m/15m/1h/1D columns now
  also reads the 50/200 MAs as dynamic support (price above) / resistance
  (below) — `near_fast` / `near_slow` when within `golden_cross.near_ma_pct`
  (`app_settings` key, default 0.3%, read-view-only — does not touch the
  scored `golden_cross` analysis's `params_hash`), `nearest_ma`/
  `nearest_ma_side` when the closer one wins. `GoldenCrossGridPanel` takes an
  amber tint + `● near 50/200 (support|resistance)` when not already
  cross-tinted. `GOLDEN_CROSS_GRID_VERSION` 0.1.0→**0.2.0**.
  **EMA row** (owner-authorised 2026-09-16 — "DMA 50 200 like need EMA one
  box"): each column also reports `ema_fast`/`ema_slow` — the same
  fast/slow periods run through `golden_cross()` a second time with
  `overrides={"ma_type":"EMA"}`, regardless of the configured `ma_type`. A
  supplementary read only — the cross/regime/near-MA logic stays tied to the
  one configured `ma_type`, not duplicated. Panel gains an **EMA (50/200)**
  row. `GOLDEN_CROSS_GRID_VERSION` 0.2.0→**0.3.0**.
  **Fix same day** (owner-flagged — "200 EMA showin 24300 around but in our
  analytical showin 24453 ? D1"): the grid's per-column bar load
  (`_GC_GRID_LOAD`) was `280` — fine for the windowed 200-bar SMA, far too
  short for EMA(200) to converge (its exponential memory extends well before
  the window). Raised to `1500`; NIFTY D1 `ema_slow` moved from 24453→24286,
  matching the owner's external reference. `GOLDEN_CROSS_GRID_VERSION`
  0.3.0→**0.3.1**.
  **Display bug fix same day** (caught during a live app run-through, not
  owner-reported): `GoldenCrossGridPanel.tsx`'s `dPct` helper, the
  `Separation` row, and the near-MA footnote all called `pct(v * 100, 2)` —
  but `lib/format.ts`'s `pct()` already multiplies its input by 100
  internally (it expects a raw fraction). Every percentage in this panel
  (Fast/Slow distance, Separation, "near ___% of a moving average") was
  rendering **100× too large** (e.g. a real −0.04% showed as "−4.37%") since
  the MA-proximity feature shipped 2026-09-15 — pure display, the underlying
  `dist_to_fast_pct`/`dist_to_slow_pct`/`separation`/`near_ma_pct` API values
  were always correct. Fixed by dropping the erroneous `* 100` at all three
  call sites.
- **Daily digest** (`docs/07` §4.12, owner-authorised 2026-09-01): per-instrument
  `GET /instruments/{id}/daily-digest` — one row per trading day with D1 OHLC,
  gap / range %, previous-day-high & previous-day-low **break flags** + a
  range-type label, and the day's TPO profile (shape / day-type / POC / VAH /
  VAL / IB / close-vs-value) where a `market_profile_sessions` row exists. Pure
  DB read in `app.api.services.daily_digest`; frontend screen + route.
  **Gap/close filter** (owner-authorised 2026-09-15 — "open gapup like more
  than .5% and close -.5% the days"): `gap_min_pct`/`gap_max_pct` (on
  `gap_pct`, open vs prior close) and `chg_min_pct`/`chg_max_pct` (on
  `change_pct`, close vs prior close), inclusive, any combination, applied
  before pagination so `total`/`summary` reflect only matching days; the
  trailing-14-day range average still sees every day regardless. Summary
  gained `mean_change_pct`. Frontend: 4 filter inputs + a one-click "gap-up
  fade preset" (0.5 / −0.5) + a `filtered: …` summary badge. Live-verified:
  60 NIFTY days since 2000 match gap ≥0.5%/close ≤−0.5%, mean gap +0.86% /
  mean close change −1.33%.
- **Index constituents / weightage** (`docs/15`, owner-authorised 2026-09-03):
  `index_weights` seeded table (migration `0005`, owner-maintained via
  `analytical-index-weights load`) + pure `analytical_core.indices`
  (`build_constituent_view` — weight-ordered names, cumulative weight, sector
  rollup, concentration/HHI, day contribution `weight·change/100`, breadth,
  beta/correlation) + `GET /instruments/{id}/constituents` (quote-on-read;
  degrades to weights-only; `?include_beta`) + `ConstituentsPanel` on the INDEX
  instrument-detail screen. Constituents are **not** tracked instruments and are
  **not** ingested. Descriptive — no signal, no BUY/SELL.
- **ORB backtest** (`docs/16`, owner-authorised 2026-09-04 — narrows decision
  23): pure `analytical_core.backtest.orb` (`run_orb` — range-window high/low,
  first breakout of a later window, target `k·range` vs opposite-edge stop,
  configurable `measure_until`, per-target hit-rates + weekday split) +
  `GET /instruments/{index_id}/backtest/orb` (M1/M15 index bars, computed on
  read, not persisted) + `/instruments/:id/backtest` screen. One bounded study,
  not a framework. Descriptive — no signal.
- **ICT swing Fair Value Gaps** (`docs/05` §9c, owner-authorised 2026-09-09):
  pure `analytical_core.fvg.scan_swing_fvgs` — the "left-side" FVGs that form
  into a swing high/low and then act as **inversion** arrays; each with CE (50%)
  and a `PRIMED / TESTED / RESPECTED / BREACHED` state (wick-violated /
  body-respected tracked). A **read view** (no factor score, no version guard,
  enums module-local), exposed only as `GET /instruments/{id}/fvg-grid` +
  `FvgGridPanel` over 5m/15m/30m/1h (M30 folded from M5), INDEX + FUTURE.
  `FVG_VERSION` 0.1.0. Descriptive — no bias score, no BUY/SELL.
- **Candle Range Theory (CRT)** (`docs/05` §9d, owner-authorised 2026-09-16):
  pure `analytical_core.crt.scan_crt` — a reference candle's High-Low range,
  read against the bars since it for **current position** (above high / below
  low / at midpoint / inside), **breakout** direction + hold/reject/retest,
  **range expansion** beyond the break (points + ×range multiple), and a
  **compression** flag when the reference candle sat fully inside its own
  prior ("mother") bar. A **read view** (no factor score, no version guard,
  enums module-local), exposed only as `GET /instruments/{id}/crt-grid` +
  `CrtGridPanel` over 5m/15m/30m/1h (M30 folded from M5), INDEX + FUTURE.
  `CRT_VERSION` 0.1.0. Descriptive — not "green candle = bullish", no
  BUY/SELL. *Scoped out:* the ICT/HTF→LTF variant (owner flagged as a
  possible follow-up) is a different method, not built here.
- **Gann time cycles** (`docs/05` §9e, owner-authorised 2026-09-16 — "Gann
  Days / Gann Time Cycles can we implement in our logic?" → "previous low day
  and high [day], then low high based on period with gann ideas"): pure
  `analytical_core.gann_cycles.scan_gann_cycles` — the previous swing low/high
  (the window's own extreme over ~1y of D1 bars) each projected forward by
  the classic Gann day-counts (45/90/120/144/180/270/360 calendar days);
  projections whose target dates land within `cluster_tolerance_days` of each
  other are grouped into confluence **clusters**. A **read view** (no factor
  score, no version guard, enums module-local), exposed only as
  `GET /instruments/{id}/gann-cycles` + `GannCyclesPanel` — one read per
  instrument (calendar-date based, not a 5m/15m/1h/1D grid), INDEX + FUTURE.
  `GANN_CYCLES_VERSION` 0.1.0. Descriptive — calendar dates where a turn is
  more likely by this method, not a signal; no BUY/SELL, no entry/target/stop.
  **Actual-value fill same day** (owner-flagged — "past data need fill the
  value"): each projection also carries `resolved_date`/`actual_close`/
  `actual_high`/`actual_low` — filled from the nearest trading date on/after
  `target_date` when that date already has a bar in the loaded series (still
  `null` for a genuinely future projection). `GannCyclesPanel`'s projections
  table gains an **actual** column so a past Gann date can be checked
  against what price really did there.
- **Gap-fade streak study** (`docs/05` §9f, owner-authorised 2026-09-16 —
  "gapup day and close much lower... continuos down... streak end
  shortterm consolidation and breakout need find", explicitly "its not
  backe test i need to analysis"): pure
  `analytical_core.gap_fade_study.scan_gap_fade_study` — **not a backtest**
  (no entry/exit/target/stop), a descriptive historical study over the
  **entire** D1 series. Reuses the Daily Digest gap-filter event definition
  (`gap_pct >= gap_min_pct` and `change_pct <= chg_max_pct`, default
  0.5/−0.5); for every qualifying day, measures the down-streak that
  followed, a **simple-box** consolidation (owner-picked over an ATR
  squeeze) from the days right after the streak ends, and the eventual
  **breakout** (owner-picked: close clears the box by a buffer, over a bare
  box-touch), direction UP/DOWN. Aggregated into a summary (occurrence
  count, streak-length histogram, consolidation days, breakout up/down
  split) plus every individual occurrence. A **read view** (no factor
  score, no version guard, enums module-local), exposed only as
  `GET /instruments/{id}/gap-fade-study` + `GapFadeStudyPanel` (live
  gap/close threshold inputs) — INDEX + FUTURE. `GAP_FADE_STUDY_VERSION`
  0.1.0. Live-verified on NIFTY: 60 historical occurrences, median 2-day
  down-streak, median 5-day consolidation, breakouts resolve UP 61% of the
  time. Descriptive — no BUY/SELL, no entry/target/stop, no hit-rate.
  **Extended 2026-09-17** (owner — "like open low close/open high close
  actually it represent the reversal"): the first version only covered the
  gap-**up**-then-close-down case — its mirror, gap-**down**-then-close-up
  (a bullish reversal), was entirely missing. Generalised to both
  directions: `UP` tracks a down-streak (unchanged), `DOWN` tracks an
  up-streak; params doubled (`gap_up_min_pct`/`chg_down_max_pct` for UP,
  `gap_down_max_pct`/`chg_up_min_pct` for DOWN); box/breakout logic stays
  direction-agnostic (a DOWN event's box can still break either way).
  Restructured `summary` (singular) → `summaries` (one per direction,
  always both present) — a clean break, not worth a migration path this
  soon after shipping. `GAP_FADE_STUDY_VERSION` 0.1.0→**0.2.0**. Panel now
  shows two boxes side by side (`Gap-up fade — bearish reversal` /
  `Gap-down fade — bullish reversal`), one ± magnitude input pair applied
  symmetrically instead of four separate fields. Live-verified on NIFTY:
  DOWN direction — 33 occurrences (previously zero, since it didn't exist),
  median 1-day up-streak, breakouts resolve UP 54.5% of the time.
- **Economic event calendar** (`docs/05` §9g, owner-authorised 2026-09-16 —
  "news driven i need basic news like fed powell and Auto sale and indian
  Gst... predefined news... calander based on the calander view", explicitly
  **not live news**): pure `analytical_core.event_calendar.scan_event_calendar`
  — `US_JOBS_REPORT` (1st Friday/month) and `INDIA_GST_COLLECTION` (~1st/month,
  from 2017-07-01) generated by deterministic calendar rule, fully backfilled
  across all D1 history; `FNO_EXPIRY` supplied as real dates from the tracked
  universe (current + next contract only — **not backfilled**, `instruments`
  doesn't retain expired contracts and NSE's expiry weekday has changed over
  the years, flagged to the owner before building). Every occurrence within
  the loaded series carries `prior_close`/`close`/`change_pct` +
  `next_close`/`next_change_pct`; per-type `summary.pct_notable_move` = the
  real historical % of occurrences moving `>= notable_move_pct` (default
  0.5%) — a genuine empirical answer to the owner's own "75% will not
  happen, 25% will" framing, not an assumed number. A **read view** (no
  factor score, no version guard, enums module-local), exposed only as
  `GET /instruments/{id}/event-calendar` + `EventCalendarPanel` — an actual
  month-grid calendar (prev/next/today nav, colour-coded per-event badges),
  INDEX + FUTURE. `EVENT_CALENDAR_VERSION` 0.1.0. Live-verified on NIFTY:
  323 jobs-report occurrences (median move 0.66%, 59% notable), 113 GST
  occurrences (median 0.59%, 57% notable), 0/2 F&O expiry resolved (exactly
  as disclosed). Descriptive — anticipatory context, not a prediction; no
  BUY/SELL, no entry/target/stop.
  **Extended same day** (owner — "fed rate decision not coming and need
  gold expiry silver expiry gst collection all old data need and meal
  while future also"): added `GOLD_EXPIRY`/`SILVER_EXPIRY` (MCX's 5th-of-
  month rule, snapped backward to the nearest earlier trading day —
  approximate, no MCX holiday calendar in this system, NSE days stand in;
  fully backfilled, 323 occurrences on NIFTY, median move 0.53%, 54%
  notable) and `FED_RATE_DECISION` (owner-authorised — FOMC dates aren't a
  formula, so a small hand-maintained seed list,
  `_FOMC_RATE_DECISION_DATES` in `app/api/services.py`, 2023-2025 only,
  seeded from training knowledge at moderate-not-certain confidence,
  explicitly **not** extended further back or into 2026+ to avoid
  presenting unverified dates as fact — 24 occurrences on NIFTY, median
  move 0.32%, **22% notable**, notably closer to the owner's original "25%"
  guess than the jobs-report/GST rates turned out to be). GST already had
  full history back to 2017-07-01 and future dates were already included
  for every type via `future_horizon_months` — both carried over
  unchanged, no gap to fix there.
  **Fix same day** (owner — "Fed rate decision yesterday but its not
  showing"): the 2023-2025 seed list had no 2026 entries at all
  (deliberately — 2026 is at/past this model's knowledge cutoff, so nothing
  was guessed). Added `2026-09-16` on the owner's direct confirmation it
  happened — **owner-confirmed dates only for 2026+, never recalled from
  training knowledge** — live-verified: NIFTY +0.43% that day, +0.29% the
  day after. Extend the same way going forward.
  **Extended 2026-09-17** (owner referenced investing.com's own economic
  calendar — "most bullishness gold expiry us and usdinr india like all
  data needed"): fetched that page to check what it flags as genuinely
  high-impact — added `US_JOBLESS_CLAIMS` (every Thursday, a real weekly
  formula the page itself lists as high-impact, zero guessing needed,
  fully backfilled — 1404 occurrences on NIFTY, median move 0.69%, 61%
  notable). Explicitly did **not** add US CPI/GDP or RBI policy decisions
  from the same page — those are agency/committee-scheduled with no clean
  formula, same reliability problem as FOMC, not built without further
  owner input. USD/INR flagged as **not trackable** as its own series —
  this system has no forex data source (decision 2 locks scope to NSE
  index/derivatives) — existing events already serve as the relevant
  triggers, impact stays measured on NIFTY. Caught and fixed a real bug
  while building the weekly generator: the shared `horizon_end` is only the
  *first* day of the horizon's last month (fine for the month-granularity
  generators, which don't care about the exact day) but a day-by-day
  Thursday walk against it silently produced **zero** occurrences for any
  horizon before this was caught — added `horizon_end_day` (the true last
  day of that month) for `_thursdays()` specifically.
  **Extended again same day** (owner — "US gold expiry ? need to fill next
  60 days enough india even us event europe events enough"): asked before
  guessing since two real forks existed — owner confirmed both (a) add
  COMEX gold/silver expiry despite the accuracy caveat (COMEX/NSE share no
  holiday calendar, unlike MCX/NSE which do — a materially rougher
  approximation, disclosed upfront), and (b) add ECB rate decision the same
  way as Fed (hand-maintained seed list, 2023-2025, moderate confidence).
  Renamed `GOLD_EXPIRY`/`SILVER_EXPIRY` → `MCX_GOLD_EXPIRY`/
  `MCX_SILVER_EXPIRY` for clarity now that a second exchange exists; added
  `COMEX_GOLD_EXPIRY`/`COMEX_SILVER_EXPIRY` (27th-of-month rule-of-thumb,
  backward-snapped — deliberately a *different* day-of-month anchor than
  MCX's 5th, so the two exchanges land on genuinely different dates) and
  `ECB_RATE_DECISION` (`_ECB_RATE_DECISION_DATES` in `app/api/services.py`,
  same treatment/caveats as `_FOMC_RATE_DECISION_DATES`). 60-day forward
  window already existed (`future_horizon_months` default 2) — confirmed,
  no change needed. Now **10 event types** total. Live-verified on NIFTY:
  COMEX gold 62% notable (vs MCX gold 54%), ECB 56.5% notable — all fast
  (0.39s for 3183 combined occurrences).
  **Extended 2026-09-17** (owner's detailed events priority table, RBI MPC
  flagged 🔴 very high priority — "hope thease all coverd?"): added
  `RBI_RATE_DECISION` — structurally identical to Fed/ECB, a small
  hand-maintained seed list (`_RBI_RATE_DECISION_DATES` in
  `app/api/services.py`), 2023-2025 only, moderate-not-certain confidence,
  bi-monthly (6/year, unlike Fed/ECB's 8), no 2026+ entries. Now **11 event
  types** total. Live-verified on NIFTY: 18/18 resolved, median move 0.52%,
  50% notable, 8 up / 10 down. Explicitly declined the rest of the owner's
  priority-table list as out of scope for this feature shape: US CPI/GDP/
  PPI/Retail Sales/ISM PMI and India CPI/GDP/IIP/PMI (agency-scheduled, no
  clean formula, lower confidence in exact recall than 6-8x/year committee
  dates — same reliability problem as FOMC/RBI, not seeded without further
  owner input); FII/DII flows (a different data shape entirely — flows, not
  calendar-date events); India company earnings (per-company, doesn't fit a
  global calendar); global geopolitical events (unschedulable by nature).
- **Key levels — last 2 sessions** (`docs/05` §10.12, owner-authorised
  2026-09-07): pure `analytical_core.market_profile.build_key_levels` — POC /
  VAH / VAL / IB / session hi-lo from the previous two completed TPO sessions,
  price-sorted, each with signed distance + a proximity `tier` (AT / NEAR /
  APPROACHING / FAR — bands default per instrument, NIFTY 15/30/45 vs BANKNIFTY
  40/80/120, overridable) + an acceptance/rejection read on the AT/NEAR levels
  from recent M5 bars. `GET /instruments/{id}/key-levels` + `KeyLevelsPanel` on
  instrument-detail. A read view — not an engine analysis (no factor score, no
  version guard, enums module-local). Descriptive — no bias, no BUY/SELL.

Not done: live Upstox checkpoints A–G (need a real token); frontend
build/lint/test; **Phase S — S3/S4** (real Upstox WS adapter once `docs/11` §5
S-1..S-7 is confirmed + `protobuf` signed off; then deploy).

**Still do not begin a new area of work without an explicit owner instruction
naming it** — this discipline stays regardless of phase.

---

## 3. Locked decisions (do not silently revisit)

| # | Decision |
|---|----------|
| 1 | Market data provider: **Upstox API** first, behind a **provider abstraction** (`MarketDataProvider` + `AuthProvider`). Providers must be replaceable. |
| 2 | Asset scope: **NSE** — NIFTY, BANKNIFTY (INDEX); NIFTY/BANKNIFTY FUTURES; NIFTY/BANKNIFTY OPTIONS. Instrument-type abstraction (`INDEX / FUTURE / OPTION`); nothing instrument-specific in the engine. |
| 3 | Cadence: **intraday periodic**, target 1–5 min cycle. **Streaming is in scope (lock lifted 2026-08-30, owner)** but strictly bounded: a WebSocket feed supplies **only the forming M1 bar + live OI**; the deterministic engine still runs on the periodic cycle; REST stays authoritative for history / backfill / disconnect gap-fill; the streamer is a **separate optional process**. |
| 3.1 | Streaming feed: **Upstox Market Data Feed v3 (WebSocket, protobuf)**, behind a `StreamingMarketDataProvider` seam. Runtime deps `protobuf` + `websockets` — **owner sign-off 2026-08-31**; `MarketDataFeed_pb2.py` generated & committed. `docs/11` §5.1 confirmed; `app/providers/upstox/feed.py` (`UpstoxMarketFeed`) built (S3). The machine PV gate stays scoped to the Phase-2 REST surface (PV-1..PV-8); the adapter carries its own `stream_enabled` guard. |
| 4 | User-facing analysis timeframes: **5m, 15m, 1h, 1D**. `M1` is an ingestion/aggregation source only. All intraday grids are **session-open-anchored**. |
| 5 | Market Profile: **TPO** and **Volume Profile**, modular, deterministic, configurable. 30-min TPO / 70% VA / NSE session are **defaults derived from parameters**, not hard-coded. |
| 6 | Golden Cross: default **50 / 200 SMA / Daily**, fully configurable; **primarily an INDEX analysis** — `NOT_APPLICABLE` on dated FUTURE/OPTION by default. |
| 7 | Users: **single-user / internal**. Global config + global tracked universe. No per-user resources in V1. Auth seam does not block multi-user later. |
| 8 | Deployment: **Docker Compose** — `db`, `backend`, `frontend` (+ optional `worker`). |
| 9 | Database: **standard PostgreSQL 16**. **No TimescaleDB.** Partition-ready schema, verified by a structural test. |
| 10 | Frontend: **React + TypeScript + Vite + Tailwind + TanStack Query**. |
| 11 | **No charts in V1** — *narrowed 2026-09-03 (owner):* one deliberately rough hand-drawn **inline SVG** on the astro day screen only (open-price line, timeframe dropdown H1/M15/M5, over the Moon-anchored dasha bands, `docs/13` §5.6.1). No charting library, no charts anywhere else. See §3b. |
| 12 | Architecture: **modular monolith**. No microservices, no Kafka, no Kubernetes, no ML infra. |
| 13 | The deterministic **analysis + scoring engine (`analytical_core`) is pure** — no FastAPI, no SQLAlchemy, no IO. It receives series + parameters; scoring receives `instrument_type` + `expected_analyses` **as data**. |
| 14 | Architecture must leave room for: backtesting, charts, alerts, more providers, more instruments, ML, AI explanations, mobile. Seams listed in `docs/02` §7 / `docs/10`. |
| 15 | **Analytical decision-support only.** No brokerage orders, no automated execution. **BUY/SELL output narrowed 2026-09-03 (owner):** still barred from the scoring engine, the analyses, and every other screen; *permitted only* in the OI-based option-strategy resource (`analytical_core.options.strategy` + `GET /instruments/{id}/option-strategies` + the `StrategyBook` panel), which returns illustrative structures with per-leg BUY/SELL + ratio and a mandatory "not advice / not an order" disclaimer. No order placement, ever. See §3b. |
| 16 | **Analysis applicability is per instrument type**, defined by the matrix in `docs/04` §4. `NOT_APPLICABLE` ≠ `INSUFFICIENT_DATA`. |
| 17 | **Analysis scope model** (`docs/12`): `PER_TIMEFRAME / SESSION / SNAPSHOT`. Invalid timeframe values are never used to represent session or snapshot analyses. |
| 18 | **Exactly one `analysis_run` per execution cycle**, covering INGEST + ANALYZE + SCORE, with per-phase and per-instrument status. |
| 19 | **Hot reads come from `current_*` projection tables.** Dashboard/detail never scan historical `analysis_results` / `signal_scores`. |
| 20 | **All timestamps are bar-open, tz-aware UTC**, everywhere. OI is explicitly aligned to bar-open (branch A) or a poll instant (branch B). |
| 21 | **Enums are defined once** in `analytical_core.enums` (`docs/12`); DB + API derive from it; a CI test enforces parity. |
| 22 | **No Upstox capability is assumed** until the matching item in `docs/11` is `CONFIRMED` or `ACCEPTED_FALLBACK`. Enforced mechanically: `docs/11-provider-validation.status.yaml` + the `provider-validation-gate` CI job + the Upstox adapter startup guard. `OPEN` blocking row ⇒ adapter refuses live calls and Phase 2 cannot start. |
| 23 | **Backtesting is future work, not built in V1** — *narrowed 2026-09-04 (owner):* one bounded study is permitted, the opening-range-breakout (ORB) backtest (`analytical_core.backtest.orb`, `GET /instruments/{id}/backtest/orb`, `/instruments/:id/backtest` screen). Pure, computed on read, not persisted, descriptive (no signal/label/BUY-SELL), no engine wiring. Not a general framework — a second pattern needs its own authorisation. `docs/16`, §3b. |

### 3b. Decision revisions (post Phase 0)

- **2026-09-04 — "No backtesting in V1" narrowed (owner).** Decision 23 now
  permits **one** bounded study: the **opening-range-breakout (ORB) backtest**
  (`analytical_core.backtest.orb.run_orb`; `GET
  /instruments/{index_id}/backtest/orb`; the `/instruments/:id/backtest` screen).
  Per day: high/low of a *range window* → first cross of an edge in a *breakout
  window* (LONG/SHORT, or immediate if already outside) → did price reach
  `k·range` (targets, default 0.5× / 1.0×) before the opposite edge (stop), by a
  configurable `measure_until`? Intrabar target+stop tie ⇒ stop-first. Aggregates
  breakout rate, per-target hit-rate, stop rate, minutes-to-target, weekday
  split, over M1/M15 index bars (2022→now). *Scope stays tight:* pure &
  deterministic, computed on read, not persisted, **no signal / label / BUY-SELL**,
  no engine or scoring wiring, no costs/sizing/equity-curve. Not a general
  backtest framework — a second pattern needs its own authorisation. `docs/16`,
  `docs/07` §4.15, `docs/08`.

- **2026-09-03 — "No BUY/SELL output" narrowed (owner).** Decisions 15 / hard
  rule 7 now permit **one** resource to emit trade structures: the OI-based
  **option-strategy suggestions** (`analytical_core.options.strategy` →
  `build_strategy_book`; `GET /instruments/{id}/option-strategies`; the
  `StrategyBook` panel on the option-chain and OI-pulse screens). It reads the
  chain's per-strike OI / ΔOI / LTP, classifies the positioning into one of six
  views (`RANGEBOUND / LEAN_* / TREND_* / VOL_EXPANSION`), and returns candidate
  structures — iron condor / fly, short & long strangle / straddle, 1:1
  verticals, 1×2 ratio spreads — with per-leg `BUY`/`SELL` + `lots`, strikes
  picked from the OI walls / ATM, approximate premium / max-P-L / breakevens,
  and per-structure caveats. **Every payload carries a mandatory disclaimer**
  ("illustrative … not investment advice, not a recommendation, not an order").
  *Scope stays tight:* pure & deterministic, computed on read, not persisted, no
  order placement; the scoring engine and every other surface stay
  analytical-labels-only. `docs/05` §11.5, `docs/07` §4.13, `docs/08`.
  **Extended 2026-09-08 (owner):** each suggestion now carries a lognormal
  **`pop`** (probability of profit at expiry, on the ATM IV), **`reward_risk`**
  (= max_profit / |max_loss|) and **`edge_score` = pop · reward_risk**; the book
  is ranked best-edge first (`ranked_by = EDGE`). Wing width is settable in
  **index points** (`?wing_points` / `options.strategy_wing_points`);
  `options.strategy_min_reward_risk` drops thin-payoff rows. Breakevens gain a
  band framing (`lower_breakeven` / `upper_breakeven` /
  `spot_inside_breakevens`). New **`CALENDAR`** family (`CALL_/PUT_CALENDAR` —
  sell near-expiry, buy the far expiry same strike) surfaced only on a range /
  lean read when a later expiry's chain is loaded (`?calendars`, default on).
  Still analytical-only, still disclaimed, still no order placement.

- **2026-09-03 — "No charts in V1" narrowed (owner).** Decision 11 now permits a
  single approximate **inline SVG** (no charting dependency) on the **astro day
  screen**: the session's **open-price line** (of the `H1` / `M15` / `M5` bars,
  whichever the panel's timeframe dropdown selects — 5m added 2026-09-11) over
  the Moon-anchored dasha mahadasha bands, an antardasha lane, a per-period
  approx % move, and a bottom **planet-places lane** (09:00 IST zodiac strip
  with each graha + the Lagna at its longitude) —
  `frontend/src/features/astro/AstroDay.tsx` `SessionDashaPlot`; `docs/13`
  §5.6.1, `docs/08`. *Why:* the dasha timeline only means something next to
  what price actually did during it, and against the day's graha placement.
  *Scope stays tight:* no library, no charts on dashboard / instrument detail /
  option / digest screens; those remain numeric/tabular. Revisit before adding
  any second chart.

- **2026-08-30 — "No streaming in V1" lifted (owner).** New scope (decision 3):
  a WebSocket feed supplies only the forming M1 bar + live OI; the deterministic
  engine still runs on the periodic cycle; REST stays authoritative for history,
  backfill, and disconnect gap-fill; the streamer is a separate optional process.
  *Why now:* live option-chain OI and a seconds-fresh forming minute.
  *Original exclusion rationale still holds for the engine:* it is a
  deterministic batch and needs no sub-minute data; the always-connected,
  stateful component is isolated in `app/ingestion/stream.py` and cannot affect
  a run's determinism.

### 3a. Phase 0 revision pass — what changed

Applied all CRITICAL/HIGH and correctness MEDIUM fixes from the consistency
review:
- **C1** analysis scope model (`PER_TIMEFRAME/SESSION/SNAPSHOT`) → `docs/03`,
  `docs/04`, `docs/05`, `docs/07`, `docs/12`.
- **C2** Upstox token lifecycle → `docs/11` PV-1, `docs/02` §3.2/§6.6.
- **C3** intraday OI availability → `docs/11` PV-4 (branch A/B), `docs/03`,
  `docs/05` §9.
- **C4** scoring input contract (`ScoringInput`, `aux` scalars,
  `expected_analyses` as data) → `docs/04` §3.3, `docs/06`.
- **H1** dated-contract Golden Cross → applicability matrix (`docs/04` §4),
  `docs/05` §7.
- **H2** one bar-open UTC timestamp convention + OI alignment → `docs/03` §2,
  `docs/05` §3/§9.
- **H3** NSE session + session-anchored M5/M15/H1 + M1 aggregation → `docs/05`
  §3, `docs/11` PV-2.
- **H4/H5** deterministic configurable Market Profile (period gen, IB count,
  partial policy, POC, VA one-sided expansion, shape classifier) → `docs/05`
  §10.
- **H6/H28** futures rollover + session-stable option universe (hysteresis) →
  `docs/04` §2.3.
- **H8** `current_*` hot-read projections → `docs/03` §5.5, `docs/07` §1.
- **H9/H10** deterministic missing-volume + RSI zero-variation → `docs/05`
  §4/§8.
- **H12** auth seam corrected (no phantom user-scoped tables) → `docs/02` §6.6,
  `docs/07` §2.
- **H13** one run per cycle + `run_phase_status` + `run_instrument_status` →
  `docs/03` §5.3.
- **H14** per-bar series vs per-run trail split → `docs/07` §4.4.
- **M5** single `contribution` formula; **M6** zero-usable-factors rule;
  **M7** deterministic OI change + epsilons; **M16** ingestion repair pass;
  **M17** `oi_snapshots` / `market_profile_sessions` defined; **M18** provider on
  watermarks; **M19** provenance columns (`params_id`, `params_hash`);
  **M20** enum contract (`docs/12`); **M21** e2e worker-cycle test;
  **M22** partition-readiness test; **M23** no-trade interval handling;
  **M24** throughput budget + recompute guard; **M25** market-profile response
  shape; **M26** label clamp semantics; **M27** calendar `segment`.
- New docs: `docs/11-PROVIDER-VALIDATION.md`, `docs/12-ENUM-CONTRACT.md`.

---

## 4. Stack: decided vs. proposed

**Decided:** Python 3.12+, FastAPI, PostgreSQL 16, SQLAlchemy + Alembic, React,
TypeScript, Vite, Tailwind, TanStack Query, Docker Compose.

**Proposed (locked at the Phase noted in `docs/02` §8):** `uv`, structlog,
APScheduler, httpx, numpy (pinned), pytest + hypothesis, Vitest + RTL + MSW,
react-router, openapi-typescript, ruff + black.

Flag any change to a *decided* item to the owner first.

---

## 5. Planned repo layout

```
Analytical/
  .claude/CLAUDE.md
  docs/                       # 01..12 — source of truth
  backend/
    analytical_core/          # pure: enums.py, series.py, indicators/, market_profile/,
                              #       scoring/, versioning.py, params.py  — NO FastAPI/DB/IO
    app/
      providers/              # base.py (MarketDataProvider, AuthProvider), upstox/, registry.py
      instruments/            # registry, selection.py (rollover + session-stable universe)
      ingestion/              # normalise, aggregation.py (M1->grid), watermarks, repair pass
      analysis/               # orchestration -> analysis_results (+ recompute guard)
      scoring/                # orchestration -> signal_scores / score_factors
      worker/                 # one run per cycle; phases; single-flight
      db/                     # models, repositories, projections/ (current_*)
      api/                    # routers, schemas/
    tests/
    pyproject.toml
  frontend/                   # src/, tests/, package.json
  deploy/                     # docker-compose.yml, backend.Dockerfile, frontend.Dockerfile
  README.md
  .gitignore
```

`analytical_core` imports nothing from `app/`. `app/` depends on
`analytical_core`, never the reverse.

---

## 6. Conventions

**Python** — 3.12+; separate `analytical_core` / `app` packages; full type
hints, `mypy`/`pyright` clean; `ruff` + `black`; **all timestamps stored and
computed as bar-open UTC** (IST only for session math + display); prices
`Decimal` at boundaries, `float64` inside the engine with explicit rounding.

**TypeScript** — `strict: true`; API types generated from OpenAPI; server state
in TanStack Query.

**Commits** — Conventional Commits; one logical change per commit.

**Tests** — every analysis ships golden + property + provenance tests before it
is "done" (`docs/09` §6). The e2e worker-cycle test is a Phase 6 exit gate.

---

## 7. Hard rules

1. **No silent architectural decisions.** If the spec doesn't cover it, write it
   into `docs/` first.
2. **No dependency installs / migrations without owner sign-off** during Phase
   0–1.
3. `analytical_core` must not import FastAPI, SQLAlchemy, httpx, or any IO
   library. Scoring gets `instrument_type` / `expected_analyses` as data, never
   an `Instrument`.
4. Provider-specific code stays behind the provider protocols. No `upstox`
   imports outside `app/providers/upstox/`.
5. **No Upstox API capability is coded until the matching `docs/11` item is
   `CONFIRMED` or `ACCEPTED_FALLBACK`** in
   `docs/11-provider-validation.status.yaml`. While any `blocks_phase_2` row is
   `OPEN`, `app/providers/upstox/` holds only the stub allow-list
   (`__init__.py`, `stub.py`, `capabilities.py`, `gate.py`) and the adapter's
   startup guard raises `ProviderValidationGateError` on any live call. The
   `provider-validation-gate` CI job enforces this on every PR.
6. Enums come from `analytical_core.enums` (`docs/12`); DB and API must match —
   enforced by `test_enum_contract`.
7. **Analytical labels only** — with the single 2026-09-03 exception: the
   OI-based option-strategy resource (`analytical_core.options.strategy`) may
   emit option structures with per-leg BUY/SELL + ratio, always behind the
   disclaimer. Nowhere else — the scoring engine, analyses, board, digests and
   every other surface never emit or render BUY/SELL/execution instructions, and
   nothing ever places an order.
8. Every analysis result and score carries provenance (`algo_version`,
   `params_id`, `params_hash`).
9. Keep the schema partition-ready (`docs/03` §2); the structural test must
   pass.
10. Read endpoints serve from `current_*` projections; only history endpoints
    touch `analysis_results` / `signal_scores`.
11. No bar is ever fabricated or carried forward for a no-trade interval.
12. Update the relevant `docs/` file in the same change that alters behaviour.

---

## 8. Document index

| File | Purpose |
|------|---------|
| `docs/01-PRODUCT.md` | Problem, users, V1 scope, non-goals, decision-support framing, success criteria |
| `docs/02-ARCHITECTURE.md` | Modules, dependency rule, run model, projections, token lifecycle, throughput budget, seams |
| `docs/03-DATABASE.md` | PostgreSQL schema, scope model, run model, `current_*`, FKs, provenance, retention, partition-readiness |
| `docs/04-DATA-MODEL.md` | Instrument abstraction, universe policy, applicability matrix, core + scoring types |
| `docs/05-ANALYSIS-ENGINE.md` | Session/timeframe model, every analysis (deterministic, configurable), Market Profile, provenance |
| `docs/06-SCORING-ENGINE.md` | `ScoringInput`, sub-scores, `weighted_v1`, labels + clamp, explainability, non-execution |
| `docs/07-API-SPEC.md` | REST resources, scope in payloads, projections, series-vs-runs split, errors |
| `docs/08-FRONTEND-SPEC.md` | Views, panels, applicability states, no charts, no execution language |
| `docs/09-TESTING.md` | Golden/property/provenance/session/enum/e2e tests, CI, per-analysis DoD |
| `docs/10-ROADMAP.md` | Phased plan; Phase 1.5 provider-validation gate; reserved seams |
| `docs/11-PROVIDER-VALIDATION.md` | Upstox capabilities that must be confirmed before Phase 2 (PV-1..PV-8); narrative + mechanical-enforcement description |
| `docs/11-provider-validation.status.yaml` | **Machine-readable source of truth** for the provider-validation gate (status/evidence/fallback/branch per PV item) |
| `docs/12-ENUM-CONTRACT.md` | Authoritative enum list + DB/API synchronisation + change procedure |
| `docs/13-ASTRO-CROSSCHECK.md` | Optional side module: sidereal (Lahiri) planetary positions + Parashari Shadbala → `astro_positions` / `astro_shadbala`, joined to market data by date. Not part of V1 output. |
| `docs/15-INDEX-CONSTITUENTS.md` | Side module (owner-authorised 2026-09-03): seeded `index_weights` + pure `analytical_core.indices` — index constituents **ordered by weight** with cumulative weight, sector rollup, concentration, day contribution, breadth, beta/correlation. Quote-on-read; not persisted; not tracked instruments. `GET /instruments/{id}/constituents`, `ConstituentsPanel` on the INDEX detail screen, `analytical-index-weights` CLI. Descriptive — no signal. **Extended 2026-09-08:** `GET /instruments/{id}/constituents/levels?n=` — for the top-N members by weight, prev-day CPR/pivots + 52w range + RSI(D1/H1) + Bollinger(D1) + MA-trend (EMA20/50, 50/200 cross) + a plain-language hint, all **fetched live per name on read** (D1 + M1→H1; ~2 provider calls/name); pure indicators, INDEX only, not persisted/scored. `ConstituentsPanel` Top-10 strip gets a "+ levels & indicators" toggle. |
| `docs/16-BACKTESTING.md` | Bounded first backtest (owner-authorised 2026-09-04, narrows decision 23): the **opening-range-breakout (ORB)** study — pure `analytical_core.backtest.orb`, `GET /instruments/{id}/backtest/orb`, `/instruments/:id/backtest` screen. Configurable range / breakout windows + `measure_until` + target multiples over M1/M15 index bars; per-target hit-rates, stop rate, weekday split. Computed on read, not persisted, descriptive — no signal/label/BUY-SELL. Not a general framework. |
| `docs/14-MARKET-PROFILE-EVENTS.md` | Phase 4 event layer extending `docs/05` §10: pure `analytical_core.market_profile.events` — FACTS→EVENTS→CLASSIFICATION with lifecycle, strength, no look-ahead. MVP event set (`MP-nnn`). Owner-authorised 2026-08-31; slices 1/3/4 done (engine + cycle wiring + `market_profile_sessions.events` blob + API + panel); slice-2 catalogue completeness / VOLUME basis / composites / FUT-as-profile-of-record are future work. |
