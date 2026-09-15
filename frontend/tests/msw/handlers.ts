import { http, HttpResponse } from "msw";

const base = "*/api/v1";

export const handlers = [
  http.get(`${base}/health/ready`, () =>
    HttpResponse.json({
      db_ok: true,
      provider_auth: "OK",
      active_provider: "stub",
      worker_running: false,
      calendar_seeded_until: "2026-12-31",
      last_cycle_seq: 7,
      last_successful_cycle_age_seconds: 42,
      cycle_overrun: false,
    }),
  ),
  http.get(`${base}/meta/versions`, () =>
    HttpResponse.json({
      algo_version: "3.0.0",
      scoring_version: "1.0.0",
      active_provider: "stub",
      git_sha: null,
      config_params_hash: null,
      stale_results: false,
    }),
  ),
  http.get(`${base}/calendar/status`, () =>
    HttpResponse.json({
      is_open: false,
      as_of: { ist: "2026-08-29T12:00:00+05:30", utc: "2026-08-29T06:30:00Z" },
      session_type: null,
      next_open: { ist: "2026-08-31T09:15:00+05:30", utc: "2026-08-31T03:45:00Z" },
      next_close: null,
      seeded_until: "2026-12-31",
    }),
  ),
  http.get(`${base}/config`, () =>
    HttpResponse.json({
      effective: { cycle_interval_seconds: 180, "scoring.min_confidence": 0.35 },
      sections: { cadence: { cycle_interval_seconds: 180 }, scoring: { min_confidence: 0.35 } },
      config_params_hash: "abcdef0123456789",
    }),
  ),
  http.get(`${base}/scores`, ({ request }) => {
    const url = new URL(request.url);
    return HttpResponse.json({
      items: [
        {
          instrument_id: 1,
          contract_key: "NIFTY-FUT-2026-09",
          symbol: "NIFTY",
          timeframe: url.searchParams.get("timeframe"),
          composite_score: 42.5,
          raw_label: "BULLISH",
          effective_label: "BULLISH",
          confidence: 0.71,
          low_confidence: false,
          as_of_ts: new Date().toISOString(),
          run_id: 7,
          delta_vs_previous: 0,
          warnings: [],
        },
      ],
      total: 1,
      limit: 500,
      offset: 0,
      next_cursor: null,
    });
  }),
];
