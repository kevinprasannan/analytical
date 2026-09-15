"""Persistence for backfilled / ingested market data (Phase 2.5).

Standalone — like ``instrument_registry``, not part of the worker ``Repositories``
bundle (the live cycle wires this in 2.6).

Idempotent upserts keyed by the natural identity of docs/03 §5.2:
``ohlcv_bars (instrument_id, timeframe, ts, provider)`` and
``open_interest (instrument_id, timeframe, ts, provider)``. A repeat of the same
bar refreshes ``o/h/l/c/volume/is_final`` (and ``ingested_at``); a
``false → true`` ``is_final`` transition is a normal update (docs/09 §2.8).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Protocol

from sqlalchemy import func, literal_column, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from analytical_core.enums import DataKind, Timeframe, WatermarkStatus
from app.db import models as m
from app.providers.base import OHLCVBar

# `xmax = 0` on a row returned by INSERT ... ON CONFLICT DO UPDATE means the row
# was newly inserted (no prior tuple version); non-zero => it was an update.
_INSERTED = (literal_column("xmax") == 0).label("inserted")
_UPSERT_CHUNK = 1000  # rows per INSERT ... ON CONFLICT statement


@dataclass(frozen=True, slots=True)
class OIRow:
    ts: datetime
    oi: int
    is_final: bool
    provider_oi_change: int | None = None


@dataclass(frozen=True, slots=True)
class UpsertCounts:
    inserted: int = 0
    updated: int = 0

    @property
    def total(self) -> int:
        return self.inserted + self.updated

    def __add__(self, other: UpsertCounts) -> UpsertCounts:
        return UpsertCounts(self.inserted + other.inserted, self.updated + other.updated)


@dataclass(frozen=True, slots=True)
class Watermark:
    last_complete_ts: datetime | None
    last_verified_ts: datetime | None
    last_status: WatermarkStatus | None


@dataclass(frozen=True, slots=True)
class WatermarkWrite:
    instrument_id: int
    timeframe: Timeframe
    data_kind: DataKind
    provider: str
    last_complete_ts: datetime | None
    last_attempt_at: datetime
    last_status: WatermarkStatus
    last_verified_ts: datetime | None = None
    detail: dict = field(default_factory=dict)


class MarketDataRepository(Protocol):
    def upsert_ohlcv_bars(
        self, *, instrument_id: int, timeframe: Timeframe, provider: str, bars: Sequence[OHLCVBar]
    ) -> UpsertCounts: ...
    def upsert_open_interest(
        self, *, instrument_id: int, timeframe: Timeframe, provider: str, rows: Sequence[OIRow]
    ) -> UpsertCounts: ...
    def get_watermark(
        self, *, instrument_id: int, timeframe: Timeframe, data_kind: DataKind, provider: str
    ) -> Watermark | None: ...
    def upsert_watermark(self, wm: WatermarkWrite) -> None: ...
    def bar_open_timestamps(
        self,
        *,
        instrument_id: int,
        timeframe: Timeframe,
        provider: str,
        start: datetime,
        end: datetime,
    ) -> list[datetime]: ...
    def count_bars(self, *, instrument_id: int, timeframe: Timeframe, provider: str) -> int: ...
    def load_bars(
        self, *, instrument_id: int, timeframe: Timeframe, provider: str, limit: int
    ) -> list[OHLCVBar]: ...
    def load_oi(
        self, *, instrument_id: int, timeframe: Timeframe, provider: str, limit: int
    ) -> list[OIRow]: ...


# ======================================================================================
# SQLAlchemy
# ======================================================================================


class SaMarketDataRepository:
    def __init__(self, session: Session) -> None:
        self.db = session

    def _bulk_upsert(self, table, constraint: str, set_cols, records: list[dict]) -> UpsertCounts:
        """INSERT ... ON CONFLICT DO UPDATE for many rows at once. The statement is
        compiled **once** (parameterised for a single row); passing the record list
        to ``execute`` lets SQLAlchemy's insertmanyvalues batch it — compiling a
        multi-row ``VALUES`` per chunk instead is O(rows) in the compiler and was
        the bottleneck that made a full worker cycle take ~15-20 min."""
        counts = UpsertCounts()
        if not records:
            return counts
        ins = pg_insert(table)
        set_ = {c: getattr(ins.excluded, c) for c in set_cols}
        if "ingested_at" in set_cols:
            set_["ingested_at"] = func.now()
        stmt = ins.on_conflict_do_update(constraint=constraint, set_=set_).returning(_INSERTED)
        for i in range(0, len(records), _UPSERT_CHUNK):
            for (inserted,) in self.db.execute(stmt, records[i : i + _UPSERT_CHUNK]):
                counts = counts + UpsertCounts(
                    inserted=int(bool(inserted)), updated=int(not inserted)
                )
        return counts

    def upsert_ohlcv_bars(
        self, *, instrument_id: int, timeframe: Timeframe, provider: str, bars: Sequence[OHLCVBar]
    ) -> UpsertCounts:
        records = [
            {
                "instrument_id": instrument_id,
                "timeframe": timeframe,
                "ts": b.ts,
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
                "provider": provider,
                "is_final": b.is_final,
            }
            for b in bars
        ]
        if not records:
            return UpsertCounts()
        return self._bulk_upsert(
            m.OhlcvBar,
            "bar_identity",
            ("open", "high", "low", "close", "volume", "is_final", "ingested_at"),
            records,
        )

    def upsert_open_interest(
        self, *, instrument_id: int, timeframe: Timeframe, provider: str, rows: Sequence[OIRow]
    ) -> UpsertCounts:
        records = [
            {
                "instrument_id": instrument_id,
                "timeframe": timeframe,
                "ts": r.ts,
                "oi": r.oi,
                "provider_oi_change": r.provider_oi_change,
                "provider": provider,
                "is_final": r.is_final,
            }
            for r in rows
        ]
        if not records:
            return UpsertCounts()
        return self._bulk_upsert(
            m.OpenInterest,
            "oi_identity",
            ("oi", "provider_oi_change", "is_final"),
            records,
        )

    def get_watermark(
        self, *, instrument_id: int, timeframe: Timeframe, data_kind: DataKind, provider: str
    ) -> Watermark | None:
        row = self.db.execute(
            select(
                m.IngestionWatermark.last_complete_ts,
                m.IngestionWatermark.last_verified_ts,
                m.IngestionWatermark.last_status,
            ).where(
                m.IngestionWatermark.instrument_id == instrument_id,
                m.IngestionWatermark.timeframe == timeframe,
                m.IngestionWatermark.data_kind == data_kind,
                m.IngestionWatermark.provider == provider,
            )
        ).one_or_none()
        if row is None:
            return None
        return Watermark(row.last_complete_ts, row.last_verified_ts, row.last_status)

    def upsert_watermark(self, wm: WatermarkWrite) -> None:
        set_ = {
            "last_complete_ts": wm.last_complete_ts,
            "last_attempt_at": wm.last_attempt_at,
            "last_status": wm.last_status,
            "detail": wm.detail,
        }
        if wm.last_verified_ts is not None:
            set_["last_verified_ts"] = wm.last_verified_ts
        stmt = (
            pg_insert(m.IngestionWatermark)
            .values(
                instrument_id=wm.instrument_id,
                timeframe=wm.timeframe,
                data_kind=wm.data_kind,
                provider=wm.provider,
                last_complete_ts=wm.last_complete_ts,
                last_verified_ts=wm.last_verified_ts,
                last_attempt_at=wm.last_attempt_at,
                last_status=wm.last_status,
                detail=wm.detail,
            )
            .on_conflict_do_update(constraint="watermark_identity", set_=set_)
        )
        self.db.execute(stmt)

    def bar_open_timestamps(
        self,
        *,
        instrument_id: int,
        timeframe: Timeframe,
        provider: str,
        start: datetime,
        end: datetime,
    ) -> list[datetime]:
        rows = self.db.execute(
            select(m.OhlcvBar.ts)
            .where(
                m.OhlcvBar.instrument_id == instrument_id,
                m.OhlcvBar.timeframe == timeframe,
                m.OhlcvBar.provider == provider,
                m.OhlcvBar.ts >= start,
                m.OhlcvBar.ts < end,
            )
            .order_by(m.OhlcvBar.ts)
        ).scalars()
        return list(rows)

    def count_bars(self, *, instrument_id: int, timeframe: Timeframe, provider: str) -> int:
        return int(
            self.db.execute(
                select(func.count())
                .select_from(m.OhlcvBar)
                .where(
                    m.OhlcvBar.instrument_id == instrument_id,
                    m.OhlcvBar.timeframe == timeframe,
                    m.OhlcvBar.provider == provider,
                )
            ).scalar_one()
        )

    def load_bars(self, *, instrument_id, timeframe, provider, limit):
        rows = self.db.execute(
            select(m.OhlcvBar)
            .where(
                m.OhlcvBar.instrument_id == instrument_id,
                m.OhlcvBar.timeframe == timeframe,
                m.OhlcvBar.provider == provider,
            )
            .order_by(m.OhlcvBar.ts.desc())
            .limit(limit)
        ).scalars()
        out = [
            OHLCVBar(
                ts=r.ts,
                open=r.open,
                high=r.high,
                low=r.low,
                close=r.close,
                volume=int(r.volume),
                is_final=bool(r.is_final),
                source=r.provider,
            )
            for r in rows
        ]
        out.reverse()  # ascending
        return out

    def load_oi(self, *, instrument_id, timeframe, provider, limit):
        rows = self.db.execute(
            select(m.OpenInterest)
            .where(
                m.OpenInterest.instrument_id == instrument_id,
                m.OpenInterest.timeframe == timeframe,
                m.OpenInterest.provider == provider,
            )
            .order_by(m.OpenInterest.ts.desc())
            .limit(limit)
        ).scalars()
        out = [
            OIRow(
                ts=r.ts,
                oi=int(r.oi),
                is_final=bool(r.is_final),
                provider_oi_change=r.provider_oi_change,
            )
            for r in rows
        ]
        out.reverse()
        return out


# ======================================================================================
# In-memory
# ======================================================================================


class MemoryMarketDataRepository:
    def __init__(self) -> None:
        # keyed by (instrument_id, timeframe, provider, ts)
        self._bars: dict[tuple[int, Timeframe, str, datetime], OHLCVBar] = {}
        self._oi: dict[tuple[int, Timeframe, str, datetime], OIRow] = {}
        # keyed by (instrument_id, timeframe, data_kind, provider)
        self._wm: dict[tuple[int, Timeframe, DataKind, str], WatermarkWrite] = {}

    def upsert_ohlcv_bars(
        self, *, instrument_id: int, timeframe: Timeframe, provider: str, bars: Sequence[OHLCVBar]
    ) -> UpsertCounts:
        ins = upd = 0
        for b in bars:
            key = (instrument_id, timeframe, provider, b.ts)
            if key in self._bars:
                upd += 1
            else:
                ins += 1
            self._bars[key] = b
        return UpsertCounts(ins, upd)

    def upsert_open_interest(
        self, *, instrument_id: int, timeframe: Timeframe, provider: str, rows: Sequence[OIRow]
    ) -> UpsertCounts:
        ins = upd = 0
        for r in rows:
            key = (instrument_id, timeframe, provider, r.ts)
            if key in self._oi:
                upd += 1
            else:
                ins += 1
            self._oi[key] = r
        return UpsertCounts(ins, upd)

    def get_watermark(
        self, *, instrument_id: int, timeframe: Timeframe, data_kind: DataKind, provider: str
    ) -> Watermark | None:
        wm = self._wm.get((instrument_id, timeframe, data_kind, provider))
        if wm is None:
            return None
        return Watermark(wm.last_complete_ts, wm.last_verified_ts, wm.last_status)

    def upsert_watermark(self, wm: WatermarkWrite) -> None:
        key = (wm.instrument_id, wm.timeframe, wm.data_kind, wm.provider)
        prev = self._wm.get(key)
        if prev is not None and wm.last_verified_ts is None:
            wm = replace(wm, last_verified_ts=prev.last_verified_ts)
        self._wm[key] = wm

    def bar_open_timestamps(
        self,
        *,
        instrument_id: int,
        timeframe: Timeframe,
        provider: str,
        start: datetime,
        end: datetime,
    ) -> list[datetime]:
        return sorted(
            ts
            for (iid, tf, pv, ts) in self._bars
            if iid == instrument_id and tf == timeframe and pv == provider and start <= ts < end
        )

    def count_bars(self, *, instrument_id: int, timeframe: Timeframe, provider: str) -> int:
        return sum(
            1
            for (iid, tf, pv, _ts) in self._bars
            if iid == instrument_id and tf == timeframe and pv == provider
        )

    def load_bars(self, *, instrument_id, timeframe, provider, limit):
        rows = [
            (ts, b)
            for (iid, tf, pv, ts), b in self._bars.items()
            if iid == instrument_id and tf == timeframe and pv == provider
        ]
        rows.sort(key=lambda x: x[0])
        return [b for _ts, b in rows[-limit:]]

    def load_oi(self, *, instrument_id, timeframe, provider, limit):
        rows = [
            (ts, r)
            for (iid, tf, pv, ts), r in self._oi.items()
            if iid == instrument_id and tf == timeframe and pv == provider
        ]
        rows.sort(key=lambda x: x[0])
        return [r for _ts, r in rows[-limit:]]
