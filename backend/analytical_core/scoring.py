"""Scoring engine (docs/06). Pure — ``ScoringInput`` in, ``CompositeResult`` out.

No IO, no DB, no raw bars, no ``Instrument``. Sub-score functions read only a
``FactorInput``'s ``values`` / ``aux`` / ``meta``. Aggregation is the transparent
``weighted_v1`` strategy. Analytical labels only — never BUY/SELL (docs/06 §1).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from analytical_core.enums import (
    AnalysisScope,
    AnalysisStatus,
    InstrumentType,
    SignalLabel,
)
from analytical_core.params import canonical_json, params_hash
from analytical_core.versioning import SCORING_VERSION

_DP = 6


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _round(x: float) -> float:
    return round(x, _DP)


# ======================================================================================
# Input / output types (docs/04 §3.3)
# ======================================================================================


@dataclass(frozen=True, slots=True)
class FactorInput:
    analysis_key: str
    scope: AnalysisScope
    status: AnalysisStatus
    values: Mapping[str, Any] = field(default_factory=dict)
    aux: Mapping[str, Any] = field(default_factory=dict)
    meta: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class InstrumentRef:
    instrument_id: int
    instrument_type: InstrumentType
    expected_analyses: frozenset[str]


@dataclass(frozen=True, slots=True)
class ScoringInput:
    instrument: InstrumentRef
    timeframe: str
    as_of_ts: datetime
    factors: tuple[FactorInput, ...]


@dataclass(frozen=True, slots=True)
class FactorBreakdown:
    analysis_key: str
    scope: AnalysisScope
    raw_values: dict[str, Any]
    sub_score: float
    confidence: float
    weight: float
    contribution: float
    reason: str
    rationale: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CompositeResult:
    instrument_id: int
    timeframe: str
    as_of_ts: datetime
    composite_score: float
    raw_label: SignalLabel
    effective_label: SignalLabel
    confidence: float
    low_confidence: bool
    factors: tuple[FactorBreakdown, ...]
    warnings: tuple[str, ...]
    explanation: str
    strategy: str
    scoring_version: str
    params_hash: str
    weights: dict[str, float] = field(default_factory=dict)
    denom: float | None = None


# ======================================================================================
# Config (docs/06 §7)
# ======================================================================================

DEFAULT_WEIGHTS: dict[str, float] = {
    "golden_cross": 1.50,
    "open_interest": 1.25,
    "ema7": 1.00,
    "bollinger": 1.00,
    "rsi": 1.00,
    "market_profile": 1.00,
    "order_block": 1.00,
    "candles": 0.75,
    "volume": 0.75,
}

#: lower-inclusive bands, high -> low (docs/06 §5)
DEFAULT_LABEL_BANDS: tuple[tuple[float, str], ...] = (
    (60.0, SignalLabel.STRONG_BULLISH.value),
    (20.0, SignalLabel.BULLISH.value),
    (-20.0, SignalLabel.NEUTRAL.value),
    (-60.0, SignalLabel.BEARISH.value),
    (-math.inf, SignalLabel.STRONG_BEARISH.value),
)

DEFAULT_PER_ANALYSIS_PARAMS: dict[str, dict[str, float]] = {
    "rsi": {"overbought_penalty": 20.0, "divergence_bump": 25.0},
    "bollinger": {"squeeze_damp": 0.5},
    "ema7": {"norm_k": 35.0, "slope_bump": 15.0},
    "golden_cross": {"sep_k": 800.0, "recent_bump": 40.0},
    "volume": {"rvol_full": 2.0, "spike_bump": 15.0, "trend_bump": 8.0},
    "open_interest": {"oi_ref_pct": 0.02},
    "market_profile": {"in_value_damp": 0.6},
    "order_block": {"dist_k_pct": 1.0, "age_full_bars": 60.0, "in_zone_score": 70.0},
    "candles": {"pattern_score": 55.0, "recency_bars": 5.0, "cluster_bump": 6.0},
}

_TOWARD_NEUTRAL = {
    SignalLabel.STRONG_BULLISH: SignalLabel.BULLISH,
    SignalLabel.BULLISH: SignalLabel.NEUTRAL,
    SignalLabel.NEUTRAL: SignalLabel.NEUTRAL,
    SignalLabel.BEARISH: SignalLabel.NEUTRAL,
    SignalLabel.STRONG_BEARISH: SignalLabel.BEARISH,
}


@dataclass(frozen=True, slots=True)
class ScoringConfig:
    strategy: str = "weighted_v1"
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    label_bands: tuple[tuple[float, str], ...] = DEFAULT_LABEL_BANDS
    min_confidence: float = 0.35
    per_analysis_params: dict[str, dict[str, float]] = field(
        default_factory=lambda: {k: dict(v) for k, v in DEFAULT_PER_ANALYSIS_PARAMS.items()}
    )

    def as_effective_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "weights": self.weights,
            "label_bands": [
                [b[0] if math.isfinite(b[0]) else "-inf", b[1]] for b in self.label_bands
            ],
            "min_confidence": self.min_confidence,
            "per_analysis_params": self.per_analysis_params,
        }

    def hashable(self) -> str:
        return canonical_json(self.as_effective_dict())

    @classmethod
    def from_app_settings(cls, settings: Mapping[str, Any] | None) -> ScoringConfig:
        """Defaults with any ``scoring.*`` override from ``app_settings`` merged on
        top (docs/06 §7). A partial ``scoring.weights`` / ``per_analysis_params``
        still merges per key."""
        s = settings or {}
        weights = {**DEFAULT_WEIGHTS, **_num_map(s.get("scoring.weights"))}
        pap = {k: dict(v) for k, v in DEFAULT_PER_ANALYSIS_PARAMS.items()}
        for key, overrides in (s.get("scoring.per_analysis_params") or {}).items():
            pap.setdefault(key, {}).update(_num_map(overrides))
        bands = s.get("scoring.label_bands")
        label_bands = (
            tuple((float(t), str(lbl)) for t, lbl in bands)
            if isinstance(bands, list) and bands
            else DEFAULT_LABEL_BANDS
        )
        mc = s.get("scoring.min_confidence")
        return cls(
            weights=weights,
            label_bands=label_bands,
            min_confidence=float(mc) if isinstance(mc, int | float) else 0.35,
            per_analysis_params=pap,
        )


def _num_map(v: Any) -> dict[str, float]:
    if not isinstance(v, Mapping):
        return {}
    return {str(k): float(x) for k, x in v.items() if isinstance(x, int | float)}


def default_config() -> ScoringConfig:
    return ScoringConfig()


def expected_analyses(
    instrument_type: InstrumentType, *, has_volume: bool = True
) -> frozenset[str]:
    if instrument_type is InstrumentType.INDEX:
        base = {
            "rsi",
            "bollinger",
            "ema7",
            "golden_cross",
            "market_profile",
            "order_block",
            "candles",
        }
        if has_volume:
            base.add("volume")
        return frozenset(base)
    if instrument_type is InstrumentType.FUTURE:
        return frozenset(
            {
                "rsi",
                "bollinger",
                "ema7",
                "volume",
                "open_interest",
                "market_profile",
                "order_block",
                "candles",
            }
        )
    # OPTION is chain-only (docs/04 §2.3/§4): premium-series technicals do not run;
    # only open_interest contributes, feeding the option-chain view (docs/05 §11).
    return frozenset({"open_interest"})  # OPTION


# ======================================================================================
# Sub-scores (docs/06 §3.1) — each returns (sub_score, confidence, reason, rationale)
# ======================================================================================


@dataclass(frozen=True, slots=True)
class _Sub:
    sub_score: float
    confidence: float
    reason: str
    rationale: dict[str, Any]


_POSITION_ADJECTIVE = {
    "MIDDLE": "mid-range",
    "UPPER_HALF": "upper half",
    "LOWER_HALF": "lower half",
    "ABOVE_UPPER": "above the upper band",
    "BELOW_LOWER": "below the lower band",
}


def _score_rsi(f: FactorInput, p: Mapping[str, float]) -> _Sub | None:
    v = f.values
    rsi = float(v["rsi"])
    base = _clamp((rsi - 50.0) * 2.0, -100.0, 100.0)
    if rsi >= 70.0:
        base = min(base, 100.0) - p["overbought_penalty"]
    elif rsi <= 30.0:
        base = max(base, -100.0) + p["overbought_penalty"]
    div = v.get("divergence", "NONE")
    if div == "BULLISH":
        base += p["divergence_bump"]
    elif div == "BEARISH":
        base -= p["divergence_bump"]
    base = _clamp(base, -100.0, 100.0)
    warm = bool(f.meta.get("warmup_ok")) and bool(f.meta.get("last_bar_final", True))
    return _Sub(
        base,
        0.9 if warm else 0.5,
        f"RSI {rsi:.0f} — {str(v.get('state', 'NEUTRAL')).lower()}",
        {"rsi": rsi, "divergence": div},
    )


def _score_bollinger(f: FactorInput, p: Mapping[str, float]) -> _Sub | None:
    v = f.values
    pos = str(v["position"])
    base = {
        "ABOVE_UPPER": 60.0,
        "UPPER_HALF": 25.0,
        "MIDDLE": 0.0,
        "LOWER_HALF": -25.0,
        "BELOW_LOWER": -60.0,
    }[pos]
    pb = v.get("percent_b")
    if pb is not None:
        base += _clamp((float(pb) - 0.5) * 40.0, -20.0, 20.0)
    if v.get("squeeze") is True:
        base *= p["squeeze_damp"]
    base = _clamp(base, -100.0, 100.0)
    bwp = v.get("bandwidth_percentile")
    if bwp is None:
        conf = 0.8 * 0.7
    elif 0.3 <= float(bwp) <= 0.7:
        conf = 0.9
    else:
        conf = 0.8
    return _Sub(
        base, conf, f"Bollinger {_POSITION_ADJECTIVE.get(pos, pos.lower())}", {"position": pos}
    )


def _score_ema7(f: FactorInput, p: Mapping[str, float]) -> _Sub | None:
    v, a = f.values, f.aux
    ema = float(v["ema"])
    atr = a.get("atr14")
    if atr is not None:
        vol_ref = float(atr)
    elif a.get("close_stdev_n") is not None:
        vol_ref = float(a["close_stdev_n"])
    else:
        vol_ref = 0.01 * abs(ema)
    norm = _clamp(float(v["price_vs_ema"]) / max(vol_ref, 1e-9), -2.0, 2.0)
    base = norm * p["norm_k"]
    state = str(v.get("slope_state", "UNKNOWN"))
    if state == "RISING":
        base += p["slope_bump"]
    elif state == "FALLING":
        base -= p["slope_bump"]
    base = _clamp(base, -100.0, 100.0)
    warm = bool(f.meta.get("warmup_ok"))
    conf = 0.6 if atr is None else (0.8 if (state != "UNKNOWN" and warm) else 0.5)
    above = bool(v.get("price_above"))
    slope_txt = {"RISING": "a rising slope", "FALLING": "a falling slope"}.get(
        state, "a flat slope"
    )
    reason = f"Price {'above' if above else 'below'} the 7-EMA with {slope_txt}"
    return _Sub(
        base,
        conf,
        reason,
        {"slope_state": state, "vol_ref_from": "atr14" if atr is not None else "stdev"},
    )


def _score_golden_cross(f: FactorInput, p: Mapping[str, float]) -> _Sub | None:
    v = f.values
    state = str(v.get("state", "BELOW"))
    base = 40.0 if state == "ABOVE" else -40.0
    recent = bool(v.get("recent"))
    ct = str(v.get("cross_type", "NONE_IN_WINDOW"))
    if ct == "GOLDEN" and recent:
        base += p["recent_bump"]
    elif ct == "DEATH" and recent:
        base -= p["recent_bump"]
    sep = v.get("separation")
    if sep is not None:
        base += _clamp(float(sep) * p["sep_k"], -20.0, 20.0)
    if v.get("provisional") is True:
        base *= 0.5
    base = _clamp(base, -100.0, 100.0)
    mp = f.meta.get("params", {})
    need = int(mp.get("slow_period", 200)) + int(mp.get("cross_search_window", 60))
    bars = int(f.meta.get("bars_used") or 0)
    last_final = bool(f.meta.get("last_bar_final", True))
    if bars >= need and last_final:
        conf = 0.9
    else:
        conf = _clamp(0.9 * (bars / need) if need else 0.4, 0.4, 0.9)
    bsc = v.get("bars_since_cross")
    if ct in ("GOLDEN", "DEATH") and recent and bsc is not None:
        reason = f"{'Golden' if ct == 'GOLDEN' else 'Death'} cross on the index ({bsc} bars ago)"
    else:
        reason = f"50/200 MA {'above' if state == 'ABOVE' else 'below'} on the index"
    return _Sub(base, conf, reason, {"state": state, "cross_type": ct, "recent": recent})


def _score_volume(f: FactorInput, p: Mapping[str, float]) -> _Sub | None:
    v, a = f.values, f.aux
    rvol = v.get("rvol")
    scaled = 0.0 if rvol is None else _clamp((float(rvol) - 1.0) / (p["rvol_full"] - 1.0), 0.0, 1.0)
    pcr = a.get("price_change_pct_recent")
    pcr = 0.0 if pcr is None else float(pcr)
    pdir = 1 if pcr > 0 else (-1 if pcr < 0 else 0)
    base = pdir * scaled * 40.0
    if v.get("spike") is True:
        base += (pdir or 1) * p["spike_bump"]
    if str(v.get("trend")) == "RISING":
        base += p["trend_bump"] if pcr > 0 else (-p["trend_bump"] if pcr < 0 else 0.0)
    base = _clamp(base, -100.0, 100.0)
    reason = "Volume thin" if rvol is None else f"Volume {float(rvol):.1f}x average"
    return _Sub(base, 0.7, reason, {"rvol": rvol, "spike": bool(v.get("spike"))})


_OI_BASE = {
    "LONG_BUILDUP": 50.0,
    "SHORT_COVERING": 35.0,
    "SHORT_BUILDUP": -50.0,
    "LONG_UNWINDING": -35.0,
    "INDETERMINATE": 0.0,
}
_OI_PHRASE = {
    "LONG_BUILDUP": "long buildup",
    "SHORT_COVERING": "short covering",
    "SHORT_BUILDUP": "short buildup",
    "LONG_UNWINDING": "long unwinding",
    "INDETERMINATE": "indeterminate",
}


def _score_open_interest(f: FactorInput, p: Mapping[str, float]) -> _Sub | None:
    v = f.values
    behavior = str(v.get("behavior", "INDETERMINATE"))
    base_mag = _OI_BASE.get(behavior, 0.0)
    oip = v.get("oi_pct_change")
    scale = 0.5 if oip is None else _clamp(abs(float(oip)) / p["oi_ref_pct"], 0.0, 1.0)
    base = _clamp(base_mag * scale, -100.0, 100.0)
    conf = 0.4 if behavior == "INDETERMINATE" else 0.75
    rationale: dict[str, Any] = {"behavior": behavior, "oi_pct_change": oip}
    for w in f.meta.get("warnings", []):
        if "option contract" in w:
            rationale["option_semantics"] = w
    ppc = v.get("price_pct_change")
    detail = ""
    if oip is not None and ppc is not None:
        detail = f" (OI {float(oip) * 100:+.1f}%, price {float(ppc) * 100:+.1f}%)"
    reason = f"OI: {_OI_PHRASE.get(behavior, behavior.lower())}{detail}"
    return _Sub(base, conf, reason, rationale)


def _score_market_profile(f: FactorInput, p: Mapping[str, float]) -> _Sub | None:
    v = f.values
    if "close_vs_vah" not in v and "close_vs_poc" not in v:
        return None  # no profile-position data (e.g. INSUFFICIENT_DATA) -> abstain
    base = 0.0
    if v.get("close_vs_vah") == "ABOVE":
        base = 40.0
    elif v.get("close_vs_val") == "BELOW":
        base = -40.0
    else:
        base = {"ABOVE": 20.0, "BELOW": -20.0}.get(str(v.get("close_vs_poc")), 0.0)
    shape = str(v.get("profile_shape", "NORMAL"))
    base += {"TREND_UP": 15.0, "TREND_DOWN": -15.0, "P_SHAPE": 8.0, "B_SHAPE": -8.0}.get(shape, 0.0)
    if v.get("close_in_value_area") is True:
        base *= p["in_value_damp"]
    base = _clamp(base, -100.0, 100.0)
    conf = 0.8 if v.get("is_session_complete") else 0.55
    return _Sub(
        base, conf, f"Market profile {shape.lower().replace('_', ' ')}", {"profile_shape": shape}
    )


def _score_order_block(f: FactorInput, p: Mapping[str, float]) -> _Sub | None:
    v = f.values
    state = str(v.get("zone_state", "OUTSIDE"))
    nb = v.get("nearest_bullish")
    ns = v.get("nearest_bearish")

    def _pull(z: Mapping[str, Any] | None, k_pct: float, age_full: float) -> float:
        if not z:
            return 0.0
        near = max(0.0, 1.0 - abs(float(z["distance_pct"])) / k_pct) if k_pct > 0 else 0.0
        fresh = max(0.0, 1.0 - int(z["age_bars"]) / age_full) if age_full > 0 else 0.0
        return near * fresh

    if state == "IN_BULLISH":
        base = p["in_zone_score"]
    elif state == "IN_BEARISH":
        base = -p["in_zone_score"]
    else:
        b = 60.0 * _pull(nb, p["dist_k_pct"], p["age_full_bars"])
        s = 60.0 * _pull(ns, p["dist_k_pct"], p["age_full_bars"])
        base = b - s
    base = _clamp(base, -100.0, 100.0)

    warm = bool(f.meta.get("warmup_ok")) and bool(f.meta.get("last_bar_final", True))
    has_any = (nb is not None) or (ns is not None)
    conf = 0.0 if not has_any else (0.8 if warm else 0.45)
    bias = str(v.get("bias", "NEUTRAL"))
    where = {
        "IN_BULLISH": "price is tagging a bullish (demand) order block",
        "IN_BEARISH": "price is tagging a bearish (supply) order block",
    }.get(state, f"{v.get('n_active_bullish', 0)} bullish / {v.get('n_active_bearish', 0)} bearish blocks in play")
    return _Sub(base, conf, f"Order blocks — {bias.lower()}; {where}", {"zone_state": state, "bias": bias})


_CANDLE_STRENGTH_W = {"WEAK": 0.4, "MODERATE": 0.7, "STRONG": 1.0}


def _score_candles(f: FactorInput, p: Mapping[str, float]) -> _Sub | None:
    v = f.values
    lp = v.get("last_pattern")
    if lp is None:
        return _Sub(0.0, 0.0, "Candles — no major pattern in the recent bars", {})
    bias = str(v.get("last_bias", "NEUTRAL"))
    sw = _CANDLE_STRENGTH_W.get(str(v.get("last_strength", "WEAK")), 0.4)
    ago = int(v.get("last_bars_ago") or 0)
    recency = max(0.0, 1.0 - ago / max(p["recency_bars"], 1.0))
    mag = p["pattern_score"] * sw * recency
    base = mag if bias == "BULLISH" else -mag if bias == "BEARISH" else 0.0
    # a cluster of same-direction patterns in the window adds a little
    net = int(v.get("n_bullish", 0)) - int(v.get("n_bearish", 0))
    base += _clamp(net * p["cluster_bump"], -p["cluster_bump"] * 3, p["cluster_bump"] * 3)
    base = _clamp(base, -100.0, 100.0)
    warm = bool(f.meta.get("warmup_ok")) and bool(f.meta.get("last_bar_final", True))
    conf = (0.75 if warm else 0.45) * (0.6 + 0.4 * sw)
    where = "on the last bar" if v.get("on_last_bar") else f"{ago} bars ago"
    return _Sub(
        base,
        round(conf, 3),
        f"Candles — {lp.replace('_', ' ').lower()} ({bias.lower()}, {where})",
        {"pattern": lp, "bias": bias, "strength": v.get("last_strength")},
    )


SUBSCORES: dict[str, Callable[[FactorInput, Mapping[str, float]], _Sub | None]] = {
    "rsi": _score_rsi,
    "bollinger": _score_bollinger,
    "ema7": _score_ema7,
    "golden_cross": _score_golden_cross,
    "volume": _score_volume,
    "open_interest": _score_open_interest,
    "market_profile": _score_market_profile,
    "order_block": _score_order_block,
    "candles": _score_candles,
}


# ======================================================================================
# Aggregation + labels (docs/06 §4, §5)
# ======================================================================================


def label_for(composite: float, bands: tuple[tuple[float, str], ...]) -> SignalLabel:
    """docs/06 §5: ``>= +60`` STRONG_BULLISH, ``<= -60`` STRONG_BEARISH; interior
    boundaries resolve symmetrically toward the stronger label (``+20`` -> BULLISH,
    ``-20`` -> BEARISH)."""
    for i, (threshold, label) in enumerate(bands):
        if i == 0 or threshold >= 0:
            if composite >= threshold:
                return SignalLabel(label)
        elif composite > threshold:
            return SignalLabel(label)
    return SignalLabel(bands[-1][1])  # pragma: no cover


def _collect_warnings(factors: tuple[FactorInput, ...], usable_keys: set[str]) -> list[str]:
    w: list[str] = []
    for f in factors:
        if f.status is AnalysisStatus.NOT_APPLICABLE:
            w.append(f"{f.analysis_key}: not applicable")
        elif f.status is AnalysisStatus.INSUFFICIENT_DATA:
            w.append(f"{f.analysis_key}: insufficient data")
        elif f.analysis_key in usable_keys:
            if f.meta.get("last_bar_final") is False:
                w.append(f"{f.analysis_key}: computed on a non-final bar")
            if f.values.get("provisional") is True:
                w.append(f"{f.analysis_key}: provisional cross")
            for m in f.meta.get("warnings", []):
                if "option contract" in m:
                    w.append("open_interest: option-strike positioning, not the underlying")
    return w


def score(inp: ScoringInput, config: ScoringConfig | None = None) -> CompositeResult:
    config = config or default_config()
    ph = params_hash({"cfg": config.hashable()})
    weights = config.weights
    expected = inp.instrument.expected_analyses & set(weights)

    usable: list[tuple[FactorInput, _Sub]] = []
    for f in inp.factors:
        if f.status is not AnalysisStatus.OK or f.analysis_key not in SUBSCORES:
            continue
        if f.analysis_key not in weights:
            continue
        sub = SUBSCORES[f.analysis_key](f, config.per_analysis_params.get(f.analysis_key, {}))
        if sub is not None:
            usable.append((f, sub))

    usable_keys = {f.analysis_key for f, _ in usable}
    warnings = _collect_warnings(inp.factors, usable_keys)

    denom = math.fsum(weights[f.analysis_key] * s.confidence for f, s in usable)
    breakdowns: list[FactorBreakdown] = []

    if denom == 0.0:
        warnings.append("no usable factors")
        return CompositeResult(
            instrument_id=inp.instrument.instrument_id,
            timeframe=inp.timeframe,
            as_of_ts=inp.as_of_ts,
            composite_score=0.0,
            raw_label=SignalLabel.NEUTRAL,
            effective_label=SignalLabel.NEUTRAL,
            confidence=0.0,
            low_confidence=True,
            factors=(),
            warnings=tuple(warnings),
            explanation="NEUTRAL (0.0, confidence 0.00). No usable factors this cycle.",
            strategy=config.strategy,
            scoring_version=SCORING_VERSION,
            params_hash=ph,
            weights=dict(weights),
            denom=0.0,
        )

    num = math.fsum(weights[f.analysis_key] * s.confidence * s.sub_score for f, s in usable)
    composite = _clamp(num / denom, -100.0, 100.0)
    for f, s in usable:
        w = weights[f.analysis_key]
        contribution = (w * s.confidence * s.sub_score) / denom
        breakdowns.append(
            FactorBreakdown(
                analysis_key=f.analysis_key,
                scope=f.scope,
                raw_values=dict(f.values),
                sub_score=_round(s.sub_score),
                confidence=_round(s.confidence),
                weight=_round(w),
                contribution=_round(contribution),
                reason=s.reason,
                rationale=s.rationale,
            )
        )

    have = denom
    expected_mass = math.fsum(weights[k] for k in expected)
    extra_mass = math.fsum(
        weights[f.analysis_key] * s.confidence for f, s in usable if f.analysis_key not in expected
    )
    union_mass = expected_mass + extra_mass
    overall_conf = _clamp(have / union_mass, 0.0, 1.0) if union_mass > 0 else 0.0

    raw_label = label_for(composite, config.label_bands)
    if overall_conf < config.min_confidence:
        effective_label = _TOWARD_NEUTRAL[raw_label]
        low_conf = True
    else:
        effective_label = raw_label
        low_conf = False

    breakdowns.sort(key=lambda b: abs(b.contribution), reverse=True)
    explanation = _explain(effective_label, composite, overall_conf, breakdowns)

    return CompositeResult(
        instrument_id=inp.instrument.instrument_id,
        timeframe=inp.timeframe,
        as_of_ts=inp.as_of_ts,
        composite_score=_round(composite),
        raw_label=raw_label,
        effective_label=effective_label,
        confidence=_round(overall_conf),
        low_confidence=low_conf,
        factors=tuple(breakdowns),
        warnings=tuple(warnings),
        explanation=explanation,
        strategy=config.strategy,
        scoring_version=SCORING_VERSION,
        params_hash=ph,
        weights=dict(weights),
        denom=_round(denom),
    )


def _explain(
    label: SignalLabel, composite: float, confidence: float, factors: list[FactorBreakdown]
) -> str:
    head = f"{label.value} ({composite:.1f}, confidence {confidence:.2f})."
    clauses = ". ".join(b.reason for b in factors)
    return f"{head} {clauses}." if clauses else head
