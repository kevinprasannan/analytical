"""``analytical-backfill`` — historical market-data backfill (Phase 2.5).

    analytical-backfill run --instrument NIFTY-INDEX --instrument NIFTY-FUT-2026-09
    analytical-backfill run --all-active --start 2026-06-01
    analytical-backfill run --all-active --repair-only

Resume-safe and idempotent: re-running continues from ``ingestion_watermarks``
and upserts. No live provider call happens unless ``ANALYTICAL_ACTIVE_PROVIDER``
is a real adapter and a token is configured.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

from sqlalchemy import select

from analytical_core.enums import Timeframe
from app.config import get_settings
from app.db import models as md
from app.db.repositories.market_data import SaMarketDataRepository
from app.db.session import session_scope
from app.ingestion.backfill import BackfillService, BackfillTarget
from app.ingestion.budget import RequestBudget
from app.providers.factory import build_live_provider

_TF_BY_NAME = {tf.value: tf for tf in Timeframe}


def _resolve_targets(
    session, *, provider: str, contract_keys: list[str], all_active: bool
) -> list[BackfillTarget]:
    q = (
        select(
            md.Instrument.id,
            md.Instrument.contract_key,
            md.Instrument.instrument_type,
            md.ProviderInstrumentMap.provider_symbol,
        )
        .join(
            md.ProviderInstrumentMap,
            md.ProviderInstrumentMap.instrument_id == md.Instrument.id,
        )
        .where(
            md.ProviderInstrumentMap.provider == provider,
            md.ProviderInstrumentMap.is_active.is_(True),
            md.Instrument.is_active.is_(True),
        )
    )
    if not all_active:
        q = q.where(md.Instrument.contract_key.in_(contract_keys))
    rows = session.execute(q.order_by(md.Instrument.contract_key)).all()
    found = {r.contract_key for r in rows}
    missing = sorted(set(contract_keys) - found) if not all_active else []
    if missing:
        sys.stderr.write(f"error: unknown / inactive contract_key(s): {', '.join(missing)}\n")
    return [
        BackfillTarget(
            instrument_id=r.id,
            provider_symbol=r.provider_symbol,
            instrument_type=r.instrument_type,
            contract_key=r.contract_key,
        )
        for r in rows
    ]


def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    provider_id = args.provider or settings.active_provider
    timeframes = (
        [_TF_BY_NAME[n] for n in args.timeframes.split(",")]
        if args.timeframes
        else [Timeframe.M1, Timeframe.D1, Timeframe.M5, Timeframe.M15, Timeframe.H1]
    )
    start = datetime.fromisoformat(args.start) if args.start else None
    end = datetime.fromisoformat(args.end) if args.end else None

    budget = RequestBudget(
        max_rps=settings.provider_max_rps, per_30min=settings.provider_30min_budget
    )
    provider, close = build_live_provider(settings, budget=budget)

    try:
        with session_scope(settings) as db:
            targets = _resolve_targets(
                db,
                provider=provider_id,
                contract_keys=args.instrument or [],
                all_active=args.all_active,
            )
            if not targets:
                sys.stderr.write("error: no targets resolved\n")
                return 2
            service = BackfillService(
                provider=provider, repo=SaMarketDataRepository(db), budget=budget, settings=settings
            )
            report = service.run(
                targets,
                timeframes=timeframes,
                start=start,
                end=end,
                repair_only=args.repair_only,
                concurrency=args.concurrency,
            )
    finally:
        close()

    if args.json:
        sys.stdout.write(json.dumps(report.as_dict(), indent=2) + "\n")
    else:
        sys.stdout.write(report.summary_line() + "\n")
        for r in report.instruments:
            flag = "" if r.status.value == "OK" else f"  [{r.status.value}] {r.error or ''}"
            wrote = sum(c.total for c in r.bars.values())
            sys.stdout.write(
                f"  {r.contract_key}: bars={wrote} oi={r.oi.total} gaps={r.m1_gap_count}{flag}\n"
            )
    return 0 if report.ok == len(report.instruments) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="analytical-backfill")
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="backfill / repair historical bars for instruments")
    r.add_argument("--instrument", action="append", metavar="CONTRACT_KEY")
    r.add_argument("--all-active", action="store_true")
    r.add_argument("--provider")
    r.add_argument("--timeframes", help="comma list, e.g. M1,D1,M5")
    r.add_argument("--start", help="ISO datetime (inclusive floor)")
    r.add_argument("--end", help="ISO datetime (default: now)")
    r.add_argument("--repair-only", action="store_true")
    r.add_argument("--concurrency", type=int)
    r.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.cmd == "run":
        if not args.instrument and not args.all_active:
            parser.error("pass --instrument CONTRACT_KEY (repeatable) or --all-active")
        return _run(args)
    return 2  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
