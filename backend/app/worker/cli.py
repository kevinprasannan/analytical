"""``analytical-worker`` — run one cycle, or the periodic scheduler loop."""

from __future__ import annotations

import argparse
import sys

from analytical_core.enums import RunPhase, RunTrigger
from app.config import get_settings
from app.logging import configure_logging
from app.worker.cycle import run_cycle
from app.worker.deps import SingleFlightBusy, worker_context


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="analytical-worker")
    sub = parser.add_subparsers(dest="command", required=True)

    p_once = sub.add_parser("run-cycle", help="run a single execution cycle and exit")
    p_once.add_argument(
        "--phases",
        default="INGEST,ANALYZE,SCORE",
        help="Comma-separated subset of INGEST,ANALYZE,SCORE",
    )

    p_serve = sub.add_parser("serve", help="run the periodic scheduler loop until stopped")
    p_serve.add_argument(
        "--run-now",
        action="store_true",
        help="run one cycle immediately on start, before the first interval tick",
    )

    p_stream = sub.add_parser(
        "stream",
        help="run the optional streaming ingestor (forming M1 bar + live OI) until stopped",
    )
    p_stream.add_argument(
        "--mode", default=None, help="feed mode override: 'ltpc' | 'full' (default: settings)"
    )

    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(level=settings.log_level, json_output=settings.log_json)

    if args.command == "serve":
        from app.worker.scheduler import serve

        return serve(settings, run_on_start=args.run_now or None)

    if args.command == "stream":
        if not settings.stream_enabled:
            sys.stdout.write(
                "streaming disabled: set ANALYTICAL_STREAM_ENABLED=true to run the ingestor\n"
            )
            return 0
        from app.ingestion.stream import serve as stream_serve

        return stream_serve(settings, mode=args.mode)

    phases = tuple(RunPhase(p.strip()) for p in args.phases.split(","))
    try:
        with worker_context(settings) as (repos, provider, app_settings):
            result = run_cycle(
                repos,
                provider,
                trigger=RunTrigger.MANUAL,
                phases=phases,
                settings=settings,
                app_settings=app_settings,
            )
    except SingleFlightBusy as exc:
        sys.stdout.write(f"skipped: {exc}\n")
        return 0
    sys.stdout.write(
        f"run_id={result.run_id} cycle_seq={result.cycle_seq} status={result.status.value}\n"
    )
    return 0 if not result.crashed else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
