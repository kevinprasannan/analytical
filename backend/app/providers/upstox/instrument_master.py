"""Upstox NSE instrument-master parsing + normalisation (Phase 2.2).

Fixture-driven: reads a **local** ``.json`` / ``.json.gz`` file in the exact
public-Upstox-master shape validated in docs/11 §4 (PV-6). No network, no auth.

  * ``read_master(path)``       -> list[dict]                 (parsing)
  * ``normalise(rows)``         -> (list[InstrumentRecord], list[RejectedRow])  (normalisation)
  * ``records_from_master(p)``  -> (list[InstrumentRecord], list[RejectedRow])

Normalisation maps Upstox's taxonomy onto the provider-neutral ``InstrumentRecord``.
A row whose *kind* is not something V1 handles (unknown ``instrument_type``,
non-derivative/non-index ``segment``, missing ``instrument_key``, malformed
``expiry``) is emitted as a ``RejectedRow`` — it is never guessed at or dropped
silently. Everything else (bad strike, missing ``weekly`` on a derivative, dup
keys, unresolved underlyings) is left for ``app.instruments.validation`` /
``app.instruments.registry``.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from analytical_core.enums import InstrumentSegment, InstrumentType, OptionType
from app.instruments.errors import RejectedRow
from app.providers.base import InstrumentRecord

IST = ZoneInfo("Asia/Kolkata")
PROVIDER = "upstox"

_TYPE_MAP: dict[str, tuple[InstrumentType, OptionType | None]] = {
    "INDEX": (InstrumentType.INDEX, None),
    "FUT": (InstrumentType.FUTURE, None),
    "CE": (InstrumentType.OPTION, OptionType.CE),
    "PE": (InstrumentType.OPTION, OptionType.PE),
}
# NSE + BSE index and F&O. Equity (NSE_EQ / BSE_EQ) and currency (BCD_FO) are out
# of scope. Downstream normalisation is exchange-agnostic — ``exchange`` comes from
# the row; ``plan_universe`` filters derivatives to the configured underlyings.
_SUPPORTED_SEGMENTS = {"NSE_INDEX", "NSE_FO", "BSE_INDEX", "BSE_FO"}


class InstrumentMasterFormatError(ValueError):
    """The master file is not a JSON list of row objects."""


def read_master(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.is_file():
        raise InstrumentMasterFormatError(f"instrument master file not found: {p}")
    opener = gzip.open if p.suffix == ".gz" else open
    with opener(p, "rb") as fh:  # type: ignore[operator]
        try:
            data = json.loads(fh.read())
        except json.JSONDecodeError as exc:
            raise InstrumentMasterFormatError(f"invalid JSON in {p}: {exc}") from exc
    if not isinstance(data, list):
        raise InstrumentMasterFormatError(f"{p}: expected a JSON list, got {type(data).__name__}")
    if not all(isinstance(row, dict) for row in data):
        raise InstrumentMasterFormatError(f"{p}: every element must be an object")
    return data


def _to_decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _epoch_ms_to_ist_date(value: object) -> tuple[date | None, bool]:
    """(date, ok). ``ok`` is False only when the value is present but malformed."""
    if value is None or value == "" or value == 0:
        return None, True
    try:
        ms = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None, False
    if ms <= 0:
        return None, False
    return datetime.fromtimestamp(ms / 1000, tz=IST).date(), True


def normalise(
    rows: Iterable[Mapping[str, object]]
) -> tuple[list[InstrumentRecord], list[RejectedRow]]:
    records: list[InstrumentRecord] = []
    rejected: list[RejectedRow] = []

    for row in rows:
        raw = dict(row)
        key = raw.get("instrument_key")
        provider_symbol = str(key) if key else None
        if not provider_symbol:
            rejected.append(RejectedRow("normalise", "missing instrument_key", None, None, raw))
            continue

        seg = raw.get("segment")
        if seg not in _SUPPORTED_SEGMENTS:
            rejected.append(
                RejectedRow("normalise", f"unsupported segment {seg!r}", provider_symbol, None, raw)
            )
            continue

        it_raw = raw.get("instrument_type")
        if it_raw not in _TYPE_MAP:
            rejected.append(
                RejectedRow(
                    "normalise",
                    f"unsupported instrument_type {it_raw!r}",
                    provider_symbol,
                    None,
                    raw,
                )
            )
            continue
        instrument_type, option_type = _TYPE_MAP[str(it_raw)]

        expiry_date, expiry_ok = _epoch_ms_to_ist_date(raw.get("expiry"))
        if not expiry_ok:
            rejected.append(
                RejectedRow(
                    "normalise",
                    f"malformed expiry {raw.get('expiry')!r}",
                    provider_symbol,
                    None,
                    raw,
                )
            )
            continue

        if instrument_type is InstrumentType.INDEX:
            segment = InstrumentSegment.INDEX
        elif instrument_type is InstrumentType.FUTURE:
            segment = InstrumentSegment.FUT
        else:
            segment = InstrumentSegment.OPT

        strike = _to_decimal(raw.get("strike_price"))
        if strike is not None and strike == 0:
            strike = None  # futures report 0.0; treat as "no strike"

        weekly = raw.get("weekly")
        weekly_flag = weekly if isinstance(weekly, bool) else None

        lot_raw = raw.get("lot_size")
        try:
            lot_size = int(lot_raw) if lot_raw not in (None, "", 0) else None
        except (TypeError, ValueError):
            lot_size = None

        records.append(
            InstrumentRecord(
                provider=PROVIDER,
                provider_symbol=provider_symbol,
                instrument_type=instrument_type,
                underlying_symbol=(
                    str(raw["underlying_symbol"]) if raw.get("underlying_symbol") else None
                ),
                exchange=str(raw.get("exchange") or "NSE"),
                expiry_date=expiry_date,
                strike_price=strike,
                option_type=option_type,
                lot_size=lot_size,
                tick_size=_to_decimal(raw.get("tick_size")),
                display_name=(str(raw["name"]) if raw.get("name") else None),
                segment=segment,
                underlying_provider_key=(
                    str(raw["underlying_key"]) if raw.get("underlying_key") else None
                ),
                weekly=weekly_flag,
                trading_symbol=(str(raw["trading_symbol"]) if raw.get("trading_symbol") else None),
                name=(str(raw["name"]) if raw.get("name") else None),
                source=PROVIDER,
                raw=raw,
            )
        )

    return records, rejected


def records_from_master(path: str | Path) -> tuple[list[InstrumentRecord], list[RejectedRow]]:
    return normalise(read_master(path))
