# 10 — Roadmap

Phased delivery. Each phase has explicit **entry** and **exit** criteria. Do not
begin a phase until its entry criteria are approved by the owner. Nothing in
Phases 1+ starts until Phase 0 is signed off.

---

## Phase 0 — Specification (current; revised)

**Goal:** agreed, internally consistent written spec. No code, no dependencies,
no migrations.

**Deliverables:** `.claude/CLAUDE.md`, `docs/01`–`docs/12`,
`docs/11-provider-validation.status.yaml`, `README.md`, `.gitignore`.

**Exit criteria:**
- Owner has reviewed all 12 docs.
- The revised consistency review returns **READY** (or only accepted LOW
  items). ✅ (returned READY; only accepted LOW items remain)
- `docs/02` §8 open decisions resolved or explicitly deferred with a chosen
  default. ✅
- Confirmed Phase 0 defaults recorded in `docs/02` §8.1 and seeded into
  `app_settings` in Phase 1: ✅ (owner-approved 2026-08-27) —
  `cycle_interval_seconds=180`, `finalize_grace_seconds=90`,
  `strike_window=5`, `max_expiries=2`, `rebuild_trigger=8`,
  `strike_step` 50/100, `scoring.min_confidence=0.35`, default weights
  (GC 1.5 / OI 1.25 / EMA 1.0 / BB 1.0 / RSI 1.0 / MP 1.0 / Vol 0.75),
  retention 180d / 400d / 400d.
- `docs/11-provider-validation.status.yaml` exists with all rows `OPEN` (the
  starting state; resolved during Phase 1.5).

---

## Phase 1 — Foundations

**Entry:** Phase 0 exit met.

**Scope:**
- Repo scaffold (`backend/analytical_core`, `backend/app`, `frontend/`,
  `deploy/`).
- Python + JS tooling chosen and pinned — **first dependency-install approval
  gate**.
- `analytical_core.enums` (`docs/12`) + `analytical_core.versioning` +
  `analytical_core.params` (`params_hash` helper).
- `deploy/docker-compose.yml` (`db`, `backend`, `frontend` skeletons).
- Full PostgreSQL schema from `docs/03` as Alembic migrations, including: the
  **scope model** on `analysis_results`, the **run model**
  (`analysis_runs` + `run_phase_status` + `run_instrument_status`), the
  **`current_*` projections**, provenance columns, `oi_snapshots` +
  `open_interest`, `market_profile_sessions`, `market_calendar` with `segment`.
  Enum types generated from `analytical_core.enums`.
- Seed: `owner` user; `market_calendar` for the **current + next** calendar
  year; `app_settings` from the `docs/02` §8.1 confirmed defaults.
  `refresh-calendar` and `rebuild-projections` commands.
- Typed settings object; `/health` + `/health/ready`.
- `app/providers/upstox/` **stub only** (allow-list per `docs/09` §2.12):
  `__init__.py`, `stub.py`, `capabilities.py`, `gate.py` (the startup guard that
  reads `docs/11-provider-validation.status.yaml`).
- `provider-validation-gate` CI job + its test (`docs/09` §2.12) — green with
  all PV rows `OPEN` because only the stub set exists.
- CI: `backend-lint`, `enum-contract`, `provider-validation-gate`, migrate
  up/down, empty test run, image build.

**Exit:**
- `docker compose up` brings up all three services; health endpoints green.
- Migrations run clean both directions in CI; `enum-contract` passes.
- Partition-readiness structural test passes.
- `provider-validation-gate` passes; constructing the Upstox adapter raises
  `ProviderValidationGateError` (guard verified).
- No business logic yet.

---

## Phase 1.5 — Provider Validation Gate (`docs/11`)

**Entry:** Phase 1 exit; access to Upstox documentation / sandbox.

**Scope:** resolve every `blocks_phase_2` item in
`docs/11-provider-validation.status.yaml` (PV-1…PV-7) to `CONFIRMED` (with
`evidence`) or `ACCEPTED_FALLBACK` (with a resolvable `fallback_ref`), editing
the `.yaml` and the mirrored `docs/11` §1 table. In particular decide and
record:
- PV-1 token lifecycle → unattended refresh (`CONFIRMED`), or the daily-manual
  fallback (`ACCEPTED_FALLBACK`).
- PV-2 `branch` = `NATIVE` or `AGGREGATE_FROM_M1`.
- PV-4 `branch` = `A_PER_CANDLE` or `B_SNAPSHOT` → sets `has_intraday_oi`
  defaults and the OI analysis `scope`.
- PV-3 historical depth → INDEX daily-seed plan for Golden Cross.
- PV-5 rate limits → concrete `PROVIDER_CONCURRENCY` / rate-limiter values in
  `docs/02` §6.7.
- PV-6 instrument master fields → `expiry_kind` source, strike step source.

**Exit (mechanical):** the `provider-validation-gate` CI job is **green** —
i.e. no `blocks_phase_2` row is `OPEN`, every resolved row is well-formed, and
the `docs/11` §1 table matches the `.yaml`. `docs/02`, `docs/03`, `docs/04`,
`docs/05` cross-references updated with the chosen branches. **The Upstox
adapter's startup guard keeps refusing live calls, and Phase 2 build does not
begin, until this job is green.**

**STATUS: PASSED 2026-08-27.** All eight PV rows resolved (evidence in `docs/11`
§4). Resolved: PV-1 `ACCEPTED_FALLBACK` (daily-manual-token); PV-2
`ACCEPTED_FALLBACK` / `branch: AGGREGATE_FROM_M1`; PV-3 `CONFIRMED`; PV-4
`CONFIRMED` / `branch: A_PER_CANDLE`; PV-5 `CONFIRMED`; PV-6 `CONFIRMED`; PV-7
`CONFIRMED`; PV-8 `ACCEPTED_FALLBACK` (deferred). Cross-references updated in
`docs/02` §6.7 / §8, this file, and `docs/11` §4.

**Phase 1.5 did NOT unlock Phase 2 coding.** The gate being green is a
*precondition* for Phase 2; Phase 2 begins only on a separate explicit
instruction.

---

## Phase 2 — Provider abstraction + ingestion

**Entry:** `provider-validation-gate` CI job is green (Phase 1.5 exit ✅ 2026-08-27);
Upstox credentials available to the owner locally; **and an explicit instruction
to start Phase 2.**

**Phase-2 entry checkpoints carried over from Phase 1.5 (first authenticated
calls, before relying on the path):**
- **PV-4:** confirm the v3 candle response's 7th element (Open Interest) is
  actually populated (non-null, plausible) for a live NSE F&O **intraday minute**
  candle. If not → config-flip to `B_SNAPSHOT` (`oi_mode=SNAPSHOT`,
  `has_intraday_oi=false`; both tables already exist, no migration).
- **PV-2 / PV-7:** the `docs/09` §2.4 normalization test pins a real intraday
  sample — first NSE session candle `09:15:00+05:30` → `03:45:00Z`, bar-open.
- **PV-5:** confirm the throttle HTTP status (expected `429`) and any
  `Retry-After` header; wire it into the backoff.
- **PV-1:** evaluate whether `extended_token` gives long-lived read-only market-
  data access (would enable unattended operation with no spec change).
- Align the Phase-1 stub to branch A: `STUB_CAPABILITIES.oi_mode = PER_TIMEFRAME`,
  `Instrument.has_intraday_oi` default `true` (config only; the applicability
  code already derives OI scope from `provider.capabilities()`).

**Scope:**
- `MarketDataProvider` + `AuthProvider` protocols + registry.
- Upstox adapter (only the capabilities `docs/11` confirmed): auth + token
  lifecycle (per PV-1 outcome), instrument master import, OHLCV, OI (per PV-4
  branch), pagination, retry/backoff, rate limiting.
- `MockProvider` + the provider contract suite + capability/branch tests.
- Ingestion: normalise to **bar-open UTC**; upsert `ohlcv_bars` /
  (`open_interest` | `oi_snapshots`); `aggregation.py` (M1 → session-anchored
  M5/M15/H1) if PV-2 requires it; **no fabricated bars**; watermarks per
  `(instrument, timeframe, data_kind, provider)`; the "re-verify last K
  finalized bars" repair pass.
- Instrument registry: `contract_key`, `provider_instrument_map`, futures
  rollover, **session-stable** option universe (daily fixing + hysteresis).
- API: `/instruments*`, `/instruments/{id}/bars`, `/open-interest`,
  `/instruments/{id}/coverage`, `/calendar*`, `/meta/*`.

**Exit:**
- Backfill populates history for the tracked universe across the required
  timeframes (INDEX daily depth per the PV-3 plan).
- Incremental ingestion is idempotent, gap-tolerant, fabricates nothing
  (tested); the repair pass corrects a seeded provider revision.
- Token-expiry path: cycle degrades, `/health/ready` reports it, no crash.
- Zero live provider calls in CI. `MockProvider` swap needs config only.

---

## Phase 3 — Analysis engine (indicators)

**Entry:** Phase 2 exit; sufficient INDEX daily history for 200-SMA.

**Scope (one analysis at a time, each to `docs/09` §6 DoD):**
RSI · 7 EMA (+ ATR helper) · Bollinger · Golden Cross · Volume · Open Interest.
- `analytical_core` input containers; `params_hash` on every result.
- Applicability wiring per `docs/04` §4 (Golden Cross `NOT_APPLICABLE` for dated
  contracts by default; Volume `NOT_APPLICABLE` on no-volume instruments).
- `app/analysis/` orchestration writing `analysis_results` (+ provenance) under
  the current run, with the **recompute guard**.
- Update `current_analysis_results`.
- API: `/analyses`, `/instruments/{id}/analyses[...]`, `.../series`, `.../runs`.

**Exit:**
- All six analyses pass golden + property + determinism + provenance tests.
- Recompute-guard tests pass (unchanged input → carried, no engine call).
- Payloads validate against shared Pydantic models; enum contract passes.

---

## Phase 4 — Market Profile

**Entry:** Phase 3 exit.

**Scope:**
- `analytical_core.market_profile`: deterministic configurable period model
  (`tpo_minutes`, `ib_periods`, `partial_period_policy`), bucketing + bin-size
  resolution, TPO builder, Volume Profile builder, shared POC + value area
  (incl. one-sided expansion, `va_expansion`), profile-shape classifier
  (`docs/05` §10.8).
- `market_profile_sessions` cache + `source_max_ts` recompute guard.
- API: `/instruments/{id}/market-profile` with the defined dual-profile response.

**Exit:**
- Full-session and partial-session golden fixtures pass for both profile types.
- Non-default `tpo_minutes` and shortened-session period generation verified;
  `ib_periods` and `partial_period_policy` variants verified.
- `VAL ≤ POC ≤ VAH` and containment invariants hold under property tests.
- One golden fixture per `market_profile_shape` value.

---

## Phase 5 — Scoring engine

**Entry:** Phase 4 exit.

**Scope:**
- `analytical_core.scoring`: `ScoringInput` (with `instrument_type` +
  `expected_analyses` as data), sub-score functions (reading only
  `values`/`aux`/`meta`), `weighted_v1` aggregation (single `contribution`
  formula; zero-usable-factors rule), label bands + low-confidence clamp,
  deterministic `explanation` templater, `warnings[]`, `SCORING_VERSION`,
  `params_hash`.
- `app/scoring/` orchestration → `signal_scores` + `score_factors` (with
  `analysis_result_id`) under the current run; update `current_signal_scores`
  with `delta_vs_previous`.
- API: `/scores`, `/instruments/{id}/score`, `/score/history`, `/config*`,
  `/runs` (+ `POST /runs`), `/runs/{id}`, `/meta/versions`, `/meta/applicability`.

**Exit:**
- Sub-score + aggregation tests pass; `fsum(contribution) == composite`; label
  boundaries exact; confidence penalty only for missing **expected** factors;
  clamp behaviour correct; zero-factors row written.
- End-to-end (manual `POST /runs`) does ingest → analyse → score under one
  `run_id`; `/scores` reflects it with `delta_vs_previous` and `explanation`.

---

## Phase 6 — Worker / cycle

**Entry:** Phase 5 exit.

**Scope:**
- `app/worker/`: one `analysis_runs` row per cycle covering INGEST → ANALYZE →
  SCORE; `run_phase_status` + `run_instrument_status`; single-flight advisory
  lock; bounded concurrency (`PROVIDER_CONCURRENCY`, `ANALYZE_CONCURRENCY`) and
  the provider rate limiter from `docs/02` §6.7 / `docs/11` PV-5; cycle-overrun
  → skip next tick; `run-completed` hook point.
- In-process mode + optional separate `worker` service (identical job bodies).
- `/health/ready` reports `last_cycle_seq`, `last_successful_cycle_age`,
  `worker_running`, `cycle_overrun`.

**Exit:**
- **End-to-end worker-cycle test (`docs/09` §2.11) passes**, incl. the
  partial-failure and recompute-carry variants.
- Cycle-timing budget test at synthetic ~94-instrument scale completes within
  the configured cadence on CI hardware (with margin).
- Left running locally, the platform self-updates every cycle; a provider outage
  degrades to `PARTIAL` and the next cycle recovers.

---

## Phase 7 — Frontend (tables only)

**Entry:** Phases 5–6 exit; stable OpenAPI schema.

**Scope:** per `docs/08` — generated client; Dashboard/Watchlist; Instrument
Detail (analysis panels incl. `NOT_APPLICABLE`/`INSUFFICIENT_DATA`/`carried`
states + score breakdown + `explanation`); per-bar series view; per-run trail
view; Instrument Manager; Runs + Run Detail; Config (schema-driven); Calendar;
global header (worker/stale/calendar indicators). MSW component tests.

**Exit:**
- All routes work end-to-end against the real API in Docker Compose.
- No charts; no client-side indicator/score computation; no execution language.
- `tsc --noEmit` clean; generated types current in CI.

---

## Phase 8 — Hardening

**Entry:** Phase 7 exit.

**Scope:** structured-logging polish; error taxonomy; readiness/metrics hook;
retention jobs (incl. `market_profile_sessions.bins` pruning); calendar-refresh
runbook; secrets/token runbook (per PV-1 outcome); performance pass on the
cycle; security pass on `LOCAL_API_TOKEN` and provider credentials.

**Exit:** V1 is operable by the owner from docs alone; a fresh
`docker compose up` + provider-validation checklist + backfill + first cycle is
a documented, repeatable procedure.

---

## Phase S — Streaming ingestion (lock lifted 2026-08-30)

**Scope (bounded — `.claude/CLAUDE.md` §3 / §3b, `docs/02` §3.4):** a WebSocket
feed for the **forming M1 bar + live OI only**. Engine and cycle unchanged; REST
stays authoritative for history / backfill / disconnect gap-fill; the streamer
is a separate optional process.

- **S0 — DONE (2026-08-30).** `docs/11` **§5** (Upstox Market Data Feed v3,
  prose — the machine PV gate stays scoped to the Phase-2 REST surface): S-1..S-7
  — endpoint, token auth, protobuf schema, subscription limit, message modes, OI
  availability, reconnect, timestamp + off-hours semantics. To be confirmed
  before S3.
- **S1 — DONE (2026-08-30).** Pure `analytical_core/streaming/m1_builder.py`:
  `M1Accumulator` + `Tick`/`StreamBar`. Wall-clock minute buckets, bar-open UTC;
  `volume = last_cum − minute_start_cum`; OI = last non-None; out-of-order ticks
  for a closed minute dropped; zero-tick minute emits nothing; `flush(now)`
  finalises + drops buckets past `grace_seconds`. `tests/test_m1_builder.py` (7).
  No dependency, no gate.
- **S2 — DONE (2026-08-30).** `app/providers/base.py` `StreamTick` +
  `StreamingMarketDataProvider`; `app/providers/stub/feed.py` `StubMarketFeed`
  (deterministic finite synthetic stream; `mode="ltpc"` drops OI);
  `app/providers/factory.py::build_streaming_provider` (stub now, `upstox` →
  `NotImplementedError` until S3); `app/ingestion/stream.py` `StreamIngestor`
  (feed → `M1Accumulator` → `SaMarketDataRepository` M1 + OI upserts, periodic
  flush + commit, run-end finalise; unmapped symbols skipped) + `build_symbol_map`
  + `serve()` (SIGINT/SIGTERM, reconnect loop); `analytical-worker stream
  [--mode]` (no-op unless `ANALYTICAL_STREAM_ENABLED=true`); config keys
  `stream_enabled`/`stream_mode`/`stream_flush_seconds`/`stream_reconnect_seconds`.
  `tests/test_stream_ingestor.py` (5, end-to-end on the stub feed). No migration.
- **S3 — DONE (2026-08-31).** `app/providers/upstox/feed.py` `UpstoxMarketFeed`:
  `GET /v3/feed/market-data-feed/authorize` → wss; binary `sub` frame;
  `MarketDataFeed_pb2` decode (proto v3, committed); `full` mode →
  `StreamTick(ltp, cum_volume=vtt, oi)`; `stream_enabled` guard; `docs/11` §5.1
  confirmed; `protobuf` + `websockets` signed off. `build_streaming_provider`
  returns it for `active_provider=upstox`. Reconnect via `StreamIngestor.serve()`;
  gap-fill stays on the REST cycle (decision 3).
- **S4 — DONE (2026-08-31).** `deploy/docker-compose.yml` `streamer` service
  (profile `streamer`, `analytical-worker stream`); `RUN_STREAM_IN_PROCESS` →
  API-lifespan daemon thread. `stream.serve()` is now **session-gated**
  (`evaluate_gate` + `market_calendar`) and takes a `stop_event` /
  `install_signals` for the in-process case. `/health/ready` reports
  `stream_enabled`, `stream_in_process`, `recent_m1_bar_age_seconds`. Config keys
  `stream_enabled` / `stream_mode` / `stream_flush_seconds` /
  `stream_reconnect_seconds` / `run_stream_in_process` + `deploy/.env.example`.

**Exit:** with the streamer running during a session, the forming M1 bar and
option-chain OI are seconds-fresh; a disconnect self-heals via REST gap-fill;
`docker compose --profile streamer up` is documented.

---

## Reserved future work (decision 14) — not scheduled, seams preserved

| Capability | Seam already in V1 |
|---|---|
| **Backtesting** | Pure engine + per-row `params_hash` + `input_window_*` + `config_snapshot` + `market_profile_sessions.source_max_ts`. **Retention (`docs/03` §6) bounds intraday depth; a separate archival job is required for deep history.** No `backtest_*` code in V1. |
| Charts | Analysis `series` payloads + `/analyses/{key}/series` endpoint; `frontend/src/charts/` reserved. |
| Alerts | `run-completed` hook + persisted `score_factors`. |
| More providers | `MarketDataProvider` / `AuthProvider` protocols + registry + `provider` on watermarks + contract suite. |
| More instruments / segments | Instrument-type abstraction + applicability matrix + `market_calendar.segment`. |
| Machine learning | Normalised `score_factors` + `params_hash` per run = feature-store seed; aggregation is a strategy interface. |
| AI explanations | Deterministic `explanation` string + `rationale` dicts. |
| Mobile app | Versioned REST API + generated schema. |
| Multi-user auth | `get_current_principal` swap + `users` auth columns + user-scoped tables. |
| Time-series optimisation | Partition-ready schema (`docs/03` §2), verified by the structural test. |
