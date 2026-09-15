"""Market Profile session cache (docs/03 §5.4, docs/05 §10.11)."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db import models as m
from app.db.repositories.protocols import (
    MarketProfileCache,
    MarketProfileSessionRef,
    MarketProfileSessionWrite,
)


class SaMarketProfileRepository:
    def __init__(self, session: Session) -> None:
        self.db = session

    def get_cache(self, instrument_id, session_date, profile_type):
        row = self.db.execute(
            select(m.MarketProfileSession.source_max_ts, m.MarketProfileSession.params_hash).where(
                m.MarketProfileSession.instrument_id == instrument_id,
                m.MarketProfileSession.session_date == session_date,
                m.MarketProfileSession.profile_type == profile_type,
            )
        ).one_or_none()
        if row is None:
            return None
        return MarketProfileCache(
            source_max_ts=row.source_max_ts,
            params_hash=row.params_hash,
        )

    def get_prior_session(self, instrument_id, before_date, profile_type):
        row = self.db.execute(
            select(
                m.MarketProfileSession.session_date,
                m.MarketProfileSession.poc,
                m.MarketProfileSession.vah,
                m.MarketProfileSession.val,
                m.MarketProfileSession.session_high,
                m.MarketProfileSession.session_low,
                m.MarketProfileSession.close,
            )
            .where(
                m.MarketProfileSession.instrument_id == instrument_id,
                m.MarketProfileSession.profile_type == profile_type,
                m.MarketProfileSession.session_date < before_date,
                m.MarketProfileSession.is_session_complete.is_(True),
            )
            .order_by(m.MarketProfileSession.session_date.desc())
            .limit(1)
        ).one_or_none()
        if row is None:
            return None
        return MarketProfileSessionRef(
            session_date=row.session_date,
            poc=float(row.poc) if row.poc is not None else None,
            vah=float(row.vah) if row.vah is not None else None,
            val=float(row.val) if row.val is not None else None,
            session_high=float(row.session_high) if row.session_high is not None else None,
            session_low=float(row.session_low) if row.session_low is not None else None,
            close=float(row.close) if row.close is not None else None,
        )

    def upsert_session(self, w: MarketProfileSessionWrite) -> None:
        values = dict(
            instrument_id=w.instrument_id,
            session_date=w.session_date,
            profile_type=w.profile_type,
            bin_size=w.bin_size,
            poc=w.poc,
            vah=w.vah,
            val=w.val,
            ib_high=w.ib_high,
            ib_low=w.ib_low,
            session_high=w.session_high,
            session_low=w.session_low,
            profile_shape=w.profile_shape,
            is_session_complete=w.is_session_complete,
            close=w.close,
            bins=w.bins,
            events=w.events,
            mp_events_version=w.mp_events_version,
            source_max_ts=w.source_max_ts,
            algo_version=w.algo_version,
            params_hash=w.params_hash,
        )
        stmt = pg_insert(m.MarketProfileSession).values(**values)
        stmt = stmt.on_conflict_do_update(
            constraint="mp_session_identity",
            set_={
                k: v
                for k, v in values.items()
                if k not in ("instrument_id", "session_date", "profile_type")
            },
        )
        self.db.execute(stmt)


class MemoryMarketProfileRepository:
    def __init__(self) -> None:
        self._store: dict[tuple[int, date, str], MarketProfileSessionWrite] = {}

    def get_cache(self, instrument_id, session_date, profile_type):
        w = self._store.get((instrument_id, session_date, profile_type))
        if w is None:
            return None
        return MarketProfileCache(
            source_max_ts=w.source_max_ts,
            params_hash=w.params_hash,
        )

    def get_prior_session(self, instrument_id, before_date, profile_type):
        cands = [
            w
            for (iid, sd, pt), w in self._store.items()
            if iid == instrument_id
            and pt == profile_type
            and sd < before_date
            and w.is_session_complete
        ]
        if not cands:
            return None
        w = max(cands, key=lambda x: x.session_date)
        return MarketProfileSessionRef(
            session_date=w.session_date,
            poc=w.poc,
            vah=w.vah,
            val=w.val,
            session_high=w.session_high,
            session_low=w.session_low,
            close=w.close,
        )

    def upsert_session(self, w: MarketProfileSessionWrite) -> None:
        self._store[(w.instrument_id, w.session_date, w.profile_type)] = w
