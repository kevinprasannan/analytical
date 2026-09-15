# Analytical

Web-based **Trading Intelligence & Market Analysis Platform** — an **analytical
decision-support system** for NSE (Indian) index and derivatives markets.

Analytical ingests market data on an intraday schedule, runs a deterministic
analysis engine, normalises each analysis into a factor score, and combines
those into a **composite score** with a **confidence** value and a
**deterministic explainable hint**, per instrument and timeframe — presented as
sortable tables.

It is **not** an execution system: it never emits BUY / SELL / entry / exit /
target / stop instructions. Discrete outputs are analytical labels
(`STRONG_BEARISH … STRONG_BULLISH`).

> **Status: Phase 0 — Specification (revised).**
> No application code, dependencies, or DB migrations yet. `docs/` is the source
> of truth. A consistency review has been run and a revision pass applied.
> See [docs/10-ROADMAP.md](docs/10-ROADMAP.md).

## What V1 does

- **Instruments:** NSE — NIFTY, BANKNIFTY (INDEX); NIFTY/BANKNIFTY FUTURES;
  NIFTY/BANKNIFTY OPTIONS. Instrument-type abstraction (`INDEX / FUTURE /
  OPTION`); managed via a registry with a **session-stable** tracked universe.
- **Analysis applicability is per instrument type** — not every analysis runs on
  every instrument (see [docs/04-DATA-MODEL.md](docs/04-DATA-MODEL.md) §4).
- **Timeframes:** 5m, 15m, 1h, Daily — all intraday grids anchored to the NSE
  session open. `M1` is an ingestion/aggregation source only.
- **Cadence:** intraday periodic cycle (target 1–5 min). Exactly one
  `analysis_run` per cycle covering ingest + analyse + score. An optional
  WebSocket streamer feeds only the forming M1 bar + live OI (docs/10 Phase S);
  the engine still runs on the periodic cycle.
- **Analyses:** Market Profile (TPO + Volume Profile — deterministic,
  configurable), Open Interest, Volume, RSI, Bollinger Bands, 7 EMA, Golden
  Cross (primarily on the INDEX series).
- **Scoring:** explainable weighted aggregation → composite score + confidence +
  raw/effective label + per-factor breakdown (factor · raw value · sub-score ·
  confidence · weight · contribution · reason) + warnings + a deterministic
  `explanation` string.
- **Surfaces:** versioned REST API (`/api/v1`) and a React + TypeScript
  table-based UI. **No charts.**

## What V1 does NOT do

No charts. No order/execution, no BUY/SELL output. No backtesting
engine (provenance + data design preserve the option). No alerts. No multi-user
auth. No ML / AI-generated explanations. No mobile app. No non-NSE markets. No
TimescaleDB. Seams for all of these are documented in
[docs/02-ARCHITECTURE.md](docs/02-ARCHITECTURE.md) §7 and
[docs/10-ROADMAP.md](docs/10-ROADMAP.md).

## Tech direction

| Layer | Choice |
|-------|--------|
| Language | Python 3.12+, TypeScript |
| Backend | FastAPI (thin API) + a **pure, framework-independent** analysis/scoring engine (`analytical_core`) |
| Data | PostgreSQL 16 (standard; partition-ready schema), SQLAlchemy + Alembic |
| Market data | Upstox API, behind a replaceable provider abstraction (`MarketDataProvider` + `AuthProvider`) — capabilities gated by `docs/11` |
| Frontend | React + TypeScript + Vite + Tailwind CSS + TanStack Query |
| Run | Docker Compose — `db`, `backend`, `frontend` (+ optional `worker`) |
| Architecture | Modular monolith (no microservices, no Kafka, no Kubernetes, no ML infra) |

## Documentation

| Doc | Contents |
|-----|----------|
| [.claude/CLAUDE.md](.claude/CLAUDE.md) | Working agreement, locked decisions (incl. the revision pass), conventions, hard rules |
| [docs/01-PRODUCT.md](docs/01-PRODUCT.md) | Problem, users, V1 scope, non-goals, decision-support framing, success criteria |
| [docs/02-ARCHITECTURE.md](docs/02-ARCHITECTURE.md) | Modules, dependency rule, run model, `current_*` projections, token lifecycle, throughput budget, seams |
| [docs/03-DATABASE.md](docs/03-DATABASE.md) | Schema, analysis scope model, run model, hot-read projections, FKs, provenance, retention, partition-readiness |
| [docs/04-DATA-MODEL.md](docs/04-DATA-MODEL.md) | Instrument abstraction, universe policy, **analysis applicability matrix**, core + scoring types |
| [docs/05-ANALYSIS-ENGINE.md](docs/05-ANALYSIS-ENGINE.md) | Session/timeframe model, every analysis (deterministic, configurable), Market Profile, provenance |
| [docs/06-SCORING-ENGINE.md](docs/06-SCORING-ENGINE.md) | `ScoringInput`, sub-scores, `weighted_v1`, labels + confidence clamp, explainability, non-execution |
| [docs/07-API-SPEC.md](docs/07-API-SPEC.md) | REST resources, scope in payloads, projections, series-vs-runs split, error format |
| [docs/08-FRONTEND-SPEC.md](docs/08-FRONTEND-SPEC.md) | Views, panels, applicability states, no charts, no execution language |
| [docs/09-TESTING.md](docs/09-TESTING.md) | Golden / property / provenance / session / enum / end-to-end tests, CI, per-analysis DoD |
| [docs/10-ROADMAP.md](docs/10-ROADMAP.md) | Phased plan; Phase 1.5 provider-validation gate; reserved seams |
| [docs/11-PROVIDER-VALIDATION.md](docs/11-PROVIDER-VALIDATION.md) | Upstox capabilities to confirm before Phase 2 (auth/token, intervals, depth, OI, rate limits, master); mechanically enforced |
| [docs/11-provider-validation.status.yaml](docs/11-provider-validation.status.yaml) | Machine-readable source of truth for the provider-validation gate (CI job + adapter startup guard read this) |
| [docs/12-ENUM-CONTRACT.md](docs/12-ENUM-CONTRACT.md) | Authoritative enum list + DB/API synchronisation + change procedure |

## Running the stack

```sh
cp deploy/.env.example deploy/.env          # edit as needed
docker compose -f deploy/docker-compose.yml up -d --build
```

Brings up `db` (Postgres 16), `backend` (runs `alembic upgrade head` + the
idempotent seed, then serves the API on `127.0.0.1:8000`), and `frontend`
(nginx on `127.0.0.1:5173`, proxying `/api/` to the backend). Check
`http://127.0.0.1:8000/api/v1/health/ready`.

The periodic execution-cycle scheduler is opt-in:

```sh
docker compose -f deploy/docker-compose.yml --profile worker up -d   # separate worker container
# or: set ANALYTICAL_RUN_WORKER_IN_PROCESS=true to run it inside the backend
```

`ANALYTICAL_ACTIVE_PROVIDER` defaults to `stub`; set it to `upstox` (with
`ANALYTICAL_UPSTOX_ACCESS_TOKEN`) for live data.

### Backend tests

```sh
cd backend && uv sync && uv run pytest          # add -m "not db" to skip Postgres-backed tests
```

## License

Private / unpublished.
