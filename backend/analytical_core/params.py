"""Parameter provenance helpers (docs/05 §12, docs/04 §5, resolves review M19).

Every analysis / scoring result carries ``params_id`` (a stable human label for
the parameter set) and ``params_hash`` (a content hash of the *effective*
parameter object). Re-running the same engine version with the same effective
parameters must reproduce an identical hash; changing any parameter must change
it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

_HASH_PREFIX_LEN = 16  # first 16 hex chars of sha256 (docs/04 §5)


def canonical_json(obj: Any) -> str:
    """Deterministic JSON: sorted keys, no whitespace, stable float/`None` handling.

    Rejects values JSON cannot represent deterministically (sets, bytes, custom
    objects) so a caller cannot silently produce an unstable hash.
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def params_hash(effective_params: Mapping[str, Any]) -> str:
    """Content hash of an effective parameter mapping.

    ``effective_params`` is the fully-resolved parameter object actually used by
    the engine call (defaults already merged), not a partial override.
    """
    if not isinstance(effective_params, Mapping):
        raise TypeError("effective_params must be a mapping")
    digest = hashlib.sha256(canonical_json(dict(effective_params)).encode("ascii")).hexdigest()
    return digest[:_HASH_PREFIX_LEN]


def params_id(analysis_key: str, version: str = "v1") -> str:
    """Stable human-facing identifier for a parameter set, e.g. ``rsi.v1``."""
    if not analysis_key:
        raise ValueError("analysis_key is required")
    return f"{analysis_key}.{version}"


#: Default effective parameters per analysis (docs/05 §4–§9). The orchestrator
#: merges any operator override from ``app_settings`` on top of these before the
#: engine call; the merged mapping is what ``params_hash`` is taken over.
DEFAULT_PARAMS: Mapping[str, Mapping[str, Any]] = {
    "rsi": {"period": 14, "source": "close", "div_lookback": 14, "div_min_rsi_delta": 1.0},
    "bollinger": {
        "period": 20,
        "num_std": 2.0,
        "source": "close",
        "std_ddof": 0,
        "squeeze_lookback": 120,
    },
    "ema7": {
        "period": 7,
        "source": "close",
        "seed": "sma",
        "slope_lookback": 3,
        "slope_flat_eps_pct": 0.0002,
        "atr_period": 14,
    },
    "golden_cross": {
        "fast_period": 50,
        "slow_period": 200,
        "ma_type": "SMA",
        "source": "close",
        "cross_search_window": 60,
        "recent_window": 10,
        "enable_for_dated": False,
    },
    "volume": {
        "ma_period": 20,
        "spike_mult": 2.0,
        "rvol_lookback": 20,
        "trend_flat_eps_pct": 0.05,
    },
    "open_interest": {
        "change_lookback": 1,
        "price_epsilon_pct": 0.0005,
        "oi_epsilon_pct": 0.001,
        "oi_eps_abs": 0,
    },
    "order_block": {
        "swing_lookback": 5,
        "atr_period": 14,
        "impulse_min_atr": 1.0,
        "bos_search_window": 30,
        "max_ob_age_bars": 60,
        "zone": "range",  # "range" (high-low) | "body" (open-close)
        "mitigation": "touch",  # "touch" | "close"
    },
    "candles": {
        "scan_bars": 5,  # how many recent bars to scan for a pattern
        "trend_lookback": 5,  # bars before the pattern used for the trend context
        "doji_body_pct": 0.1,  # body <= this x range -> doji
        "marubozu_body_pct": 0.9,  # body >= this x range -> marubozu
        "wick_body_mult": 2.0,  # dominant wick must be >= this x body (hammer/star)
        "opp_wick_pct": 0.15,  # the other wick must be <= this x range
        "star_body_pct": 0.35,  # "small body" cut-off (stars, hammers)
        # a candidate bar preceded by >= this many identical zero-range bars (a
        # frozen/carried-forward quote, e.g. a provider feed snapshot near the
        # session close) is not scored as a pattern — see _frozen_tape_artifact.
        "frozen_run_min_bars": 2,
    },
    # Market Profile carries its full config in MarketProfileConfig (docs/05
    # §10.1); this stub keeps params_id / provenance helpers consistent.
    "market_profile": {
        "tpo_minutes": 30,
        "ib_periods": 2,
        "value_area_pct": 0.70,
        "va_expansion": "PAIR",
        "source_timeframe": "M5",
        "min_periods_for_result": 3,
        "min_bins": 10,
    },
}


def effective_params(
    analysis_key: str, overrides: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Defaults for ``analysis_key`` with ``overrides`` merged on top (shallow)."""
    base = dict(DEFAULT_PARAMS[analysis_key])
    if overrides:
        for k, v in overrides.items():
            if k not in base:
                raise KeyError(f"unknown {analysis_key} parameter: {k!r}")
            base[k] = v
    return base
