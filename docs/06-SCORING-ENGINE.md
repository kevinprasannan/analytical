# 06 — Scoring Engine

## 1. Role, boundaries, and what it is not

- Part of `analytical_core` (`analytical_core.scoring`). **Pure** — no IO, no
  FastAPI, no DB, no raw bars, no `Instrument` object.
- **Input:** a `ScoringInput` (`docs/04` §3.3) for one
  `(instrument, timeframe, as_of_ts)` — a tuple of `FactorInput`s plus an
  `InstrumentRef` carrying `instrument_type` and `expected_analyses` **as
  data** (computed by `app/scoring/`). Plus a `ScoringConfig`.
- **Output:** one `CompositeResult` (`docs/04` §3.3).
- `app/scoring/` orchestrates: gather the same-run `analysis_results`, build the
  `ScoringInput`, call the engine, persist `signal_scores` + `score_factors`,
  update `current_signal_scores`.

**This is analytical decision-support, not an execution system.** It never
produces BUY / SELL / entry / exit / target / stop output. The discrete outputs
are analytical labels: `STRONG_BEARISH, BEARISH, NEUTRAL, BULLISH,
STRONG_BULLISH`.

- **No ML, no parameter optimisation in V1.** Aggregation is a transparent
  documented function. The aggregation interface is a strategy so an ML strategy
  could be added later without touching sub-score functions.

## 2. Pipeline

```
FactorInput[] ──> per-analysis sub-score fn ──> (sub_score, confidence, reason, rationale)
                                                      │
                    ScoringConfig (weights, params) ──┤
                    InstrumentRef.expected_analyses ──┤
                                                      ▼
                                aggregation strategy (weighted_v1)
                                                      ▼
   CompositeResult{ composite_score, raw_label, effective_label, confidence,
                    low_confidence, factors[], warnings[], explanation }
```

## 3. Sub-scores

- Scale: **−100 (max bearish) .. +100 (max bullish)**, `0` = neutral / no
  information.
- Confidence: **0..1**, reflecting data sufficiency and signal clarity
  (warm-up not met, non-final bar, weak separation, provisional cross → lower).
- Sub-score functions read **only** `FactorInput.values`, `FactorInput.aux`,
  `FactorInput.meta`. They never see raw bars. Every scalar a sub-score needs is
  supplied by the analysis result (`aux`): EMA `atr14`, Volume
  `price_change_pct_recent`, Market Profile `close` + `close_vs_vah/val`
  (resolves C4).

### 3.1 Per-analysis sub-score rules (V1 defaults, all configurable)

**RSI**
- `base = clamp((rsi − 50) · 2, −100, 100)`.
- Mean-reversion damping: if `rsi ≥ 70` → `base = min(base, 100) − overbought_penalty`
  (default 20); mirror for `rsi ≤ 30` (+20).
- `divergence`: `BULLISH` +25, `BEARISH` −25 (added, then clamp to ±100).
- `confidence = 0.9` if `warmup_ok and last_bar_final` else `0.5`.

**Bollinger**
- From `position`: `ABOVE_UPPER` +60, `UPPER_HALF` +25, `MIDDLE` 0,
  `LOWER_HALF` −25, `BELOW_LOWER` −60.
- `%B` fine adjust: `+ clamp((percent_b − 0.5)·40, −20, +20)`.
- `squeeze == true` → multiply magnitude by `squeeze_damp` (default 0.5).
- `confidence`: base 0.8; ×0.7 if `bandwidth_percentile` is null; higher when
  `bandwidth_percentile` is mid-range.

**7 EMA**
- `vol_ref = aux.atr14` if not null, else `aux.close_stdev_n` (the engine also
  exposes a fallback recent close stdev), else `0.01 · ema` (last resort).
- `norm = clamp(price_vs_ema / max(vol_ref, tiny), −2, 2)` → `base = norm · 35`.
- `slope_state`: `RISING` +15, `FALLING` −15, `FLAT`/`UNKNOWN` 0.
- `confidence = 0.8` if `slope_state != UNKNOWN and warmup_ok`; `0.6` if
  `aux.atr14` is null (fallback vol_ref used); `0.5` otherwise.

**Golden Cross**
- Only contributes on `INDEX` (or opted-in dated contract, with a warning).
  `NOT_APPLICABLE` → no factor row, no penalty.
- `state ABOVE` → base +40, `BELOW` → −40.
- `cross_type GOLDEN and recent` → +40; `DEATH and recent` → −40 (added).
- `+ clamp(separation · sep_k, −20, +20)` (`sep_k` default 800).
- `provisional == true` → final magnitude × 0.5.
- `confidence = 0.9` if `bars_used ≥ slow_period + cross_search_window and
  last_bar_final` else scaled down (min 0.4).

**Volume**
- `scaled_rvol` from `rvol`: `1.0 → 0`, `2.0 → 1.0`, linear, clamp 0..1
  (null `rvol` → 0).
- `dir = sign(aux.price_change_pct_recent)` (0 → treat as +1 for spike only).
- `base = dir · scaled_rvol · 40`.
- `spike == true` → `+ dir · 15`.
- `trend RISING` with price up → `+8`; `trend RISING` with price down → `−8`
  (distribution).
- `confidence = 0.7`; the Volume factor is never the dominant term by default
  (weight 0.75, §4).
- If Volume is `NOT_APPLICABLE` (no volume) → no factor row; because Volume is
  **not** in `expected_analyses` for `INDEX` when `has_volume = false`, there is
  **no** confidence penalty (resolves H9 — the earlier "low confidence when
  absent" rule is removed).

**Open Interest** (FUTURE / OPTION)
- `LONG_BUILDUP` +50, `SHORT_COVERING` +35, `SHORT_BUILDUP` −50,
  `LONG_UNWINDING` −35, `INDETERMINATE` 0.
- Scale by `clamp(|oi_pct_change| / oi_ref_pct, 0, 1)` (`oi_ref_pct` default
  2%); if `oi_pct_change` is null (prior OI was 0) use a fixed scale of `0.5`.
- `confidence = 0.75` normally; `0.4` if `INDETERMINATE`; the option-strike
  semantics warning is copied into `rationale`.
- For OPTION this is the **only** factor — the contract is chain-only
  (`docs/04` §2.3/§4), so `expected_analyses(OPTION) = {open_interest}` and a
  strike's score rests entirely on its OI regime.

**Market Profile** (SESSION factor, reused across the instrument's timeframes)
- `close_vs_vah == ABOVE` → +40; `close_vs_val == BELOW` → −40.
- else `close_vs_poc ABOVE` → +20, `BELOW` → −20, `AT` → 0.
- `profile_shape`: `TREND_UP` +15, `TREND_DOWN` −15, `P_SHAPE` +8,
  `B_SHAPE` −8, `DOUBLE_DISTRIBUTION`/`NORMAL` 0.
- `close_in_value_area == true` → multiply magnitude by `in_value_damp`
  (default 0.6) — inside value = less conviction.
- `confidence = 0.8` if `is_session_complete` else `0.55` (session still
  forming).
- `INSUFFICIENT_DATA` (e.g. deep-OTM option) → no factor row; penalty only if
  `market_profile ∈ expected_analyses` (true for INDEX/FUTURE, not OPTION).

**Order Block** (INDEX / FUTURE PER_TIMEFRAME — `docs/05` §9a)
- `zone_state == IN_BULLISH` → `base = +in_zone_score` (default 70);
  `IN_BEARISH` → `−in_zone_score`.
- else `base = 60·pull(nearest_bullish) − 60·pull(nearest_bearish)`, where
  `pull(z) = max(0, 1 − |distance_pct| / dist_k_pct) · max(0, 1 − age_bars /
  age_full_bars)` over the nearest **unmitigated** block on each side
  (`dist_k_pct` default 1.0, `age_full_bars` default 60).
- `confidence = 0.8` when warmed up and the last bar is final and at least one
  block is in play; `0.45` otherwise; `0` (no factor row) when there are no
  active blocks. Weight `1.00` (§4.1). Never emits BUY/SELL — the sub-score is
  the only thing that leaves this factor.

**Candles** (INDEX / FUTURE PER_TIMEFRAME — `docs/05` §9b)
- No `last_pattern` in the scan window → `sub_score = 0`, `confidence = 0`
  (factor contributes nothing).
- Else `mag = pattern_score · strength_w · recency`, where `strength_w` ∈
  `{WEAK 0.4, MODERATE 0.7, STRONG 1.0}`, `recency = max(0, 1 − last_bars_ago /
  recency_bars)` (`pattern_score` default 55, `recency_bars` default 5). `base =
  ±mag` by `last_bias` (`NEUTRAL` → 0).
- Cluster bump: `base += clamp((n_bullish − n_bearish) · cluster_bump, ±3·
  cluster_bump)` (`cluster_bump` default 6). `base` clamped to ±100.
- `confidence = (0.75 if warm else 0.45) · (0.6 + 0.4·strength_w)` where `warm`
  = warmed up and last bar final. Weight `0.75` (§4.1). Descriptive only — never
  emits BUY/SELL.

## 4. Aggregation strategy `weighted_v1` (resolves M5, M6)

Let `U` = usable factors (`status == OK`), each with weight `wᵢ`, confidence
`cᵢ`, sub-score `sᵢ`. Let `E` = `expected_analyses(instrument_type)` ∩ (config
applicability).

- `denom = fsum(wᵢ · cᵢ for i in U)`.
- **If `denom == 0`** (no usable factors): `composite_score = 0.0`,
  `confidence = 0.0`, `raw_label = effective_label = NEUTRAL`,
  `low_confidence = true`, `warnings += "no usable factors"`. A `signal_scores`
  row **is still written** (dashboard shows the instrument with a clear no-data
  state).
- Else:
  - `composite_score = fsum(wᵢ · cᵢ · sᵢ for i in U) / denom` (∈ −100..+100).
  - `contributionᵢ = (wᵢ · cᵢ · sᵢ) / denom` → **`fsum(contributionᵢ) ==
    composite_score`** (single definition — resolves M5; the earlier
    `docs/03` "weight × sub_score" wording is corrected there too).
- **Overall confidence** (expected-but-missing factors drag it down):
  - `have = fsum(wₖ · cₖ for k in U)`
  - `expected_mass = fsum(wₖ · 1.0 for k in E)`  (missing expected factors count
    at confidence 1.0 in the denominator, contributing 0 to the numerator)
  - `union_mass = expected_mass + fsum(wₖ · cₖ for k in U and k ∉ E)`
  - `overall_confidence = clamp(have / union_mass, 0, 1)`.

Store `weights`, `denom`, `params_hash` on the `signal_scores` row so per
`(instrument, timeframe)` reconstruction is exact even under
`timeframe_overrides`.

### 4.1 Default weights (config `scoring.weights`; `timeframe_overrides` allowed)

| analysis_key | weight |
|---|---|
| `golden_cross` | 1.50 (INDEX only in practice) |
| `open_interest` | 1.25 (FUTURE / OPTION) |
| `ema7` | 1.00 |
| `bollinger` | 1.00 |
| `rsi` | 1.00 |
| `market_profile` | 1.00 |
| `order_block` | 1.00 (INDEX / FUTURE) |
| `candles` | 0.75 (INDEX / FUTURE) |
| `volume` | 0.75 |

Starting values, explicitly **unvalidated** (no backtest behind them). Editable
in `app_settings` without redeploy.

## 5. Labels (resolves M26)

`raw_label` — pure function of `composite_score` and `scoring.label_bands`:

| composite | label |
|---|---|
| ≥ +60 | `STRONG_BULLISH` |
| +20 .. +60 | `BULLISH` |
| −20 .. +20 | `NEUTRAL` |
| −60 .. −20 | `BEARISH` |
| ≤ −60 | `STRONG_BEARISH` |

Boundary resolution (implementation): `>= +60` → `STRONG_BULLISH`, `<= −60` →
`STRONG_BEARISH`; interior boundaries resolve symmetrically toward the stronger
label — exactly `+20` → `BULLISH`, exactly `−20` → `BEARISH`, `0` → `NEUTRAL`.

`effective_label`:
- if `overall_confidence < min_confidence` (default **0.35**) →
  `effective_label` = `raw_label` moved **one band toward NEUTRAL`;
  `low_confidence = true`.
- else `effective_label = raw_label`; `low_confidence = false`.

Both are stored. `GET /scores?label=` and dashboard sorting/colouring use
**`effective_label`** (documented in `docs/07` §4.5).

## 6. Explainability (strategic directives 6, 7)

Every `score_factors` row stores, per factor:

`analysis_key · scope · raw_values (dict) · sub_score · confidence · weight ·
contribution · reason (short templated string) · rationale (dict)`

Example `reason`: `"OI long buildup on the future (OI +1.8%, price +0.9%)"`.

The `signal_scores` row stores `strategy`, `scoring_version`, `params_hash`,
`weights`, `denom`, `warnings[]`, and `explanation`.

**`explanation`** — deterministic template (no model call). Factors are ordered
by `|contribution|` desc; each emits one clause from its `reason`; a header line
states the label, composite, and confidence. Example:

> BULLISH (58.4, confidence 0.71). Golden cross active on the index (6 bars
> ago). Price above the 7-EMA with a rising slope. OI: long buildup on the
> future. RSI 57 — neutral. Bollinger mid-range. Volume 1.4× average.

`warnings[]` collects: `NOT_APPLICABLE` / `INSUFFICIENT_DATA` factors, forming
bar, provisional cross, option-strike OI semantics, no-volume instruments, and
"no usable factors".

The `rationale` dicts + `explanation` string are the seam for a future AI
narration layer — **no engine change** required to add it.

## 7. `ScoringConfig`

```
@dataclass(frozen=True)
class ScoringConfig:
    strategy: str = "weighted_v1"
    weights: dict[str, float]
    label_bands: tuple[tuple[float, str], ...]
    min_confidence: float = 0.35
    per_analysis_params: dict          # penalties, refs, damps from §3.1
    timeframe_overrides: dict[str, "ScoringConfig"] | None = None
```

Assembled by `app/scoring/` from defaults + `app_settings`; passed in. The engine
never reads config itself. `params_hash` is computed from the effective
`ScoringConfig` and stored per score.

## 8. Versioning

- `SCORING_VERSION` in `analytical_core.versioning` — bump on any change to
  sub-score formulas, default params, aggregation, or label bands. Golden
  fixtures regenerated + reviewed; CI guard asserts the bump.
- `params_hash` on every `signal_scores` row (provenance parity with analyses).

## 9. Explicit non-goals (V1)

- No BUY/SELL/execution output of any kind.
- No regime detection / conditional weighting (`timeframe_overrides` + the
  strategy interface are the seam).
- No multi-timeframe fusion into a single score (each timeframe scored
  independently; a consensus view is a later frontend/aggregate concern).
- No learning from outcomes (needs backtesting + labels — future).
