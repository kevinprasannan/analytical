"""Config-driven tracked-universe selection (docs/04 §2.3).

Given a provider instrument master + the ``option_selection.*`` config + a spot
price per underlying, decide **which contracts become ``is_tracked``**:

* each configured underlying's INDEX,
* its two nearest monthly FUTURE expiries (near + next),
* for the next ``max_expiries`` option expiries: CE + PE within
  ``ATM ± strike_window`` strikes.

Pure. Re-running with a later ``today`` rolls expiries / re-centres strikes; the
caller then tracks the new set and untracks the rest. Adding another index is a
change to ``option_selection.underlyings`` — no code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from analytical_core.enums import ExpiryKind, InstrumentType
from app.instruments.contract_key import build_contract_key, normalise_underlying
from app.providers.base import InstrumentRecord

#: default provider keys for the indices we know; extend as underlyings are added.
INDEX_PROVIDER_KEY = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "FINNIFTY": "NSE_INDEX|Nifty Fin Service",
    "MIDCPNIFTY": "NSE_INDEX|NIFTY MID SELECT",
    "SENSEX": "BSE_INDEX|SENSEX",
    "BANKEX": "BSE_INDEX|BANKEX",
}


@dataclass(frozen=True, slots=True)
class UniverseConfig:
    underlyings: tuple[str, ...] = ("NIFTY",)
    strike_window: int = 15
    max_expiries: int = 5
    strike_step: dict[str, float] = field(default_factory=lambda: {"NIFTY": 50.0})
    monthly_futures: int = 2  # near + next

    @classmethod
    def from_app_settings(cls, settings: dict) -> UniverseConfig:
        s = settings or {}
        steps = {
            k.split(".")[-1].upper(): float(v)
            for k, v in s.items()
            if k.startswith("option_selection.strike_step.")
        }
        return cls(
            underlyings=tuple(
                normalise_underlying(u) for u in s.get("option_selection.underlyings", ["NIFTY"])
            ),
            strike_window=int(s.get("option_selection.strike_window", 15)),
            max_expiries=int(s.get("option_selection.max_expiries", 5)),
            strike_step=steps or {"NIFTY": 50.0},
        )


@dataclass(frozen=True, slots=True)
class UniversePlan:
    tracked_keys: frozenset[str]
    records_to_sync: tuple[InstrumentRecord, ...]  # the master subset for those keys
    per_underlying: dict[
        str, dict
    ]  # {sym: {future_expiries, option_expiries, strike_lo, strike_hi}}


def _key_of(rec: InstrumentRecord) -> str | None:
    try:
        kind = (
            ExpiryKind.WEEKLY
            if rec.weekly
            else (ExpiryKind.MONTHLY if rec.expiry_date is not None else None)
        )
        return build_contract_key(
            instrument_type=rec.instrument_type,
            underlying_symbol=rec.underlying_symbol or "",
            expiry_date=rec.expiry_date,
            expiry_kind=kind,
            strike_price=rec.strike_price,
            option_type=rec.option_type,
        )
    except Exception:
        return None


def plan_universe(
    records: list[InstrumentRecord],
    cfg: UniverseConfig,
    *,
    spot_by_symbol: dict[str, float],
    today: date,
) -> UniversePlan:
    wanted = {normalise_underlying(u) for u in cfg.underlyings}
    tracked: set[str] = set()
    subset: list[InstrumentRecord] = []
    meta: dict[str, dict] = {}

    # index provider keys we must keep even if the master row lacks a clean symbol
    index_keys = {INDEX_PROVIDER_KEY.get(u) for u in wanted if u in INDEX_PROVIDER_KEY}

    fut_by_u: dict[str, list[InstrumentRecord]] = {}
    opt_by_u: dict[str, list[InstrumentRecord]] = {}
    for rec in records:
        if rec.instrument_type is InstrumentType.INDEX:
            if rec.provider_symbol in index_keys:
                u = next(k for k, v in INDEX_PROVIDER_KEY.items() if v == rec.provider_symbol)
                key = build_contract_key(instrument_type=InstrumentType.INDEX, underlying_symbol=u)
                tracked.add(key)
                subset.append(rec)
            continue
        u = normalise_underlying(rec.underlying_symbol or "")
        if u not in wanted or rec.expiry_date is None:
            continue
        if rec.instrument_type is InstrumentType.FUTURE:
            fut_by_u.setdefault(u, []).append(rec)
        elif rec.instrument_type is InstrumentType.OPTION and rec.strike_price is not None:
            opt_by_u.setdefault(u, []).append(rec)

    for u in wanted:
        step = cfg.strike_step.get(u, 50.0)
        spot = spot_by_symbol.get(u)
        m: dict = {
            "future_expiries": [],
            "option_expiries": [],
            "strike_lo": None,
            "strike_hi": None,
        }

        futs = sorted({r.expiry_date for r in fut_by_u.get(u, []) if r.expiry_date > today})[
            : cfg.monthly_futures
        ]
        m["future_expiries"] = [d.isoformat() for d in futs]
        for rec in fut_by_u.get(u, []):
            if rec.expiry_date in futs:
                k = _key_of(rec)
                if k:
                    tracked.add(k)
                    subset.append(rec)

        exps = sorted({r.expiry_date for r in opt_by_u.get(u, []) if r.expiry_date > today})[
            : cfg.max_expiries
        ]
        m["option_expiries"] = [d.isoformat() for d in exps]
        if spot is not None and exps:
            atm = round(spot / step) * step
            lo = atm - cfg.strike_window * step
            hi = atm + cfg.strike_window * step
            m["strike_lo"], m["strike_hi"] = lo, hi
            for rec in opt_by_u.get(u, []):
                if rec.expiry_date in exps and lo <= float(rec.strike_price) <= hi:
                    k = _key_of(rec)
                    if k:
                        tracked.add(k)
                        subset.append(rec)
        meta[u] = m

    # de-dup subset by provider_symbol, preserve order
    seen: set[str] = set()
    uniq = []
    for r in subset:
        if r.provider_symbol not in seen:
            seen.add(r.provider_symbol)
            uniq.append(r)
    return UniversePlan(frozenset(tracked), tuple(uniq), meta)
