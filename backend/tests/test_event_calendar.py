"""Economic event calendar (docs/05 §9g) — recurring-date event types
(not live news) with a before/after price read."""

from __future__ import annotations

from datetime import date, timedelta

from analytical_core.event_calendar import (
    COMEX_GOLD_EXPIRY,
    COMEX_SILVER_EXPIRY,
    ECB_RATE_DECISION,
    FED_RATE_DECISION,
    FNO_EXPIRY,
    INDIA_GST_COLLECTION,
    MCX_GOLD_EXPIRY,
    MCX_SILVER_EXPIRY,
    RBI_RATE_DECISION,
    US_JOBLESS_CLAIMS,
    US_JOBS_REPORT,
    scan_event_calendar,
)


def _business_days(start: date, end: date) -> list[str]:
    out: list[str] = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def test_insufficient_data():
    r = scan_event_calendar(["2025-01-01"], [100.0])
    assert r.status == "INSUFFICIENT_DATA"


def test_first_friday_of_january_2025_is_the_3rd():
    dates = _business_days(date(2025, 1, 1), date(2025, 1, 31))
    closes = [100.0 + i * 0.1 for i in range(len(dates))]
    r = scan_event_calendar(dates, closes, params={"future_horizon_months": 0})
    jobs = [o for o in r.occurrences if o.event_type == US_JOBS_REPORT]
    assert any(o.event_date == "2025-01-03" for o in jobs)


def test_gst_events_start_no_earlier_than_launch_date():
    dates = _business_days(date(2017, 6, 1), date(2017, 8, 31))
    closes = [100.0] * len(dates)
    r = scan_event_calendar(dates, closes, params={"future_horizon_months": 0})
    gst = [o for o in r.occurrences if o.event_type == INDIA_GST_COLLECTION]
    assert all(o.event_date >= "2017-07-01" for o in gst)
    assert any(o.event_date.startswith("2017-07") for o in gst)
    assert not any(o.event_date.startswith("2017-06") for o in gst)


def test_gst_on_a_weekend_snaps_to_the_next_trading_day():
    # 2022-01-01 is a Saturday -> should snap forward to the next trading day
    dates = _business_days(date(2021, 12, 1), date(2022, 1, 31))
    closes = [100.0] * len(dates)
    r = scan_event_calendar(dates, closes, params={"future_horizon_months": 0})
    gst_jan = next(
        o
        for o in r.occurrences
        if o.event_type == INDIA_GST_COLLECTION and o.event_date.startswith("2022-01")
    )
    resolved = date.fromisoformat(gst_jan.event_date)
    assert resolved >= date(2022, 1, 1)
    assert resolved.weekday() < 5


def test_occurrence_within_series_gets_prior_and_next_close():
    dates = _business_days(date(2025, 1, 1), date(2025, 1, 31))
    closes = [100.0 + i for i in range(len(dates))]  # steadily rising by 1 each day
    r = scan_event_calendar(dates, closes, params={"future_horizon_months": 0})
    jobs = next(o for o in r.occurrences if o.event_type == US_JOBS_REPORT)
    idx = dates.index(jobs.event_date)
    assert jobs.prior_close == closes[idx - 1]
    assert jobs.close == closes[idx]
    assert jobs.next_close == closes[idx + 1]
    assert jobs.change_pct is not None and jobs.change_pct > 0  # rising series


def test_future_event_beyond_the_series_has_no_price_data():
    dates = _business_days(date(2025, 1, 1), date(2025, 1, 10))
    closes = [100.0] * len(dates)
    r = scan_event_calendar(dates, closes, params={"future_horizon_months": 2})
    future = [o for o in r.occurrences if o.event_date > dates[-1]]
    assert future  # the 2-month horizon should produce some
    for o in future:
        assert o.close is None
        assert o.change_pct is None


def test_fno_expiry_dates_are_passed_through_not_generated():
    dates = _business_days(date(2025, 1, 1), date(2025, 1, 31))
    closes = [100.0] * len(dates)
    r = scan_event_calendar(
        dates,
        closes,
        fno_expiry_dates=["2025-01-28"],
        params={"future_horizon_months": 0},
    )
    expiry = [o for o in r.occurrences if o.event_type == FNO_EXPIRY]
    assert len(expiry) == 1
    assert expiry[0].event_date == "2025-01-28"
    assert expiry[0].close is not None  # it's an exact trading date in our series


def test_mcx_gold_and_silver_expiry_resolve_on_or_before_the_5th():
    dates = _business_days(date(2025, 1, 1), date(2025, 1, 31))
    closes = [100.0] * len(dates)
    r = scan_event_calendar(dates, closes, params={"future_horizon_months": 0})
    gold = [o for o in r.occurrences if o.event_type == MCX_GOLD_EXPIRY]
    silver = [o for o in r.occurrences if o.event_type == MCX_SILVER_EXPIRY]
    assert len(gold) == 1 and len(silver) == 1
    resolved = date.fromisoformat(gold[0].event_date)
    assert resolved <= date(2025, 1, 5)
    assert resolved.weekday() < 5  # snapped back to an actual trading day
    assert gold[0].event_date == silver[0].event_date  # same underlying MCX-day rule


def test_mcx_gold_silver_expiry_beyond_the_series_has_no_price_data():
    dates = _business_days(date(2025, 1, 1), date(2025, 1, 10))
    closes = [100.0] * len(dates)
    r = scan_event_calendar(dates, closes, params={"future_horizon_months": 2})
    future_gold = [
        o for o in r.occurrences if o.event_type == MCX_GOLD_EXPIRY and o.event_date > dates[-1]
    ]
    assert future_gold
    for o in future_gold:
        assert o.close is None


def test_comex_gold_and_silver_expiry_resolve_on_or_before_the_27th():
    dates = _business_days(date(2025, 1, 1), date(2025, 1, 31))
    closes = [100.0] * len(dates)
    r = scan_event_calendar(dates, closes, params={"future_horizon_months": 0})
    gold = [o for o in r.occurrences if o.event_type == COMEX_GOLD_EXPIRY]
    silver = [o for o in r.occurrences if o.event_type == COMEX_SILVER_EXPIRY]
    assert len(gold) == 1 and len(silver) == 1
    resolved = date.fromisoformat(gold[0].event_date)
    assert resolved <= date(2025, 1, 27)
    assert resolved.weekday() < 5
    assert gold[0].event_date == silver[0].event_date
    # COMEX and MCX use different day-of-month anchors -> different dates
    mcx_gold_date = next(o.event_date for o in r.occurrences if o.event_type == MCX_GOLD_EXPIRY)
    assert gold[0].event_date != mcx_gold_date


def test_ecb_dates_are_passed_through_not_generated():
    dates = _business_days(date(2025, 1, 1), date(2025, 1, 31))
    closes = [100.0] * len(dates)
    r = scan_event_calendar(
        dates, closes, ecb_dates=["2025-01-30"], params={"future_horizon_months": 0}
    )
    ecb = [o for o in r.occurrences if o.event_type == ECB_RATE_DECISION]
    assert len(ecb) == 1
    assert ecb[0].event_date == "2025-01-30"
    assert ecb[0].close is not None


def test_rbi_dates_are_passed_through_not_generated():
    dates = _business_days(date(2025, 1, 1), date(2025, 1, 31))
    closes = [100.0] * len(dates)
    r = scan_event_calendar(
        dates, closes, rbi_dates=["2025-01-08"], params={"future_horizon_months": 0}
    )
    rbi = [o for o in r.occurrences if o.event_type == RBI_RATE_DECISION]
    assert len(rbi) == 1
    assert rbi[0].event_date == "2025-01-08"
    assert rbi[0].close is not None


def test_fomc_dates_are_passed_through_not_generated():
    dates = _business_days(date(2025, 1, 1), date(2025, 1, 31))
    closes = [100.0] * len(dates)
    r = scan_event_calendar(
        dates, closes, fomc_dates=["2025-01-29"], params={"future_horizon_months": 0}
    )
    fomc = [o for o in r.occurrences if o.event_type == FED_RATE_DECISION]
    assert len(fomc) == 1
    assert fomc[0].event_date == "2025-01-29"
    assert fomc[0].close is not None  # exact trading date in our series


def test_summary_notable_move_rate_matches_the_data():
    # build a year where every jobs-report day moves exactly +1% (all "notable")
    dates = _business_days(date(2024, 1, 1), date(2024, 12, 31))
    closes = [100.0] * len(dates)
    r0 = scan_event_calendar(dates, closes, params={"future_horizon_months": 0})
    jobs_dates = {o.event_date for o in r0.occurrences if o.event_type == US_JOBS_REPORT}
    for i, d in enumerate(dates):
        if d in jobs_dates and i > 0:
            closes[i] = closes[i - 1] * 1.01
        elif i > 0:
            closes[i] = closes[i - 1]
    r = scan_event_calendar(
        dates, closes, params={"future_horizon_months": 0, "notable_move_pct": 0.5}
    )
    summary = next(s for s in r.summaries if s.event_type == US_JOBS_REPORT)
    assert summary.pct_notable_move == 100.0
    assert summary.up_count == summary.n_resolved
    assert summary.down_count == 0


def test_jobless_claims_fire_every_thursday():
    dates = _business_days(date(2025, 1, 1), date(2025, 1, 31))
    closes = [100.0] * len(dates)
    r = scan_event_calendar(dates, closes, params={"future_horizon_months": 0})
    claims = [o for o in r.occurrences if o.event_type == US_JOBLESS_CLAIMS]
    # January 2025 has 4 Thursdays: 2, 9, 16, 23, 30 -- that's 5
    assert len(claims) == 5
    for o in claims:
        assert date.fromisoformat(o.event_date).weekday() == 3  # Thursday


def test_jobless_claims_weekly_spacing_is_seven_days():
    dates = _business_days(date(2025, 1, 1), date(2025, 3, 31))
    closes = [100.0] * len(dates)
    r = scan_event_calendar(dates, closes, params={"future_horizon_months": 0})
    claim_dates = sorted(
        date.fromisoformat(o.event_date) for o in r.occurrences if o.event_type == US_JOBLESS_CLAIMS
    )
    gaps = {(b - a).days for a, b in zip(claim_dates, claim_dates[1:], strict=False)}
    assert gaps == {7}
