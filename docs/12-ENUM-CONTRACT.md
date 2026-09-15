# 12 — Authoritative Enum Contract

**Purpose (resolves M20).** Enumerated values are defined **once**, in
`analytical_core.enums` (a pure module, standard library only). The PostgreSQL
`ENUM` types and the API/DTO schemas are derived from — and continuously checked
against — this single list. No enum value is defined independently in the DB
layer or the API layer.

---

## 1. Source of truth

- `backend/analytical_core/enums.py` — Python `enum.Enum` / `enum.StrEnum`
  classes. Importable by `app/` (which depends on `analytical_core`), never the
  reverse.
- Storage form: `UPPER_SNAKE_CASE` string values, **except** `analysis_key`
  which is `lower_snake_case` (it is used as a JSON map key and URL path
  segment).
- `analytical_core.enums.ENUM_REGISTRY: dict[str, type[Enum]]` maps a stable
  contract name → the enum class. The registry is the list the DB migrations and
  the contract test iterate over.

## 2. Synchronisation mechanism

1. **DB.** Alembic migrations create each Postgres `ENUM` type from
   `list(EnumClass)` — the migration author copies the values from a helper
   (`python -m analytical_core.enums --emit-sql`) rather than hand-typing them.
2. **API.** Pydantic DTOs import the same Python enums directly. FastAPI emits
   their values into the OpenAPI schema. The generated TypeScript client
   therefore inherits them.
3. **Frontend.** `GET /api/v1/meta/enums` also serves the full registry at
   runtime (label + value + description) for schema-driven UI (filters, config
   form). The build-time generated types remain the compile-time contract.
4. **CI gate — `test_enum_contract`** (see `docs/09` §2.6): for every entry in
   `ENUM_REGISTRY`, assert
   `set(python_values) == set(pg_enum_labels) == set(openapi_enum_values)`.
   A mismatch fails the build.

## 3. Change procedure

Adding a value:
1. Add it to the enum class in `analytical_core.enums` (append; never reorder or
   renumber — ordering is not semantic but stability aids diffs).
2. New Alembic migration: `ALTER TYPE <type> ADD VALUE '<VALUE>'`
   (Postgres allows add, not remove; removal = new type + swap, treated as a
   breaking change → `/api/v2`).
3. Regenerate the OpenAPI snapshot and the frontend client; commit the diff.
4. `test_enum_contract` must pass.

Bump `ALGO_VERSION` / `SCORING_VERSION` only if the new value changes analysis or
scoring output for existing inputs.

## 4. The enums

### Market / instrument

| Contract name | Values | Notes |
|---|---|---|
| `timeframe` | `M1, M5, M15, H1, D1` | `M1` is an **ingestion/aggregation source only** in V1 — not offered as a user-facing analysis timeframe. User-facing analysis timeframes: `M5, M15, H1, D1`. |
| `instrument_type` | `INDEX, FUTURE, OPTION` | Extensible (`EQUITY`, `CURRENCY_FUTURE`, …). |
| `instrument_segment` | `INDEX, FUT, OPT` | Exchange segment label. |
| `option_type` | `CE, PE` | |
| `expiry_kind` | `WEEKLY, MONTHLY, QUARTERLY` | Derivatives only; NULL for index. Resolves M3. |
| `data_kind` | `OHLCV, OI` | Used by `ingestion_watermarks`. |
| `provider_name` | *(not an enum — free text)* | Provider ids are open-ended; kept as text with a documented active value. |

### Analysis

| Contract name | Values | Notes |
|---|---|---|
| `analysis_scope` | `PER_TIMEFRAME, SESSION, SNAPSHOT` | Resolves C1. Determines which of `timeframe` / `session_date` / `snapshot_ts` is populated on `analysis_results`. |
| `analysis_key` | `rsi, bollinger, ema7, golden_cross, volume, open_interest, market_profile, order_block, candles` | Lowercase. `ema7` = EMA with default period 7 (period configurable; key name fixed). `order_block` added 2026-09-07 (`docs/05` §9a) — migration `0006`. `candles` added 2026-09-07 (`docs/05` §9b) — needs migration `0007` to widen the `analysis_key_known` CHECK on an existing DB. |
| `analysis_status` | `OK, INSUFFICIENT_DATA, NOT_APPLICABLE, ERROR` | `NOT_APPLICABLE` = excluded **by instrument-type design** (no confidence penalty). `INSUFFICIENT_DATA` = applicable but not enough data yet (penalty only if the factor is *expected* for that instrument type). |
| `profile_type` | `TPO, VOLUME` | |
| `market_profile_shape` | `NORMAL, P_SHAPE, B_SHAPE, DOUBLE_DISTRIBUTION, TREND_UP, TREND_DOWN` | Deterministic classifier defined in `docs/05` §10.8. Resolves H4. |
| `oi_behavior` | `LONG_BUILDUP, SHORT_BUILDUP, LONG_UNWINDING, SHORT_COVERING, INDETERMINATE` | |
| `oi_direction` / `price_direction` | `UP, DOWN, FLAT` | Intermediate signed directions after epsilon thresholding (`docs/05` §9). |
| `bollinger_position` | `ABOVE_UPPER, UPPER_HALF, MIDDLE, LOWER_HALF, BELOW_LOWER` | `MIDDLE` covers the degenerate `upper == lower` case. |
| `ma_slope_state` | `RISING, FALLING, FLAT, UNKNOWN` | `UNKNOWN` when slope lookback not yet satisfied. |
| `rsi_state` | `OVERBOUGHT, OVERSOLD, NEUTRAL` | |
| `golden_cross_type` | `GOLDEN, DEATH, NONE_IN_WINDOW` | |
| `divergence` | `BULLISH, BEARISH, NONE` | RSI price/oscillator divergence (`docs/05` §4). Contract/API-only (JSONB `values` field), no PG type. |
| `volume_trend` | `RISING, FALLING, FLAT` | Sign of the OLS slope of volume over the MA window (`docs/05` §8). Contract/API-only, no PG type. |
| `volume_up_down_state` | `MORE_UP, MORE_DOWN, BALANCED, ALL_UP, ALL_DOWN` | Up/down bar mix over the MA window (`docs/05` §8). Contract/API-only, no PG type. |
| `order_block_bias` | `BULLISH, BEARISH, NEUTRAL` | Net structural lean from the active order blocks (`docs/05` §9a). Contract/API-only, no PG type. |
| `order_block_zone_state` | `OUTSIDE, IN_BULLISH, IN_BEARISH` | Whether price sits inside a bullish (demand) or bearish (supply) order block (`docs/05` §9a). Contract/API-only, no PG type. |
| `candle_pattern` | `DOJI, GRAVESTONE_DOJI, DRAGONFLY_DOJI, MARUBOZU, HAMMER, INVERTED_HAMMER, HANGING_MAN, SHOOTING_STAR, BULLISH_ENGULFING, BEARISH_ENGULFING, BULLISH_HARAMI, BEARISH_HARAMI, PIERCING_LINE, DARK_CLOUD_COVER, MORNING_STAR, EVENING_STAR` | Major candlestick patterns recognised by `candles` (`docs/05` §9b). Contract/API-only, no PG type. |
| `candle_bias` | `BULLISH, BEARISH, NEUTRAL` | Directional lean of a recognised candle pattern (`docs/05` §9b). Contract/API-only, no PG type. |
| `candle_strength` | `WEAK, MODERATE, STRONG` | Pattern conviction, upgraded by matching trend context (`docs/05` §9b). Contract/API-only, no PG type. |

### Scoring

| Contract name | Values | Notes |
|---|---|---|
| `signal_label` | `STRONG_BEARISH, BEARISH, NEUTRAL, BULLISH, STRONG_BULLISH` | **Analytical** labels. The system never emits BUY/SELL or execution instructions (`docs/01` §1, `docs/06` §1). |
| `scoring_strategy` | `weighted_v1` | Extensible; the aggregation strategy id stored per score. |

### Run / operations

| Contract name | Values | Notes |
|---|---|---|
| `run_trigger` | `SCHEDULED, MANUAL, BACKFILL` | |
| `run_status` | `RUNNING, SUCCEEDED, PARTIAL, FAILED` | One row per execution cycle (`docs/03` §5.3, resolves H13). |
| `run_phase` | `INGEST, ANALYZE, SCORE` | |
| `phase_status` | `PENDING, RUNNING, SUCCEEDED, PARTIAL, FAILED, SKIPPED` | Per (run, phase). |
| `instrument_phase_outcome` | `OK, DEGRADED, SKIPPED, ERROR` | Per (run, instrument, phase). This is where "instrument X was degraded this cycle" is recorded. |
| `watermark_status` | `OK, ERROR, RATE_LIMITED, AUTH_FAILED` | On `ingestion_watermarks`. |
| `provider_auth_state` | `OK, EXPIRED, UNKNOWN` | Surfaced by `/health/ready`. Resolves C2 visibility. |

## 5. Non-enum controlled vocabularies

These are validated in code but kept as `text` (values churn or are
provider-defined): `provider_name`, `params_id`, config keys in `app_settings`,
`warnings[]` strings (templated, not enumerated).
