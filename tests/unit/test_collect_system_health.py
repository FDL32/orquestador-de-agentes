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


# ---- WOT-2026-021c: read the DESTINO's last-run when dest_ok (not the motor's) ----


def _fake_dest(tmp_path, lastrun: dict | None):
    """A repo_destino with a .agent/ workspace and, optionally, its own last-run.json."""
    dest = tmp_path / "dest"
    (dest / ".agent").mkdir(parents=True)
    if lastrun is not None:
        psafe = dest / ".agent" / "runtime" / "pytest-safe"
        psafe.mkdir(parents=True)
        (psafe / "last-run.json").write_text(json.dumps(lastrun), encoding="utf-8")
    return dest


def _run_full(tmp_path, monkeypatch, motor_lastrun, dest_lastrun):
    """Run main() in full mode (motor + destino); return (rc, findings)."""
    motor = _fake_motor(tmp_path)
    (motor / ".agent" / "runtime" / "pytest-safe" / "last-run.json").write_text(
        json.dumps(motor_lastrun), encoding="utf-8"
    )
    dest = _fake_dest(tmp_path, dest_lastrun)
    monkeypatch.setattr(csh, "_run", _fake_run_factory())
    out = tmp_path / "out"
    rc = csh.main(
        [
            "--motor-root",
            str(motor),
            "--project-root",
            str(dest),
            "--mode",
            "full",
            "--out",
            str(out),
        ]
    )
    findings = json.loads((out / "findings.json").read_text(encoding="utf-8"))
    return rc, findings


def test_dest_green_motor_stale_is_not_false_red(tmp_path, monkeypatch):
    """Fixture 1: motor last-run stale (exit 1), destino green (exit 0).

    The collector must read the DESTINO's last-run -> no false-RED of the destino.
    """
    _rc, findings = _run_full(
        tmp_path,
        monkeypatch,
        motor_lastrun={"exit_code": 1},
        dest_lastrun={"exit_code": 0},
    )
    assert "pytest_safe_last_run_nonzero" not in findings["automatic_criticals"]
    assert findings["pytest_safe_last_run"]["source"] == "destino"
    assert findings["pytest_safe_last_run"]["exit_code"] == 0


def test_dest_real_failure_is_critical(tmp_path, monkeypatch):
    """Fixture 2: destino exit=1 with failed_test_ids -> real red suite -> critical."""
    _rc, findings = _run_full(
        tmp_path,
        monkeypatch,
        motor_lastrun={"exit_code": 0},
        dest_lastrun={"exit_code": 1, "failed_test_ids": ["tests/x.py::test_y"]},
    )
    assert "pytest_safe_last_run_nonzero" in findings["automatic_criticals"]
    assert findings["pytest_safe_last_run"]["source"] == "destino"


def test_dest_missing_lastrun_is_missing_critical_not_motor_fallback(
    tmp_path, monkeypatch
):
    """Fixture 4: dest_ok but destino has NO last-run.json.

    Must emit pytest_safe_last_run_missing (cannot confirm green) and NOT silently
    fall back to the motor's last-run (that would be a false-green). Guards the
    principal risk of the plan audit.
    """
    _rc, findings = _run_full(
        tmp_path, monkeypatch, motor_lastrun={"exit_code": 0}, dest_lastrun=None
    )
    assert "pytest_safe_last_run_missing" in findings["automatic_criticals"]
    assert findings["pytest_safe_last_run"]["present"] is False
    assert findings["pytest_safe_last_run"]["source"] == "destino"


def test_motor_only_still_reads_motor(tmp_path, monkeypatch):
    """Fixture 3: motor-only mode (no destino) keeps reading the motor's last-run."""
    motor = _fake_motor(tmp_path)
    (motor / ".agent" / "runtime" / "pytest-safe" / "last-run.json").write_text(
        json.dumps({"exit_code": 1}), encoding="utf-8"
    )
    monkeypatch.setattr(csh, "_run", _fake_run_factory())
    out = tmp_path / "out"
    csh.main(["--motor-root", str(motor), "--mode", "auto", "--out", str(out)])
    findings = json.loads((out / "findings.json").read_text(encoding="utf-8"))
    assert findings["pytest_safe_last_run"]["source"] == "motor"
    assert "pytest_safe_last_run_nonzero" in findings["automatic_criticals"]


# ---- WOT-2026-021n: flag a STALE last-run (tested an old commit) as a WARN ----

_MOTOR_SHA = "a" * 40
_DEST_SHA = "b" * 40


def _fake_run_per_root(motor: Path, dest: Path, *, head_fails: bool = False):
    """A _run fake that returns a DISTINCT HEAD sha per repo root (motor vs dest).

    The default _fake_run_factory returns one sha ('abc1234def') for every rev-parse,
    so it cannot exercise the delivery_authority axis (motor != dest). This variant
    keys the rev-parse output on the cwd. `head_fails` makes rev-parse exit 1 (HEAD
    None edge). Non-git commands keep the benign defaults.
    """
    motor_s = str(motor)

    def _fake(cmd, cwd, timeout=600):
        joined = " ".join(cmd)
        if "rev-parse" in joined:
            if head_fails:
                return {
                    "cmd": cmd,
                    "exit_code": 1,
                    "stdout": "",
                    "stderr": "",
                    "ok": False,
                }
            sha = _MOTOR_SHA if str(cwd) == motor_s else _DEST_SHA
            return {
                "cmd": cmd,
                "exit_code": 0,
                "stdout": sha + "\n",
                "stderr": "",
                "ok": True,
            }
        if "ls-files" in joined:
            return {
                "cmd": cmd,
                "exit_code": 0,
                "stdout": "a.py\n",
                "stderr": "",
                "ok": True,
            }
        if "--validate" in joined:
            return {
                "cmd": cmd,
                "exit_code": 0,
                "stdout": "{}",
                "stderr": "",
                "ok": True,
            }
        return {"cmd": cmd, "exit_code": 0, "stdout": "ok", "stderr": "", "ok": True}

    return _fake


def _write_wp(root: Path, delivery_authority: str):
    """Write a minimal work_plan.md declaring delivery_authority in `root`."""
    collab = root / ".agent" / "collaboration"
    collab.mkdir(parents=True, exist_ok=True)
    (collab / "work_plan.md").write_text(
        f"# Plan\n\n- **delivery_authority:** {delivery_authority}\n", encoding="utf-8"
    )


def _run_full_staleness(
    tmp_path, monkeypatch, *, dest_delivery, dest_lastrun, head_fails=False
):
    """Run full mode with distinct motor/dest HEADs; return findings."""
    motor = _fake_motor(tmp_path)
    dest = _fake_dest(tmp_path, dest_lastrun)
    _write_wp(dest, dest_delivery)
    monkeypatch.setattr(
        csh, "_run", _fake_run_per_root(motor, dest, head_fails=head_fails)
    )
    out = tmp_path / "out"
    csh.main(
        [
            "--motor-root",
            str(motor),
            "--project-root",
            str(dest),
            "--mode",
            "full",
            "--out",
            str(out),
        ]
    )
    return json.loads((out / "findings.json").read_text(encoding="utf-8"))


def test_stale_flagged_when_tested_sha_differs_from_delivery_head(
    tmp_path, monkeypatch
):
    """DoD-a: last-run tested a sha != the delivery HEAD -> stale True + warn."""
    # dest delivery_authority repo_destino -> compare vs dest HEAD (_DEST_SHA);
    # last-run tested a different sha -> stale.
    findings = _run_full_staleness(
        tmp_path,
        monkeypatch,
        dest_delivery="repo_destino",
        dest_lastrun={"exit_code": 0, "tested_commit_sha": "c" * 40},
    )
    assert findings["pytest_safe_last_run"]["stale"] is True
    assert "pytest_safe_last_run_stale" in findings["automatic_warnings"]


def test_fresh_not_flagged_when_tested_sha_matches(tmp_path, monkeypatch):
    """DoD-b: last-run tested exactly the delivery HEAD -> stale False, no warn."""
    findings = _run_full_staleness(
        tmp_path,
        monkeypatch,
        dest_delivery="repo_destino",
        dest_lastrun={"exit_code": 0, "tested_commit_sha": _DEST_SHA},
    )
    assert findings["pytest_safe_last_run"]["stale"] is False
    assert "pytest_safe_last_run_stale" not in findings["automatic_warnings"]


def test_repo_motor_ticket_compares_vs_motor_not_dest(tmp_path, monkeypatch):
    """DoD-c (the BLOCKER): dest_ok + delivery_authority repo_motor + last-run stamped
    with the MOTOR head must compare vs MOTOR head -> NOT stale (no false-positive).

    This is the exact real-world topology: a destino runs the suite for a repo_motor
    ticket; the last-run file lives under the destino but tested_commit_sha is the
    MOTOR HEAD. Comparing against dest_head (the v1-plan bug) would be spurious stale.
    """
    findings = _run_full_staleness(
        tmp_path,
        monkeypatch,
        dest_delivery="repo_motor",  # default authority
        dest_lastrun={"exit_code": 0, "tested_commit_sha": _MOTOR_SHA},
    )
    assert findings["pytest_safe_last_run"]["stale"] is False, (
        "repo_motor ticket must compare tested_sha vs MOTOR head, not dest head"
    )
    assert "pytest_safe_last_run_stale" not in findings["automatic_warnings"]


def test_repo_destino_ticket_stale_vs_dest_head(tmp_path, monkeypatch):
    """DoD-d: dest_ok + delivery_authority repo_destino + tested_sha != dest head -> stale."""
    findings = _run_full_staleness(
        tmp_path,
        monkeypatch,
        dest_delivery="repo_destino",
        dest_lastrun={"exit_code": 0, "tested_commit_sha": _MOTOR_SHA},  # != _DEST_SHA
    )
    assert findings["pytest_safe_last_run"]["stale"] is True
    assert "pytest_safe_last_run_stale" in findings["automatic_warnings"]


def test_no_tested_sha_is_not_stale(tmp_path, monkeypatch):
    """DoD-e: last-run without tested_commit_sha -> stale False (no spurious mark)."""
    findings = _run_full_staleness(
        tmp_path,
        monkeypatch,
        dest_delivery="repo_destino",
        dest_lastrun={"exit_code": 0},  # no tested_commit_sha
    )
    assert findings["pytest_safe_last_run"]["stale"] is False
    assert "pytest_safe_last_run_stale" not in findings["automatic_warnings"]


def test_head_none_is_not_stale(tmp_path, monkeypatch):
    """DoD-f: unknown HEAD (rev-parse fails) -> stale False."""
    findings = _run_full_staleness(
        tmp_path,
        monkeypatch,
        dest_delivery="repo_destino",
        dest_lastrun={"exit_code": 0, "tested_commit_sha": "c" * 40},
        head_fails=True,
    )
    assert findings["pytest_safe_last_run"]["stale"] is False
    assert "pytest_safe_last_run_stale" not in findings["automatic_warnings"]


def test_stale_is_never_a_critical(tmp_path, monkeypatch):
    """DoD-g (NON-GOAL duro): a stale last-run with exit 0 produces ZERO criticals."""
    findings = _run_full_staleness(
        tmp_path,
        monkeypatch,
        dest_delivery="repo_destino",
        dest_lastrun={"exit_code": 0, "tested_commit_sha": "c" * 40},
    )
    assert findings["pytest_safe_last_run"]["stale"] is True
    assert findings["automatic_criticals"] == []
    assert "pytest_safe_last_run_stale" in findings["automatic_warnings"]


def test_read_delivery_authority_default_and_explicit(tmp_path):
    """The helper mirrors pre_handoff_guard: repo_destino only when declared."""
    # missing work_plan -> default repo_motor
    assert csh._read_delivery_authority(tmp_path) == "repo_motor"
    _write_wp(tmp_path, "repo_motor")
    assert csh._read_delivery_authority(tmp_path) == "repo_motor"
    _write_wp(tmp_path, "repo_destino")
    assert csh._read_delivery_authority(tmp_path) == "repo_destino"


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


# ---- WOT-2026-023x: the collector never mutates the tracked INDEX.md by default --

# The register lives at out_dir.parent/INDEX.md, a TRACKED file in the dogfooding
# workspace. Writing it on every run made this "read-only collector" mutate the
# working tree (the sibling batch audit hit that B3 violation live). These tests
# are STRUCTURAL (they check whether the INDEX.md file exists), not porcelain-based:
# porcelain would couple the test to the real motor tree (the false-green of
# WOT-2026-023p) and, worse, would go blind if the audit dir were ever gitignored.
# Structural existence isolates the INDEX.md branch so the DoD (b) mutation reaches it.


def test_default_run_does_not_create_tracked_index(tmp_path, monkeypatch):
    """DoD (a): a default invocation writes nothing outside its own out_dir.

    Mutation-to-prove (DoD b): reverting the --publish-index gate so INDEX.md is
    written unconditionally makes THIS assertion fail (the file reappears next to
    out_dir without the flag). The branch under test is the ONLY thing that decides
    the verdict -- no porcelain, no dependency on the real tree.
    """
    motor = _fake_motor(tmp_path)
    monkeypatch.setattr(csh, "_run", _fake_run_factory())
    out = tmp_path / "audits" / "out"

    rc = csh.main(["--motor-root", str(motor), "--mode", "auto", "--out", str(out)])
    assert rc == 0
    # The collection artifacts DO exist (the run really ran)...
    assert (out / "findings.json").exists()
    # ...but the shared, tracked INDEX.md register was NOT written.
    assert not (out.parent / "INDEX.md").exists()


def test_publish_index_flag_writes_the_register(tmp_path, monkeypatch):
    """The register is still reachable, but only opt-in via --publish-index.

    This pins the flag so a future refactor cannot silently drop the capability
    (which would make the default-off test pass vacuously).
    """
    motor = _fake_motor(tmp_path)
    monkeypatch.setattr(csh, "_run", _fake_run_factory())
    out = tmp_path / "audits" / "out"

    rc = csh.main(
        [
            "--motor-root",
            str(motor),
            "--mode",
            "auto",
            "--out",
            str(out),
            "--publish-index",
        ]
    )
    assert rc == 0
    index = out.parent / "INDEX.md"
    assert index.exists()
    body = index.read_text(encoding="utf-8")
    assert "System Health Audits" in body
    assert out.name in body  # the row references this run's dir
