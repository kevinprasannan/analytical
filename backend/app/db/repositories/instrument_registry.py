"""Persistence for the canonical instrument registry (Phase 2.2).

Standalone — **not** part of the worker ``Repositories`` bundle, because
instrument-master sync is an admin operation, not a step of ``run_cycle``.

Two implementations behind one protocol:
  * ``SaInstrumentRegistryRepository``     — PostgreSQL, transactional
  * ``MemoryInstrumentRegistryRepository`` — deterministic, for no-DB tests

Contract-identity rule (§3): a provider re-issuing its instrument key updates
``provider_instrument_map`` only; the ``instruments`` row keeps its ``id`` and
``contract_key``, and historical market-data tables are never touched here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from analytical_core.enums import InstrumentType
from app.db import models as m
from app.instruments.validation import CanonicalInstrument

_MUTABLE_FIELDS = (
    "symbol",
    "display_name",
    "exchange",
    "segment",
    "underlying_id",
    "expiry_date",
    "expiry_kind",
    "strike_price",
    "option_type",
    "lot_size",
    "tick_size",
    "has_intraday_oi",
    "is_active",
)


class RegistryIntegrityError(RuntimeError):
    """A canonical invariant would be violated (e.g. contract_key type mismatch)."""


@dataclass(frozen=True, slots=True)
class InstrumentSummary:
    id: int
    instrument_type: InstrumentType
    provider_symbol: str | None


class InstrumentRegistryRepository(Protocol):
    def get_instrument_id_by_provider_symbol(
        self, provider: str, provider_symbol: str
    ) -> int | None: ...
    def get_instrument_by_contract_key(self, contract_key: str) -> InstrumentSummary | None: ...
    def get_instrument_type(self, instrument_id: int) -> InstrumentType | None: ...
    def upsert_instrument(
        self, draft: CanonicalInstrument, *, underlying_id: int | None
    ) -> tuple[int, str]: ...  # (id, "created" | "updated" | "unchanged")
    def upsert_provider_map(
        self,
        provider: str,
        instrument_id: int,
        provider_symbol: str,
        metadata: Mapping[str, object],
    ) -> str: ...  # "created" | "remapped" | "unchanged"
    def list_active_instrument_ids(self, provider: str) -> set[int]: ...
    def deactivate(self, instrument_id: int) -> None: ...


def _draft_values(draft: CanonicalInstrument, underlying_id: int | None) -> dict:
    return {
        "symbol": draft.symbol,
        "display_name": draft.display_name,
        "exchange": draft.exchange,
        "segment": draft.segment,
        "underlying_id": underlying_id,
        "expiry_date": draft.expiry_date,
        "expiry_kind": draft.expiry_kind,
        "strike_price": draft.strike_price,
        "option_type": draft.option_type,
        "lot_size": draft.lot_size,
        "tick_size": draft.tick_size,
        "has_intraday_oi": draft.has_intraday_oi,
        "is_active": True,
    }


def _eq(a: object, b: object) -> bool:
    # Decimal("1.0") == Decimal("1.0000"); None-safe.
    return a == b


# ======================================================================================
# SQLAlchemy
# ======================================================================================


class SaInstrumentRegistryRepository:
    def __init__(self, session: Session) -> None:
        self.db = session

    def get_instrument_id_by_provider_symbol(
        self, provider: str, provider_symbol: str
    ) -> int | None:
        return self.db.execute(
            select(m.ProviderInstrumentMap.instrument_id).where(
                m.ProviderInstrumentMap.provider == provider,
                m.ProviderInstrumentMap.provider_symbol == provider_symbol,
            )
        ).scalar_one_or_none()

    def get_instrument_by_contract_key(self, contract_key: str) -> InstrumentSummary | None:
        row = self.db.execute(
            select(m.Instrument.id, m.Instrument.instrument_type).where(
                m.Instrument.contract_key == contract_key
            )
        ).one_or_none()
        if row is None:
            return None
        ps = self.db.execute(
            select(m.ProviderInstrumentMap.provider_symbol).where(
                m.ProviderInstrumentMap.instrument_id == row.id
            )
        ).scalar_one_or_none()
        return InstrumentSummary(id=row.id, instrument_type=row.instrument_type, provider_symbol=ps)

    def get_instrument_type(self, instrument_id: int) -> InstrumentType | None:
        return self.db.execute(
            select(m.Instrument.instrument_type).where(m.Instrument.id == instrument_id)
        ).scalar_one_or_none()

    def upsert_instrument(
        self, draft: CanonicalInstrument, *, underlying_id: int | None
    ) -> tuple[int, str]:
        existing = self.db.execute(
            select(m.Instrument).where(m.Instrument.contract_key == draft.contract_key)
        ).scalar_one_or_none()
        values = _draft_values(draft, underlying_id)

        if existing is None:
            row = m.Instrument(
                contract_key=draft.contract_key,
                instrument_type=draft.instrument_type,
                currency="INR",
                is_tracked=False,
                has_volume=True,
                **values,
            )
            self.db.add(row)
            self.db.flush()
            return int(row.id), "created"

        if existing.instrument_type != draft.instrument_type:
            raise RegistryIntegrityError(
                f"contract_key {draft.contract_key!r} exists as "
                f"{existing.instrument_type.value}, master says {draft.instrument_type.value}"
            )
        changed = any(not _eq(getattr(existing, f), values[f]) for f in _MUTABLE_FIELDS)
        if not changed:
            return int(existing.id), "unchanged"
        for f in _MUTABLE_FIELDS:
            setattr(existing, f, values[f])
        self.db.flush()
        return int(existing.id), "updated"

    def upsert_provider_map(
        self,
        provider: str,
        instrument_id: int,
        provider_symbol: str,
        metadata: Mapping[str, object],
    ) -> str:
        existing = self.db.execute(
            select(m.ProviderInstrumentMap).where(
                m.ProviderInstrumentMap.provider == provider,
                m.ProviderInstrumentMap.instrument_id == instrument_id,
            )
        ).scalar_one_or_none()
        meta = dict(metadata)
        if existing is None:
            self.db.add(
                m.ProviderInstrumentMap(
                    provider=provider,
                    instrument_id=instrument_id,
                    provider_symbol=provider_symbol,
                    provider_metadata=meta,
                    is_active=True,
                )
            )
            self.db.flush()
            return "created"
        if existing.provider_symbol != provider_symbol:
            existing.provider_symbol = provider_symbol
            existing.provider_metadata = meta
            existing.is_active = True
            self.db.flush()
            return "remapped"
        if existing.provider_metadata != meta or not existing.is_active:
            existing.provider_metadata = meta
            existing.is_active = True
            self.db.flush()
        return "unchanged"

    def list_active_instrument_ids(self, provider: str) -> set[int]:
        rows = self.db.execute(
            select(m.Instrument.id)
            .join(m.ProviderInstrumentMap, m.ProviderInstrumentMap.instrument_id == m.Instrument.id)
            .where(m.ProviderInstrumentMap.provider == provider)
            .where(m.ProviderInstrumentMap.is_active.is_(True))
            .where(m.Instrument.is_active.is_(True))
        ).scalars()
        return {int(x) for x in rows}

    def deactivate(self, instrument_id: int) -> None:
        self.db.execute(
            update(m.Instrument).where(m.Instrument.id == instrument_id).values(is_active=False)
        )
        self.db.execute(
            update(m.ProviderInstrumentMap)
            .where(m.ProviderInstrumentMap.instrument_id == instrument_id)
            .values(is_active=False)
        )


# ======================================================================================
# In-memory
# ======================================================================================


class MemoryInstrumentRegistryRepository:
    def __init__(self) -> None:
        self._inst: dict[int, dict] = {}
        self._by_ck: dict[str, int] = {}
        self._maps: dict[tuple[str, int], dict] = {}
        self._by_ps: dict[tuple[str, str], int] = {}
        self._seq = 0

    # -- queries --------------------------------------------------------
    def get_instrument_id_by_provider_symbol(
        self, provider: str, provider_symbol: str
    ) -> int | None:
        return self._by_ps.get((provider, provider_symbol))

    def get_instrument_by_contract_key(self, contract_key: str) -> InstrumentSummary | None:
        iid = self._by_ck.get(contract_key)
        if iid is None:
            return None
        row = self._inst[iid]
        ps = next(
            (v["provider_symbol"] for (p, i), v in self._maps.items() if i == iid),
            None,
        )
        return InstrumentSummary(id=iid, instrument_type=row["instrument_type"], provider_symbol=ps)

    def get_instrument_type(self, instrument_id: int) -> InstrumentType | None:
        row = self._inst.get(instrument_id)
        return row["instrument_type"] if row else None

    # -- writes --------------------------------------------------------
    def upsert_instrument(
        self, draft: CanonicalInstrument, *, underlying_id: int | None
    ) -> tuple[int, str]:
        values = _draft_values(draft, underlying_id)
        iid = self._by_ck.get(draft.contract_key)
        if iid is None:
            self._seq += 1
            iid = self._seq
            self._inst[iid] = {
                "id": iid,
                "contract_key": draft.contract_key,
                "instrument_type": draft.instrument_type,
                "is_tracked": False,
                "has_volume": True,
                "currency": "INR",
                **values,
            }
            self._by_ck[draft.contract_key] = iid
            return iid, "created"
        row = self._inst[iid]
        if row["instrument_type"] != draft.instrument_type:
            raise RegistryIntegrityError(f"contract_key {draft.contract_key!r} type mismatch")
        changed = any(not _eq(row[f], values[f]) for f in _MUTABLE_FIELDS)
        if not changed:
            return iid, "unchanged"
        row.update(values)
        return iid, "updated"

    def upsert_provider_map(
        self,
        provider: str,
        instrument_id: int,
        provider_symbol: str,
        metadata: Mapping[str, object],
    ) -> str:
        meta = dict(metadata)
        cur = self._maps.get((provider, instrument_id))
        if cur is None:
            self._maps[(provider, instrument_id)] = {
                "provider_symbol": provider_symbol,
                "provider_metadata": meta,
                "is_active": True,
            }
            self._by_ps[(provider, provider_symbol)] = instrument_id
            return "created"
        if cur["provider_symbol"] != provider_symbol:
            self._by_ps.pop((provider, cur["provider_symbol"]), None)
            cur["provider_symbol"] = provider_symbol
            cur["provider_metadata"] = meta
            cur["is_active"] = True
            self._by_ps[(provider, provider_symbol)] = instrument_id
            return "remapped"
        cur["provider_metadata"] = meta
        cur["is_active"] = True
        return "unchanged"

    def list_active_instrument_ids(self, provider: str) -> set[int]:
        return {
            i
            for (p, i), v in self._maps.items()
            if p == provider and v["is_active"] and self._inst[i]["is_active"]
        }

    def deactivate(self, instrument_id: int) -> None:
        if instrument_id in self._inst:
            self._inst[instrument_id]["is_active"] = False
        for (_p, i), v in self._maps.items():
            if i == instrument_id:
                v["is_active"] = False
