"""Items 9-12 & 19 — the provider-validation gate.

  9  gate blocks while PV rows are OPEN            (synthetic fixture)
  10 gate passes with all rows CONFIRMED
  11 gate passes with ACCEPTED_FALLBACK
  12 invalid PV status rejected
  19 the Phase-2 gate cannot be accidentally bypassed

NOTE: Phase 1.5 (2026-08-27) resolved every PV row, so the *real*
``docs/11-provider-validation.status.yaml`` now evaluates CLEAR. The blocking-path
logic is still covered here via a synthetic all-OPEN fixture.
"""

from __future__ import annotations

import copy

import pytest
import yaml

from app.providers.base import ProviderValidationGateError
from app.providers.validation import evaluate, load_status
from app.providers.validation.gate import UPSTOX_STUB_ALLOWLIST, main
from app.providers.validation.loader import ValidationSchemaError
from tests.conftest import DOCS_TABLE, STATUS_YAML, UPSTOX_DIR


def _base_doc() -> dict:
    return yaml.safe_load(STATUS_YAML.read_text(encoding="utf-8"))


def _write(tmp_path, doc: dict):
    p = tmp_path / "status.yaml"
    p.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return p


def _all_open(doc: dict) -> dict:
    """Force every blocking row back to OPEN (blocking-path fixture)."""
    doc = copy.deepcopy(doc)
    for item in doc["items"].values():
        if item["blocks_phase_2"]:
            item["status"] = "OPEN"
            item["evidence"] = None
            item["fallback_ref"] = None
            item["branch"] = None
            item["decided_on"] = None
    return doc


def _resolve_all(doc: dict, status: str) -> dict:
    doc = copy.deepcopy(doc)
    for pv, item in doc["items"].items():
        if not item["blocks_phase_2"]:
            continue
        item["status"] = status
        item["decided_on"] = "2026-08-27"
        if status == "CONFIRMED":
            item["evidence"] = ["https://example/docs — 2026-08-27"]
            item["fallback_ref"] = None
        else:
            item["evidence"] = None
            item["fallback_ref"] = f"{pv} / Accepted fallback"
        if pv == "PV-2":
            item["branch"] = "AGGREGATE_FROM_M1"
        if pv == "PV-4":
            item["branch"] = "B_SNAPSHOT"
    return doc


# --- item 9 (blocking path — synthetic fixture) -------------------------


def test_gate_blocks_while_all_open(tmp_path):
    status = load_status(_write(tmp_path, _all_open(_base_doc())))
    result = evaluate(status)
    assert result.blocked is True
    assert result.open_items == ["PV-1", "PV-2", "PV-3", "PV-4", "PV-5", "PV-6", "PV-7"]
    assert result.exit_code != 0


def test_cli_blocks_and_reports_every_open(tmp_path, capsys):
    p = _write(tmp_path, _all_open(_base_doc()))
    rc = main(["--status-file", str(p), "--no-upstox-check", "--no-docs-check"])
    out = capsys.readouterr().out
    assert rc != 0
    assert "PHASE 2 GATE: BLOCKED" in out
    for pv in ("PV-1", "PV-7"):
        assert f"{pv} OPEN" in out


# --- Phase 1.5 outcome: the real file now evaluates CLEAR ---------------


def test_real_status_file_is_clear_after_phase_1_5():
    """docs/11 §4 evidence resolved every PV row on 2026-08-27."""
    status = load_status(STATUS_YAML)
    result = evaluate(status, docs_table_path=DOCS_TABLE, upstox_dir=UPSTOX_DIR)
    assert result.blocked is False, (result.open_items, result.errors)
    assert result.open_items == []
    assert result.errors == []
    assert load_status(STATUS_YAML).items["PV-2"].branch == "AGGREGATE_FROM_M1"
    assert load_status(STATUS_YAML).items["PV-4"].branch == "A_PER_CANDLE"


def test_cli_on_real_file_is_clear(capsys):
    rc = main(["--status-file", str(STATUS_YAML), "--docs-table", str(DOCS_TABLE)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "PHASE 2 GATE: CLEAR" in out


# --- item 10 --------------------------------------------------------------


def test_gate_passes_when_all_confirmed(tmp_path):
    p = _write(tmp_path, _resolve_all(_base_doc(), "CONFIRMED"))
    result = evaluate(load_status(p))
    assert result.blocked is False
    assert result.exit_code == 0


def test_confirmed_without_evidence_is_an_error(tmp_path):
    doc = _resolve_all(_base_doc(), "CONFIRMED")
    doc["items"]["PV-3"]["evidence"] = None
    result = evaluate(load_status(_write(tmp_path, doc)))
    assert result.blocked is True
    assert any("PV-3" in e and "evidence" in e for e in result.errors)


# --- item 11 --------------------------------------------------------------


def test_gate_passes_with_accepted_fallback(tmp_path):
    p = _write(tmp_path, _resolve_all(_base_doc(), "ACCEPTED_FALLBACK"))
    result = evaluate(load_status(p))
    assert result.blocked is False


def test_accepted_fallback_needs_ref_and_branch(tmp_path):
    doc = _resolve_all(_base_doc(), "ACCEPTED_FALLBACK")
    doc["items"]["PV-5"]["fallback_ref"] = None
    doc["items"]["PV-2"]["branch"] = None
    result = evaluate(load_status(_write(tmp_path, doc)))
    assert result.blocked is True
    assert any("PV-5" in e and "fallback_ref" in e for e in result.errors)
    assert any("PV-2" in e and "branch" in e for e in result.errors)


# --- item 12 --------------------------------------------------------------


def test_invalid_status_is_rejected(tmp_path):
    doc = _base_doc()
    doc["items"]["PV-1"]["status"] = "MAYBE"
    with pytest.raises(ValidationSchemaError):
        load_status(_write(tmp_path, doc))


def test_missing_item_is_rejected(tmp_path):
    doc = _base_doc()
    del doc["items"]["PV-6"]
    with pytest.raises(ValidationSchemaError):
        load_status(_write(tmp_path, doc))


def test_cli_returns_2_on_invalid_file(tmp_path, capsys):
    doc = _base_doc()
    doc["items"]["PV-1"]["status"] = "NOPE"
    p = _write(tmp_path, doc)
    rc = main(["--status-file", str(p), "--no-upstox-check", "--no-docs-check"])
    assert rc == 2


# --- item 19: cannot be bypassed --------------------------------------


def test_upstox_allowlist_enforced_when_a_blocking_row_is_open(tmp_path):
    status_p = _write(tmp_path, _all_open(_base_doc()))
    fake = tmp_path / "upstox"
    fake.mkdir()
    for n in UPSTOX_STUB_ALLOWLIST:
        (fake / n).write_text("# stub\n", encoding="utf-8")
    (fake / "client.py").write_text("# sneaky real client\n", encoding="utf-8")
    result = evaluate(load_status(status_p), upstox_dir=fake)
    assert result.blocked is True
    assert any("allow-list" in e for e in result.errors)


def test_real_upstox_provider_is_wired_and_gate_clear():
    """Phase 2.1: the gate is CLEAR, so the real ``UpstoxProvider`` is built (the
    docs/09 §2.12 allow-list only applies while a blocking PV row is OPEN, which
    is covered by the synthetic-fixture test above)."""
    from app.config import Settings
    from app.providers.base import (
        MarketDataProvider,
        ProviderUnavailableCapabilityError,
    )
    from app.providers.registry import get_provider
    from app.providers.upstox import UpstoxProvider

    provider = get_provider(Settings(active_provider="upstox", upstox_token_file="/nonexistent"))
    assert isinstance(provider, UpstoxProvider)
    assert isinstance(provider, MarketDataProvider)
    # a data call fails on its own merits (no master file configured), not with a
    # gate error — the gate is genuinely clear.
    with pytest.raises(ProviderUnavailableCapabilityError):
        provider.fetch_instrument_master()


def test_upstox_provider_refuses_if_a_pv_row_reopens(monkeypatch):
    """Defense-in-depth: ``UpstoxProvider.__init__`` re-runs the PV gate."""
    from app.config import Settings
    from app.providers.upstox import provider as provider_mod

    def _blocked(*_a, **_k):
        raise ProviderValidationGateError("simulated: PV-3 re-opened")

    monkeypatch.setattr(provider_mod, "assert_gate_clear", _blocked)
    with pytest.raises(ProviderValidationGateError):
        provider_mod.UpstoxProvider(Settings(active_provider="upstox"))


def test_docs_table_parity_is_checked(tmp_path):
    doc = _base_doc()
    # real docs/11 §1 table says PV-1 = ACCEPTED_FALLBACK; force a disagreement.
    doc["items"]["PV-1"]["status"] = "CONFIRMED"
    doc["items"]["PV-1"]["evidence"] = ["x — 2026-08-27"]
    doc["items"]["PV-1"]["fallback_ref"] = None
    doc["items"]["PV-1"]["decided_on"] = "2026-08-27"
    result = evaluate(load_status(_write(tmp_path, doc)), docs_table_path=DOCS_TABLE)
    assert any("table" in e and "PV-1" in e for e in result.errors)


def test_gate_never_writes_the_status_file():
    before = STATUS_YAML.read_bytes()
    main(["--status-file", str(STATUS_YAML), "--no-upstox-check", "--no-docs-check", "--quiet"])
    assert STATUS_YAML.read_bytes() == before
