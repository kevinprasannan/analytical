# 14 — Market Profile Event Layer (Phase 4, extends `docs/05` §10)

Owner-authorised 2026-08-31. This is an **extension** of the existing
deterministic Market Profile builder (`docs/05` §10 / `analytical_core.market_profile`),
not a replacement. The builder is unchanged; a new **pure** module
(`analytical_core.market_profile.events`) consumes its output plus the prior
session's profile and emits a typed **event** stream with lifecycle, strength and
a strict facts-vs-interpretation separation.

Full research spec + rationale (alternatives, master table, auction-theory
detectability grades): the "Market Profile Event Spec" artifact —
`https://claude.ai/code/artifact/9b1a84bf-bc83-456b-b052-0988e5e7dd79`. This doc
is the repo's authoritative summary; where they differ, this doc wins.

---

## 14.1 Locked decisions

| # | Decision |
|---|---|
| 1 | **TPO period = 30 min.** 13 brackets A–M in an NSE 09:15–15:30 session; M is the 15-min partial (`partial_period_policy = KEEP`). |
| 2 | **Initial Balance = first 30 min** ⇒ `ib_periods = 1`. Single-bracket IB — sensitive; an "IB range vs session range" study on 2022→now M5 is a follow-up before the parameter is frozen. `ib_periods` stays configurable. |
| 3 | **Relationship = extension.** Existing builder produces the `Profile`; the event module is a new pure `analytical_core` module (no FastAPI / SQLAlchemy / httpx / IO). |
| 4 | **FUT is the profile of record** for value / POC events wherever a mapped FUT exists. The INDEX TPO profile is still computed but carried `advisory` for those event families; `basis_fallback` when no FUT is mapped or its data is degraded. Structure / shape events run on the in-view instrument's own profile. |
| 5 | **Backtest window starts at the 2022 M5 floor.** No D1-only proxy *in this engine* for 2000–2022; it reports `INSUFFICIENT_DATA` before the floor. (A separate, clearly-labelled OHLC day-type classification `d1_day_type` lives in the **daily digest** report — `docs/07` §4.12 — for full-history context. It is descriptive reporting, never a substitute for the TPO event pipeline.) |
| 6 | **Expiry / atypical sessions:** mark `is_atypical`, keep the raw profile + events, exclude from trailing percentiles and composites by default (`include_atypical_in_stats = false`). |
| 7 | **Bin size:** fixed tick-multiple (recommendation stands; `resolve_bin_size` in §10.4 already does this). Revisit only if excess/poor detection is brittle. |
| 8 | **No BUY/SELL.** The event layer emits analytical states + an optional narrative string. Scoring (`docs/06`) consumes the structured states as data. |

## 14.2 Layered pipeline

```
FACTS          numeric session state, recomputed at each bracket close
   ↓           (developing_poc/vah/val/high/low, ib_*, ext_*, per-level relations)
EVENTS         typed occurrences, each a small lifecycle state machine + evidence
   ↓
CLASSIFICATION session rollups (day type, silhouette, value relationship, auction narrative)
   ↓
INTERPRETATION analytical narrative string — never a directive
   ↓
SCORING        out of scope here — the Scoring Engine consumes the above as data
```

`MP_EVENTS_VERSION` (module constant, semver) tags every result. It is
independent of `ALGO_VERSION` until the module is wired into `AnalysisService`
(slice 3); at that point it joins the engine-snapshot guard and a version bump.

## 14.3 Event lifecycle

`MPState`: `NOT_TRIGGERED → TRIGGERED → DEVELOPING → CONFIRMED`, with
`INVALIDATED` (terminal for that instance; a fresh trigger later opens a new
instance `id#2`) and `EXPIRED` (session closed while still TRIGGERED/DEVELOPING).
Skips forward are allowed. `DEVELOPING ↔ TRIGGERED` oscillation is logged; ≥3
flips emits `UNSTABLE_<level>` (weak).

Each `MPEvent` stores `state`, `state_history: [(state, bracket_index,
minutes_to_close, evidence)]`, `strength`, `basis` (`TPO|VOLUME`), `degraded`
(missing bracket in the evidence window) and `confirmed_close_only` (day type,
sustained acceptance, poor high/low — cannot reach CONFIRMED intraday).

## 14.4 Strength grades

`MPStrength`: `STRONG` (multi-bracket + structural), `MODERATE` (single
condition), `WEAK` (single bracket / tick), `CONTEXT` (almost always true; frames
but is not evidence of change). Assigned by rule, not probability. Modifiers
(`degraded`, `early`/`late`, `basis_agree`, `repeat`) annotate, they don't change
the grade.

## 14.5 Acceptance / rejection state machine (the core mechanism)

Level-agnostic; instantiated per reference level. For bracket *k* and level *L*,
`frac_beyond` = TPO-weighted fraction of bracket *k*'s bins that lie strictly
beyond *L*.

```
ABOVE_FULL     frac_beyond ≥ accept_frac   (default 0.80)
ABOVE_PARTIAL  0 < frac_beyond < accept_frac
SPANNING       bracket low < L < bracket high, neither side ≥ accept_frac
```

States of a break beyond *L* (upside; downside symmetric):

| state | condition | strength |
|---|---|---|
| `PROBE` | ≥1 bracket PARTIAL/SPANNING, 0 FULL | WEAK |
| `BREAK` | exactly 1 bracket ABOVE_FULL | WEAK |
| `DEVELOPING_ACCEPTANCE` | ≥ `accept_brackets` (2) consecutive ABOVE_FULL, no VA edge beyond L | MODERATE |
| `ACCEPTANCE` | + `developing_val` > L (whole developing VA beyond L) | STRONG |
| `SUSTAINED_ACCEPTANCE` | ACCEPTANCE held to close: `final_val` > L and `close` > L | STRONG, close-only |
| `FAILED_ACCEPTANCE` | reached DEVELOPING/ACCEPTANCE, then ≥2 consecutive BELOW_FULL and `developing_poc` ≤ L | STRONG |
| `REJECTION` | PROBE/BREAK then ≤2 brackets → BELOW_FULL with a single-print/excess tail at the probed extreme | MODERATE (→STRONG with an excess tail) |
| `RETURN_INTO_VALUE` | a bracket trades within `[developing_val, developing_vah]` | MODERATE |
| `FAILED_BREAKOUT` | BREAK/PROBE of a prior **range** extreme or IB extreme → RETURN_INTO_VALUE → `developing_poc` on the origin side | STRONG |

`DEVELOPING_VALUE_OUTSIDE_PRIOR_VA` is a distinct fact: `developing_val >
prev_final_vah` (or mirror) — today's whole value area forming outside
yesterday's; the leading indicator of value migration.

## 14.6 MVP event set (slice 1–2)

IDs match the artifact master table (§17). Detection rules: artifact §4–§10.
`basis` variants (VOLUME) and weekly/monthly frames are post-MVP.

| ID | Category | Event | Strength |
|---|---|---|---|
| MP-001 | Opening | Open vs prior value / range (5 zones) | CONTEXT |
| MP-002 | Opening | Open above prior high / below prior low | CONTEXT |
| MP-003 | Opening | Gap magnitude vs prior close (ATR-banded, signed) | CONTEXT |
| MP-010 | Acceptance | Accept above prev VAH | STRONG |
| MP-011 | Acceptance | Accept below prev VAL | STRONG |
| MP-012 | Acceptance | Reject above prev VAH → return to value | MODERATE |
| MP-013 | Acceptance | Reject below prev VAL → return to value | MODERATE |
| MP-014 | Acceptance | Failed acceptance above prev VAH (and mirror MP-014D) | STRONG |
| MP-015 | Acceptance | Developing value entirely outside prior VA | STRONG |
| MP-016 | Acceptance | Accept above prev day HIGH | STRONG |
| MP-017 | Acceptance | Accept below prev day LOW | STRONG |
| MP-018 | Acceptance | Failed breakout of prev high / low | STRONG |
| MP-019 | Acceptance | Accept above IB high | STRONG (intraday-valid) |
| MP-020 | Acceptance | Accept below IB low | STRONG (intraday-valid) |
| MP-021 | Acceptance | Failed IB breakout (either side) | STRONG |
| MP-024 | Acceptance | Accept outside prior day RANGE (rollup of MP-016/017) | STRONG |
| MP-025 | Acceptance | Return inside prior range after breaking it | MODERATE |
| MP-030 | Value | Value migration direction (session) | STRONG (close) / MODERATE (developing) |
| MP-031 | Value | Value overlap topology (5 states) | MODERATE |
| MP-033 | Value | Multi-day value trend (3–5 sessions) | STRONG |
| MP-040 | POC | POC migration vs prior session | STRONG |
| MP-041 | POC | Developing-POC drift (intraday) | MODERATE |
| MP-045 | POC | Naked prior POC above / below (+ FILLED) | MODERATE |
| MP-051 | IB | IB broken up / down / both | WEAK → see MP-019/020 |
| MP-052 | IB | Range-extension size & sidedness | MODERATE (→STRONG one-sided ≥1×IB) |
| MP-053 | IB | Directional after IB (one-timeframing) | MODERATE |
| MP-060 | Breakout | Upside auction outcome (narrative rollup) | inherited |
| MP-061 | Breakout | Downside auction outcome (narrative rollup) | inherited |
| MP-070 | Structure | Excess / poor at each extreme (3-way per extreme) | STRONG (excess) / MODERATE (poor) |
| MP-072 | Structure | Poor high / poor low | MODERATE, close-only |
| MP-075 | Structure | Double / multiple distribution | STRONG (confirmed) / MODERATE (developing) |
| MP-080 | Shape | Day type (provisional + confirmed) | STRONG (confirmed) / MODERATE (provisional) |
| MP-081 | Shape | Profile silhouette | MODERATE |
| MP-100 | Multi-TF | Price vs 5-day composite POC / value | MODERATE |
| MP-110 | Tension | Price–value divergence | MODERATE |

## 14.7 Day-type classification (MVP subset, §10 taxonomy extended)

`MPDayType`: `NORMAL`, `NORMAL_VARIATION`, `TREND_UP`, `TREND_DOWN`,
`DOUBLE_DISTRIBUTION`, `NEUTRAL`, `NEUTRAL_EXTREME`, `RANGE`, `LARGE_RANGE`.
Resolution order (first match wins; all matches also recorded as
`candidate_day_types` with satisfied-condition counts):
`TREND_* → DOUBLE_DISTRIBUTION → NEUTRAL_EXTREME → NEUTRAL → NORMAL_VARIATION →
NORMAL → RANGE`. Objective conditions: artifact §10.1. Emitted provisionally each
bracket close as "conditions accumulating k/m"; `CONFIRMED` at session close only.

`MPSilhouette` (histogram shape, orthogonal axis): `BALANCED_D`, `P_SHAPE`,
`B_SHAPE`, `THIN_I`, `BIMODAL`. Reuses the existing `_classify` primitives.

## 14.8 Look-ahead rules (backtest contract)

1. No rule references `final_*`, `close`, or any `confirmed_close_only` quantity
   of the **current** session while emitting an intraday state.
2. Developing values are stamped with their bracket index; "state as of bracket
   k" is derived only from brackets `0..k`.
3. Trailing statistics (IB-range percentiles, session-range percentiles, ATR,
   composites) never include the in-progress session; `is_atypical` sessions
   excluded by default.
4. The prior-session `Profile` used today is its **final** object, frozen at
   yesterday's close. Prior `INSUFFICIENT_DATA` ⇒ cross-session events
   `degraded` or skipped.
5. Re-running the engine over a historical date produces the identical `events`
   array it would have produced live — a golden replay test enforces this
   (determinism) alongside a prefix test (`detect_events` on facts truncated to
   bracket k == the prefix of the full run's `state_history` up to k).

## 14.9 Build slices

Slices 3+4 were **folded and made lighter** than first planned: no new
`market_profile_events` table (one `ADD COLUMN` on `market_profile_sessions`
instead), no `ALGO_VERSION` bump (the event layer keeps its own
`MP_EVENTS_VERSION`, off the engine-snapshot surface), enums stay module-local.

| Slice | Scope | Status |
|---|---|---|
| **1** | `analytical_core.market_profile.events`: FACTS builder (per-bracket developing snapshots by slicing the M5 series and reusing `build_profile`; structural facts from the final bins), the acceptance state machine, the MVP event set, day-type/silhouette, MP-110 tension, `MP_EVENTS_VERSION = "0.1.0"`, `event_result_to_dict`. Golden + property (determinism, no-look-ahead prefix) + edge tests. Enums module-local (unregistered). | **DONE** |
| **3** (folded) | Migration `0004`: `market_profile_sessions` += `close`, `events` (jsonb), `mp_events_version` (`ADD COLUMN IF NOT EXISTS` — 0001 is a live model snapshot). `AnalysisService._run_market_profile` runs `run_event_engine` after the TPO profile (isolated — a failure stores `{status:"ERROR"}`), stores the compact blob on the TPO row; `MP_EVENTS_VERSION` folded into the MP recompute-guard `params_hash`. `MarketProfileSessionRef` + `get_prior_session` on the MP repo (Sa + Memory). ATR passed as `None` for now (gap-band → `UNKNOWN`, POC-drift skipped). No per-instrument FUT-reads-for-INDEX wiring yet (events run on the in-view instrument's own profile). | **DONE** |
| **4** (folded) | `GET /instruments/{id}/market-profile` response gains an `events` block (`MPEventsBlock`); `MarketProfilePanel` renders an "Auction events" section — day-type/silhouette + a strength-sorted event table + tensions. `docs/03/05/07/08`. | **DONE** |
| 2 / future | Incremental developing-snapshot accumulator (drop the per-bracket rebuild); full event catalogue beyond MVP (MP-014/018/021/024/025/031/033/045/053/060-family completeness, MP-100+ multi-TF); VOLUME-basis variants + MP-111; 5/20-day composite + naked-POC engine; **FUT-as-profile-of-record** cross-instrument wiring (decision 4); real trailing ATR threaded in; `MPEventConfig` under `app_settings.market_profile_events.*`; per-event-row `market_profile_events` table if event history/query is needed; enum registration in `analytical_core.enums` + `docs/12` if events reach a typed column. | future |
