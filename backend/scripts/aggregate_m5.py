"""Recovery aggregation: build M5/M15/H1 from the full stored M1 history.

``reindex.py`` writes only M1 + D1; the worker only aggregates the incremental
window. This backfills the aggregate timeframes for the tracked indices so
Market Profile and the intraday analyses have data.

    cd backend && python scripts/aggregate_m5.py            # tracked indices
    cd backend && python scripts/aggregate_m5.py --only NIFTY-INDEX
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402

from analytical_core.enums import DataKind, Timeframe, WatermarkStatus  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import models as m  # noqa: E402
from app.db.repositories.market_data import SaMarketDataRepository  # noqa: E402
from app.db.session import session_scope  # noqa: E402
from app.ingestion.aggregation import aggregate_m1  # noqa: E402
from app.providers.base import OHLCVBar  # noqa: E402

AGG = (Timeframe.M5, Timeframe.M15, Timeframe.H1)


def _set_wm(db, iid, tf, provider, last_ts):
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
    keys = ("last_complete_ts", "last_verified_ts", "last_attempt_at", "last_status")
    db.execute(
        stmt.on_conflict_do_update(
            constraint="watermark_identity", set_={k: vals[k] for k in keys}
        )
    )


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--only", action="append")
    args = p.parse_args(argv)
    s = get_settings()
    provider = s.active_provider
    now = datetime.now(UTC)

    with session_scope(s) as db:
        q = select(m.Instrument.id, m.Instrument.contract_key).where(
            m.Instrument.instrument_type == "INDEX"
        )
        if args.only:
            q = q.where(m.Instrument.contract_key.in_(args.only))
        else:
            q = q.where(m.Instrument.is_tracked.is_(True))
        targets = list(db.execute(q.order_by(m.Instrument.contract_key)))

    for iid, ck in targets:
        print(f"\n=== {ck} ===", flush=True)
        with session_scope(s) as db:
            rows = db.execute(
                select(
                    m.OhlcvBar.ts,
                    m.OhlcvBar.open,
                    m.OhlcvBar.high,
                    m.OhlcvBar.low,
                    m.OhlcvBar.close,
                    m.OhlcvBar.volume,
                    m.OhlcvBar.is_final,
                )
                .where(
                    m.OhlcvBar.instrument_id == iid,
                    m.OhlcvBar.timeframe == Timeframe.M1,
                    m.OhlcvBar.provider == provider,
                )
                .order_by(m.OhlcvBar.ts)
            ).all()
        m1 = [
            OHLCVBar(
                ts=r.ts,
                open=float(r.open),
                high=float(r.high),
                low=float(r.low),
                close=float(r.close),
                volume=int(r.volume),
                is_final=bool(r.is_final),
                source="reindex",
                open_interest=None,
            )
            for r in rows
        ]
        print(f"  loaded {len(m1)} M1 bars", flush=True)
        for tf in AGG:
            t0 = time.time()
            agg = aggregate_m1(m1, tf, now=now)
            if not agg.bars:
                print(f"  {tf.value}: 0", flush=True)
                continue
            with session_scope(s) as db:
                rr = SaMarketDataRepository(db).upsert_ohlcv_bars(
                    instrument_id=iid, timeframe=tf, provider=provider, bars=agg.bars
                )
                last = max((b.ts for b in agg.bars if b.is_final), default=None)
                _set_wm(db, iid, tf, provider, last)
            print(
                f"  {tf.value}: {len(agg.bars):>6} bars  +{rr.inserted}/~{rr.updated}  "
                f"{time.time() - t0:5.1f}s",
                flush=True,
            )
    print("\nDONE. Now run: python -m app.worker.cli run-cycle", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
