"""Tests for scripts/check_batch_run_accounting.py (WOT-2026-025k).

Contract under test: in a `batch_run_<ts>.json` from the autonomous batch,
`group_stop_reports` (GSR) must never reference a ticket ABSENT from the
`tickets{}` index. Origin (F1 2026-07-16): PREDICATE #3
(`contabilidad_completa`) self-declared PASS with an incomplete `tickets{}`;
an auditor re-deriving the universe solely from `tickets{}` would silently
lose GSR-only tickets -- a false green.

`tickets` may appear as a dict keyed by ticket-id, a list of
`{id, ...}` objects, or be entirely absent (empty universe).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _write_batch_run(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "batch_run_20260716-0900.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_orphan_gsr_ticket_fails(tmp_path: Path) -> None:
    """GSR references a ticket absent from tickets{} (dict form) -> orphan detected."""
    from scripts.check_batch_run_accounting import check_batch_run_accounting

    payload = {
        "tickets": {
            "WOT-2026-021r": {"state": "closed"},
        },
        "group_stop_reports": [
            {"group": "G-X", "ticket": "WOT-2026-021r", "state": "closed"},
            {"group": "G-Y", "ticket": "WOT-2026-099z", "state": "frozen"},
        ],
    }
    batch_run = _write_batch_run(tmp_path, payload)

    orphans = check_batch_run_accounting(batch_run)

    assert orphans == ["WOT-2026-099z"]


def test_complete_legitimate_batch_run_passes(tmp_path: Path) -> None:
    """Positive fixture: every GSR ticket is present in tickets{} -> no orphans.

    Guards against gate_false_positive_legitimate_input: a correct, complete
    batch_run must never be flagged.
    """
    from scripts.check_batch_run_accounting import check_batch_run_accounting

    payload = {
        "tickets": {
            "WOT-2026-021q": {"state": "frozen-with-GROUP_STOP_REPORT"},
            "WOT-2026-016r": {"state": "frozen-with-GROUP_STOP_REPORT"},
            "WOT-2026-022f": {"state": "closed"},
        },
        "group_stop_reports": [
            {"group": "G-A", "ticket": "WOT-2026-021q", "state": "frozen"},
            {"group": "G-B", "ticket": "WOT-2026-016r", "state": "frozen"},
        ],
    }
    batch_run = _write_batch_run(tmp_path, payload)

    orphans = check_batch_run_accounting(batch_run)

    assert orphans == []


def test_tickets_as_list_form(tmp_path: Path) -> None:
    """tickets{} may be a list of {id, ...} objects instead of a dict."""
    from scripts.check_batch_run_accounting import check_batch_run_accounting

    payload = {
        "tickets": [
            {"id": "WOT-2026-021r", "state": "closed"},
            {"id": "WOT-2026-024g", "state": "closed"},
        ],
        "group_stop_reports": [
            {"group": "G-A", "ticket": "WOT-2026-021r", "state": "closed"},
        ],
    }
    batch_run = _write_batch_run(tmp_path, payload)

    orphans = check_batch_run_accounting(batch_run)

    assert orphans == []


def test_tickets_as_list_form_detects_orphan(tmp_path: Path) -> None:
    """List form: an orphan GSR ticket is still detected."""
    from scripts.check_batch_run_accounting import check_batch_run_accounting

    payload = {
        "tickets": [
            {"id": "WOT-2026-021r", "state": "closed"},
        ],
        "group_stop_reports": [
            {"group": "G-A", "ticket": "WOT-2026-099z", "state": "frozen"},
        ],
    }
    batch_run = _write_batch_run(tmp_path, payload)

    orphans = check_batch_run_accounting(batch_run)

    assert orphans == ["WOT-2026-099z"]


def test_tickets_absent_means_empty_universe(tmp_path: Path) -> None:
    """tickets{} entirely absent -> empty universe; any GSR ticket is orphan."""
    from scripts.check_batch_run_accounting import check_batch_run_accounting

    payload = {
        "group_stop_reports": [
            {"group": "G-A", "ticket": "WOT-2026-021r", "state": "frozen"},
        ],
    }
    batch_run = _write_batch_run(tmp_path, payload)

    orphans = check_batch_run_accounting(batch_run)

    assert orphans == ["WOT-2026-021r"]


def test_no_group_stop_reports_is_trivially_clean(tmp_path: Path) -> None:
    """Absent group_stop_reports -> nothing to reconcile, no orphans."""
    from scripts.check_batch_run_accounting import check_batch_run_accounting

    payload = {"tickets": {"WOT-2026-021r": {"state": "closed"}}}
    batch_run = _write_batch_run(tmp_path, payload)

    orphans = check_batch_run_accounting(batch_run)

    assert orphans == []


def test_cli_exit_code_1_prints_orphans(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """CLI contract: orphan(s) present -> exit 1, orphan ticket name(s) printed."""
    from scripts.check_batch_run_accounting import main

    payload = {
        "tickets": {"WOT-2026-021r": {"state": "closed"}},
        "group_stop_reports": [
            {"group": "G-A", "ticket": "WOT-2026-099z", "state": "frozen"},
        ],
    }
    batch_run = _write_batch_run(tmp_path, payload)

    rc = main([str(batch_run)])

    assert rc == 1
    captured = capsys.readouterr()
    assert "WOT-2026-099z" in captured.out


def test_cli_exit_code_0_when_complete(tmp_path: Path) -> None:
    """CLI contract: complete accounting -> exit 0."""
    from scripts.check_batch_run_accounting import main

    payload = {
        "tickets": {"WOT-2026-021r": {"state": "closed"}},
        "group_stop_reports": [
            {"group": "G-A", "ticket": "WOT-2026-021r", "state": "closed"},
        ],
    }
    batch_run = _write_batch_run(tmp_path, payload)

    rc = main([str(batch_run)])

    assert rc == 0


def test_cli_accepts_dash_dash_file_flag(tmp_path: Path) -> None:
    """CLI also accepts --file as an alternative to the positional arg."""
    from scripts.check_batch_run_accounting import main

    payload = {
        "tickets": {"WOT-2026-021r": {"state": "closed"}},
        "group_stop_reports": [],
    }
    batch_run = _write_batch_run(tmp_path, payload)

    rc = main(["--file", str(batch_run)])

    assert rc == 0


def _write_flight_tree(
    tmp_path: Path, payload: dict, dag_stem: str | None = None
) -> Path:
    """Standard report tree: `<tmp>/orchestrator_pipeline/reports/` +
    `<tmp>/orchestrator_pipeline/flight_plans/` (empty unless dag_stem given)."""
    reports = tmp_path / "orchestrator_pipeline" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    flight_plans = tmp_path / "orchestrator_pipeline" / "flight_plans"
    flight_plans.mkdir(parents=True, exist_ok=True)
    if dag_stem is not None:
        (flight_plans / f"{dag_stem}.json").write_text(
            json.dumps({"name": dag_stem}), encoding="utf-8"
        )
    batch_run = reports / "batch_run_20260831-NAN-DAG.json"
    batch_run.write_text(json.dumps(payload), encoding="utf-8")
    return batch_run


def _claimed_fp_payload() -> dict:
    """WOT-2026-058t defect shape: FP- flight whose PREDICATE conditions 1/2
    claim `exit_code: 0` for validate_batch_dag.py."""
    return {
        "flight": "FP-20260831-NAN-DAG",
        "PREDICATE": {
            "schema_valido": {
                "command": "validate_batch_dag.py",
                "exit_code": 0,
                "note": "validated pre-execution by the flight plan",
            },
            "dag_aciclico": {
                "command": "validate_batch_dag.py",
                "exit_code": 0,
                "note": "validated pre-execution",
            },
        },
        "group_stop_reports": [],
    }


def test_missing_dag_for_claimed_fp_flight_fails(tmp_path: Path) -> None:
    """WOT-2026-058t mutation: conditions 1/2 claim exit 0 but no DAG-JSON is
    persisted for the FP- flight -> finding + CLI exit 1."""
    from scripts.check_batch_run_accounting import (
        check_flight_plan_persisted,
        main,
    )

    batch_run = _write_flight_tree(tmp_path, _claimed_fp_payload())

    findings = check_flight_plan_persisted(batch_run)
    rc = main([str(batch_run)])

    assert len(findings) == 1
    assert "FP-20260831-NAN-DAG" in findings[0]
    assert rc == 1


def test_claimed_fp_flight_with_persisted_dag_passes(tmp_path: Path) -> None:
    """WOT-2026-058t positive: the claim is VERIFIABLE because the DAG-JSON is
    on disk -> no finding, CLI exit 0."""
    from scripts.check_batch_run_accounting import (
        check_flight_plan_persisted,
        main,
    )

    batch_run = _write_flight_tree(
        tmp_path, _claimed_fp_payload(), dag_stem="FP-20260831-NAN-DAG"
    )

    findings = check_flight_plan_persisted(batch_run)
    rc = main([str(batch_run)])

    assert findings == []
    assert rc == 0


def test_fp_flight_without_claim_passes_even_without_dag(tmp_path: Path) -> None:
    """DoD sin-DAG remedy: conditions 1/2 emitted N/A (no exit_code 0) is a
    declared absence, not a verified claim -> no finding."""
    from scripts.check_batch_run_accounting import check_flight_plan_persisted

    payload = _claimed_fp_payload()
    payload["PREDICATE"]["schema_valido"]["exit_code"] = "N/A"
    payload["PREDICATE"]["dag_aciclico"]["exit_code"] = "N/A"
    batch_run = _write_flight_tree(tmp_path, payload)

    findings = check_flight_plan_persisted(batch_run)

    assert findings == []


def test_non_fp_flight_citing_success_is_left_alone(tmp_path: Path) -> None:
    """Legacy flights whose `flight` predates the FP- convention (descriptive
    text, G-xxxx ids) are not constrained: retroactively requiring a persisted
    plan from them would convert the historical corpus red (measured: 12 such
    reports in the destination)."""
    from scripts.check_batch_run_accounting import check_flight_plan_persisted

    payload = {
        "flight": "054-familia-barrera-prosa",
        "PREDICATE": {
            "schema_valido": {"command": "validate_batch_dag.py", "exit_code": 0},
            "dag_aciclico": {"command": "validate_batch_dag.py", "exit_code": 0},
        },
    }
    batch_run = _write_flight_tree(tmp_path, payload)

    findings = check_flight_plan_persisted(batch_run)

    assert findings == []


def test_report_without_flight_field_is_left_alone(tmp_path: Path) -> None:
    """Reports with no flight citation at all are not constrained by the
    flight-plan check (nothing to resolve against flight_plans/)."""
    from scripts.check_batch_run_accounting import check_flight_plan_persisted

    payload = {
        "PREDICATE": {
            "schema_valido": {"command": "validate_batch_dag.py", "exit_code": 0},
        },
    }
    batch_run = _write_flight_tree(tmp_path, payload)

    findings = check_flight_plan_persisted(batch_run)

    assert findings == []


def test_flight_in_start_context_isolation_is_resolved(tmp_path: Path) -> None:
    """The flight citation may live under start_context_isolation.flight."""
    from scripts.check_batch_run_accounting import check_flight_plan_persisted

    payload = _claimed_fp_payload()
    payload.pop("flight")
    payload["start_context_isolation"] = {"flight": "FP-20260831-NAN-DAG"}
    batch_run = _write_flight_tree(tmp_path, payload)

    findings = check_flight_plan_persisted(batch_run)

    assert len(findings) == 1
    assert "FP-20260831-NAN-DAG" in findings[0]


def test_parenthetical_flight_suffix_still_resolves_dag(tmp_path: Path) -> None:
    """Flight names with a '(VUELO ...)' annotation still resolve against the
    DAG stem (measured on batch_run_20260722_FP-20260722-027n-027o.json)."""
    from scripts.check_batch_run_accounting import check_flight_plan_persisted

    payload = _claimed_fp_payload()
    payload["flight"] = "FP-20260831-NAN-DAG (VUELO GARANTIAS DEL ENSEMBLE)"
    batch_run = _write_flight_tree(tmp_path, payload, dag_stem="FP-20260831-NAN-DAG")

    findings = check_flight_plan_persisted(batch_run)

    assert findings == []
