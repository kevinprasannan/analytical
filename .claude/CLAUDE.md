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
