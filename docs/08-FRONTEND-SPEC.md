# 08 — Frontend Specification

## 1. Stack

- **React + TypeScript** (`strict: true`), **Vite**, **Tailwind CSS**,
  **TanStack Query** for all server state, **react-router** (proposed).
- API client + types **generated from OpenAPI** (`openapi-typescript` + a thin
  typed fetch wrapper). Enum values come from the generated schema; runtime
  schema-driven UI uses `GET /meta/enums`. Hand-written API types are not
  allowed.
- No component-library dependency assumed in V1 (small hand-built primitives).

## 2. Hard constraints

- **No charts** — one exception (owner, 2026-09-03): a single deliberately rough
  hand-drawn **inline SVG** on the **astro day screen** (`SessionDashaPlot` — the
  H1 hourly open-price line over the Moon-anchored dasha bands, `docs/13` §5.6.1).
  No charting library; every other screen stays numbers-and-tables only, no
  sparklines. `frontend/src/charts/` is still reserved and empty.
- **No execution language** — one bounded exception (owner, 2026-09-03): the
  `StrategyBook` panel on the option-chain and OI-pulse screens renders per-leg
  BUY/SELL for OI-based option structures (`docs/07` §4.13), always under the
  mandatory "not advice / not an order" disclaimer. Nowhere else: score labels
  stay analytical (`STRONG_BEARISH … STRONG_BULLISH`, with the numeric composite
  and confidence), and no screen shows entry/exit/target/stop or places orders.
- **No client-side computation of indicators or scores.** Display only. If a
  value is not in the API, it is not shown.

## 3. Routes

| Route | View |
|---|---|
| `/` → `/dashboard` | Watchlist — sortable table of tracked instruments, composite score + effective label + confidence for the selected timeframe (from `/scores`, i.e. the current projection). |
| `/instruments/:id` | Instrument Detail — per-analysis numeric panels + score breakdown + explanation for a chosen timeframe. For an `INDEX`, also `ConstituentsPanel` (`docs/15`, `/instruments/:id/constituents`): the constituents **ordered by weight** with running cumulative weight, a summary strip (index change %, top-5/10 weight, HHI, and — when per-name quotes resolve — advances/declines, weighted advance-decline, "move carried by top 5"), a sector-weight table, a **Top 10 by weight** strip (all weight columns — the "what carries the index" hint) with a **`+ levels & indicators`** toggle that fires `/constituents/levels` (`docs/07` §4.20, live per-name provider fetch, ~seconds, cached 5 min) and appends per-stock columns — last · P · vs P · R1/S1 · 52w % · RSI d/h · %B · 50/200 (`50›200`/`50‹200`, `●` on a recent cross) · a plain-language read — and the full constituent table `# · symbol · sector · weight % · cum % · chg % · contrib pts · contrib % · rank` with a **frozen header row** (sticky within a `max-h` scroll box) and a **beta / corr** toggle (adds two columns, asks the API for `include_beta`). Weights are seeded reference data. Table only; descriptive — no signal, no BUY/SELL. |
| `/instruments/:id/series` | Per-bar finalized series tables (one row per final bar) for each analysis. |
| `/instruments/:id/runs` | Per-run audit trail (intraday recompute log) for this instrument. |
| `/instruments/:id/option-chain` | Option chain for one expiry (INDEX only): expiry selector + summary (spot, ATM, PCR, max-pain, total CE/PE OI) + a strike ladder (CALLS \| STRIKE \| PUTS) of ΔOI · OI · θ · Δ · IV% · O/H/L · LTP. IV/greeks/PCR/max-pain computed on read (`/instruments/:underlying_id/option-chain`, `docs/07` §4.4). **ATM-centred & auto-adjusting:** the chain re-polls every 30 s in session; a **`±8 / ±12 / ±20 / all`** near-money window keeps `2k+1` strikes centred on the ATM (sliding the band if ATM is near an edge), a **`follow ATM`** toggle re-centres the table on the ATM row whenever spot crosses a strike (scrolls the table box only, not the page), and a **pinned ATM strip** (sticky) shows ATM strike · spot · CE/PE LTP + ΔOI · PCR · max-pain so the money row stays on screen. Sticky table header; ATM row ring-highlighted, ±1 rows tinted. Below the ladder, the **`StrategyBook`** panel (see the OI-pulse row). Table only. |
| `/instruments/:id/daily-digest` | **Daily digest** (`/instruments/:id/daily-digest`, `docs/07` §4.12) — one row per trading day: date · day · O/H/L/C · change % · gap % · range % · PDH · PDL · a range-type chip (inside / PDH break / PDL break / outside, plus `c>PDH` / `c<PDL`) · **c-loc** (close position in the range) · **day type** (classified from the D1 candle for every day; the TPO day-type shown alongside when it differs) · the day's TPO profile (shape / POC / close-vs-value) where one exists. Filter bar (from / to date, sort, page size, **gap % ≥/≤ and close % ≥/≤** — owner-authorised 2026-09-15, e.g. a **"gap-up fade preset"** button sets gap ≥ 0.5 / close ≤ −0.5 in one click for "gapped up then faded to close down" days; a `clear` link when any is set), a summary strip (PDH/PDL break counts + %, inside/outside days, mean range/gap/**close change** %, days-with-TPO-profile) with a D1-day-type distribution and a **`filtered: gap […] · close […]`** badge when the gap/close filter is active, paged — `total` / the summary counts reflect only the matching days. INDEX / FUTURE (options are chain-only). Table only; descriptive, no execution language. |
| `/instruments/:id/oi-pulse` | **OI pulse** — trending open interest for one expiry (INDEX only, `/instruments/:underlying_id/oi-pulse`, `docs/07` §4.11). Panels: **Pulse** (spot, PCR open→now, max-pain open→now + shift, OI support/resistance strike, total & net-session ΔOI per side, a `bias` chip); **strike ladder** (CALLS \| STRIKE \| PUTS of OI · Δsession · Δ15m · buildup, support/resistance rows tinted, `S`/`R` marks); **session trace** (5-min time-series, newest first: spot · calls ΔOI + (Δ) · puts ΔOI + (Δ) · diff ΔOI · diff % · dir-of-change · PCR · COI PCR · VOL PCR · sentiment). `buildup`/`bias`/`sentiment` are positioning labels; table only, no charts. Auto-refreshes each minute. **`StrategyBook`** panel (shared with the option-chain screen, `/instruments/:underlying_id/option-strategies`, `docs/07` §4.13): a disclaimer banner, the classified positioning **view** (Rangebound / Leaning / Trending / Vol-expansion + confidence + evidence + walls/max-pain/PCR/net-ΔOI), then per structure a card — name, family/risk(defined·undefined)/net(credit·debit)/bias chips, a legs table (**BUY/SELL** · ×lots · CE/PE · strike · LTP · OI · ΔOI · role), and approx max-profit / max-loss / breakevens + rationale + caveats. This is the **only** panel in the UI that shows BUY/SELL — owner-authorised, always disclaimed. |
| `/instruments/:id/oi-movers` | **Big OI movers** — options only (INDEX detail link, `/instruments/:underlying_id/oi-movers`, `docs/07` §4.22). A context strip (spot · expiry · PCR · max-pain · support/resistance strike · net CE/PE ΔOI · which side drew the fresh OI) then **two stacked panels — `OI added` and `OI reduced`** — the near-expiry strikes with the biggest session ΔOI increase / decrease. **CE and PE render as separate boxes side by side within each panel** (owner-authorised 2026-09-17 — "CE PE sepearte box", `CePeBoxes`) rather than one mixed table sorted by magnitude — the redundant `type` column dropped in favour of a `Calls (CE)` / `Puts (PE)` box heading, the 🔥 crowded flag moved onto the strike cell. The two Added/Reduced panels stack full-width (not side-by-side) specifically so each CE/PE box gets a full half-page width — the row is wide (8 columns), and quartering it looked cramped in an early pass. Each row: strike + moneyness · OI · **Δ session** · Δ% · **Δ recent** · LTP · **LTP Δ%** (premium change vs today's open, with the last-band change shown small when it diverges) · a **buildup** chip (the *session* read — an `OI added` row is always a *buildup*, a `reduced` row a *unwinding / covering*; colour-coded) with a small **`now:`** tag when the last band's read diverges (the day's build accelerating or reversing). A **`1 / 3 / 5 / 10 / 15 m` recent-band toggle** (`1m` added 2026-09-17, owner: "ONE MORE FILTER 1MIN") sets the Δ-recent window; **moneyness chips** (deep ITM / ITM / ATM / OTM / deep OTM) filter the strikes. Click the `Δ session` / `Δ recent` header to re-rank a list, or a **strike** to jump straight to its trace. A **`Movers` / `LTP trace` tab switcher** (owner-authorised 2026-09-17 — "another tab with time ltp and nifty ltp") sits next to the recent-band toggle; the **`LTP trace`** tab (`docs/07` §4.22) shows a strike/option-type picker (defaults to today's top OI add) and a newest-first table — time (IST) · that strike's own **OI** · **OI Δ (prev)** (change vs. the row right above it, tick to tick — frontend-only, derived from adjacent rows already in the response, added same day, owner — "PREVIOUS ROW - CURRENT ONE COLUMN ADDITONAL NEED") · **OI Δ (session)** (cumulative change vs. the trace's own first tick, ≈ today's session open; server-computed `oi_change` field, added same day, owner — "aDD oi CHANGE ALSO") · that strike's LTP · the underlying's LTP at the same tick (OI column added same day, owner — "Strike LTP trace WITH oi NEEDED"), each price/OI/Δ cell colour-coded vs. the previous row. **`group` bucketing** (added 2026-09-17, owner — "i NEED FILTRATION IN ltp TRACE IF LTP LOW HIGH BAND LIKE IF 5 MIN MULTIPLE PRICE MEANS"): a `1 / 3 / 5 / 10 / 15 m` toggle (same values as the Movers tab's recent-band, `bucketTrace` in `OiMovers.tsx`, frontend-only — the raw 1-min series already has everything needed) groups consecutive 1-min ticks into N-min, session-open-anchored windows; each window's time column becomes a range (`15:35–15:39`) and its LTP columns become a **low–high band** (`99.00–104.70`) whenever that window actually saw more than one price, a plain single value when it didn't — OI / OI Δ columns read the window's *last* tick (a running value, not something to band). The up/down colour on a grouped row compares each window's **last** tick to the previous window's last tick (not high-to-high), so colouring stays meaningful once ranges are involved. **Price-difference columns** (added 2026-09-17, owner — "CAN U ADD PRICE DIFFERNCE IN ltp TRACE"): **LTP Δ** and **`<underlying>` Δ** sit right after their respective LTP columns — the plain signed price change (row's own close vs. the previous row's close, `sPrice`) next to each low–high band, so the reader isn't left inferring the delta from the band and the colour alone. A third **`OI ladder`** tab (`docs/07` §4.22, owner: "one more display option in LTP Trace [/] oi movers", confirmed via follow-up as a CE/PE-mirrored ladder) shows a classic **Calls (CE) OI Δ | strike | Puts (PE) OI Δ** table across `marks` recent time columns (`step`/`columns` controls, default **6 columns 3 min apart** — widened from the initial 3×1m same day, owner: "default 3 min and 6 columns and add another strike above and below") — calls read left→right (oldest → newest, toward the strike column), puts right→left (mirrored, newest closest to the strike column), each cell the OI **change since the column beside it** (not a running total), ATM row highlighted, strikes windowed to **±10** of ATM by default (widened 6→7→10 across two same-day requests). **Per-column max-|Δ| elevation** (added same day, owner — "each maximum no oI change back ground color elevate"): the single biggest `|OI Δ|` on each side in each time column gets an elevated background (on top of the usual green/rose text) so the standout mover per column reads at a glance; a `0` delta is never elevated. **Hover-for-price, per cell** (added same day, owner — "mouse hover can we show price" then "tool tip is a good idea if possible add option price also and tool tip not working showing symbol '?'"): the first pass used a native `title` on the header (`cursor-help`), which the owner reported showed only the `?` help-cursor icon with no visible tooltip text; replaced with a real always-rendering CSS tooltip on every OI-Δ cell — hovering shows that strike/side's own OI (+ change), its own **LTP** (server-added same day), and the underlying's LTP, all at that exact time mark. Anchored to the cell's own edge (not centred) and flipped to open upward only for the table's last row, both to avoid the tooltip clipping against the table's horizontal-scroll container edges. Auto-refreshes ~45 s in session. Positioning labels only — table only, no BUY/SELL. |
| `/instruments/:id/premium-decay` | **Premium decay** — options only (INDEX detail link, `/instruments/:underlying_id/premium-decay`, `docs/07` §4.23). A context strip (spot · expiry (+selector) · days-to-expiry · a **fast decay zone** badge when `dte ≤ 5` · ATM call/put/straddle θ per lot · session elapsed) then a single **CALLS \| STRIKE \| PUTS** ladder (mirrored columns, ATM row highlighted): **LTP** (+ IV%) · **θ/lot** (₹/day for one lot, + %/day of premium) · **expected → actual** (the theta-implied move since today's open vs. what the premium actually did) · a **state** chip — `as expected` / `decaying faster` / `offset by move` / `—`. Auto-refreshes ~45 s in session. Descriptive decay-vs-move read only — table only, no BUY/SELL. |
| `/instruments/:id/backtest` | **Opening-range breakout backtest** (INDEX only, `/instruments/:id/backtest/orb`, `docs/07` §4.15). A parameter form — from/to date, five IST `HH:MM` fields (range from/to, breakout from/to, measure-until), target multiples, an M1/M15 toggle, **Run** — then a result strip (days, breakout rate, long/short, per-target hit-rate + avg minutes, stop rate, avg range / MFE / MAE in R), a weekday hit-rate table, and a per-day table (date · day · range · size · dir[+imm] · break time · per-target minutes-to-hit / "stop" · stop time · MFE · MAE). Table only; labelled "descriptive backtest — not a signal, not advice". |
| `/instruments` | Instrument Manager — browse all; toggle `is_tracked`; set `profile_bin_size`. |
| `/runs` | Runs — cycles with phase status; trigger a manual run. |
| `/runs/:id` | Run Detail — `phase_status[]`, per-instrument outcome grid, `config_snapshot`. |
| `/config` | Configuration — schema-driven form. |
| `/calendar` | Trading days / session status. |
| `/astro` | Astro × market (`docs/13` §5). Four views via a segmented control. **Patterns** — descriptive cross-tabs of daily index return by weekday / Moon nakshatra / lagna / tithi vs a pooled baseline (`/astro/study`); diverging mean-return bars, sortable; every bucket name is a link into the Day log. **Day log** — the individual days (`/astro/days`): a filter bar (**from / to date**, weekday, month, tithi, paksha, Moon nakshatra, Moon rashi, lagna) whose selections combine, a `summary` strip for the filtered set, and a paged (25/50/100/200) sortable table of date · day · tithi · paksha · nakshatra · Moon · lagna · **dasha @open** (Moon-anchored mahadasha–antardasha lord at session open, balance in the tooltip) · chg % · range %, default sorted by chg % descending. Every date links to the day screen. **Almanac** — every computed day, today onward by default (`/astro/almanac`, left-joined so **future / untraded days appear**): from / to date, a paged table of date · day · tithi · paksha · nakshatra · Moon · lagna · Sun · chg % (or "no candle"). Each date opens the day screen, which shows the full panchang + planets + Shadbala even with no market data. **Dasha** — the Vimshottari 9×9 mahadasha × antardasha grid (`/astro/dasha`): a session-length input (default 390 min, quick 390/400/375 buttons) and a start-lord selector; a scrollable table of MD rows × AD columns where each cell shows the scaled `H:MM:SS` over its year value, the diagonal (period lord's own sub-period) tinted, with a period-total column and a 120-year total row. Pure arithmetic — no chart, no underlying. Table only; labelled "descriptive, not predictive"; no forecast, no execution language. |
| `/astro/day/:date` | One trading day on one screen (`/astro/days/{d}`, `?underlying=`). Panels: **Market — daily candle** (O/H/L/C, prev close, change %, range %, volume); **Market — intraday** (a **1 hour / 15 min** timeframe dropdown; session bars O/H/L/C + per-bar %, preceded by `SessionDashaPlot` — a rough inline-SVG **open-price line** of the same bars over the Moon-anchored mahadasha bands, antardasha + pratyantar lanes, each mahadasha tagged `H<by-degree>/<whole-sign>` (that lord's house from the lagna) + its approx % move, and a bottom **planet-places lane** (09:00 IST sky as a 0–360° zodiac strip with each graha + the Lagna at its longitude, retrograde flagged, and the running mahadasha lord picked out in amber with a dashed link to the Lagna showing its house count); the one chart in V1, `docs/13` §5.6.1); **Panchang** (weekday + lord, tithi + paksha, Moon rashi/nakshatra/pada, lagna, Sun, sunrise/sunset, ayanamsha); **Dasha — Moon-anchored** (`docs/13` §5.6.1; fetches `/astro/dasha/moon`): an **open-time picker (09:00 / 09:15)** and a **session-length picker (390 / 400 min)** that refetch, then a headline (Moon nakshatra/pada, ruling mahadasha, **that lord's house from the lagna — by exact degree and whole-sign**, % of nakshatra elapsed, balance at open in H:MM:SS + years) and a period table — clock IST · period · **lagna °/w** (each period lord's house from the ascendant, by degree then whole-sign) · duration · = years · **% chg** (owner-authorised 2026-09-16 — "the table its self showing the % changes": the index's open→close move over that period's own window, from the day's M5 bars re-based to this panel's own selected session-open, `▲`/`▼` signed, blank when no bar falls inside a short period) — with an MD / +AD / +PD depth toggle and the balance period tagged; the pickers shift only the wall-clock labels, not the sky or any duration; labelled "not the 120-year cycle"; **Planets** (sidereal positions — rashi, °, nakshatra + pada + lord, retro, dignity, speed); **Shadbala** (rank, total rupa, ×required, the six balas, ishta/kashta). Empty panels degrade to a note. Descriptive only. |

Global header: market open/closed (`/calendar/status`), `worker_running`
indicator, `last_successful_cycle_age`, `calendar_seeded_until` warning when
< 30 days, active `algo_version`/`scoring_version`, a `stale_results` badge
linking to `/runs` when `/meta/versions.stale_results` is true, and the global
**timeframe selector** (persisted in URL + localStorage).

**Polling is session-gated.** The dashboard board / health and the header status
refetch on their intervals only while the NSE session is live — server
`/calendar/status.is_open` **and** the IST clock (09:15–15:40, weekdays;
`src/lib/marketClock.ts`) both agree. Off-hours those stop after one fetch; a
5-minute `/calendar/status` heartbeat stays on to resume at the next open. The
OI-pulse page refetches on the same 15:40 cutoff (matching its fixed trace).

**Share mode** (`VITE_SHARE_MODE=1` at dev/build time; off by default). Wraps the
app in a passcode gate (`src/features/auth/ShareGate.tsx`) — only the SHA-256 of
the passcode is in the bundle (`src/lib/sha256.ts` + `src/lib/share.ts`), a match
sets a `sessionStorage` flag. Once unlocked, **only `/dashboard` is routable**
(every other path redirects there) and the header nav collapses to *Dashboard* +
a *lock* button. For handing a read-only dashboard to someone on the LAN; not an
auth boundary (a client gate is defeatable — the API itself stays open, decision
7). Change the passcode by replacing `PASS_HASH` with a new `sha256hex(...)`.

## 4. Key screens

### 4.1 Dashboard — Market board
- **Data-first landing view.** Data: `GET /board` — one row per tracked
  **INDEX / FUTURE** (options are not here; they're reached via the chain).
- Columns: Instrument (`contract_key`, links to detail), **Last** (newest M1
  price), **Chg** (% vs prev daily close, green/red + arrow), **Range** (today's
  high−low %), **OI** (futures), **History** (span of stored D1 bars `→last`,
  green/amber dot from `history_ok`; hover shows the full D1 + M1 spans and D1
  bar count), **5m** / **H1** / **D1** label chips (from `current_signal_scores`,
  analytical only, secondary — `5m` is the fastest read and moves through the
  session), **Updated** (relative; amber when stale *and* the market is open).
- **Health strip** above the table: instrument count, market open/closed, `N
  stale` (last bar older than ~3 cycles, only while open), `N behind on D1`
  (`history_ok == false`).
- `history_ok` heuristic: D1's last bar is within 4 days of today (covers a
  weekend). `d1_from/through`, `d1_bars`, `m1_from/through` come from `/board`.
- Per-row links: `chain` (INDEX only), `series`.
- Poll interval = `cycle_interval_seconds` from `/config`. Header shows last
  successful cycle age + cycle #, a `streaming` badge when `stream_enabled`, a
  `worker idle` badge, and a red banner when `provider_auth != OK` (token needs
  `analytical-provider login`).
- States: skeleton / empty ("no tracked INDEX or FUTURE") / `<ProblemError>`.
- The per-timeframe scored **watchlist** (`GET /scores`) is a secondary view;
  it stays reachable but is not the landing page while analysis is being reworked.

### 4.2 Instrument Detail
- Data: `GET /instruments/:id`, `GET /instruments/:id/analyses?timeframe=<tf>`,
  `GET /instruments/:id/score?timeframe=<tf>`,
  `GET /instruments/:id/market-profile` (when a SESSION profile exists).
- Header: instrument meta + capabilities (`has_volume`, `has_intraday_oi`,
  applicable analyses). A **frozen top bar** (`position: sticky`, full-width
  over the content) stays pinned while the long panel stack scrolls — it carries
  `contract_key` · **latest price** (+ today's % vs the last daily close, from
  the shared `/pivots` `last_price`) · type · the **timeframe `<select>`**
  (same `useTimeframe` URL/localStorage state as the global header, so it can be
  changed from anywhere on the page) · the effective-label chip · composite
  score. The badges + cross-links sit in a normal (non-sticky) row just under it.
- **Score summary card:** composite, effective label (+ "clamped from
  `raw_label`" note when `low_confidence`), confidence, `warnings[]` list, and
  the `explanation` text block.
- **Score breakdown table:** analysis_key · raw values · sub-score · confidence ·
  weight · contribution · reason. Contributions visibly sum to the composite.
- **Analysis panels**, each showing `status`, `as_of_ts`, `scope`,
  `coverage_ratio`, and a `carried` badge when the result was carried:
  - RSI: rsi, state, slope, divergence.
  - Bollinger: basis/upper/lower, %B, bandwidth, bandwidth percentile, squeeze,
    position.
  - 7 EMA: ema, price vs ema, above/below, slope state, atr14.
  - Golden Cross (50 / 200 SMA, D1 default): fast, slow, **regime** (50 above /
    below 200, tinted emerald / rose), **cross type** (golden / death / none,
    tinted), bars since cross, separation, `recent`, `provisional` badge. **The
    alert:** when `recent` is true and a cross is present the panel takes an
    emerald (GOLDEN) / rose (DEATH) accent border + ring and a "Golden cross —
    50 crossed above 200, N bars ago" (or death-cross) call-out. Collapsed
    `NOT_APPLICABLE` for FUTURE/OPTION.
  - Volume: volume, vol MA, RVOL, spike, up/down ratio, trend — or collapsed
    `NOT_APPLICABLE` ("no volume").
  - Open Interest (FUTURE/OPTION): oi, Δoi, %Δoi, price Δ, price/oi direction,
    behavior; option panels show the "positioning in this contract, not the
    underlying" note.
  - Market Profile (SESSION): POC, VAH, VAL, IB high/low, session hi/lo, range,
    close vs POC/VAH/VAL, in-value-area, shape, `is_session_complete`. **One
    merged price-row table** (owner-authorised 2026-09-17 — "VOLUME & tpo TWO
    COLUMN MERGE IT ONE WITH SMALL BAR", replacing the earlier TPO/VOLUME tab
    switcher): price | IB | one column per period letter | TPO count | a small
    horizontal **Volume bar** (CSS `<div>` width against the session's busiest
    price — no chart library, no SVG, still table-only per decision 11), one
    row per price across the union of both profiles' bins (joined on
    `price_low` — the two normally share the same grid; a borrowed-FUTURE
    volume profile, below, can differ by a bin or two). Volume column omitted
    entirely when `profiles.VOLUME` is absent (rare — see the borrow note
    below). **Not a chart**.
    **TPO letter grid** (owner-authorised 2026-09-15 — "print pattern like
    abcdefg… dont remove text" → "classic column layout"): each period that
    printed this session (A, B, C…, derived from the bins already on hand, no
    extra field) gets its own narrow column; a letter shows in the row it
    traded at, blank otherwise — the busiest (POC) row amber-highlighted. This
    is the original hand-plotted TPO chart, rendered as monospace text —
    horizontally scrollable, still table-only, still no chart library or SVG.
    **Initial Balance column** (owner-authorised 2026-09-15, "IB TPO need
    like need" then revised same day — "Price TPO need to column wise IB
    then A B C D E F like need basic market profile" — then reordered
    2026-09-16, "IB second column A Third colum B like profile structure?",
    moving **TPO count to the last column** so the period letters sit right
    after IB): the TPO table is column-wise **Price | IB | A | B | C … | TPO
    count**, matching the classic market-profile layout. The dedicated **IB**
    column is sky-tinted with a left bar on every price row whose
    `[price_low, price_low+bin_size)` band overlaps `[ib_low, ib_high]` (a
    value-based overlap test — `ib_periods` isn't exposed by the API, so this
    reads against the IB price range already shown in the stat grid, not
    specific period letters); the top/bottom such row reads **`hi`** / **`lo`**
    (or **`IB`** when the range is one bin), interior rows a **`│`** mark.
    Frontend-only — no new API field.
    **Session date navigator** (owner-authorised 2026-09-15 — "like this last 3
    day value or 7 days"): a ◀ / date-input / ▶ control in the panel header
    (max = today) pages back through past sessions — `GET .../market-profile`
    already took a `session_date` query param (unused by the frontend until
    now); `MarketProfilePanel` now owns its own `useMarketProfile(instrumentId,
    selectedDate)` query alongside the parent's "latest" one, a `latest` reset
    link, and a friendly "no session that date" read for weekends/holidays
    (never a raw error). **Known gap:** the `letters` field is only populated
    for the session a cycle actually computes (today's forming/closed session);
    already-closed historical days keep their `tpo_count` numbers but show no
    letter columns until/unless that day's profile is recomputed — there is no
    backfill job for it yet.
    **Volume borrowed from the linked FUTURE on an INDEX** (owner-authorised
    2026-09-17 — "FOR MARKET PROFILE ADD WITH FUTURE VOLUME"): an index has no
    genuine traded volume, so its own Volume Profile was previously just
    absent (no volume bars at all) — `GET .../market-profile` now borrows the
    nearest linked future contract's own already-persisted Volume Profile for
    the same session when the index has none of its own (`docs/07` §4.4,
    `docs/05` §10.6). When the merged table's Volume bars are borrowed, an
    amber **`Volume from <FUTURE-contract-key>`** badge sits above the table
    (hover for the full disclosure — a disclosed approximation, not the
    index's own data); absent when `VOLUME` is the instrument's own (e.g. on
    a FUTURE/OPTION screen, which already have real volume and never needed
    this).
    Below the tables, an **"Auction events"**
    section (`docs/14`) when `events` is present: a day-type + silhouette badge
    line, then a compact table of `MP-nnn` events sorted by strength — id +
    strength chip, state chip (+ `@bracket`), and a plain-language "Read (not a
    signal)" one-liner; conflicting-evidence tensions listed below. Labelled
    "descriptive, not trade signals".
  - Order Block (INDEX/FUTURE PER_TIMEFRAME, `docs/05` §9a): bias, zone state,
    price, ATR, active block counts, nearest demand/supply zone, and a table of
    recent zones (side · zone · age · dist % · state). Descriptive — no
    entry/target/stop.
  - Candles (INDEX/FUTURE PER_TIMEFRAME, `docs/05` §9b): bias, last pattern
    (name · bias · strength), when (on the last bar / N bars ago), the window
    tally (`n_bullish` · `n_bearish` · bars scanned), and a table of recent hits
    (pattern · bias · strength · bars ago · close). **The "alert":** when
    `on_last_bar` is true the whole panel takes an emerald / rose accent border
    + ring and shows a one-line "<Pattern> on the just-closed bar" call-out.
    Descriptive labels only — no entry/target/stop.
- **Candlestick patterns — multi-timeframe grid** (`CandlesGridPanel`, below the
  per-analysis grid; INDEX + FUTURE only, `docs/07` §4.17): a 4-column table
  **5m / 15m / 30m / 1h**, rows = the last 5 pattern hits per timeframe (newest
  first: name · bias colour · strength · bars-ago · trend context · the bar's
  own clock time, IST `HH:MM` from `bar_ts`). Each column header shows that
  timeframe's most recent pattern (+ its `HH:MM`) and is tinted emerald / rose
  when it sits on the just-closed bar (`on_last_bar`). **Reversal-pattern alert**
  (owner-authorised 2026-09-15 — "recheck if reversal pattern need alert"): a
  column also tints when a **`STRONG`**-strength reversal-type pattern
  (`BULLISH_/BEARISH_ENGULFING`, `BULLISH_/BEARISH_HARAMI`, the hammer / star
  family, `PIERCING_LINE`/`DARK_CLOUD_COVER`, `MORNING_/EVENING_STAR` — not the
  doji family or `MARUBOZU`) shows up **anywhere in the scanned window**, not
  only the just-closed bar; the header gets an extra `● Pattern (strong, Nb
  ago · HH:MM)` line when that hit isn't already the one shown for
  `on_last_bar`, and the matching row in the table is amber-marked.
  **Timeline values** (owner-authorised 2026-09-15 — "near by pattern give
  the time line value"): every bars-ago reference in the panel (header line,
  reversal-alert line, table rows) is followed by that bar's own IST clock
  time, so a hit found "2b ago" can be matched straight against an external
  chart. Purely a frontend read of the existing `patterns[].bar_ts` field — no
  API/schema change. 30m is folded on read from 5m (footnote says so). Read
  view — not scored; descriptive, no BUY/SELL.
- **Golden Cross — 5m / 15m / 1h / 1D** (`GoldenCrossGridPanel`, below the
  candles grid; non-OPTION, `docs/07` §4.19): a table (regime · last price ·
  fast 50 (+ distance %) · slow 200 (+ distance %) · separation · last cross ·
  bars since · cross date), each column header showing `50 › 200` / `50 ‹ 200`
  tinted emerald / rose and a `● golden Nb` / `● death Nb` badge when the
  cross is recent; the whole column header tints when so. **MA proximity
  alert** (owner-authorised 2026-09-15): reads the 50/200 MAs as dynamic
  support (price above) / resistance (below) — a column not already tinted by
  a recent cross takes an **amber** tint + a `● near {50/200} (support|
  resistance)` line under the regime when the last price sits within
  `near_ma_pct` (default 0.3%) of a MA; the Fast/Slow distance cells
  themselves turn amber-bold when that specific MA is the near one. **EMA row**
  (owner-authorised 2026-09-16 — "DMA 50 200 like need EMA one box"): one extra
  row, **EMA (50/200)**, showing the same two periods as an exponential
  average — `fast_ema / slow_ema` — alongside the DMA (SMA) rows; a reference
  read only, it doesn't drive the regime/cross/near-MA tints, which stay tied
  to the configured `ma_type` (default SMA). Dated
  contracts render a single "runs on the INDEX series" note. Read view — not
  scored.
- **ICT Fair Value Gaps — 5m / 15m / 30m / 1h** (`FvgGridPanel`, below the
  golden-cross grid; non-OPTION, `docs/07` §4.21): a 4-column table with a
  **nearest above** / **nearest below** / **last** row — each gap cell shows the
  zone (`bottom–top`), CE, `state` chip (primed / tested / respected /
  breached), signed distance %, and `hit CE` / `wick-only` flags, coloured by
  its **inversion polarity** (rose = bearish array overhead, green = bullish
  array below). The column header shows the `bias` lean + active-gap count and
  tints when price sits inside a gap. 30m folded from 5m. Read view — not scored,
  no BUY/SELL.
- **Candle Range Theory — 5m / 15m / 30m / 1h** (`CrtGridPanel`, below the
  FVG grid; non-OPTION, owner-authorised 2026-09-16, `docs/07` §4.24): a
  4-column table — **reference range** (`low–high`, midpoint, range, an
  `inside (mother)` tag when the reference candle was a compression candle),
  **current position** (above high / below low / at midpoint / inside, +
  last close), **breakout** (▲/▼ high/low break, `close outside` /
  `closed back inside` / `retested` / `holds` / `vol-confirmed` flags), and
  **expansion** (points + ×range multiple). The column header tints and
  labels the plain-language `signal` (bullish/bearish continuation, high/low
  rejection, range expansion ↑/↓, compression, neutral). 30m folded from 5m.
  Read view — not scored, no BUY/SELL; explicitly not "green candle =
  bullish" — the range boundaries and what happens *after* a break are what's
  shown.
- **Gann time cycles** (`GannCyclesPanel`, below the CRT panel; non-OPTION,
  owner-authorised 2026-09-16 — "Gann Days / Gann Time Cycles can we
  implement in our logic?", clarified as "previous low day and high [day],
  then low high based on period with gann ideas", `docs/07` §4.25): a
  **previous swing low** / **previous swing high** card pair (price + date,
  green/rose), a **confluence clusters** section (amber cards when upcoming
  — cluster date, days-from-today, contributing cycle count and labels) shown
  only when 2+ projections converge, and an **all projections** table (date ·
  cycle e.g. `low + 90d` · anchor date/price · **actual** · days ago/in).
  **Actual column** (owner-flagged 2026-09-16 — "past data need fill the
  value"): once a projected date has passed, shows that day's real close +
  high–low range (a dash while it's still upcoming) — a `· as of {date}`
  note when the exact date fell on a weekend/holiday and resolved to the
  next session — so a past Gann date can be checked against what price
  actually did there. Classic Gann
  day-count cycles (45/90/120/144/180/270/360 calendar days), not a fixed
  timeframe grid — one read per instrument off ~1y of daily bars. Read view —
  not scored, no BUY/SELL; a calendar-date study, not a signal — no entry, no
  target, no stop.
- **Gap-fade streak study** (`GapFadeStudyPanel`, below the Gann cycles
  panel; non-OPTION, owner-authorised 2026-09-16 — "i need to find gapup day
  and close much lower like days continuos down howmany days when its
  streak end shortterm consolidation and breakout need find" — explicitly
  "its not backe test i need to analysis", `docs/07` §4.26): **not a
  backtest** — a historical study over the full D1 series. **Both reversal
  directions side by side** (owner-extended 2026-09-17 — "like open low
  close/open high close actually it represent the reversal"): a
  **`Gap-up fade — bearish reversal`** box and a **`Gap-down fade — bullish
  reversal`** box, each with its own 4-stat summary strip (occurrences,
  median streak, median consolidation, breakout split `N↑/N↓ (X% up)`), a
  **streak length — how often** histogram (chips, `Nd × count`), and an
  **every occurrence** table (event date · gap%/close% · streak days · box
  range · days in box · outcome, colour-coded broke-up/broke-down/still-
  consolidating/too-recent, breakout date shown inline) — filtered to that
  direction. Header carries one **± magnitude pair** of threshold inputs
  (`gap ≥ __%` / `close ≥ __%, either way`) applied symmetrically to both
  directions, rather than four separate inputs. Owner picked the
  **simple box** consolidation method (a fixed high/low band from the days
  right after the streak ends) over an ATR-squeeze alternative, and
  **close-breaks-the-box-by-a-buffer** for the breakout trigger over a bare
  box-touch — both apply the same way regardless of which direction
  triggered the occurrence. Read view — not scored; descriptive only, no
  entry, no target, no stop, no hit-rate against a simulated trade.
- **Economic event calendar** (`EventCalendarPanel`, below the Gap-fade
  panel; non-OPTION, owner-authorised 2026-09-16 — "news driven i need
  basic news like fed powell and Auto sale and indian Gst... predefined
  news... calander based on the calander view... previous close - today
  close", clarified across follow-ups to **not live news** (recurring-date
  rules only) and confirmed the price read is against the NSE instrument on
  screen, not gold/silver/bonds, `docs/07` §4.27): an actual **month-grid
  calendar** (Mon-Sun columns, prev/next/today navigation) — the one other
  grid-shaped, non-tabular read view in the app besides the Market Profile
  TPO letter grid, still not a chart. An **11-card** summary strip (one per
  event type: occurrences with data, median move, notable-move % + up/down
  split, or "no historical data available" for `FNO_EXPIRY`). Each calendar
  day carries a small colour-coded badge per event on it (**Jobs** sky,
  **Claims** cyan, **GST** violet, **Fed** rose, **ECB** indigo, **RBI**
  fuchsia, **F&O Exp** amber, **MCX Gold** yellow, **MCX Silver** slate,
  **COMEX Gold** orange, **COMEX Silver** stone) with the day's `change_pct` inline once resolved,
  a dash while still upcoming; today's cell is tinted. Event types: **US
  jobs report** (1st Friday/month), **US jobless claims** (owner-authorised
  2026-09-17 — cross-checked against investing.com's own economic calendar
  as a genuine high-impact weekly release; every Thursday, no approximation
  needed), **India GST collection** (~1st/month, from 2017-07-01),
  **MCX gold/silver expiry** (5th-of-month rule, approximated against NSE
  trading days — no MCX holiday calendar, but MCX/NSE share Indian
  holidays), and **COMEX gold/silver expiry** (owner-authorised 2026-09-17
  — "US gold expiry?"; a cruder 27th-of-month rule-of-thumb, since COMEX
  and NSE share no holiday calendar at all — disclosed and accepted before
  building) are fully backfilled across all available history.
  **Fed/ECB/RBI rate decisions** (owner-authorised 2026-09-16/17 — "fed rate
  decision not coming" / following the owner's investing.com reference /
  RBI flagged 🔴 very high priority in the owner's events-priority list) are
  small hand-maintained seed lists — 2023-2025 from training knowledge at
  moderate confidence (Fed additionally has owner-confirmed 2026 entries,
  e.g. 2026-09-16 after the owner reported "Fed rate decision yesterday but
  its not showing"; RBI is bi-monthly, 6/year vs. Fed/ECB's 8) — never
  guessed for 2026+ on any of the three lists, disclosed in the panel's own
  intro paragraph, since these are committee-set dates and no formula can
  generate them. **Monthly F&O expiry** shows on the calendar
  (current + next contract, exact dates) but carries no historical stats —
  the instruments table doesn't retain expired contracts and NSE's expiry
  weekday has changed over the years, disclosed the same way rather than
  silently shown as a thin/misleading sample. Read view — not scored;
  anticipatory context from real history, no entry, no target, no stop.
- **CPR & pivots** (`PivotsPanel`, below Key levels; **all instrument types**,
  `docs/07` §4.18): three columns **Daily / Weekly / Monthly**, each with a
  **Now** and a **Next** R3→S3 level ladder (price · signed distance vs last
  price · AT/NEAR tint) with the **CPR band rows** (TC / P / BC) shaded, a
  `NARROW/AVERAGE/WIDE` CPR-width chip and a `higher/lower/overlapping value vs
  prev` note. **Next** is the upcoming period's levels ("tomorrow" for daily,
  next week / month otherwise) with a `provisional` badge while the source
  period is still open and the resolved next-session date in its label. Plus the
  source period's H/L/C and a collapsible **history** table (P · TC/BC · CPR % ·
  R1/S1 · vs-prev, ~3 months). A **"Daily history: on <month> <day> · <N> yr"**
  control switches the daily history to a *same-calendar-date* table — one row
  per year (year · session · P · R1/S1 · close · ret % · close-vs-pivot ·
  R1·S1-hit), i.e. "what has 1 September done, 20 years back". A "next level up /
  down" strip picks the nearest current level across all three timeframes. Read view — computed on read from
  D1 bars, not scored; descriptive, no BUY/SELL, no target/stop.
- `INSUFFICIENT_DATA` panels show `coverage_ratio` / periods-elapsed and the
  reason.

### 4.3 Configuration
- Rendered from `GET /config/schema`.
- Sections: **Cadence**; **Market Profile** (`tpo_minutes`, `ib_periods`,
  `value_area_pct`, `partial_period_policy`, `va_expansion`, bin-size rules,
  shape thresholds; the NSE session assumption shown read-only with a note);
  **Scoring** (weights table, label bands, `min_confidence`,
  `per_analysis_params`); **Universe selection** (`max_expiries`,
  `strike_window`, `strike_step` per underlying, `rebuild_trigger`,
  `futures_rollover`); **Retention** (read-only display).
- `PATCH /config` → shows `effective_from` and the new `config_params_hash`.
- 422 `errors` mapped to fields.

### 4.4 Runs
- `GET /runs` table: `cycle_seq`, trigger, status (`SUCCEEDED/PARTIAL/FAILED`),
  timings, phase counts.
- "Trigger run" → modal (phases subset, scope). `POST /runs`; on `409` show
  "a cycle is already running" with the `Retry-After`.
- Run Detail: phase-status cards; per-instrument outcome grid; `config_snapshot`
  viewer.

### 4.5 Instrument Manager — browse / track / add / delete
- List with `q` + `instrument_type` + `is_tracked` filters; per-row
  **track / untrack** (`PATCH`).
- **Add** (collapsible form): `type` → `provider_symbol` (Upstox key) → `symbol`;
  for a derivative also `underlying` (dropdown of existing INDEX rows) + `expiry`
  + `kind`, and `strike` + `CE/PE` for an option. Quick-fill buttons for the
  known indices. `POST /instruments`.
- **`provider_symbol` autosuggest:** the field is a debounced combobox
  (200 ms) backed by `GET /instruments/catalog?q=`. The dropdown lists matching
  master rows (key · name · type · expiry · `CE/PE`, plus an "in DB" tag);
  picking one fills `provider_symbol` and every field it can derive
  (`instrument_type`, `segment`, `symbol`, `display_name`, `exchange`,
  `underlying_symbol`, `underlying_contract_key` when the underlying is an
  existing INDEX row, `expiry_date`, `expiry_kind`, `strike_price`,
  `option_type`). When the catalog reports `available: false` the field stays a
  plain text input.
- **Delete** per row → `window.confirm` (names the contract, warns it's
  irreversible) → `DELETE /instruments/{id}`. On `409` (it's an underlying) a
  second confirm offers `?force=true`.

## 5. Cross-cutting conventions

- **Number formatting:** fixed decimals per field type (prices 2, RSI 1, ratios
  2, scores 1); `en-IN` grouping; nulls render as "—".
- **Labels:** always text + icon (never colour alone); effective label is the
  primary; raw label shown only in the "clamped" note.
- **Loading / empty / error:** skeletons for tables, inline spinners for panels,
  explicit empty states with the next action, shared `<ProblemError>` for RFC
  7807.
- **Staleness:** `as_of_ts` + "updated Xs ago" everywhere. Every screen renders a
  shared **`<LastUpdated>`** (`components/LastUpdated.tsx`) beside its `<h1>`,
  wired to that screen's primary TanStack Query result(s): a live-ticking
  "updated Xs ago" from the oldest `dataUpdatedAt` on screen, a manual **↻**
  refresh, "refreshing…" while a fetch is in flight, and — where the payload
  carries its own stamp (`as_of` on OI pulse / OI movers) — a `· data HH:MM IST`
  suffix. The global `Header` keeps its separate worker-cycle age badge
  (`last_successful_cycle` — backend freshness, distinct from browser fetch age).

## 6. Project structure (planned)

```
frontend/src/
  api/  generated/        # openapi-typescript output (do not edit)
        client.ts         # typed fetch wrapper, base URL, auth header
        queries/          # TanStack Query hooks per resource
  components/ primitives/ layout/
  features/ dashboard/ instrument-detail/ series/ runs/ config/ calendar/ instruments/
  routes/
  lib/ format.ts timeframe.ts scoreBands.ts scope.ts
  charts/  # RESERVED — empty in V1
  main.tsx app.tsx
frontend/tests/  # Vitest + RTL + MSW
```

## 7. Build / run

- Dev: Vite dev server, proxy `/api` → `backend`.
- Prod (Compose): `vite build` → nginx in the `frontend` image.
- Env: `VITE_API_BASE_URL`, optional `VITE_LOCAL_API_TOKEN`.

## 8. Reserved for later (no work in V1)

Charts module; alerts UI; auth/login screens; multi-timeframe consensus view;
mobile-specific layouts (components stay responsive, no separate app).
