"""Scoring engine — sub-scores, weighted_v1 aggregation, labels, provenance (docs/06)."""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest

from analytical_core.enums import AnalysisScope, AnalysisStatus, InstrumentType, SignalLabel
from analytical_core.scoring import (
    DEFAULT_WEIGHTS,
    FactorInput,
    InstrumentRef,
    ScoringConfig,
    ScoringInput,
    default_config,
    expected_analyses,
    label_for,
    score,
)
from analytical_core.versioning import SCORING_VERSION

NOW = datetime(2026, 8, 27, tzinfo=UTC)
_PT = AnalysisScope.PER_TIMEFRAME


def _f(key, values, *, aux=None, meta=None, status=AnalysisStatus.OK, scope=_PT) -> FactorInput:
    return FactorInput(key, scope, status, values, aux or {}, meta or {"last_bar_final": True})


def _score(factors, *, itype=InstrumentType.INDEX, has_volume=True, config=None):
    ref = InstrumentRef(1, itype, expected_analyses(itype, has_volume=has_volume))
    return score(ScoringInput(ref, "D1", NOW, tuple(factors)), config or default_config())


# ======================================================================================
# sub-scores (docs/06 §3.1)
# ======================================================================================


def test_rsi_subscore_direction_and_overbought_damp():
    warm = {"warmup_ok": True, "last_bar_final": True}
    bull = _score([_f("rsi", {"rsi": 65.0, "state": "NEUTRAL", "divergence": "NONE"}, meta=warm)])
    assert bull.factors[0].sub_score == pytest.approx(30.0)  # (65-50)*2
    assert bull.factors[0].confidence == pytest.approx(0.9)

    ob = _score([_f("rsi", {"rsi": 75.0, "state": "OVERBOUGHT", "divergence": "NONE"}, meta=warm)])
    assert ob.factors[0].sub_score == pytest.approx(
        30.0
    )  # (75-50)*2=50, then -20 overbought penalty


def test_rsi_divergence_bump_and_low_confidence_without_warmup():
    r = _score(
        [
            _f(
                "rsi",
                {"rsi": 45.0, "state": "NEUTRAL", "divergence": "BULLISH"},
                meta={"last_bar_final": True},
            )
        ]
    )
    assert r.factors[0].sub_score == pytest.approx(-10.0 + 25.0)  # (45-50)*2 + 25
    assert r.factors[0].confidence == pytest.approx(0.5)  # warmup_ok missing


def test_bollinger_position_map_and_squeeze_damp():
    base = _score(
        [
            _f(
                "bollinger",
                {
                    "position": "UPPER_HALF",
                    "percent_b": 0.5,
                    "bandwidth_percentile": 0.5,
                    "squeeze": False,
                },
            )
        ]
    )
    assert base.factors[0].sub_score == pytest.approx(25.0)
    sq = _score(
        [
            _f(
                "bollinger",
                {
                    "position": "UPPER_HALF",
                    "percent_b": 0.5,
                    "bandwidth_percentile": 0.5,
                    "squeeze": True,
                },
            )
        ]
    )
    assert sq.factors[0].sub_score == pytest.approx(12.5)  # * 0.5
    mid = _score(
        [
            _f(
                "bollinger",
                {
                    "position": "MIDDLE",
                    "percent_b": 0.5,
                    "bandwidth_percentile": None,
                    "squeeze": None,
                },
            )
        ]
    )
    assert mid.factors[0].sub_score == pytest.approx(0.0)
    assert mid.factors[0].confidence == pytest.approx(0.8 * 0.7)  # null bandwidth_percentile


def test_ema_norm_and_slope_and_fallback_confidence():
    warm = {"warmup_ok": True, "last_bar_final": True}
    a = _score(
        [
            _f(
                "ema7",
                {"ema": 100.0, "price_vs_ema": 2.0, "price_above": True, "slope_state": "RISING"},
                aux={"atr14": 1.0},
                meta=warm,
            )
        ]
    )
    assert a.factors[0].sub_score == pytest.approx(
        2.0 * 35.0 + 15.0
    )  # norm clamped at 2 -> 70 + slope 15
    assert a.factors[0].confidence == pytest.approx(0.8)
    b = _score(
        [
            _f(
                "ema7",
                {"ema": 100.0, "price_vs_ema": 0.5, "price_above": True, "slope_state": "FLAT"},
                aux={"atr14": None, "close_stdev_n": 1.0},
                meta=warm,
            )
        ]
    )
    assert b.factors[0].confidence == pytest.approx(0.6)  # atr14 null -> fallback vol_ref


def test_golden_cross_recent_bump_and_provisional_halving():
    meta = {
        "bars_used": 300,
        "last_bar_final": True,
        "params": {"slow_period": 200, "cross_search_window": 60},
    }
    g = _score(
        [
            _f(
                "golden_cross",
                {
                    "state": "ABOVE",
                    "cross_type": "GOLDEN",
                    "recent": True,
                    "bars_since_cross": 5,
                    "separation": 0.0,
                    "provisional": False,
                },
                meta=meta,
            )
        ]
    )
    assert g.factors[0].sub_score == pytest.approx(80.0)  # 40 + 40
    p = _score(
        [
            _f(
                "golden_cross",
                {
                    "state": "ABOVE",
                    "cross_type": "GOLDEN",
                    "recent": True,
                    "bars_since_cross": 0,
                    "separation": 0.0,
                    "provisional": True,
                },
                meta=meta,
            )
        ]
    )
    assert p.factors[0].sub_score == pytest.approx(40.0)  # 80 * 0.5


def test_volume_rvol_scaling_and_spike():
    v = _score(
        [
            _f(
                "volume",
                {"volume": 1, "vol_ma": 1, "rvol": 2.0, "spike": True, "trend": "RISING"},
                aux={"price_change_pct_recent": 0.01},
            )
        ]
    )
    # dir=+1, scaled_rvol=1.0 -> 40 ; spike +15 ; trend RISING & up +8
    assert v.factors[0].sub_score == pytest.approx(63.0)
    n = _score(
        [
            _f(
                "volume",
                {"volume": 1, "vol_ma": 1, "rvol": None, "spike": False, "trend": "FLAT"},
                aux={"price_change_pct_recent": None},
            )
        ]
    )
    assert n.factors[0].sub_score == pytest.approx(0.0)


def test_oi_behavior_map_and_null_pct_fixed_scale():
    lb = _score(
        [
            _f(
                "open_interest",
                {"behavior": "LONG_BUILDUP", "oi_pct_change": 0.02, "price_pct_change": 0.01},
            )
        ],
        itype=InstrumentType.FUTURE,
    )
    assert lb.factors[0].sub_score == pytest.approx(50.0)  # 50 * clamp(0.02/0.02)=1
    nul = _score(
        [
            _f(
                "open_interest",
                {"behavior": "SHORT_BUILDUP", "oi_pct_change": None, "price_pct_change": None},
            )
        ],
        itype=InstrumentType.FUTURE,
    )
    assert nul.factors[0].sub_score == pytest.approx(-25.0)  # -50 * 0.5 fixed scale


def test_market_profile_without_position_data_produces_no_factor():
    r = _score(
        [
            _f(
                "market_profile",
                {"reason": "insufficient session depth"},
                scope=AnalysisScope.SESSION,
                status=AnalysisStatus.INSUFFICIENT_DATA,
            )
        ]
    )
    assert all(f.analysis_key != "market_profile" for f in r.factors)


# ======================================================================================
# weighted_v1 aggregation (docs/06 §4)
# ======================================================================================


def _bull_set():
    warm = {"warmup_ok": True, "last_bar_final": True}
    gcmeta = {
        "bars_used": 300,
        "last_bar_final": True,
        "params": {"slow_period": 200, "cross_search_window": 60},
    }
    return [
        _f("rsi", {"rsi": 62.0, "state": "NEUTRAL", "divergence": "NONE"}, meta=warm),
        _f(
            "ema7",
            {"ema": 100.0, "price_vs_ema": 1.0, "price_above": True, "slope_state": "RISING"},
            aux={"atr14": 1.0},
            meta=warm,
        ),
        _f(
            "golden_cross",
            {
                "state": "ABOVE",
                "cross_type": "GOLDEN",
                "recent": True,
                "bars_since_cross": 6,
                "separation": 0.02,
                "provisional": False,
            },
            meta=gcmeta,
        ),
        _f(
            "bollinger",
            {
                "position": "UPPER_HALF",
                "percent_b": 0.65,
                "bandwidth_percentile": 0.5,
                "squeeze": False,
            },
            meta=warm,
        ),
        _f(
            "volume",
            {"volume": 1, "vol_ma": 1, "rvol": 1.5, "spike": False, "trend": "RISING"},
            aux={"price_change_pct_recent": 0.008},
            meta=warm,
        ),
    ]


def test_contributions_sum_to_composite_exactly():
    cr = _score(_bull_set())
    assert math.isclose(
        math.fsum(f.contribution for f in cr.factors), cr.composite_score, abs_tol=1e-9
    )
    assert cr.raw_label is SignalLabel.BULLISH
    assert -100.0 <= cr.composite_score <= 100.0
    assert cr.denom > 0


def test_no_usable_factors_still_yields_a_neutral_result():
    cr = _score([])
    assert cr.composite_score == 0.0
    assert cr.raw_label is SignalLabel.NEUTRAL and cr.effective_label is SignalLabel.NEUTRAL
    assert cr.low_confidence is True
    assert "no usable factors" in cr.warnings
    assert cr.factors == () and cr.denom == 0.0


def test_not_applicable_factor_makes_no_row_and_no_penalty():
    # golden_cross NA on a FUTURE is not in expected_analyses -> confidence not dragged
    fut_factors = [
        _f(
            "rsi",
            {"rsi": 60.0, "state": "NEUTRAL", "divergence": "NONE"},
            meta={"warmup_ok": True, "last_bar_final": True},
        ),
        _f("golden_cross", {"reason": "n/a"}, status=AnalysisStatus.NOT_APPLICABLE),
    ]
    cr = _score(fut_factors, itype=InstrumentType.FUTURE)
    assert all(f.analysis_key != "golden_cross" for f in cr.factors)
    assert any("golden_cross: not applicable" in w for w in cr.warnings)


def test_missing_expected_factor_drags_overall_confidence_down():
    one = _score(
        [
            _f(
                "rsi",
                {"rsi": 80.0, "state": "OVERBOUGHT", "divergence": "NONE"},
                meta={"warmup_ok": True, "last_bar_final": True},
            )
        ]
    )
    full = _score(_bull_set())
    assert one.confidence < full.confidence  # only 1 of ~6 expected present


# ======================================================================================
# labels + clamp (docs/06 §5)
# ======================================================================================


@pytest.mark.parametrize(
    ("composite", "label"),
    [
        (75.0, SignalLabel.STRONG_BULLISH),
        (60.0, SignalLabel.STRONG_BULLISH),
        (40.0, SignalLabel.BULLISH),
        (20.0, SignalLabel.BULLISH),
        (0.0, SignalLabel.NEUTRAL),
        (-20.0, SignalLabel.BEARISH),
        (-40.0, SignalLabel.BEARISH),
        (-60.0, SignalLabel.STRONG_BEARISH),
        (-90.0, SignalLabel.STRONG_BEARISH),
    ],
)
def test_label_bands(composite, label):
    assert label_for(composite, default_config().label_bands) is label


def test_low_confidence_clamps_effective_label_one_band_toward_neutral():
    # a single weak factor -> strongly bullish raw, but tiny confidence -> clamp
    cr = _score(
        [
            _f(
                "golden_cross",
                {
                    "state": "ABOVE",
                    "cross_type": "GOLDEN",
                    "recent": True,
                    "bars_since_cross": 1,
                    "separation": 0.05,
                    "provisional": False,
                },
                meta={
                    "bars_used": 40,
                    "last_bar_final": False,
                    "params": {"slow_period": 200, "cross_search_window": 60},
                },
            )
        ]
    )
    assert cr.confidence < 0.35
    assert cr.low_confidence is True
    assert cr.effective_label is not cr.raw_label
    assert cr.effective_label in (SignalLabel.BULLISH, SignalLabel.NEUTRAL)


# ======================================================================================
# provenance + determinism (docs/06 §8, docs/09 §6)
# ======================================================================================


def test_deterministic_and_versioned():
    a = _score(_bull_set())
    b = _score(_bull_set())
    assert a.composite_score == b.composite_score
    assert a.params_hash == b.params_hash and len(a.params_hash) == 16
    assert a.scoring_version == SCORING_VERSION == "1.2.0"
    assert a.strategy == "weighted_v1"


def test_params_hash_changes_with_config():
    base = _score(_bull_set()).params_hash
    cfg = ScoringConfig(min_confidence=0.5)
    changed = _score(_bull_set(), config=cfg).params_hash
    assert base != changed


def test_explanation_is_templated_header_plus_ordered_clauses():
    cr = _score(_bull_set())
    assert cr.explanation.startswith(
        f"{cr.effective_label.value} ({cr.composite_score:.1f}, confidence "
    )
    # factors are ordered by |contribution| desc in the CompositeResult
    contribs = [abs(f.contribution) for f in cr.factors]
    assert contribs == sorted(contribs, reverse=True)


def test_expected_analyses_by_type():
    assert "golden_cross" in expected_analyses(InstrumentType.INDEX)
    assert "golden_cross" not in expected_analyses(InstrumentType.FUTURE)
    # OPTION is chain-only: open_interest is the sole expected analysis
    assert expected_analyses(InstrumentType.OPTION) == frozenset({"open_interest"})
    for k in ("rsi", "bollinger", "ema7", "volume", "market_profile"):
        assert k not in expected_analyses(InstrumentType.OPTION)
    assert "volume" not in expected_analyses(InstrumentType.INDEX, has_volume=False)


def test_weights_and_denom_stored_for_exact_reconstruction():
    cr = _score(_bull_set())
    assert cr.weights == DEFAULT_WEIGHTS
    assert cr.denom is not None and cr.denom > 0


# ======================================================================================
# ScoringConfig.from_app_settings — app_settings merge (docs/06 §7)
# ======================================================================================


def test_from_app_settings_none_is_defaults():
    cfg = ScoringConfig.from_app_settings(None)
    assert cfg.weights == DEFAULT_WEIGHTS
    assert cfg.min_confidence == 0.35
    assert cfg.hashable() == ScoringConfig().hashable()


def test_from_app_settings_partial_weights_merge_per_key():
    cfg = ScoringConfig.from_app_settings(
        {"scoring.weights": {"rsi": 3.0}, "scoring.min_confidence": 0.5}
    )
    assert cfg.weights["rsi"] == 3.0
    # untouched keys keep their defaults
    assert cfg.weights["golden_cross"] == DEFAULT_WEIGHTS["golden_cross"]
    assert cfg.min_confidence == 0.5
    assert cfg.hashable() != ScoringConfig().hashable()


def test_from_app_settings_per_analysis_params_merge():
    cfg = ScoringConfig.from_app_settings(
        {"scoring.per_analysis_params": {"rsi": {"overbought_penalty": 10.0}}}
    )
    assert cfg.per_analysis_params["rsi"]["overbought_penalty"] == 10.0
    assert cfg.per_analysis_params["rsi"]["divergence_bump"] == 25.0


def test_from_app_settings_ignores_non_numeric_and_empty_bands():
    cfg = ScoringConfig.from_app_settings(
        {
            "scoring.weights": {"rsi": "loud"},
            "scoring.label_bands": [],
            "scoring.min_confidence": None,
        }
    )
    assert cfg.weights["rsi"] == DEFAULT_WEIGHTS["rsi"]
    assert cfg.label_bands == ScoringConfig().label_bands
    assert cfg.min_confidence == 0.35


def test_from_app_settings_scoring_result_reflects_bumped_weight():
    bumped = ScoringConfig.from_app_settings({"scoring.weights": {"rsi": 5.0}})
    cr = _score(_bull_set(), config=bumped)
    assert cr.weights["rsi"] == 5.0
    assert cr.params_hash != _score(_bull_set()).params_hash
