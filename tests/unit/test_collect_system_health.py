"""Tests for scripts/collect_system_health.py (collector, not auditor).

Covers the contract conditions agreed for v0: topology/degraded mode, immutable
output dir (no overwrite), declared coverage in skeletons, path relativization,
and exit-on-critical (red suite).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


_SPEC = importlib.util.spec_from_file_location(
    "collect_system_health",
    Path(__file__).resolve().parents[2] / "scripts" / "collect_system_health.py",
)
csh = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(csh)


# ---- Pure helpers -----------------------------------------------------------


def test_relativize_strips_personal_paths():
    roots = {
        "MOTOR_ROOT": Path("C:/Users/fdl/motor"),
        "DESTINO_ROOT": Path("C:/Users/fdl/dest"),
    }
    text = r"error at C:\Users\fdl\motor\x.py and C:/Users/fdl/dest/y.py"
    out = csh._relativize(text, roots)
    assert "C:/Users/fdl" not in out
    assert "C:\\Users\\fdl" not in out
    assert "<MOTOR_ROOT>" in out
    assert "<DESTINO_ROOT>" in out


def test_unique_out_dir_no_overwrite(tmp_path):
    base = tmp_path / "general_audit_20260613_1200"
    first = csh._unique_out_dir(base)
    assert first == base
    base.mkdir()
    second = csh._unique_out_dir(base)
    assert second != base
    assert second.name == "general_audit_20260613_1200_01"


def test_read_pytest_last_run_missing(tmp_path):
    res = csh._read_pytest_last_run(tmp_path)
    assert res["present"] is False
    assert res["exit_code"] is None


def test_read_pytest_last_run_present(tmp_path):
    p = tmp_path / ".agent" / "runtime" / "pytest-safe"
    p.mkdir(parents=True)
    (p / "last-run.json").write_text(
        json.dumps({"exit_code": 0, "finished_at": "now"}), encoding="utf-8"
    )
    res = csh._read_pytest_last_run(tmp_path)
    assert res["present"] is True
    assert res["exit_code"] == 0


# ---- Integration via monkeypatched _run -------------------------------------


def _fake_run_factory(validate_exit=0):
    def _fake_run(cmd, cwd, timeout=600):
        joined = " ".join(cmd)
        if "rev-parse" in joined:
            return {
                "cmd": cmd,
                "exit_code": 0,
                "stdout": "abc1234def\n",
                "stderr": "",
                "ok": True,
            }
        if "ls-files" in joined:
            return {
                "cmd": cmd,
                "exit_code": 0,
                "stdout": "a.py\nb.py\n",
                "stderr": "",
                "ok": True,
            }
        if "--validate" in joined:
            return {
                "cmd": cmd,
                "exit_code": validate_exit,
                "stdout": "{}",
                "stderr": "",
                "ok": True,
            }
        return {"cmd": cmd, "exit_code": 0, "stdout": "ok", "stderr": "", "ok": True}

    return _fake_run


def _fake_motor(tmp_path):
    motor = tmp_path / "motor"
    motor.mkdir()
    (motor / "MANIFEST.distribute").write_text("AGENTS.md\n", encoding="utf-8")
    psafe = motor / ".agent" / "runtime" / "pytest-safe"
    psafe.mkdir(parents=True)
    (psafe / "last-run.json").write_text(json.dumps({"exit_code": 0}), encoding="utf-8")
    return motor


def test_main_motor_only_creates_skeletons_and_relativized_findings(
    tmp_path, monkeypatch
):
    motor = _fake_motor(tmp_path)
    monkeypatch.setattr(csh, "_run", _fake_run_factory())
    out = tmp_path / "out"

    rc = csh.main(["--motor-root", str(motor), "--mode", "auto", "--out", str(out)])
    assert rc == 0

    # Skeletons + findings present.
    for fname in csh.SKELETON_FILES:
        assert (out / fname).exists()
    findings = json.loads((out / "findings.json").read_text(encoding="utf-8"))
    assert findings["mode"] == "motor-only"
    assert findings["degraded"] is True
    # Paths must be relativized in findings.
    assert str(motor) not in (out / "findings.json").read_text(encoding="utf-8")
    assert findings["topology"]["motor_root"] == "<MOTOR_ROOT>"
    # Declared coverage caveat present in a skeleton.
    assert "NO es verde global" in (out / "04_quality_gates.md").read_text(
        encoding="utf-8"
    )
    # raw/ must be kept out of git (it can leak personal paths/PII).
    gitignore = out / ".gitignore"
    assert gitignore.exists()
    assert "raw/" in gitignore.read_text(encoding="utf-8")


def test_main_full_mode_requires_destino_returns_3(tmp_path, monkeypatch):
    motor = _fake_motor(tmp_path)
    monkeypatch.setattr(csh, "_run", _fake_run_factory())
    rc = csh.main(
        ["--motor-root", str(motor), "--mode", "full", "--out", str(tmp_path / "o")]
    )
    assert rc == 3


def test_main_exit_critical_when_suite_red(tmp_path, monkeypatch):
    # Fixture C: exit_code=1 with NO failed/error ids and NO state_leak -> unexplained
    # -> must stay critical (fail-safe). This is the case the `!= []` bug would break.
    motor = _fake_motor(tmp_path)
    psafe = motor / ".agent" / "runtime" / "pytest-safe" / "last-run.json"
    psafe.write_text(json.dumps({"exit_code": 1}), encoding="utf-8")
    monkeypatch.setattr(csh, "_run", _fake_run_factory())
    out = tmp_path / "out"
    rc = csh.main(["--motor-root", str(motor), "--mode", "auto", "--out", str(out)])
    assert rc == 1
    findings = json.loads((out / "findings.json").read_text(encoding="utf-8"))
    assert "pytest_safe_last_run_nonzero" in findings["automatic_criticals"]


# ---- WOT-2026-021m: classify nonzero exit by CAUSE (state-leak vs real failure) ----


def _run_with_lastrun(tmp_path, monkeypatch, lastrun: dict) -> dict:
    """Run main() with a synthetic last-run.json; return the findings.json dict."""
    motor = _fake_motor(tmp_path)
    psafe = motor / ".agent" / "runtime" / "pytest-safe" / "last-run.json"
    psafe.write_text(json.dumps(lastrun), encoding="utf-8")
    monkeypatch.setattr(csh, "_run", _fake_run_factory())
    out = tmp_path / "out"
    csh.main(["--motor-root", str(motor), "--mode", "auto", "--out", str(out)])
    return json.loads((out / "findings.json").read_text(encoding="utf-8"))


def test_stateleak_only_is_warn_not_critical(tmp_path, monkeypatch):
    """Fixture A: exit=1 caused ONLY by state_leak -> WARN, not critical."""
    findings = _run_with_lastrun(
        tmp_path,
        monkeypatch,
        {
            "exit_code": 1,
            "failed_test_ids": [],
            "error_test_ids": [],
            "state_leak": ["AUDIT_WOT-2026-021d.md"],
        },
    )
    assert "pytest_safe_last_run_nonzero" not in findings["automatic_criticals"]
    assert "pytest_safe_last_run_stateleak_only" in findings["automatic_warnings"]


def test_real_failure_is_critical(tmp_path, monkeypatch):
    """Fixture B: exit=1 with failed_test_ids -> critical (real red suite)."""
    findings = _run_with_lastrun(
        tmp_path,
        monkeypatch,
        {
            "exit_code": 1,
            "failed_test_ids": ["tests/x.py::test_y"],
            "error_test_ids": [],
        },
    )
    assert "pytest_safe_last_run_nonzero" in findings["automatic_criticals"]
    assert "pytest_safe_last_run_stateleak_only" not in findings["automatic_warnings"]


def test_green_suite_no_flag(tmp_path, monkeypatch):
    """Fixture D: exit=0 -> neither critical nor warn."""
    findings = _run_with_lastrun(
        tmp_path, monkeypatch, {"exit_code": 0, "failed_test_ids": []}
    )
    assert "pytest_safe_last_run_nonzero" not in findings["automatic_criticals"]
    assert "pytest_safe_last_run_stateleak_only" not in findings["automatic_warnings"]


def test_failure_and_leak_together_is_critical(tmp_path, monkeypatch):
    """Fixture E: exit=1 with BOTH a real failure AND a state_leak -> critical.

    Guards branch order: a real failure must WIN over the state-leak, so a leak can
    never mask a genuine red suite (CONCERN-2 of the plan audit).
    """
    findings = _run_with_lastrun(
        tmp_path,
        monkeypatch,
        {
            "exit_code": 1,
            "failed_test_ids": ["tests/x.py::test_y"],
            "error_test_ids": [],
            "state_leak": ["AUDIT_WOT-2026-021d.md"],
        },
    )
    assert "pytest_safe_last_run_nonzero" in findings["automatic_criticals"]
    assert "pytest_safe_last_run_stateleak_only" not in findings["automatic_warnings"]


def test_main_rejects_non_motor_root(tmp_path):
    notmotor = tmp_path / "x"
    notmotor.mkdir()
    rc = csh.main(["--motor-root", str(notmotor), "--out", str(tmp_path / "o")])
    assert rc == 2


def test_run_captures_non_cp1252_stdout_without_crash(tmp_path):
    cmd = [
        sys.executable,
        "-c",
        "import sys; sys.stdout.buffer.write(b'\\x81'); sys.stdout.flush(); sys.exit(0)",
    ]
    res = csh._run(cmd, tmp_path)
    assert res["exit_code"] == 0
    assert res["stdout"] is not None
    assert "\ufffd" in res["stdout"]
    assert res["ok"] is True


def test_run_ok_false_on_nonzero_exit(tmp_path):
    cmd = [sys.executable, "-c", "import sys; sys.exit(1)"]
    res = csh._run(cmd, tmp_path)
    assert res["exit_code"] == 1
    assert res["ok"] is False


def test_run_ok_true_on_zero_exit(tmp_path):
    cmd = [sys.executable, "-c", "import sys; sys.exit(0)"]
    res = csh._run(cmd, tmp_path)
    assert res["exit_code"] == 0
    assert res["ok"] is True
