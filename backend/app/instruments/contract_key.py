"""``contract_key`` — the platform-stable canonical contract identity (docs/03 §5.1).

A ``contract_key`` never changes while the underlying real-world contract is the
same, even if the provider re-issues its instrument key/token. Forms:

    INDEX    {U}-INDEX
    FUTURE   {U}-FUT-{YYYY-MM}           (monthly)
             {U}-FUT-{YYYY-MM-DD}        (weekly)
    OPTION   {U}-OPT-{YYYY-MM}-{K}-{CE|PE}       (monthly)
             {U}-OPT-{YYYY-MM-DD}-{K}-{CE|PE}    (weekly)

``U`` is the underlying symbol upper-cased with internal whitespace removed.
Monthly contracts key on **year-month** (no day) so an NSE holiday-driven shift
of a monthly expiry date within the same month does not change identity.
``K`` is the strike: an integer when whole, otherwise a fixed-precision decimal
string with trailing zeros trimmed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from analytical_core.enums import ExpiryKind, InstrumentType, OptionType

_U_RE = re.compile(r"[^A-Z0-9]")


class ContractKeyError(ValueError):
    """The inputs cannot form a deterministic contract_key."""


def normalise_underlying(symbol: str) -> str:
    token = _U_RE.sub("", (symbol or "").upper())
    if not token:
        raise ContractKeyError("empty underlying symbol")
    return token


def _fmt_strike(strike: Decimal) -> str:
    if strike <= 0:
        raise ContractKeyError(f"non-positive strike {strike}")
    q = strike.normalize()
    if q == q.to_integral_value():
        return str(int(q))
    return format(q, "f").rstrip("0").rstrip(".")


def _fmt_expiry(expiry: date, expiry_kind: ExpiryKind) -> str:
    if expiry_kind is ExpiryKind.WEEKLY:
        return expiry.isoformat()  # YYYY-MM-DD
    return f"{expiry.year:04d}-{expiry.month:02d}"  # MONTHLY / QUARTERLY -> year-month


def build_contract_key(
    *,
    instrument_type: InstrumentType,
    underlying_symbol: str,
    expiry_date: date | None = None,
    expiry_kind: ExpiryKind | None = None,
    strike_price: Decimal | None = None,
    option_type: OptionType | None = None,
) -> str:
    u = normalise_underlying(underlying_symbol)
    if instrument_type is InstrumentType.INDEX:
        return f"{u}-INDEX"
    if expiry_date is None or expiry_kind is None:
        raise ContractKeyError("derivative contract_key requires expiry_date + expiry_kind")
    exp = _fmt_expiry(expiry_date, expiry_kind)
    if instrument_type is InstrumentType.FUTURE:
        return f"{u}-FUT-{exp}"
    if instrument_type is InstrumentType.OPTION:
        if strike_price is None or option_type is None:
            raise ContractKeyError("option contract_key requires strike_price + option_type")
        return f"{u}-OPT-{exp}-{_fmt_strike(strike_price)}-{option_type.value}"
    raise ContractKeyError(f"unsupported instrument_type {instrument_type!r}")


@dataclass(frozen=True, slots=True)
class ContractKeyParts:
    underlying: str
    instrument_type: InstrumentType
    expiry_token: str | None  # "YYYY-MM" or "YYYY-MM-DD"
    strike: str | None
    option_type: OptionType | None


def parse_contract_key(contract_key: str) -> ContractKeyParts:
    """Best-effort structural parse (round-trips :func:`build_contract_key`)."""
    parts = contract_key.split("-")
    u = parts[0]
    kind = parts[1] if len(parts) > 1 else ""
    if kind == "INDEX":
        return ContractKeyParts(u, InstrumentType.INDEX, None, None, None)
    if kind == "FUT":
        return ContractKeyParts(u, InstrumentType.FUTURE, "-".join(parts[2:]), None, None)
    if kind == "OPT":
        opt = OptionType(parts[-1])
        strike = parts[-2]
        expiry_token = "-".join(parts[2:-2])
        return ContractKeyParts(u, InstrumentType.OPTION, expiry_token, strike, opt)
    raise ContractKeyError(f"unrecognised contract_key {contract_key!r}")
