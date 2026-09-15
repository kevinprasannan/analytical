"""Implied volatility — invert Black–Scholes for ``vol`` (docs/05 §11).

Newton–Raphson seeded by the Brenner–Subrahmanyam ATM approximation, with a
bisection fallback. Deterministic: fixed seed, iteration cap and tolerance.
Returns ``None`` when the price is outside the no-arbitrage band or the solver
does not converge.
"""

from __future__ import annotations

import math

from analytical_core.options.black_scholes import _d1_d2, _norm_pdf, bs_price

_VOL_LO, _VOL_HI = 1e-4, 5.0
_MAX_ITER = 100
_PRICE_TOL = 1e-7


def implied_vol(
    price: float,
    spot: float,
    strike: float,
    t: float,
    r: float,
    *,
    is_call: bool,
    q: float = 0.0,
) -> float | None:
    if price <= 0.0 or spot <= 0.0 or strike <= 0.0 or t <= 0.0:
        return None
    df_r, df_q = math.exp(-r * t), math.exp(-q * t)
    lower = max(0.0, (spot * df_q - strike * df_r) if is_call else (strike * df_r - spot * df_q))
    upper = spot * df_q if is_call else strike * df_r
    if price <= lower + 1e-9 or price >= upper - 1e-12:
        return None

    def f(vol: float) -> float:
        return bs_price(spot, strike, t, r, vol, is_call=is_call, q=q) - price

    # Brenner–Subrahmanyam seed
    vol = max(_VOL_LO, min(_VOL_HI, math.sqrt(2.0 * math.pi / t) * price / spot))
    for _ in range(_MAX_ITER):
        diff = f(vol)
        if abs(diff) < _PRICE_TOL:
            return round(vol, 6)
        d1, _ = _d1_d2(spot, strike, t, r, q, vol)
        vega = spot * df_q * _norm_pdf(d1) * math.sqrt(t)  # per 1.0 vol
        if vega < 1e-12:
            break
        step = diff / vega
        vol -= step
        if not (_VOL_LO <= vol <= _VOL_HI):
            break

    lo, hi = _VOL_LO, _VOL_HI
    flo = f(lo)
    if flo * f(hi) > 0.0:
        return None
    for _ in range(_MAX_ITER):
        mid = 0.5 * (lo + hi)
        fm = f(mid)
        if abs(fm) < _PRICE_TOL or (hi - lo) < 1e-8:
            return round(mid, 6)
        if flo * fm < 0.0:
            hi = mid
        else:
            lo, flo = mid, fm
    return round(0.5 * (lo + hi), 6)
