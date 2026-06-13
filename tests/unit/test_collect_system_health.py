"""Tests for scripts/collect_system_health.py (collector, not auditor).

Covers the contract conditions agreed for v0: topology/degraded mode, immutable
output dir (no overwrite), declared coverage in skeletons, path relativization,
and exit-on-critical (red suite).
"""

from __future__ import annotations

import importlib.util
import json
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
    motor = _fake_motor(tmp_path)
    # Red suite: last-run exit_code=1
    psafe = motor / ".agent" / "runtime" / "pytest-safe" / "last-run.json"
    psafe.write_text(json.dumps({"exit_code": 1}), encoding="utf-8")
    monkeypatch.setattr(csh, "_run", _fake_run_factory())
    out = tmp_path / "out"
    rc = csh.main(["--motor-root", str(motor), "--mode", "auto", "--out", str(out)])
    assert rc == 1
    findings = json.loads((out / "findings.json").read_text(encoding="utf-8"))
    assert "pytest_safe_last_run_nonzero" in findings["automatic_criticals"]


def test_main_rejects_non_motor_root(tmp_path):
    notmotor = tmp_path / "x"
    notmotor.mkdir()
    rc = csh.main(["--motor-root", str(notmotor), "--out", str(tmp_path / "o")])
    assert rc == 2
