"""Tests for the decision-commit convention (WOT-2026-040t, Pieza 3).

Pieza 1 demands that a flight hand off a commit. A flight that produces CODE
satisfies that naturally. A flight that stops (GROUP_STOP) produces a DECISION,
not code -- and until now that decision lived only in a prompt-level
``GROUP_STOP_REPORT``, i.e. a norm. So a stopped flight had nothing to hand off
and stayed in limbo (F7): exactly what happened to WOT-2026-040j, whose stop left
zero commits and let ``--session-close`` certify an unrelated stale ticket.

Pieza 3 makes the decision itself committable, so the SAME rejector accepts a
stopped flight without being weakened.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from check_handoff_committed import (
    DECISION_DIR,
    EXIT_OK,
    DecisionCommitError,
    evaluate,
    read_decision_at_sha,
    write_decision_record,
)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )


def init_git_repo(repo_path: Path) -> None:
    repo_path.mkdir(parents=True, exist_ok=True)
    _git(repo_path, "init")
    _git(repo_path, "config", "user.email", "test@example.com")
    _git(repo_path, "config", "user.name", "Test User")
    (repo_path / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    _git(repo_path, "add", ".")
    _git(repo_path, "commit", "-m", "Initial commit")


def _head(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def test_stopped_flight_without_a_decision_commit_is_rejected(tmp_path: Path) -> None:
    """THE 040j shape: a flight stops, writes nothing, hands off nothing.

    The rejector must not accept "I stopped, so there is nothing to commit" --
    that is precisely the limbo state (F7).
    """
    repo = tmp_path / "repo"
    init_git_repo(repo)
    # A stopped flight that left an unstaged report lying around.
    (repo / "GROUP_STOP_REPORT.json").write_text("{}", encoding="utf-8")

    code, lines = evaluate(repo)

    assert code != EXIT_OK
    assert "GROUP_STOP_REPORT.json" in "\n".join(lines)


def test_write_decision_record_produces_a_committable_file(tmp_path: Path) -> None:
    """The decision becomes a real file under the conventional directory."""
    repo = tmp_path / "repo"
    init_git_repo(repo)

    path = write_decision_record(
        repo,
        ticket="WOT-2026-040j",
        state="GROUP_STOP",
        cause_type="CONTRACT_GAP",
        summary="premisa falsa: el probe no reproduce la ruta productiva",
        evidence=["python -c 'pass' -> exit 1 en PowerShell, exit 0 en Git Bash"],
    )

    assert path.exists()
    assert DECISION_DIR in path.parts
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["ticket"] == "WOT-2026-040j"
    assert record["state"] == "GROUP_STOP"
    assert record["cause_type"] == "CONTRACT_GAP"
    assert record["evidence"]


def test_decision_commit_makes_a_stopped_flight_pass_the_rejector(
    tmp_path: Path,
) -> None:
    """The closing of the loop: decision -> commit -> rejector accepts.

    Crucially this passes through the SAME rejector, with no special case for
    stopped flights. The flight is accepted because it now HAS a commit, not
    because the barrier was softened for it.
    """
    repo = tmp_path / "repo"
    init_git_repo(repo)

    write_decision_record(
        repo,
        ticket="WOT-2026-040j",
        state="GROUP_STOP",
        cause_type="CONTRACT_GAP",
        summary="premisa falsa",
        evidence=["probe refutado"],
    )
    # Before committing, the tree is dirty -> still rejected.
    assert evaluate(repo)[0] != EXIT_OK

    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "WOT-2026-040j: GROUP_STOP decision record")

    code, lines = evaluate(repo)
    assert code == EXIT_OK, "\n".join(lines)


def test_decision_is_readable_from_the_sha_not_the_tree(tmp_path: Path) -> None:
    """Pieza 2 applied to Pieza 3: the decision is audited at the SHA.

    A decision that could be edited after the fact would be no better evidence
    than the working tree it replaced.
    """
    repo = tmp_path / "repo"
    init_git_repo(repo)
    path = write_decision_record(
        repo,
        ticket="WOT-2026-040j",
        state="GROUP_STOP",
        cause_type="TEST_FAIL",
        summary="original",
        evidence=["e1"],
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "WOT-2026-040j: decision")
    sha = _head(repo)

    # Tamper with the decision in the working tree AFTER committing it.
    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["summary"] = "rewritten after the fact"
    path.write_text(json.dumps(tampered), encoding="utf-8")

    record = read_decision_at_sha(repo, sha, "WOT-2026-040j")

    assert record["summary"] == "original"
    assert record["cause_type"] == "TEST_FAIL"


def test_decision_absent_at_sha_is_not_auditable(tmp_path: Path) -> None:
    """No decision at that SHA -> NOT AUDITABLE, never an implicit approval."""
    repo = tmp_path / "repo"
    init_git_repo(repo)
    sha = _head(repo)

    with pytest.raises(Exception) as excinfo:
        read_decision_at_sha(repo, sha, "WOT-2026-040j")

    assert "NO AUDITABLE" in str(excinfo.value)


def test_decision_requires_evidence(tmp_path: Path) -> None:
    """A stop with no evidence is a claim, not a record (CEM).

    Without this, the convention would let a flight satisfy the rejector with an
    empty decision -- turning a real barrier into a rubber stamp.
    """
    repo = tmp_path / "repo"
    init_git_repo(repo)

    with pytest.raises(DecisionCommitError):
        write_decision_record(
            repo,
            ticket="WOT-2026-040j",
            state="GROUP_STOP",
            cause_type="CONTRACT_GAP",
            summary="me pare porque si",
            evidence=[],
        )


def test_decision_rejects_an_unknown_cause_type(tmp_path: Path) -> None:
    """cause_type is a closed vocabulary (shared with GROUP_STOP_REPORT)."""
    repo = tmp_path / "repo"
    init_git_repo(repo)

    with pytest.raises(DecisionCommitError):
        write_decision_record(
            repo,
            ticket="WOT-2026-040j",
            state="GROUP_STOP",
            cause_type="PORQUE_ME_APETECE",
            summary="s",
            evidence=["e"],
        )
