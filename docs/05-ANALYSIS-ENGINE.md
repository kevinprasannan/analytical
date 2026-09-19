# 05 — Analysis Engine (`analytical_core`)

## 1. Design principles

1. **Pure.** No IO, no network, no DB, no FastAPI, no config-file reads. Inputs
   in, results out.
2. **Deterministic.** Same inputs + same effective parameters (`params_hash`) +
   same `ALGO_VERSION` ⇒ identical results **under the pinned numeric stack**
   (numpy version pinned; `math.fsum` used for session-length aggregations to
   remove summation-order sensitivity — resolves review L2).
3. **Instrument-agnostic.** Functions take series + parameters, never an
   `Instrument`. No branching on a specific instrument.
4. **Timeframe-agnostic.** A timeframe is a period length + label. Adding one
   needs no engine change.
5. **Explicit status.** `OK / INSUFFICIENT_DATA / NOT_APPLICABLE / ERROR` —
   never a partial or guessed number.
6. **Provenance on every result.** `meta` carries `algo_version`, `params_id`,
   `params_hash`, `input_window_start/end`, `bars_used`, `coverage_ratio`,
   `warmup_ok`, `last_bar_final` (resolves M19).
7. **Applicability is decided by the caller** (`app/analysis/`) from the matrix
   in `docs/04` §4. When an analysis does not apply to an instrument type, the
   caller records a lightweight `NOT_APPLICABLE` `analysis_results` row (with a
   `reason`) — it is **persisted**, not omitted, so the API / projection /
   scoring provenance have one explicit source. The engine also self-guards on
   structural conditions it can see (e.g. Volume returns `NOT_APPLICABLE` when
   the instrument capability `has_volume` is false; a transient all-zero window
   on a `has_volume` instrument returns `INSUFFICIENT_DATA`).

## 2. Numeric policy

- Internal math in `float64` (numpy). Prices enter as `float` (converted from
  `Decimal` by the caller).
- Output rounding, applied once at result construction: prices 4 dp, RSI 2 dp,
  ratios / %B / bandwidth 6 dp, EMA/SMA 4 dp, scores 6 dp.
- Session-length sums (Market Profile totals, value-area accumulation) use
  `math.fsum`.

## 3. Session & timeframe model (resolves H2, H3, H11)

### 3.1 NSE session (canonical)

- Timezone **IST = `Asia/Kolkata`, fixed UTC+05:30, no DST**.
- Continuous session **09:15:00–15:30:00 IST** for index + F&O. Length 375 min.
- Pre-open (09:00–09:15) and post-close are **excluded** from all analytical
  input.
- Actual per-date hours come from `market_calendar` (`session_open_ist`,
  `session_close_ist`); a shortened `NORMAL` day simply has different values and
  all logic below reads them. `MUHURAT` / `SPECIAL` sessions are **skipped** by
  V1 unless explicitly enabled.

### 3.2 Timestamp convention

- Every bar `ts` is the **bar-open instant, tz-aware UTC**. A bar with `ts = T`
  covers `[T, T + interval)`.
- 09:15:00 IST = 03:45:00Z.

### 3.3 Timeframe boundaries — anchored to the session open

All intraday grids start at `session_open`, not wall-clock midnight.

| TF | Grid (default 09:15–15:30) | Bars/day | Last bar |
|----|----------------------------|----------|----------|
| M1 | 09:15, 09:16, … 15:29 | 375 | 15:29–15:30 |
| M5 | 09:15, 09:20, … 15:25 | 75 | 15:25–15:30 |
| M15 | 09:15, 09:30, … 15:15 | 25 | 15:15–15:30 |
| H1 | 09:15–10:15, 10:15–11:15, 11:15–12:15, 12:15–13:15, 13:15–14:15, 14:15–15:15, **15:15–15:30 (partial 15 min)** | 6 full + 1 partial = 7 | partial, `meta.partial_bar = true` |
| D1 | one bar; `ts` = `session_open` instant in UTC for the trading date (default 03:45:00Z) | 1 | — |

- The **partial H1 bar** is a real bar: `is_final = true` at session close +
  grace, flagged `partial_bar`. Indicators treat it as one bar.
- A shortened session yields correspondingly fewer bars; the generic rule is
  `floor((close-open)/interval)` full bars plus one partial bar iff there is a
  remainder.

### 3.4 No-trade intervals (resolves M23, strategic directive 20)

- If no trade occurs in an interval, **no bar row exists** for it. The engine
  operates on the contiguous array it receives. Bars are **never** fabricated or
  carried forward.
- `OHLCVSeries.expected_grid_len` is the session-anchored period count; the
  engine computes `coverage_ratio = bars_used / expected_grid_len` and
  `gap_count` = missing interior periods.
- Per-indicator "minimum bars" is counted in **actual bars present**.
- If `coverage_ratio < min_coverage` (default **0.6**) the analysis returns
  `INSUFFICIENT_DATA` (`reason = "sparse series"`).

### 3.5 Provider-native vs aggregated bars (resolves H3; `docs/11` PV-2)

**RESOLVED `docs/11` PV-2, 2026-08-27: branch AGGREGATE_FROM_M1.** Upstox serves
native 1-minute candles (from Jan 2022) but does not document whether 60-minute
candles are anchored to the 09:15 NSE session open or to wall-clock hours, and
§3.3 requires session-anchored H1. So V1 always ingests **M1** and aggregates
M5/M15/H1 locally; **D1 is ingested natively** (`unit=days`). OI (branch A) rides
in the same M1 candle response and aggregates as the period's last value.

- Ingest **M1** and aggregate in `app/ingestion/aggregation.py` to the §3.3 grid:
  - `open` = first child open, `high` = max child high, `low` = min child low,
    `close` = last child close, `volume` = Σ child volume,
    `open_interest` = last child OI.
  - A target period with **zero** child M1 bars is **not emitted** (§3.4).
  - Aggregated bar `is_final` = (all covered child bars final) **and** (target
    period ended by ≥ `finalize_grace_seconds`).

### 3.6 `is_final` transition (resolves M15)

A bar flips `false → true` when its period ended by ≥ `finalize_grace_seconds`
(default **90**) **and** the provider returns it closed (or, for aggregation,
all child M1 bars are final). Until then it is the forming bar; results computed
against it carry `last_bar_final = false`.

---

## 4. RSI (resolves H10, M13)

- **Params:** `period` (14), `source` (`close`), `div_lookback` (14),
  `div_min_rsi_delta` (1.0).
- **Algorithm (Wilder):**
  1. `delta[i] = source[i] − source[i−1]`; `gain = max(delta,0)`,
     `loss = max(−delta,0)`.
  2. Seed `avg_gain` / `avg_loss` = simple mean of the first `period` gains /
     losses.
  3. Wilder smoothing: `avg = (avg·(period−1) + current) / period`.
  4. **Terminal value, in this exact precedence:**
     1. `avg_gain == 0 and avg_loss == 0` → **RSI = 50.0**
     2. elif `avg_loss == 0` → RSI = 100.0
     3. elif `avg_gain == 0` → RSI = 0.0
     4. else `RS = avg_gain/avg_loss`; `RSI = 100 − 100/(1+RS)`
  - A zero-variation series (all deltas 0) is case 1 ⇒ 50.0, deterministically.
- **Minimum bars:** `period + 1`. `warmup_ok = bars_used ≥ period·5`.
- **Divergence** (deterministic): window = last `div_lookback` bars **including**
  current, on `close`.
  - **Bullish**: `close[-1] == min(window_close)` **and**
    `rsi[-1] − rsi[argmin] ≥ div_min_rsi_delta`.
  - **Bearish**: `close[-1] == max(window_close)` **and**
    `rsi[argmax] − rsi[-1] ≥ div_min_rsi_delta`.
  - `argmin` / `argmax` ties → earliest index. Else `NONE`.
- **`values`:** `rsi`, `state` (`OVERBOUGHT ≥70 / OVERSOLD ≤30 / NEUTRAL`),
  `slope` (`rsi[-1] − rsi[-2]`), `divergence` (`BULLISH / BEARISH / NONE`).
- **`series` (optional):** `rsi[]` (leading nulls during warm-up).

## 5. Bollinger Bands (resolves M11)

- **Params:** `period` (20), `num_std` (2.0), `source` (`close`),
  `std_ddof` (**0**, population), `squeeze_lookback` (120).
- `basis = SMA(source, period)`; `dev = stdev(source[-period:], ddof=0)`;
  `upper = basis + num_std·dev`; `lower = basis − num_std·dev`.
- `percent_b = (source[-1] − lower) / (upper − lower)`.
- `bandwidth = (upper − lower) / basis`.
- **Degenerate `upper == lower`:** `percent_b = 0.5`, `bandwidth = 0.0`,
  `position = MIDDLE`.
- **Squeeze:** window = the `squeeze_lookback` **prior** bandwidth values
  (**excluding** the current bar). `squeeze = bandwidth[-1] ≤ min(prior_window)`.
  If fewer than `squeeze_lookback` prior values → `squeeze = null`.
- `bandwidth_percentile = count(prior_window < bandwidth[-1]) / len(prior_window)`
  (exclusive rank; null if window short).
- **`position`:** `ABOVE_UPPER` (`close ≥ upper`), `UPPER_HALF`
  (`basis ≤ close < upper`), `LOWER_HALF` (`lower < close < basis`),
  `BELOW_LOWER` (`close ≤ lower`), `MIDDLE` (degenerate).
- **Minimum bars:** `period` (squeeze needs `period + squeeze_lookback`).
- **`values`:** `basis, upper, lower, percent_b, bandwidth,
  bandwidth_percentile, squeeze, position`.

## 6. 7 EMA (resolves M14; ATR helper for scoring — C4)

- **Params:** `period` (7), `source` (`close`), `seed` (`sma`),
  `slope_lookback` (3), `slope_flat_eps_pct` (0.0002 = 0.02%).
- `k = 2/(period+1)`; seed EMA = SMA of the first `period` present values;
  `ema[i] = source[i]·k + ema[i−1]·(1−k)`.
- **Slope:** needs `slope_lookback` EMA values after the seed. Minimum bars for a
  slope = `period + slope_lookback`; below that `slope = null`,
  `slope_state = UNKNOWN`.
  `slope = ema[-1] − ema[-1-slope_lookback]`;
  `eps = slope_flat_eps_pct · ema[-1]`;
  `slope_state = RISING (slope > eps) / FALLING (slope < −eps) / FLAT`.
- **Volatility auxiliaries (for scoring — resolves C4):** the engine computes
  Wilder ATR over the same OHLC series (period 14, configurable) → `aux.atr14`
  (null if `< 15` bars), and a fallback `aux.close_stdev_n` = stdev of the last
  `n` closes (`n = slope_lookback·5`, default). These are shared helpers, not
  standalone `analysis_key`s.
- **`values`:** `ema`, `price_vs_ema` (`close[-1] − ema[-1]`), `price_above`
  (bool), `slope`, `slope_state`. **`aux`:** `atr14` (nullable), `close_stdev_n`.

## 7. Golden Cross (resolves M12, H1; strategic directive 3)

- **Params:** `fast_period` (50), `slow_period` (200), `ma_type` (`SMA`;
  `EMA` allowed), `source` (`close`), `cross_search_window` (60 bars,
  configurable), `recent_window` (10), `enable_for_dated` (**false**).
- **Applicability:**
  - `INDEX` → normal path; Daily is the default series.
  - `FUTURE` / `OPTION` → if `enable_for_dated = false` → **`NOT_APPLICABLE`**
    (`reason = "dated contract history shorter than slow_period; index trend is
    represented by the INDEX instrument"`). If `true` → normal path, but every
    result carries `warnings = ["computed on a dated-contract series; not
    equivalent to the index golden cross"]`.
- **Minimum bars:** `slow_period + 1` for `state`; below → `INSUFFICIENT_DATA`.
- **Cross detection:** `d[i] = sign(fast[i] − slow[i])` with `sign(0) = 0`. Scan
  the last `min(cross_search_window, available)` bars oldest→newest. Carry the
  last non-zero sign across zeros. A **golden** cross is where the carried sign
  goes `− → +`; a **death** cross `+ → −`, recorded at the bar where the new
  sign is established.
- **`values`:** `fast`, `slow`, `state` (`ABOVE` if `fast[-1] > slow[-1]` else
  `BELOW`), `cross_type` (`GOLDEN / DEATH / NONE_IN_WINDOW`), `cross_ts`
  (null if none), `bars_since_cross` (null if none),
  `separation = (fast[-1] − slow[-1]) / slow[-1]`,
  `recent = bars_since_cross is not null and ≤ recent_window`,
  `provisional = (cross occurred on the non-final last bar)`.
- **Frontend alert** (`docs/08` §4.2): the per-timeframe panel takes an emerald
  (`GOLDEN`) / rose (`DEATH`) accent + call-out when `recent` is true; the
  regime (`state`) and cross type are colour-coded regardless.
- **Multi-timeframe read grid** (owner-authorised 2026-09-08): `GET
  /instruments/{id}/golden-cross-grid` (`docs/07` §4.19) runs this same pure
  indicator over **5m / 15m / 1h / 1D** as parallel columns — a read view, not
  an engine analysis (not persisted, not scored, no version guard). INDEX → all
  four `OK`; dated FUTURE / OPTION → `NOT_APPLICABLE` per timeframe.
  **Extended 2026-09-15 (owner — "need alert like 200 moving average near by
  support and resistance"):** each column also reads the fast/slow MAs as
  dynamic support/resistance — `last_price`, `dist_to_fast_pct` /
  `dist_to_slow_pct` (`(last_price − MA) / MA`, signed), `near_fast` /
  `near_slow` (`|dist| ≤ golden_cross.near_ma_pct`, default 0.3% — an
  `app_settings` key, read-view-only, not in `analytical_core.params` so it
  never touches the scored `golden_cross` analysis's `params_hash`), and
  `nearest_ma` / `nearest_ma_side` (`FAST`/`SLOW`, whichever is nearer and
  within the band, wins when both `near_fast` and `near_slow` are true — e.g.
  just after a golden/death cross, when the two MAs sit close together;
  `SUPPORT` when price sits above that MA, `RESISTANCE` below). A missing MA
  (insufficient history for that period) is skipped, not an error.
  `GOLDEN_CROSS_GRID_VERSION` `0.1.0` → **`0.2.0`**.
  **Extended 2026-09-16 (owner — "DMA 50 200 like need EMA one box"):** each
  column also reports `ema_fast` / `ema_slow` — the same `fast_period` /
  `slow_period` computed as an **EMA**, via a second `golden_cross()` call
  with `overrides={"ma_type": "EMA"}`, regardless of the column's own
  configured `ma_type` (default `SMA`). Purely a supplementary read alongside
  the DMA cross — `state` / `cross_type` / `near_fast` / `near_slow` /
  `nearest_ma` are all still driven by the one configured `ma_type` only, not
  duplicated for EMA (no second cross-state, no second near-MA alert).
  `null` when there isn't enough history for that period, independent of the
  primary read's `status`. `GOLDEN_CROSS_GRID_VERSION` `0.2.0` → **`0.3.0`**.
  **Fix 2026-09-16 (owner-flagged — "200 EMA showin 24300 around but in our
  analytical showin 24453 ? D1"):** `_GC_GRID_LOAD` (bars fetched per column)
  was `280` — enough for the 200-bar *SMA* window but far too little for the
  *EMA* to actually converge, since an EMA is a recursive average that keeps a
  decaying memory of bars before the window; seeded from ~280 bars (only ~80
  past the SMA seed) it landed well off a broker/charting platform's
  full-history EMA(200). Raised to `1500` (all four timeframes have far more
  history than that) — EMA(200)'s exponential weight (`k = 2/201`) is
  `> 99.99%` converged by then (`(1-k)^1500 ≈ 6e-7`). Verified: NIFTY D1
  `ema_slow` moved from `24453` to `24286`, matching the owner's reference.
  `GOLDEN_CROSS_GRID_VERSION` `0.3.0` → **`0.3.1`**.

## 8. Volume (resolves H9)

- **Params:** `ma_period` (20), `spike_mult` (2.0), `rvol_lookback` (20),
  `trend_flat_eps_pct` (0.05).
- **Applicability guard:** the caller passes `has_volume` (instrument
  capability). `has_volume == false` → **`NOT_APPLICABLE`**
  (`reason = "instrument/provider has no volume"`) — structural. If
  `has_volume == true` but `sum(volume over the window) == 0` (a real
  no-trade stretch) → **`INSUFFICIENT_DATA`** (`reason = "no traded volume in
  window"`), so an instrument that is expected to have volume still incurs the
  scoring confidence penalty (`docs/06` §4).
- `vol_ma = SMA(volume, ma_period)`.
- `rvol = volume[-1] / mean(volume[-1-rvol_lookback:-1])`; if the denominator is
  0 → `rvol = null`.
- `spike = volume[-1] ≥ spike_mult · vol_ma[-1]`.
- Up/down split over `ma_period`: bar is "up" if `close ≥ open`. If the down
  count is 0 → `up_down_ratio = null`, `up_down_state = ALL_UP`; if the up count
  is 0 → `up_down_ratio = 0.0`, `up_down_state = ALL_DOWN`; otherwise
  `up_down_ratio = up/down` and `up_down_state ∈ {MORE_UP, MORE_DOWN, BALANCED}`
  (`volume_up_down_state`, `docs/12`).
- `trend` = sign of the OLS slope of `volume` over `ma_period`, with
  `flat_eps = trend_flat_eps_pct · vol_ma[-1]` → `RISING / FALLING / FLAT`.
- **`aux.price_change_pct_recent`** = `close[-1] / close[-1-rvol_lookback] − 1`
  (for the Volume sub-score — resolves C4).
- **`values`:** `volume, vol_ma, rvol, spike, up_down_ratio, up_down_state,
  trend`.

## 9. Open Interest (resolves M7, M8; `docs/11` PV-4; strategic directive 16)

### 9.1 Input & scope

**RESOLVED `docs/11` PV-4, 2026-08-27: branch A_PER_CANDLE.** The Upstox v3
candle response carries per-candle OI as element 7 (three official pages).

- **Branch A (active):** `scope = PER_TIMEFRAME`; input aligned 1:1 (equal `ts`,
  bar-open) to `ohlcv_bars` — OI is ingested from the same candle response as
  OHLCV. Under `AGGREGATE_FROM_M1`, per-M1 OI aggregates to the period as the
  **last** value in the period (OI is a level, not a flow — `docs/05` §3.5).
  `change_lookback` counts periods (default 1).
- **Branch B (reserved fallback):** `scope = SNAPSHOT`; input from `oi_snapshots`
  (poll instants). Used only if the Phase-2 entry smoke test finds intraday
  per-candle OI unpopulated — a config-only flip.
- The classifier below is identical for both branches.

### 9.2 Deterministic change (never trust provider deltas)
- `k` = latest index. `oi_change = oi[k] − oi[k − change_lookback]`.
- `price_change = price[k] − price[k − change_lookback]`.
- `provider_oi_change` is stored for cross-check only and is **not** used.

### 9.3 Epsilon thresholding (resolves M7)
- `price_eps = price_epsilon_pct · price[k − change_lookback]`,
  `price_epsilon_pct` default **0.05%**.
- `oi_eps = max(oi_epsilon_pct · oi[k − change_lookback], oi_eps_abs)`,
  `oi_epsilon_pct` default **0.10%**, `oi_eps_abs` default **0**.
- `price_direction = UP (> price_eps) / DOWN (< −price_eps) / FLAT`.
- `oi_direction = UP (> oi_eps) / DOWN (< −oi_eps) / FLAT`.

### 9.4 Classification

| price_direction | oi_direction | `oi_behavior` |
|---|---|---|
| UP | UP | `LONG_BUILDUP` |
| DOWN | UP | `SHORT_BUILDUP` |
| DOWN | DOWN | `LONG_UNWINDING` |
| UP | DOWN | `SHORT_COVERING` |
| FLAT, or oi_direction FLAT | any | `INDETERMINATE` |

### 9.5 Price source & option semantics (resolves M8)
- The price series is the **instrument's own** series (futures price for a
  future; **option premium** for an option).
- For a single option strike the labels describe positioning **in that
  contract**, not the underlying. A `warnings` entry states this on option
  results.
- Minimum points: `change_lookback + 1`; below → `INSUFFICIENT_DATA`.
- `oi_pct_change = oi_change / oi[k − change_lookback]`; if the prior OI is `0`
  (possible on a freshly listed strike) → `oi_pct_change = null` and the
  behavior scaling in scoring (`docs/06` §3.1) falls back to a fixed factor.
- **`values`:** `oi, oi_change, oi_pct_change, price_change, price_pct_change,
  price_direction, oi_direction, behavior, provider_oi_change`.
- Chain aggregation (PCR, total CE/PE OI) is a reserved future `oi_chain`
  analysis computed by `app/analysis/` from multiple instruments — **not V1**.

---

## 9a. Order Blocks (owner-authorised 2026-09-07)

`analytical_core.indicators.order_block` — pure, deterministic, `PER_TIMEFRAME`
(5m / 15m / 1h / 1D). **INDEX + FUTURE** only; `NOT_APPLICABLE` on OPTION
(premium series, chain-only — `docs/04` §4). Descriptive: it names a structural
**bias**, where price sits relative to the nearest blocks, and the block zones
themselves — **never BUY/SELL, no entry / target / stop** (hard rule 7).

### 9a.1 Parameters (`params.DEFAULT_PARAMS["order_block"]`)

| param | default | meaning |
|---|---|---|
| `swing_lookback` | 5 | fractal swing = strict unique extreme of `[i−L, i+L]`; a swing is only confirmed `L` bars later |
| `atr_period` | 14 | Wilder ATR (whole series) = the volatility scale for the impulse gate |
| `impulse_min_atr` | 1.0 | the move out of the block into the break must be `≥ impulse_min_atr · ATR` |
| `bos_search_window` | 30 | bars after a swing to look for the breaking close |
| `max_ob_age_bars` | 60 | blocks whose break is older than this (in bars) are dropped |
| `zone` | `"range"` | block zone = candle high–low (`"range"`) or open–close (`"body"`) |
| `mitigation` | `"touch"` | mitigated once a later bar trades into the zone (`"touch"`) or closes inside it (`"close"`) |

### 9a.2 Algorithm (deterministic)

1. **Swings** — fractal swing highs on `high`, swing lows on `low`
   (`swing_lookback` bars each side, strict unique extreme).
2. **Break of Structure** — for a swing high at `s`, the first bar `j ∈
   (s, s+bos_search_window]` whose **close** `> high[s]` is a bullish BOS;
   mirror on the close `< low[s]` for a bearish BOS off a swing low. Close, not
   wick.
3. **The order block** — the **last opposing candle** in `[s, j)`: the last
   *bearish* candle before a bullish BOS (the last *bullish* candle before a
   bearish BOS). If none, the extreme candle of the run. Zone = that candle's
   high–low (or body). `formed_ts` = that candle; `bos_ts` = bar `j`.
4. **Impulse gate** — bullish: `high[j] − zone_low ≥ impulse_min_atr · ATR`;
   bearish: `zone_high − low[j] ≥ …`. Below → the block is discarded.
5. **Mitigation** — the first bar after `j` to trade back into the zone
   (`touch`) or close inside it (`close`) sets `mitigated` + `mitigated_ts`.
6. **Ageing** — blocks with `last_index − j > max_ob_age_bars` are dropped.
   Surviving blocks are de-duplicated by `(side, low, high)`, newest `bos_ts`
   first.
7. **State** — `distance_pct` is price vs. the near edge (`0` when inside);
   `zone_state` ∈ `OUTSIDE / IN_BULLISH / IN_BEARISH` from whether price is
   inside *any* recent block (mitigated or not — a tag is a tag); `bias` ∈
   `BULLISH / BEARISH / NEUTRAL` from the zone state, else the nearest
   **unmitigated** block on each side.

Minimum bars: `swing_lookback·2 + bos_search_window + atr_period + 1` → below →
`INSUFFICIENT_DATA`.

### 9a.3 Output

- **`values`:** `bias`, `zone_state`, `price`, `atr`, `n_active_bullish`,
  `n_active_bearish`, `nearest_bullish`, `nearest_bearish`, `zones`. Each
  zone / nearest = `{side, low, high, mid, formed_ts, bos_ts, age_bars,
  mitigated, mitigated_ts, distance_pct}`.
- Scoring (`docs/06` §3.1): sub-score from `zone_state` (inside a block → ±
  `in_zone_score`) else the proximity × freshness of the nearest unmitigated
  block per side; weight `1.00`.

---

## 9b. Candlestick patterns (owner-authorised 2026-09-07)

`analytical_core.indicators.candles` — pure, deterministic, `PER_TIMEFRAME`
(5m / 15m / 1h / 1D). **INDEX + FUTURE** only; `NOT_APPLICABLE` on OPTION
(premium series, chain-only — `docs/04` §4). Descriptive: it **names** the major
candlestick pattern on each of the last `scan_bars` finished bars, tags each
`BULLISH` / `BEARISH` / `NEUTRAL` with a `WEAK` / `MODERATE` / `STRONG`
strength and the short-term trend it formed in, and reports the most recent one
as `last_pattern` + `last_bias`. **Never BUY/SELL, no entry / target / stop**
(hard rule 7). The "alert" is the frontend panel highlight when a pattern lands
on the just-closed bar (`on_last_bar` — `docs/08`).

### 9b.1 Parameters (`params.DEFAULT_PARAMS["candles"]`)

| param | default | meaning |
|---|---|---|
| `scan_bars` | 5 | how many of the most recent finished bars are each tested as a pattern's last bar |
| `trend_lookback` | 5 | bars before the pattern used for the ± 0.15 % trend-context classification (`UPTREND` / `DOWNTREND` / `SIDEWAYS`) |
| `doji_body_pct` | 0.10 | body ÷ range at/under this → `DOJI` (checked first) |
| `marubozu_body_pct` | 0.90 | body ÷ range at/over this → `MARUBOZU` |
| `wick_body_mult` | 2.0 | a "long" wick is `≥ wick_body_mult · body` |
| `opp_wick_pct` | 0.15 | the opposite wick must be `≤ opp_wick_pct · range` for a hammer / star shape |
| `star_body_pct` | 0.35 | "small body" ceiling (body ÷ range) for hammer / star / the star bar of a 3-bar |
| `frozen_run_min_bars` | 2 | a candidate bar preceded by `≥` this many identical zero-range bars (same timeframe) is not scored — see 9b.2a |

### 9b.2 Algorithm (deterministic)

Anatomy: `body = |close − open|`, `range = high − low`,
`upper = high − max(o, c)`, `lower = min(o, c) − low`.

For each bar `i` in the last `scan_bars`, the first match of
**3-bar → 2-bar → 1-bar** wins:

1. **3-bar** — `MORNING_STAR` (bearish bar, small-body star, bullish bar closing
   back over bar-1 midpoint with body `≥ 0.6·` bar-1 body) / `EVENING_STAR`
   (mirror).
2. **2-bar** — `BULLISH_ENGULFING` / `BEARISH_ENGULFING` (opposite colour, current
   real body covers the prior real body and is larger), `BULLISH_HARAMI` /
   `BEARISH_HARAMI` (small opposite body contained in a `≥ 2×` prior body),
   `PIERCING_LINE` / `DARK_CLOUD_COVER` (close back through the prior midpoint but
   not the prior open).
3. **1-bar** — doji family (body ≤ `doji_body_pct`) sub-classed by which wick
   is negligible (≤ `opp_wick_pct` · range — the two can't both qualify, since
   they'd have to sum to ≤ `2·opp_wick_pct` of the range while the non-body
   remainder is ≥ `1 − doji_body_pct`): lower wick negligible, long upper →
   `GRAVESTONE_DOJI` (`BEARISH`, `STRONG` in an uptrend else `WEAK`); upper
   wick negligible, long lower → `DRAGONFLY_DOJI` (mirror, `BULLISH`); neither
   negligible → plain `DOJI` (`NEUTRAL`) — → `MARUBOZU` (body ≥
   `marubozu_body_pct`) → hammer family (long lower wick, tiny upper, small
   body → `HAMMER` in a downtrend / `HANGING_MAN` in an uptrend) → inverted
   (long upper wick, tiny lower, small body → `SHOOTING_STAR` in an uptrend /
   `INVERTED_HAMMER` in a downtrend).

Trend context upgrades strength (a hammer in a confirmed downtrend is `STRONG`,
elsewhere `WEAK`). No look-ahead — only bars `≤ i` are read for bar `i`.

Minimum bars: `scan_bars + trend_lookback + 3` → below → `INSUFFICIENT_DATA`.

### 9b.2a Frozen-tape guard (bug fix, `ALGO_VERSION` 3.4.0→**3.4.1**, owner-flagged
2026-09-11: "candlestick patterns … its not perfectly deliver")

The NSE_INDEX intraday candle feed (verified on NIFTY / BANKNIFTY / SENSEX, 3
consecutive trading days) carries the same LTP forward as `O=H=L=C` for
several consecutive M1 bars in the last ~15 minutes before the close — the
index compute/candle-publish pipeline stalls, then snaps to the real closing
print in one step. Two guards stop that snap being scored as a genuine
pattern:

1. In `candles()`'s scan loop, a candidate bar preceded by `≥ frozen_run_min_bars`
   exactly flat, mutually-identical bars (same timeframe) is skipped —
   `_frozen_tape_artifact`. This is airtight for **M5** (and any timeframe
   whose own bucket width is *narrower* than the freeze, so the freeze spans
   multiple whole buckets of it) but **cannot** catch **M15 / M30 / H1** here:
   at those wider bucket widths the ~15-minute freeze fits entirely *inside
   one bucket*, so the immediately-preceding same-timeframe bar is genuine,
   non-flat data — there is no signal to detect without M1-level visibility,
   which this pure function does not have. **Known gap, not yet closed.**
2. `_three_bar`'s "star" (the small middle bar of `MORNING_STAR` /
   `EVENING_STAR`) now requires the middle bar's own range to be `> 0` —
   previously a literal zero-range middle bar divided by an epsilon and could
   read as a valid (in fact perfect, body = 0) star, letting a single frozen
   bar manufacture a 3-bar pattern around a real bar on one side and the
   catch-up jump on the other. This guard is general (any degenerate middle
   bar, any cause), not specific to the frozen-tape case.

Both are pure logic changes with no new inputs — `SCORING_VERSION` unchanged.

### 9b.3 Output

- **`values`:** `bias` (= `last_bias`, else `NEUTRAL`), `last_pattern`,
  `last_bias`, `last_strength`, `last_bars_ago`, `on_last_bar`, `n_bullish`,
  `n_bearish`, `bars_scanned`, `patterns`. Each `patterns[]` entry =
  `{pattern, bias, strength, trend_context, bar_ts, bars_ago, open, high, low,
  close}`, most-recent first.
- Scoring (`docs/06` §3.2): base from `last_pattern` bias × strength weight ×
  recency, plus a small cluster bump from `n_bullish − n_bearish`; `0.0` /
  no-op when no pattern is in the window; weight `0.75`.

### 9b.4 Multi-timeframe read grid (owner-authorised 2026-09-08)

`GET /instruments/{id}/candles-grid` (`docs/07` §4.17) is a **read view**, not an
engine analysis: it runs the same pure `candles` scan over **5m / 15m / 30m /
1h** and returns the last *N* hits per timeframe as parallel columns.
`M5 / M15 / H1` read the stored aggregated bars; **`M30` is folded on read from
`M5`** (session-open-anchored, docs/05 §3.5 rule) because there is no M30 in the
engine grid (decision 4) — it is never persisted, never scored, and does not
enter `expected_analyses`. Same applicability as the analysis (INDEX + FUTURE;
every column `NOT_APPLICABLE` on OPTION). `candles_grid_version` is module-local
(`0.1.0`), independent of `ALGO_VERSION`.

---

## 9c. ICT swing Fair Value Gaps (read view, owner-authorised 2026-09-09)

Pure `analytical_core.fvg.scan_swing_fvgs` — a **read view**, not an engine
analysis (no factor score, no `analysis_results` row, no version guard, enums
module-local). It surfaces the **"left-side" FVGs**: the Fair Value Gaps that
form in the final expansion leg *into* a confirmed swing high or low (ICT frames
this as institutional distribution, not continuation) and then act as
**inversion** arrays once price rotates off the swing.

- **FVG** — 3 consecutive candles: a *bullish* gap where `low[i] > high[i-2]`
  (zone `[high[i-2], low[i]]`), a *bearish* gap where `high[i] < low[i-2]`. `CE`
  = the 50 % midpoint.
- **Swing** — a fractal extreme, strictly greater / less than `swing_lookback`
  bars each side (confirmed `swing_lookback` bars later).
- **Association** — a bullish gap whose 3rd candle sits within
  `pre_swing_window` bars *before* a swing **high**, where the swing extreme
  expanded *past* the gap, is a left-side array; after the swing it acts as a
  **bearish** resistance / inversion. Mirror: a bearish gap before a swing
  **low** → **bullish** support / inversion.
- **State** per gap (from the bars after the swing): `PRIMED` (rotated away, not
  retested), `TESTED` (left the zone then traded back in), `RESPECTED` (a wick
  pierced the far edge but no body closed through), `BREACHED` (a body closed
  through the far edge — the clean setup is gone). Plus `reached_ce`,
  `wick_violated`, `body_respected`.
- Gaps thinner than `min_gap_pct` (0.03 % of price) are dropped as noise.

Output: per gap `{kind, inversion_kind, swing, top, bottom, ce, formed_ts,
swing_ts, bars_since_swing, state, reached_ce, wick_violated, body_respected,
distance_pct}`; per scan `nearest_above` / `nearest_below` (nearest **active**
gap each side), and a soft `bias` = the `inversion_kind` of the nearest active
gap. `FVG_VERSION = "0.1.0"`. Exposed only as the **multi-timeframe grid**
`GET /instruments/{id}/fvg-grid` (`docs/07` §4.21) over 5m / 15m / 30m / 1h
(M30 folded from M5), INDEX + FUTURE, `NOT_APPLICABLE` on OPTION; a `FvgGridPanel`
on instrument-detail. Descriptive — no bias score, no BUY/SELL, no target/stop.

---

## 9d. Candle Range Theory — CRT (read view, owner-authorised 2026-09-16)

Pure `analytical_core.crt.scan_crt` — a **read view**, not an engine analysis
(no factor score, no `analysis_results` row, no version guard, enums
module-local). A candle's High-Low range is a **reference range**; the bars
since it are read against four boundaries to say whether that range is being
**accepted**, **rejected**, or **expanded** — not "green candle = bullish."

- **Reference candle** = the bar `scan_bars` (default 5) back from the latest
  in the column; **`ref_high`/`ref_low`/`ref_range`/`ref_midpoint`** from it.
- **Compression** — the reference candle is flagged `is_inside_candle` when it
  sits fully inside its own immediately-prior ("mother") bar
  (`ref_high <= mother_high and ref_low >= mother_low`); the eventual break of
  the *mother* bar's own high/low then matters more than the reference's own.
- **Current position** (of the latest close) — `ABOVE_HIGH` / `BELOW_LOW` /
  `AT_MIDPOINT` (within `at_midpoint_pct`, default 10 %, of the range around
  the midpoint) / `INSIDE`.
- **Breakout** — the first bar in the reacting window whose high clears
  `ref_high` or low clears `ref_low` (a bar breaking both edges resolves by
  its own close). From there: `close_outside` (is the *latest* close still
  beyond the level), `returned_inside` (broke, but the latest close is back
  under/over it — **rejection**), `holds_beyond` (the latest bar's own wick,
  not just its close, stayed clear — a stronger hold), `retested` (a bar
  pulled back within `retest_tol_pct` of the level before price ultimately
  continued past it), and **range expansion** — `expansion_points` /
  `expansion_multiple` (furthest travel beyond the level since the break, as
  a multiple of `ref_range`; `>= expansion_multiple_strong`, default 0.5×,
  reads as expansion rather than plain continuation).
- **Volume confirmation** — `volume_confirms` compares the breakout bar's
  volume to the scan window's average (`>= volume_confirm_multiple`, default
  1.2×); `null` when the series carries no usable volume (the NSE INDEX feed —
  same `NOT_APPLICABLE`-for-volume characteristic as §4). OI-based
  confirmation is **not attempted** — OI already has its own dedicated reads
  (`docs/05` §9, §11.4) and doesn't apply at the level of a single price bar;
  a documented scope boundary, not a silent gap.
- **Signal** (per column) — `COMPRESSION` (no breakout, `is_inside_candle`) /
  `NEUTRAL` (no breakout, not inside) / `HIGH_REJECTION` / `LOW_REJECTION`
  (`returned_inside`) / `RANGE_EXPANSION_UP` / `RANGE_EXPANSION_DOWN`
  (`expansion_multiple >= expansion_multiple_strong`) / `BULLISH_CONTINUATION`
  / `BEARISH_CONTINUATION` (breakout holds, not yet a strong expansion).

`CRT_VERSION = "0.1.0"`. Exposed only as the **multi-timeframe grid**
`GET /instruments/{id}/crt-grid` (`docs/07` §4.24) over 5m / 15m / 30m / 1h
(M30 folded from M5), INDEX + FUTURE, `NOT_APPLICABLE` on OPTION; a
`CrtGridPanel` on instrument-detail. Descriptive — no bias score, no BUY/SELL,
no target/stop. *Scoped out of v1:* the ICT/HTF→LTF variant (a higher-timeframe
candle's range read via lower-timeframe reaction, for liquidity-manipulation
setups) is a different, more specific method the owner flagged as a possible
follow-up — not built here, needs its own worked example first.

---

## 9e. Gann time cycles (read view, owner-authorised 2026-09-16)

Pure `analytical_core.gann_cycles.scan_gann_cycles` — a **read view**, not an
engine analysis (no factor score, no `analysis_results` row, no version
guard, enums module-local). Owner: "Gann Days / Gann Time Cycles can we
implement in our logic?" → clarified as "previous low day and high [day],
then low high based on period with gann ideas" — the classic W.D. Gann
day-count method: project forward fixed cycle lengths from the last
significant swing low and swing high, and flag dates where several
projections converge.

- **Anchors** — over the last `lookback_bars` (default 260 ≈ 1y) daily
  bars, the **previous swing low** = the bar with the lowest `low`, the
  **previous swing high** = the bar with the highest `high` in that window
  (the window's own extremes, not a fractal-confirmed minor swing — Gann
  cycles are drawn from the major recent top/bottom, not every wiggle).
- **Projections** — from each anchor date, `anchor_date + cycle_days` for
  each of the classic Gann day-counts (default `45, 90, 120, 144, 180, 270,
  360` **calendar** days); kept only when within `horizon_days` (default 60)
  of today, so the read stays focused on near-term dates rather than the
  full multi-year sweep.
- **Confluence clusters** — projections (from either anchor, any cycle
  length) whose target dates fall within `cluster_tolerance_days` (default
  2) of each other are grouped; a cluster of 2+ is a stronger "time turn"
  candidate than any single projection alone (single-linkage grouping,
  walked chronologically).
- Trading-date math reuses `app.ingestion.session.trading_date_of` (IST
  calendar date of a bar-open UTC timestamp) — the pure module itself takes
  plain ISO date strings, no timezone dependency.
- **Filling past dates with what actually happened** (owner-flagged
  2026-09-16 — "past data need fill the value"): a projection whose
  `target_date` already has a bar on or shortly after it (within the same
  loaded daily series the anchors came from) is resolved to that bar — the
  nearest **trading** date on/after `target_date` (a weekend/holiday target
  nudges forward to the next session) — and carries that bar's
  `close`/`high`/`low`. A projection still ahead of the data we have (a
  genuinely future date) is left unfilled (`resolved_date`/`actual_*` all
  `null`). Lets the panel show, for a date that's already passed, what price
  actually did there — the whole point of checking a Gann date against real
  action, not just listing the date.

Output: `{swing_low, swing_high}` anchors (`kind`, `anchor_date`, `price`);
`projections: [{anchor_kind, anchor_date, anchor_price, cycle_days,
target_date, days_from_today, resolved_date, actual_close, actual_high,
actual_low}]`; `clusters: [{cluster_date, days_from_today, strength,
projections}]`. `GANN_CYCLES_VERSION = "0.1.0"`. Exposed as
`GET /instruments/{id}/gann-cycles` (`docs/07` §4.25) — a single read, not a
timeframe grid (Gann cycles are calendar-date based, decision 4's 5m/15m/1h/
1D grid model doesn't apply); INDEX + FUTURE, `NOT_APPLICABLE` on OPTION
(dated contracts don't carry a year of D1 history); a `GannCyclesPanel` on
instrument-detail. Descriptive — no bias score, no BUY/SELL, no
entry/target/stop; these are calendar dates where a turn is more likely by
Gann's method, not a signal.

---

## 9f. Gap-fade streak study (read view, owner-authorised 2026-09-16)

Pure `analytical_core.gap_fade_study.scan_gap_fade_study` — a **read view**,
not an engine analysis and explicitly **not a backtest** (owner: "its not
backe test i need to analysis how its happen after that"): no entry, no
exit, no target/stop, no hit-rate against a simulated trade. A descriptive
historical study — for every day that gaps one way but closes the other,
what actually followed, aggregated across the full available history.

**Both reversal directions** (owner-extended 2026-09-17 — "like open low
close/open high close actually it represent the reversal": the first
version only covered the gap-up case, missing its mirror):
- **UP** — gapped up and still closed down. A bearish-reversal candidate;
  the following streak counts **lower**-closing days.
- **DOWN** — gapped down and still closed up. A bullish-reversal candidate;
  the following streak counts **higher**-closing days.

- **Event** — the same threshold shape as the Daily Digest gap filter
  (`docs/07` §4.12), doubled for the mirror direction: `gap_pct >=
  gap_up_min_pct` (default 0.5%) and `change_pct <= chg_down_max_pct`
  (default −0.5%) → `UP`; `gap_pct <= gap_down_max_pct` (default −0.5%) and
  `change_pct >= chg_up_min_pct` (default 0.5%) → `DOWN`. Every day in the
  loaded D1 history that qualifies either way is its own independent
  occurrence (no de-duplication when two qualifying days' windows overlap).
- **Streak** — consecutive closes continuing in the reversal's own
  direction, starting on the event day itself (already such a day by
  definition); ends on the first day that closes against that direction.
- **Consolidation box** (owner-clarified 2026-09-16, "simple box" over an
  ATR-squeeze alternative) — the high/low of the first `box_days` (default
  3) days right after the streak ends. `consolidation_days` = how many days
  from the box's start until the breakout (or until the search window runs
  out, if no breakout has happened yet). Direction-agnostic — a `DOWN`
  event's box can still break either way, same as `UP`.
- **Breakout** (owner-clarified 2026-09-16, "close breaks the box by a
  buffer" over a bare box-touch) — the first day the **close** clears the
  box high/low by `breakout_buffer_pct` (default 0.3%); direction `UP` or
  `DOWN` (independent of the triggering event's own direction). Search gives
  up after `max_breakout_search_days` (default 90) — that occurrence is left
  `CONSOLIDATING` rather than scanned indefinitely.
- Per-occurrence `status`: `STREAK_ONGOING` (event too recent, streak hasn't
  ended within the data) / `INSUFFICIENT_BOX_DATA` (streak ended but not
  enough bars yet to form the box) / `CONSOLIDATING` (box formed, no
  breakout within the search window) / `BREAKOUT_UP` / `BREAKOUT_DOWN`.

Output: `summaries` — **one per direction** (`UP` then `DOWN`, always both
present even when empty), each `{direction, n_occurrences, n_streak_resolved,
mean/median streak days, streak_day_histogram, n_breakout_resolved,
mean/median consolidation days, breakout up/down counts, breakout_up_pct}`
— and `occurrences` (both directions combined, newest first, capped at
`max_occurrences` default 200 *per direction*) — each `{event_date,
direction, gap_pct, change_pct, streak_days, streak_end_date, status,
box_start_date, box_high, box_low, consolidation_days, breakout_date,
breakout_direction}`. `GAP_FADE_STUDY_VERSION` `0.1.0` → **`0.2.0`** (the
`summary` singular → `summaries` list restructuring, `direction` field
added — a clean break, not worth a migration path this soon after the
feature shipped). Exposed as `GET /instruments/{id}/gap-fade-study`
(`docs/07` §4.26) — all thresholds overridable per request; runs over the
**entire** D1 history (not a lookback window, unlike Gann cycles — the whole
point is "what has historically followed"); INDEX + FUTURE, `NOT_APPLICABLE`
on OPTION; a `GapFadeStudyPanel` on instrument-detail, side by side per
direction. Descriptive — no bias score, no BUY/SELL, no entry/target/stop.

---

## 9g. Economic event calendar (read view, owner-authorised 2026-09-16)

Pure `analytical_core.event_calendar.scan_event_calendar` — a **read view**,
not an engine analysis (no factor score, no `analysis_results` row, no
version guard, enums module-local). Owner: "news driven i need basic news
like fed powell and Auto sale and indian Gst... predefined news like
unemployment data... calander based on the calander view... previous close
- today close" — clarified across follow-ups to: **not live news**, a small
set of **recurring-date** event types generated by deterministic rule, each
with a before/after price read on the instrument being viewed, shown on an
actual calendar grid. Owner explicitly confirmed the price read is against
the NSE instrument on screen (NIFTY/BANKNIFTY/SENSEX), not against
gold/silver/bonds — this system tracks NSE index/derivatives only (decision
2) — and separately confirmed the intent is informational/anticipatory
context ("mind will change... 75 percent will not happen 25 only will
happen but it will get some idea"), not a predictor — the
`pct_notable_move` stat *is* exactly that real historical base rate,
computed from data rather than assumed.

- **US_JOBS_REPORT** — first Friday of each month. A clean, unchanging
  calendar rule; generated for the full span of loaded daily bars.
- **US_JOBLESS_CLAIMS** (owner-authorised 2026-09-17, cross-checked against
  investing.com's own economic calendar, which flags it as a genuine
  high-impact weekly release) — every Thursday, no approximation needed (a
  real weekly formula, unlike the monthly releases below). Generated
  week-by-week (`_thursdays()`) rather than month-by-month; the shared
  `horizon_end` (first of the horizon's last month) needed its own day-level
  extension (`horizon_end_day` = the last day of that month) for this one —
  the month-granularity generators don't care about the exact day, but a
  weekly walk under-covers the horizon's last month without it (caught while
  building, not by inspection — the first version of this generator silently
  produced zero occurrences for month-granularity horizons).
- **INDIA_GST_COLLECTION** — nearest trading day on/after the 1st of each
  month; no occurrences generated before `gst_start_date` (default
  2017-07-01, when GST launched).
- **MCX_GOLD_EXPIRY** / **MCX_SILVER_EXPIRY** — the 5th calendar day of each
  month, snapped **backward** to the nearest earlier trading day (MCX
  contract expiry convention). **Approximate**: this system has no MCX
  holiday calendar, so NSE's own trading days stand in for it — mostly but
  not always identical, since MCX and NSE are both Indian exchanges and
  largely share the same holiday calendar. Both land on the same date since
  they share the rule. (Renamed from the original `GOLD_EXPIRY`/
  `SILVER_EXPIRY` on 2026-09-17 when the US/COMEX pair was added, to keep
  the two exchanges unambiguous.)
- **COMEX_GOLD_EXPIRY** / **COMEX_SILVER_EXPIRY** (owner-authorised
  2026-09-17 — "US gold expiry?") — the 27th calendar day of each month, a
  rule-of-thumb stand-in for "a few business days before month end" (COMEX's
  own convention isn't a clean day-of-month rule), snapped backward the same
  way as the MCX pair. **A cruder approximation than MCX**: COMEX (US) and
  NSE (India) share no holiday calendar at all, so a US-holiday week can
  land this a day or more off — flagged to the owner before building, who
  accepted the tradeoff. Lands on a different date than the MCX pair (5th
  vs. 27th of the month), by design.
- **FED_RATE_DECISION** — **not generated**, supplied from a small
  owner-maintained seed list in `app/api/services.py`
  (`_FOMC_RATE_DECISION_DATES`) — FOMC meeting dates are committee-set, not
  a formula, so nothing can generate them. Owner-authorised 2026-09-16
  ("fed rate decision not coming"); seeded from training knowledge for
  **2023-2025**, at moderate confidence, **not independently verified** —
  deliberately not extended further back to avoid presenting unverified
  dates as historical fact. **2026 dates are owner-confirmed only**, never
  from training-knowledge recall (2026 is at/past this model's knowledge
  cutoff) — the first, `2026-09-16`, was added the same day the owner
  reported "Fed rate decision yesterday but its not showing." Extend the
  constant directly (or ask for it to be extended) with real dates as
  needed; cross-check against federalreserve.gov before relying on it for
  anything beyond a rough read.
- **ECB_RATE_DECISION** (owner-authorised 2026-09-17, following the same
  investing.com reference the owner shared) — same treatment as
  `FED_RATE_DECISION`: **not generated**, a small owner-maintained seed list
  (`_ECB_RATE_DECISION_DATES` in `app/api/services.py`), committee-set with
  no formula. Seeded for **2023-2025** at moderate confidence, not
  independently verified; no 2026+ entries (same reasoning as Fed — nothing
  guessed past this model's knowledge cutoff). Cross-check against
  ecb.europa.eu before relying on it beyond a rough read.
- **RBI_RATE_DECISION** (owner-authorised 2026-09-17, flagged 🔴 very high
  priority in the owner's events list) — same treatment as
  `FED_RATE_DECISION`/`ECB_RATE_DECISION`: **not generated**, a small
  owner-maintained seed list (`_RBI_RATE_DECISION_DATES` in
  `app/api/services.py`), committee-set (RBI Monetary Policy Committee) with
  no formula. Seeded for **2023-2025** at moderate confidence, not
  independently verified — bi-monthly (6/year, unlike Fed/ECB's 8); no
  2026+ entries (same reasoning as Fed/ECB). Cross-check against rbi.org.in
  before relying on it beyond a rough read.
- **FNO_EXPIRY** — **not generated**, supplied as real dates from the
  tracked option/future universe. Deliberately **not backfilled
  historically**: `instruments` only retains the current + next contract
  (older ones are pruned on each universe roll — decision `docs/04` §2.3),
  and NSE's expiry weekday convention has itself changed over the years
  (Thursday → Tuesday), so no reliable formula exists for reconstructing
  past dates without risking wrong dates presented as fact. In practice this
  means `FNO_EXPIRY` shows on the calendar (current + next month) but never
  carries a historical `pct_notable_move` — flagged to the owner before
  building rather than silently thin data.
- A date beyond the loaded series (still upcoming) is listed with no price
  fields — `future_horizon_months` (default 2) controls how far past the
  last loaded bar the calendar still shows known upcoming dates. Applies
  uniformly to every event type, generated or supplied.
- For every occurrence that does fall within the loaded series: `prior_close`
  / `close` / `change_pct` (close vs prior close) and `next_close` /
  `next_change_pct` (the following day, a lagged-reaction read).

Output: `summaries` (one per event type — `n_occurrences`, `n_resolved`,
mean/median `|change_pct|`, `pct_notable_move` = the real % of occurrences
whose move was `>= notable_move_pct` (default 0.5%), up/down counts) and a
flat `occurrences` list (every historical + near-future date, across all
six types) — the frontend groups this into whichever month the calendar
grid is showing, not the API. `EVENT_CALENDAR_VERSION = "0.1.0"`. Exposed as
`GET /instruments/{id}/event-calendar` (`docs/07` §4.27); INDEX + FUTURE,
`NOT_APPLICABLE` on OPTION; an `EventCalendarPanel` on instrument-detail
rendering an actual month-grid calendar (not a chart — a structured grid of
text/number cells, same spirit as the Market Profile TPO letter grid).
Descriptive — no bias score, no BUY/SELL, no entry/target/stop; anticipatory
context from real history, not a prediction.

---

## 10. Market Profile (resolves H4, H5; strategic directives 5, 13)

Two profile types — **TPO** and **Volume Profile** — built by separate builders
that share the period model, bucketing, and value-area / POC algorithm. Fully
deterministic and configurable. **The 09:15–15:30 / 30-minute / A–M example is
derived from the parameters, not hard-coded.**

`scope = SESSION`. `as_of_ts = session_open` (UTC).

### 10.1 `MarketProfileConfig`

| param | default | meaning |
|---|---|---|
| `tpo_minutes` | 30 | period length |
| `ib_periods` | 2 | number of leading periods forming the Initial Balance |
| `value_area_pct` | 0.70 | value-area coverage target |
| `partial_period_policy` | `KEEP` | `KEEP / MERGE_PREV / DROP` for a trailing partial period |
| `va_expansion` | `PAIR` | `PAIR` (CBOT 2-bin step) / `SINGLE` (1-bin step) |
| `vp_distribution` | `UNIFORM` | V1 only value; `OHLC_WEIGHTED` reserved |
| `source_timeframe` | `M5` | bar series the builders consume |
| `min_periods_for_result` | 3 | fewer elapsed periods → `INSUFFICIENT_DATA` |
| `min_bins` | 10 | fewer price bins over the session range → `INSUFFICIENT_DATA` |
| bin-size params | see §10.4 | |
| shape thresholds | see §10.8 | |

### 10.2 Period generation (deterministic)

Given `session_open`, `session_close` (from `market_calendar`), `tpo_minutes`:
- `n_full = floor((close − open) / tpo_minutes)`;
  `remainder = (close − open) − n_full·tpo_minutes`.
- Full periods `P₀ … P_{n_full−1}`, `Pᵢ = [open + i·tpo, open + (i+1)·tpo)`.
- If `remainder > 0` there is a trailing partial period `P_{n_full} =
  [open + n_full·tpo, close)`:
  - `KEEP` → its own period / letter.
  - `MERGE_PREV` → its bars attributed to `P_{n_full−1}`.
  - `DROP` → excluded; counted in `meta.excluded_bars`.
- **Letters:** `A, B, …, Z, a, b, …` by period index (documented; only relevant
  for display).
- A source bar belongs to the period containing its `ts`.
- **Default case check:** 375 min ÷ 30 → `n_full = 12`, `remainder = 15` →
  periods A…L (30 min) + partial M (15 min); `KEEP` gives the familiar A–M.

### 10.3 Initial Balance

`IB = the price range (min low … max high) across periods P₀ … P_{ib_periods−1}`.
If fewer than `ib_periods` periods have elapsed → `ib_high = ib_low = null`,
`ib_complete = false`.

### 10.4 Price bucketing & bin size (resolves M9)

- `bin_size` resolution order:
  1. `Instrument.profile_bin_size` if set;
  2. config override by `instrument_type` / underlying;
  3. derived:
     - **INDEX / FUTURE:** `bin_size = round_to_increment(price_ref · bin_pct,
       increment)`, `bin_pct` default 0.025%, `increment` per underlying
       (NIFTY 5, BANKNIFTY 10), `price_ref` = session-open price of the profiled
       series.
     - **OPTION:** `bin_size = max(tick_size, premium_ref · option_bin_pct)`,
       `option_bin_pct` default 1%, `premium_ref` = session-open premium.
- `bin_key(price) = floor(price / bin_size) · bin_size`.
- If the session range spans `< min_bins` bins → `status = INSUFFICIENT_DATA`
  (`reason = "price range too small for a meaningful profile"`). This is the
  common deep-OTM option outcome.

### 10.5 TPO builder

- For each `source_timeframe` bar, for the period it belongs to, for each bin
  overlapped by `[bar.low, bar.high]`, record that period's letter **once** at
  that bin.
- `tpo_count[bin]` = number of distinct period letters at the bin.
- **Approximation note:** with `source_timeframe = M5` each 30-min period has ≤ 6
  bars; true TPO uses finer brackets. A finer feed later improves fidelity with
  no interface change.

### 10.6 Volume Profile builder

- For each source bar, distribute `bar.volume` across the bins overlapped by
  `[bar.low, bar.high]` using `vp_distribution = UNIFORM` (equal split across
  the overlapped bin count).
- `vol[bin]` = Σ distributed volume (`math.fsum`).
- Requires `has_volume`; otherwise the Volume Profile is omitted and only TPO is
  produced. In practice an **INDEX** always falls into this case even when its
  `has_volume` flag is `true` (a DB default, not a reflection of reality) —
  an index is a calculated value, never itself bought/sold, so its own bars
  carry `volume = 0` and `build_profile` returns `None` for `total <= 0.0`
  regardless of the flag.
  **Borrowed FUTURE volume (`app.api.services.market_profile_view`, read
  layer only, owner-authorised 2026-09-17 — "FOR MARKET PROFILE ADD WITH
  FUTURE VOLUME"):** when `GET /instruments/{id}/market-profile` is asked
  for an INDEX session with no VOLUME row of its own, it looks up the
  nearest linked FUTURE contract (`Instrument.underlying_id == index_id`,
  soonest `expiry_date >= session_date`) and, if that FUTURE already has its
  own **persisted** Volume Profile for the same `session_date`, folds those
  bins into the response as `profiles["VOLUME"]`. No new computation, no
  engine change, no migration, no `ALGO_VERSION`/`SCORING_VERSION` bump —
  purely a second `SELECT` against `market_profile_sessions` data the
  regular cycle already builds for the future (futures trade with real
  volume). The response discloses the source (`volume_source: "FUTURE"`,
  `volume_source_contract_key`) rather than silently presenting it as the
  index's own — the future's own price grid can sit a small basis away from
  the index's, so this is a disclosed approximation, not a claim of exact
  equivalence. `docs/07` §4.4, `docs/08`.

### 10.7 POC & Value Area (deterministic; resolves M10)

`metric[bin]` = `tpo_count` (TPO) or `vol` (Volume Profile).

- **`total = fsum(metric)`**. If `total == 0` → `INSUFFICIENT_DATA`.
- **POC** = bin with max `metric`. Ties, in order: (1) bin price closest to the
  session VWAP proxy `fsum(typical_price·volume)/fsum(volume)` (or session mid if
  no volume); (2) lower bin price.
- **Value area:**
  - `VA = {POC}`, `running = metric[POC]`, `up = POC_idx + 1`,
    `down = POC_idx − 1`.
  - While `running < value_area_pct · total` **and** (`up` in range or `down` in
    range):
    - If **both** sides in range:
      - `up_val = metric[up] + (metric[up+1] if va_expansion == PAIR and up+1 in
        range else 0)`
      - `down_val = metric[down] + (metric[down−1] if va_expansion == PAIR and
        down−1 in range else 0)`
      - `up_val > down_val` → add the up side (1 bin `SINGLE`, up to 2 `PAIR`),
        advance `up`, `running += added`.
      - `down_val > up_val` → symmetric on the down side.
      - **equal** → expand **upward** first (documented tie-break); the next
        iteration takes the other side.
    - If **only one** side in range → add from that side (1 or 2 bins per mode),
      advance. (Explicit one-sided-exhaustion branch — resolves M10.)
  - `VAH = max(bin price ∈ VA)`, `VAL = min(bin price ∈ VA)`.

### 10.8 Profile-shape classification (deterministic; resolves H4)

Computed on the finished profile (`metric` as above). Let
`range = session_high − session_low`,
`poc_pos = (POC − session_low) / range`,
`va_width = (VAH − VAL) / range`,
`lower_third` / `upper_third` = the price thirds of the session range,
`third_share(x)` = `fsum(metric in third x) / total`.

Evaluated **in this order**; first match wins:

1. `TREND_UP` — `close ≥ VAH` and `poc_pos ≥ 0.66` and `va_width ≤ 0.50`.
2. `TREND_DOWN` — `close ≤ VAL` and `poc_pos ≤ 0.34` and `va_width ≤ 0.50`.
3. `P_SHAPE` — `poc_pos ≥ 0.60` and `third_share(lower) ≤ tail_pct` (default
   0.15).
4. `B_SHAPE` — `poc_pos ≤ 0.40` and `third_share(upper) ≤ tail_pct`.
5. `DOUBLE_DISTRIBUTION` — ∃ two bins each `≥ dd_peak_pct` (default 0.12) of
   `total`, separated by at least one bin `≤ dd_valley_pct` (default 0.04) of
   `total`.
6. else `NORMAL`.

All thresholds are config keys.

### 10.9 Reference close & derived flags (feeds scoring — resolves review L13)

- `close` = last `source_timeframe` bar close within the session (forming bar
  allowed).
- `close_vs_poc` = `ABOVE / BELOW / AT` (`AT` if `|close − POC| < bin_size/2`).
- `close_vs_vah`, `close_vs_val` = `ABOVE / AT / BELOW` (same `bin_size/2`
  tolerance).
- `close_in_value_area = VAL ≤ close ≤ VAH`.

### 10.10 Output

- **`values`:** `profile_type, session_date, session_start_ts, session_end_ts,
  bin_size, poc, vah, val, value_area_pct, ib_high, ib_low, ib_complete,
  session_high, session_low, range, close, close_vs_poc, close_vs_vah,
  close_vs_val, close_in_value_area, profile_shape, is_session_complete,
  n_periods_elapsed, n_periods_total`.
- **`aux`:** `close` (also here for the sub-score), `vwap_proxy`.
- **`series`:** `bins[] = {price_low, tpo_count?, letters?, volume?}` — persisted
  in `market_profile_sessions.bins`, not in the small `analysis_results.result`.
  **`letters`** (TPO only, owner-authorised 2026-09-15): the actual period
  letters that printed at that price, chronological (e.g. `"DEFGH"`) — the
  classic hand-plotted TPO read, alongside the `tpo_count` that was already
  there (`len(letters) == tpo_count`). Display-only — never read by scoring or
  the engine-snapshot guard (`ProfileResult.values()` excludes `bins`
  entirely, TPO or Volume).
- **`events`:** the Market Profile event layer (`docs/14`) runs after the TPO
  profile in the same step — a compact blob (`version`, `status`, `day_type`,
  MVP event list with lifecycle state + strength, tensions) persisted in
  `market_profile_sessions.events` (TPO rows only). Its `MP_EVENTS_VERSION` is
  folded into the recompute-guard `params_hash`. The event layer never breaks
  the cycle — a failure stores `{status: "ERROR", reason}`. It is **not** on the
  `ALGO_VERSION` engine-snapshot surface (own version, own golden tests).
- **`meta`:** all params, `partial_period_policy`, `va_expansion`,
  `excluded_bars`, `gap_count`, `source_timeframe`, `source_max_ts`,
  `algo_version`, `params_id`, `params_hash`.
- `< min_periods_for_result` periods elapsed → `INSUFFICIENT_DATA` with the safe
  partial fields and `is_session_complete = false`.

### 10.11 Recompute guard (resolves M24)

Market Profile for `(instrument, session_date, profile_type)` is recomputed only
when the session's max source-bar `ts`/`ingested_at` (`source_max_ts`) has
advanced since the cached `market_profile_sessions` row, or `params_hash`
changed. Otherwise the prior result is carried
(`analysis_results.carried = true`, `carried_from_result_id` set) with no
rebuild.

### 10.12 Key levels — last two sessions (`levels.py`, owner-authorised 2026-09-07)

Pure `analytical_core.market_profile.build_key_levels` — a **read view**, not an
engine analysis (no factor score, no `analysis_results` row, no version guard).
Takes the previous **two completed TPO sessions** (`D-1`, `D-2`) — `POC / VAH /
VAL / IB_HIGH / IB_LOW / session HIGH / LOW`, shape, day-type, close — the
latest price, and a proximity band triple, and returns:

- the two sessions side by side with `close_vs_value` (`ABOVE` / `INSIDE` /
  `BELOW`);
- **`levels`** — every non-null level from both sessions, price-sorted, each
  tagged: `distance` (signed points `level − last_price`), `distance_pct`,
  `side` (`ABOVE` / `BELOW` / `AT`), and a **`tier`**: `AT` (`|d| ≤ at`),
  `NEAR` (`≤ near`), `APPROACHING` (`≤ approaching`), else `FAR`;
- **`acceptance`** on the `AT` / `NEAR` levels only, from the recent M5 bars:
  `ACCEPTED_ABOVE` / `ACCEPTED_BELOW` (last `accept_bars` = 3 closes all one
  side + price that side), `REJECTED_FROM_ABOVE` / `REJECTED_FROM_BELOW` (a bar
  in the last `reject_lookback` = 6 poked through and closed back, price now
  back on the near side), `TESTING`, `UNTOUCHED`;
- **`alerts`** (`tier != FAR`, nearest first) and `nearest_above` /
  `nearest_below`.

Bands default **per instrument** (points): `NIFTY*` → 15 / 30 / 45; `BANKNIFTY*`
/ `SENSEX*` → 40 / 80 / 120; else 15 / 30 / 45 — overridable per request.
`KEY_LEVELS_VERSION = "0.1.0"`; enums are module-local (unregistered — a read
view, `docs/12` untouched). Descriptive — **no bias, no BUY/SELL, no target /
stop**. Read path: `app.api.services.key_levels`; `GET
/instruments/{id}/key-levels` (`docs/07` §4.16); a `KeyLevelsPanel` on the
instrument-detail screen.

### 10.13 CPR & classic pivots — daily / weekly / monthly (`pivots.py`, owner-authorised 2026-09-08)

Pure `analytical_core.pivots` — a **read view**, not an engine analysis (no
factor score, no `analysis_results` row, no version guard, enums module-local).
`compute_pivots(high, low, close)` on a **completed period's** H/L/C returns that
period's forward-looking lines:

- **Pivot** `P = (H + L + C) / 3`; classic floor steps `R1 = 2P − L`,
  `S1 = 2P − H`, `R2 = P + (H − L)`, `S2 = P − (H − L)`,
  `R3 = H + 2(P − L)`, `S3 = L − 2(H − P)`.
- **CPR band** — `BC = (H + L) / 2`, `TC = 2P − BC` (by formula; `TC` can fall
  *below* `BC` on a weak close). `cpr_top` / `cpr_bottom` = `max` / `min` of the
  two; `cpr_width` and `cpr_width_pct = width / P · 100`; `width_band` ∈
  `NARROW` (`≤ 0.25 %`) / `AVERAGE` / `WIDE` (`≥ 0.75 %`) — a narrow CPR is the
  classic expansion-day tell, a wide one a rotation day. Configurable.
- **`vs_prev`** — `cpr_relation` of this CPR band to the previous period's:
  `HIGHER_VALUE` / `LOWER_VALUE` / `OVERLAPPING` / `INSIDE_VALUE` /
  `OUTSIDE_VALUE` / `UNCHANGED`.

The read service (`app.api.services.pivots_view`) folds **D1 bars** into daily
(each bar), weekly (ISO week, IST) and monthly (calendar month, IST) periods;
for each timeframe it returns the **`current`** levels (from the last *completed*
period — the ones in force now), the **`next`** levels (for the upcoming
period — **"tomorrow" for daily** — computed from the most recent period's
H/L/C: `provisional: true` while that period is still open, and `for_label` /
`for_date` name the period it applies to, the daily date resolved against
`market_calendar` so weekends / holidays are skipped), and **`history`** (the
last `daily_history` = 66 ≈ 3 months / `weekly_history` = 13 /
`monthly_history` = 4 completed periods, newest first). The **daily** history
also has a *same-calendar-date* mode — `daily_on = "MM-DD"` (+ `daily_years`,
default 20): the first session on/after that date in each of the last N years,
each row carrying `year` / `for_date` and a `realized` block (that session's
open/high/low/close, `ret_pct`, `range_pct`, `close_vs_pivot`, `touched_r1` /
`touched_s1`) — a seasonality read ("what has 1 September done, 20 years back"). Every `current` level is
tagged `distance` /
`distance_pct` / `tier` (`AT` ≤ `at`, `NEAR` ≤ `near`, else `FAR`, per-instrument
point bands reused from §10.12) / `side`; `nearest_above` / `nearest_below` /
`alerts` (`tier != FAR`) roll up across all three timeframes. `PIVOTS_VERSION =
"0.1.0"`. **All instrument types** — computed from whatever D1 bars exist (young
FUTURE / OPTION contracts simply have shorter history). Descriptive — **no bias,
no BUY/SELL, no target / stop**. `GET /instruments/{id}/pivots` (`docs/07`
§4.18); a `PivotsPanel` on instrument-detail.

---

## 11. Option pricing & chain (`docs/07` §4.4)

`analytical_core.options` — pure, deterministic, standard-library only. **Table
only, no charts** (decision 11).

### 11.1 Black–Scholes–Merton (`black_scholes.py`)
- European `bs_price(spot, strike, t_years, r, vol, *, is_call, q=0.0)` with a
  continuous dividend/carry yield `q` (default 0 for index options). Normal CDF
  via `math.erf`.
- `bs_greeks(...) -> Greeks(delta, gamma, theta, vega, rho)`. Display
  conventions: **theta per calendar day** (annual θ / 365), **vega and rho per
  1 percentage point** (annual / 100).
- `t_years ≤ 0` or `vol ≤ 0` → price = intrinsic, greeks = step-delta / 0.

### 11.2 Implied volatility (`iv.py`)
- `implied_vol(price, spot, strike, t_years, r, *, is_call, q=0.0)`. Newton–
  Raphson seeded by Brenner–Subrahmanyam, bisection fallback on `[1e-4, 5.0]`.
  Deterministic: fixed seed, `MAX_ITER=100`, price tolerance `1e-7`, result
  rounded to 6 dp.
- Returns `None` when the price is outside the no-arbitrage band
  (`≤ intrinsic` or `≥ spot·e^−qT` / `strike·e^−rT`) or the solver does not
  converge.

### 11.3 Chain assembly (`chain.py`)
- `build_chain(*, underlying_symbol, spot, expiry, now, risk_free_rate, legs,
  dividend_yield=0.0)`. `legs` are raw `LegInput(strike, option_type, ltp, oi,
  oi_change, volume, day_open, day_high, day_low)`; the API layer aggregates each
  contract's **session O/H/L/C + volume** from its M1 bars (`day_close` echoes
  `ltp`), and takes OI / OI-change from the `open_interest` analysis (raw OI
  otherwise). Each leg also carries `open_at_high` / `open_at_low` — `true` when
  the open equals the session high / low over a non-degenerate range (`high >
  low`); the premium topped / bottomed at the opening print and moved one way
  after — plus `oi_change_pct` (ΔOI ÷ opening OI) and `crowded` (this strike is
  its side's single biggest positive OI build). The chain-level **crowded read**
  (`crowded_read`, shared with §11.4) adds `crowded_side` (`CALLS`/`PUTS`/
  `BALANCED` — one side's Σ positive ΔOI must beat the other's by 1.3×),
  `crowded_call_strike` / `crowded_put_strike` and `crowded_*_frac` (the hot
  strike's share of that side's build).
- `t_years` = calendar seconds from `now` to the expiry-day 15:30 IST close,
  over `365·24·3600`. `days_to_expiry` is calendar days.
- Per leg: IV, then greeks at that IV (both `None` when IV can't be solved).
- Aggregates: `pcr_oi` = Σ put OI / Σ call OI; `pcr_volume` likewise;
  `max_pain_strike` = the strike minimising total writer payout
  `Σ_K [ CE_OI·max(0,S−K) + PE_OI·max(0,K−S) ]` over candidate S = each strike;
  `atm_strike` = strike nearest spot.
- Rounding at construction: strikes/LTP 4 dp, IV 6 dp (fraction), delta/theta/
  vega 6 dp, gamma 8 dp.
- Not persisted — computed on read. The response carries `algo_version`.
- `max_pain(strikes, ce_oi, pe_oi)` is a module-public helper (reused by §11.4).

### 11.4 OI pulse (`oi_pulse.py`, `docs/07` §4.11)

Intraday **trending open interest** for one expiry — a snapshot of *positioning
change* through the session, not a forecast and not a BUY/SELL (decision 15).

- `build_oi_pulse(*, underlying_symbol, spot, expiry, now, session_open, legs,
  config=OiPulseConfig())`. Each `OiLegSeries(strike, option_type, oi[], premium[])`
  is that leg's ascending per-minute history for the current session; the API
  layer loads it from `open_interest` + the option M1 bars. Pure, no IO.
- **Per strike / leg:** `oi`, `oi_at_open` (value at/again before `session_open`),
  `oi_change_session`, `oi_change_recent` (vs. `now − recent_window_min`, default
  15), `ltp`, `price_at_open`, `price_change_recent_pct` /
  `price_change_session_pct`, and **two buildup labels** =
  `classify_oi_behavior(price_dir, oi_dir)` reusing the `open_interest` table
  (§9): `buildup` from premium × OI direction over the **recent** window,
  `buildup_session` from premium-vs-open × OI-vs-open over the **session** →
  `LONG_BUILDUP / SHORT_BUILDUP / LONG_UNWINDING / SHORT_COVERING /
  INDETERMINATE`; `NO_DATA` when the leg has no history. Both describe
  positioning **in that contract**, not the underlying. (`OI_PULSE_VERSION`
  0.1.0 → **0.2.0** for the added fields.)
- **Aggregates:** `pcr_oi_now` / `pcr_oi_open` (Σ put OI / Σ call OI now vs. at the
  open); `max_pain_now` / `max_pain_open` / `max_pain_shift` (§11.3 helper on the
  now- and open- OI distributions); `support_strike` = max-PE-OI strike,
  `resistance_strike` = max-CE-OI strike; `net_ce_oi_change` / `net_pe_oi_change`
  (Σ session ΔOI per side); `bias` ∈ `CALL_WRITING / PUT_WRITING /
  CALL_UNWINDING / PUT_UNWINDING / BALANCED` from the sign + magnitude of the
  larger net side (|net| below `bias_epsilon_frac`·total-OI ⇒ `BALANCED`).
- **Crowded read** (`crowded_read`, shared with §11.3): `crowded_side` ∈
  `CALLS / PUTS / BALANCED` (one side's Σ positive session ΔOI must beat the
  other's by 1.3×), `crowded_ce_strike` / `crowded_pe_strike` = each side's
  single biggest positive build, `crowded_*_frac` = its share of that side's
  total build; the matching per-leg `OiPulseLeg.crowded` flag marks those
  strikes in the ladder.
- **Session trace:** at each `trace_step_min` mark (default 5) from
  `session_open` to `min(now, session_close + trace_end_grace_min)` — i.e. up to
  ~15:40 IST (10 min past the bell, to catch closing-session prints). Once that
  cutoff passes the trace is **fixed**: one full set of marks, re-running yields
  the identical series (only the strike ladder / LTP keep refreshing). Each mark is a
  full time-series row computed from each leg's OI / premium / volume *as of that
  mark*: `spot`; `call_oi_change` / `put_oi_change`
  (cumulative Σ(OI − open OI) per side) with the `*_delta` versus the previous
  mark; `diff_oi` = put ΔOI − call ΔOI (negative ⇒ calls written / puts unwound
  faster ⇒ resistance-heavy); `diff_pct` = `diff_oi / (|callΔ| + |putΔ|)`;
  `dir_of_change` = `diff_oi` − previous mark's; `pcr_oi` (total OI),
  `coi_pcr` (put ΔOI / call ΔOI), `vol_pcr` (cumulative put vol / call vol);
  `total_ce_oi` / `total_pe_oi`; `max_pain`; and `sentiment` ∈ `Bullish /
  Bearish / Neutral` from the sign of `diff_oi` (|diff| below
  `sentiment_epsilon_frac`·(|callΔ|+|putΔ|) ⇒ `Neutral`). The last mark's
  cumulative figures reconcile with the top-level `net_ce_oi_change` /
  `net_pe_oi_change` (when unwindowed). `trace_window_up` / `trace_window_down`
  (API `?trace_up=N` / `?trace_down=N`) independently restrict the trace's
  per-mark aggregates to **N strikes above / below ATM** (`trace_atm_strike` =
  the strike nearest spot; step inferred from the ladder; a `None` side = no
  limit that way) — the strike ladder and the top-level PCR / walls / bias are
  unaffected. Tabular — **no chart** (decision 11). Marks before any leg has
  data are skipped.
- Not persisted — computed on read. Carries `algo_version` + independent
  `oi_pulse_version` (`OI_PULSE_VERSION`, currently `0.2.0`).
- **Big OI movers** (`app.api.services.oi_movers`, `docs/07` §4.22,
  owner-authorised 2026-09-10) is a thin re-shape of this ladder: flatten the
  per-strike CE/PE legs, split into the strikes that **added** vs **reduced** the
  most **session** OI, top `N` each. Each row's `buildup` is the leg's
  **`buildup_session`** — consistent with the list it sits in (an *added* row is
  always a `*_BUILDUP`, a *reduced* row a `LONG_UNWINDING` / `SHORT_COVERING`) —
  and `buildup_now` (= the recent-band `buildup`) is surfaced when it diverges
  ("built all day, now unwinding"). `time_band` (1 / 3 / 5 / 10 / 15 — `1`
  added 2026-09-17) is the recent-band minutes; `moneyness` filters the
  buckets. Options only;
  `GET /instruments/{id}/oi-movers`; a `/instruments/:id/oi-movers` screen.
  Positioning labels only — no BUY/SELL.
  **LTP trace** (`app.api.services.oi_mover_ltp_trace` →
  `analytical_core.options.build_ltp_trace`, `docs/07` §4.22, owner-authorised
  2026-09-17 — watching a crowded strike's premium for where a build-up might
  "find liquidity"): for one `(strike, option_type)`, pairs each of that
  option's session M1 premium ticks with the underlying's own LTP and that
  strike's own OI, each at/just before the same instant — no resampling, no
  indicator, no positioning label, just OI and the two price series lined up
  tick for tick. `_at_or_before` (the same lookup `oi_pulse`'s trace already
  uses) supplies the underlying and OI sides, so a gap in either feed carries
  its last known value forward rather than leaving a hole (`oi` is `None`
  only when the strike has no OI sample at all yet). **OI column added same
  day** (owner — "Strike LTP trace WITH oi NEEDED"): `oi_series` threaded
  through from `OpenInterest` for the resolved option instrument, same as
  `underlying_ltp`'s pattern. **OI change column added same day** (owner —
  "aDD oi CHANGE ALSO"): `oi_change` = `oi` minus `oi_series[0]`'s own value
  — deliberately not a fresh session-open lookup, since the caller already
  pre-filters `oi_series` to `ts >= session_open` (the same convention
  `option_premium` / `spot_series` already follow), so the passed-in
  series's first sample *is* the session-open read. `GET
  /instruments/{id}/oi-movers/ltp-trace?strike=&option_type=`; a **`LTP
  trace`** tab on the `/instruments/:id/oi-movers` screen. **Tick-to-tick OI
  Δ added same day** (owner — "PREVIOUS ROW - CURRENT ONE COLUMN ADDITONAL
  NEED", alongside the server-computed cumulative `oi_change`): the frontend
  table's `OI Δ (prev)` column is computed client-side from adjacent rows
  already present in the response — no backend/schema change, since the
  full ordered series is already there and "versus the row above it" is a
  pure display concern (docs/08).
  **N-minute grouping with an LTP low–high band** (owner — "i NEED
  FILTRATION IN ltp TRACE IF LTP LOW HIGH BAND LIKE IF 5 MIN MULTIPLE PRICE
  MEANS"): frontend-only, no backend/schema change — the same raw 1-min
  `series` is grouped client-side into session-open-anchored N-min windows
  (`bucketTrace`), each window reporting `optLow`/`optHigh` (+ the
  underlying's own low/high) instead of every tick; rendered as a single
  price when a window only ever saw one, a `low–high` band when it saw more
  than one. OI / OI Δ columns read the window's last tick (a running value,
  not something to band) rather than aggregating. `1m` (the default) is a
  1:1 passthrough of the raw series, so nothing changes unless the owner
  actually groups.
  **Price-difference columns** (owner — "CAN U ADD PRICE DIFFERNCE IN ltp
  TRACE", same day): `LTP Δ` / `<underlying> Δ` sit beside their respective
  LTP columns — each row's own close (its last raw tick, whether grouped or
  not) minus the previous row's close, `sPrice`-formatted (signed). Reuses
  the `optClose`/`undClose` fields the grouping feature above already
  carries, so the low–high band and its plain difference are computed from
  the same close values that drive the row's colour — frontend-only, no
  backend/schema change.
  **Near-expiry auto-pick now prefers a tracked expiry** (owner-flagged
  2026-09-17 — "SENSEX SHOWING 11:45 AM ONLY?"): `services.option_expiries`
  gained an `only_tracked` filter and a new `services._pick_near_expiry`
  helper, used by `option_chain`, `oi_pulse`, and `oi_mover_ltp_trace`
  wherever the caller doesn't name an explicit `?expiry=`. Root cause — the
  universe roll (`app.instruments.roll`) periodically drops a just-expired
  week's option contracts from `is_tracked`, but their rows (and stale
  OI/price history) stay in the table; `option_expiries()` never filtered
  on `is_tracked`, so once SENSEX's own weekly expiry (which happened to
  land that trading day) rolled off mid-session, "the near expiry ≥ today"
  kept resolving to that now-frozen contract — every OI-pulse/OI-movers/LTP-
  trace reading silently came from data that stopped updating the moment of
  the roll (11:45 IST that day), not "now", while NIFTY's own near expiry
  happened to still be several days out and never hit the bug. The picker
  now prefers the nearest **tracked** expiry ≥ today, falling back to the
  full expiry list (tracked or not) only if nothing at all is tracked for
  that underlying. The full `expiries[]` list returned to the frontend is
  unchanged (still includes the frozen expiry, so it can still be picked
  explicitly for historical inspection) — only the *default* auto-pick
  changed.
- **OI ladder** (`build_oi_ladder` in `oi_pulse.py`, `app.api.services.oi_ladder`,
  `docs/07` §4.22, owner — "i NEED FILTRATION IN ltp TRACE IF LTP LOW HIGH
  BAND LIKE IF 5 MIN MULTIPLE PRICE MEANS" → clarified via follow-up as a
  distinct request: "one more display option in LTP Trace [/] oi movers"
  with a pasted mock showing time columns mirrored either side of a strike
  column — confirmed via `AskUserQuestion` as a classic CE | strike | PE
  option-chain layout, but with OI **change between time columns** instead
  of a single "now" snapshot). Distinct from `OiPulse.trace` (§ above), which
  aggregates every strike into one number per side per mark — this keeps
  every strike its own row, so a trader can see *where on the chain* OI is
  moving, not just how much moved in total. `build_oi_ladder(legs, marks,
  spot, *, window_up=, window_down=)`: for each strike (optionally windowed
  to N strikes above/below ATM — same step-inference convention as
  `build_oi_pulse`'s own `trace_window_up`/`_down`), resolves CE/PE OI at
  each of `marks` (ascending) via `_at_or_before`, plus each mark's change
  from the mark before it (`oi_delta`, `None` on the first column — the
  ladder is deliberately **OI-delta only**, per the owner's framing, not a
  raw-OI display). `services.oi_ladder` generates `marks` as `n_marks`
  `step_min`-spaced times ending at `min(now, session_close)` (default 3
  marks, 1 min apart, matching the owner's pasted mock exactly), resolves
  the near expiry via the same `_pick_near_expiry` fix above, and loads only
  each strike's OI series (no premium/volume needed for this view). `GET
  /instruments/{id}/oi-ladder?marks=&step_min=&window_up=&window_down=`; a
  third **`OI ladder`** tab on the `/instruments/:id/oi-movers` screen next
  to `Movers`/`LTP trace`. **Per-column max-|Δ| elevation** (same day, owner
  — "each maximum no oI change back ground color elevate"): frontend-only —
  each time column's single biggest `|oi_delta|` on each side gets an
  elevated background in addition to the usual colour, so the reader isn't
  left scanning every cell to spot the standout mover; a `0` delta is never
  elevated. **Underlying LTP on hover + wider default window** (2026-09-18,
  owner — "±10 around ATM and mouse hover can we show price"): `window_up`/
  `window_down` request defaults widened 6→7→10 (two requests same day —
  the ladder's frontend defaults, not the API's own `Query(...)` defaults,
  which stay 6). `build_oi_ladder` gained an `underlying_series` param and
  a matching `underlying_at_marks` output field — the underlying's own LTP
  at/just-before each mark, via the same `_at_or_before` lookup already
  used for OI, so a reader can see what the underlying was doing at a given
  time column without a chart. `services.oi_ladder` loads the underlying's
  M1 close series the same way `oi_pulse` already loads its own spot
  series. Frontend: each time-column header carries a native `title`
  tooltip (dotted underline, `cursor-help`) — no chart, no new UI surface,
  just a hover disclosure on data already computed.
  **Per-cell tooltip with option LTP added same day** (owner — "tool tip is
  a good idea if possible add option price also and tool tip not working
  showing symbol '?'"): the native header `title` was reported broken —
  browsers only surfaced the `cursor-help` "?" icon, no visible tooltip
  text. Replaced with a real, always-rendering custom CSS tooltip on every
  OI-Δ **cell** instead of the header, so hover context and the OI reading
  live together. `OiLadderCell` gained an `ltp: float | None` field (that
  option's own premium at the mark, resolved the same `_at_or_before` way);
  `build_oi_ladder`'s `_cells()` now reads `lg.premium` too, and
  `services.oi_ladder` loads each option's M1 close series (same query
  shape `oi_pulse` already uses) and passes it into `OiLegSeries.premium`
  instead of `()`. Frontend tooltip shows strike/side/time, OI (+ Δ), LTP,
  and the underlying's LTP together. Anchored to the hovered cell's own
  edge (not centred) and flipped to open upward for the table's last row —
  a centred/downward-only tooltip clipped against the table's own
  horizontal-scroll container at the far edges and the bottom row, caught
  by screenshotting those exact positions rather than assuming the first
  fix worked. Options only, positioning read only — no BUY/SELL.

### 11.5 Option-strategy suggestions (`strategy.py`, `docs/07` §4.13)

**Owner-authorised 2026-09-03 — a bounded revision of decision 15 / hard rule 7
(see `.claude/CLAUDE.md` §3b).** This is the one engine module that emits option
structures carrying per-leg **`BUY` / `SELL`** and a quantity ratio. It stays
pure and deterministic, is computed on read, is not persisted, and **never
places an order**. Every `StrategyBook` carries `disclaimer` — *illustrative
analytical output derived from open interest; not investment advice, not a
recommendation, not an order*.

`build_strategy_book(underlying_symbol, quotes: list[StrikeQuote], *, spot,
expiry, now, config=StrategyConfig(), atm_iv=None, t_years=0.0,
risk_free_rate=0.065, far_quotes=None, far_expiry=None)` where `StrikeQuote` is
`(strike, ce_oi, ce_oi_change, ce_ltp, pe_oi, pe_oi_change, pe_ltp)` — the API
fills it from the §11.3 chain (and, when a later expiry has stored option OI, a
second `far_quotes` chain). Steps:

1. **Derive** step (min strike gap), ATM (nearest strike to spot), PCR(OI),
   `support_wall` (max Σ put OI strike), `resistance_wall` (max Σ call OI
   strike), `max_pain` (§11.3 helper), `net_ce_oi_change` / `net_pe_oi_change`
   (Σ ΔOI per side), `crowded_side` (`crowded_read`).
2. **Classify** into one `MarketView.label` by an additive score over six views:
   `RANGEBOUND`, `LEAN_BULLISH`, `LEAN_BEARISH`, `TREND_BULLISH`,
   `TREND_BEARISH`, `VOL_EXPANSION`. The ΔOI **flow** signal is weighted highest
   (calls unwinding + puts written ⇒ trend up; both unwinding ⇒ vol expansion;
   both writing ⇒ rangebound; one-sided writing ⇒ lean); PCR level, max-pain-vs-
   spot, crowded side and "walls bracket spot" are lighter positional signals. A
   decisive flow score overrides a merely-positional read. `confidence` =
   `clamp(score/4, 0.2, 0.95)`; `evidence` is the list of firing reasons.
3. **Templates** per view, strikes from the walls / ATM, wings
   `config.wing_points` index points when set, else `config.wing_steps` strikes
   out (default 2):
   - RANGEBOUND → `IRON_CONDOR` (sell the walls, buy wings), `IRON_FLY` (sell ATM
     straddle, wings at the walls), `SHORT_STRANGLE` (undefined risk).
   - LEAN_/TREND_BULLISH → `BULL_PUT_SPREAD` (1:1 credit), `CALL_RATIO_SPREAD_1X2`
     (buy 1 ATM, sell 2 at the call wall — naked extra short), and for a trend
     also `BULL_CALL_SPREAD` (1:1 debit). Bearish mirrors.
   - VOL_EXPANSION → `LONG_STRADDLE`, `LONG_STRANGLE`.
   - RANGEBOUND / LEAN_* **and** `far_quotes` present → `CALL_CALENDAR` /
     `PUT_CALENDAR` (sell the near-expiry strike, buy the same strike of the far
     expiry). Family `CALENDAR`; the long leg carries `expiry`; `max_loss` = the
     net debit, `max_profit` unknown (depends on the far leg's IV at the near
     expiry) — flagged in `caveats`.
   Each `StrategySuggestion` carries `family`, `direction_bias`, `risk`
   (`DEFINED`/`UNDEFINED`), `net` (`CREDIT`/`DEBIT`/`UNKNOWN`), `legs`
   (`action, lots, option_type, strike, role, ltp, oi, oi_change, expiry`),
   `est_net_premium`, approximate `max_profit` / `max_loss` / `breakevens`, and
   the band framing `lower_breakeven` / `upper_breakeven` /
   `spot_inside_breakevens` (spot within a two-sided profit zone).
4. **Edge** — when `atm_iv` + `t_years` are given, each same-expiry suggestion
   gets a `pop` (probability of profit at expiry): the piecewise-linear expiry
   payoff is built from the legs and the lognormal density —
   `ln S_T ~ N(ln spot + (r − σ²/2)t, σ²t)`, `σ = atm_iv` — is integrated over
   the price region where payoff > 0 (`pop_basis = LOGNORMAL_IV`). Calendars use
   `LOGNORMAL_NEAR_RANGE` — P(price within ±wing of the strike at the near
   expiry). `reward_risk = max_profit / |max_loss|` (both defined), `edge_score =
   pop · reward_risk`, `high_pop = pop ≥ config.high_pop` (default 0.70). With
   `config.rank_by_edge` (default true) the book is sorted **best `edge_score`
   first** (rows without an edge after); `config.min_reward_risk` (default 0)
   drops defined-risk rows below the ratio. `StrategyBook` also carries
   `atm_iv`, `far_expiry`, `ranked_by`. Capped at `config.max_suggestions`
   (default 8).

Config keys read from `app_settings`: `options.strategy_wing_steps`,
`options.strategy_wing_points`, `options.strategy_max_suggestions`,
`options.strategy_min_reward_risk`. Query params: `wing_points`, `calendars`.

### 11.6 Premium decay (`decay.py`, `docs/07` §4.23)

**Owner-authorised 2026-09-11.** Theta-implied decay vs. the session's actual
premium move, per strike, for one underlying's near expiry — a **read view**
(no factor score, no version guard, enums module-local), computed on read from
the live `chain.py` build (IV/theta) + each option's M1 premium at today's
session open. Descriptive only — a `decay_state` label, never a BUY/SELL
instruction (decision 15).

- `build_premium_decay(*, underlying_symbol, spot, expiry, days_to_expiry,
  atm_strike, now, session_open, legs, config=DecayConfig())`. Each
  `DecayLegInput(strike, option_type, ltp, iv, theta, lot_size, price_at_open)`
  — `theta` and `iv` come straight from the live `ChainLeg` (§11.3); the API
  layer resolves `price_at_open` from the option's M1 bars (earliest close
  at/after the session open) and `lot_size` from the instrument record. Pure,
  no IO.
- **Per strike / leg:** `theta_per_lot` = `theta × lot_size` (₹/day for one
  lot); `theta_pct_of_premium` = `theta / ltp` (a normalised decay rate,
  comparable across strikes regardless of premium level); `expected_decay` =
  `theta × elapsed_calendar_days` since the session open — a **linear
  back-of-envelope estimate at the option's current Greeks**, not a
  re-pricing at the morning's spot/IV (theta is evaluated *now*, at the
  current time-to-expiry, and assumed constant across the elapsed window);
  `actual_change` = `ltp − price_at_open`; `decay_gap` = `actual_change −
  expected_decay`. `decay_state` = `_decay_state(expected, actual, config)`:
  `NO_DATA` when either side is missing; else within
  `max(price_epsilon_abs, gap_epsilon_frac · |expected_decay|)` of zero ⇒
  `AS_EXPECTED`; `decay_gap < 0` (lost more than theta alone predicts) ⇒
  `DECAYING_FASTER`; else (a price/IV move outweighed the theta bleed) ⇒
  `OFFSET_BY_MOVE`. On all but the quietest sessions the actual move dwarfs
  the linear theta estimate — showing that split is the point of the screen,
  not a defect in the estimate.
- **Headline figures:** `atm_call_theta_per_lot` / `atm_put_theta_per_lot` /
  `atm_straddle_theta_per_lot` (sum of the two) at `atm_strike`; `days_to_expiry`
  + `fast_decay_zone` (`dte ≤ 5`, the well-known window where theta
  accelerates non-linearly — a flag only, no re-modelling of the curve).
- Not persisted — computed on read. Carries `algo_version` + independent
  `decay_version` (`DECAY_VERSION`, currently `0.1.0`). Options only;
  `GET /instruments/{id}/premium-decay`; a `/instruments/:id/premium-decay`
  screen.

Config keys read from `app_settings`: `options.decay_epsilon_abs` (default
0.5), `options.decay_gap_epsilon_frac` (default 0.3) — internal defaults, not
yet exposed on `PATCH /config` (same status as the strategy-suggestion tuning
keys in §11.5).

---

## 12. Gaps, halts, non-final bars

- Missing bars are real (§3.4); the engine never invents them. `meta.gap_count`
  and `coverage_ratio` report the condition.
- The last bar may be non-final; every result carries `last_bar_final`. Scoring
  may down-weight signals that hinge on it (`docs/06`).
- Daily during a session: the forming D1 bar is included with
  `last_bar_final = false`. A Golden Cross first appearing on the forming bar is
  reported with `provisional = true`.

## 13. Versioning

- `analytical_core.versioning.ALGO_VERSION` — single string. Current: **3.1.0**
  (3.0.0 = the six indicators; 3.1.0 added Market Profile to the deterministic
  engine surface).
- Bump on any change to a formula, default parameter, rounding, tie-break, or
  approximation. The engine-output snapshot is regenerated + reviewed on every
  bump; a CI guard asserts the bump (`docs/09` §2.1).
- `params_id` / `params_hash` (from `analytical_core.params`) travel on every
  result and into `analysis_results` columns (`docs/03` §5.4).

## 14. Output payload contract

Each `analysis_key` has a Pydantic model in `app/api/schemas/analysis/` mirroring
the engine's `values` / `aux` / `series` / `meta`. `analysis_results.result`
JSONB is validated against it on write. Enum-typed fields use
`analytical_core.enums` (`docs/12`). This is the contract the frontend and any
future chart / ML / AI consumer codes against.
