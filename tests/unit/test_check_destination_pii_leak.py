"""Barrier tests for check_destination_pii_leak.py (WOT-2026-020t).

The auditor must LIST every included destination that tracks a managed PII
surface (the link file or .agent/collaboration/) WITHOUT touching anything;
exclude the motor and its dogfooding workspace by IDENTITY; and treat an
included destination without its own .git as an OPERATIONAL ERROR (exit 2,
CF-audit E1: git would walk up to a parent repo, so "0 leaks" must never mean
"0 audited").

Hermetic by construction (vector git WOT-2026-020r): every fixture repo runs
its own ``git init -b main``; the real machine's destinations are never
touched by these tests.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.check_destination_pii_leak import main, run_audit
from scripts.prepush_check import run_destination_pii_check


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GUARD_PATH = PROJECT_ROOT / "scripts" / "check_destination_pii_leak.py"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )


def _git_out(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )
    return proc.stdout


def _commit_all(repo: Path, paths: list[str]) -> None:
    _git(repo, "add", "--", *paths)
    _git(
        repo,
        "-c",
        "user.email=t@t",
        "-c",
        "user.name=t",
        "commit",
        "-q",
        "-m",
        "fixture",
    )


def _make_destination(
    parent: Path,
    name: str,
    link_motor_root: Path,
    *,
    with_git: bool = True,
    track_link: bool = False,
    track_collab: bool = False,
) -> Path:
    """Sibling destination with a valid link; optionally git-init'd and dirty."""
    root = parent / name
    config = root / ".agent" / "config"
    config.mkdir(parents=True)
    link = config / "motor_destination_link.json"
    link.write_text(
        json.dumps(
            {
                "motor_root": str(link_motor_root),
                "destination_root": str(root),
                "ticket_prefix": name[:3].upper(),
            }
        ),
        encoding="utf-8",
    )
    collab = root / ".agent" / "collaboration"
    collab.mkdir(parents=True)
    (collab / "execution_log.md").write_text(
        "ruta local C:/Users/someone/x\n", encoding="utf-8"
    )
    if with_git:
        _git(root, "init", "-q", "-b", "main")
        tracked: list[str] = []
        if track_link:
            tracked.append(".agent/config/motor_destination_link.json")
        if track_collab:
            tracked.append(".agent/collaboration")
        if tracked:
            _commit_all(root, tracked)
    return root


def _make_motor(parent: Path) -> Path:
    motor = parent / "motor"
    motor.mkdir()
    return motor


# --------------------------------------------------------------- DoD (a): audit


def test_clean_destination_is_exit_0(tmp_path: Path) -> None:
    motor = _make_motor(tmp_path)
    other_motor = tmp_path / "other_motor"
    _make_destination(tmp_path, "dest_clean", other_motor)
    rc = main(["--motor-root", str(motor)])
    assert rc == 0


def test_tracked_link_is_detected_and_exit_1(tmp_path: Path) -> None:
    motor = _make_motor(tmp_path)
    other_motor = tmp_path / "other_motor"
    dest = _make_destination(tmp_path, "dest_link", other_motor, track_link=True)
    audits, _ = run_audit(motor)
    leaks = [a for a in audits if a.leaking]
    assert len(leaks) == 1
    assert leaks[0].root == dest.resolve()
    assert ".agent/config/motor_destination_link.json" in leaks[0].tracked_files
    assert main(["--motor-root", str(motor)]) == 1


def test_tracked_collaboration_is_detected(tmp_path: Path) -> None:
    motor = _make_motor(tmp_path)
    other_motor = tmp_path / "other_motor"
    _make_destination(tmp_path, "dest_collab", other_motor, track_collab=True)
    audits, _ = run_audit(motor)
    leaks = [a for a in audits if a.leaking]
    assert len(leaks) == 1
    assert any(f.startswith(".agent/collaboration/") for f in leaks[0].tracked_files)


# ----------------------------------------- DoD (b): exclusion by IDENTITY


def test_dogfooding_workspace_is_excluded_external_is_not(tmp_path: Path) -> None:
    """A dirty workspace whose link declares THIS motor is excluded by identity;
    an equally dirty external destination IS reported."""
    motor = _make_motor(tmp_path)
    other_motor = tmp_path / "other_motor"
    workspace = _make_destination(tmp_path, "motor_workspace", motor, track_collab=True)
    external = _make_destination(tmp_path, "dest_dirty", other_motor, track_collab=True)
    audits, discovery = run_audit(motor)
    audited_roots = {a.root for a in audits}
    assert workspace.resolve() not in audited_roots
    assert external.resolve() in audited_roots
    assert any(
        Path(resolved) == workspace.resolve() for _, resolved in discovery.excluded
    )
    leaks = [a for a in audits if a.leaking]
    assert [a.root for a in leaks] == [external.resolve()]


# ------------------------- DoD (k) / CF-audit E1: no-git is NEVER a green skip


def test_included_destination_without_git_is_exit_2(tmp_path: Path) -> None:
    """CF-audit E1 with REAL teeth: the parent dir IS a git repo, so without
    the walk-up guard `git -C dest ls-files` would succeed against the PARENT
    tree, look clean, and yield a false-green exit 0. The guard must turn this
    into an operational exit 2 instead."""
    _git(tmp_path, "init", "-q", "-b", "main")
    motor = _make_motor(tmp_path)
    other_motor = tmp_path / "other_motor"
    _make_destination(tmp_path, "dest_nogit", other_motor, with_git=False)
    audits, _ = run_audit(motor)
    assert len(audits) == 1
    assert audits[0].error is not None
    assert "walk" in audits[0].error
    assert not audits[0].leaking
    rc = main(["--motor-root", str(motor)])
    assert rc == 2, "an unaudited included destination must never yield exit 0"


def test_leak_plus_unauditable_is_exit_2_not_1(tmp_path: Path) -> None:
    """Operational failure dominates: exit 2 even when leaks were also found."""
    _git(tmp_path, "init", "-q", "-b", "main")
    motor = _make_motor(tmp_path)
    other_motor = tmp_path / "other_motor"
    _make_destination(tmp_path, "dest_leak", other_motor, track_link=True)
    _make_destination(tmp_path, "dest_nogit", other_motor, with_git=False)
    assert main(["--motor-root", str(motor)]) == 2


# --------------------------------------------------- DoD (a): strictly read-only


def test_audit_is_read_only(tmp_path: Path) -> None:
    motor = _make_motor(tmp_path)
    other_motor = tmp_path / "other_motor"
    dest = _make_destination(tmp_path, "dest_ro", other_motor, track_collab=True)
    before_ls = _git_out(dest, "ls-files")
    before_status = _git_out(dest, "status", "--porcelain")
    main(["--motor-root", str(motor)])
    assert _git_out(dest, "ls-files") == before_ls
    assert _git_out(dest, "status", "--porcelain") == before_status


# ------------------------------------------------------- DoD (h): real CLI run


def test_cli_subprocess_real_rc(tmp_path: Path) -> None:
    motor = _make_motor(tmp_path)
    other_motor = tmp_path / "other_motor"
    _make_destination(tmp_path, "dest_link", other_motor, track_link=True)
    proc = subprocess.run(
        [sys.executable, str(GUARD_PATH), "--motor-root", str(motor)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "LEAK" in proc.stdout


# ----------------------- DoD (g): prepush wiring, WARN default / FAIL opt-in


def test_wiring_warn_default_reports_but_does_not_block(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("DESTINATION_PII_STRICT", raising=False)
    motor = _make_motor(tmp_path)
    other_motor = tmp_path / "other_motor"
    _make_destination(tmp_path, "dest_leak", other_motor, track_collab=True)
    result = run_destination_pii_check(tmp_path, motor_root=motor)
    assert result.passed is False
    assert result.is_blocking is False
    assert "LEAK" in result.output
    assert "WOT-2026-023b" in result.output


def test_wiring_strict_opt_in_blocks(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DESTINATION_PII_STRICT", "1")
    motor = _make_motor(tmp_path)
    other_motor = tmp_path / "other_motor"
    _make_destination(tmp_path, "dest_leak", other_motor, track_collab=True)
    result = run_destination_pii_check(tmp_path, motor_root=motor)
    assert result.passed is False
    assert result.is_blocking is True


def test_wiring_clean_machine_passes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DESTINATION_PII_STRICT", raising=False)
    motor = _make_motor(tmp_path)
    other_motor = tmp_path / "other_motor"
    _make_destination(tmp_path, "dest_clean", other_motor)
    result = run_destination_pii_check(tmp_path, motor_root=motor)
    assert result.passed is True
