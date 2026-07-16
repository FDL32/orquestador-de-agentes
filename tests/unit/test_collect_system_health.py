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
        "MOTOR_ROOT": Path("C:/Users/testuser/motor"),
        "DESTINO_ROOT": Path("C:/Users/testuser/dest"),
    }
    text = r"error at C:\Users\testuser\motor\x.py and C:/Users/testuser/dest/y.py"
    out = csh._relativize(text, roots)
    assert "C:/Users/testuser" not in out
    assert "C:\\Users\\testuser" not in out
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


def _fake_dest(tmp_path, lastrun: dict | None, delivery_authority: str | None = None):
    """A repo_destino with a .agent/ workspace and, optionally, its own last-run.json.

    WOT-2026-022v: `delivery_authority` defaults to None = NO work_plan field at all,
    because that is the shape of 12 of the 13 REAL destinos. A fixture that always
    declares the field would hide the very default that turned a red destino silent.
    """
    dest = tmp_path / "dest"
    (dest / ".agent").mkdir(parents=True)
    if delivery_authority is not None:
        collab = dest / ".agent" / "collaboration"
        collab.mkdir(parents=True, exist_ok=True)
        (collab / "work_plan.md").write_text(
            f"# Work Plan\n\n- **delivery_authority:** {delivery_authority}\n",
            encoding="utf-8",
        )
    if lastrun is not None:
        psafe = dest / ".agent" / "runtime" / "pytest-safe"
        psafe.mkdir(parents=True)
        (psafe / "last-run.json").write_text(json.dumps(lastrun), encoding="utf-8")
    return dest


def _run_full(
    tmp_path, monkeypatch, motor_lastrun, dest_lastrun, delivery_authority=None
):
    """Run main() in full mode (motor + destino); return (rc, findings)."""
    motor = _fake_motor(tmp_path)
    (motor / ".agent" / "runtime" / "pytest-safe" / "last-run.json").write_text(
        json.dumps(motor_lastrun), encoding="utf-8"
    )
    dest = _fake_dest(tmp_path, dest_lastrun, delivery_authority)
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
    """Fixture 1: motor last-run stale (exit 1), destino green (exit 0), DESTINO ticket.

    The destino is delivering, so ITS last-run is the critical axis -> no false-RED.
    022v: the ticket must DECLARE repo_destino, because that is what makes the destino
    the delivery repo. The motor's red does not vanish -- it is now a WARNING (visible).
    """
    _rc, findings = _run_full(
        tmp_path,
        monkeypatch,
        motor_lastrun={"exit_code": 1},
        dest_lastrun={"exit_code": 0},
        delivery_authority="repo_destino",
    )
    assert "pytest_safe_last_run_nonzero" not in findings["automatic_criticals"]
    assert findings["pytest_safe_last_run"]["source"] == "destino"
    assert findings["pytest_safe_last_run"]["exit_code"] == 0
    # ...and the motor's red is SURFACED, not discarded: the old code never even read it.
    assert "pytest_safe_last_run_nonzero_motor" in findings["automatic_warnings"]


def test_dest_real_failure_is_critical(tmp_path, monkeypatch):
    """Fixture 2: destino exit=1 with failed_test_ids -> real red suite -> critical."""
    _rc, findings = _run_full(
        tmp_path,
        monkeypatch,
        motor_lastrun={"exit_code": 0},
        dest_lastrun={"exit_code": 1, "failed_test_ids": ["tests/x.py::test_y"]},
        delivery_authority="repo_destino",
    )
    assert "pytest_safe_last_run_nonzero" in findings["automatic_criticals"]
    assert findings["pytest_safe_last_run"]["source"] == "destino"


def test_dest_missing_lastrun_is_missing_critical_not_motor_fallback(
    tmp_path, monkeypatch
):
    """Fixture 4: a DESTINO ticket whose destino has NO last-run.json.

    Must emit pytest_safe_last_run_missing (cannot confirm the delivery) and NOT silently
    fall back to the motor's last-run (that would be a false-green).
    """
    _rc, findings = _run_full(
        tmp_path,
        monkeypatch,
        motor_lastrun={"exit_code": 0},
        dest_lastrun=None,
        delivery_authority="repo_destino",
    )
    assert "pytest_safe_last_run_missing" in findings["automatic_criticals"]
    assert findings["pytest_safe_last_run"]["present"] is False
    assert findings["pytest_safe_last_run"]["source"] == "destino"


# ---------------------------------------------------------------------------
# WOT-2026-022v: delivery_authority decides SEVERITY, never VISIBILITY.
#
# The three tests above declare repo_destino. 12 of the 13 REAL destinos declare
# NOTHING -- and the previous attempt at this ticket routed the last-run FILE by that
# field, so a non-declaring destino had its own last-run silently discarded in favour of
# the motor's. A destino with a genuinely red suite reported rc=0, criticals=[].
# `Unificar_recibos_norma_43` carries a red last-run TODAY. An adversarial audit caught
# it before push. These are the tests that would have caught it here.
# ---------------------------------------------------------------------------


def test_a_red_destino_is_never_silent_even_when_it_declares_nothing(
    tmp_path, monkeypatch
):
    """THE false-green, in fixture form. Motor green + destino REALLY red + no declaration.

    The motor is the delivery repo (nothing declared), so the destino's red is not a
    blocker -- but it must be VISIBLE. Silence is the one thing that is not allowed.
    """
    rc, findings = _run_full(
        tmp_path,
        monkeypatch,
        motor_lastrun={"exit_code": 0},
        dest_lastrun={"exit_code": 1, "failed_test_ids": ["tests/x.py::test_roto"]},
        delivery_authority=None,  # 12 of 13 real destinos
    )
    assert "pytest_safe_last_run_nonzero_destino" in findings["automatic_warnings"], (
        "a red destino suite was DISCARDED: the collector went silent about it"
    )
    # It is not the delivery repo, so it does not block the motor's ticket...
    assert findings["automatic_criticals"] == []
    assert rc == 0
    # ...but its record is reported, not thrown away.
    assert findings["non_authoritative_health"]["repo"] == "destino"
    assert findings["non_authoritative_health"]["verdict"] == "red"
    assert findings["non_authoritative_health"]["last_run"]["exit_code"] == 1


def test_a_missing_destino_lastrun_is_visible_when_it_declares_nothing(
    tmp_path, monkeypatch
):
    """8 real destinos have .agent/ and no last-run. Not a blocker for a motor ticket,
    but 'I cannot confirm this repo is green' must reach the auditor."""
    rc, findings = _run_full(
        tmp_path,
        monkeypatch,
        motor_lastrun={"exit_code": 0},
        dest_lastrun=None,
        delivery_authority=None,
    )
    assert "pytest_safe_last_run_missing_destino" in findings["automatic_warnings"]
    assert findings["automatic_criticals"] == []
    assert rc == 0


def test_a_red_motor_is_never_silent_during_a_destino_ticket(tmp_path, monkeypatch):
    """The MIRROR bug, which the ORIGINAL code had: keying the file on `dest_ok` meant
    that whenever a destino was passed, the motor's last-run was never read at all. A red
    motor was invisible. Reproduced against the pre-fix code before writing this.
    """
    _rc, findings = _run_full(
        tmp_path,
        monkeypatch,
        motor_lastrun={"exit_code": 1, "failed_test_ids": ["tests/m.py::test_motor"]},
        dest_lastrun={"exit_code": 0},
        delivery_authority="repo_destino",
    )
    assert "pytest_safe_last_run_nonzero_motor" in findings["automatic_warnings"], (
        "a red MOTOR was discarded because a destino was being audited"
    )
    assert findings["non_authoritative_health"]["repo"] == "motor"
    assert findings["non_authoritative_health"]["verdict"] == "red"
    assert findings["non_authoritative_health"]["last_run"]["exit_code"] == 1


def test_the_dogfooding_fossil_does_not_false_red_a_green_motor(tmp_path, monkeypatch):
    """THE original 022v symptom. The dogfooding workspace never runs the canonical
    suite; its last-run is a fossil (exit=5, runner=unittest, 2026-07-10). With the motor
    green, auditing a MOTOR ticket must not go CRITICAL on that fossil -- but the fossil
    must still be visible as a warning.
    """
    rc, findings = _run_full(
        tmp_path,
        monkeypatch,
        motor_lastrun={"exit_code": 0},
        dest_lastrun={"exit_code": 5, "runner": "unittest"},
        delivery_authority=None,
    )
    assert findings["automatic_criticals"] == []
    assert rc == 0
    assert "pytest_safe_last_run_nonzero_destino" in findings["automatic_warnings"]


def test_the_non_authoritative_verdict_is_structured_not_buried(tmp_path, monkeypatch):
    """A warning appended to a flat list is easy to bury next to lint/stale noise.

    The non-delivery repo's health must be a FIRST-CLASS block with its own verdict, so a
    consumer can ask "is the other repo green?" without grepping strings.
    """
    _rc, findings = _run_full(
        tmp_path,
        monkeypatch,
        motor_lastrun={"exit_code": 0},
        dest_lastrun={"exit_code": 1, "failed_test_ids": ["tests/x.py::test_roto"]},
        delivery_authority=None,
    )
    auth = findings["authoritative_health"]
    non_auth = findings["non_authoritative_health"]

    assert auth["repo"] == "motor"
    assert auth["is_delivery"] is True
    assert auth["verdict"] == "green"
    assert auth["blocking"] is False

    assert non_auth["repo"] == "destino"
    assert non_auth["is_delivery"] is False
    assert non_auth["verdict"] == "red", "el destino rojo debe tener veredicto propio"
    assert non_auth["blocking"] is False, "no bloquea un ticket del motor..."
    assert "pytest_safe_last_run_nonzero_destino" in non_auth["findings"]
    assert non_auth["last_run"]["exit_code"] == 1


HEALTH_BLOCK_KEYS = {
    "repo",
    "is_delivery",
    "verdict",
    "blocking",
    "stale",
    "exit_code",
    "findings",
    "last_run",
}
VERDICTS = {"green", "red", "stateleak", "unknown"}


def test_health_block_shape_is_stable(tmp_path, monkeypatch):
    """CONTRACT on the SHAPE, not on one field at a time.

    Partial asserts drift: a refactor can drop a key and every existing test still passes
    because none of them looked at that key. This pins the exact key set and the closed
    set of verdicts for BOTH blocks, so removing or renaming one is a red test.
    """
    _rc, findings = _run_full(
        tmp_path,
        monkeypatch,
        motor_lastrun={"exit_code": 0},
        dest_lastrun={"exit_code": 1, "failed_test_ids": ["tests/x.py::test_roto"]},
        delivery_authority=None,
    )

    for key in ("authoritative_health", "non_authoritative_health"):
        block = findings[key]
        assert set(block) == HEALTH_BLOCK_KEYS, (
            f"{key} cambio de forma: {sorted(block)}"
        )
        assert block["repo"] in {"motor", "destino"}
        assert block["verdict"] in VERDICTS, f"{key}.verdict fuera del enum"
        assert isinstance(block["is_delivery"], bool)
        assert isinstance(block["blocking"], bool)
        assert isinstance(block["stale"], bool)
        assert isinstance(block["findings"], list)
        assert isinstance(block["last_run"], dict)

    # Exactly one of the two blocks delivers, and only a delivering repo can block.
    auth, non_auth = (
        findings["authoritative_health"],
        findings["non_authoritative_health"],
    )
    assert auth["is_delivery"] is True
    assert non_auth["is_delivery"] is False
    assert non_auth["blocking"] is False
    assert auth["repo"] != non_auth["repo"]
    # `delivery_authority` must be published: it is what decides severity.
    assert findings["delivery_authority"] in {"repo_motor", "repo_destino"}


def test_console_announces_a_red_non_authoritative_repo(tmp_path, monkeypatch, capsys):
    """The JSON block is for machines; a human reads the console. A non-blocking red repo
    that only exists inside findings.json is a red repo nobody will ever look at."""
    _run_full(
        tmp_path,
        monkeypatch,
        motor_lastrun={"exit_code": 0},
        dest_lastrun={"exit_code": 1, "failed_test_ids": ["tests/x.py::test_roto"]},
        delivery_authority=None,
    )
    out = capsys.readouterr().out
    assert "el repo que NO entrega (destino)" in out
    assert "'red'" in out
    assert "NO esta verde" in out


def test_console_stays_quiet_when_the_other_repo_is_green(
    tmp_path, monkeypatch, capsys
):
    """Control: the notice must be a SIGNAL, not a permanent banner. If it printed always,
    it would be ignored always -- and the test above would pass for the wrong reason.
    """
    _run_full(
        tmp_path,
        monkeypatch,
        motor_lastrun={"exit_code": 0},
        dest_lastrun={"exit_code": 0},
        delivery_authority=None,
    )
    out = capsys.readouterr().out
    assert "el repo que NO entrega" not in out


def test_the_delivery_repo_block_is_marked_blocking_when_red(tmp_path, monkeypatch):
    """Control on the same structure: the delivery repo's block must say `blocking`."""
    _rc, findings = _run_full(
        tmp_path,
        monkeypatch,
        motor_lastrun={"exit_code": 1, "failed_test_ids": ["tests/m.py::test_m"]},
        dest_lastrun={"exit_code": 0},
        delivery_authority=None,
    )
    assert findings["authoritative_health"]["verdict"] == "red"
    assert findings["authoritative_health"]["blocking"] is True
    assert findings["non_authoritative_health"]["verdict"] == "green"


def test_a_red_delivery_repo_still_blocks(tmp_path, monkeypatch):
    """Control: severity routing must not degrade into 'nothing is ever critical'.

    Without this, making everything a warning would satisfy every test above.
    """
    rc, findings = _run_full(
        tmp_path,
        monkeypatch,
        motor_lastrun={"exit_code": 1, "failed_test_ids": ["tests/m.py::test_motor"]},
        dest_lastrun={"exit_code": 0},
        delivery_authority=None,  # motor delivers
    )
    assert "pytest_safe_last_run_nonzero" in findings["automatic_criticals"]
    assert rc == 1


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
    tmp_path,
    monkeypatch,
    *,
    dest_delivery,
    dest_lastrun,
    head_fails=False,
    motor_lastrun=None,
):
    """Run full mode with distinct motor/dest HEADs; return findings.

    WOT-2026-022v: `motor_lastrun` exists because the DELIVERY repo's record is the one
    under `pytest_safe_last_run`. For a repo_motor ticket that is the MOTOR's file, so a
    staleness test for that case must be able to STAMP it. Without this the test asserts
    `stale is False` about a fixture that has no tested_commit_sha at all, and passes for
    the wrong reason -- which it did, until a mutation of the SHA axis failed to kill it.
    """
    motor = _fake_motor(tmp_path)
    if motor_lastrun is not None:
        (motor / ".agent" / "runtime" / "pytest-safe" / "last-run.json").write_text(
            json.dumps(motor_lastrun), encoding="utf-8"
        )
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

    022v REWROTE this test. It used to stamp only the DESTINO's last-run and assert "not
    stale". Once the DELIVERY repo's record is the one under `pytest_safe_last_run`, a
    repo_motor ticket reads the MOTOR's file -- so the old fixture asserted about a record
    with no tested_commit_sha at all and passed VACUOUSLY (no mutation of the SHA axis
    could turn it red). Now the MOTOR's last-run carries the sha and the DESTINO's carries
    a DECOY that must not be compared against the motor's HEAD.
    """
    findings = _run_full_staleness(
        tmp_path,
        monkeypatch,
        dest_delivery="repo_motor",  # default authority
        motor_lastrun={"exit_code": 0, "tested_commit_sha": _MOTOR_SHA},
        dest_lastrun={"exit_code": 0, "tested_commit_sha": "c" * 40},  # decoy
    )
    assert findings["pytest_safe_last_run"]["source"] == "motor"
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


# ---- WOT-2026-024m: docstring vs actually-executed checks -------------------


def test_docstring_does_not_promise_checks_the_collector_never_runs(
    tmp_path, monkeypatch
):
    """WOT-2026-024m: the module docstring must not advertise a check the
    collector does not actually run.

    The docstring used to list "encoding guard" and a "manifest-vs-tracked
    diff" among the checks, but the real ``checks[...]`` block runs neither
    (MANIFEST.distribute is only checked for existence, never diffed). That
    doc-vs-code drift misleads anyone reading the collector's contract.

    This test runs main() and reads the checks the collector REALLY produced,
    then asserts the phantom phrases are absent from the docstring. Mutation:
    re-add "encoding guard" (or "manifest-vs-tracked") to the docstring without
    implementing the check -> this test fails.
    """
    motor = _fake_motor(tmp_path)
    monkeypatch.setattr(csh, "_run", _fake_run_factory())
    out = tmp_path / "out"
    rc = csh.main(["--motor-root", str(motor), "--mode", "auto", "--out", str(out)])
    assert rc == 0

    findings = json.loads((out / "findings.json").read_text(encoding="utf-8"))
    real_checks = set(findings["checks"].keys())

    # No real check corresponds to an encoding guard or a manifest diff.
    assert not any("encoding" in c for c in real_checks)
    assert not any("manifest" in c.lower() for c in real_checks)

    doc = csh.__doc__ or ""
    doc_lower = doc.lower()
    # The phantom phrases must NOT appear in the "During" checks enumeration.
    assert "encoding guard" not in doc_lower, (
        "docstring advertises an 'encoding guard' check the collector never runs"
    )
    assert "manifest-vs-tracked" not in doc_lower, (
        "docstring advertises a 'manifest-vs-tracked diff' the collector never runs"
    )


# ---- WOT-2026-022l: caducated last-run degrades to WARN, not critical ------


def _run_full_with_session_start(
    tmp_path, monkeypatch, motor_lastrun, dest_lastrun, session_start
):
    """Like _run_full but passes --session-start (WOT-2026-022l)."""
    motor = _fake_motor(tmp_path)
    (motor / ".agent" / "runtime" / "pytest-safe" / "last-run.json").write_text(
        json.dumps(motor_lastrun), encoding="utf-8"
    )
    dest = _fake_dest(tmp_path, dest_lastrun, delivery_authority="repo_motor")
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
            "--session-start",
            session_start,
        ]
    )
    findings = json.loads((out / "findings.json").read_text(encoding="utf-8"))
    return rc, findings


def test_caducated_destino_nonzero_is_warn_not_critical(tmp_path, monkeypatch):
    """WOT-2026-022l decision (b): a destino last-run that FINISHED BEFORE the
    session started, with an unexplained nonzero (exit 5, no-tests-collected),
    degrades to a WARN (evidencia caducada), NOT a spurious critical.

    The dogfooding workspace keeps an old exit-5 last-run that used to
    false-critical EVERY code-only close even with a green fresh motor suite.
    """
    # Destino delivers (repo_motor authority makes MOTOR the delivery repo, so the
    # DESTINO is the non-delivery repo -> its nonzero is already a warning-severity
    # target; but its CAUSE classification still applies). Old finished_at.
    dest_old = {
        "exit_code": 5,
        "failed_test_ids": [],
        "error_test_ids": [],
        "finished_at": "2026-07-10T09:00:00+00:00",  # before session_start
    }
    motor_green = {"exit_code": 0, "finished_at": "2026-07-16T02:00:00+00:00"}
    _rc, findings = _run_full_with_session_start(
        tmp_path,
        monkeypatch,
        motor_green,
        dest_old,
        session_start="2026-07-16T01:00:00+00:00",
    )
    # The caducated nonzero must NOT be a critical; it is a classified WARN.
    assert "pytest_safe_last_run_nonzero_destino" not in findings["automatic_criticals"]
    assert (
        "pytest_safe_last_run_stale_nonzero_destino" in findings["automatic_warnings"]
    ), "a caducated nonzero must degrade to a classified WARN, not a critical"


def test_recent_destino_nonzero_stays_critical(tmp_path, monkeypatch):
    """The counterpart (never option (a)): a RECENT unexplained nonzero (finished
    AFTER the session start) stays a critical -- a real exit-5 today must not be
    silenced by the caducation rule.

    Here the destino IS the delivery repo (declares repo_destino) so its nonzero
    is a critical when recent.
    """
    dest = _fake_dest(
        tmp_path,
        {
            "exit_code": 5,
            "failed_test_ids": [],
            "error_test_ids": [],
            "finished_at": "2026-07-16T03:00:00+00:00",  # AFTER session_start
        },
        delivery_authority="repo_destino",
    )
    motor = _fake_motor(tmp_path)
    (motor / ".agent" / "runtime" / "pytest-safe" / "last-run.json").write_text(
        json.dumps({"exit_code": 0, "finished_at": "2026-07-16T03:00:00+00:00"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(csh, "_run", _fake_run_factory())
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
            "--session-start",
            "2026-07-16T01:00:00+00:00",
        ]
    )
    findings = json.loads((out / "findings.json").read_text(encoding="utf-8"))
    assert "pytest_safe_last_run_nonzero" in findings["automatic_criticals"], (
        "a RECENT unexplained nonzero must stay critical (never silenced)"
    )


def test_caducated_helper_fail_safe_without_timestamp():
    """_last_run_is_caducated fails safe to NOT caducated when finished_at is
    absent/unparseable -- we never silence a red we cannot date."""
    from datetime import datetime, timezone

    now = datetime(2026, 7, 16, tzinfo=timezone.utc)
    assert csh._last_run_is_caducated({"exit_code": 5}, now) is False
    assert csh._last_run_is_caducated({"finished_at": "not-a-date"}, now) is False
    assert (
        csh._last_run_is_caducated({"finished_at": "2020-01-01T00:00:00+00:00"}, now)
        is True
    )


# ---- WOT-2026-024a: --validate --no-heal keeps the collector read-only ---------


def test_validate_no_heal_does_not_write_state_md_real_path(tmp_path):
    """`agent_controller --validate --no-heal` must NOT heal (write) the tracked
    STATE.md, even under real bus drift.

    REAL PATH by design: a subprocess to the controller (NOT a mocked csh._run),
    so it exercises the actual sync_state_projection call that the mocked-_run
    tests in this file can never reach -- a hermetic mock of _run passes GREEN
    with the defect live (that is exactly why 024a needs a real-path test).

    Mutation (teeth): remove the `if not no_heal:` guard in _handle_validate (heal
    always) and the --no-heal run heals STATE.md -> the byte-identity assert FAILS.
    """
    import subprocess

    controller = Path(__file__).resolve().parents[2] / ".agent" / "agent_controller.py"
    project_root = Path(__file__).resolve().parents[2]

    fx = tmp_path / "fx"
    collab = fx / ".agent" / "collaboration"
    events = fx / ".agent" / "runtime" / "events"
    collab.mkdir(parents=True)
    events.mkdir(parents=True)
    # Non-seed-neutral (ID != none) so --validate reaches the heal branch.
    (collab / "work_plan.md").write_text(
        "# Plan\n\n- **ID:** WOT-TEST-001\n- **Estado:** IN_PROGRESS\n",
        encoding="utf-8",
    )
    (collab / "execution_log.md").write_text(
        "# Log\n\n- **Estado:** IN_PROGRESS\n", encoding="utf-8"
    )
    state = collab / "STATE.md"
    state_content = "ACTIVE_TICKET: WOT-TEST-001\nSTATUS: IN_PROGRESS\n"
    state.write_text(state_content, encoding="utf-8")
    # Bus derives READY_FOR_REVIEW != STATE.md's IN_PROGRESS -> DRIFTED.
    (events / "events.jsonl").write_text(
        '{"event_type": "STATE_CHANGED", "ticket_id": "WOT-TEST-001", '
        '"payload": {"to_state": "READY_FOR_REVIEW"}}\n',
        encoding="utf-8",
    )
    # git-init the fixture so any git walk-up stays hermetic (WOT-2026-020r).
    subprocess.run(["git", "init", "-q", str(fx)], check=True)

    def _validate(*extra: str) -> None:
        subprocess.run(
            [
                sys.executable,
                str(controller),
                "--validate",
                "--json",
                "--force",
                *extra,
                "--project-root",
                str(fx),
            ],
            cwd=str(project_root),
            capture_output=True,
            text=True,
        )

    # --no-heal: STATE.md content is UNCHANGED (no write under drift).
    _validate("--no-heal")
    assert state.read_text(encoding="utf-8") == state_content, (
        "STATE.md was healed under --no-heal (read-only contract violated)"
    )

    # Sanity: the fixture genuinely drifts and the REAL heal path fires WITHOUT the
    # flag -- so the assertion above is meaningful, not vacuous.
    _validate()
    healed = state.read_text(encoding="utf-8")
    assert healed != state_content and "READY_FOR_REVIEW" in healed, (
        "fixture did not drift/heal without --no-heal; the --no-heal test would be vacuous"
    )


def test_collector_passes_no_heal_to_both_validate_invocations(tmp_path, monkeypatch):
    """The READ-ONLY collector passes --no-heal to BOTH --validate invocations
    (motor and destino). Mutation: drop --no-heal from either invocation -> FAILS."""
    motor = _fake_motor(tmp_path)
    dest = _fake_dest(tmp_path, lastrun={"exit_code": 0})

    captured: list[list[str]] = []
    passthrough = _fake_run_factory()

    def _spy(cmd, cwd, timeout=600):
        captured.append(list(cmd))
        return passthrough(cmd, cwd, timeout)

    monkeypatch.setattr(csh, "_run", _spy)
    csh.main(
        [
            "--motor-root",
            str(motor),
            "--project-root",
            str(dest),
            "--mode",
            "full",
            "--out",
            str(tmp_path / "out"),
        ]
    )
    validate_cmds = [cmd for cmd in captured if "--validate" in cmd]
    assert len(validate_cmds) >= 2, (
        f"expected motor + destino --validate invocations; got {validate_cmds}"
    )
    for cmd in validate_cmds:
        assert "--no-heal" in cmd, f"--validate invocation missing --no-heal: {cmd}"
