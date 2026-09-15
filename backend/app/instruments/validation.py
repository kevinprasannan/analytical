"""Deterministic validation: ``InstrumentRecord`` -> accepted ``CanonicalInstrument``
or ``RejectedRow`` (§9). No guessing — a record that cannot be classified from the
provider's own fields is quarantined with a stable reason.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from analytical_core.enums import (
    ExpiryKind,
    InstrumentSegment,
    InstrumentType,
    OptionType,
)
from app.instruments.contract_key import ContractKeyError, build_contract_key
from app.instruments.errors import RejectedRow
from app.providers.base import InstrumentRecord

_DERIVATIVES = {InstrumentType.FUTURE, InstrumentType.OPTION}


@dataclass(frozen=True, slots=True)
class CanonicalInstrument:
    """An accepted, fully-classified contract, ready for canonical construction.

    ``underlying_id`` is resolved later (registry, §5); ``None`` here.
    """

    contract_key: str
    instrument_type: InstrumentType
    segment: InstrumentSegment
    symbol: str
    display_name: str | None
    exchange: str
    underlying_symbol: str | None
    underlying_provider_key: str | None
    expiry_date: date | None
    expiry_kind: ExpiryKind | None
    strike_price: Decimal | None
    option_type: OptionType | None
    lot_size: int | None
    tick_size: Decimal | None
    has_intraday_oi: bool
    provider: str
    provider_symbol: str
    provider_metadata: Mapping[str, object] = field(default_factory=dict)

    def sort_key(self) -> tuple[str, str]:
        return (self.contract_key, self.provider_symbol)


def _classify_one(rec: InstrumentRecord) -> CanonicalInstrument | RejectedRow:
    ps = rec.provider_symbol
    raw = dict(rec.raw)

    def reject(reason: str) -> RejectedRow:
        return RejectedRow("validate", reason, ps, None, raw)

    it = rec.instrument_type
    seg = rec.segment
    if seg is None:
        return reject("missing segment")

    if it is InstrumentType.INDEX:
        token = rec.trading_symbol or rec.name
        if not token:
            return reject("index row has no trading_symbol/name")
        if rec.expiry_date is not None:
            return reject("index row has an expiry_date")
        if rec.strike_price is not None:
            return reject("index row has a strike_price")
        try:
            ck = build_contract_key(instrument_type=it, underlying_symbol=token)
        except ContractKeyError as exc:
            return reject(f"contract_key: {exc}")
        return CanonicalInstrument(
            contract_key=ck,
            instrument_type=it,
            segment=seg,
            symbol=rec.trading_symbol or token,
            display_name=rec.display_name or rec.name,
            exchange=rec.exchange or "NSE",
            underlying_symbol=None,
            underlying_provider_key=None,
            expiry_date=None,
            expiry_kind=None,
            strike_price=None,
            option_type=None,
            lot_size=None,
            tick_size=None,
            has_intraday_oi=False,
            provider=rec.provider,
            provider_symbol=ps,
            provider_metadata=raw,
        )

    if it not in _DERIVATIVES:
        return reject(f"unsupported instrument_type {it.value!r}")

    if not rec.underlying_symbol:
        return reject("derivative row has no underlying_symbol")
    if not rec.underlying_provider_key:
        return reject("derivative row has no underlying_key")
    if rec.expiry_date is None:
        return reject("derivative row has no expiry")
    if not isinstance(rec.weekly, bool):
        return reject("cannot classify expiry_kind: provider 'weekly' flag absent/invalid")
    expiry_kind = ExpiryKind.WEEKLY if rec.weekly else ExpiryKind.MONTHLY
    if rec.lot_size is None or rec.lot_size <= 0:
        return reject(f"invalid lot_size {rec.lot_size!r}")
    if rec.tick_size is None or rec.tick_size <= 0:
        return reject(f"invalid tick_size {rec.tick_size!r}")

    if it is InstrumentType.OPTION:
        if rec.option_type not in (OptionType.CE, OptionType.PE):
            return reject("option row has no CE/PE option_type")
        if rec.strike_price is None or rec.strike_price <= 0:
            return reject(f"invalid strike_price {rec.strike_price!r}")
        strike = rec.strike_price
        option_type = rec.option_type
    else:  # FUTURE
        if rec.strike_price is not None:
            return reject("future row has a strike_price")
        strike = None
        option_type = None

    try:
        ck = build_contract_key(
            instrument_type=it,
            underlying_symbol=rec.underlying_symbol,
            expiry_date=rec.expiry_date,
            expiry_kind=expiry_kind,
            strike_price=strike,
            option_type=option_type,
        )
    except ContractKeyError as exc:
        return reject(f"contract_key: {exc}")

    return CanonicalInstrument(
        contract_key=ck,
        instrument_type=it,
        segment=seg,
        symbol=rec.trading_symbol or ck,
        display_name=rec.display_name or rec.name,
        exchange=rec.exchange or "NSE",
        underlying_symbol=rec.underlying_symbol,
        underlying_provider_key=rec.underlying_provider_key,
        expiry_date=rec.expiry_date,
        expiry_kind=expiry_kind,
        strike_price=strike,
        option_type=option_type,
        lot_size=rec.lot_size,
        tick_size=rec.tick_size,
        has_intraday_oi=True,
        provider=rec.provider,
        provider_symbol=ps,
        provider_metadata=raw,
    )


def validate(
    records: Iterable[InstrumentRecord],
) -> tuple[list[CanonicalInstrument], list[RejectedRow]]:
    accepted: list[CanonicalInstrument] = []
    rejected: list[RejectedRow] = []

    for rec in records:
        outcome = _classify_one(rec)
        (accepted if isinstance(outcome, CanonicalInstrument) else rejected).append(outcome)  # type: ignore[arg-type]

    # --- cross-record dedup (§9): if a provider_symbol or a contract_key
    #     appears more than once among the per-record-accepted set we cannot
    #     tell which row is authoritative -> quarantine *all* the colliding rows.
    ps_counts = Counter(c.provider_symbol for c in accepted)
    ck_counts = Counter(c.contract_key for c in accepted)
    kept: list[CanonicalInstrument] = []
    for c in accepted:
        if ps_counts[c.provider_symbol] > 1:
            rejected.append(
                RejectedRow(
                    "validate",
                    "duplicate provider instrument key",
                    c.provider_symbol,
                    c.contract_key,
                    dict(c.provider_metadata),
                )
            )
        elif ck_counts[c.contract_key] > 1:
            rejected.append(
                RejectedRow(
                    "validate",
                    "duplicate canonical contract",
                    c.provider_symbol,
                    c.contract_key,
                    dict(c.provider_metadata),
                )
            )
        else:
            kept.append(c)

    kept.sort(key=CanonicalInstrument.sort_key)
    rejected.sort(key=RejectedRow.sort_key)
    return kept, rejected
