"""Engine version constants (docs/05 §12, docs/06 §8).

``ALGO_VERSION`` is bumped on any change to an indicator / Market Profile
formula, default parameter, rounding, tie-break, or approximation (a CI guard
asserts the engine-output snapshot was regenerated — docs/09 §2.1).
``SCORING_VERSION`` tracks the scoring engine (``weighted_v1``) the same way.

Every ``analysis_results`` / ``signal_scores`` row records the value in force at
write time.
"""

from __future__ import annotations

#: Phase 3 — the six deterministic indicators (RSI, Bollinger, EMA+ATR, Golden
#: Cross, Volume, Open Interest) per docs/05 §4–§9.
#: 3.1.0 — Market Profile (docs/05 §10: TPO + Volume profile, POC, value area,
#:         IB, shape classifier) joined the deterministic engine surface.
#: 3.2.0 — Option pricing (docs/05 §11: Black–Scholes price + greeks, implied
#:         volatility, chain assembly with PCR / max-pain) joined it.
#: 3.3.0 — Order blocks (docs/05 §9a: last opposing candle before a Break of
#:         Structure, mitigation, zones) joined the PER_TIMEFRAME surface for
#:         INDEX / FUTURE.
#: 3.4.0 — Candlestick patterns (docs/05 §9b: ~14 major one/two/three-bar
#:         patterns with trend context) joined the PER_TIMEFRAME surface for
#:         INDEX / FUTURE.
#: 3.4.1 — Candlestick patterns bug fix: a candidate bar preceded by a run of
#:         >= `frozen_run_min_bars` identical zero-range bars (a provider feed
#:         snapshot carried forward, e.g. NSE_INDEX near the session close) is
#:         no longer scored as a pattern; a three-bar star also requires the
#:         middle bar to have non-zero range (was previously accepted via a
#:         div-by-zero epsilon, letting a frozen middle bar read as a "star").
#: 3.5.0 — Candlestick patterns: the doji family is sub-classed into
#:         `GRAVESTONE_DOJI` (tiny body, negligible lower wick, long upper —
#:         bearish reversal read) / `DRAGONFLY_DOJI` (mirror, bullish) / plain
#:         `DOJI` (neither wick negligible); previously every small-bodied bar
#:         was reported as generic `DOJI`.
ALGO_VERSION: str = "3.5.0"

#: Scoring engine — `weighted_v1` aggregation + per-analysis sub-scores + label
#: bands + low-confidence clamp (docs/06).
#: 1.1.0 — `order_block` sub-score + weight + added to `expected_analyses`
#:         (INDEX / FUTURE).
#: 1.2.0 — `candles` sub-score + weight (0.75) + added to `expected_analyses`.
SCORING_VERSION: str = "1.2.0"
