"""Historical backfill (Phase 2.5).

Watermark-driven, resume-safe, idempotent. Pulls **M1 + D1** natively via the
provider adapter (which paginates internally, docs/11 PV-3), aggregates M1 →
session-anchored M5/M15/H1 (2.4), and upserts ``ohlcv_bars`` /
``open_interest``. A shared thread-safe :class:`RequestBudget` keeps concurrent
instruments under the provider's per-second and 30-minute limits (docs/02 §6.7).

Not a worker cycle: no ``analysis_runs`` row is created (that is 2.6). Progress
and failure live in ``ingestion_watermarks`` + the returned :class:`BackfillReport`.

Integrity: no fabricated bars; interior no-trade gaps stay gaps (docs/05 §3.4);
the repair pass only **re-verifies** a trailing window (restatements / ``is_final``
flips), it never invents a missing bar.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from analytical_core.enums import DataKind, InstrumentType, Timeframe, WatermarkStatus
from app.config import Settings, get_settings
from app.db.repositories.market_data import (
    MarketDataRepository,
    OIRow,
    UpsertCounts,
    WatermarkWrite,
)
from app.ingestion.aggregation import aggregate_m1
from app.ingestion.session import nse_session_window, trading_date_of
from app.providers.base import (
    OHLCVBar,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
)

_AGG_TIMEFRAMES = (Timeframe.M5, Timeframe.M15, Timeframe.H1)
_OI_TYPES = frozenset({InstrumentType.FUTURE, InstrumentType.OPTION})


@dataclass(frozen=True, slots=True)
class BackfillTarget:
    instrument_id: int
    provider_symbol: str
    instrument_type: InstrumentType
    contract_key: str


@dataclass(frozen=True, slots=True)
class BackfillPlan:
    m1_start: datetime
    d1_start: datetime
    end: datetime


@dataclass(slots=True)
class InstrumentReport:
    contract_key: str
    status: WatermarkStatus = WatermarkStatus.OK
    bars: dict[str, UpsertCounts] = field(default_factory=dict)
    oi: UpsertCounts = field(default_factory=UpsertCounts)
    m1_gap_count: int = 0
    error: str | None = None

    def as_dict(self) -> dict:
        return {
            "contract_key": self.contract_key,
            "status": self.status.value,
            "bars": {
                k: {"inserted": v.inserted, "updated": v.updated} for k, v in self.bars.items()
            },
            "oi": {"inserted": self.oi.inserted, "updated": self.oi.updated},
            "m1_gap_count": self.m1_gap_count,
            "error": self.error,
        }


@dataclass(slots=True)
class BackfillReport:
    provider: str
    started_at: datetime
    finished_at: datetime
    instruments: list[InstrumentReport] = field(default_factory=list)
    budget: dict = field(default_factory=dict)

    @property
    def ok(self) -> int:
        return sum(1 for r in self.instruments if r.status is WatermarkStatus.OK)

    def summary_line(self) -> str:
        wrote = sum(c.total for r in self.instruments for c in r.bars.values())
        oi = sum(r.oi.total for r in self.instruments)
        reqs = self.budget.get("granted", 0)
        waited = self.budget.get("waited_seconds", 0)
        return (
            f"provider={self.provider} instruments={len(self.instruments)} ok={self.ok} "
            f"bars_upserted={wrote} oi_upserted={oi} requests={reqs} waited_s={waited}"
        )

    def as_dict(self) -> dict:
        return {
            "provider": self.provider,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "budget": self.budget,
            "instruments": [r.as_dict() for r in self.instruments],
        }


@dataclass(slots=True)
class _Fetched:
    target: BackfillTarget
    d1: list[OHLCVBar]
    m1: list[OHLCVBar]
    error: Exception | None = None


def _last_final_ts(bars: Sequence[OHLCVBar]) -> datetime | None:
    finals = [b.ts for b in bars if b.is_final]
    return max(finals) if finals else None


def _session_floor(ts: datetime) -> datetime:
    """Snap a candidate start down to the NSE session open of its IST date, so a
    resumed M1 pull always covers whole sessions (aggregation needs full periods)."""
    return nse_session_window(trading_date_of(ts)).open_utc


def _m1_interior_gap_count(bars: Sequence[OHLCVBar]) -> int:
    """Missing minutes strictly *between* the first and last fetched M1 bar of
    each session — i.e. interior no-trade slots in the pulled span. Not counted:
    minutes outside the pulled window, or the overnight gap between sessions.
    """
    by_date: dict[object, list[datetime]] = {}
    for b in bars:
        by_date.setdefault(trading_date_of(b.ts), []).append(b.ts)
    gap = 0
    for tslist in by_date.values():
        tslist.sort()
        span = int((tslist[-1] - tslist[0]) // timedelta(minutes=1)) + 1
        gap += span - len(tslist)
    return gap


class BackfillService:
    def __init__(
        self,
        *,
        provider,
        repo: MarketDataRepository,
        budget=None,
        settings: Settings | None = None,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._provider = provider
        self._repo = repo
        self._budget = budget
        self._settings = settings or get_settings()
        self._now_fn = now_fn or (lambda: datetime.now(tz=UTC))
        self._provider_id = getattr(provider, "provider_id", self._settings.active_provider)

    # -- planning -------------------------------------------------------------
    def _plan(
        self,
        target: BackfillTarget,
        *,
        start: datetime | None,
        end: datetime,
        repair_only: bool,
    ) -> BackfillPlan:
        s = self._settings
        k = s.backfill_repair_lookback_bars

        wm_m1 = self._repo.get_watermark(
            instrument_id=target.instrument_id,
            timeframe=Timeframe.M1,
            data_kind=DataKind.OHLCV,
            provider=self._provider_id,
        )
        wm_d1 = self._repo.get_watermark(
            instrument_id=target.instrument_id,
            timeframe=Timeframe.D1,
            data_kind=DataKind.OHLCV,
            provider=self._provider_id,
        )

        if repair_only:
            m1_candidate = (
                (wm_m1.last_complete_ts - timedelta(minutes=k))
                if wm_m1 and wm_m1.last_complete_ts
                else end - timedelta(days=s.backfill_repair_window_days)
            )
            d1_candidate = (
                (wm_d1.last_complete_ts - timedelta(days=k))
                if wm_d1 and wm_d1.last_complete_ts
                else end - timedelta(days=s.backfill_repair_window_days)
            )
        else:
            m1_floor = start or (end - timedelta(days=s.backfill_m1_days))
            d1_floor = start or (end - timedelta(days=s.backfill_d1_days))
            # resume from the watermark (re-fetch the forming tail), else the floor
            m1_candidate = max(
                m1_floor,
                (
                    (wm_m1.last_complete_ts - timedelta(minutes=k))
                    if wm_m1 and wm_m1.last_complete_ts
                    else m1_floor
                ),
            )
            d1_candidate = max(
                d1_floor,
                (
                    (wm_d1.last_complete_ts - timedelta(days=k))
                    if wm_d1 and wm_d1.last_complete_ts
                    else d1_floor
                ),
            )

        return BackfillPlan(
            m1_start=_session_floor(m1_candidate),
            d1_start=d1_candidate,
            end=end,
        )

    # -- fetch (concurrent, network only) ----------------------------------
    def _fetch(self, target: BackfillTarget, plan: BackfillPlan) -> _Fetched:
        out = _Fetched(target=target, d1=[], m1=[])
        try:
            if Timeframe.D1 in self._timeframes:
                out.d1 = list(
                    self._provider.fetch_ohlcv(
                        target.provider_symbol, Timeframe.D1, plan.d1_start, plan.end
                    )
                )
            out.m1 = list(
                self._provider.fetch_ohlcv(
                    target.provider_symbol, Timeframe.M1, plan.m1_start, plan.end
                )
            )
        except (ProviderRateLimitError, ProviderAuthError, ProviderError) as exc:
            out.error = exc  # surfaced per-instrument in the report; never crashes the run
        return out

    # -- persist (serial, single session) --------------------------------
    def _persist(self, fetched: _Fetched) -> InstrumentReport:
        t = fetched.target
        now = self._now_fn()
        rep = InstrumentReport(contract_key=t.contract_key)

        if isinstance(fetched.error, ProviderRateLimitError):
            rep.status = WatermarkStatus.RATE_LIMITED
        elif isinstance(fetched.error, ProviderAuthError):
            rep.status = WatermarkStatus.AUTH_FAILED
        elif fetched.error is not None:
            rep.status = WatermarkStatus.ERROR
        rep.error = None if fetched.error is None else str(fetched.error)

        # ---- D1 ----------------------------------------------------------
        if fetched.d1:
            rep.bars["D1"] = self._repo.upsert_ohlcv_bars(
                instrument_id=t.instrument_id,
                timeframe=Timeframe.D1,
                provider=self._provider_id,
                bars=fetched.d1,
            )
        self._write_wm(t, Timeframe.D1, DataKind.OHLCV, _last_final_ts(fetched.d1), now, rep)

        # ---- M1 + per-candle OI ---------------------------------------
        if fetched.m1:
            rep.bars["M1"] = self._repo.upsert_ohlcv_bars(
                instrument_id=t.instrument_id,
                timeframe=Timeframe.M1,
                provider=self._provider_id,
                bars=fetched.m1,
            )
            rep.m1_gap_count = _m1_interior_gap_count(fetched.m1)

        oi_rows: list[OIRow] = []
        if t.instrument_type in _OI_TYPES:
            oi_rows = [
                OIRow(ts=b.ts, oi=int(b.open_interest), is_final=b.is_final)
                for b in fetched.m1
                if b.open_interest is not None
            ]
        if oi_rows:
            rep.oi = self._repo.upsert_open_interest(
                instrument_id=t.instrument_id,
                timeframe=Timeframe.M1,
                provider=self._provider_id,
                rows=oi_rows,
            )
        m1_final = _last_final_ts(fetched.m1)
        self._write_wm(t, Timeframe.M1, DataKind.OHLCV, m1_final, now, rep)
        if t.instrument_type in _OI_TYPES:
            oi_final = max((r.ts for r in oi_rows if r.is_final), default=None)
            self._write_wm(t, Timeframe.M1, DataKind.OI, oi_final, now, rep)

        # ---- aggregate M1 -> M5/M15/H1 ------------------------------
        # Options are chain-only (LTP + OI); skip the multi-timeframe aggregation
        # to keep a wide option universe within the cycle budget (docs/04 §2.3).
        agg_types = () if t.instrument_type is InstrumentType.OPTION else _AGG_TIMEFRAMES
        for tf in agg_types:
            if tf not in self._timeframes or not fetched.m1:
                continue
            agg = aggregate_m1(fetched.m1, tf, now=now)
            if agg.bars:
                rep.bars[tf.value] = self._repo.upsert_ohlcv_bars(
                    instrument_id=t.instrument_id,
                    timeframe=tf,
                    provider=self._provider_id,
                    bars=agg.bars,
                )
            self._write_wm(t, tf, DataKind.OHLCV, _last_final_ts(agg.bars), now, rep)

        return rep

    def _write_wm(
        self,
        target: BackfillTarget,
        timeframe: Timeframe,
        data_kind: DataKind,
        last_final_ts: datetime | None,
        now: datetime,
        rep: InstrumentReport,
    ) -> None:
        prev = self._repo.get_watermark(
            instrument_id=target.instrument_id,
            timeframe=timeframe,
            data_kind=data_kind,
            provider=self._provider_id,
        )
        prev_ts = prev.last_complete_ts if prev else None
        # never move the watermark backwards or past a non-final bar
        new_ts = max(filter(None, [prev_ts, last_final_ts]), default=None)
        self._repo.upsert_watermark(
            WatermarkWrite(
                instrument_id=target.instrument_id,
                timeframe=timeframe,
                data_kind=data_kind,
                provider=self._provider_id,
                last_complete_ts=new_ts,
                last_verified_ts=now,
                last_attempt_at=now,
                last_status=rep.status,
                detail={"contract_key": target.contract_key},
            )
        )

    # -- entrypoint --------------------------------------------------------
    def run(
        self,
        targets: Sequence[BackfillTarget],
        *,
        timeframes: Sequence[Timeframe] = (Timeframe.M1, Timeframe.D1, *_AGG_TIMEFRAMES),
        start: datetime | None = None,
        end: datetime | None = None,
        repair_only: bool = False,
        concurrency: int | None = None,
    ) -> BackfillReport:
        self._timeframes = frozenset(timeframes)
        started = self._now_fn()
        end = end or started
        workers = concurrency or self._settings.provider_concurrency

        plans = {
            t.instrument_id: self._plan(t, start=start, end=end, repair_only=repair_only)
            for t in targets
        }

        fetched: list[_Fetched] = []
        if workers > 1 and len(targets) > 1:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                fetched = list(pool.map(lambda t: self._fetch(t, plans[t.instrument_id]), targets))
        else:
            fetched = [self._fetch(t, plans[t.instrument_id]) for t in targets]

        report = BackfillReport(provider=self._provider_id, started_at=started, finished_at=started)
        for f in fetched:  # serial persistence on the caller's single session
            report.instruments.append(self._persist(f))
        report.finished_at = self._now_fn()
        report.budget = self._budget.snapshot() if self._budget is not None else {}
        return report
