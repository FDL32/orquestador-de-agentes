from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts import check_motor_pristine


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _init_repo(repo: Path) -> None:
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("initial\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")


def test_check_reports_dirty_worktree_without_strict_failure(tmp_path: Path) -> None:
    repo = tmp_path / "motor"
    _init_repo(repo)
    snapshot = tmp_path / "before.json"
    report = tmp_path / "after.json"

    assert (
        check_motor_pristine.main(
            ["--motor-root", str(repo), "--snapshot", "--out", str(snapshot)]
        )
        == 0
    )
    (repo / "README.md").write_text("changed\n", encoding="utf-8")

    rc = check_motor_pristine.main(
        [
            "--motor-root",
            str(repo),
            "--check",
            "--snapshot-file",
            str(snapshot),
            "--report",
            str(report),
        ]
    )

    data = json.loads(report.read_text(encoding="utf-8"))
    assert rc == 0
    assert data["event"] == "MOTOR_DIRTY_DETECTED"
    assert data["motor_head_changed"] is False
    assert data["motor_status_new"]
    assert data["motor_status_after"]
    assert data["motor_diff_stat_after"]


def test_pre_existing_dirty_baseline_without_new_changes_is_ok(tmp_path: Path) -> None:
    repo = tmp_path / "motor"
    _init_repo(repo)
    snapshot = tmp_path / "before.json"
    report = tmp_path / "after.json"

    (repo / "README.md").write_text("already dirty\n", encoding="utf-8")
    assert (
        check_motor_pristine.main(
            ["--motor-root", str(repo), "--snapshot", "--out", str(snapshot)]
        )
        == 0
    )

    rc = check_motor_pristine.main(
        [
            "--motor-root",
            str(repo),
            "--check",
            "--snapshot-file",
            str(snapshot),
            "--report",
            str(report),
            "--strict",
        ]
    )

    data = json.loads(report.read_text(encoding="utf-8"))
    assert rc == 0
    assert data["event"] == "MOTOR_PRISTINE_OK"
    assert data["pre_existing_dirty"]
    assert data["motor_status_new"] == []
    assert data["motor_dirty_after"] is True


def test_check_strict_fails_when_head_changes(tmp_path: Path) -> None:
    repo = tmp_path / "motor"
    _init_repo(repo)
    snapshot = tmp_path / "before.json"
    report = tmp_path / "after.json"

    assert (
        check_motor_pristine.main(
            ["--motor-root", str(repo), "--snapshot", "--out", str(snapshot)]
        )
        == 0
    )
    (repo / "new.txt").write_text("new\n", encoding="utf-8")
    _git(repo, "add", "new.txt")
    _git(repo, "commit", "-m", "change head")

    rc = check_motor_pristine.main(
        [
            "--motor-root",
            str(repo),
            "--check",
            "--snapshot-file",
            str(snapshot),
            "--report",
            str(report),
            "--strict",
        ]
    )

    data = json.loads(report.read_text(encoding="utf-8"))
    assert rc == 1
    assert data["event"] == "MOTOR_DIRTY_DETECTED"
    assert data["motor_head_changed"] is True
    assert len(data["motor_head_before"]) == 40
    assert len(data["motor_head_after"]) == 40


def test_record_denied_appends_attempt_with_head_evidence(tmp_path: Path) -> None:
    repo = tmp_path / "motor"
    _init_repo(repo)
    report = tmp_path / "denied.json"

    rc = check_motor_pristine.main(
        [
            "--motor-root",
            str(repo),
            "--record-denied",
            "--report",
            str(report),
            "--operation",
            "write",
            "--path",
            str(repo / "blocked.txt"),
            "--reason",
            "Permission denied",
            "--ticket",
            "CTL-2026-003a",
        ]
    )

    data = json.loads(report.read_text(encoding="utf-8"))
    attempt = data["denied_attempts"][0]
    assert rc == 0
    assert data["event"] == "MOTOR_WRITE_DENIED"
    assert attempt["ticket"] == "CTL-2026-003a"
    assert attempt["operation"] == "write"
    assert len(attempt["motor_head"]) == 40
