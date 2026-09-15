# 09 — Testing Strategy

## 1. Priorities

1. **`analytical_core` correctness** — the engine is the product.
2. **Reproducibility** — same inputs + `params_hash` + `ALGO_VERSION` ⇒
   identical output.
3. **Contract integrity** — engine payloads == API schemas == generated
   frontend types == DB enums.
4. **Cycle integrity** — one run per cycle; phase/instrument status; partial
   failure handled.
5. **Ingestion safety** — idempotent, gap-tolerant, no fabricated bars, no live
   provider calls in CI.
6. Everything else: pragmatic coverage.

## 2. Backend

### 2.1 `analytical_core` unit tests (pytest)
- **Golden-value fixtures** per analysis under
  `backend/tests/fixtures/analysis/<analysis_key>/`: hand-verified inputs →
  expected outputs. Each analysis ≥ 3 fixtures (normal / boundary /
  insufficient), plus:
  - **RSI (H10):** Wilder worked example; all-zero-delta → 50.0; `avg_loss==0`
    → 100.0; `avg_gain==0` → 0.0; precedence fixture hitting the both-zero
    branch first; divergence bullish/bearish/none with the `div_min_rsi_delta`
    boundary.
  - **Bollinger (M11):** population-std reference; `upper==lower` → `MIDDLE`,
    `%B=0.5`, `bandwidth=0`; squeeze window excludes the current bar;
    `bandwidth_percentile` exclusive rank; short-window → `squeeze=null`.
  - **EMA (M14):** SMA seeding; recurrence; slope `null`/`UNKNOWN` below
    `period+slope_lookback`; `atr14` aux value.
  - **Golden Cross (M12, H1):** golden / death / none-in-window / multiple
    crosses in window (pick most recent) / exact-touch `fast==slow` (zero-sign
    carry) / cross on the forming bar (`provisional`); `NOT_APPLICABLE` for
    FUTURE and OPTION by default; opt-in path emits the warning.
  - **Volume (H9):** all-zero volume → `NOT_APPLICABLE` (not
    `INSUFFICIENT_DATA`); `rvol` null on zero denominator; `up_down_ratio` null
    when down-count 0; `aux.price_change_pct_recent`.
  - **Open Interest (M7, M8):** `oi_change` computed only from stored `oi`;
    `provider_oi_change` present but ignored; one fixture per `oi_behavior`
    incl. `INDETERMINATE` via price-flat and via oi-flat (epsilon boundaries);
    option fixture carries the per-strike-semantics warning; SNAPSHOT and
    (branch A) PER_TIMEFRAME inputs both classify identically.
  - **Market Profile (H4, H5):**
    - Period generation for `tpo_minutes` ∈ {20, 30, 60} and for a **shortened
      session** (non-default `session_close_ist`); assert period count, letters,
      and that the default 375/30 case reproduces A–M.
    - `ib_periods` ∈ {1, 2, 3}; `partial_period_policy` KEEP / MERGE_PREV /
      DROP.
    - POC tie-break (VWAP-proximity then lower price).
    - Value area: `va_expansion` PAIR vs SINGLE; one-sided-exhaustion branch
      (POC adjacent to session high); equal-pair upward tie-break;
      `total==0` → `INSUFFICIENT_DATA`.
    - Profile-shape: one fixture per `market_profile_shape` value, order-of-rules
      check.
    - Deep-OTM option: `< min_bins` → `INSUFFICIENT_DATA`.
    - Full synthetic NSE session (09:15–15:30 IST, M5 bars) with hand-derived
      POC/VAH/VAL for both profile types; partial session
      (`is_session_complete=false`).
- **Property tests (hypothesis):**
  - `0 ≤ RSI ≤ 100`.
  - `lower ≤ basis ≤ upper`; degenerate handled.
  - Market Profile: `VAL ≤ POC ≤ VAH`; VA metric ≥ `value_area_pct·total`
    (± one expansion step); `VAL ≥ session_low`, `VAH ≤ session_high`.
  - Golden Cross: `state` consistent with `sign(fast[-1]-slow[-1])`.
  - Engine never raises on contract-valid input — returns a status.
- **Determinism:** run each analysis twice → deep-equal; `meta.algo_version ==
  ALGO_VERSION`.
- **Version guard** (`tests/test_version_guard.py`): `tests/support/engine_snapshot.py`
  runs every deterministic engine (the six indicators + Market Profile + the
  scoring aggregation) over a fixed synthetic battery; its canonical-JSON output
  is committed as `tests/fixtures/analysis/engine_snapshot.json`. Any change to a
  formula, default parameter, rounding, tie-break, or approximation shifts the
  digest and fails the test until the fixture is regenerated
  (`python -m tests.support.engine_snapshot`) **and** `ALGO_VERSION` /
  `SCORING_VERSION` are bumped in the same commit — the fixture records the
  version it was generated under and a companion assertion checks it equals the
  current constant.

### 2.2 Provenance tests (M19)
- Every result `meta` carries `algo_version`, `params_id`, `params_hash`,
  `input_window_start/end`, `bars_used`, `coverage_ratio`.
- Same inputs + same effective params → identical `params_hash`; changing any
  parameter changes the hash.
- Orchestration writes these into `analysis_results` columns, not only JSONB.

### 2.3 Recompute-guard tests (M24)
- Unchanged latest bar `ts`/`is_final` + unchanged `params_hash` → analysis is
  **carried** (`carried=true`, `carried_from_result_id` set), engine not
  invoked (spy asserts zero calls).
- Advanced bar or changed params → recompute.
- Market Profile guard keyed on `source_max_ts`.

### 2.4 Session / timezone tests (H11)
- M1 → session-anchored M5/M15/H1 aggregation: correct boundaries IST↔UTC; H1
  partial last bar flagged; empty target periods **not emitted** (M23); `is_final`
  only when all children final and period ended by `finalize_grace`.
- D1 `ts` convention (session-open instant, UTC).
- `is_final` false→true transition at `finalize_grace_seconds`.
- `/calendar/status` on weekend / holiday / pre-open / shortened `NORMAL`
  session / `MUHURAT` (skipped).
- Provider timestamp normalisation: bar-open vs bar-close input both map to
  bar-open UTC (`docs/11` PV-7 fallback).

### 2.5 No-trade / sparse-series tests (M23)
- Sparse M1 fixture → aggregation emits no bar for empty periods; indicators run
  on the contiguous present bars; `coverage_ratio` computed; `< min_coverage` →
  `INSUFFICIENT_DATA` (`reason="sparse series"`); no OHLC fabricated or carried
  forward.

### 2.6 Enum contract test (M20)
- For every entry in `analytical_core.enums.ENUM_REGISTRY`:
  `set(python_values) == set(pg_enum_labels) == set(openapi_enum_values)`.
- `analysis_key` `CHECK` constraint matches the Python set.
- Fails the build on any drift.

### 2.7 Scoring tests (C4, M5, M6, M26, H9)
- Per sub-score fn: fixture table (`FactorInput` → expected sub_score,
  confidence, reason). EMA reads `aux.atr14`; Volume reads
  `aux.price_change_pct_recent`; Market Profile reads `close_vs_vah/val`.
- Aggregation: `fsum(contributionᵢ) == composite_score`; label-band boundaries
  (`±60`, `±20`) exact; `overall_confidence` drops when an **expected** factor
  is missing but **not** when a `NOT_APPLICABLE` factor is absent; low-confidence
  clamp moves exactly one band; `/scores?label=` matches `effective_label`.
- **Zero usable factors** → `composite=0`, `confidence=0`,
  `raw=effective=NEUTRAL`, `low_confidence=true`, row still written.
- Determinism + `SCORING_VERSION` guard.

### 2.8 Persistence / structural tests (M22, M1)
- Ephemeral PostgreSQL (Docker service or `testcontainers`); no SQLite.
- Alembic `upgrade head` then `downgrade base` clean on an empty DB.
- **Partition-readiness structural test:** for each high-volume table assert the
  natural key is present, `ts`/`scope_key` convention holds, no FK spans a
  would-be partition boundary in a blocking way, retention query is a
  time-window delete.
- FK behaviour: `score_factors` cascades from `signal_scores`;
  `analysis_results`/`signal_scores` cascade from `analysis_runs`;
  `*_→ instruments` is `RESTRICT`; `current_*` cascade from their sources;
  `carried_from_result_id` → `SET NULL`.
- Upsert idempotency: same bar/OI twice → one row, `DO UPDATE SET` columns
  refreshed, `is_final` false→true transition correct.
- Watermark advance + the "re-verify last K finalized bars" repair pass (M16).
- Scope model: `analysis_results` `CHECK`s enforce exactly one of
  `timeframe`/`session_date`/`snapshot_ts` per `scope`; `scope_key` generation.
- `rebuild-projections` reproduces `current_*` byte-for-byte from history.

### 2.9 Provider / ingestion tests
- **No live Upstox calls in CI, ever.** Sanitised recorded fixtures under
  `backend/tests/fixtures/providers/upstox/`.
- `MockProvider` implements the protocols; the provider **contract suite** runs
  against any implementation (future providers inherit it).
- Capability/branch tests: system degrades correctly when the provider reports
  (a) no per-candle OI → SNAPSHOT branch used; (b) no native M5 → M1-aggregation
  branch used; (c) token `EXPIRED` → cycle marks instruments `SKIPPED`,
  `/health/ready` reports it, no crash (C2).
- Rate-limit response → watermark `RATE_LIMITED`, instrument `DEGRADED`, cycle
  continues (M24 fallback limits).
- Normalisation: provider payload → canonical bars/OI (units, tz→UTC bar-open,
  instrument mapping).

### 2.10 API tests
- FastAPI `TestClient`; real service layer; ephemeral DB; mocked provider.
- Per endpoint: happy path, filters/pagination, 404, 422 (problem+json shape).
- `NOT_APPLICABLE` (e.g. OI on INDEX) returns `200` with the marker, **not** a
  4xx.
- Read endpoints hit `current_*` (assert no full-history scan via query
  inspection / row-count guard).
- `POST /runs` during a running cycle → `409` + `Retry-After`.
- Scope in payloads: every analysis item carries `scope` + exactly one of
  timeframe/session_date/snapshot_ts.
- **Schema contract test:** export OpenAPI; assert analysis `result` payloads
  validate against the shared Pydantic models; snapshot the OpenAPI doc and fail
  on unreviewed changes.
- Auth: with `LOCAL_API_TOKEN` set, missing/wrong → 401; correct → 200.

### 2.11 End-to-end worker-cycle test (M21, strategic directive 19)
- Ephemeral PG + `MockProvider` fixtures for a small universe (1 INDEX, 1
  FUTURE, 2 OPTIONs).
- **Happy path:** run one full cycle. Assert: exactly **one** `analysis_runs`
  row; three `run_phase_status` rows (INGEST/ANALYZE/SCORE = SUCCEEDED);
  `run_instrument_status` populated per (instrument, phase);
  `analysis_results` + `signal_scores` all under that one `run_id`;
  `current_analysis_results` + `current_signal_scores` updated;
  `signal_scores.explanation` non-empty; `fsum(contribution)` ≈ `composite`.
- **Partial failure:** `MockProvider` raises for one instrument during INGEST.
  Assert: `analysis_runs.status = PARTIAL`; that instrument
  `run_instrument_status = ERROR` (INGEST) and `SKIPPED`/`DEGRADED` downstream;
  the other instruments are fully analysed and scored; the cycle finishes; the
  advisory lock is released.
- **Recompute-carry:** a second immediate cycle with no new bars → analyses
  carried, no engine calls, scores stable, `delta_vs_previous ≈ 0`.
- **Cycle-timing budget:** a synthetic ~94-instrument universe completes a cycle
  under the configured cadence on CI hardware within a generous margin
  (informational threshold; a hard fail only on gross regressions). Phase 6 exit
  gate (`docs/10`).

### 2.12 Provider-validation gate test (mechanical Phase 2 gate)
Backs the `provider-validation-gate` CI job. Pure — parses files, no network.
- **Schema:** `docs/11-provider-validation.status.yaml` parses; every `PV-*` item
  present; `status ∈ {OPEN, CONFIRMED, ACCEPTED_FALLBACK}`;
  `blocks_phase_2` is `true` for PV-1…PV-7 and `false` for PV-8;
  `meta.gate_blocking_ids == [PV-1..PV-7]`.
- **Well-formedness:** `CONFIRMED` ⇒ non-empty `evidence` (each entry matches
  `"<url> — YYYY-MM-DD"`); `ACCEPTED_FALLBACK` ⇒ `fallback_ref` resolves to a
  heading/anchor in `docs/11-PROVIDER-VALIDATION.md`; PV-2 resolved ⇒ `branch ∈
  {NATIVE, AGGREGATE_FROM_M1}`; PV-4 resolved ⇒ `branch ∈ {A_PER_CANDLE,
  B_SNAPSHOT}`; resolved ⇒ non-null `decided_on`.
- **Table parity:** the `docs/11` §1 markdown table rows match the `.yaml`
  (id, item title, status).
- **The gate itself:** if any `blocks_phase_2` item is `OPEN`, assert
  `backend/app/providers/upstox/` contains only files on the declared
  pre-gate-clear allow-list (`__init__.py`, `stub.py`, `capabilities.py`,
  `gate.py`) — any additional module fails the job. **This check applies only
  while a blocking PV row is OPEN.** Once the gate is CLEAR (Phase 1.5 outcome,
  2026-08-27) Phase 2 legitimately adds the real adapter modules to that
  directory; `evaluate()` skips the allow-list check when there are no open
  blocking rows. Coverage of the check is retained via a synthetic all-OPEN
  fixture (`test_validation_gate.py`).
- **Adapter guard unit test:** constructing `UpstoxProvider` while the `.yaml`
  has an `OPEN` blocking row raises `ProviderValidationGateError` (defense-in-
  depth: `__init__` re-runs the gate); with all blocking rows resolved it
  constructs and exposes auth + capabilities; `StubProvider` is unaffected.

## 3. Frontend

- **Vitest + React Testing Library**, **MSW** shaped from the committed OpenAPI
  schema (fixtures generated from it → drift caught).
- Component tests: Dashboard table (sort, filter on `effective_label`, empty,
  loading, `<ProblemError>`, "worker not running" banner); Instrument Detail
  panels (each renders `OK` / `INSUFFICIENT_DATA` / `NOT_APPLICABLE` / null;
  `carried` and `provisional` badges); Score breakdown sums to composite;
  `explanation` renders; Config form from schema + 422 mapping.
- `lib/format.ts`, `scoreBands.ts`, `timeframe.ts`, `scope.ts` — pure unit
  tests.
- `tsc --noEmit` is a CI gate; generated API types must be current (CI
  regenerates + diffs).
- No e2e/browser automation in V1 (Playwright reserved).

## 4. CI outline (proposed — GitHub Actions)

| Job | Steps |
|---|---|
| `backend-lint` | ruff, black --check, mypy/pyright |
| `backend-test` | spin PG → alembic up/down → pytest (unit, property, provenance, recompute-guard, session/tz, no-trade, scoring, persistence/structural, provider, api, **e2e worker-cycle**), coverage |
| `enum-contract` | build PG enums + OpenAPI → run `enum-contract` test |
| `provider-validation-gate` | validate `docs/11-provider-validation.status.yaml` (see §2.12); fail if a `blocks_phase_2` item is `OPEN` while `backend/app/providers/upstox/` exceeds its declared stub set, or on any malformed / unresolvable / branch-missing row, or if the `docs/11` §1 table disagrees with the file |
| `contract` | export OpenAPI → validate → diff snapshot; regenerate frontend types → diff |
| `frontend-lint` | eslint, prettier --check, tsc --noEmit |
| `frontend-test` | vitest run, coverage |
| `build` | docker build backend + frontend images (no push in V1) |

All jobs on PR; no deploy stage in V1. `provider-validation-gate` is also the
mechanical definition of the `docs/10` Phase 1.5 exit.

## 5. Coverage expectations

| Area | Target |
|---|---|
| `analytical_core` indicators + market profile | ≥ 95% line + branch |
| `analytical_core.scoring` | ≥ 95% |
| ingestion / normalisation / aggregation | ≥ 85% |
| worker cycle orchestration | ≥ 85% |
| API routers / services | ≥ 80% |
| frontend lib + critical components | ≥ 80% |

Coverage is a floor; golden + property + e2e tests are the real protection.

## 6. Definition of done — per analysis

1. Spec section in `docs/05` complete (formula, params, applicability, outputs,
   edge cases, references).
2. Pure implementation in `analytical_core`, no IO.
3. Golden fixtures (normal / boundary / insufficient / not-applicable where
   relevant) committed and passing.
4. Property invariants passing.
5. Provenance (`algo_version`, `params_id`, `params_hash`) present and tested.
6. Pydantic result model matches the engine output; API contract test passes;
   enum contract test passes.
7. Sub-score function + tests in the scoring engine (reads only
   `values`/`aux`/`meta`).
8. Applicability wired per `docs/04` §4 (NOT_APPLICABLE path tested).
9. Frontend panel renders every status.
10. `ALGO_VERSION` reflects the current formulas.

## 7. Test data policy

Synthetic or sanitised only. No real account tokens, no proprietary vendor data.
Fixture files small and human-reviewable; large series built in-test from a
seeded RNG with the seed recorded.
