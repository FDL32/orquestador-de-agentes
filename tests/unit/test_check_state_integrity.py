"""Tests for scripts/check_state_integrity.py (WOT-2026-074x DoD a).

Red/Green contract: the guard MUST fail on an undeclared shrink
(truncation/disappearance -- the exact class the ticket's receipt proves
invisible to ``--validate``) and MUST pass on declared rotations and on the
legitimate lifecycle moves of ``.agent/collaboration/`` (plan_audit moves,
notifications/execution_log/review_queue rotations writing into ``archive/``,
lock churn, the WOT-2026-060k removal of ``loop_execution_targets.txt``).

Mutations with teeth (for the evidence pass): removing the
``union_lines < union_hwm`` comparison in ``evaluate`` makes
``test_bus_truncation_undeclared_fails`` go green (i.e. the guard stops
biting); removing the live high-water comparison makes
``test_live_rotation_undeclared_fails`` go green.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


try:
    from scripts.check_state_integrity import run_check
except ImportError:  # pragma: no cover - direct script execution
    from check_state_integrity import run_check

_MOTOR_ROOT = Path(__file__).resolve().parents[2]

LIVE_SURFACES = (
    "STATE.md",
    "TURN.md",
    "execution_log.md",
    "backlog.md",
    "notifications.md",
    "review_queue.md",
)


def _make_root(tmp_path: Path) -> Path:
    root = tmp_path / "destino"
    (root / ".agent" / "runtime" / "events" / "archive").mkdir(parents=True)
    (root / ".agent" / "collaboration" / "_archive").mkdir(parents=True)
    return root


def _bus_path(root: Path) -> Path:
    return root / ".agent" / "runtime" / "events" / "events.jsonl"


def _write_bus(root: Path, lines: int) -> None:
    payload = "".join(json.dumps({"seq": i}) + "\n" for i in range(lines))
    _bus_path(root).write_text(payload, encoding="utf-8")


def _write_collab(root: Path, backlog_done_lines: int = 5) -> None:
    collab = root / ".agent" / "collaboration"
    for name in LIVE_SURFACES:
        (collab / name).write_text("content\n", encoding="utf-8")
    (collab / "_archive" / "backlog_done.md").write_text(
        "".join(f"row {i}\n" for i in range(backlog_done_lines)), encoding="utf-8"
    )


def _seeded_root(tmp_path: Path, bus_lines: int = 10) -> Path:
    root = _make_root(tmp_path)
    _write_bus(root, bus_lines)
    _write_collab(root)
    return root


def _anchor_path(root: Path) -> Path:
    return root / ".agent" / "runtime" / "state_integrity.json"


def test_baseline_then_stable_pass(tmp_path: Path) -> None:
    root = _seeded_root(tmp_path)
    first = run_check(root)
    assert first["verdict"] == "baseline"
    assert _anchor_path(root).is_file()
    second = run_check(root)
    assert second["verdict"] == "pass"


def test_bus_truncation_undeclared_fails(tmp_path: Path) -> None:
    root = _seeded_root(tmp_path, bus_lines=10)
    assert run_check(root)["verdict"] == "baseline"
    _write_bus(root, 0)
    report = run_check(root)
    assert report["verdict"] == "fail"
    assert any("SHRINK bus" in finding for finding in report["findings"])


def test_bus_truncation_fail_does_not_rewrite_anchor(tmp_path: Path) -> None:
    root = _seeded_root(tmp_path, bus_lines=10)
    run_check(root)
    before = _anchor_path(root).read_text(encoding="utf-8")
    _write_bus(root, 0)
    assert run_check(root)["verdict"] == "fail"
    assert _anchor_path(root).read_text(encoding="utf-8") == before


def test_bus_truncation_declared_passes(tmp_path: Path) -> None:
    root = _seeded_root(tmp_path, bus_lines=10)
    run_check(root)
    _write_bus(root, 0)
    declared = run_check(root, update=True, reason="reset operativo declarado")
    assert declared["verdict"] == "pass"
    assert declared["declared"] is True
    assert run_check(root)["verdict"] == "pass"


def test_live_rotation_undeclared_fails(tmp_path: Path) -> None:
    root = _seeded_root(tmp_path, bus_lines=10)
    run_check(root)
    # Rotation: move 4 events live->archive (union preserved).
    archive = root / ".agent" / "runtime" / "events" / "archive" / "events.T.jsonl"
    archive.write_text(
        "".join(json.dumps({"seq": i}) + "\n" for i in range(4)), "utf-8"
    )
    _write_bus(root, 6)
    report = run_check(root)
    assert report["verdict"] == "fail"
    assert any("rotacion sin declarar" in finding for finding in report["findings"])


def test_live_rotation_declared_passes(tmp_path: Path) -> None:
    root = _seeded_root(tmp_path, bus_lines=10)
    run_check(root)
    archive = root / ".agent" / "runtime" / "events" / "archive" / "events.T.jsonl"
    archive.write_text(
        "".join(json.dumps({"seq": i}) + "\n" for i in range(4)), "utf-8"
    )
    _write_bus(root, 6)
    declared = run_check(
        root,
        update=True,
        reason="archive_event_bus: archived tickets WOT-2026-999x",
        source="archive_event_bus",
    )
    assert declared["verdict"] == "pass"
    assert run_check(root)["verdict"] == "pass"
    anchor = json.loads(_anchor_path(root).read_text(encoding="utf-8"))
    assert anchor["declarations"][-1]["source"] == "archive_event_bus"


def test_union_loss_fails_even_after_partial_rotation(tmp_path: Path) -> None:
    root = _seeded_root(tmp_path, bus_lines=10)
    run_check(root)
    archive = root / ".agent" / "runtime" / "events" / "archive" / "events.T.jsonl"
    archive.write_text(
        "".join(json.dumps({"seq": i}) + "\n" for i in range(2)), "utf-8"
    )
    _write_bus(root, 6)
    report = run_check(root)
    assert report["verdict"] == "fail"
    assert any("union bajo" in finding for finding in report["findings"])


def test_bus_disappearance_fails(tmp_path: Path) -> None:
    root = _seeded_root(tmp_path, bus_lines=10)
    run_check(root)
    _bus_path(root).unlink()
    report = run_check(root)
    assert report["verdict"] == "fail"
    assert any("bus desaparecido" in finding for finding in report["findings"])


def test_collab_census_decrease_fails(tmp_path: Path) -> None:
    root = _seeded_root(tmp_path)
    queued = root / ".agent" / "collaboration" / "queued"
    queued.mkdir()
    (queued / "STRATEGY_WOT-2026-999x.md").write_text("plan\n", encoding="utf-8")
    run_check(root)
    (queued / "STRATEGY_WOT-2026-999x.md").unlink()
    report = run_check(root)
    assert report["verdict"] == "fail"
    assert any("SHRINK collab" in finding for finding in report["findings"])


def test_collab_plan_audit_move_passes(tmp_path: Path) -> None:
    root = _seeded_root(tmp_path)
    collab = root / ".agent" / "collaboration"
    strategy = collab / "STRATEGY_WOT-2026-999x.md"
    strategy.write_text("plan\n", encoding="utf-8")
    run_check(root)
    plan_audit = collab / "_archive" / "plan_audit"
    plan_audit.mkdir()
    strategy.rename(plan_audit / "STRATEGY_WOT-2026-999x.md")
    assert run_check(root)["verdict"] == "pass"


def test_collab_archive_dir_churn_ignored(tmp_path: Path) -> None:
    root = _seeded_root(tmp_path)
    archive = root / ".agent" / "collaboration" / "archive"
    archive.mkdir()
    snapshot = archive / "notifications_20260101_000000.md"
    snapshot.write_text("entries\n", encoding="utf-8")
    run_check(root)
    snapshot.unlink()
    assert run_check(root)["verdict"] == "pass"


def test_session_bus_locks_churn_ignored(tmp_path: Path) -> None:
    root = _seeded_root(tmp_path)
    locks = root / ".agent" / "collaboration" / "session_bus" / "locks"
    locks.mkdir(parents=True)
    lock = locks / "sello_level_all.lock"
    lock.write_text("held\n", encoding="utf-8")
    run_check(root)
    lock.unlink()
    assert run_check(root)["verdict"] == "pass"


def test_loop_execution_targets_removal_tolerated(tmp_path: Path) -> None:
    root = _seeded_root(tmp_path)
    targets = root / ".agent" / "collaboration" / "loop_execution_targets.txt"
    targets.write_text("sha code\n", encoding="utf-8")
    run_check(root)
    targets.unlink()
    assert run_check(root)["verdict"] == "pass"


def test_live_surface_disappearance_fails(tmp_path: Path) -> None:
    root = _seeded_root(tmp_path)
    run_check(root)
    (root / ".agent" / "collaboration" / "STATE.md").unlink()
    report = run_check(root)
    assert report["verdict"] == "fail"
    assert any("superficie viva ausente: STATE.md" in f for f in report["findings"])


def test_backlog_done_shrink_fails(tmp_path: Path) -> None:
    root = _seeded_root(tmp_path)
    run_check(root)
    backlog_done = root / ".agent" / "collaboration" / "_archive" / "backlog_done.md"
    backlog_done.write_text("row 0\nrow 1\n", encoding="utf-8")
    report = run_check(root)
    assert report["verdict"] == "fail"
    assert any("backlog_done.md" in finding for finding in report["findings"])


def test_collab_disappearance_fails(tmp_path: Path) -> None:
    root = _seeded_root(tmp_path)
    run_check(root)
    collab = root / ".agent" / "collaboration"
    for candidate in sorted(collab.rglob("*"), reverse=True):
        if candidate.is_file():
            candidate.unlink()
        elif candidate.is_dir():
            candidate.rmdir()
    collab.rmdir()
    report = run_check(root)
    assert report["verdict"] == "fail"
    assert any("collaboration/ desaparecido" in f for f in report["findings"])


def test_skip_when_no_operational_state(tmp_path: Path) -> None:
    empty = tmp_path / "not_a_workspace"
    empty.mkdir()
    report = run_check(empty)
    assert report["verdict"] == "skip"
    assert not _anchor_path(empty).is_file()


def test_anchor_for_other_root_rebaselines(tmp_path: Path) -> None:
    first = _seeded_root(tmp_path)
    run_check(first)
    other = tmp_path / "otro_destino"
    (other / ".agent" / "runtime" / "events" / "archive").mkdir(parents=True)
    (other / ".agent" / "collaboration").mkdir(parents=True)
    _write_bus(other, 3)
    _anchor_path(other).write_text(
        _anchor_path(first).read_text(encoding="utf-8"), encoding="utf-8"
    )
    report = run_check(other)
    assert report["verdict"] == "baseline"
    assert any("otra raiz" in finding for finding in report["findings"])


def test_update_requires_reason(tmp_path: Path) -> None:
    root = _seeded_root(tmp_path)
    report = run_check(root, update=True, reason="   ")
    assert report["verdict"] == "fail"


def test_growth_updates_high_water(tmp_path: Path) -> None:
    root = _seeded_root(tmp_path, bus_lines=10)
    run_check(root)
    _write_bus(root, 14)
    assert run_check(root)["verdict"] == "pass"
    anchor = json.loads(_anchor_path(root).read_text(encoding="utf-8"))
    assert anchor["bus"]["live_hwm"] == 14
    _write_bus(root, 12)
    assert run_check(root)["verdict"] == "fail"


def test_archive_event_bus_declares_rotation(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    _write_bus(root, 0)
    _write_collab(root)
    bus = _bus_path(root)
    events = [
        {
            "event_id": f"ev-{i}",
            "event_type": "STATE_CHANGED",
            "ticket_id": "WOT-2026-999x",
            "timestamp": "2026-10-14T00:00:00+00:00",
            "payload": {"to_state": "COMPLETED" if i else "IN_PROGRESS"},
        }
        for i in range(3)
    ]
    bus.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    run_check(root)

    env = dict(os.environ)
    env["AGENT_PROJECT_ROOT"] = str(root)
    result = subprocess.run(
        [
            sys.executable,
            str(_MOTOR_ROOT / "scripts" / "archive_event_bus.py"),
            "--ticket",
            "WOT-2026-999x",
        ],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert bus.read_text(encoding="utf-8") == ""
    anchor = json.loads(_anchor_path(root).read_text(encoding="utf-8"))
    assert anchor["declarations"], "la rotacion debe declararse en el ancla"
    assert anchor["declarations"][-1]["source"] == "archive_event_bus"
    assert run_check(root)["verdict"] == "pass"


def test_prepush_registers_state_integrity_check() -> None:
    """The guard is a BARRIER only if a self-running path invokes it: the
    closeout registration in prepush_check.run_preflight_check must CALL the
    check (the static import alone is not enough)."""
    import inspect

    try:
        from scripts import prepush_check
    except ImportError:  # pragma: no cover - direct script execution
        import prepush_check  # type: ignore[no-redef]

    source = inspect.getsource(prepush_check.run_preflight_check)
    assert "run_state_integrity_check(project_root)" in source
