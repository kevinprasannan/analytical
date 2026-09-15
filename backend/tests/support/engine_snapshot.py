"""Golden snapshot of the deterministic engine surface — the ``ALGO_VERSION`` /
``SCORING_VERSION`` version guard (docs/09 §2.1).

``build_snapshot`` runs every deterministic engine (the six indicators, Market
Profile, and the scoring aggregation) over a fixed synthetic battery and returns
a plain-dict view of their outputs. ``test_version_guard.py`` hashes it and
compares against ``fixtures/analysis/engine_snapshot.json``: any change to a
formula, default parameter, rounding, tie-break, or approximation shifts the
digest and fails the test until the fixture is regenerated **and** the matching
version constant is bumped.

Regenerate (after a deliberate engine change, in the same commit as the bump)::

    python -m tests.support.engine_snapshot
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

from analytical_core.enums import AnalysisScope, InstrumentType, Timeframe
from analytical_core.indicators import (
    bollinger,
    candles,
    ema7,
    golden_cross,
    open_interest,
    order_block,
    rsi,
    volume,
)
from analytical_core.market_profile import MarketProfileConfig, market_profile
from analytical_core.params import canonical_json
from analytical_core.scoring import (
    FactorInput,
    InstrumentRef,
    ScoringInput,
    default_config,
    expected_analyses,
    score,
)
from analytical_core.series import OHLCVSeries, OpenInterestSeries
from analytical_core.versioning import ALGO_VERSION, SCORING_VERSION

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "analysis" / "engine_snapshot.json"

_T0 = datetime(2026, 8, 27, 3, 45, tzinfo=UTC)  # NSE session open, bar-open UTC
_SESSION_OPEN = _T0
_SESSION_CLOSE = datetime(2026, 8, 27, 10, 0, tzinfo=UTC)  # 15:30 IST


def _ohlcv(closes, *, vols=None, finals=None, tf=Timeframe.M5, minutes=1):
    n = len(closes)
    c = tuple(float(x) for x in closes)
    o = (c[0], *c[:-1])
    h = tuple(max(a, b) + 1.5 for a, b in zip(o, c, strict=True))
    low = tuple(min(a, b) - 1.5 for a, b in zip(o, c, strict=True))
    return OHLCVSeries(
        timeframe=tf,
        ts=tuple(_T0 + timedelta(minutes=minutes * i) for i in range(n)),
        open=o,
        high=h,
        low=low,
        close=c,
        volume=tuple(
            int(x) for x in (vols if vols is not None else [1000 + 7 * i for i in range(n)])
        ),
        is_final=tuple(bool(x) for x in (finals if finals is not None else [True] * n)),
        expected_grid_len=n,
    )


def _wave(n, base, amp, period):
    return [base + amp * math.sin(2 * math.pi * i / period) + 0.4 * i for i in range(n)]


def _hump(n, centre, amp):
    return [centre + amp * math.exp(-((i - n / 2) ** 2) / (2 * (n / 6) ** 2)) for i in range(n)]


def _result_view(r) -> dict:
    return {
        "status": r.status.value,
        "values": r.values,
        "aux": r.aux,
        "warnings": list(r.warnings),
    }


def _compute_indicators() -> dict:
    wave = _ohlcv(_wave(40, 100.0, 6.0, 11))
    vol_series = _ohlcv(
        _wave(40, 100.0, 4.0, 9),
        vols=[500] * 20 + [520, 480, 610, 505, 495, 700, 510, 490, 900, 520] + [500] * 10,
    )
    gc_series = _ohlcv(
        [200.0 - 0.7 * i for i in range(200)] + [60.0 + 2.4 * i for i in range(60)],
        minutes=1440,
        tf=Timeframe.D1,
    )
    oi_series = OpenInterestSeries(
        scope=AnalysisScope.PER_TIMEFRAME,
        ts=tuple(_T0 + timedelta(days=i) for i in range(20)),
        oi=tuple(10_000 + 300 * i + (250 if i % 3 == 0 else -120) for i in range(20)),
        price=tuple(100.0 + 1.5 * i - (2.0 if i % 4 == 0 else 0.0) for i in range(20)),
    )
    return {
        "rsi": rsi(wave),
        "bollinger": bollinger(wave),
        "ema7": ema7(wave),
        "golden_cross": golden_cross(gc_series, instrument_type=InstrumentType.INDEX),
        "volume": volume(vol_series, has_volume=True),
        "open_interest": open_interest(oi_series, instrument_type=InstrumentType.FUTURE),
        "order_block": order_block(gc_series),
        "candles": candles(gc_series),
        # an INSUFFICIENT_DATA edge so a shift in the min-bars gate is caught too
        "rsi_insufficient": rsi(_ohlcv([100.0, 101.0, 100.5])),
    }


def _market_profile() -> dict:
    n = 75
    closes = _hump(n, 24_000.0, 150.0)
    series = _ohlcv(closes, tf=Timeframe.M5, minutes=5)
    out = market_profile(
        series,
        config=MarketProfileConfig(),
        session_open=_SESSION_OPEN,
        session_close=_SESSION_CLOSE,
        session_date=_SESSION_OPEN.date(),
        instrument_type=InstrumentType.INDEX,
        has_volume=True,
        price_ref=24_000.0,
        underlying_symbol="NIFTY",
        now=_SESSION_CLOSE + timedelta(minutes=5),
    )
    return {
        "status": out.status,
        "reason": out.reason,
        "params": out.params,
        "profiles": {
            name: pr.values(_SESSION_OPEN.date(), _SESSION_OPEN, _SESSION_CLOSE)
            for name, pr in sorted(out.profiles.items())
        },
    }


def _scoring(indicator_results: dict) -> dict:
    itype = InstrumentType.FUTURE
    ref = InstrumentRef(1, itype, expected_analyses(itype, has_volume=True))
    factors = tuple(
        FactorInput(
            r.analysis_key,
            r.scope,
            r.status,
            r.values,
            r.aux,
            {"last_bar_final": True},
        )
        for key, r in indicator_results.items()
        if key in {"rsi", "bollinger", "ema7", "volume", "open_interest", "order_block", "candles"}
    )
    cr = score(ScoringInput(ref, "M5", _T0, factors), default_config())
    return {
        "composite_score": cr.composite_score,
        "raw_label": cr.raw_label.value,
        "effective_label": cr.effective_label.value,
        "confidence": cr.confidence,
        "low_confidence": cr.low_confidence,
        "denom": cr.denom,
        "weights": cr.weights,
        "factors": [
            {
                "analysis_key": b.analysis_key,
                "sub_score": b.sub_score,
                "confidence": b.confidence,
                "weight": b.weight,
                "contribution": b.contribution,
                "reason": b.reason,
            }
            for b in cr.factors
        ],
        "explanation": cr.explanation,
    }


def _options() -> dict:
    from datetime import date

    from analytical_core.options import LegInput, bs_greeks, bs_price, build_chain

    now = datetime(2026, 8, 27, 5, 0, tzinfo=UTC)
    S, r, T = 24000.0, 0.065, 33 / 365
    price = bs_price(S, 24100.0, T, r, 0.15, is_call=True)
    g = bs_greeks(S, 24100.0, T, r, 0.15, is_call=True)
    legs = []
    for k in (23800, 23900, 24000, 24100, 24200):
        legs.append(
            LegInput(
                float(k),
                "CE",
                bs_price(S, float(k), T, r, 0.14, is_call=True),
                90000 + k,
                1000,
                4000,
            )
        )
        legs.append(
            LegInput(
                float(k),
                "PE",
                bs_price(S, float(k), T, r, 0.16, is_call=False),
                80000 + k,
                900,
                3000,
            )
        )
    ch = build_chain(
        underlying_symbol="NIFTY",
        spot=S,
        expiry=date(2026, 9, 29),
        now=now,
        risk_free_rate=r,
        legs=legs,
    )
    return {
        "sample_call_price": price,
        "sample_call_greeks": [g.delta, g.gamma, g.theta, g.vega, g.rho],
        "chain": {
            "atm": ch.atm_strike,
            "dte": ch.days_to_expiry,
            "pcr_oi": ch.pcr_oi,
            "max_pain": ch.max_pain_strike,
            "rows": [
                {
                    "strike": row.strike,
                    "ce": (
                        None if row.call is None else [row.call.iv, row.call.delta, row.call.theta]
                    ),
                    "pe": None if row.put is None else [row.put.iv, row.put.delta, row.put.theta],
                }
                for row in ch.rows
            ],
        },
    }


def build_snapshot() -> dict:
    indicators = _compute_indicators()
    return {
        "algo_version": ALGO_VERSION,
        "scoring_version": SCORING_VERSION,
        "indicators": {k: _result_view(r) for k, r in indicators.items()},
        "market_profile": _market_profile(),
        "scoring": _scoring(indicators),
        "options": _options(),
    }


def snapshot_payload() -> str:
    return canonical_json(build_snapshot())


def write_fixture() -> str:
    payload = snapshot_payload()
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(json.loads(payload), indent=2, sort_keys=True) + "\n")
    return payload


if __name__ == "__main__":  # pragma: no cover
    write_fixture()
    snap = build_snapshot()
    print(f"wrote {FIXTURE}")
    print(f"algo_version={snap['algo_version']} scoring_version={snap['scoring_version']}")
