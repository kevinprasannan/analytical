"""`plan_analyses` applicability matrix (docs/04 §4) — pure, no DB.

Focus: OPTION is chain-only — only ``open_interest`` runs; every premium-series
technical is ``NOT_APPLICABLE`` by design.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from analytical_core.enums import AnalysisStatus, InstrumentType, Timeframe
from app.analysis.applicability import plan_analyses
from app.db.repositories.protocols import InstrumentView
from app.providers.capabilities import OIMode, ProviderCapabilities

_AS_OF = datetime(2026, 9, 1, 6, 0, tzinfo=UTC)
_SDATE = date(2026, 9, 1)

_CAPS = ProviderCapabilities(
    provider="upstox",
    auth_kind="static-token",
    supports_instrument_master=True,
    native_timeframes=frozenset({Timeframe.M1, Timeframe.D1}),
    aggregatable_from=Timeframe.M1,
    oi_mode=OIMode.PER_TIMEFRAME,
)


def _view(itype: InstrumentType, *, has_volume: bool = True) -> InstrumentView:
    return InstrumentView(
        id=1,
        contract_key="NIFTY-OPT-2026-09-01-24000-CE",
        instrument_type=itype,
        has_volume=has_volume,
        has_intraday_oi=True,
        provider_symbol="NSE_FO|12345",
    )


def _by_key(plans):
    out: dict[str, set[AnalysisStatus]] = {}
    for p in plans:
        out.setdefault(p.analysis_key, set()).add(p.status)
    return out


def test_option_is_chain_only():
    plans = plan_analyses(_view(InstrumentType.OPTION), _CAPS, as_of=_AS_OF, session_date=_SDATE)
    by_key = _by_key(plans)

    # every premium-series technical is NOT_APPLICABLE for OPTION
    for key in ("rsi", "bollinger", "ema7", "volume"):
        assert by_key[key] == {AnalysisStatus.NOT_APPLICABLE}, key

    # open_interest still runs (feeds the option-chain view)
    assert by_key["open_interest"] == {AnalysisStatus.OK}

    # golden_cross NA (dated contract), market_profile INSUFFICIENT_DATA (shallow premium range)
    assert by_key["golden_cross"] == {AnalysisStatus.NOT_APPLICABLE}
    assert by_key["market_profile"] == {AnalysisStatus.INSUFFICIENT_DATA}

    # every chain-only NA carries the explanatory reason
    for p in plans:
        if p.analysis_key in ("rsi", "bollinger", "ema7", "volume"):
            assert p.reason and "chain-only" in p.reason


@pytest.mark.parametrize("itype", [InstrumentType.INDEX, InstrumentType.FUTURE])
def test_non_option_technicals_still_ok(itype):
    by_key = _by_key(plan_analyses(_view(itype), _CAPS, as_of=_AS_OF, session_date=_SDATE))
    assert AnalysisStatus.OK in by_key["rsi"]
    assert AnalysisStatus.OK in by_key["ema7"]
