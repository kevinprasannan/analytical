# 04 — Data Model

## 1. Model layering

| Layer | Where | Purpose | May depend on |
|-------|-------|---------|---------------|
| **Core types** | `analytical_core` | Inputs/outputs of pure analysis + scoring; the enum contract (`analytical_core.enums`, see `docs/12`). Plain frozen dataclasses / typed arrays. | stdlib + numpy only |
| **ORM models** | `app/db/models/` | SQLAlchemy mappings to `docs/03` tables. | SQLAlchemy, `analytical_core.enums` |
| **API DTOs** | `app/api/schemas/` | Pydantic request/response models; the OpenAPI contract. | Pydantic, `analytical_core.enums` |

Enums are defined **once** in `analytical_core.enums`; DB and API derive from it
and a CI test enforces parity (`docs/12` §2, `docs/09` §2.6). Mapping helpers:
`app/analysis/` (ORM → core), `app/scoring/` (core → ORM), `app/api/` (ORM →
DTO). The core layer never imports ORM or Pydantic.

## 2. Instrument abstraction

The analysis engine never branches on a specific instrument. It receives numeric
series + resolved parameters + (for Market Profile) session boundaries. It never
receives an `Instrument`.

### 2.1 Canonical `Instrument`

Storage: `instruments` table (`docs/03` §5.1). Fields:

- Identity: `id`, `contract_key` (provider-independent canonical id, UNIQUE),
  `symbol`, `display_name`
- Classification: `exchange`, `segment` (`instrument_segment`),
  `instrument_type` (`INDEX | FUTURE | OPTION`)
- Derivative attributes: `underlying_id` (FK → an **INDEX** `instruments` row;
  `CHECK underlying_id <> id`), `expiry_date`, `expiry_kind`
  (`WEEKLY | MONTHLY | QUARTERLY`), `strike_price`, `option_type` (`CE | PE`)
- Trading attributes: `lot_size`, `tick_size`, `currency` (`INR`)
- Platform flags: `is_active`, `is_tracked`
- Capability flags: `has_volume` (bool — drives Volume applicability),
  `has_intraday_oi` (bool — **RESOLVED `docs/11` PV-4, 2026-08-27: branch
  A_PER_CANDLE**, so default `true` for FUTURE/OPTION; INDEX always `false`.
  Per-candle OI comes in the same v3 candle response as OHLCV.)
- Analysis hints: `profile_bin_size` (nullable → derived per `docs/05` §10.4)

### 2.2 Capability resolution (done before the engine is called)

Given an `Instrument`, `app/analysis/` resolves:

- **Applicable analyses** — from the matrix in §4, filtered further by config.
- **Has OI?** `instrument_type in (FUTURE, OPTION)` and `has_intraday_oi`
  (branch A) or snapshot OI configured (branch B). `INDEX` → never.
- **Has volume?** `has_volume`.
- **Provider identity** — via `provider_instrument_map` for the active provider.
- **Session** — via `market_calendar` for `(exchange, segment, date)`.
- **Expected analyses for scoring** — `expected_analyses(instrument_type)`, §5.

### 2.3 Instrument universe policy (resolves H6 / M28)

Lives in `app/instruments/universe.py` (`plan_universe`) + the
`analytical-instruments build-universe` CLI, not the engine. **Config-driven** —
`app_settings` `option_selection.*`:

| key | default | meaning |
|---|---|---|
| `option_selection.underlyings` | `["NIFTY", "BANKNIFTY", "SENSEX"]` | index symbols to build chains for — **add another index by editing this list, no code** (provider keys known for NIFTY/BANKNIFTY/FINNIFTY/MIDCPNIFTY/SENSEX/BANKEX) |
| `option_selection.strike_window` | `15` | ATM ± N strike steps per expiry |
| `option_selection.max_expiries` | `5` | nearest option expiries to track |
| `option_selection.strike_step.{SYM}` | 50 / 100 | strike ladder step per underlying |

`build-universe` reads the config + the provider instrument master + a spot per
underlying (latest ingested INDEX bar, or `--spot SYM=price`), computes the
tracked set (index + near/next monthly futures + CE/PE within
`ATM ± strike_window` for the next `max_expiries` expiries), syncs those
contracts into the registry, and **rolls `is_tracked`** to exactly that set.
Idempotent — re-running performs the expiry roll and re-centres the strike
window. **Auto-wired (2026-09-09):** the worker's `analytical-universe-roll`
timer job (`docs/02` §3.7, `UNIVERSE_DAILY_ROLL`, every 6 h + once on start)
calls `app.instruments.roll.roll_universe` after `download_upstox_masters`
re-pulls the current NSE+BSE masters — so the tracked strikes follow spot and
new weekly expiries appear without a manual run. The next engine cycle ingests
the newly-tracked contracts. `analytical-instruments build-universe
--refresh-master` does the same download+roll from the CLI. Session-stable
hysteresis (`rebuild_trigger`, fixed-ATM-for-the-session) is spec'd below but
not yet enforced — the roll re-centres on the live spot each run.

Options are ingested **M1 + OI only** (no M5/M15/H1 aggregation) so a wide
chain stays within the cycle budget; the chain view (docs/05 §11) needs only the
latest premium + OI. Options are likewise **chain-only in ANALYZE**: only
`open_interest` runs; every premium-series technical is `NOT_APPLICABLE` (§4).

**Futures rollover**
- Track, per underlying: `near` = nearest non-expired monthly contract;
  `next` = the following monthly contract. (NIFTY/BANKNIFTY F&O are monthly;
  weeklies, where listed, are options only.)
- Roll: on the first cycle of the session **after** `near`'s `expiry_date`,
  `near ← old next`, and a new `next` is created/enabled from the instrument
  master.
- Expired contracts: `is_tracked = false`, `is_active = false`, **retained** for
  history (never deleted).

**Option selection (session-stable — hysteresis)**
- Underlyings: NIFTY, BANKNIFTY.
- Expiries: the nearest `max_expiries` (default 2) expiries the instrument
  master lists as **active** for that underlying — whatever their `expiry_kind`.
  Do **not** assume a weekly exists.
- Strike step: `app_settings` `option_selection.strike_step.{NIFTY,BANKNIFTY}`
  (defaults 50 / 100) or derived from the master's strike ladder.
- Strike window: ATM ± `strike_window` steps (default N = 5), where **ATM is
  fixed at the first cycle of the day** from the underlying's prior-session
  close (or first print), and **held for the whole session**.
- Intra-session rebuild is allowed only if the underlying moves beyond
  `rebuild_trigger` steps (default 8) from the fixed anchor; the rebuild happens
  at the next cycle and is logged. Otherwise the set is unchanged all session.
- Out-of-window instruments: `is_tracked = false` at the next daily fixing;
  retained.
- Rationale: prevents `analysis_results` / `current_*` / dashboard churn.

**Index constituents are outside this universe.** The NIFTY-50 (etc.) member
stocks are **not** `Instrument` rows, are not tracked, and are not ingested —
they are seeded reference data in `index_weights` (`docs/15`, `docs/03` §5.8),
read on demand and joined to a quote-on-read snapshot. Adding them as tracked
instruments would be a separate universe-policy change.

### 2.4 `expiry_kind` derivation

**RESOLVED `docs/11` PV-6, 2026-08-27:** the Upstox NSE instrument master carries
an explicit **`weekly` boolean** on every derivative row (verified first-hand).
Primary rule: `weekly == true` → `WEEKLY`; `weekly == false` → `MONTHLY`, or
`QUARTERLY` for a far-dated quarter-end contract. The "last expiry of a calendar
month" heuristic is only a secondary tiebreak (splitting `MONTHLY` vs
`QUARTERLY` among `weekly == false` rows). The rule in force is recorded in
`analysis_runs.config_snapshot`. **Verified against live data:** NIFTY has
`weekly == true` expiries; **BANKNIFTY has none** (monthly-only) — do not assume
BANKNIFTY weeklies (H6).

## 3. Core types (`analytical_core`)

### 3.1 Inputs

```
Timeframe        # enum: M1, M5, M15, H1, D1   (docs/12)
AnalysisScope    # enum: PER_TIMEFRAME, SESSION, SNAPSHOT

@dataclass(frozen=True)
class OHLCVSeries:
    timeframe: Timeframe
    ts: Sequence[datetime]      # tz-aware UTC, BAR-OPEN, strictly increasing
    open/high/low/close: Sequence[float]
    volume: Sequence[int]       # >= 0; may be all zero -> volume NOT_APPLICABLE
    is_final: Sequence[bool]    # last element may be False (forming bar)
    expected_grid_len: int      # session-anchored period count for coverage calc
    # NOTE: no bar is fabricated for a no-trade interval; gaps are real (docs/05 §3.4)

@dataclass(frozen=True)
class OpenInterestSeries:
    scope: AnalysisScope        # PER_TIMEFRAME (branch A) or SNAPSHOT (branch B)
    ts: Sequence[datetime]      # bar-open (branch A) or poll instant (branch B), UTC
    oi: Sequence[int]
    price: Sequence[float]      # the instrument's OWN price series, aligned 1:1 to oi
    provider_oi_change: Sequence[int] | None   # stored for cross-check only; NOT used

@dataclass(frozen=True)
class SessionSpec:
    tz: str                     # "Asia/Kolkata"
    session_open_ist: time      # default 09:15
    session_close_ist: time     # default 15:30
    session_date: date
    # Market Profile params (docs/05 §10) travel in MarketProfileConfig, not here.
```

**Contract rules**
- `ts` ascending, unique, tz-aware UTC, bar-open.
- No NaN in OHLC. `volume >= 0`.
- Callers pass enough history for the largest lookback; the engine returns
  `INSUFFICIENT_DATA` rather than guessing.
- `coverage_ratio = bars_present / expected_grid_len`. Below `min_coverage`
  (default 0.6) the engine returns `INSUFFICIENT_DATA` (`reason = "sparse
  series"`).

### 3.2 Outputs

Every analysis returns a frozen result with:
- `status`: `OK | INSUFFICIENT_DATA | NOT_APPLICABLE | ERROR`
- `scope`: `PER_TIMEFRAME | SESSION | SNAPSHOT`
- `as_of_ts`: the instant the result refers to (bar-open / session-open / poll)
- `values`: analysis-specific scalars (contract per `docs/05`)
- `aux`: scalars a sub-score needs that are not "headline" values
  (e.g. EMA `atr14`, Volume `price_change_pct_recent`, Market Profile `close`)
- `series` *(optional, small)*: per-bar arrays for history/divergence
- `warnings`: list[str]
- `meta`: **provenance** — `algo_version`, `params_id`, `params_hash`,
  `input_window_start/end`, `bars_used`, `coverage_ratio`, `warmup_ok`,
  `last_bar_final`, plus analysis-specific params. (Resolves M19.)

### 3.3 Scoring types

```
@dataclass(frozen=True)
class FactorInput:
    analysis_key: str
    scope: AnalysisScope
    status: AnalysisStatus
    values: dict
    aux: dict
    meta: dict            # incl. params_hash, warmup_ok, last_bar_final, provisional

@dataclass(frozen=True)
class InstrumentRef:
    instrument_id: int
    instrument_type: InstrumentType
    expected_analyses: frozenset[str]   # computed by app/scoring, passed as DATA

@dataclass(frozen=True)
class ScoringInput:
    instrument: InstrumentRef
    timeframe: Timeframe
    as_of_ts: datetime
    factors: tuple[FactorInput, ...]

@dataclass(frozen=True)
class FactorBreakdown:
    analysis_key: str
    raw_values: dict
    sub_score: float        # -100..+100
    confidence: float        # 0..1
    weight: float
    contribution: float      # signed; sum(contribution) == composite_score
    reason: str

@dataclass(frozen=True)
class CompositeResult:
    instrument_id: int
    timeframe: Timeframe
    as_of_ts: datetime
    composite_score: float          # -100..+100
    raw_label: SignalLabel          # pure function of composite + bands
    effective_label: SignalLabel    # after low-confidence clamp
    confidence: float               # 0..1
    low_confidence: bool
    factors: tuple[FactorBreakdown, ...]
    warnings: tuple[str, ...]
    explanation: str                # deterministic template
    strategy: str
    scoring_version: str
    params_hash: str
```

The scoring engine reads **only** `ScoringInput`. It never touches raw bars or an
`Instrument` object; `instrument_type` and `expected_analyses` arrive as data.
(Resolves C4.)

## 4. Analysis applicability matrix (resolves H1, strategic directives 2–4)

`OK-path` = normally produces `OK`. `NA` = `NOT_APPLICABLE` by design (excluded
from scoring with **no** confidence penalty). `INSUF` = applicable but commonly
`INSUFFICIENT_DATA` for that type/timeframe (excluded; **penalty only if the
factor is expected**).

| analysis_key | scope | INDEX | FUTURE (dated) | OPTION (dated) |
|---|---|---|---|---|
| `rsi` | PER_TIMEFRAME | OK-path, all TF | OK-path M5/M15/H1; D1 INSUF until history | **NA** — chain-only |
| `bollinger` | PER_TIMEFRAME | OK-path | OK-path intraday; D1 needs ≥ period | **NA** — chain-only |
| `ema7` | PER_TIMEFRAME | OK-path | OK-path | **NA** — chain-only |
| `golden_cross` | PER_TIMEFRAME | **OK-path (primary), D1 default** | **NA** by default; opt-in → INSUF then OK with warning | **NA** by default |
| `volume` | PER_TIMEFRAME | OK-path if `has_volume` else **NA** | OK-path | **NA** — chain-only |
| `open_interest` | **PER_TIMEFRAME** (branch A_PER_CANDLE — RESOLVED `docs/11` PV-4) | **NA** (no OI) | OK-path | OK-path (per-strike semantics, `docs/05` §9.5) |
| `order_block` | PER_TIMEFRAME | OK-path (`docs/05` §9a) | OK-path | **NA** — chain-only |
| `candles` | PER_TIMEFRAME | OK-path (`docs/05` §9b) | OK-path | **NA** — chain-only |
| `market_profile` | SESSION | OK-path (TPO always; Volume Profile needs `has_volume`) | OK-path | INSUF if premium range < `min_bins` |

**OPTION is chain-only (§2.3).** A tracked option feeds only the option-chain
view (`docs/05` §11) — latest premium + OI in, IV / greeks / PCR / max-pain
computed on read. Its premium series is **not** a V1 analysis input, so every
premium-series technical is `NOT_APPLICABLE` by design (no confidence penalty);
only `open_interest` runs in ANALYZE. This bounds the per-cycle ANALYZE cost of a
wide chain (hundreds of strikes × 4 timeframes would otherwise dominate a cycle).

**`expected_analyses(instrument_type)`** (used for the confidence denominator,
`docs/06` §4; configurable):

- `INDEX` → `{rsi, bollinger, ema7, golden_cross, market_profile, order_block,
  candles}` ∪ `{volume}` iff `has_volume`.
- `FUTURE` → `{rsi, bollinger, ema7, volume, open_interest, market_profile,
  order_block, candles}`. (`golden_cross` **not** expected.)
- `OPTION` → `{open_interest}`.
  (chain-only — `rsi` / `bollinger` / `ema7` / `volume` / `market_profile` are
  `NA` and not expected.)

## 5. Units, precision, time

| Quantity | Type | Notes |
|---|---|---|
| Price | float in engine; `NUMERIC(18,4)` at rest | rounding rules per indicator (`docs/05` §2) |
| Volume / OI | int / `BIGINT` | never negative |
| Timestamps | tz-aware UTC, **bar-open** everywhere (resolves H2) | IST only for session math + display |
| RSI | 0..100 (2 dp) | |
| %B | unbounded float (6 dp) | |
| Bandwidth | `(upper-lower)/basis` (6 dp) | |
| Scores / sub-scores / contributions | −100..+100 (6 dp) | |
| Confidence | 0..1 (6 dp) | |
| `params_hash` | first 16 hex of sha256(canonical-json(effective params)) | provenance |

## 6. Provenance (backtesting-ready, not backtested — strategic directive 22)

Every `analysis_results` row and `signal_scores` row carries: `run_id` (one run
per cycle), `algo_version` / `scoring_version`, `params_id`, `params_hash`,
`input_window_start/end`, and (on the run) `config_snapshot`. Re-running the same
engine version over the same window with the same effective params reproduces
identical `result` payloads — enforced by `docs/09` §2.5. Long-history
backtesting is bounded by the retention windows in `docs/03` §6 and would need a
separate archival job (future, not V1).
