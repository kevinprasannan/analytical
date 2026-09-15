# Development (implementation-facing)

The architecture/specification documents (`docs/01`–`docs/12`, `.claude/CLAUDE.md`)
are authoritative and are updated in the same change as any behaviour they cover.
This file is a pointer to the runnable pieces.

## Implemented

- **Foundations:** repo scaffold, PostgreSQL 16 schema + Alembic baseline,
  authoritative enum contract, provider protocols + `StubProvider`, the
  provider-validation gate (CLI + adapter guard) — currently **CLEAR**.
- **Ingestion:** real Upstox v3 candle adapter (M1/D1), M1 → session-anchored
  M5/M15/H1 aggregation, historical backfill (`analytical-backfill`), and the
  live INGEST phase wired into the cycle.
- **Analysis engine (`analytical_core`, pure):** RSI, Bollinger, EMA (+ATR),
  Golden Cross, Volume, Open Interest, and Market Profile (TPO + Volume profile).
  `ALGO_VERSION` with an engine-output snapshot guard (`tests/test_version_guard.py`).
- **Scoring engine:** `weighted_v1` aggregation → composite + confidence +
  raw/effective label + per-factor breakdown + `explanation`. `SCORING_VERSION`.
- **Worker:** one `analysis_runs` row per cycle (INGEST → ANALYZE → SCORE),
  per-phase / per-instrument status, partial-failure tolerance, single-flight
  advisory lock, the `run-completed` hook registry (`app/worker/hooks.py`), and
  the APScheduler loop (`analytical-worker serve`, session-gated).
- **API (`/api/v1`):** instruments, analyses, scores, runs (async `POST /runs`
  with `Idempotency-Key`), config, calendar, health, meta. RFC-7807 errors.
- **`app_settings` merge:** `PATCH /config` changes the effective scoring /
  Market Profile config from the next cycle; recorded on the run.
- **Deploy:** `deploy/docker-compose.yml` (db + backend + frontend, optional
  `worker` profile), `backend.Dockerfile`, `.env.example`.
- **Frontend:** complete React + TS + Vite + Tailwind + TanStack Query source
  (`frontend/`) — **not yet built/verified in this environment (needs Node).**

Backend setup, migration, test, gate and stub-provider instructions:
[`backend/README.md`](../backend/README.md).

## Provider-validation gate

`docs/11-provider-validation.status.yaml` is the machine-readable source of truth.
Run `python -m app.providers.validation.gate` (from `backend/`) — exit `0` = CLEAR,
`1` = BLOCKED, `2` = invalid file. Never change a PV status as a side effect of
coding.

## Not yet done

- Live Upstox checkpoints A–G (need a real access token).
- Frontend build / lint / test (need a Node toolchain).
- WebSockets / streaming (future work per docs/10).
