"""Typed application settings (docs/02 §6.1).

Sources: environment variables + an optional ``.env`` file. Engine/scoring
parameters that the owner edits at runtime live in the ``app_settings`` table
(docs/03 §5.1), not here — this object holds process/deployment config only.

The confirmed Phase-0 defaults (docs/02 §8.1) are the defaults below and are also
seeded into ``app_settings`` by the ``seed`` command.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ANALYTICAL_",
        # backend/.env for a local run; deploy/.env is the compose template and a
        # fallback when running CLIs from backend/. Real env vars still win.
        env_file=(".env", "../deploy/.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- database -------------------------------------------------------------
    database_url: str = Field(
        default="postgresql+psycopg://analytical:analytical@localhost:5432/analytical",
        description="SQLAlchemy URL. Phase 1 targets PostgreSQL 16 only.",
    )

    # --- provider seam -----------------------------------------------------
    active_provider: str = Field(
        default="stub",
        description="Provider id resolved by app.providers.registry ('stub' | 'upstox').",
    )
    provider_validation_status_path: str = Field(
        default="../docs/11-provider-validation.status.yaml",
        description="Path (relative to backend/) to the machine-readable PV gate file.",
    )

    # --- Upstox auth (docs/11 PV-1: daily-manual token, no refresh) -------
    upstox_access_token: SecretStr | None = Field(
        default=None,
        description="Runtime Upstox access token. Prefer the token file via "
        "`analytical-provider set-token`; this env var is a convenience.",
    )
    upstox_token_file: str = Field(
        default=".secrets/upstox_token.json",
        description="Git-ignored path (relative to CWD) for the runtime Upstox token.",
    )
    upstox_api_key: SecretStr | None = Field(
        default=None,
        description="Upstox app API key (client_id) — used only by "
        "`analytical-provider login` to run the daily OAuth code exchange.",
    )
    upstox_api_secret: SecretStr | None = Field(
        default=None, description="Upstox app API secret (client_secret) — `login` only."
    )
    upstox_redirect_uri: str = Field(
        default="http://localhost",
        description="Upstox app redirect URI; must match the app registration exactly.",
    )
    upstox_base_url: str = Field(default="https://api.upstox.com")
    upstox_api_version: str = Field(default="v3")
    upstox_instrument_master_file: str | None = Field(
        default=None,
        description="Local path to an Upstox NSE instrument master (.json/.json.gz). "
        "Phase 2.2 is fixture-driven — no automatic download.",
    )
    upstox_master_dir: str = Field(
        default=".data/upstox",
        description="Directory of Upstox instrument master files (*.json / *.json.gz) "
        "searched by GET /instruments/catalog for the add-instrument autosuggest. "
        "Git-ignored; refresh periodically.",
    )
    upstox_candle_ts_is_bar_close: bool = Field(
        default=False,
        description="docs/11 PV-7 fallback: if the provider ever returns bar-CLOSE "
        "timestamps, the candle adapter subtracts one interval to derive bar-open. "
        "Upstox v3 is documented as candle-start, so this stays False unless a live "
        "checkpoint proves otherwise.",
    )

    # --- provider HTTP / rate limiting (docs/02 §6.7, docs/11 PV-5) --------
    provider_max_rps: float = Field(
        default=8.0,
        description="Client-side request ceiling (docs/02 §6.7 PROVIDER_MAX_RPS). "
        "Under the Upstox 500/min ≈ 8.3/s limit.",
    )
    provider_concurrency: int = Field(
        default=4, description="Bounded parallelism for multi-instrument pulls (reserved for 2.5)."
    )
    provider_30min_budget: int = Field(
        default=1800,
        description="Rolling 30-minute request budget (10% headroom under Upstox 2000). "
        "Reserved for the backfill ledger in 2.5.",
    )
    provider_http_timeout_seconds: float = Field(default=10.0)
    provider_max_retries: int = Field(
        default=4,
        description="Retry attempts on a throttle response before ProviderRateLimitError.",
    )
    provider_backoff_base_seconds: float = Field(
        default=0.5, description="Exponential-backoff base: sleep = base * 2**attempt."
    )

    # --- historical backfill (docs/10 Phase 2, docs/03 §6) ---------------
    backfill_m1_days: int = Field(
        default=10,
        description="Default M1 backfill horizon when there is no watermark and no "
        "--start (M1 retention is 10 days, docs/03 §6).",
    )
    backfill_d1_days: int = Field(
        default=800,
        description="Default D1 backfill horizon (≥ 200-SMA + cross window; D1 is kept "
        "indefinitely so a wider one-off --start is fine).",
    )
    backfill_repair_lookback_bars: int = Field(
        default=5,
        description="Repair pass re-verifies this many trailing finalized bars/periods "
        "(catches provider restatements and is_final flips, docs/02 §3.4).",
    )
    backfill_repair_window_days: int = Field(
        default=3,
        description="Trailing window re-verified by --repair-only when there is no watermark.",
    )
    ingestion_lookback_days: int = Field(
        default=1,
        description="How far back the live INGEST phase pulls when there is no watermark "
        "(the forming tail once a watermark exists). Deep history is `analytical-backfill`.",
    )

    # --- API auth seam (docs/02 §6.6) -----------------------------------
    local_api_token: str | None = Field(
        default=None,
        description="If set, /api/v1 requires 'Authorization: Bearer <token>'.",
    )

    # --- confirmed Phase-0 defaults (docs/02 §8.1) ---------------------
    cycle_interval_seconds: int = 180
    finalize_grace_seconds: int = 90
    idempotency_window_seconds: int = Field(
        default=600,
        description="POST /runs replays the response for a repeated Idempotency-Key "
        "seen within this window instead of starting another cycle (docs/07 §3).",
    )

    # --- streaming ingestion (docs/02 §3.4, Phase S) -----------------
    stream_enabled: bool = Field(
        default=False,
        description="Master switch for the optional streaming ingestor "
        "(`analytical-worker stream`). The deterministic cycle never depends on it; "
        "when true, a separate process feeds the forming M1 bar + live OI.",
    )
    stream_mode: str = Field(
        default="full",
        description="Feed mode: 'ltpc' (price only) | 'full' (price + cumulative "
        "session volume + OI).",
    )
    stream_flush_seconds: int = Field(
        default=10,
        description="How often the M1 accumulator flushes forming/finalised bars to "
        "the DB between ticks.",
    )
    stream_reconnect_seconds: int = Field(
        default=5,
        description="Delay before reconnecting after the streaming feed drops or errors.",
    )
    run_stream_in_process: bool = Field(
        default=False,
        description="Run the streaming ingestor in a background thread inside the API "
        "process (needs stream_enabled). Off by default — the `streamer` service / "
        "`analytical-worker stream` owns it.",
    )

    # --- astro cross-check (docs/13) --------------------------------
    astro_latitude: float = Field(
        default=19.076090, description="Observer latitude for the astro dataset (Mumbai)."
    )
    astro_longitude: float = Field(
        default=72.877426, description="Observer longitude for the astro dataset (Mumbai)."
    )
    astro_hour_ist: float = Field(
        default=9.0, description="Clock time (IST, decimal hours) each astro snapshot is taken at."
    )
    astro_start_date: str = Field(
        default="2000-01-01", description="Default first date for `analytical-astro build`."
    )
    astro_daily_catchup: bool = Field(
        default=True,
        description="`analytical-worker serve` fills any missing weekday astro rows up to "
        "today's IST date (offline, deterministic, idempotent). Set false to manage the "
        "dataset only via `analytical-astro build`.",
    )
    astro_catchup_interval_seconds: int = Field(
        default=6 * 3600,
        description="How often the worker's astro catch-up job runs (also once on start).",
    )

    # --- worker / scheduler (docs/02 §3.7) ----------------------------
    run_worker_in_process: bool = False
    scheduler_session_only: bool = Field(
        default=True,
        description="Gate scheduled ticks to the NSE trading session (per market_calendar). "
        "Set false to tick around the clock (dev against a stub/mock provider).",
    )
    scheduler_warmup_seconds: int = Field(
        default=300,
        description="Begin ticking this many seconds before session open.",
    )
    scheduler_cooldown_seconds: int = Field(
        default=300,
        description="Keep ticking this many seconds after session close so the final "
        "bars finalize and get ingested (see finalize_grace_seconds).",
    )
    scheduler_segment: str = Field(
        default="FO",
        description="market_calendar segment the session gate reads (NSE exchange).",
    )
    scheduler_run_on_start: bool = Field(
        default=False,
        description="Run one cycle immediately when `analytical-worker serve` starts, "
        "before the first interval tick.",
    )

    # --- daily universe roll (docs/04 §2.3) ------------------------------
    universe_daily_roll: bool = Field(
        default=True,
        description="`analytical-worker serve` re-downloads the Upstox instrument master "
        "and re-rolls the tracked option universe against the current spot (keeps the "
        "strikes centred on the money, picks up new weekly expiries). Idempotent.",
    )
    universe_roll_interval_seconds: int = Field(
        default=6 * 3600,
        description="How often the worker's universe-roll job runs (also once on start).",
    )

    # --- nightly DB backup ---------------------------------------------
    db_backup_enabled: bool = Field(
        default=True,
        description="`analytical-worker serve` runs a nightly pg_dump to db_backup_dir.",
    )
    db_backup_dir: str = Field(default="deploy/backups", description="Where dumps are written.")
    db_backup_keep: int = Field(default=14, description="Newest N dumps to retain; older pruned.")
    db_backup_interval_seconds: int = Field(default=24 * 3600)
    db_backup_timeout_seconds: int = Field(default=600)
    pg_dump_path: str = Field(
        default="pg_dump",
        description="pg_dump executable (name on PATH or an absolute path).",
    )

    # --- build / observability ---------------------------------------
    git_sha: str | None = Field(
        default=None,
        description="Commit the running image was built from; set via ANALYTICAL_GIT_SHA "
        "(build arg in deploy/backend.Dockerfile). Surfaced by GET /meta/versions.",
    )

    # --- logging -------------------------------------------------------
    log_level: str = "INFO"
    log_json: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
