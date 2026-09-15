# 01 — Product Specification

## 1. What this is (and is not)

**Analytical** is an **analytical decision-support system** for NSE index and
derivatives markets. On an intraday schedule it ingests market data, runs a
deterministic analysis engine, normalises each analysis into a factor score, and
combines those into a single **composite score** with a **confidence** value and
an **explainable hint**, presented as sortable tables.

**It does not, and will not in V1:**
- place brokerage orders or perform any automated execution;
- produce BUY / SELL / entry / exit / target / stop instructions — **except** the
  OI-based option-strategy suggestions resource (owner-authorised 2026-09-03,
  `docs/05` §11.5 / `docs/07` §4.13), which returns *illustrative* option
  structures with per-leg BUY/SELL behind a mandatory "not advice / not an order"
  disclaimer, and still never places an order;
- manage positions, portfolios, or P&L.

Output is a **read** on market posture. The discrete labels are analytical, not
directives: `STRONG_BEARISH, BEARISH, NEUTRAL, BULLISH, STRONG_BULLISH`.

## 2. Problem statement

An active trader/analyst working NIFTY / BANKNIFTY and their derivatives needs a
consolidated, repeatable, reviewable read on market state across Market Profile,
Open Interest, Volume, RSI, Bollinger Bands, EMA and moving-average structure.
Done by hand this is slow and inconsistent between sessions.

## 3. Target user

- **V1: a single internal user** — the project owner, running the platform
  locally via Docker Compose.
- V1 has a **global** configuration and a **global** tracked instrument
  universe. There are no per-user watchlists. Multi-user is deferred; the auth
  seam (`docs/02` §6.6) is a dependency swap plus new user-scoped tables, not a
  rewrite of domain tables.

## 4. Job to be done

> "On a regular intraday cadence, tell me the current technical posture of each
> instrument I track — per timeframe — with one score and one confidence value I
> can rank on, and let me see exactly which factors produced that score and
> why."

## 5. V1 scope

### 5.1 Instruments (strategic directive 2)

| Type | V1 instruments |
|------|----------------|
| **INDEX** | NIFTY 50, NIFTY BANK (BANKNIFTY) |
| **FUTURE** | NIFTY futures (near + next monthly), BANKNIFTY futures (near + next monthly) |
| **OPTION** | NIFTY options and BANKNIFTY options — a **session-stable** window of strikes around ATM, across the provider-listed active expiries (see `docs/04` §2.3). Weekly availability is taken from the instrument master, **not assumed** (BANKNIFTY may be monthly-only). |

Instruments are managed through an instrument registry and an
instrument-type abstraction (`INDEX / FUTURE / OPTION`). Nothing about specific
instruments is hard-coded in the analysis engine.

### 5.2 Analysis applicability is per instrument type (strategic directives 2, 3, 4)

Not every analysis runs on every instrument. Applicability is defined explicitly
in `docs/04` §4. Summary:

- **Long-lookback structure (Golden Cross 50/200)** is primarily an **INDEX**
  analysis. On dated FUTURE / OPTION contracts it is `NOT_APPLICABLE` by default
  (insufficient history); it is not pretended to be equivalent. Opt-in per
  instrument is possible and always carries a warning.
- **Open Interest** applies to **FUTURE / OPTION** only (`NOT_APPLICABLE` for
  INDEX).
- **Volume** applies where the provider supplies volume for that instrument;
  otherwise `NOT_APPLICABLE`.
- **Market Profile** (TPO + Volume Profile) applies to any instrument with an
  intraday session series; for deep-OTM options it may return
  `INSUFFICIENT_DATA`.
- **RSI, Bollinger, EMA** apply to all types on the timeframes where enough bars
  exist.

### 5.3 Timeframes

- User-facing analysis timeframes: **5 minute, 15 minute, 1 hour, Daily**.
- `M1` (1-minute) is an **ingestion/aggregation source only** — used when the
  provider does not serve session-anchored M5/M15/H1 natively (`docs/11` PV-2).
- All intraday timeframes are **anchored to the NSE session open** (`docs/05`
  §3).

### 5.4 Data cadence

- Intraday periodic ingest → analyse → score cycle; target cycle time **1–5
  minutes**.
- Streaming ingestion is **in scope but bounded** (lock lifted 2026-08-30,
  `.claude/CLAUDE.md` §3b): a WebSocket feed supplies only the **forming M1 bar +
  live OI**; the deterministic engine still runs on the periodic cycle; REST
  remains authoritative for history, backfill, and disconnect gap-fill; the
  streamer is a separate optional process. No tick-level analytical inputs.
- Exactly **one `analysis_run` per execution cycle**, covering all three phases
  (`docs/02` §4, `docs/03` §5.3).

### 5.5 Analyses (V1)

1. **Market Profile** — TPO Profile and Volume Profile (modular; shared value
   area / POC algorithm). POC, value area (default 70%), VAH/VAL, Initial
   Balance, range, profile-shape classification. Deterministic and configurable
   (`docs/05` §10).
2. **Open Interest** — level, deterministic change from stored OI values, and a
   four-quadrant behaviour classification with explicit epsilon tolerances
   (`docs/05` §9).
3. **Volume** — volume moving average, relative volume, spike flag, up/down
   split, trend; deterministic missing-volume behaviour.
4. **RSI** — Wilder's RSI (default period 14); state; deterministic
   zero-variation behaviour; basic divergence with a defined rule.
5. **Bollinger Bands** — 20 SMA basis, 2σ (population), %B, bandwidth, bandwidth
   percentile, squeeze (defined window).
6. **7 EMA** — EMA (default period 7), price position, slope state; exposes an
   ATR(14) auxiliary value for scoring.
7. **Golden Cross** — configurable fast/slow SMA (default 50 / 200) on the
   **INDEX** Daily series by default; defined crossover search window;
   `NOT_APPLICABLE` on dated contracts by default.

### 5.6 Scoring (strategic directives 1, 6, 7)

Every composite result is fully decomposable. For each factor the system records:

`factor · raw value(s) · normalized sub-score · confidence · weight ·
contribution · reason`

The final result object contains:

`composite score · confidence · raw label · effective label · factor
breakdown · warnings · explanation`

`explanation` is a **deterministic templated summary** (not an LLM). The
`rationale` dicts and `explanation` string are the seam for a future AI
narration layer.

### 5.7 Delivery surfaces

- Versioned REST API (`/api/v1`), OpenAPI as the contract.
- React + TypeScript + Vite + Tailwind + TanStack Query SPA: watchlist table,
  instrument detail (numeric panels + factor breakdown + explanation),
  run history, config. **No charts in V1.**

## 6. Explicit non-goals for V1

- No charts / graphical visualisation — one rough inline SVG on the astro day
  screen excepted (owner, 2026-09-03; `.claude/CLAUDE.md` §3b, `docs/13` §5.6.1).
- No order placement, execution, or position/P&L tracking. **No BUY/SELL output —
  except** the OI-based option-strategy suggestions (owner, 2026-09-03; `docs/05`
  §11.5, `docs/07` §4.13): illustrative structures with per-leg BUY/SELL, always
  disclaimed, never placed.
- No tick-level analytical inputs. (A WebSocket feed for the forming M1 bar +
  live OI **is** in scope — see §5 and `.claude/CLAUDE.md` §3b — but the engine
  never consumes ticks directly.)
- No backtesting engine. Provenance and data design **preserve** the ability to
  add it later (`docs/02` §7, `docs/03` §6) — it is not built in V1.
- No alerting/notifications.
- No multi-user accounts, roles, or login UI.
- No machine learning or AI-generated explanations (the deterministic
  `explanation` string is not ML).
- No mobile app (API stays mobile-friendly).
- No non-NSE markets, no equities cash.
- No TimescaleDB or other time-series database (schema stays partition-ready).

## 7. Success criteria for V1

- A full ingest → analyse → score cycle for the tracked universe completes
  within the target cadence on the owner's local machine, under a documented
  request budget (`docs/02` §6.7).
- Every analysis matches its hand-verified golden fixture and is deterministic:
  same inputs + same effective parameters (`params_hash`) + same `ALGO_VERSION`
  ⇒ identical `result` payload.
- Every composite score reproduces from stored provenance
  (`params_hash`, weights, factor rows).
- Adding a timeframe or an instrument requires config only — no analysis-engine
  code change.
- Swapping in the `MockProvider` requires implementing the provider protocol
  only — no engine / API / schema change.
- The dashboard and one instrument-detail view work end-to-end against the real
  API, with no charts, and every displayed score is explainable from the factor
  breakdown shown.

## 8. Example workflows

### W1 — Session posture check
Dashboard lists tracked instruments with composite score + effective label +
confidence for the selected timeframe (served from the current-scores
projection, not a historical scan). Sort by score, open BANKNIFTY 15m detail,
read the factor breakdown and explanation.

### W2 — Intraday re-check
The worker has run several cycles. Refresh; the dashboard shows updated scores
and `delta_vs_previous`. A `low_confidence` badge appears where the effective
label was clamped.

### W3 — Factor audit
User questions a `BULLISH` label on NIFTY futures. Instrument detail shows: OI
factor = `LONG_BUILDUP` (+50, confidence 0.7, weight 1.25, contribution +14),
Golden Cross = `NOT_APPLICABLE` (dated contract) with a warning, RSI neutral,
Bollinger mid-range. The `explanation` string summarises this in order of
contribution.

### W4 — Universe management
A new expiry becomes active. At the next **daily** universe fixing the option
selection policy adds the in-window strikes; the set is then stable for the
session (no per-cycle churn).
