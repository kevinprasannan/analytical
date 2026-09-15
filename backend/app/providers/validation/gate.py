"""Gate evaluation + CLI (`analytical-gate`).

Passes only when every ``blocks_phase_2`` PV item is ``CONFIRMED`` or
``ACCEPTED_FALLBACK`` and every resolved row is well-formed. Reports every OPEN
item. Exits non-zero when blocked. Never modifies the status file.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app.providers.validation.loader import ValidationSchemaError, load_status
from app.providers.validation.status import BRANCH_REQUIRED, ValidationStatusFile

#: Files permitted in ``app/providers/upstox/`` while the gate is blocked
#: (docs/09 §2.12 allow-list).
UPSTOX_STUB_ALLOWLIST: frozenset[str] = frozenset(
    {"__init__.py", "stub.py", "capabilities.py", "gate.py"}
)

_EVIDENCE_RE = re.compile(r"^\S.* — \d{4}-\d{2}-\d{2}$")


@dataclass(slots=True)
class GateResult:
    blocked: bool
    open_items: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    checked_items: list[str] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        return 0 if not self.blocked else 1


def evaluate(
    status: ValidationStatusFile,
    *,
    upstox_dir: Path | None = None,
    docs_table_path: Path | None = None,
) -> GateResult:
    result = GateResult(blocked=False)

    for item in status.blocking_items():
        result.checked_items.append(item.id)
        if item.is_open:
            result.open_items.append(item.id)
            continue
        # resolved -> well-formedness
        if item.decided_on is None:
            result.errors.append(f"{item.id}: resolved but 'decided_on' is null")
        if item.status == "CONFIRMED":
            if not item.evidence:
                result.errors.append(f"{item.id}: CONFIRMED but 'evidence' is empty")
            else:
                for ev in item.evidence:
                    if not _EVIDENCE_RE.match(ev):
                        result.errors.append(
                            f"{item.id}: evidence entry not '<text> — YYYY-MM-DD': {ev!r}"
                        )
        if item.status == "ACCEPTED_FALLBACK" and not item.fallback_ref:
            result.errors.append(f"{item.id}: ACCEPTED_FALLBACK but 'fallback_ref' is null")
        if item.id in BRANCH_REQUIRED:
            allowed = BRANCH_REQUIRED[item.id]
            if item.branch not in allowed:
                result.errors.append(
                    f"{item.id}: resolved but 'branch' {item.branch!r} not in {sorted(allowed)}"
                )

    # gate_blocking_ids sanity
    from app.providers.validation.status import DEFAULT_BLOCKING_IDS

    if tuple(status.gate_blocking_ids) != DEFAULT_BLOCKING_IDS:
        got = list(status.gate_blocking_ids)
        want = list(DEFAULT_BLOCKING_IDS)
        result.errors.append(f"meta.gate_blocking_ids {got} != {want}")

    if upstox_dir is not None and status.open_blocking_ids():
        result.errors.extend(_check_upstox_allowlist(upstox_dir))

    if docs_table_path is not None:
        result.errors.extend(_check_docs_table_parity(docs_table_path, status))

    result.blocked = bool(result.open_items) or bool(result.errors)
    return result


def _check_upstox_allowlist(upstox_dir: Path) -> list[str]:
    if not upstox_dir.is_dir():
        return [f"upstox dir not found: {upstox_dir}"]
    errs: list[str] = []
    for child in sorted(upstox_dir.iterdir()):
        if child.name == "__pycache__":
            continue
        if not child.is_file() or child.name not in UPSTOX_STUB_ALLOWLIST:
            errs.append(
                f"upstox stub allow-list violated while PV gate is OPEN: unexpected {child.name!r}"
            )
    return errs


def _check_docs_table_parity(md_path: Path, status: ValidationStatusFile) -> list[str]:
    if not md_path.is_file():
        return [f"docs table not found: {md_path}"]
    text = md_path.read_text(encoding="utf-8")
    table_status: dict[str, str] = {}
    for m in re.finditer(r"^\|\s*(PV-\d)\s*\|(.+?)\|(.+?)\|.*$", text, re.MULTILINE):
        pv_id = m.group(1)
        raw_status = m.group(3)
        token = raw_status.replace("*", "").strip()
        token = token.split("(")[0].strip()  # drop "(non-blocking)"
        table_status[pv_id] = token
    errs: list[str] = []
    for pv_id, item in status.items.items():
        if pv_id not in table_status:
            errs.append(f"docs/11 §1 table has no row for {pv_id}")
        elif table_status[pv_id] != item.status:
            errs.append(
                f"docs/11 §1 table {pv_id}={table_status[pv_id]!r} != status file {item.status!r}"
            )
    return errs


def render(result: GateResult, status: ValidationStatusFile) -> str:
    lines: list[str] = []
    header = "PHASE 2 GATE: BLOCKED" if result.blocked else "PHASE 2 GATE: CLEAR"
    lines.append(header)
    lines.append("")
    for item in status.blocking_items():
        lines.append(f"{item.id} {item.status}")
    non_blocking = [i for i in status.items.values() if not i.blocks_phase_2]
    for item in non_blocking:
        lines.append(f"{item.id} {item.status} (non-blocking)")
    if result.errors:
        lines.append("")
        lines.append("ERRORS:")
        lines.extend(f"  - {e}" for e in result.errors)
    lines.append("")
    if result.blocked:
        n_open = len(result.open_items)
        lines.append(f"BLOCKED: {n_open} OPEN blocking item(s), {len(result.errors)} error(s).")
    else:
        lines.append("CLEAR: all blocking PV items are CONFIRMED or ACCEPTED_FALLBACK.")
    return "\n".join(lines) + "\n"


def _default_paths() -> tuple[Path, Path, Path]:
    """Resolve defaults relative to this file (works from backend/ or repo root)."""
    here = Path(__file__).resolve()
    repo_root = here.parents[4]  # .../providers/validation/gate.py -> repo root
    return (
        repo_root / "docs" / "11-provider-validation.status.yaml",
        repo_root / "backend" / "app" / "providers" / "upstox",
        repo_root / "docs" / "11-PROVIDER-VALIDATION.md",
    )


def main(argv: list[str] | None = None) -> int:
    d_status, d_upstox, d_docs = _default_paths()
    parser = argparse.ArgumentParser(
        prog="analytical-gate",
        description="Provider-validation gate for Phase 2 (docs/11). Read-only.",
    )
    parser.add_argument("--status-file", type=Path, default=d_status)
    parser.add_argument("--upstox-dir", type=Path, default=d_upstox)
    parser.add_argument("--docs-table", type=Path, default=d_docs)
    parser.add_argument("--no-upstox-check", action="store_true")
    parser.add_argument("--no-docs-check", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    try:
        status = load_status(args.status_file)
    except ValidationSchemaError as exc:
        sys.stderr.write(f"PHASE 2 GATE: INVALID STATUS FILE\n  - {exc}\n")
        return 2

    result = evaluate(
        status,
        upstox_dir=None if args.no_upstox_check else args.upstox_dir,
        docs_table_path=None if args.no_docs_check else args.docs_table,
    )
    if not args.quiet:
        sys.stdout.write(render(result, status))
    return result.exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
