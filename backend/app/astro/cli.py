"""``analytical-astro`` — build / inspect the astro cross-check dataset (docs/13).

    analytical-astro build                       # 2000-01-01 -> today, weekdays, + Shadbala
    analytical-astro build --start 2023-08-30 --no-shadbala
    analytical-astro build --resume              # continue after the last stored date
    analytical-astro show 2024-01-01             # positions + Shadbala for one date
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime, timedelta

from app.astro import backfill as bf
from app.astro.ephemeris import AstroEngine
from app.astro.shadbala import compute_shadbala
from app.config import get_settings
from app.db.session import session_scope


def _today_ist() -> date:
    return datetime.now(tz=bf.IST).date()


def _cmd_build(args: argparse.Namespace) -> int:
    s = get_settings()
    lat = args.lat if args.lat is not None else s.astro_latitude
    lon = args.lon if args.lon is not None else s.astro_longitude
    end = date.fromisoformat(args.end) if args.end else _today_ist()
    engine = AstroEngine()

    with session_scope(s) as session:
        if args.resume and not args.start:
            last = bf.last_built_date(session)
            start = (last + timedelta(days=1)) if last else date.fromisoformat(s.astro_start_date)
        else:
            start = date.fromisoformat(args.start or s.astro_start_date)
        if start > end:
            sys.stdout.write(f"nothing to do (start {start} > end {end})\n")
            return 0
        sys.stdout.write(
            f"building {start}..{end} weekdays  lat={lat} lon={lon} "
            f"shadbala={not args.no_shadbala}\n"
        )
        rep = bf.build(
            session,
            start=start,
            end=end,
            latitude=lat,
            longitude=lon,
            hour_ist=s.astro_hour_ist,
            with_shadbala=not args.no_shadbala and not args.days_only,
            with_positions=not args.days_only,
            engine=engine,
        )
    sys.stdout.write(rep.line() + "\n")
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    s = get_settings()
    d = date.fromisoformat(args.date)
    dt = datetime(d.year, d.month, d.day, tzinfo=bf.IST) + timedelta(hours=s.astro_hour_ist)
    engine = AstroEngine()
    sys.stdout.write(
        f"{d}  {dt.astimezone(UTC):%Y-%m-%d %H:%MZ}  ayanamsha={engine.ayanamsha(dt):.5f}\n"
    )
    for p in engine.positions(dt):
        sys.stdout.write(
            f"  {p.graha:8} {p.longitude:9.4f}  {p.rashi:10} {p.degree:7.3f}  "
            f"{p.nakshatra:16} p{p.pada}  {'R' if p.retrograde else 'D'}  {p.dignity}\n"
        )
    if not args.no_shadbala:
        sys.stdout.write("  --- Shadbala (rupa / required / ratio / rank) ---\n")
        for g, r in compute_shadbala(engine, dt, s.astro_latitude, s.astro_longitude).items():
            sys.stdout.write(
                f"  {g:8} {r.total_rupa:6.2f} / {r.required_rupa:4.1f} "
                f"= {r.ratio:5.2f}  rank {r.rank}\n"
            )
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="analytical-astro")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="generate/refresh the weekday astro dataset")
    b.add_argument("--start", help="ISO date (default: settings astro_start_date / 2000-01-01)")
    b.add_argument("--end", help="ISO date (default: today IST)")
    b.add_argument("--resume", action="store_true", help="continue after the last stored date")
    b.add_argument("--no-shadbala", action="store_true", help="positions + days only")
    b.add_argument(
        "--days-only",
        action="store_true",
        help="only (re)build astro_days (skip positions/shadbala)",
    )
    b.add_argument("--lat", type=float, default=None)
    b.add_argument("--lon", type=float, default=None)

    sh = sub.add_parser("show", help="print positions + Shadbala for one date")
    sh.add_argument("date", help="ISO date")
    sh.add_argument("--no-shadbala", action="store_true")

    st = sub.add_parser("study", help="astro x NIFTY-daily cross-check (descriptive stats)")
    st.add_argument("--underlying", default="NIFTY-INDEX")
    st.add_argument("--start", help="ISO date")
    st.add_argument("--end", help="ISO date")
    st.add_argument("--json", metavar="PATH", help="write the full result as JSON")

    args = p.parse_args(argv)
    if args.cmd == "build":
        return _cmd_build(args)
    if args.cmd == "show":
        return _cmd_show(args)
    if args.cmd == "study":
        return _cmd_study(args)
    return 2


def _cmd_study(args: argparse.Namespace) -> int:
    import json

    from app.astro.study import result_to_dict, run_study

    s = get_settings()
    with session_scope(s) as session:
        res = run_study(
            session,
            underlying=args.underlying,
            start=date.fromisoformat(args.start) if args.start else None,
            end=date.fromisoformat(args.end) if args.end else None,
        )
    d = result_to_dict(res)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(d, fh, indent=2)
        sys.stdout.write(f"wrote {args.json}\n")
    b = d["baseline"]
    sys.stdout.write(f"{d['underlying']}  {d['first']}..{d['last']}  n={d['n_days']}\n")
    sys.stdout.write(
        f"baseline mean={b['mean_ret']:+.3f}%  up={b['pct_up']:.1f}%  "
        f"range={b['mean_range']:.2f}%\n\n"
    )
    for row in d["by_weekday"]:
        sys.stdout.write(
            f"  {row['key']:10} n={row['n']:5} mean={row['mean_ret']:+.3f}%  "
            f"up={row['pct_up']:.1f}%\n"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
