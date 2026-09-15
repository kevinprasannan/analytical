# Analytical — backend

FastAPI API + a pure `analytical_core` engine (indicators + Market Profile +
`weighted_v1` scoring) + the worker cycle (INGEST → ANALYZE → SCORE), the Upstox
v3 candle adapter, historical backfill, and the APScheduler loop. Provider
capabilities are gated by `docs/11` (the gate is currently CLEAR).

Architecture docs are authoritative: `../docs/`, `../.claude/CLAUDE.md` — updated
alongside the behaviour they describe. `../docs/DEVELOPMENT.md` is the
implementation-facing status pointer.

---

## Layout

```
analytical_core/        pure engine — enums (source of truth), versioning, params,
                        series, indicators/, market_profile/, scoring, results
app/
  config.py             typed settings (env: ANALYTICAL_*)
  logging.py             structlog
  providers/
    base.py              protocols + DTOs + exceptions
    capabilities.py       ProviderCapabilities + resolution helpers (ask, don't assume)
    registry.py / factory.py   active provider from settings
    validation/           PV gate: loader, evaluate, CLI  (never writes the YAML)
    stub/                 StubProvider — deterministic synthetic data, all failure modes
    upstox/               v3 auth + candle adapter (gate CLEAR); stub allow-list otherwise
  db/
    models.py            SQLAlchemy models (docs/03 §5)
    repositories/         protocols + memory impl + sqlalchemy impl
    seed.py / commands.py seed data, rebuild-projections, refresh-calendar
  ingestion/             candle normalise, M1->grid aggregation, backfill, live INGEST
  analysis/ scoring/     ANALYZE / SCORE orchestration over analytical_core
  worker/               run_cycle, hooks (run-completed), scheduler, CLI
  api/                  FastAPI /api/v1: instruments, analyses, scores, runs, config,
                        calendar, health, meta
alembic/                0001_phase1_baseline
tests/                  pytest suite (~365 no-DB, ~430 with a PostgreSQL)
```

## Setup

Intended tool is **uv** (Phase-0 decision). If you have it:

```
cd backend
uv sync --extra dev
uv run pytest
```

Without uv (plain venv + pip):

```
cd backend
python -m venv .venv && . .venv/Scripts/activate      # or .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Environment (all optional, sane defaults in `app/config.py`):

| var | default | meaning |
|-----|---------|---------|
| `ANALYTICAL_DATABASE_URL` | `postgresql+psycopg://analytical:analytical@localhost:5432/analytical` | app DB |
| `ANALYTICAL_ACTIVE_PROVIDER` | `stub` | `stub` \| `upstox` (upstox refuses until the PV gate clears) |
| `ANALYTICAL_LOCAL_API_TOKEN` | *(unset)* | if set, `/api/v1` needs `Authorization: Bearer <token>` |
| `ANALYTICAL_TEST_DATABASE_URL` | *(unset)* | enables the `@pytest.mark.db` tests |

## Database / migrations

```
# render SQL offline (no DB needed):
python -m alembic upgrade head --sql

# apply to a database:
ANALYTICAL_DATABASE_URL=postgresql+psycopg://user:pass@host:5432/db \
  python -m alembic upgrade head
python -m app.db.seed                 # owner user + app_settings (docs/02 §8.1) + calendar
python -m app.db.commands rebuild-projections
python -m app.db.commands refresh-calendar --years-ahead 2
```

Enum types are created by the baseline migration from `analytical_core.enums`
(via `pg_enum(values_callable=...)`), so labels have one source of truth;
`python -m analytical_core.enums --emit-sql` renders the same list for
inspection and `tests/test_enum_contract.py` checks all three representations
agree.

## Tests

```
pytest -m "not db"                      # no database needed
ANALYTICAL_TEST_DATABASE_URL=postgresql+psycopg://user:pass@host:5432/testdb pytest
                                        # + the @pytest.mark.db tests
```

DB tests use PostgreSQL only (never SQLite — docs/09 §2.8). Any throwaway
PostgreSQL works, e.g. `docker run --rm -e POSTGRES_PASSWORD=x -p 5461:5432 postgres:16`
then point `ANALYTICAL_TEST_DATABASE_URL` at it. The DB fixture runs
`alembic downgrade base` / `upgrade head` around each test.

## Provider-validation gate (docs/11)

```
python -m app.providers.validation.gate       # human-readable report; exit 0 = CLEAR, 1 = BLOCKED, 2 = invalid file
# or, after `pip install -e .`:
analytical-gate
```

The gate reads `../docs/11-provider-validation.status.yaml` and never writes it.
It is **CLEAR** (every `blocks_phase_2` item is `CONFIRMED` or
`ACCEPTED_FALLBACK`), so the Upstox adapter is permitted to construct. If a
blocking item ever reverts to `OPEN`, constructing the adapter raises
`ProviderValidationGateError` and `app/providers/upstox/` is restricted to the
stub allow-list — a violation fails the gate.

**Do not flip a PV status by hand as part of coding.** Statuses change only when
a requirement is genuinely validated against Upstox docs/sandbox.

## Local stub provider

`ANALYTICAL_ACTIVE_PROVIDER=stub` (the default) uses `app/providers/stub`. Every
value it returns is synthetic and tagged `source="STUB_FIXTURE"` — it is never
real market data. Configure failure modes for testing via `StubBehavior`
(`auth_state`, `empty_symbols`, `rate_limited_symbols`, `error_symbols`,
`unavailable_capabilities`).

## Run a cycle / the API

```
python -m app.worker.cli run-cycle                 # one INGEST->ANALYZE->SCORE cycle
python -m app.worker.cli run-cycle --phases ANALYZE,SCORE
python -m app.worker.cli serve [--run-now]         # the periodic scheduler loop
uvicorn app.api.main:app --reload                  # http://127.0.0.1:8000/api/v1/health
```

## Docker Compose

```
cp ../deploy/.env.example ../deploy/.env
docker compose -f ../deploy/docker-compose.yml up -d --build      # db + backend + frontend
docker compose -f ../deploy/docker-compose.yml --profile worker up -d   # + scheduler
```
