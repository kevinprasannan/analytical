"""Idempotent seed data (docs/10 Phase 1).

  * the single ``owner`` user
  * ``market_calendar`` for the current + next calendar year
    (Phase-1 approximation: Mon-Fri = trading day, 09:15-15:30 IST, segment FO;
    the NSE holiday list is layered in later via ``refresh-calendar``)
  * ``app_settings`` from the confirmed Phase-0 defaults (docs/02 §8.1)

Run:  python -m app.db.seed        (or the ``analytical-seed`` console script)
"""

from __future__ import annotations

import sys
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import models as m
from app.db.session import session_scope

APP_SETTINGS_DEFAULTS: dict[str, object] = {
    "cycle_interval_seconds": 180,
    "finalize_grace_seconds": 90,
    "option_selection.underlyings": ["NIFTY", "BANKNIFTY", "SENSEX"],
    "option_selection.strike_window": 15,  # ATM ± 15 strikes
    "option_selection.max_expiries": 2,  # nearest expiry (weekly where it exists) + one more
    "option_selection.rebuild_trigger": 8,
    "option_selection.strike_step.NIFTY": 50,
    "option_selection.strike_step.BANKNIFTY": 100,
    "option_selection.strike_step.SENSEX": 100,
    "scoring.min_confidence": 0.35,
    "scoring.weights": {
        "golden_cross": 1.5,
        "open_interest": 1.25,
        "ema7": 1.0,
        "bollinger": 1.0,
        "rsi": 1.0,
        "market_profile": 1.0,
        "volume": 0.75,
    },
    "scoring.label_bands": [
        [60, "STRONG_BULLISH"],
        [20, "BULLISH"],
        [-20, "NEUTRAL"],
        [-60, "BEARISH"],
        [-1000, "STRONG_BEARISH"],
    ],
    "retention.ohlcv_m5_days": 180,
    "retention.ohlcv_m15_h1_days": 400,
    "retention.results_scores_days": 400,
    "options.risk_free_rate": 0.065,
    "options.dividend_yield": 0.0,
}


def seed_users(db) -> None:
    if db.execute(select(m.User).where(m.User.username == "owner")).scalar_one_or_none() is None:
        db.add(m.User(username="owner"))


def seed_app_settings(db) -> None:
    for key, value in APP_SETTINGS_DEFAULTS.items():
        stmt = pg_insert(m.AppSetting).values(key=key, value=value)
        stmt = stmt.on_conflict_do_nothing(index_elements=["key"])
        db.execute(stmt)


def seed_calendar(db, *, years_ahead: int = 1) -> int:
    today = date.today()
    start = date(today.year, 1, 1)
    end = date(today.year + years_ahead, 12, 31)
    rows = 0
    d = start
    while d <= end:
        is_trading = d.weekday() < 5  # Mon-Fri (Phase-1 approximation)
        stmt = pg_insert(m.MarketCalendar).values(
            exchange="NSE",
            segment="FO",
            calendar_date=d,
            is_trading_day=is_trading,
            session_type="NORMAL",
        )
        stmt = stmt.on_conflict_do_nothing(index_elements=["exchange", "segment", "calendar_date"])
        db.execute(stmt)
        rows += 1
        d += timedelta(days=1)
    return rows


def run_seed() -> None:
    with session_scope() as db:
        seed_users(db)
        seed_app_settings(db)
        n = seed_calendar(db)
    sys.stdout.write(
        f"seed: owner user + {len(APP_SETTINGS_DEFAULTS)} app_settings + {n} calendar days\n"
    )


def main(argv: list[str] | None = None) -> int:  # noqa: ARG001
    run_seed()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
