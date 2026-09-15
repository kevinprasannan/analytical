# 11 — Provider Validation Requirements (Upstox)

**Purpose (resolves C2, C3, H3; addresses review §14 hidden assumptions and
strategic directive 23).**

Nothing about the Upstox API is treated as known until the corresponding item
below is either **`CONFIRMED`** against official Upstox documentation / a sandbox
test (with a link and a date), or **`ACCEPTED_FALLBACK`** with a documented
fallback recorded here. Those two strings, plus `OPEN`, are the exact `status`
vocabulary in `docs/11-provider-validation.status.yaml`.

**Phase 2 (provider abstraction + ingestion) build is BLOCKED** until every
`blocks_phase_2` item (PV-1…PV-7) is `CONFIRMED` or `ACCEPTED_FALLBACK`. The gate
is **enforced mechanically**, not by judgment — see §0.

The spec deliberately supports both branches of each uncertain item so that the
data model and engine do not need redesigning once validation completes.

---

## 0. Mechanical enforcement

The authoritative status is the machine-readable file
[`docs/11-provider-validation.status.yaml`](11-provider-validation.status.yaml).
The prose in §1–§2 is the narrative; the `.yaml` is what the gate reads.

Three keyed-off enforcement points, all reading that one file:

1. **CI job `provider-validation-gate`** (`docs/09` §4). Fails the build when:
   - any PV-1…PV-7 row is `OPEN` **and** `backend/app/providers/upstox/`
     contains more than its declared stub set; or
   - a row is `CONFIRMED` with an empty `evidence`; or
   - a row is `ACCEPTED_FALLBACK` with an `fallback_ref` that does not resolve
     to a heading/anchor in this document; or
   - a `status` value is outside the vocabulary
     (`OPEN | CONFIRMED | ACCEPTED_FALLBACK`); or
   - PV-2 / PV-4 are resolved without a `branch` value.
2. **Upstox adapter startup guard** (`docs/02` §3.2). `app/providers/upstox/`
   refuses **all** live calls while any PV-1…PV-7 row is `OPEN`, so a local run
   cannot bypass the gate either.
3. **Roadmap gate** (`docs/10` Phase 1.5). Phase 1.5 exit is literally
   "`provider-validation-gate` is green"; Phase 2 `entry` references the same
   job.

PV-8 is `blocks_phase_2: false` (LOW, future-only) and is exempt from points 1–3.

## 1. Status summary

Rendered from `docs/11-provider-validation.status.yaml`; the CI gate asserts this
table matches the file. **Phase 1.5 completed 2026-08-27 — evidence in §4.**

| # | Item | Status | Blocks |
|---|------|--------|--------|
| PV-1 | Authentication & access-token lifecycle | **ACCEPTED_FALLBACK** | C2, unattended operation, `provider_credentials`, scheduler auth handling |
| PV-2 | Native candle intervals (1m / 5m / 15m / 60m / day) | **ACCEPTED_FALLBACK** | H3, ingestion aggregation need, Market Profile source timeframe |
| PV-3 | Historical depth per interval | **CONFIRMED** | H1 (index 200-SMA / Golden Cross), backfill scope, retention |
| PV-4 | Intraday Open Interest availability & granularity | **CONFIRMED** | C3, `open_interest` vs `oi_snapshots` model, OI analysis scope (SNAPSHOT vs PER_TIMEFRAME), OI scoring factor |
| PV-5 | Rate limits & quotas | **CONFIRMED** | M24 throughput budget, bounded concurrency limits, cycle cadence feasibility |
| PV-6 | Instrument master format & fields | **CONFIRMED** | Instrument registry, M3 (expiry kind), M4 (strike step), H6 (expiry policy) |
| PV-7 | Candle timestamp semantics & response timezone | **CONFIRMED** | H2 / H11 normalization (bar-open UTC convention) |
| PV-8 | Corporate actions / index constituents | **ACCEPTED_FALLBACK** (non-blocking) | Not required for index/derivative V1; note only |

**Resolved branches:** PV-2 → `AGGREGATE_FROM_M1` · PV-4 → `A_PER_CANDLE`.

To change an item: edit the `.yaml` (`status`, `evidence` **or**
`fallback_ref`, `decided_on`, and `branch` for PV-2/PV-4), update the matching
row above and the §4 evidence, and confirm `provider-validation-gate` passes.

---

## 2. Detail

### PV-1 — Authentication & access-token lifecycle
**What we need confirmed**
- OAuth flow type and redirect requirements.
- Access-token TTL (hours? until end of day?).
- Whether a refresh token exists, its TTL, and whether **unattended** refresh is
  possible without human interaction.
- Behaviour on expiry (error shape / status code).

**Why it matters**
`docs/10` Phase 6 exit expects the platform to run unattended across trading
days. If tokens require a daily interactive login, "self-updates every cycle" is
false without a fallback.

**Accepted fallback (if no unattended refresh)**
- Token supplied via `provider_credentials` (or env for V1) and refreshed by a
  documented **once-per-day manual step** performed by the owner before the
  session.
- On expiry mid-session: `ingestion_watermarks.last_status = AUTH_FAILED`;
  `/health/ready` reports `provider_auth = EXPIRED`; the current cycle marks all
  provider-dependent instruments `SKIPPED` in `run_instrument_status`; the worker
  does **not** crash and retries next cycle.
- A minimal authenticated local endpoint (or CLI command) accepts a fresh token
  at runtime without a redeploy.

**The once-per-day step (`analytical-provider login`, 2026-08-31).** Needs the
Upstox app's `ANALYTICAL_UPSTOX_API_KEY` / `_API_SECRET` / `_REDIRECT_URI`
(from developer.upstox.com). `login` prints the `…/v2/login/authorization/dialog`
URL, the owner approves in a browser and pastes the redirected `?code=…` URL, and
the command POSTs `…/v2/login/authorization/token` (`grant_type=authorization_code`)
and stores the returned `access_token` in `upstox_token_file`. `app/providers/
upstox/oauth.py` + `cli.py`. `set-token` (paste a token you already have) still
exists.

**Impacts:** `docs/02` §5, §6.4, §6.6; `docs/03` `provider_credentials`;
`docs/07` `/health/ready`; `docs/12` `provider_auth_state`.

### PV-2 — Native candle intervals
**What we need confirmed**
- Which intervals the historical endpoint serves directly: `1minute`,
  `5minute` (or `Nminute`), `30minute`, `60minute`, `day`.
- Which intervals the "recent / intraday" (near-real-time) endpoint serves.
- Whether interval boundaries are exchange-session-anchored or wall-clock.

**Why it matters**
`docs/04`/`docs/05` require session-anchored `M5, M15, H1` bars. If any are not
native, or boundaries differ, the platform must aggregate.

**Accepted fallback (`branch: AGGREGATE_FROM_M1`)**
- Ingest `M1` (1-minute) natively and **aggregate locally** to session-anchored
  `M5 / M15 / H1` per `docs/05` §3.3 (`app/ingestion/aggregation.py`).
- Market Profile `source_timeframe` remains `M5` (native or aggregated).
- If session-anchored `M5/M15/H1` are confirmed native → `branch: NATIVE`.

**Intraday endpoint — CONFIRMED (2026-08-31).** The historical endpoint returns
**nothing for the current trading day** while it is in progress; the current
day's completed candles come from `GET /{ver}/historical-candle/intraday/
{instrument_key}/{unit}/{interval}` (same 7-element row shape: `[ts, o, h, l, c,
volume, oi]`; `minutes` 1–300 / `hours` 1–5 / `days` 1; no date args; ts is
bar-open `+05:30`). `app/providers/upstox/candles.py` fetches the current IST
trading day from `intraday` and prior days from `historical`, merges, and marks
the **last** intraday bar `is_final=False` (may still be forming). This is what
makes market data live during the session.

**Impacts:** `docs/02` §3.4; `docs/05` §3.2–3.3; `docs/04` §3.1; `docs/03`
`ohlcv_bars` (`M1` rows may be persisted or transient — decide at PV-2 close).

### PV-3 — Historical depth per interval
**What we need confirmed**
- Max lookback for `day` candles (need ≥ **250 trading days** for a 200-period
  SMA + a cross-search window on the INDEX series).
- Max lookback for intraday intervals (for backfill and for intraday indicators'
  warm-up).
- Any per-request row caps / pagination model.

**Why it matters**
Golden Cross on the INDEX (strategic directive 3) is only meaningful with
sufficient daily history. Retention windows in `docs/03` §6 assume a certain
intraday depth is obtainable.

**Accepted fallback**
- If daily depth < 250 days: seed the INDEX daily series from a one-time
  historical import file (documented manual step), then maintain incrementally.
- If intraday depth is shallow: reduce intraday backfill target and document the
  warm-up lag before intraday indicators reach `warmup_ok`.

**Impacts:** `docs/10` Phase 2/3 entry; `docs/03` §6; `docs/05` §7.

### PV-4 — Intraday Open Interest availability & granularity
**What we need confirmed**
- Is OI available **per historical intraday candle**, **only as a live quote
  snapshot**, or **only end-of-day**?
- Latency / update frequency of live OI.
- Can OI history be reconstructed after the fact?

**Why it matters**
The OI analysis, its `SNAPSHOT` vs `PER_TIMEFRAME` scope, and the OI scoring
factor all depend on this.

**Branch A — per-candle intraday OI is available (`CONFIRMED`; `branch: A_PER_CANDLE`)**
- `open_interest` table populated, `analysis_scope = PER_TIMEFRAME`, `ts` =
  bar-open aligned to the OHLCV bar (`docs/05` §9.1).
- `change_lookback` expressed in periods.

**Branch B — snapshot / live only (`ACCEPTED_FALLBACK`, default assumption; `branch: B_SNAPSHOT`)**
- `oi_snapshots` table populated by polling once per cycle
  (`docs/03` §5.2). `open_interest` table is **not used** in V1.
- OI analysis runs at `analysis_scope = SNAPSHOT`; `change_lookback` expressed
  in snapshots (default 1) with `snapshot_ts` provenance.
- Retention and `current_analysis_results` handle SNAPSHOT scope identically to
  other scopes.

Both branches feed the **same** deterministic classifier (`docs/05` §9.3); only
the input source and scope differ. The engine code path is shared.

**Impacts:** `docs/03` §5.2, §5.3; `docs/05` §9; `docs/06` §3.1 (OI factor);
`docs/04` applicability matrix.

### PV-5 — Rate limits & quotas
**What we need confirmed**
- Requests/second, requests/minute, and any daily cap.
- Whether limits differ per endpoint (historical vs quote vs instrument master).
- Burst allowance and the throttling response (status code / headers).
- Whether the instrument master is a single bulk download.

**Why it matters**
`docs/02` §6.7 sets a per-cycle request budget and bounded-concurrency limits;
these must be sized to the real limits, not guessed. Cycle cadence feasibility
(`docs/01` §7) depends on it.

**Accepted fallback (until confirmed)**
- Conservative defaults: global provider-call semaphore = **4 concurrent**,
  ≤ **10 requests/second**, exponential backoff on any throttle response,
  `ingestion_watermarks.last_status = RATE_LIMITED` on exhaustion, instrument
  marked `DEGRADED` for the cycle, retried next cycle.

**Impacts:** `docs/02` §6.7; `docs/09` §2.7 (throughput test).

### PV-6 — Instrument master format & fields
**What we need confirmed**
- Format (CSV / JSON / gzip) and refresh cadence.
- Fields present: provider instrument key/token, `lot_size`, `tick_size`,
  `expiry` (and whether **weekly vs monthly** is distinguishable), `strike`,
  `option_type`, freeze quantity, trading status.
- How **expired** contracts are represented (dropped vs flagged).
- The strike ladder / strike step per underlying (or must it be inferred).

**Why it matters**
Instrument registry population, option contract identity (M3), strike step (M4),
and the futures/option selection policy (H6) all read from this.

**Accepted fallback**
- If weekly/monthly is not directly distinguishable: derive `expiry_kind` by
  rule (last expiry of a calendar month for that underlying = `MONTHLY`, others
  = `WEEKLY`) and record the rule in `docs/04` §2.4.
- If strike step is absent: configure it per underlying in `app_settings`
  (`option_selection.strike_step.NIFTY = 50`, `.BANKNIFTY = 100`) — default
  path anyway (M4).
- **Do not assume BANKNIFTY weekly options exist** — take only what the master
  lists (H6).

**Impacts:** `docs/04` §2.3–2.4; `docs/03` `instruments`.

### PV-7 — Candle timestamp semantics & response timezone
**What we need confirmed**
- Are candle timestamps **bar-open** or bar-close?
- What timezone are they returned in (IST offset, UTC, epoch)?

**Why it matters**
The whole model uses **bar-open, UTC** (`docs/03` §2, resolves H2). Normalization
must convert correctly and consistently.

**Accepted fallback**
- Normalization layer detects and converts to bar-open UTC; a normalization test
  pins the expected mapping (`docs/09` §2.4). If the provider returns bar-close,
  ingestion subtracts one interval to derive bar-open.

**Impacts:** `docs/02` §3.4; `docs/05` §3; `docs/09` §2.4.

### PV-8 — Corporate actions / index constituents
Not required for V1 (index level + index derivatives only). Recorded so it is
not silently assumed away when equities are added later.

---

## 3. Exit criteria (== `provider-validation-gate` is green)

- `docs/11-provider-validation.status.yaml`: every `blocks_phase_2: true` item
  (PV-1…PV-7) is `CONFIRMED` (with `evidence`) or `ACCEPTED_FALLBACK` (with a
  resolvable `fallback_ref`).
- `branch` recorded for PV-2 (`NATIVE` | `AGGREGATE_FROM_M1`) and PV-4
  (`A_PER_CANDLE` | `B_SNAPSHOT`).
- PV-1: an unattended refresh is `CONFIRMED`, or the manual-daily-token fallback
  is `ACCEPTED_FALLBACK` (owner-approved).
- §1 table in this document matches the `.yaml` (the gate asserts this).
- `docs/02`, `docs/03`, `docs/04`, `docs/05`, `docs/10` cross-references updated
  with the chosen branches.
- The `provider-validation-gate` CI job passes.

Until all of the above hold, the Upstox adapter refuses live calls and Phase 2
does not begin.

---

## 4. Validation results — Phase 1.5 (2026-08-27)

Method: first-hand download of the public Upstox instrument master (no auth) +
review of official Upstox developer documentation (fetched and quoted, dated) +
Upstox staff community statements. **No authenticated live API call was made**
(no credentials available); items that would benefit from a live check carry an
explicit Phase-2 entry checkpoint. Nothing below is marked `CONFIRMED` on the
strength of a documentation *hint* — only on an explicit documented contract, a
first-hand artifact, or a staff statement.

### PV-1 — Authentication → `ACCEPTED_FALLBACK`
- **Sources:** Get Token API, Authentication, Access Token Request pages; Upstox
  staff community reply (URLs + date in the `.yaml`).
- **Observed:** OAuth 2.0 authorization-code flow. `access_token` "validity
  period that lasts until 3:30 AM the following day, regardless of the time it
  was generated." Token response fields listed with **no `refresh_token`**. The
  notifier ("Access Token Request") flow **still requires human approval each
  time**. Upstox staff: "As per SEBI guidelines, you are required to log in to
  your account daily." An `extended_token` is returned ("prolonged usage,
  primarily read-only") but its validity period and eligibility are **not
  documented**.
- **Conclusion:** No unattended token renewal exists (regulatory, not just
  technical). The documented **daily-manual-token fallback** applies — already
  implemented in Phase 1 (`provider_auth_state=EXPIRED` → instruments `SKIPPED`,
  worker does not crash; runtime token entry). `extended_token` is flagged for
  Phase-2 evaluation as a possible unattended read-only path; the auth seam
  already supports runtime token replacement, so adopting it later needs no spec
  change.
- **Architecture impact:** `docs/10` Phase 6 "unattended across trading days" →
  read as "unattended *within* a trading day after a once-daily manual token
  refresh (before ~09:00 IST); degrades to `SKIPPED` on mid-session expiry and
  recovers when a fresh token is supplied." No schema/engine change.

### PV-2 — Candle intervals & boundaries → `ACCEPTED_FALLBACK`, `branch: AGGREGATE_FROM_M1`
- **Sources:** v3 Historical Candle Data API, v3 Intraday Candle Data API.
- **Observed:** `unit=minutes` interval `1..300`; `unit=hours` interval `1..5`;
  `unit=days` interval `1`. So 1 / 5 / 15 minute, 60 minute and daily are all
  offered. Intraday endpoint = current trading day only; prior days via the
  historical endpoint. Timestamps are ISO 8601 `+05:30`, candle **start** time.
  Real intraday 15-min sample starts: `…T14:45:00+05:30`, `…T15:15:00+05:30`
  (on the wall-clock 15-min grid, which coincides with the NSE-session grid
  because 09:15 is a grid point for 1/5/15 min). **No official statement or
  sample establishes whether 60-minute candles are anchored to the 09:15 session
  open or to wall-clock hours.**
- **Conclusion:** 1-minute is confirmed native (from Jan 2022). H1
  session-anchoring cannot be verified without a live test, and `docs/05` §3.3
  mandates session-anchored H1 (09:15–10:15…). Ingest **M1** and aggregate
  locally to the NSE session grid for M5/M15/H1 (`app/ingestion/aggregation.py`,
  `docs/05` §3.3/§3.5). D1 stays native (`unit=days`).
- **Architecture impact:** `docs/02` §8 open item "M5/M15/H1 native vs
  aggregate-from-M1" → **AGGREGATE_FROM_M1**. `M1` rows persisted, 10-day
  retention (already in `docs/03` §6). Market Profile `source_timeframe = M5`
  (aggregated). Confirms the aggregation component is required.

### PV-3 — Historical depth → `CONFIRMED`
- **Sources:** v3 Historical Candle Data API; Expired Historical Candle Data API.
- **Observed:** `days` from **January 2000**, 1 decade per request. `minutes`
  1–15 from **January 2022**, 1 month per request. `minutes` >15 and `hours` from
  Jan 2022, 1 quarter per request. Over-limit requests error out. Expired
  dated-contract history (with OI) exists via `/expired-instruments/
  historical-candle/…` but **requires an "Upstox Plus plan subscription."**
- **Conclusion:** Daily INDEX depth (Jan 2000) vastly exceeds the ≥250-trading-
  day requirement for the 200-SMA Golden Cross — the PV-3 fallback (one-time
  daily import file) is **not** triggered. Intraday depth ≈ 4.5 years,
  paginated. Expired-contract intraday history is a paid add-on **not required
  for V1** (dated-contract long-lookback analyses are `NOT_APPLICABLE` by
  design; backtesting is future work).
- **Architecture impact:** ingestion backfill paginates ≤ 1 month/request for
  M1, ≤ 1 quarter for hours/>15-min (`docs/02` §3.4, `docs/10` Phase 2). No
  manual daily-import file needed. Retention windows sit well within provider
  depth.

### PV-4 — Intraday Open Interest → `CONFIRMED`, `branch: A_PER_CANDLE`
- **Sources:** v3 Historical Candle Data API, v3 Intraday Candle Data API,
  Expired Historical Candle Data API — **three independent official pages.**
- **Observed:** the candle response on all three is a **7-element array whose
  7th element is Open Interest** ("total number of outstanding derivative
  contracts"), returned by the same endpoints that serve OHLCV, at every
  supported interval (1..300 min, hours, days).
- **Conclusion:** per-candle historical + intraday OI is part of the documented
  response contract. **Branch A (`A_PER_CANDLE`) adopted**, replacing the
  previous `B_SNAPSHOT` default. OI is ingested from the same candle response as
  OHLCV; `analysis_scope = PER_TIMEFRAME`; `open_interest` table active;
  `oi_snapshots` reserved/unused in V1; `change_lookback` in periods. Under
  `AGGREGATE_FROM_M1`, per-M1 OI aggregates as **last value in period** (OI is a
  level; `docs/05` §3.5).
- **Phase-2 entry checkpoint:** the first authenticated smoke test **must**
  confirm element 7 is actually populated (non-null, plausible) for a live NSE
  F&O intraday minute candle. If it is not, flip to the pre-designed
  `B_SNAPSHOT` branch — a **config-only** change (`oi_mode=SNAPSHOT`,
  `has_intraday_oi=false`); both tables already exist, no migration.
- **Architecture impact:** `docs/02` §8 "OI scope" default → **PER_TIMEFRAME
  (branch A)**. `docs/03` §5.2 `open_interest` is the active OI store.
  `docs/04` §2.1 `has_intraday_oi` default → `true` for FUTURE/OPTION; §4 OI
  applicability scope → `PER_TIMEFRAME`. `docs/05` §9.1 branch A active.
  `docs/06` §3.1 OI factor reads `open_interest`. Phase-1 stub alignment
  (`STUB_CAPABILITIES.oi_mode`, `Instrument.has_intraday_oi` default) is a
  Phase-2 entry task — the applicability code already derives scope from
  `provider.capabilities().oi_scope()`, so it adapts automatically.

### PV-5 — Rate limits → `CONFIRMED`
- **Sources:** official Rate Limits page.
- **Observed:** "Other Standard APIs" (Historical + Intraday Candle Data fall
  here): **50 req/sec, 500 req/min, 2000 req/30 min**, enforced per-API
  per-user. No daily quota documented. "Exceeding these limits might result in
  temporary suspension of access" (HTTP status not stated on the page; expected
  429). Instrument master is a single public bulk download (PV-6).
- **Conclusion:** peak defaults (`PROVIDER_CONCURRENCY=4`, ≤ 10 req/s) are within
  50 req/s. The **binding constraints are 2000 req/30 min (≈ 1.1 req/s
  sustained) and 500 req/min (≈ 8.3 req/s sustained).**
- **Architecture impact (`docs/02` §6.7):** keep `PROVIDER_CONCURRENCY=4`; add
  `PROVIDER_MAX_RPS=8` and a rolling `PROVIDER_30MIN_BUDGET=1800` (10% headroom
  under 2000); exponential backoff on throttle (confirm exact HTTP status on the
  first authenticated call); `ingestion_watermarks.last_status=RATE_LIMITED` +
  instrument `DEGRADED` (already designed). Cycle-budget rule:
  `requests_per_cycle × (1800 / cycle_interval_seconds) ≤ PROVIDER_30MIN_BUDGET`.
  With ≈ 94 instruments (one M1 incremental fetch each — OI rides along under
  branch A) and `cycle_interval_seconds = 180`: ≈ 940 requests / 30 min,
  comfortably under 1800. The **confirmed Phase-0 cadence (180 s) and universe
  size (~94) are compatible with the confirmed limits** — no cadence change.

### PV-6 — Instrument master → `CONFIRMED`
- **Sources:** **first-hand download** of
  `https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz`
  (public, no auth, HTTP 200, `application/gzip`, daily refresh, 1.88 MB,
  75,294 NSE rows).
- **Observed fields per record:** `instrument_key`, `exchange_token`,
  `trading_symbol`, `name`, `exchange`, `segment`, `instrument_type`,
  `lot_size`, `minimum_lot`, `tick_size`, `freeze_quantity`, `qty_multiplier`,
  `strike_price`, `expiry` (epoch **ms**), **`weekly` (boolean)**,
  `underlying_symbol`, `underlying_key` (e.g. `NSE_INDEX|Nifty 50`),
  `asset_symbol`/`asset_key`, `asset_type`/`underlying_type`, `isin` (EQ only),
  `last_trading_date` (null on observed F&O rows).
- **Verified against live data:** NIFTY 50 = `NSE_INDEX|Nifty 50` / `NIFTY`;
  Nifty Bank = `NSE_INDEX|Nifty Bank` / `BANKNIFTY`. NIFTY & BANKNIFTY futures
  = 3 serial monthly contracts (`weekly=false`). **NIFTY options have 4 weekly
  (`weekly=true`) expiries + monthly/quarterly/far; BANKNIFTY options have ZERO
  weekly expiries (monthly only).** NIFTY option strike step = uniform **50**;
  BANKNIFTY ≈ **100** near ATM (wider at wings). Expired contracts are **dropped**
  from the file.
- **Conclusion:** all registry fields present. **Weekly vs monthly is directly
  distinguishable via the `weekly` boolean** → `expiry_kind` primary rule = the
  `weekly` flag; the "last-expiry-of-month" heuristic drops to a secondary
  tiebreak (MONTHLY vs QUARTERLY among `weekly=false`). The docs/11 warning
  "do not assume BANKNIFTY weekly options" is **confirmed true against live
  data.** No `strike_step` field → per-underlying `app_settings` config
  (NIFTY=50, BANKNIFTY=100, per M4). `contract_key` = platform-stable identity
  from `underlying_symbol + expiry_date + strike + option_type`;
  `provider_instrument_map.provider_symbol` = the volatile `instrument_key`.
- **Architecture impact:** `docs/04` §2.4 `expiry_kind` derivation → primary =
  `weekly` flag. `docs/03` `instruments.expiry` = epoch-ms normalised to a date
  in IST. Session-stable option universe (`docs/04` §2.3) has everything it
  needs from the daily master. No fallback triggered except strike-step-from-
  config (already the default).

### PV-7 — Candle timestamps → `CONFIRMED`
- **Sources:** v3 Historical + v3 Intraday Candle Data API (independent of PV-2's
  interval question).
- **Observed:** "Timestamps are ISO 8601 with timezone offset, example
  `2025-01-01T00:00:00+05:30`" and "They represent the candle **start** time
  (opening of the timeframe)." Real intraday sample starts `…T14:45:00+05:30`,
  `…T15:15:00+05:30` (15:15 start = the 15:15–15:30 NSE closing slot).
- **Conclusion:** timestamps are **bar-open** with an **IST (+05:30)** offset.
  Normalization = `fromisoformat` → `astimezone(UTC)`; **no** bar-close→bar-open
  subtraction (the PV-7 fallback contingency does not apply). Because the
  platform aggregates from M1 it re-derives M5/M15/H1 bar-open timestamps on the
  NSE session grid anyway.
- **Phase-2 checkpoint:** `docs/09` §2.4 normalization test pins an actual
  authenticated intraday sample (first candle `09:15:00+05:30` → `03:45:00Z`).

### PV-8 — Corporate actions / index constituents → `ACCEPTED_FALLBACK` (non-blocking)
- **Sources:** `docs/01` §5.1 (V1 universe = NSE index + index futures/options
  only, no equities cash).
- **Conclusion:** corporate actions (splits/bonus/dividends) affect equity
  price-series continuity, not index levels or index-derivative analysis; index
  constituents matter only for reconstructing an index from members, which V1
  does not do. **Not required for the V1 universe** — deferred to equities work.
  `blocks_phase_2: false`.

### Cross-references updated for the chosen branches (`docs/11` §3)

`docs/02` §8 (OI scope → PER_TIMEFRAME / branch A; M5/M15/H1 → AGGREGATE_FROM_M1;
token refresh → daily-manual; M1 persisted; + §6.7 rate-limit config);
`docs/03` §5.2 / §6 (OI store; M1 retention); `docs/04` §2.1 / §2.3–2.4 / §4
(`has_intraday_oi`, `expiry_kind` from `weekly`, OI scope); `docs/05` §3.3 / §9.1
(aggregate-from-M1; branch A); `docs/10` Phase 1.5 → PASS, Phase 2 entry
checkpoints.

---

## 5. Streaming feed — Upstox Market Data Feed v3 (WebSocket)

**Not part of the machine gate.** The `provider-validation-gate` job and
`docs/11-provider-validation.status.yaml` stay scoped to the Phase-2 **REST**
surface (PV-1..PV-8). Streaming was added after Phase 0 (lock lifted 2026-08-30 —
`.claude/CLAUDE.md` §3 / §3b); its provider requirements are tracked here as
prose and must be **confirmed against Upstox docs / a first-hand artifact before
Phase S3** (the real `app/providers/upstox/feed.py`). S1 (pure M1-from-ticks
builder) and S2 (`StreamingMarketDataProvider` seam + `StubMarketFeed`) do not
depend on any of this.

### 5.1 Confirmed 2026-08-31 (S3 built)

`protobuf` + `websockets` deps signed off by the owner (`.claude/CLAUDE.md`
decision 3.1). `app/providers/upstox/feed.py` (`UpstoxMarketFeed`) implements the
`StreamingMarketDataProvider` seam.

| # | Requirement | Finding (Upstox docs, 2026-08-31) | In the adapter |
|---|---|---|---|
| S-1 | Authorize + connect | `GET /v3/feed/market-data-feed/authorize` → `data.authorized_redirect_uri` = `wss://…/market-data-feeder/v3/…?requestId=…&code=…`; connect with `Authorization: Bearer <daily token>`. Token expiry mid-stream → socket drops; the streamer reconnects and re-authorises. | `_authorize()` + `_connect()`; token via `UpstoxAuthProvider` |
| S-2 | Message schema | protobuf, proto at `https://assets.upstox.com/feed/market-data-feed/v3/MarketDataFeed.proto`. **Subscribe/unsub/change_mode frames are sent as WebSocket BINARY** (`{"guid","method","data":{"mode","instrumentKeys"}}` JSON → bytes). Server frames are protobuf `FeedResponse` (no length prefix — one message per frame). | `MarketDataFeed.proto` + committed `MarketDataFeed_pb2.py`; `_sub_frame()` sends bytes; `FeedResponse.FromString` |
| S-3 | Modes & fields | `ltpc` / `full` / `option_greeks` / `full_d30`. **`full`** carries `MarketFullFeed{ltpc{ltp,ltt}, vtt (cumulative volume traded today), oi}` for F&O and `IndexFullFeed{ltpc, marketOHLC}` for an index (no volume/OI). | `_to_tick()` reads `vtt` → `cum_volume`, `oi` → `oi`; index → 0 / None |
| S-4 | Subscription limits | Standard tier: 2 connections/user; `full` up to **1,500 combined** instrument keys. The 313-key NIFTY universe fits one `full` subscription. | single `subscribe()` call with all keys |
| S-5 | Reconnect semantics | First frame = market status; second = snapshot; then live only (no replay). Server sends `ping`; `websockets` auto-`pong`s. | disconnect → `StreamIngestor.serve()` reconnect loop; **the periodic REST cycle fills any gap** (decision 3 — REST authoritative) |
| S-6 | Timestamp semantics | `LTPC.ltt` = last-traded epoch **milliseconds** (exchange time); `0` when absent → fall back to `FeedResponse.currentTs`. | `datetime.fromtimestamp(ltt/1000, UTC)`; `M1Accumulator` floors to the wall-clock minute (bar-open UTC) |
| S-7 | Off-hours behaviour | Socket stays open outside the session; pre-open/auction ticks may arrive. | the streamer is started/stopped around the session; ticks outside 09:15–15:30 IST produce bars only if `M1Accumulator` is fed them — the streamer process is session-scoped |
