# 15 — Index constituents & weightage

Owner-authorised 2026-09-03. A side module that answers **"which stocks carry
this index right now, and how tightly does each track it?"** — the names of an
index ordered by weight, with running cumulative weight, sector rollup,
concentration, each name's day contribution to the index move, market breadth,
and (on request) rolling beta / correlation.

Descriptive only. It is **not** part of the scoring engine, produces no
analytical label, and emits no BUY/SELL. The 50 constituents are **not tracked
instruments** and are **not ingested** — the weights are seeded reference data
and the dynamic figures come from a quote-on-read snapshot.

---

## 1. Data — seeded weights (`index_weights`)

Free-float index weights are **owner-maintained**: the NSE / niftyindices
factsheet is loaded on each semi-annual rebalance. There is no scraper and no
provider-validation gate — this is static reference data.

`index_weights` (migration `0005`, additive / `IF NOT EXISTS`):

| column | notes |
|---|---|
| `index_key` | the index `instruments.contract_key` (`NIFTY-INDEX`, `BANKNIFTY-INDEX`, `SENSEX-INDEX`) |
| `effective_date` | the rebalance date this set applies from |
| `symbol` | NSE equity symbol |
| `name`, `sector` | display + the niftyindices sector bucket |
| `weight_pct` | free-float weight, percent (0–100) |
| `provider`, `provider_symbol` | optional — the provider key for quote-on-read; the weight view needs neither |
| `source` | `seed` |

`UNIQUE (index_key, symbol, effective_date)`; index on `(index_key, effective_date)`.
No FK to `instruments` (constituents are not instruments).

**CLI — `analytical-index-weights`:**

```
analytical-index-weights load data/nifty50_weights.csv --effective-date 2026-07-31
analytical-index-weights load fs.csv --index BANKNIFTY-INDEX --effective-date 2026-07-31
analytical-index-weights show                       # latest NIFTY-INDEX set
analytical-index-weights show --index NIFTY-INDEX --date 2026-07-31
```

CSV columns: `symbol,name,sector,weight_pct` and optional `provider_symbol`;
`#` / blank lines skipped. `load` replaces the rows for that
`(index_key, effective_date)` unless `--append`. A dated seed lives at
`backend/data/nifty50_weights.csv` (illustrative — replace with the real
factsheet).

---

## 2. Engine — `analytical_core.indices` (pure)

`build_constituent_view(*, index_symbol, algo_version, weight_rows, ...) ->
ConstituentView` — pure, deterministic, stdlib only. Inputs beyond the weight
rows are all optional; the view degrades cleanly (static analytics only) when
they are absent.

- **Ordering** — `items` sorted by `weight_pct` desc (tie-break symbol);
  `rank` 1 = heaviest; `cumulative_weight_pct` is the running Σ down that list.
- **Contribution** (needs a quote per name): `change_pct = (ltp − prev_close) /
  prev_close · 100`; `contribution_pct = weight_pct · change_pct / 100` — the
  **index percent** that name added today, so `Σ contribution_pct` ≈ the index's
  own change %. `contribution_points = contribution_pct / 100 · index_prev_close`.
  `contribution_rank` ranks by signed contribution (1 = most positive);
  `abs_contribution_rank` by magnitude (1 = biggest mover of the index either
  way — note this is *weight × move*, not the biggest price move). Approximate:
  price-return only, ignores the divisor, corporate actions and intraday weight
  drift.
- **Concentration** — `top1_pct` / `top5_pct` / `top10_pct` (Σ of the heaviest
  N), `hhi` (Herfindahl on weight fractions).
- **Sectors** — per bucket: `weight_pct`, `count`, `contribution_pct`
  (Σ contribution of its names); ordered by weight desc.
- **Breadth** (needs quotes): `advances` / `declines` / `unchanged` counts over
  `covered` names; `up_weight_pct` / `down_weight_pct` and
  `advance_decline_weight` (up − down); `net_contribution_pct` (Σ, the index
  proxy); `top5_move_share` = |Σ top-5 contribution| / Σ|contribution| — how
  concentrated the move is.
- **Beta / correlation** (needs `history` per name + `index_history`, both
  short D1 close series): `beta_correlation` is an OLS of the name's returns on
  the index's — `beta = cov / var(index)`, Pearson `correlation`,
  `r_squared`, `alpha_daily`. `None` for names with < 3 usable closes or a
  flat index series.
- `index_change_pct` uses a real index quote (`index_ltp` vs `index_prev_close`)
  when supplied, else falls back to `net_contribution_pct`.
- `algo_version` (`ALGO_VERSION`) + `index_constituents_version`
  (`INDEX_CONSTITUENTS_VERSION`, currently `0.1.0`).

---

## 3. Read path — `app.api.services.index_constituents`

For an `INDEX` instrument:

1. `weight_rows_for(db, contract_key)` → the latest (or `effective_date`) set.
   No rows ⇒ `404` ("run `analytical-index-weights load`").
2. If any constituent has a `provider_symbol`, one batched
   `provider.fetch_full_quote([...])` (plus the index's own key) fills
   `ConstituentQuote(ltp, prev_close)` and `index_ltp` / `index_prev_close`.
   Provider errors degrade to the static view (no exception) — consistent with
   "built against the stub, lights up with a real token".
3. `include_beta=true` additionally fetches ~`lookback` (default 60) D1 closes
   per name **and** for the index (`fetch_ohlcv`, one call each) — a heavier
   read; skipped otherwise.
4. `build_constituent_view(...)`. Computed on read, **not persisted**.

**`as_of_date`** (past-data analysis): steps 2–3 swap the live
`fetch_full_quote` for a per-name `fetch_ohlcv(D1)` call over a window ending
at `as_of_date`, 23:59 IST. Each name's closes are reduced to the last trading
day on or before `as_of_date` (`ltp`) and the one before that (`prev_close`) —
the same contribution/breadth math then runs unchanged on those two numbers
instead of a live quote. `include_beta`'s history window is anchored the same
way, so beta/correlation reflect the replayed date, not today. `weight_rows_for`
is **not** re-anchored to `as_of_date` — weights are seeded reference data with
one vintage in practice, so the latest (or explicit `effective_date`) set is
still used. `422` if `as_of_date` is in the future.

---

## 4. API — `GET /instruments/{index_id}/constituents`

`docs/07` §4.14. Query: `effective_date` (default: latest loaded),
`include_beta` (default `false`), `lookback` (5–500, default 60), `as_of_date`
(ISO date — historical replay, see §3). `404` when the id is not an `INDEX` or
no weights are seeded; `422` if `as_of_date` is in the future; `502` on a
provider error while `include_beta` is set. Response mirrors `ConstituentView`
+ `index_id` + `historical` (true when `as_of_date` was used).

---

## 5. Frontend

`ConstituentsPanel` on the **instrument-detail screen for an `INDEX`** (`docs/08`).
An intro line, a summary strip (index change %, top-5/10 weight, HHI, and — when
quotes resolved — advances/declines, weighted A/D, "move carried by top 5"), a
sector table, then the constituent table ordered by weight: `# · symbol ·
sector · weight % · cum % · chg % · contrib pts · contrib % · rank` with a
**beta / corr** toggle that adds two columns and asks the API for
`include_beta`. A **date** picker (max: today) sends `as_of_date` and replays
that past session's contribution/breadth in place of the live view — a
"historical: YYYY-MM-DD" badge replaces the live source badge, and a "back to
live" link clears it. Table only; "descriptive — not a signal".

---

## 6. Not in scope (yet)

- Auto-refresh of weights from niftyindices (a scraper + its own validation).
- Ingesting the constituents as tracked instruments (history, intraday
  contribution trace, per-name analyses) — a real universe-policy change
  (`docs/04`).
- BANKNIFTY / SENSEX seed CSVs (the table + code are index-generic; only the
  NIFTY 50 seed ships).
- Divisor-accurate contribution; sector indices; any wiring into scoring.
