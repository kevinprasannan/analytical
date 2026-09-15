"""One-off recovery backfill (2026-08-31 DB wipe).

Direct fetch->upsert loop that bypasses ``BackfillService`` (which hangs on the
deep-history path). D1 from 2000, M1 from 2022 in 25-day windows, per instrument,
plus a watermark row so the worker's incremental cycle picks up from here.

    cd backend && python scripts/reindex.py                 # 3 indices
    cd backend && python scripts/reindex.py --futures       # + near/next futures
    cd backend && python scripts/reindex.py --only NIFTY-INDEX
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/ on path

from sqlalchemy import select  # noqa: E402
from sqlalchemy.dialects.postgresql import insert as pg_insert

from analytical_core.enums import DataKind, Timeframe, WatermarkStatus  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import models as m  # noqa: E402
from app.db.repositories.market_data import SaMarketDataRepository  # noqa: E402
from app.db.session import session_scope  # noqa: E402
from app.ingestion.budget import RequestBudget  # noqa: E402
from app.providers.factory import build_live_provider  # noqa: E402

D1_START = datetime(2000, 1, 1, tzinfo=UTC)
M1_START = datetime(2022, 1, 3, tzinfo=UTC)  # Upstox M1 floor
M1_WINDOW_DAYS = 25  # Upstox 400s on ~29-31d M1 windows for 2022-era history


def _targets(db, only: list[str] | None, futures: bool, provider: str):
    q = (
        select(
            m.Instrument.id,
            m.Instrument.contract_key,
            m.Instrument.instrument_type,
            m.ProviderInstrumentMap.provider_symbol,
        )
        .join(m.ProviderInstrumentMap, m.ProviderInstrumentMap.instrument_id == m.Instrument.id)
        .where(
            m.ProviderInstrumentMap.provider == provider,
            m.ProviderInstrumentMap.is_active.is_(True),
        )
    )
    if only:
        q = q.where(m.Instrument.contract_key.in_(only))
    else:
        kinds = ["INDEX", "FUTURE"] if futures else ["INDEX"]
        q = q.where(m.Instrument.instrument_type.in_(kinds))
    return list(db.execute(q.order_by(m.Instrument.contract_key)))


def _set_watermark(db, iid: int, tf: Timeframe, provider: str, last_ts: datetime | None) -> None:
    vals = dict(
        instrument_id=iid,
        timeframe=tf,
        data_kind=DataKind.OHLCV,
        provider=provider,
        last_complete_ts=last_ts,
        last_verified_ts=last_ts,
        last_attempt_at=datetime.now(UTC),
        last_status=WatermarkStatus.OK,
    )
    stmt = pg_insert(m.IngestionWatermark).values(**vals)
    upd = ("last_complete_ts", "last_verified_ts", "last_attempt_at", "last_status")
    stmt = stmt.on_conflict_do_update(
        constraint="watermark_identity", set_={k: vals[k] for k in upd}
    )
    db.execute(stmt)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--only", action="append", help="contract_key (repeatable)")
    p.add_argument("--futures", action="store_true", help="also do near/next futures")
    p.add_argument("--d1-only", action="store_true")
    args = p.parse_args(argv)

    s = get_settings()
    provider = s.active_provider
    budget = RequestBudget(max_rps=s.provider_max_rps, per_30min=s.provider_30min_budget)
    prov, close = build_live_provider(s, budget=budget)
    now = datetime.now(UTC)
    try:
        with session_scope(s) as db:
            targets = _targets(db, args.only, args.futures, provider)
        if not targets:
            sys.stderr.write("no targets\n")
            return 2
        print(f"reindex: {len(targets)} instruments, provider={provider}", flush=True)

        for iid, ck, _itype, psym in targets:
            print(f"\n=== {ck} ({psym}) ===", flush=True)

            # --- D1: whole history in one call (adapter chunks internally) ---
            t0 = time.time()
            d1 = prov.fetch_ohlcv(psym, Timeframe.D1, D1_START, now)
            with session_scope(s) as db:
                r = SaMarketDataRepository(db).upsert_ohlcv_bars(
                    instrument_id=iid, timeframe=Timeframe.D1, provider=provider, bars=d1
                )
                last = max((b.ts for b in d1), default=None)
                _set_watermark(db, iid, Timeframe.D1, provider, last)
            print(
                f"  D1  {len(d1):>6} bars  +{r.inserted}/~{r.updated}  {time.time() - t0:5.1f}s",
                flush=True,
            )
            if args.d1_only:
                continue

            # --- M1: 25-day windows from 2022 (or the instrument's start) ---
            m1_from = M1_START
            total = ins = upd = 0
            t0 = time.time()
            cur = m1_from
            last_m1: datetime | None = None
            while cur < now:
                w_end = min(now, cur + timedelta(days=M1_WINDOW_DAYS))
                try:
                    bars = prov.fetch_ohlcv(psym, Timeframe.M1, cur, w_end)
                except Exception as exc:  # noqa: BLE001
                    print(f"  M1  {cur.date()}..{w_end.date()}  ERROR {exc}", flush=True)
                    cur = w_end
                    continue
                if bars:
                    with session_scope(s) as db:
                        rr = SaMarketDataRepository(db).upsert_ohlcv_bars(
                            instrument_id=iid, timeframe=Timeframe.M1, provider=provider, bars=bars
                        )
                    total += len(bars)
                    ins += rr.inserted
                    upd += rr.updated
                    last_m1 = max(last_m1 or bars[0].ts, max(b.ts for b in bars))
                cur = w_end
            with session_scope(s) as db:
                _set_watermark(db, iid, Timeframe.M1, provider, last_m1)
            print(f"  M1  {total:>7} bars  +{ins}/~{upd}  {time.time() - t0:6.1f}s", flush=True)

        print("\nDONE. Now run: python -m app.worker.cli serve --run-now", flush=True)
        return 0
    finally:
        close()


if __name__ == "__main__":
    raise SystemExit(main())
