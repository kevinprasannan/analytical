"""INGEST phase — the real live/incremental pull (Phase 2.6).

Delegates to :class:`~app.ingestion.backfill.BackfillService` (the shared
watermark-driven engine from 2.5: 2.3 adapter → 2.4 aggregation → 2.5
``MarketDataRepository``), bounded to a short recent window so a cycle only
touches the forming tail. Deep history is ``analytical-backfill``.

Per-instrument outcome mapping (docs/03 §5.3, docs/09 §2.9):
  * OK / partial-but-persisted -> ``OK``
  * throttled (429)            -> ``DEGRADED``  (watermark ``RATE_LIMITED``, cycle continues)
  * token expired mid-cycle    -> ``SKIPPED``
  * any other provider error   -> ``ERROR``     (other instruments continue)

A token that is already expired at phase start short-circuits: **every**
instrument ``SKIPPED``, phase ``SKIPPED``, the worker does not crash.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from analytical_core.enums import InstrumentPhaseOutcome, PhaseStatus, RunPhase, WatermarkStatus
from app.config import Settings, get_settings
from app.db.repositories.market_data import MarketDataRepository
from app.db.repositories.protocols import InstrumentView
from app.ingestion.backfill import BackfillService, BackfillTarget
from app.pipeline import PhaseOutcome
from app.providers.base import MarketDataProvider, ProviderAuthError

_STATUS_TO_OUTCOME = {
    WatermarkStatus.OK: InstrumentPhaseOutcome.OK,
    WatermarkStatus.RATE_LIMITED: InstrumentPhaseOutcome.DEGRADED,
    WatermarkStatus.AUTH_FAILED: InstrumentPhaseOutcome.SKIPPED,
    WatermarkStatus.ERROR: InstrumentPhaseOutcome.ERROR,
}


class IngestionService:
    def __init__(
        self,
        provider: MarketDataProvider,
        market_data: MarketDataRepository,
        *,
        settings: Settings | None = None,
        now: datetime | None = None,
    ) -> None:
        self.provider = provider
        self.market_data = market_data
        self.settings = settings or get_settings()
        self.now = now or datetime.now(tz=UTC)

    def run(self, instruments: list[InstrumentView]) -> PhaseOutcome:
        outcome = PhaseOutcome(phase=RunPhase.INGEST, status=PhaseStatus.RUNNING)

        try:
            self.provider.ensure_authenticated()
        except ProviderAuthError as exc:
            for inst in instruments:
                outcome.record(inst.id, InstrumentPhaseOutcome.SKIPPED)
            outcome.status = PhaseStatus.SKIPPED
            outcome.detail = {"reason": "provider_auth_failed", "error": str(exc)}
            return outcome

        if not instruments:
            outcome.status = PhaseStatus.SUCCEEDED
            return outcome

        targets = [
            BackfillTarget(
                instrument_id=inst.id,
                provider_symbol=inst.provider_symbol,
                instrument_type=inst.instrument_type,
                contract_key=inst.contract_key,
            )
            for inst in instruments
        ]
        service = BackfillService(
            provider=self.provider,
            repo=self.market_data,
            budget=None,  # rate limiting lives in the provider's HTTP client
            settings=self.settings,
            now_fn=lambda: self.now,
        )
        report = service.run(
            targets,
            start=self.now - timedelta(days=self.settings.ingestion_lookback_days),
            end=self.now,
            concurrency=self.settings.provider_concurrency,
        )

        bars = oi = gaps = 0
        per_instrument: dict[str, int] = {}
        for inst, ir in zip(instruments, report.instruments, strict=True):
            outcome.record(inst.id, _STATUS_TO_OUTCOME[ir.status])
            n = sum(c.total for c in ir.bars.values())
            per_instrument[str(inst.id)] = n
            bars += n
            oi += ir.oi.total
            gaps += ir.m1_gap_count
        outcome.detail = {
            "bars": per_instrument,
            "bars_upserted": bars,
            "oi_upserted": oi,
            "m1_gap_count": gaps,
        }
        outcome.status = _roll_up(outcome)
        return outcome


def _roll_up(outcome: PhaseOutcome) -> PhaseStatus:
    vals = set(outcome.instrument_outcomes.values())
    if not vals:
        return PhaseStatus.SUCCEEDED
    if vals == {InstrumentPhaseOutcome.SKIPPED}:
        return PhaseStatus.SKIPPED
    if vals == {InstrumentPhaseOutcome.OK}:
        return PhaseStatus.SUCCEEDED
    return PhaseStatus.PARTIAL
