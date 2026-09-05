"""Tests for scripts/builder_agent.py (WOT-2026-058v).

Contract under test: the PREVENTIVE launch gate. A flight whose launch
context (batch_run-shaped JSON: `flight` + `PREDICATE`) cites no DAG at all,
or whose cited DAG does not resolve to a file under
`orchestrator_pipeline/flight_plans/**`, must fail closed (exit != 0) naming
the plan. A launch with the DAG persisted passes the gate, and historical
`reports/` artifacts are never touched (the gate is launch-moment only, not a
retrospective scanner).

The claimed-DAG-vs-disk resolution is REUSED from
`scripts.check_batch_run_accounting.check_flight_plan_persisted`
(WOT-2026-058t detective) by import: the delegation test monkeypatches that
symbol and fails if the launch path stops invoking it.

Tests never drive main() past the launch gate: below it the smoke flow writes
collaboration state (execution_log, bus events). A passing guard is asserted
at the gate level (empty findings) or by driving main() with the downstream
read patched to force its early no-plan return (still write-free).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).parent.parent.parent))


import scripts.builder_agent as ba


FLIGHT = "FP-20260905-LAUNCH-GUARD"


def _claimed_payload() -> dict:
    """Launch context whose PREDICATE claims conditions 1/2 (exit_code 0)."""
    return {
        "flight": FLIGHT,
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
    }


def _write_launch_context(tmp_path: Path, payload: dict) -> Path:
    """Write the launch context where a real takeoff keeps it: under the
    destination tree whose ancestor chain owns `flight_plans/`."""
    ctx = tmp_path / "orchestrator_pipeline" / "reports" / "launch_context.json"
    ctx.parent.mkdir(parents=True, exist_ok=True)
    ctx.write_text(json.dumps(payload), encoding="utf-8")
    return ctx


def _persist_dag(tmp_path: Path, stem: str = FLIGHT) -> Path:
    """Persist the DAG-JSON the PREDICATE cites, under flight_plans/."""
    flight_plans = tmp_path / "orchestrator_pipeline" / "flight_plans"
    flight_plans.mkdir(parents=True, exist_ok=True)
    dag = flight_plans / f"{stem}.json"
    dag.write_text(
        json.dumps({"id": stem, "schema": "autonomous-batch-dag/v1"}),
        encoding="utf-8",
    )
    return dag


def test_launch_fails_when_predicate_cites_no_dag(tmp_path: Path) -> None:
    """(a0) A PREDICATE that cites no DAG (conditions N/A), or a launch with no
    PREDICATE at all, must also fail closed: not citing anything is the easiest
    hole to exploit."""
    payload = _claimed_payload()
    payload["PREDICATE"]["schema_valido"]["exit_code"] = "N/A"
    payload["PREDICATE"]["dag_aciclico"]["exit_code"] = "N/A"
    ctx = _write_launch_context(tmp_path, payload)
    _persist_dag(tmp_path)  # even a persisted DAG cannot save a non-citation

    findings = ba.check_flight_launch_prerequisites(ctx)
    assert findings, "N/A conditions must fail closed"
    assert FLIGHT in findings[0]

    no_predicate = _write_launch_context(tmp_path / "nopred", {"flight": FLIGHT})
    findings = ba.check_flight_launch_prerequisites(no_predicate)
    assert findings, "a launch without PREDICATE must fail closed"
    assert FLIGHT in findings[0]


def test_launch_fails_when_predicate_dag_missing(tmp_path: Path) -> None:
    """(a) Fail-closed: the launch gate returns findings (exit != 0 at main)
    when the DAG the PREDICATE cites does not resolve to a file under
    orchestrator_pipeline/flight_plans/** - both when the tree exists but has
    no matching DAG (the measured FP-20260823 shape) and when no tree is
    reachable at all."""
    ctx = _write_launch_context(tmp_path, _claimed_payload())
    (tmp_path / "orchestrator_pipeline" / "flight_plans").mkdir(parents=True)

    findings = ba.check_flight_launch_prerequisites(ctx)
    assert len(findings) == 1
    assert FLIGHT in findings[0]
    assert "flight_plans" in findings[0]

    no_tree_ctx = _write_launch_context(tmp_path / "notree", _claimed_payload())
    findings = ba.check_flight_launch_prerequisites(no_tree_ctx)
    assert len(findings) == 1
    assert FLIGHT in findings[0]


def test_launch_names_missing_plan(tmp_path: Path, capsys) -> None:
    """(b) The failure output NAMES the missing plan (mutation with teeth:
    pre-fix the launch started without any warning, p2 = 0 hits)."""
    ctx = _write_launch_context(tmp_path, _claimed_payload())
    (tmp_path / "orchestrator_pipeline" / "flight_plans").mkdir(parents=True)

    rc = ba.main(["--flight-launch-context", str(ctx)])
    out = capsys.readouterr().out

    assert rc != 0
    assert FLIGHT in out
    assert "[LAUNCH-GUARD] ERROR" in out


def test_launch_succeeds_with_persisted_dag_and_reports_not_red(
    tmp_path: Path,
) -> None:
    """(c) Negative control: a launch with the DAG persisted passes the gate
    (empty findings = launch proceeds), even when the tree carries HISTORICAL
    batch_run reports whose own DAGs are missing - the launch guard is not a
    retrospective scanner and must not turn them red."""
    reports = tmp_path / "orchestrator_pipeline" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    historical = reports / "batch_run_FP-20260823-BUS-Y-RECIBO.json"
    historical_payload = {
        "flight": "FP-20260823-BUS-Y-RECIBO",
        "PREDICATE": {
            "schema_valido": {"command": "validate_batch_dag.py", "exit_code": 0},
            "dag_aciclico": {"command": "validate_batch_dag.py", "exit_code": 0},
        },
    }
    historical.write_text(json.dumps(historical_payload), encoding="utf-8")

    ctx = _write_launch_context(tmp_path, _claimed_payload())
    _persist_dag(tmp_path)

    findings = ba.check_flight_launch_prerequisites(ctx)

    assert findings == []
    # The historical report stays byte-identical (read-only launch path).
    assert json.loads(historical.read_text(encoding="utf-8")) == historical_payload


def test_builder_agent_delegates_to_check_flight_plan_persisted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(e) Reuse, not reimplementation - BINARIZED: the launch guard must invoke
    check_flight_plan_persisted. If the launch stops delegating (e.g. the
    matching got reimplemented), this test FAILS because the monkeypatched
    symbol is never called."""
    calls: list[tuple[Path, Path | None]] = []

    def _fake_check(context: Path, flight_plans_root: Path | None = None):
        calls.append((context, flight_plans_root))
        return []

    monkeypatch.setattr(ba, "check_flight_plan_persisted", _fake_check)

    ctx = _write_launch_context(tmp_path, _claimed_payload())
    _persist_dag(tmp_path)
    findings = ba.check_flight_launch_prerequisites(ctx)

    assert findings == []
    assert calls, "the launch must delegate to check_flight_plan_persisted"
    assert calls[0][0] == ctx


def test_main_launch_invokes_the_guard_before_any_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The launch (main) wires the guard as step 0: a failing guard returns
    exit != 0 before reading the work plan or writing any state."""
    called: list[str] = []

    def _failing_guard(context: Path, flight_plans_root: Path | None = None):
        called.append(str(context))
        return [f"el arranque del vuelo '{FLIGHT}' no cita ningun DAG validado"]

    monkeypatch.setattr(ba, "check_flight_launch_prerequisites", _failing_guard)

    ctx = tmp_path / "ctx.json"
    ctx.write_text("{}", encoding="utf-8")
    rc = ba.main(["--flight-launch-context", str(ctx)])

    assert rc != 0
    assert called, "main() must run the launch guard when a context is given"


def test_main_launch_with_persisted_dag_reaches_past_the_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """(c) at the CLI level: with the DAG persisted the launch guard does NOT
    block. main() proceeds past the gate; get_plan_id is patched to force the
    write-free early return at the plan check (step 1), so the observed rc=1 is
    the smoke flow's, never the guard's. Driving main() further would enter its
    wait loop and write collaboration state."""
    monkeypatch.setattr(ba, "get_plan_id", lambda _content: None)

    ctx = _write_launch_context(tmp_path, _claimed_payload())
    _persist_dag(tmp_path)

    rc = ba.main(["--flight-launch-context", str(ctx)])
    out = capsys.readouterr().out

    assert "[OK] Launch guard: el DAG citado por el vuelo esta persistido" in out
    assert "[LAUNCH-GUARD] ERROR" not in out
    assert rc != 0  # no-plan early return, NOT the launch guard
