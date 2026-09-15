"""Config assembly + validation (pure) — docs/07 §4.7."""

from __future__ import annotations

import pytest

from app.api import config_model as cm


def test_effective_merges_stored_over_defaults():
    eff = cm.effective({"scoring.min_confidence": 0.5, "unknown.key": 1})
    assert eff["scoring.min_confidence"] == 0.5
    assert eff["cycle_interval_seconds"] == cm.DEFAULTS["cycle_interval_seconds"]
    assert "unknown.key" in eff  # dotted keys pass through (forward-compat)


def test_sectioned_groups_by_prefix():
    s = cm.sectioned(cm.effective({}))
    assert set(s) == {
        "cadence",
        "scoring",
        "option_selection",
        "retention",
        "market_profile",
        "options",
    }
    assert "min_confidence" in s["scoring"]
    assert "tpo_minutes" in s["market_profile"]
    assert "risk_free_rate" in s["options"]


def test_config_params_hash_stable_and_sensitive():
    a = cm.config_params_hash(cm.effective({}))
    b = cm.config_params_hash(cm.effective({}))
    c = cm.config_params_hash(cm.effective({"scoring.min_confidence": 0.4}))
    assert a == b and len(a) == 16 and a != c


@pytest.mark.parametrize(
    "patch",
    [
        {},
        {"scoring.min_confidence": 5},
        {"scoring.min_confidence": -0.1},
        {"cycle_interval_seconds": 5},
        {"scoring.weights": {"nope": 1.0}},
        {
            "scoring.label_bands": [[20, "BULLISH"], [60, "STRONG_BULLISH"]]
        },  # not decreasing / wrong len
        {"market_profile.va_expansion": "WEIRD"},
        {"totally.unknown": 1},
    ],
)
def test_validate_patch_rejects_bad_input(patch):
    with pytest.raises(cm.ConfigError):
        cm.validate_patch(patch)


def test_validate_patch_accepts_good_input():
    clean = cm.validate_patch(
        {
            "scoring.min_confidence": 0.4,
            "scoring.weights": {"rsi": 2.0, "volume": 0.5},
            "market_profile.tpo_minutes": 60,
            "retention.ohlcv_m5_days": 90,
        }
    )
    assert clean["scoring.min_confidence"] == 0.4
    assert clean["market_profile.tpo_minutes"] == 60


def test_json_schema_shape():
    sch = cm.json_schema()
    assert sch["type"] == "object" and "scoring.weights" in sch["properties"]
