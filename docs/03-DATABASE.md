# 03 — Database Design

## 1. Engine

- **Standard PostgreSQL 16** (pinned). No extensions required in V1.
- **No TimescaleDB.** Schema is written so a later move to native range
  partitioning (or Timescale) is a migration, not a redesign. A structural CI
  test enforces the rules in §2 (`docs/09` §2.8, resolves M22).

## 2. Time-series compatibility rules

Applied to `ohlcv_bars`, `open_interest`, `oi_snapshots`, `analysis_results`,
`signal_scores`, `score_factors`:

1. Natural key includes `(instrument_id, …, ts_or_scope_key)`. Surrogate `id`
   exists but joins do not depend on it alone.
2. Every time column is `TIMESTAMPTZ`, UTC, **bar-open** (or an explicit poll
   instant for `oi_snapshots.snapshot_ts`) — one convention, everywhere
   (resolves H2).
3. No `ON UPDATE` triggers or stored procedures that would block partition
   routing.
4. Indexes are declared so they can be recreated per-partition
   (`btree (instrument_id, …, ts DESC)`; `BRIN (ts)` reserved).
5. Writes are idempotent upserts on the natural key (`INSERT … ON CONFLICT`).
   The `DO UPDATE SET` list is documented per table (§5).
6. Retention is a time-window delete (`WHERE ts < now() - interval`) so it
   becomes "drop partition" later.
7. No cross-table foreign key spans a would-be partition boundary in a way that
   blocks partitioning (children of `analysis_runs` are pruned before parents,
   §6).

## 3. Migrations & enums

- **Alembic.** Every schema change is a reviewed migration; no blind
  autogenerate.
- **Enum types** are created from `analytical_core.enums` (`docs/12`). The
  migration author emits the value list via
  `python -m analytical_core.enums --emit-sql`. `test_enum_contract`
  (`docs/09` §2.6) asserts PG labels == Python values == OpenAPI values.
- Seed migrations / a `seed` command (idempotent): the single `owner` user,
  `market_calendar` for the current **and next** calendar year, and
  `app_settings` populated from the **confirmed Phase 0 defaults**
  (`docs/02` §8.1) — `cycle_interval_seconds=180`, `finalize_grace_seconds=90`,
  `option_selection.*` (N=5, max_expiries=2, rebuild_trigger=8, strike_step
  50/100), `scoring.min_confidence=0.35`, `scoring.weights`,
  `scoring.label_bands`, retention windows. A `refresh-calendar` command
  extends the calendar; `/health/ready` warns when the furthest seeded date is
  < 30 days ahead (resolves H11).

## 4. Column conventions

| Concern | Rule |
|---|---|
| Prices | `NUMERIC(18,4)` |
| Volume / OI | `BIGINT` |
| Ratios / scores / %B / confidence | `NUMERIC(12,6)` |
| Timestamps | `TIMESTAMPTZ`, UTC, bar-open |
| Enums | Postgres `ENUM` generated from `analytical_core.enums` |
| `analysis_key` | `text` with a `CHECK` against the known set (it is a JSON/URL key, kept lowercase) |
| `params_hash` | `text` (16 hex) |
| PKs | `BIGINT GENERATED ALWAYS AS IDENTITY` |
| FKs | explicit `ON DELETE` on every FK (§5) |
| Soft delete | `is_active BOOLEAN` on registry tables; hard delete on derived data |
| Auditing | `created_at`, `updated_at` on mutable tables |
| Naming | `snake_case`, plural tables |

## 5. Schema (logical)

### 5.1 Reference / registry

**`instruments`**

| column | type | notes |
|---|---|---|
| id | bigint PK | |
| contract_key | text UNIQUE NOT NULL | provider-independent canonical id, e.g. `NIFTY-FUT-2026-01`, `NIFTY-OPT-2026-01-08-24000-CE`, `NIFTY-INDEX` |
| symbol / display_name | text | |
| exchange | text | `NSE` |
| segment | enum `instrument_segment` | `INDEX / FUT / OPT` |
| instrument_type | enum `instrument_type` | `INDEX / FUTURE / OPTION` |
| underlying_id | bigint FK → instruments(id) `ON DELETE RESTRICT`; `CHECK (underlying_id <> id)` | must reference an `INDEX` row (enforced in app layer; documented) |
| expiry_date | date NULL | derivatives only |
| expiry_kind | enum `expiry_kind` NULL | `WEEKLY / MONTHLY / QUARTERLY`; derivation rule `docs/04` §2.4 (resolves M3) |
| strike_price | numeric(18,4) NULL | options only |
| option_type | enum `option_type` NULL | options only |
| lot_size | integer NULL | |
| tick_size | numeric(18,4) NULL | |
| currency | text | `INR` |
| is_active / is_tracked | bool | |
| has_volume | bool NOT NULL default true | drives Volume applicability (resolves H9) |
| has_intraday_oi | bool NOT NULL | **RESOLVED `docs/11` PV-4: branch A_PER_CANDLE** → default `true` for FUTURE/OPTION, `false` for INDEX (seed sets it per `instrument_type`) |
| profile_bin_size | numeric(18,4) NULL | null → derived (`docs/05` §10.4) |
| created_at / updated_at | timestamptz | |

UNIQUE `(instrument_type, underlying_id, expiry_date, expiry_kind, strike_price, option_type)` (NULLs normalized) — `contract_key` is the practical unique key. Strike step is **not** a column: it lives in `app_settings` (`option_selection.strike_step.{NIFTY,BANKNIFTY}`, resolves M4).

**`provider_instrument_map`**

| column | type | notes |
|---|---|---|
| id | bigint PK | |
| instrument_id | bigint FK → instruments(id) `ON DELETE CASCADE` | |
| provider | text | `upstox` |
| provider_symbol | text | Upstox instrument key/token |
| provider_metadata | jsonb | raw provider fields |
| is_active | bool | |
| UNIQUE | `(provider, provider_symbol)`, `(provider, instrument_id)` | |

**`market_calendar`** (resolves M27)

| column | type | notes |
|---|---|---|
| id | bigint PK | |
| exchange | text | `NSE` |
| segment | text NOT NULL default `FO` | resolves M27 |
| calendar_date | date | |
| is_trading_day | bool | |
| session_open_ist | time | default `09:15` |
| session_close_ist | time | default `15:30` |
| session_type | text | `NORMAL / MUHURAT / SPECIAL`; a shortened day is `NORMAL` with non-default hours |
| note | text | |
| UNIQUE | `(exchange, segment, calendar_date)` | |

**`app_settings`** — `key text PK`, `value jsonb`, `updated_at timestamptz`.
Keys include `cycle_interval_seconds`, `market_profile.*`, `scoring.weights`,
`scoring.label_bands`, `scoring.min_confidence`, `option_selection.*`,
`futures_rollover.*`.

**`users`** — `id`, `username text UNIQUE` (one row: `owner`), `created_at`.
Reserved for real auth (password hash, roles) via future migration.

**`provider_credentials`** *(concrete once `docs/11` PV-1 closes; may be
env-only in V1)* — `id`, `provider`, `label`, `secret_ref`, `meta jsonb`
(token expiry, refresh capability).

### 5.2 Market data

**`ohlcv_bars`**

| column | type | notes |
|---|---|---|
| id | bigint PK | |
| instrument_id | bigint FK → instruments(id) `ON DELETE RESTRICT` | |
| timeframe | enum `timeframe` | `M1, M5, M15, H1, D1` |
| ts | timestamptz | **bar-open**, UTC; session-anchored (`docs/05` §3) |
| open/high/low/close | numeric(18,4) | |
| volume | bigint | ≥ 0 |
| provider | text | active provider |
| is_final | bool | false while forming; transition rule `docs/05` §3.5 |
| ingested_at | timestamptz | |
| UNIQUE | `(instrument_id, timeframe, ts, provider)` | |
| INDEX | `(instrument_id, timeframe, ts DESC)` | |
| `DO UPDATE SET` | `open,high,low,close,volume,is_final,ingested_at` (resolves L9 — forming→final revisions overwrite) | |

`M1` rows are persisted with short retention (§6) and used as the aggregation
source (`docs/05` §3.3). **RESOLVED `docs/11` PV-2, 2026-08-27: branch
AGGREGATE_FROM_M1** — Upstox serves native 1-minute (from Jan 2022) but H1
session-anchoring is undocumented, so M5/M15/H1 are always aggregated from M1;
D1 is native.

**`open_interest`** — **ACTIVE OI store in V1** (RESOLVED `docs/11` PV-4,
2026-08-27: branch A_PER_CANDLE — Upstox v3 candle response carries per-candle
OI as element 7).

| column | type | notes |
|---|---|---|
| id | bigint PK | |
| instrument_id | bigint FK → instruments(id) `ON DELETE RESTRICT` | FUTURE / OPTION |
| timeframe | enum `timeframe` | per-candle OI |
| ts | timestamptz | **bar-open**, aligned 1:1 to the same-`ts` `ohlcv_bars` row (resolves H2) |
| oi | bigint | contracts |
| provider_oi_change | bigint NULL | stored for cross-check only; **never** used in classification (resolves M7) |
| provider | text | |
| is_final | bool | |
| UNIQUE | `(instrument_id, timeframe, ts, provider)` | |

**`oi_snapshots`** *(RESERVED — branch B fallback; NOT populated in V1 after the
`docs/11` PV-4 resolution to branch A. Kept for the config-only flip if the
Phase-2 smoke test finds intraday per-candle OI unpopulated. Resolves M17.)*

| column | type | notes |
|---|---|---|
| id | bigint PK | |
| instrument_id | bigint FK → instruments(id) `ON DELETE RESTRICT` | FUTURE / OPTION |
| provider | text | |
| snapshot_ts | timestamptz | poll instant, UTC (explicitly **not** a bar-open) |
| oi | bigint | |
| provider_oi_change | bigint NULL | cross-check only |
| day_volume | bigint NULL | |
| instrument_price | numeric(18,4) NULL | the instrument's own price at poll |
| ingested_at | timestamptz | |
| UNIQUE | `(instrument_id, provider, snapshot_ts)` | |
| INDEX | `(instrument_id, snapshot_ts DESC)` | |

Exactly one of `open_interest` / `oi_snapshots` is active in V1. **RESOLVED
`docs/11` PV-4, 2026-08-27: `open_interest` (branch A_PER_CANDLE).**
`oi_snapshots` stays defined for the config-only fallback flip.

### 5.3 Runs (resolves H13, strategic directive 9)

**`analysis_runs`** — **exactly one row per execution cycle**.

| column | type | notes |
|---|---|---|
| id | bigint PK | |
| cycle_seq | bigint UNIQUE NOT NULL | monotonic |
| trigger | enum `run_trigger` | `SCHEDULED / MANUAL / BACKFILL` |
| status | enum `run_status` | `RUNNING / SUCCEEDED / PARTIAL / FAILED` |
| phases_requested | text[] | subset of `INGEST, ANALYZE, SCORE` |
| started_at / finished_at | timestamptz | |
| algo_version / scoring_version | text | |
| config_snapshot | jsonb | full effective engine + scoring + selection config |
| params_hash | text | hash of `config_snapshot` |
| notes | text | |

**`run_phase_status`** — PK `(run_id, phase)`.

| column | type | notes |
|---|---|---|
| run_id | bigint FK → analysis_runs(id) `ON DELETE CASCADE` | |
| phase | enum `run_phase` | |
| status | enum `phase_status` | |
| started_at / finished_at | timestamptz | |
| counts | jsonb | `{ok, insufficient, not_applicable, error, skipped, carried}` |
| detail | jsonb | |

**`run_instrument_status`** — PK `(run_id, instrument_id, phase)`. This is where
per-instrument degradation lives (resolves review N).

| column | type | notes |
|---|---|---|
| run_id | bigint FK → analysis_runs(id) `ON DELETE CASCADE` | |
| instrument_id | bigint FK → instruments(id) `ON DELETE CASCADE` | |
| phase | enum `run_phase` | |
| outcome | enum `instrument_phase_outcome` | `OK / DEGRADED / SKIPPED / ERROR` |
| detail | jsonb | reason, provider error, coverage_ratio, etc. |

### 5.4 Analysis results

**`analysis_results`** — one row per `(run, instrument, analysis_key,
scope_key)`.

| column | type | notes |
|---|---|---|
| id | bigint PK | |
| run_id | bigint FK → analysis_runs(id) `ON DELETE CASCADE` | |
| instrument_id | bigint FK → instruments(id) `ON DELETE RESTRICT` | |
| analysis_key | text `CHECK` in known set | |
| scope | enum `analysis_scope` | `PER_TIMEFRAME / SESSION / SNAPSHOT` (resolves C1) |
| timeframe | enum `timeframe` NULL | **NOT NULL iff `scope = PER_TIMEFRAME`**, and then `∈ {M5, M15, H1, D1}` (`M1` is an ingestion source only) (`CHECK`) |
| session_date | date NULL | NOT NULL iff `scope = SESSION` (`CHECK`) |
| snapshot_ts | timestamptz NULL | NOT NULL iff `scope = SNAPSHOT` (`CHECK`) |
| scope_key | text NOT NULL | generated: `PER_TIMEFRAME:{timeframe}` \| `SESSION:{session_date}` \| `SNAPSHOT:{snapshot_ts ISO}` |
| as_of_ts | timestamptz NOT NULL | bar-open / session-open / poll instant |
| status | enum `analysis_status` | `OK / INSUFFICIENT_DATA / NOT_APPLICABLE / ERROR` |
| result | jsonb | `values` + `aux` + optional small `series` + `warnings` |
| algo_version | text NOT NULL | provenance (resolves M19) |
| params_id | text NOT NULL | |
| params_hash | text NOT NULL | |
| input_window_start / input_window_end | timestamptz NULL | |
| bars_used | int NULL | |
| coverage_ratio | numeric(6,4) NULL | |
| carried | bool NOT NULL default false | recompute guard (resolves M24) |
| carried_from_result_id | bigint NULL FK → analysis_results(id) `ON DELETE SET NULL` | |
| created_at | timestamptz | |
| UNIQUE | `(run_id, instrument_id, analysis_key, scope_key)` | |
| INDEX | `(instrument_id, analysis_key, scope_key, as_of_ts DESC)`, `(run_id)`, `(run_id, status)` | |

A `NOT_APPLICABLE` outcome **is persisted** as a lightweight row (`status =
NOT_APPLICABLE`, `result = {"reason": "..."}`, no `values`). This gives the
`current_analysis_results` projection, the API, and the scoring provenance a
single explicit source for "this analysis does not apply to this instrument
type" (versus a row that is simply absent). Carried rows and `NOT_APPLICABLE`
rows are cheap and do not hold a `series`.

**`market_profile_sessions`** — SESSION-profile cache + recompute-guard anchor
(resolves M17, M24).

| column | type | notes |
|---|---|---|
| id | bigint PK | |
| instrument_id | bigint FK → instruments(id) `ON DELETE CASCADE` | |
| session_date | date | |
| profile_type | enum `profile_type` | `TPO / VOLUME` |
| bin_size | numeric(18,4) | |
| poc / vah / val / ib_high / ib_low / session_high / session_low | numeric(18,4) | |
| profile_shape | enum `market_profile_shape` | |
| is_session_complete | bool | |
| close | numeric(18,4) | session close (nullable; prior-session reference for the event layer) |
| bins | jsonb | `[{price_low, tpo_count?, volume?}]` — pruned to NULL after 180 d (§6) |
| events | jsonb | Market Profile event layer (`docs/14`). Compact `event_result_to_dict` blob — day type, silhouette, MVP event list with lifecycle state, tensions. TPO rows only. Added in migration `0004`. |
| mp_events_version | text | `MP_EVENTS_VERSION` that produced `events`; folded into `params_hash` so a bump forces recompute |
| source_max_ts | timestamptz | max source-bar `ts` folded in — the recompute guard key |
| algo_version / params_hash | text | |
| created_at / updated_at | timestamptz | |
| UNIQUE | `(instrument_id, session_date, profile_type)` | |

### 5.5 Scoring + current projections

**`signal_scores`** — one row per `(run, instrument, timeframe)`.

| column | type | notes |
|---|---|---|
| id | bigint PK | |
| run_id | bigint FK → analysis_runs(id) `ON DELETE CASCADE` | |
| instrument_id | bigint FK → instruments(id) `ON DELETE RESTRICT` | |
| timeframe | enum `timeframe` | user-facing timeframe |
| as_of_ts | timestamptz | |
| composite_score | numeric(12,6) | −100..+100 |
| raw_label | enum `signal_label` | pure function of composite + bands |
| effective_label | enum `signal_label` | after low-confidence clamp (resolves M26) |
| confidence | numeric(12,6) | 0..1 |
| low_confidence | bool | |
| strategy | text | `weighted_v1` |
| scoring_version | text | |
| params_hash | text NOT NULL | scoring config provenance (resolves review XX) |
| weights | jsonb NOT NULL | effective per-factor weights used |
| denom | numeric(18,6) | Σ(wᵢ·cᵢ) — reconstruction aid |
| warnings | jsonb | list[str] |
| explanation | text | deterministic template |
| created_at | timestamptz | |
| UNIQUE | `(run_id, instrument_id, timeframe)` | |
| INDEX | `(instrument_id, timeframe, as_of_ts DESC)`, `(run_id)` | |

**`score_factors`** — per-factor breakdown.

| column | type | notes |
|---|---|---|
| id | bigint PK | |
| signal_score_id | bigint FK → signal_scores(id) `ON DELETE CASCADE` | |
| analysis_result_id | bigint NULL FK → analysis_results(id) `ON DELETE SET NULL` | exact provenance (resolves M1) |
| analysis_key | text | |
| scope | enum `analysis_scope` | |
| raw_values | jsonb | the values the sub-score read |
| sub_score | numeric(12,6) | −100..+100 |
| confidence | numeric(12,6) | 0..1 |
| weight | numeric(12,6) | effective weight |
| contribution | numeric(12,6) | `wᵢ·cᵢ·sᵢ / denom`; `Σ contribution = composite_score` (resolves M5) |
| reason | text | short templated reason |
| rationale | jsonb | machine-readable (AI-narration seam) |

**`current_signal_scores`** — hot read projection (resolves H8). PK
`(instrument_id, timeframe)`.

| column | type | notes |
|---|---|---|
| instrument_id | bigint FK → instruments(id) `ON DELETE CASCADE` | |
| timeframe | enum `timeframe` | |
| signal_score_id | bigint FK → signal_scores(id) `ON DELETE CASCADE` | |
| run_id | bigint | |
| composite_score / confidence | numeric(12,6) | |
| raw_label / effective_label | enum `signal_label` | |
| low_confidence | bool | |
| as_of_ts | timestamptz | |
| delta_vs_previous | numeric(12,6) NULL | composite delta vs the prior run's score for the same key |
| warnings | jsonb | |
| updated_at | timestamptz | |

**`current_analysis_results`** — hot read projection. PK
`(instrument_id, analysis_key, scope_ref)`.

`scope_ref` is the **collapsed** scope key so the projection holds exactly one
"latest" row per logical slot: `PER_TIMEFRAME:{timeframe}` |
`SESSION` | `SNAPSHOT`. (The full `analysis_results.scope_key`, which includes
`session_date` / `snapshot_ts`, is retained only on the history table where each
run writes its own row.)

| column | type | notes |
|---|---|---|
| instrument_id | bigint FK → instruments(id) `ON DELETE CASCADE` | |
| analysis_key | text | |
| scope_ref | text | `PER_TIMEFRAME:{timeframe}` \| `SESSION` \| `SNAPSHOT` |
| scope | enum `analysis_scope` | |
| timeframe | enum `timeframe` NULL | set iff `scope = PER_TIMEFRAME` |
| session_date | date NULL | set iff `scope = SESSION` (the latest profiled session) |
| snapshot_ts | timestamptz NULL | set iff `scope = SNAPSHOT` (the latest poll) |
| analysis_result_id | bigint FK → analysis_results(id) `ON DELETE CASCADE` | latest result row |
| status | enum `analysis_status` | incl. `NOT_APPLICABLE` |
| as_of_ts | timestamptz | |
| algo_version / params_hash | text | |
| carried | bool | true if the latest result was carried (recompute guard) |
| summary | jsonb | `values` + `aux` (+ `reason` for `NOT_APPLICABLE`); no large `series` |
| updated_at | timestamptz | |

A `NOT_APPLICABLE` analysis is projected here too (so the API and the frontend
have a single source for the collapsed panel and its reason).

Projections are caches: fully rebuildable from history via a
`rebuild-projections` command. They are **not** a source of truth. The worker
upserts them at the end of the ANALYZE / SCORE phases.

### 5.6 Operations

**`ingestion_watermarks`** — PK adds `provider` (resolves M18).

| column | type | notes |
|---|---|---|
| id | bigint PK | |
| instrument_id | bigint FK → instruments(id) `ON DELETE RESTRICT` | |
| timeframe | enum `timeframe` | |
| data_kind | enum `data_kind` | `OHLCV / OI` |
| provider | text | |
| last_complete_ts | timestamptz | last finalized bar/period pulled |
| last_verified_ts | timestamptz | last bar re-verified by the repair pass (resolves M16) |
| last_attempt_at | timestamptz | |
| last_status | enum `watermark_status` | `OK / ERROR / RATE_LIMITED / AUTH_FAILED` |
| detail | jsonb | |
| UNIQUE | `(instrument_id, timeframe, data_kind, provider)` | |

### 5.7 Astro cross-check side tables (migration `0002`, spec: `docs/13`)

Optional research tables, **no FK into the market schema**, joined to market data
by `as_of_date`. `body` / `graha` are `TEXT` + `CHECK` (no new enum types).

- **`astro_positions`** — one row per `(as_of_date, body)` (9 grahas incl.
  Rahu/Ketu): sidereal (Lahiri) `longitude`, `latitude`, `speed_longitude`,
  `retrograde`, `rashi`(+index), `degree`, `nakshatra`(+index), `pada`,
  `nakshatra_lord`, `dignity`, `ayanamsha`, `source`. `as_of_ts` = 03:30 UTC.
- **`astro_shadbala`** — one row per `(as_of_date, graha)` (7 planets): the six
  balas (virupa), `total_virupa` / `total_rupa`, `required_rupa`,
  `strength_ratio`, `rank`, `ishta_phala` / `kashta_phala`, `graha_yuddha`,
  `components` jsonb (flat breakdown).

Populated by `analytical-astro build` (offline, Swiss Ephemeris). Not read by the
engine, scoring, or the API.

### 5.8 Index-constituent weights side table (migration `0005`, spec: `docs/15`)

- **`index_weights`** — seeded, owner-maintained free-float index weights. One
  row per `(index_key, symbol, effective_date)` (unique): `index_key` = the
  index `instruments.contract_key` (`TEXT`, no FK — constituents are not
  instruments), `name`, `sector`, `weight_pct` numeric(9,6), optional
  `provider` / `provider_symbol` for quote-on-read, `source` (`seed`). Index on
  `(index_key, effective_date)`. Loaded by `analytical-index-weights load` from
  the NSE / niftyindices factsheet each rebalance. Not ingested, not read by the
  engine or scoring; the constituent read API (`docs/07` §4.14) joins it to a
  quote-on-read snapshot.

## 6. Retention (V1 defaults, configurable; strategic directive 22)

| Data | Retention |
|---|---|
| `ohlcv_bars` M1 | 10 days (aggregation source only) |
| `ohlcv_bars` M5 | 180 days |
| `ohlcv_bars` M15 / H1 | 400 days |
| `ohlcv_bars` D1 | **kept indefinitely** (200-SMA on the INDEX) |
| `open_interest` / `oi_snapshots` | 180 days |
| `analysis_results` (incl. small `series`) | 400 days |
| `market_profile_sessions` scalar rows | 400 days; `bins` jsonb nulled after 180 days |
| `signal_scores` / `score_factors` | 400 days (explainability trail) |
| `analysis_runs` / `run_phase_status` / `run_instrument_status` | 400 days |
| `current_*` projections | not time-pruned (one row per key) |

All time-window deletes → convert cleanly to partition drops. Intraday
backtesting depth is bounded by these windows; deeper history needs a future
archival job.

## 7. Sizing note

Default universe ≈ 94 instruments, fixed per session. Per cycle: ≈ 1 880
PER_TIMEFRAME engine calls (most short-circuited by NOT_APPLICABLE / recompute
guard) and ≈ 376 score rows. At ~75 cycles/day and 400-day retention,
`analysis_results` is the largest table at low-tens of millions of rows with
small JSONB payloads (`series` arrays are bounded; Market Profile `bins` live in
`market_profile_sessions`, pruned at 180 days). Hot reads never touch it — they
hit `current_*`. Plain PostgreSQL is sufficient for V1; partitioning stays a
later, migration-only optimisation.
