"""Tests for closeout commit resolution from the accredited M3 checkpoint.

WOT-2026-068q: the closeout gate used to validate the literal HEAD commit
message. A later, legitimate commit (for example a memory promotion from
another session) buried the ticket's own commit, and the gate aborted with
"Commit message does not reference any ticket ID" even though the ticket's
commit was reachable and had already been accredited by
checkpoint/review-<ticket> (the M3 tag).

These tests use REAL git repos in tmp_path (git subprocess is NOT mocked),
imitating the init_git_repo pattern from tests/test_pre_handoff_guard.py.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest


TICKET = "WOT-2026-900a"
FOREIGN_SUBJECT = "memory: promote another sessions observation"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    """Run a git command in repo, failing loudly on error."""
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Initialize a real git repo with an initial commit."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _git(repo_path, "init")
    _git(repo_path, "config", "user.email", "test@example.com")
    _git(repo_path, "config", "user.name", "Test User")
    (repo_path / "README.md").write_text("# Test Repo", encoding="utf-8")
    _git(repo_path, "add", "README.md")
    _git(repo_path, "commit", "-m", "Initial commit")
    return repo_path


def _commit(repo: Path, filename: str, message: str) -> str:
    """Create a commit touching a fresh file and return its SHA."""
    (repo / filename).write_text(f"{message}\n", encoding="utf-8")
    _git(repo, "add", filename)
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _tag(repo: Path, tag_name: str, sha: str = "HEAD") -> None:
    """Create an annotated tag at sha (defaults to HEAD)."""
    _git(repo, "tag", "-a", tag_name, "-m", "Test checkpoint", sha)


def _buried_ticket_repo(repo: Path) -> str:
    """Ticket commit + M3 tag, then a foreign commit on top of HEAD.

    Reproduces the 2026-09-13 scenario: the delivery commit is accredited by
    checkpoint/review-<ticket> but is no longer HEAD.
    """
    ticket_sha = _commit(repo, "delivery.txt", f"{TICKET}: productive change")
    _tag(repo, f"checkpoint/review-{TICKET}", ticket_sha)
    _commit(repo, "foreign.txt", FOREIGN_SUBJECT)
    return ticket_sha


class TestCloseoutCommitResolution:
    """Unit-level behaviour of _check_last_commit()."""

    def test_literal_head_commit_still_accepted(self, repo: Path) -> None:
        """Parity: a HEAD that itself cites the ticket keeps working."""
        from agent_controller import _check_last_commit

        _commit(repo, "delivery.txt", f"{TICKET}: productive change")

        valid, reason = _check_last_commit(repo, TICKET)

        assert valid is True, reason
        assert reason == ""

    def test_accredited_checkpoint_commit_buried_under_foreign_head_is_accepted(
        self, repo: Path
    ) -> None:
        """DoD (a): a ticket commit accredited by M3 is accepted even when a
        foreign, legitimate commit is HEAD. RED before the fix (the old gate
        only read HEAD and returned "does not reference any ticket ID")."""
        from agent_controller import _check_last_commit

        _buried_ticket_repo(repo)

        valid, reason = _check_last_commit(repo, TICKET)

        assert valid is True, reason
        assert reason == ""

    def test_no_commit_citing_ticket_still_fails(self, repo: Path) -> None:
        """CONTROL NEGATIVO (DoD c): with no ticket commit and no accredited
        checkpoint, the gate still rejects. Locks the anti-history-scan rule."""
        from agent_controller import _check_last_commit

        _commit(repo, "churn.txt", "chore: unrelated work")

        valid, reason = _check_last_commit(repo, TICKET)

        assert valid is False
        assert "does not reference any ticket ID" in reason

    def test_checkpoint_commit_not_ancestor_of_head_fails_distinctly(
        self, repo: Path
    ) -> None:
        """DoD (d): the message must distinguish "no commit cites the ticket"
        from "the ticket's commit exists but is not HEAD / reachable". A tag on
        an unmerged side branch names the existing commit instead of asserting
        an absence that was never measured."""
        from agent_controller import _check_last_commit

        base_branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        _git(repo, "checkout", "-b", "ticket-side")
        ticket_sha = _commit(repo, "delivery.txt", f"{TICKET}: productive change")
        _tag(repo, f"checkpoint/review-{TICKET}", ticket_sha)
        _git(repo, "checkout", base_branch)
        _commit(repo, "foreign.txt", FOREIGN_SUBJECT)

        valid, reason = _check_last_commit(repo, TICKET)

        assert valid is False
        assert ticket_sha[:8] in reason, reason
        assert "not an ancestor of HEAD" in reason, reason
        assert "does not reference any ticket ID" not in reason, reason

    def test_rogue_checkpoint_subject_without_ticket_is_rejected(
        self, repo: Path
    ) -> None:
        """CONTROL NEGATIVO: a checkpoint tag whose own subject does not cite
        the ticket must not whitelist the commit. The tag is authoritative only
        when its subject cites the ticket, exactly as resolve_motor_checkpoint_files
        already requires."""
        from agent_controller import _check_last_commit

        # Tag points at the bare initial commit (ancestor of HEAD) whose
        # subject is "Initial commit".
        _tag(repo, f"checkpoint/review-{TICKET}", "HEAD")
        _commit(repo, "foreign.txt", FOREIGN_SUBJECT)

        valid, reason = _check_last_commit(repo, TICKET)

        assert valid is False
        assert "is not a valid closeout commit" in reason, reason


@pytest.fixture
def manager_files(tmp_path: Path) -> dict:
    """Collaboration projections for driving _handle_manager_approve."""
    collab = tmp_path / ".agent" / "collaboration"
    collab.mkdir(parents=True, exist_ok=True)

    work_plan = collab / "work_plan.md"
    work_plan.write_text(
        f"# Plan de Trabajo: {TICKET}\n\n"
        "## Metadata\n"
        f"- **ID:** {TICKET}\n"
        "- **Estado:** APPROVED\n"
        "- **deliverable_type:** code\n"
        "- **delivery_authority:** repo_motor\n",
        encoding="utf-8",
    )

    exec_log = collab / "execution_log.md"
    exec_log.write_text(
        f"# Execution Log\n\n## {TICKET}\n**Estado:** READY_FOR_REVIEW\n",
        encoding="utf-8",
    )

    turn = collab / "TURN.md"
    turn.write_text("# TURNO ACTUAL\n\n## Agente Activo\n", encoding="utf-8")

    state = collab / "STATE.md"
    state.write_text(
        "# STATE\n\n- **Estado actual:** READY_FOR_REVIEW\n", encoding="utf-8"
    )

    return {
        "work_plan": work_plan,
        "exec_log": exec_log,
        "turn": turn,
        "state": state,
        "collab_dir": collab,
    }


def _drive_manager_approve(repo: Path, files: dict, bus, force_mode: bool) -> int:
    """Run _handle_manager_approve with the real _check_last_commit against a
    real git repo used as the closeout commit root."""
    from agent_controller import _handle_manager_approve

    with (
        patch("agent_controller.event_bus", bus),
        patch("agent_controller.BUS_AVAILABLE", True),
        patch("agent_controller.WORK_PLAN", files["work_plan"]),
        patch("agent_controller.EXEC_LOG", files["exec_log"]),
        patch("agent_controller.TURN_FILE", files["turn"]),
        patch("agent_controller.STATE_FILE", files["state"]),
        patch("agent_controller.AGENT_DIR", files["collab_dir"].parent),
        patch("agent_controller._resolve_closeout_commit_root", return_value=repo),
    ):
        return _handle_manager_approve(TICKET, json_output=False, force_mode=force_mode)


class TestManagerApproveBuriedCommit:
    """Integration: --manager-approve WITHOUT --force over a real git repo."""

    def test_manager_approve_passes_with_buried_accredited_commit(
        self, repo: Path, manager_files: dict, tmp_path: Path
    ) -> None:
        """DoD (b) fixture: foreign HEAD + M3 tag on the ticket commit ->
        --manager-approve without --force returns 0. RED before the fix."""
        from bus.event_bus import EventBus

        bus = EventBus(tmp_path / "runtime" / "events")
        _buried_ticket_repo(repo)

        result = _drive_manager_approve(repo, manager_files, bus, force_mode=False)

        assert result == 0

    def test_manager_approve_without_force_blocks_when_no_ticket_commit(
        self, repo: Path, manager_files: dict, tmp_path: Path
    ) -> None:
        """CONTROL NEGATIVO (DoD c): no ticket commit anywhere in history ->
        blocked unless --force."""
        from bus.event_bus import EventBus

        bus = EventBus(tmp_path / "runtime" / "events")
        _commit(repo, "churn.txt", "chore: unrelated work")

        result = _drive_manager_approve(repo, manager_files, bus, force_mode=False)

        assert result == 1

    def test_force_mode_still_bypasses_the_same_commit_gate(
        self, repo: Path, manager_files: dict, tmp_path: Path
    ) -> None:
        """CONTROL NEGATIVO (DoD c): --force still bypasses exactly this block.
        Same repo + same projections as the blocked case; only force_mode
        differs, so a 0 here proves the escape hatch survived the fix."""
        from bus.event_bus import EventBus

        bus = EventBus(tmp_path / "runtime_force" / "events")
        _commit(repo, "churn.txt", "chore: unrelated work")

        result = _drive_manager_approve(repo, manager_files, bus, force_mode=True)

        assert result == 0
