"""Black–Scholes–Merton European option pricing + greeks (docs/05 §11).

Pure, deterministic, standard-library only (``math.erf`` for the normal CDF).
Continuous dividend/carry yield ``q`` (default 0 for index options). Conventions
match what retail chains display:

* ``theta`` is **per calendar day** (annual θ / 365)
* ``vega`` and ``rho`` are **per 1 percentage point** of vol / rate (annual / 100)
"""

from __future__ import annotations

import math
from dataclasses import dataclass

_SQRT_2PI = math.sqrt(2.0 * math.pi)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / _SQRT_2PI


def _d1_d2(
    spot: float, strike: float, t: float, r: float, q: float, vol: float
) -> tuple[float, float]:
    v = vol * math.sqrt(t)
    d1 = (math.log(spot / strike) + (r - q + 0.5 * vol * vol) * t) / v
    return d1, d1 - v


def bs_price(
    spot: float, strike: float, t: float, r: float, vol: float, *, is_call: bool, q: float = 0.0
) -> float:
    """Undiscounted-forward Black–Scholes price. ``t`` in years."""
    intrinsic = max(0.0, (spot - strike) if is_call else (strike - spot))
    if t <= 0.0 or vol <= 0.0 or spot <= 0.0 or strike <= 0.0:
        return intrinsic
    d1, d2 = _d1_d2(spot, strike, t, r, q, vol)
    df_r, df_q = math.exp(-r * t), math.exp(-q * t)
    if is_call:
        return spot * df_q * _norm_cdf(d1) - strike * df_r * _norm_cdf(d2)
    return strike * df_r * _norm_cdf(-d2) - spot * df_q * _norm_cdf(-d1)


@dataclass(frozen=True, slots=True)
class Greeks:
    delta: float
    gamma: float
    theta: float  # per calendar day
    vega: float  # per 1% vol
    rho: float  # per 1% rate


def bs_greeks(
    spot: float, strike: float, t: float, r: float, vol: float, *, is_call: bool, q: float = 0.0
) -> Greeks:
    if t <= 0.0 or vol <= 0.0 or spot <= 0.0 or strike <= 0.0:
        # at/after expiry: delta is a step, the rest vanish
        itm = (spot > strike) if is_call else (spot < strike)
        return Greeks((1.0 if is_call else -1.0) if itm else 0.0, 0.0, 0.0, 0.0, 0.0)
    d1, d2 = _d1_d2(spot, strike, t, r, q, vol)
    df_r, df_q = math.exp(-r * t), math.exp(-q * t)
    pdf = _norm_pdf(d1)
    sqrt_t = math.sqrt(t)

    gamma = df_q * pdf / (spot * vol * sqrt_t)
    vega = spot * df_q * pdf * sqrt_t / 100.0
    if is_call:
        delta = df_q * _norm_cdf(d1)
        theta_yr = (
            -spot * df_q * pdf * vol / (2.0 * sqrt_t)
            - r * strike * df_r * _norm_cdf(d2)
            + q * spot * df_q * _norm_cdf(d1)
        )
        rho = strike * t * df_r * _norm_cdf(d2) / 100.0
    else:
        delta = -df_q * _norm_cdf(-d1)
        theta_yr = (
            -spot * df_q * pdf * vol / (2.0 * sqrt_t)
            + r * strike * df_r * _norm_cdf(-d2)
            - q * spot * df_q * _norm_cdf(-d1)
        )
        rho = -strike * t * df_r * _norm_cdf(-d2) / 100.0
    return Greeks(delta, gamma, theta_yr / 365.0, vega, rho)
