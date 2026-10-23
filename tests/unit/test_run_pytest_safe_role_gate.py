"""Proves the role-gate (WOT-2026-117a) is actually WIRED into
`run_pytest_safe.py --level all`, not just defined as a free-floating
function.

Companion to tests/unit/test_check_manager_role_for_suite.py, which tests
the gate's pure logic in isolation. This file calls the real `main()` with a
TURN.md declaring a non-Manager role and verifies the run is blocked BEFORE
any lock/subprocess work happens, and that a Manager-declared (or absent)
TURN.md lets `main()` proceed past the gate.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = PROJECT_ROOT / "scripts" / "run_pytest_safe.py"


def load_runner_module():
    spec = importlib.util.spec_from_file_location("run_pytest_safe", RUNNER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module._probe_cpu_load = lambda window_s=0.3: (None, [])
    module._probe_foreign_pytest = lambda: (None, [])
    return module


def _write_turn(tmp_path: Path, role: str) -> None:
    turn_dir = tmp_path / ".agent" / "collaboration"
    turn_dir.mkdir(parents=True, exist_ok=True)
    (turn_dir / "TURN.md").write_text(
        f"| **ROL** | **{role}** |\n| **Plan ID** | WOT-2026-117a |\n",
        encoding="utf-8",
    )


def _stub_for_pass_through(mod, tmp_path: Path, monkeypatch) -> None:
    """Wire just enough so a run that passes the gate can reach dry-run exit 0."""
    base = tmp_path / ".agent" / "runtime" / "pytest-safe"
    base.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_PROJECT_ROOT_BOOTSTRAP", tmp_path)
    monkeypatch.setattr(mod, "LAST_RUN_JSON", base / "last-run.json")
    monkeypatch.setattr(mod, "LAST_RUN_LOG", base / "last-run.log")
    monkeypatch.setattr(mod, "RUN_HISTORY_JSONL", base / "run_history.jsonl")
    monkeypatch.setattr(
        mod, "cleanup_known_temp_dirs", lambda: {"removed": [], "failed": []}
    )
    lock_obj = {
        "pid": 0,
        "started_at": "2026-01-01T00:00:00+00:00",
        "cwd": str(tmp_path),
    }
    monkeypatch.setattr(mod, "acquire_lock", lambda force_unlock=False: lock_obj)
    monkeypatch.setattr(mod, "release_lock", lambda: None)
    monkeypatch.setattr(
        mod,
        "select_test_runner",
        lambda interp, args, xdist, run_dir, test_dir: (["echo"], "pytest"),
    )
    monkeypatch.setattr(mod, "resolve_test_interpreter", lambda: sys.executable)


@pytest.mark.parametrize("blocked_role", ["BUILDER", "REVISOR"])
def test_level_all_is_blocked_before_any_other_work_when_role_is_not_manager(
    tmp_path: Path, monkeypatch, blocked_role: str
) -> None:
    """A non-Manager TURN.md blocks --level all with EX_ROLE_NOT_PERMITTED (77),
    without ever reaching lock acquisition (acquire_lock is never patched in,
    so a call to the real one would hit the repo's own lock -- it must not).
    """
    mod = load_runner_module()
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
    _write_turn(tmp_path, blocked_role)
    monkeypatch.setattr(sys, "argv", ["run_pytest_safe.py", "--level", "all"])

    def _fail_if_called(*args, **kwargs):
        raise AssertionError(
            "acquire_lock must not run: the role gate should short-circuit first"
        )

    monkeypatch.setattr(mod, "acquire_lock", _fail_if_called)

    code = mod.main()

    assert code == mod.EX_ROLE_NOT_PERMITTED
    assert code == 77


def test_level_all_proceeds_past_gate_when_role_is_manager(
    tmp_path: Path, monkeypatch
) -> None:
    mod = load_runner_module()
    _write_turn(tmp_path, "MANAGER")
    _stub_for_pass_through(mod, tmp_path, monkeypatch)
    monkeypatch.setattr(
        sys, "argv", ["run_pytest_safe.py", "--level", "all", "--dry-run"]
    )

    code = mod.main()

    assert code == 0


def test_level_all_proceeds_past_gate_when_turn_file_absent(
    tmp_path: Path, monkeypatch
) -> None:
    """Motor CODE-ONLY MODE / sesion de un solo Builder: sin TURN.md, el
    protocolo de rol-unico no aplica (ver LIMITE DECLARADO del gate)."""
    mod = load_runner_module()
    _stub_for_pass_through(mod, tmp_path, monkeypatch)
    monkeypatch.setattr(
        sys, "argv", ["run_pytest_safe.py", "--level", "all", "--dry-run"]
    )

    code = mod.main()

    assert code == 0


def test_level_unit_is_never_gated_by_role(tmp_path: Path, monkeypatch) -> None:
    """The gate only fires for --level all; default --level unit is untouched."""
    mod = load_runner_module()
    _write_turn(tmp_path, "BUILDER")
    _stub_for_pass_through(mod, tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["run_pytest_safe.py", "--dry-run"])

    code = mod.main()

    assert code == 0
