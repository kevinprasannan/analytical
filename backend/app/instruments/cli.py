"""``analytical-instruments`` — registry sync + config-driven universe selection.

    analytical-instruments sync --master-file path/to/NSE.json[.gz]
    analytical-instruments build-universe --master-file path/to/NSE.json[.gz]

``sync`` ingests a whole provider master into the canonical registry (no
tracking). ``build-universe`` reads ``option_selection.*`` from ``app_settings``,
selects the tracked set (indices + near/next futures + option chains within
``ATM ± strike_window`` for the next ``max_expiries`` expiries) and rolls
``is_tracked`` to match — idempotent, so re-running weekly performs the roll.
"""

from __future__ import annotations

import argparse
import json
import sys

from app.config import get_settings
from app.db.repositories.instrument_registry import SaInstrumentRegistryRepository
from app.db.session import session_scope
from app.instruments.registry import sync_instruments
from app.instruments.roll import download_upstox_masters, roll_universe
from app.providers.upstox.instrument_master import records_from_master


def _sync(master_file: str | None, provider: str, as_json: bool) -> int:
    settings = get_settings()
    path = master_file or settings.upstox_instrument_master_file
    if not path:
        sys.stderr.write(
            "error: no master file (pass --master-file or set "
            "ANALYTICAL_UPSTOX_INSTRUMENT_MASTER_FILE)\n"
        )
        return 2
    records, normalise_rejections = records_from_master(path)
    with session_scope(settings) as db:
        report = sync_instruments(
            records,
            provider=provider,
            repo=SaInstrumentRegistryRepository(db),
            extra_rejections=normalise_rejections,
        )
    if as_json:
        sys.stdout.write(
            json.dumps(
                {
                    "provider": report.provider,
                    "rows_in_master": report.rows_in_master,
                    "accepted": report.accepted,
                    "created": report.created,
                    "updated": report.updated,
                    "remapped": report.remapped,
                    "unchanged": report.unchanged,
                    "deactivated": report.deactivated,
                    "quarantined": [
                        {"stage": q.stage, "reason": q.reason, "provider_symbol": q.provider_symbol}
                        for q in report.quarantined
                    ],
                },
                indent=2,
            )
            + "\n"
        )
    else:
        sys.stdout.write(report.summary_line() + "\n")
        for q in report.quarantined:
            sys.stdout.write(f"  quarantined [{q.stage}] {q.provider_symbol or '-'}: {q.reason}\n")
    return 0


def _build_universe(
    master_files: list[str],
    provider: str,
    spot_args: list[str],
    as_json: bool,
    refresh_master: bool,
) -> int:
    settings = get_settings()
    if refresh_master:
        try:
            paths = [str(p) for p in download_upstox_masters(settings.upstox_master_dir)]
        except Exception as exc:  # noqa: BLE001 - surface the fetch error to the CLI
            sys.stderr.write(f"error: master download failed: {exc}\n")
            return 3
    else:
        paths = list(master_files) or (
            [settings.upstox_instrument_master_file]
            if settings.upstox_instrument_master_file
            else []
        )
    if not paths:
        sys.stderr.write(
            "error: no master file (pass --master-file, --refresh-master, or set env)\n"
        )
        return 2

    overrides: dict[str, float] = {}
    for a in spot_args:
        k, _, v = a.partition("=")
        overrides[k.strip().upper()] = float(v)

    with session_scope(settings) as db:
        result = roll_universe(db, master_paths=paths, provider=provider, spot_overrides=overrides)

    if as_json:
        sys.stdout.write(json.dumps(result, indent=2) + "\n")
    else:
        sys.stdout.write(
            f"universe: {result['selected']} contracts selected for "
            f"{result['underlyings']} -> {result['now_tracked']} tracked "
            f"(+{result['tracked_added']}/-{result['tracked_removed']}); "
            f"synced +{result['synced_created']}/~{result['synced_updated']}\n"
        )
        for u, meta in result["per_underlying"].items():
            lo, hi = meta["strike_lo"], meta["strike_hi"]
            sys.stdout.write(
                f"  {u}: spot {result['spots'].get(u, '?')}, "
                f"futures {meta['future_expiries']}, "
                f"options {meta['option_expiries']} strikes {lo}..{hi}\n"
            )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="analytical-instruments")
    sub = parser.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("sync", help="sync the whole registry from a local provider master file")
    s.add_argument("--master-file")
    s.add_argument("--provider", default="upstox")
    s.add_argument("--json", action="store_true")

    b = sub.add_parser("build-universe", help="select + roll the tracked universe from config")
    b.add_argument(
        "--master-file",
        action="append",
        default=[],
        help="local provider master (repeatable — e.g. NSE + BSE for a multi-exchange universe)",
    )
    b.add_argument("--provider", default="upstox")
    b.add_argument("--spot", action="append", default=[], help="SYMBOL=price override, repeatable")
    b.add_argument(
        "--refresh-master",
        action="store_true",
        help="download the current Upstox NSE+BSE masters first (ignores --master-file)",
    )
    b.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    if args.cmd == "sync":
        return _sync(args.master_file, args.provider, args.json)
    if args.cmd == "build-universe":
        return _build_universe(
            args.master_file, args.provider, args.spot, args.json, args.refresh_master
        )
    return 2  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
