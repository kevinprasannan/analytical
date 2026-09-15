"""Phase 3 DoD item 6 — the API result models mirror the engine output exactly."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest

from analytical_core.enums import InstrumentType, Timeframe
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
from analytical_core.series import OHLCVSeries, OpenInterestSeries
from app.api.schemas.analysis import AUX_MODELS, VALUE_MODELS

T0 = datetime(2026, 8, 27, tzinfo=UTC)


def _ohlcv(n: int, tf=Timeframe.D1) -> OHLCVSeries:
    rng = random.Random(7)
    close = [100.0]
    for _ in range(n - 1):
        close.append(close[-1] * (1 + rng.uniform(-0.02, 0.02)))
    o = [close[0], *close[:-1]]
    return OHLCVSeries(
        timeframe=tf,
        ts=tuple(T0 + timedelta(days=i) for i in range(n)),
        open=tuple(o),
        high=tuple(max(a, b) + 1 for a, b in zip(o, close, strict=True)),
        low=tuple(min(a, b) - 1 for a, b in zip(o, close, strict=True)),
        close=tuple(close),
        volume=tuple(1000 + i for i in range(n)),
        is_final=tuple([True] * n),
        expected_grid_len=n,
    )


def _oi(n: int) -> OpenInterestSeries:
    return OpenInterestSeries(
        scope=__import__(
            "analytical_core.enums", fromlist=["AnalysisScope"]
        ).AnalysisScope.PER_TIMEFRAME,
        ts=tuple(T0 + timedelta(minutes=5 * i) for i in range(n)),
        oi=tuple(1000 + 10 * i for i in range(n)),
        price=tuple(50.0 + i for i in range(n)),
        provider_oi_change=tuple(5 for _ in range(n)),
    )


_ENGINE_OUTPUTS = {
    "rsi": lambda: rsi(_ohlcv(120)),
    "bollinger": lambda: bollinger(_ohlcv(180)),
    "ema7": lambda: ema7(_ohlcv(60)),
    "golden_cross": lambda: golden_cross(_ohlcv(300), instrument_type=InstrumentType.INDEX),
    "volume": lambda: volume(_ohlcv(60), has_volume=True),
    "open_interest": lambda: open_interest(_oi(10), instrument_type=InstrumentType.FUTURE),
    "order_block": lambda: order_block(_ohlcv(220)),
    "candles": lambda: candles(_ohlcv(220)),
}


@pytest.mark.parametrize("key", sorted(VALUE_MODELS))
def test_value_model_validates_real_engine_output(key):
    res = _ENGINE_OUTPUTS[key]()
    assert res.status.value == "OK", res.values
    model = VALUE_MODELS[key](**res.values)  # must not raise
    # round-trips without losing enum-typed fields
    dumped = model.model_dump(mode="json")
    assert set(dumped) == set(res.values)


@pytest.mark.parametrize("key", sorted(AUX_MODELS))
def test_aux_model_validates_real_engine_output(key):
    res = _ENGINE_OUTPUTS[key]()
    AUX_MODELS[key](**res.aux)


def test_provenance_model_accepts_engine_meta():
    from app.api.schemas.common import Provenance

    res = rsi(_ohlcv(120))
    Provenance(**{k: res.meta.get(k) for k in Provenance.model_fields})
