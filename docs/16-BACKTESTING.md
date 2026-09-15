# 16 — Backtesting: opening-range breakout (ORB)

Owner-authorised 2026-09-04 — a **bounded** first backtest, not a general
framework. Decision 23 ("backtesting is future work") is narrowed to permit this
one deterministic study.

Descriptive research over historical bars. It classifies past sessions; it emits
**no signal, no label, no BUY/SELL**, and is not wired into the engine, scoring
or the run model.

---

## 1. The study

For each trading day of an index:

1. **Range window** `[range_start, range_end)` (IST) → `range_high` = max bar
   high, `range_low` = min bar low, `range_size = range_high − range_low`.
2. **Breakout window** `[break_start, break_end]` → the **first bar whose
   close** is ≥ `range_high` (⇒ `LONG`) or ≤ `range_low` (⇒ `SHORT`) —
   **a confirmed close, not a wick** (fixed 2026-09-04: a high/low poke that
   closes back inside the range no longer flips the call — see the shakeout
   note below). If the window's first bar already **opened** beyond a level
   *and* its close confirms it, that is an **immediate breakout** at
   `break_start`; an open beyond the level that closes back inside falls
   through to the normal bar-by-bar scan. One breakout per day. Because
   detection is close-based, a single bar can no longer trigger both sides at
   once, so there is no tie-break rule.
3. **Entry level** = the broken edge (`range_high` for LONG, `range_low` for
   SHORT). **Stop** = the opposite edge.
4. **Measurement** from the breakout minute to `measure_until` (IST, separate
   knob; default `break_end`): for each **target multiple** `k` (default
   `0.5`, `1.0`), did price reach `level ± k·range_size` (in the breakout
   direction) before the stop? Target and stop are checked **intrabar** (a
   high/low touch fills them, same as a resting limit/stop order) — only the
   *entry signal* requires a confirmed close, not the exit. Intrabar tie (a bar
   touches both target and stop) is scored **stop-first** (pessimistic). Also
   `mfe_r` / `mae_r` — the max favourable / adverse excursion from the entry
   level, in range units
   ("R").

**Why close-confirmation (2026-09-04, owner-reported):** wick-only detection
let a brief shakeout — one bar poking through an edge on its high/low and
snapping back inside — lock in the wrong direction for the whole day; the
real, sustained breakout on the other side then hit its target while the
mis-called side got stopped out, reading as a self-contradictory result
("hit target *and* stop"). A confirmed close removes that false flip; target
and stop stay wick-based because those model resting orders, which do fill
intrabar.

Days with no bars in the range or breakout window, or `range_size == 0`, are
recorded with `direction = NONE` and a `note`.

---

## 2. Engine — `analytical_core.backtest.orb` (pure)

`run_orb(days: Sequence[DayBars], config: OrbConfig) -> OrbResult` — pure,
deterministic, stdlib only. `DayBars = (date, weekday, bars)` where each `Bar`
carries `minute` (IST minute-of-day 0–1439) + OHLC; the app layer converts
stored bar-open UTC timestamps to IST minute-of-day.

`OrbConfig`: `range_start`, `range_end`, `break_start`, `break_end`,
`measure_until` (all IST minute-of-day), `target_mults` (tuple, default
`(0.5, 1.0)`). Validation: each window ordered, `range_end ≤ break_end`,
`break_start ≤ measure_until`, all in `[0, 1440)`.

`DayResult`: `date, weekday, range_high, range_low, range_size, direction
(LONG|SHORT|NONE), break_minute, break_immediate, entry_level, stop_level,
stop_hit, stop_minute, mfe_r, mae_r, targets: [{mult, hit, minutes_to_hit,
stopped_first}], note`.

`OrbAggregate` (over `direction != NONE` days): `n_days, n_with_range,
n_breakout, breakout_rate, n_long, n_short, n_immediate, stop_rate,
avg_range_size, avg_mfe_r, avg_mae_r, per_target: [{mult, hits, hit_rate
(÷ n_breakout), avg_minutes_to_hit}], by_weekday: [{weekday, n, n_breakout,
per_target_hit_rate}]`.

`INDEX_ORB_VERSION` (`0.1.0`) rides the payload alongside `algo_version`.

---

## 3. Read path — `app.api.services.orb_backtest`

Loads `ohlcv_bars` for the index (`timeframe` M1 or M15) between
`start`/`end` (IST dates), groups by IST date → `DayBars`, calls `run_orb`.
Computed on read, **not persisted**. M1 over a wide range is a heavy query;
default span is ~1 year, hard cap ~3 years, M15 offered as the fast path.

---

## 4. API — `GET /instruments/{index_id}/backtest/orb`

`docs/07` §4.15. Query: `start`, `end` (ISO date; default `end = today`,
`start = end − 365d`), `range_start`, `range_end`, `break_start`, `break_end`,
`measure_until` (IST `HH:MM`; `measure_until` defaults to `break_end`),
`targets` (comma list of floats, default `0.5,1.0`), `timeframe` (`M1` | `M15`,
default `M1`). Response = `OrbResult` + `index_id`. `404` if the id is not an
`INDEX`; `422` on bad times / an empty date range; `200` with `n_days: 0` when
the range has no stored bars.

---

## 5. Frontend — `/instruments/:id/backtest`

Route + screen (INDEX only, linked from instrument detail). A form: two date
inputs, five `HH:MM` time inputs (range from/to, breakout from/to, measure
until), a target-multiples field, an M1/M15 toggle, **Run**. Then:

- a **summary strip** — days, breakout rate, long/short, per-target hit-rate,
  stop rate, avg minutes-to-target, avg R excursions;
- a **weekday table** — per-target hit-rate by weekday;
- a paged **per-day table** — date · day · range hi/lo/size · dir · break time ·
  immediate? · half hit (min) · full hit (min) · stop (min) · MFE R · MAE R.

Table only; labelled "descriptive backtest — not a signal, not advice".

---

## 6. Not in scope

- Any other pattern; a general strategy/backtest framework; parameter sweeps.
- Costs, slippage, position sizing, compounding, equity curves.
- Persisting results or wiring into scoring / alerts.
- Futures / options (the index M1 history is the dataset).
