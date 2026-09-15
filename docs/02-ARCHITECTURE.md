# 02 — Architecture

## 1. Style

**Modular monolith.** One deployable backend process (plus an optional worker
process running the same codebase), one frontend SPA, one PostgreSQL database.
No microservices, no message broker, no Kafka, no Kubernetes, no ML
infrastructure in V1.

Modularity is enforced by package boundaries and dependency direction, not
network calls.

## 2. Dependency rule (the hard constraint)

```
frontend ──HTTP──> app (FastAPI)
                     ├── depends on ──> analytical_core   (pure: enums, analysis, scoring)
                     ├── depends on ──> persistence layer (SQLAlchemy models, repos, projections)
                     ├── depends on ──> provider layer    (protocol + Upstox adapter + auth)
                     └── depends on ──> ingestion + worker

analytical_core depends on: nothing in app/. No FastAPI, no SQLAlchemy, no httpx,
no file/network IO. Standard library + numpy only.
```

If a change makes `analytical_core` import from `app/`, the change is wrong.

## 3. Modules

### 3.1 `analytical_core` (pure)
- `enums` — the authoritative enum contract (`docs/12`).
- `series` — `OHLCVSeries`, `OpenInterestSeries`, `SessionSpec` (`docs/04` §3.1).
- `indicators` — RSI, Bollinger, EMA (+ shared ATR helper), SMA / Golden Cross,
  Volume, Open Interest.
- `market_profile` — period model, bucketing, TPO builder, Volume Profile
  builder, shared value-area / POC algorithm, shape classifier (`docs/05` §10).
- `scoring` — sub-score functions, aggregation strategies, `CompositeResult`
  assembly, deterministic `explanation` templater (`docs/06`).
- `versioning` — `ALGO_VERSION`, `SCORING_VERSION`.
- `params` — helper that computes `params_id` / `params_hash` from an effective
  parameter object (`docs/04` §5, resolves M19).
- No knowledge of Upstox, of the DB, or of specific instruments. Inputs are
  arrays + parameter objects + (for scoring) a `ScoringInput` carrying
  `instrument_type` and `expected_analyses` **as data**.

### 3.2 Provider layer (`app/providers/`)
- `base.py`:
  - `MarketDataProvider` protocol — `list_instruments()`,
    `get_ohlcv(provider_symbol, timeframe, start, end)`,
    `get_recent_ohlcv(provider_symbol, timeframe)`,
    `get_oi_snapshot(provider_symbols)` **and/or**
    `get_oi_series(provider_symbol, timeframe, start, end)` (per `docs/11` PV-4
    branch), plus a `capabilities()` descriptor
    (native intervals, historical depth, whether per-candle OI, rate limits).
  - `AuthProvider` protocol — `is_valid()`, `refresh_if_possible()`,
    `state() -> provider_auth_state`. Resolves C2: the worker checks auth state
    before a cycle; on `EXPIRED` it does not crash — the cycle marks
    provider-dependent instruments `SKIPPED` and `/health/ready` reports it.
- `upstox/` — the only concrete implementation in V1. All Upstox auth, endpoint
  URLs, payload mapping, pagination, retry/backoff, rate-limit handling. **No
  Upstox capability is coded until the matching `docs/11` item is `CONFIRMED` or
  `ACCEPTED_FALLBACK`.**
  - **Startup gate (mechanical, resolves the "enforced by judgment" gap):** the
    adapter reads `docs/11-provider-validation.status.yaml` at construction and
    **refuses every live call** (raises `ProviderValidationGateError`) while any
    `blocks_phase_2` item (PV-1…PV-7) is `OPEN`. This holds for local runs and
    the worker alike; only `MockProvider` is usable until the gate clears. The
    same file backs the `provider-validation-gate` CI job (`docs/09` §4) and the
    `docs/10` Phase 1.5 exit.
- `registry.py` — resolves the single active provider from config. A documented
  "preferred source order" exists but has one entry in V1 (M18).
- `MockProvider` (in tests) — implements the same protocols from recorded
  fixtures; the provider contract test suite runs against any implementation.

### 3.3 Instrument registry (`app/instruments/`)
- Owns `instruments`, `provider_instrument_map`, `contract_key` generation.
- `selection.py` — futures rollover + session-stable option universe
  (`docs/04` §2.3). Runs at the first cycle of each trading day.

### 3.4 Ingestion (`app/ingestion/`)
- Pulls bars / OI via the provider layer; normalises to **bar-open UTC**
  (`docs/05` §3.2); upserts `ohlcv_bars` / (`open_interest` | `oi_snapshots`).
- **Current-day bars are live.** The Upstox historical endpoint has nothing for
  the in-progress trading day; the candle adapter (`app/providers/upstox/
  candles.py`) fetches the current IST trading day from the **intraday** endpoint
  (`docs/11` PV-2) and prior days from **historical**, merging them. The last
  intraday bar is `is_final=False`, so the watermark stops just short of it and
  the repair pass re-verifies it next cycle.
- `aggregation.py` — if the provider does not serve session-anchored M5/M15/H1
  natively (`docs/11` PV-2), ingest M1 and aggregate to the session-anchored
  grid (`docs/05` §3.3). **A target period with zero child M1 bars is not
  emitted** (no fabrication — resolves M23).
- `ingestion_watermarks` — per `(instrument, timeframe, data_kind, provider)`;
  incremental pulls always re-fetch the forming tail; a periodic "re-verify last
  K finalized bars" pass repairs provider revisions (resolves M16).
- Backfill mode (historical range) vs incremental mode (since watermark).
- **Streaming (`app/ingestion/stream.py`) — optional, bounded** (decision 3, lock
  lifted 2026-08-30; built S1–S4). A separate long-running process
  (`analytical-worker stream` / the `streamer` Compose profile / an in-process
  daemon thread when `run_stream_in_process`), **session-gated** by the same
  `market_calendar` window as the scheduler: authenticates, opens the provider's
  WebSocket feed (Upstox Market Data Feed v3 — `docs/11` §5.1;
  `app/providers/upstox/feed.py`), subscribes to the **tracked universe** in
  `full` mode, and feeds ticks (LTP + cumulative volume + OI) into a **pure
  M1-from-ticks builder** (`analytical_core.streaming`
  — session-grid minute buckets: open=first, hi/lo, close=last,
  `volume = cum_volume − minute_start_cum`, OI=last; a zero-tick minute emits no
  row). Closed minutes upsert `ohlcv_bars` / `open_interest` under the same
  `bar_identity`; the forming minute is written non-final and flipped `is_final`
  after `finalize_grace_seconds`. **Scope limit:** the stream only supplies the
  forming M1 + live OI — history, backfill and disconnect gap-fill stay on REST
  (on reconnect, REST backfills `[last_stream_bar, now]`). The deterministic
  engine is untouched; it still runs on the periodic cycle over whatever is in
  the DB.

### 3.5 Analysis orchestration (`app/analysis/`)
- For each tracked instrument: resolve applicable analyses (`docs/04` §4), load
  the required history, build `analytical_core` inputs, call the engine, write
  `analysis_results` (with full provenance columns) under the **current run**.
- **Recompute guard (resolves M24):** if the latest input bar `ts` + `is_final`
  and the effective `params_hash` are unchanged since the last result for
  `(instrument, analysis_key, scope_key)`, skip recompute and write a light
  `carried = true` row referencing the prior result. Market Profile uses the
  session's max source-bar timestamp for the same guard.
- Updates `current_analysis_results` at the end of the ANALYZE phase.

### 3.6 Scoring orchestration (`app/scoring/`)
- For each `(tracked instrument, user-facing timeframe)`: gather the latest
  `analysis_results` **from the same run** (PER_TIMEFRAME factors for that
  timeframe, plus the session `market_profile` and the snapshot `open_interest`,
  each tagged with its scope), build a `ScoringInput` (computing
  `expected_analyses` from `instrument_type`), call `analytical_core.scoring`,
  write `signal_scores` + `score_factors` under the current run.
- Updates `current_signal_scores` at the end of the SCORE phase.

### 3.7 Worker (`app/worker/`)
- Drives one **execution cycle** = one `analysis_runs` row covering INGEST →
  ANALYZE → SCORE (resolves H13, strategic directive 9).
- Writes `run_phase_status` per phase and `run_instrument_status` per
  `(instrument, phase)` outcome (`OK / DEGRADED / SKIPPED / ERROR`).
- **Single-flight:** at most one cycle at a time (Postgres advisory lock). If a
  scheduled tick fires while a cycle runs, the tick is skipped and logged. A
  `POST /runs` during a running cycle returns `409` + `Retry-After`.
- **V1 default:** in-process scheduler (APScheduler `BackgroundScheduler`,
  `app/worker/scheduler.py`) started from the API lifespan when
  `RUN_WORKER_IN_PROCESS=true`. **Alternative:** same image, `analytical-worker
  serve` entrypoint, as a separate Compose service. Identical job body
  (`run_scheduled_cycle`).
- **Tick interval** `CYCLE_INTERVAL_SECONDS` (default 180). The job is
  `max_instances=1`, `coalesce=True`, `misfire_grace_time=30` — a tick that
  fires while the previous cycle still runs is dropped (belt-and-braces with the
  advisory lock, which also covers a separate `worker` process).
- **Session gate** (`app/worker/calendar_gate.py`): when
  `SCHEDULER_SESSION_ONLY=true` (default) a tick only runs a cycle from
  `SCHEDULER_WARMUP_SECONDS` before the `market_calendar` session open to
  `SCHEDULER_COOLDOWN_SECONDS` after its close, on a trading day for
  `SCHEDULER_SEGMENT`; otherwise the tick logs `skipped` and does nothing. Set
  the flag false to tick around the clock (dev against a stub/mock provider).
  `scheduled` cycles carry `run_trigger = SCHEDULED`.
- `analytical-worker serve [--run-now]` blocks until SIGINT/SIGTERM, then
  `scheduler.shutdown(wait=True)`. `--run-now` (or `SCHEDULER_RUN_ON_START=true`)
  fires one cycle immediately on start.
- Job interface written so a real broker (Arq/RQ/Celery) can replace it later
  without touching job bodies.
- **`run-completed` hook** (`app/worker/hooks.py`): a process-local registry
  fired once per finished cycle with the `CycleResult`. V1 registers one sink (a
  structured-log line); the alerts seam (docs/10) subscribes here later without
  touching the cycle body. A raising hook is isolated and never breaks the cycle.
- **Async `POST /runs`:** the API writes the run row via
  `create_pending_run`, returns `202` + `Location`, and executes
  `run_cycle(run_id=…)` in a FastAPI background task under the same advisory lock.
- **Side timer jobs on the same scheduler** — separate from the engine cycle,
  each `max_instances=1` / `coalesce=True`, guarded so a raise only logs:
  - `analytical-astro-catchup` (`docs/13` §5.4) — fill missing weekday astro
    rows; every `ASTRO_CATCHUP_INTERVAL_SECONDS` (6 h).
  - `analytical-universe-roll` (`docs/04` §2.3) — re-download the Upstox
    instrument master and re-roll the tracked option universe against the
    current spot per underlying (keeps strikes centred on the money, picks up
    new weekly expiries; idempotent). Every `UNIVERSE_ROLL_INTERVAL_SECONDS`
    (6 h) **and once on worker start**; toggle `UNIVERSE_DAILY_ROLL`. The next
    engine cycle ingests any newly-tracked contracts.
  - `analytical-db-backup` — nightly `pg_dump -Fc` of `DATABASE_URL` to
    `DB_BACKUP_DIR` (default `deploy/backups/`, CWD-relative), keeping the
    newest `DB_BACKUP_KEEP` (14). `pg_dump` is taken from `PG_DUMP_PATH` /
    `PATH` / a common Windows PostgreSQL install path; password via `PGPASSWORD`,
    never argv. Every `DB_BACKUP_INTERVAL_SECONDS` (24 h); toggle
    `DB_BACKUP_ENABLED`. Also runnable by hand: `python -m app.ops.backup`.

### 3.8 API layer (`app/api/`)
- FastAPI routers under `/api/v1`. Thin: validate → service → serialise.
- **Read endpoints hit the `current_*` projections** (`docs/03` §5.5, resolves
  H8); historical endpoints hit `signal_scores` / `analysis_results`.
- No analysis or scoring math in the API layer.

### 3.9 Frontend — see `docs/08`.

## 4. Data flow (one cycle = one run)

```
scheduler tick  ->  acquire advisory lock  ->  create analysis_runs row (status RUNNING, cycle_seq++)
  phase INGEST:
     (daily-first-cycle only) run instrument universe fixing (docs/04 §2.3)
     for each tracked instrument (bounded concurrency, docs/02 §6.7):
        provider -> normalize to bar-open UTC -> upsert ohlcv_bars
        provider -> upsert open_interest | oi_snapshots
        update ingestion_watermarks ; record run_instrument_status(INGEST, ...)
     write run_phase_status(INGEST)
  phase ANALYZE:
     for each tracked instrument, for each applicable (analysis, scope):
        recompute-guard check -> engine call OR carry
        write analysis_results (+ provenance) under this run_id
        record run_instrument_status(ANALYZE, ...)
     upsert current_analysis_results ; write run_phase_status(ANALYZE)
  phase SCORE:
     for each (tracked instrument, user-facing timeframe):
        gather same-run analysis_results -> ScoringInput -> analytical_core.scoring
        write signal_scores + score_factors under this run_id
        record run_instrument_status(SCORE, ...)
     upsert current_signal_scores (with delta_vs_previous)
     write run_phase_status(SCORE)
  finalize: analysis_runs.status = SUCCEEDED | PARTIAL | FAILED ; release lock ; run-completed hook

API read path:  frontend -> /api/v1/... -> current_* projections (hot) or history tables
```

## 5. Deployment (V1)

`deploy/docker-compose.yml` (all ports bound to `127.0.0.1`):

| Service | Image | Notes |
|---|---|---|
| `db` | `postgres:16` (pinned) | named volume `db_data`; `pg_isready` healthcheck |
| `backend` | `backend.Dockerfile` | `alembic upgrade head` → `python -m app.db.seed` (idempotent) → uvicorn; `/api/v1/health` healthcheck |
| `worker` *(profile `worker`)* | same image | `analytical-worker serve` (scheduler loop); waits for `backend` healthy. Alternative: omit it and set `ANALYTICAL_RUN_WORKER_IN_PROCESS=true` so the backend lifespan runs the scheduler in-process |
| `frontend` | `frontend.Dockerfile` | multi-stage `vite build` → nginx; nginx proxies `/api/` → `backend:8000` |

- `deploy/backend.Dockerfile` installs deps + the two first-party packages from
  `backend/pyproject.toml` (`pip install ./backend`) so the image never drifts
  from the pinned manifest. Root `.dockerignore` keeps the context lean.
- Config via env + `deploy/.env` (git-ignored; `deploy/.env.example` is the
  template), validated by the typed `pydantic-settings` object (`env_prefix
  ANALYTICAL_`).
- Upstox credentials/token via env in V1; `provider_credentials` table reserved
  and made concrete once `docs/11` PV-1 closes.

## 6. Cross-cutting concerns

### 6.1 Configuration
- One typed settings object (env / `.env`) + an `app_settings` table for
  runtime-editable values (cadence, Market Profile params, scoring
  weights/bands, universe-selection params).
- **Engine parameters are always passed in explicitly** from `app/` config into
  `analytical_core`; the engine has defaults but never reads config. Each engine
  call also receives the effective parameter object from which `params_id` /
  `params_hash` are derived and stored on the result (M19).

### 6.2 Time (resolves H2, H11)
- All persisted and computed timestamps are **tz-aware UTC, bar-open**.
- IST = `Asia/Kolkata`, fixed `UTC+05:30`, no DST. Session boundaries are
  defined in IST (`docs/05` §3) and converted once.
- `market_calendar` (with a `segment` dimension) drives trading-day / session
  hours / "market open now" logic, including shortened `NORMAL` sessions.

### 6.3 Logging & observability
- Structured logging (structlog, proposed). Every log line in a cycle carries
  `cycle_seq` / `run_id`. Each analysis / score row references its run.
- `/api/v1/health` (liveness) and `/api/v1/health/ready` (DB reachable,
  `provider_auth`, `calendar_seeded_until`, `last_cycle_seq`,
  `last_successful_cycle_age_seconds`, `worker_running`).
- Prometheus metrics endpoint reserved; not implemented in V1.

### 6.4 Error handling
- Provider errors (rate limit, auth, gap) are caught in the provider/ingestion
  layer, recorded on `run_instrument_status` (`DEGRADED` / `SKIPPED` / `ERROR`),
  and do **not** crash the cycle.
- A phase that cannot run at all → `run_phase_status = FAILED`,
  `analysis_runs.status = FAILED`.
- Some instruments failing while the cycle completes → `PARTIAL`.
- API errors: `application/problem+json` (`docs/07` §3).

### 6.5 Backtesting seam (strategic directive 22 — reserved, not built)
- `analytical_core` is pure and window-driven; `analysis_runs.config_snapshot` +
  per-row `params_hash` + `input_window_*` + `market_profile_sessions.
  source_max_ts` give the provenance a future backtest needs.
- **Retention (`docs/03` §6) bounds intraday backtest depth.** A longer-history
  archival job is explicitly future work. No `backtest_*` code, tables, or
  endpoints in V1.

### 6.6 Auth seam (resolves H12)
- Every request passes `get_current_principal`; V1 returns a fixed `owner`
  principal, optionally gated by a static `LOCAL_API_TOKEN` bearer.
- V1 has **global** config (`app_settings`) and a **global** tracked universe.
  There are **no** `watchlists` / `scoring_profiles` tables in V1, and the API
  has no per-user resources. The earlier "owner-scoped resources" language is
  removed.
- Adding multi-user later = swap the dependency + add `users` auth columns +
  add `watchlists` / `scoring_profiles` tables scoped by `owner_id`. Domain
  tables (`instruments`, `ohlcv_bars`, `analysis_results`, …) stay global.

### 6.7 Throughput & concurrency budget (resolves M24, strategic directive 21)

Worked estimate for the default universe (N = 5 strike window):

| Component | Count | Notes |
|---|---|---|
| INDEX | 2 | |
| FUTURE | 4 | 2 underlyings × (near + next) |
| OPTION | ≈ 88 | 2 underlyings × 2 expiries × (2·5+1) strikes × 2 (CE/PE) |
| **Tracked instruments** | **≈ 94** | fixed per session |
| Ingest fetches / cycle | ≈ 94 M1 incremental-tail fetches (OI rides along in the same v3 candle response under branch A) + periodic daily/backfill | bounded by provider limits (`docs/11` PV-5) |
| (instrument, user timeframe) units | ≈ 94 × 4 = 376 | |
| Engine calls / cycle (PER_TIMEFRAME) | ≈ 376 × 5 ≈ 1 880 | RSI, Bollinger, EMA, GC, Volume; many short-circuit via NOT_APPLICABLE / recompute-guard |
| Market Profile builds / cycle | ≤ 94 × 2 profile types, **only when the session's M5 input changed** | recompute guard |
| Score computations / cycle | ≈ 376 | pure, in-memory |

**Confirmed provider limits (`docs/11` PV-5, 2026-08-27):** Upstox "Other
Standard APIs" (Historical + Intraday Candle) = **50 req/s, 500 req/min,
2000 req/30 min**, per-API per-user; no daily quota. Binding constraint is
2000/30 min (≈ 1.1 req/s sustained). At ≈ 94 M1 fetches/cycle and
`cycle_interval_seconds = 180` → ≈ 940 requests / 30 min — under budget with
headroom.

Controls:
- `PROVIDER_CONCURRENCY` (default **4**), `PROVIDER_MAX_RPS` (default **8**,
  under the 500/min ≈ 8.3/s ceiling), and a **rolling `PROVIDER_30MIN_BUDGET`
  (default 1800**, 10% headroom under 2000). Cycle-budget rule:
  `requests_per_cycle × (1800 / cycle_interval_seconds) ≤ PROVIDER_30MIN_BUDGET`.
- Exponential backoff on a throttle response (expected HTTP 429 — confirm exact
  status on the first authenticated call); `ingestion_watermarks.last_status =
  RATE_LIMITED`, instrument `DEGRADED` for the cycle.
- `ANALYZE_CONCURRENCY` (default = CPU count) for the pure engine calls.
- Recompute guard so unchanged inputs cost ~nothing.
- Market Profile computed at most once per new M5 source bar per instrument.
- **Cycle overrun policy:** if a cycle exceeds the configured cadence, the next
  scheduled tick is skipped (single-flight); the overrun is logged and surfaced
  on `/health/ready`.
- A cycle-timing test at synthetic universe scale is a Phase 6 exit gate
  (`docs/09` §2.7, `docs/10` Phase 6).

## 7. Reserved seams for future work (decision 14)

| Capability | Seam already in V1 |
|---|---|
| Backtesting | Pure engine + per-row provenance (`params_hash`, `input_window_*`) + `config_snapshot`; retention caveat noted. Not built. |
| Charts | Analysis `series` payloads + a dedicated per-bar series endpoint (`docs/07` §4.4); `frontend/src/charts/` reserved. |
| Alerts | `run-completed` hook + persisted `score_factors`. |
| More providers | `MarketDataProvider` / `AuthProvider` protocols + registry + `provider_instrument_map` + `provider` on watermarks. |
| More instruments / segments | Instrument-type abstraction + applicability matrix + `market_calendar.segment`. |
| Machine learning | Normalised factor rows + `params_hash` per run = feature-store seed; aggregation is a strategy interface. |
| AI explanations | Deterministic `explanation` string + `score_factors.rationale` dicts are the narration seam. |
| Mobile app | Versioned REST API + generated schema; no server-rendered HTML. |
| Multi-user auth | `get_current_principal` swap + `users` auth columns + user-scoped tables. |
| Time-series optimisation | Partition-ready schema (`docs/03` §2), verified by a structural test. |

## 8. Open architectural decisions (defaults chosen; revisit at the stated gate)

| Topic | Default | Gate |
|---|---|---|
| Python dependency manager | `uv` | Phase 1 |
| Scheduler library | APScheduler in-process | Phase 1 |
| Numeric library in engine | `numpy` (pinned); `math.fsum` for session-length sums | Phase 3 |
| Logging | structlog | Phase 1 |
| Frontend static serving | nginx in the `frontend` image | Phase 7 |
| Local API protection | static `LOCAL_API_TOKEN` bearer | Phase 1 |
| **OI scope (SNAPSHOT vs PER_TIMEFRAME)** | **PER_TIMEFRAME (branch A_PER_CANDLE)** — RESOLVED `docs/11` PV-4, 2026-08-27 (Upstox v3 candle response carries per-candle OI). `open_interest` table active; `oi_snapshots` reserved. Phase-2 entry must verify intraday OI is populated; else config-flip to `B_SNAPSHOT`. |
| **M5/M15/H1 native vs aggregate-from-M1** | **AGGREGATE_FROM_M1** — RESOLVED `docs/11` PV-2, 2026-08-27 (1m native from Jan 2022; H1 session-anchoring undocumented). D1 native. |
| **Token refresh unattended vs daily manual** | **daily manual** — RESOLVED `docs/11` PV-1, 2026-08-27 (no refresh token; fixed 03:30 IST daily expiry; SEBI-mandated daily login). `extended_token` = a Phase-2 evaluation item. |
| `M1` bars persisted vs transient | **persisted, 10-day retention** — RESOLVED `docs/11` PV-2, 2026-08-27 (`docs/03` §6). |

The `docs/11` gate is enforced mechanically (§3.2 adapter startup guard +
`provider-validation-gate` CI job + `docs/10` Phase 1.5 exit), not by review
judgment. **Phase 1.5 PASSED 2026-08-27 — all PV rows CONFIRMED or
ACCEPTED_FALLBACK (`docs/11` §4).**

### 8.1 Confirmed Phase 0 defaults (owner-approved 2026-08-27)

Seeded into `app_settings` (`docs/03` §3) and the engine defaults; editable at
runtime via `/config`.

| Key | Value |
|---|---|
| `cycle_interval_seconds` | `180` |
| `finalize_grace_seconds` | `90` |
| `option_selection.strike_window` (ATM ± N) | `5` |
| `option_selection.max_expiries` | `2` |
| `option_selection.rebuild_trigger` (steps) | `8` |
| `option_selection.strike_step.NIFTY` / `.BANKNIFTY` | `50` / `100` |
| `scoring.min_confidence` | `0.35` |
| `scoring.weights` | GC 1.5 · OI 1.25 · EMA 1.0 · BB 1.0 · RSI 1.0 · MP 1.0 · Vol 0.75 |
| retention: `ohlcv_bars` M5 / (M15·H1) / results·scores | `180d` / `400d` / `400d` |
