"""Effective-config assembly + validation for ``GET/PATCH /config`` (docs/07 §4.7).

``app_settings`` is a flat key/value store (dotted keys). The effective config is
``APP_SETTINGS_DEFAULTS`` with any stored override merged on top. A ``PATCH`` is a
partial map of the **writable** keys; each value is range/shape checked before it
reaches ``app_settings``. Changes ``effective_from`` the next cycle — nothing here
mutates a running cycle.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from analytical_core.params import canonical_json, params_hash
from app.db.seed import APP_SETTINGS_DEFAULTS

_LABELS = {"STRONG_BEARISH", "BEARISH", "NEUTRAL", "BULLISH", "STRONG_BULLISH"}
_ANALYSIS_KEYS = {
    "rsi",
    "bollinger",
    "ema7",
    "golden_cross",
    "volume",
    "open_interest",
    "market_profile",
}

#: Market Profile knobs surfaced for editing (docs/05 §10.1). Consumed by the
#: engine once the app_settings merge lands; stored + validated here now.
_MP_DEFAULTS: dict[str, Any] = {
    "market_profile.tpo_minutes": 30,
    "market_profile.ib_periods": 2,
    "market_profile.value_area_pct": 0.70,
    "market_profile.va_expansion": "PAIR",
    "market_profile.partial_period_policy": "KEEP",
    "market_profile.min_periods_for_result": 3,
    "market_profile.min_bins": 10,
}

DEFAULTS: dict[str, Any] = {**APP_SETTINGS_DEFAULTS, **_MP_DEFAULTS}


class ConfigError(ValueError):
    """A PATCH value is not a known key or fails validation."""


def _check(key: str, value: Any) -> Any:
    if key == "cycle_interval_seconds":
        if not (isinstance(value, int) and 30 <= value <= 3600):
            raise ConfigError("cycle_interval_seconds must be an int in [30, 3600]")
    elif key == "finalize_grace_seconds":
        if not (isinstance(value, int) and 0 <= value <= 600):
            raise ConfigError("finalize_grace_seconds must be an int in [0, 600]")
    elif key == "scoring.min_confidence":
        if not (isinstance(value, int | float) and 0.0 <= value <= 1.0):
            raise ConfigError("scoring.min_confidence must be in [0, 1]")
    elif key == "scoring.weights":
        if not isinstance(value, Mapping) or not value:
            raise ConfigError("scoring.weights must be a non-empty object")
        for k, v in value.items():
            if k not in _ANALYSIS_KEYS or not isinstance(v, int | float) or v < 0:
                raise ConfigError(f"scoring.weights[{k!r}] invalid")
    elif key == "scoring.label_bands":
        if not isinstance(value, list) or len(value) != 5:
            raise ConfigError("scoring.label_bands must be a list of 5 [threshold, label]")
        prev = None
        for pair in value:
            if (
                not isinstance(pair, list | tuple)
                or len(pair) != 2
                or not isinstance(pair[0], int | float)
                or pair[1] not in _LABELS
            ):
                raise ConfigError("scoring.label_bands entries must be [number, SIGNAL_LABEL]")
            if prev is not None and pair[0] >= prev:
                raise ConfigError("scoring.label_bands thresholds must be strictly decreasing")
            prev = pair[0]
    elif key == "option_selection.underlyings":
        if not isinstance(value, list) or not all(isinstance(x, str) and x.strip() for x in value):
            raise ConfigError("option_selection.underlyings must be a list of symbols")
    elif key.startswith("option_selection.strike_step."):
        if not (isinstance(value, int | float) and value > 0):
            raise ConfigError(f"{key} must be a positive number")
    elif key.startswith("option_selection."):
        if key.endswith((".strike_window", ".max_expiries", ".rebuild_trigger")) and not (
            isinstance(value, int) and value > 0
        ):
            raise ConfigError(f"{key} must be a positive int")
    elif key.startswith("retention."):
        if not (isinstance(value, int) and value > 0):
            raise ConfigError(f"{key} must be a positive int (days)")
    elif key == "market_profile.tpo_minutes":
        if not (isinstance(value, int) and 5 <= value <= 240):
            raise ConfigError("market_profile.tpo_minutes must be in [5, 240]")
    elif key == "market_profile.ib_periods":
        if not (isinstance(value, int) and 1 <= value <= 12):
            raise ConfigError("market_profile.ib_periods must be in [1, 12]")
    elif key == "market_profile.value_area_pct":
        if not (isinstance(value, int | float) and 0.3 <= value <= 0.95):
            raise ConfigError("market_profile.value_area_pct must be in [0.3, 0.95]")
    elif key == "market_profile.va_expansion":
        if value not in ("PAIR", "SINGLE"):
            raise ConfigError("market_profile.va_expansion must be PAIR or SINGLE")
    elif key == "market_profile.partial_period_policy":
        if value not in ("KEEP", "MERGE_PREV", "DROP"):
            raise ConfigError("market_profile.partial_period_policy invalid")
    elif key in ("market_profile.min_periods_for_result", "market_profile.min_bins"):
        if not (isinstance(value, int) and value >= 1):
            raise ConfigError(f"{key} must be a positive int")
    elif key == "options.risk_free_rate":
        if not (isinstance(value, int | float) and 0.0 <= value <= 0.5):
            raise ConfigError("options.risk_free_rate must be in [0, 0.5]")
    elif key == "options.dividend_yield":
        if not (isinstance(value, int | float) and 0.0 <= value <= 0.5):
            raise ConfigError("options.dividend_yield must be in [0, 0.5]")
    elif key not in DEFAULTS:
        raise ConfigError(f"unknown config key: {key!r}")
    return value


def validate_patch(patch: Mapping[str, Any]) -> dict[str, Any]:
    if not patch:
        raise ConfigError("empty patch")
    out: dict[str, Any] = {}
    for k, v in patch.items():
        if k not in DEFAULTS and not (
            k.startswith(("option_selection.", "retention.", "market_profile."))
        ):
            raise ConfigError(f"unknown config key: {k!r}")
        out[k] = _check(k, v)
    return out


def effective(stored: Mapping[str, Any]) -> dict[str, Any]:
    """Defaults with stored overrides merged on top (stored wins)."""
    return {**DEFAULTS, **{k: v for k, v in stored.items() if k in DEFAULTS or "." in k}}


def sectioned(flat: Mapping[str, Any]) -> dict[str, Any]:
    sections: dict[str, Any] = {
        "cadence": {},
        "scoring": {},
        "option_selection": {},
        "retention": {},
        "market_profile": {},
        "options": {},
    }
    for k, v in flat.items():
        if k in ("cycle_interval_seconds", "finalize_grace_seconds"):
            sections["cadence"][k] = v
        elif k.startswith("scoring."):
            sections["scoring"][k.split(".", 1)[1]] = v
        elif k.startswith("option_selection."):
            sections["option_selection"][k.split(".", 1)[1]] = v
        elif k.startswith("retention."):
            sections["retention"][k.split(".", 1)[1]] = v
        elif k.startswith("market_profile."):
            sections["market_profile"][k.split(".", 1)[1]] = v
        elif k.startswith("options."):
            sections["options"][k.split(".", 1)[1]] = v
    return sections


def config_params_hash(flat: Mapping[str, Any]) -> str:
    return params_hash({"config": canonical_json(dict(sorted(flat.items())))})


def json_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "AnalyticalConfig",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "cycle_interval_seconds": {"type": "integer", "minimum": 30, "maximum": 3600},
            "finalize_grace_seconds": {"type": "integer", "minimum": 0, "maximum": 600},
            "scoring.min_confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "scoring.weights": {
                "type": "object",
                "additionalProperties": {"type": "number", "minimum": 0},
                "propertyNames": {"enum": sorted(_ANALYSIS_KEYS)},
            },
            "scoring.label_bands": {
                "type": "array",
                "minItems": 5,
                "maxItems": 5,
                "items": {
                    "type": "array",
                    "prefixItems": [
                        {"type": "number"},
                        {"enum": sorted(_LABELS)},
                    ],
                },
            },
            "option_selection.underlyings": {"type": "array", "items": {"type": "string"}},
            "option_selection.strike_window": {"type": "integer", "minimum": 1},
            "option_selection.max_expiries": {"type": "integer", "minimum": 1},
            "option_selection.rebuild_trigger": {"type": "integer", "minimum": 1},
            "retention.ohlcv_m5_days": {"type": "integer", "minimum": 1},
            "retention.ohlcv_m15_h1_days": {"type": "integer", "minimum": 1},
            "retention.results_scores_days": {"type": "integer", "minimum": 1},
            "market_profile.tpo_minutes": {"type": "integer", "minimum": 5, "maximum": 240},
            "market_profile.ib_periods": {"type": "integer", "minimum": 1, "maximum": 12},
            "market_profile.value_area_pct": {"type": "number", "minimum": 0.3, "maximum": 0.95},
            "market_profile.va_expansion": {"enum": ["PAIR", "SINGLE"]},
            "market_profile.partial_period_policy": {"enum": ["KEEP", "MERGE_PREV", "DROP"]},
            "market_profile.min_periods_for_result": {"type": "integer", "minimum": 1},
            "market_profile.min_bins": {"type": "integer", "minimum": 1},
            "options.risk_free_rate": {"type": "number", "minimum": 0, "maximum": 0.5},
            "options.dividend_yield": {"type": "number", "minimum": 0, "maximum": 0.5},
        },
    }
