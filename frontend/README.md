# Analytical — Frontend (docs/08)

Table-based decision-support UI for NSE index & derivatives analysis.
**No charts. No BUY/SELL/execution language.** Display only — every number comes
from the API; nothing is computed client-side.

## Stack

React 18 + TypeScript (`strict`) · Vite · Tailwind · TanStack Query ·
react-router · Vitest + Testing Library + MSW.

## Develop

```bash
npm install
# point the dev proxy at your running backend (default http://localhost:8000)
VITE_API_TARGET=http://localhost:8000 npm run dev      # http://localhost:5173
```

The dev server proxies `/api` → backend. For a non-proxied setup set
`VITE_API_BASE_URL`. If the backend has `LOCAL_API_TOKEN` set, put the same value
in `VITE_LOCAL_API_TOKEN`.

## API types

`src/api/generated/schema.ts` is the drop-in target for

```bash
npm run gen:api   # openapi-typescript http://localhost:8000/openapi.json -o src/api/generated/schema.ts
```

It was hand-authored from the live OpenAPI while a Node toolchain was
unavailable — run `gen:api` against a running backend to regenerate it verbatim.
Only `src/api/` imports from it; the rest of the app uses `client.ts` + the
`queries.ts` hooks.

## Test / lint / build

```bash
npm test          # vitest (jsdom + MSW)
npm run lint      # eslint — includes a no-execution-language rule (docs/08 §2)
npm run typecheck
npm run build     # tsc -b && vite build  ->  dist/
```

## Routes

| Route | View |
|---|---|
| `/dashboard` | Watchlist — `/scores` for the selected timeframe, sortable, filter chips, pollable |
| `/instruments` | Instrument Manager — browse, toggle `is_tracked` |
| `/instruments/:id` | Detail — score card + breakdown + explanation + per-analysis panels + Market Profile (TPO / Volume as tables) |
| `/instruments/:id/series` | Per-final-bar series tables per analysis |
| `/instruments/:id/runs` | Per-run recompute audit for the instrument |
| `/runs`, `/runs/:id` | Cycles + trigger a manual run (`409` handled); run detail with phase cards + per-instrument outcome grid + `config_snapshot` |
| `/config` | Schema-driven form from `/config/schema`; `PATCH` shows `effective_from` + new `config_params_hash` |
| `/calendar` | Session status + trading-day table |

Global header: market open/closed, worker-running, last-successful-cycle age,
calendar-seeded warning, `stale_results` badge, versions, and the timeframe
selector (URL `?tf=` + localStorage).

## Deploy

`deploy/frontend.Dockerfile` runs `vite build` then serves `dist/` with nginx
(SPA fallback + `/api` proxy to the `backend` service). `docker compose up`
exposes it on `127.0.0.1:5173`.

## Reserved (no work in V1)

`src/charts/` (empty), alerts UI, auth/login, multi-timeframe consensus.
