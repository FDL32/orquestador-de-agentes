"""Barrier tests for WOT-2026-040w: `_step_write_decision_records` must ask
about THE TICKET, not about the repo.

The wiring landed in 10c7871 but was INERT. `_has_productive_commits` has no
`ticket_id` parameter at all (its signature is `(project_root, motor_root,
window_start)`), so the guard asked "does this repo have any commit?" instead
of "does THIS ticket have a commit?". Called with `window_start=None` it runs
`git log --oneline` over the entire history, which is True in any repo with a
single commit -- so the `continue` always fired and `write_decision_record`
was never reached.

Measured before the fix (productive path, real repos):
    _has_productive_commits(destino, motor, None) -> True
    motor: 1437 commits, destino: 1357 commits (full history, no window)

Three defects, three tests:
  (a) PER-TICKET: a repo whose history has commits for OTHER tickets must
      still produce a decision record for the ticket that has none. This is
      the one that made the feature inert.
  (b) SKIP WHEN LANDED: a ticket that DOES have a commit naming it must NOT
      get a decision record. Without this, (a) passes trivially by always
      writing.
  (c) FAIL-CLOSED ON UNRESOLVED MOTOR: `mr is None` left `has_commits=False`,
      writing the record without checking anything -- failing OPEN in the
      opposite direction.

No `subprocess` mocking: real git repos, per the precedent of
test_session_closeout_loop_targets.py -- a mock would only prove the mock.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


_MOTOR_ROOT = Path(__file__).resolve().parents[2]
if str(_MOTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_MOTOR_ROOT))

from scripts import session_closeout  # noqa: E402


def _init_git_repo(repo: Path) -> None:
    """Minimal git repo with its own .git (WOT-2026-020r: no walk-up)."""
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@e.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "T"], cwd=repo, check=True, capture_output=True
    )
    (repo / "README.md").write_text("# repo")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True
    )


def _commit(repo: Path, rel: str, message: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")
    subprocess.run(["git", "add", "--", rel], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", message], cwd=repo, check=True, capture_output=True
    )


@pytest.fixture
def repos(tmp_path: Path) -> tuple[Path, Path]:
    """A destino and a motor, each a real git repo with its own history."""
    destino = tmp_path / "destino"
    motor = tmp_path / "motor"
    _init_git_repo(destino)
    _init_git_repo(motor)
    return destino, motor


def _run_step(destino: Path, motor: Path, tickets: list[str]) -> None:
    """Invoke the step with the motor resolved, as production does.

    `session_closeout` imports `resolve_motor_root` INSIDE the function, so the
    patch target is the source module (`runtime.motor_link`), not an attribute
    of `session_closeout` -- patching the latter would silently patch nothing.
    """
    import runtime.motor_link

    with patch.object(runtime.motor_link, "resolve_motor_root", return_value=motor):
        session_closeout._step_write_decision_records(destino, tickets)


def _record(destino: Path, ticket: str) -> Path:
    return destino / ".flight-decision" / f"{ticket}.json"


def test_decision_record_written_when_this_ticket_has_no_commit(
    repos: tuple[Path, Path],
) -> None:
    """(a) Other tickets' commits must not suppress THIS ticket's record.

    THE defect that made WOT-2026-040w inert. The motor history carries a
    commit for a DIFFERENT ticket, so a repo-wide query returns True and the
    `continue` fires. Asking per-ticket keeps the branch reachable.

    Mutation: reverting the guard to the repo-wide query makes this fail --
    the record is never written.
    """
    destino, motor = repos
    _commit(motor, "other.py", "WOT-2026-099z: an unrelated landed ticket")

    _run_step(destino, motor, ["WOT-2026-040w"])

    assert _record(destino, "WOT-2026-040w").exists(), (
        "no decision record for a ticket without commits; the guard asked "
        "about the repo instead of about the ticket"
    )


def test_no_decision_record_when_this_ticket_landed(
    repos: tuple[Path, Path],
) -> None:
    """(b) NEGATIVE CONTROL: a landed ticket gets no record.

    Without this, test (a) would pass by writing unconditionally, which is a
    different bug with the same green.
    """
    destino, motor = repos
    _commit(motor, "landed.py", "WOT-2026-040w: the real productive commit")

    _run_step(destino, motor, ["WOT-2026-040w"])

    assert not _record(destino, "WOT-2026-040w").exists(), (
        "decision record written for a ticket that HAS a commit naming it"
    )


def test_both_repos_are_searched_for_the_ticket_commit(
    repos: tuple[Path, Path],
) -> None:
    """(b') The commit may land in destino instead of motor; both count."""
    destino, motor = repos
    _commit(destino, "landed.py", "WOT-2026-040w: landed in destino")

    _run_step(destino, motor, ["WOT-2026-040w"])

    assert not _record(destino, "WOT-2026-040w").exists(), (
        "only the motor was searched; a commit in destino must count too"
    )


def test_unresolved_motor_does_not_write_blindly(repos: tuple[Path, Path]) -> None:
    """(c) `mr is None` must not write without checking.

    The original left `has_commits=False` when the motor did not resolve, so
    an unresolvable motor produced records for tickets that had landed --
    failing OPEN. With destino searched directly, the landed ticket is still
    seen.
    """
    destino, _motor = repos
    _commit(destino, "landed.py", "WOT-2026-040w: landed, motor unresolvable")

    import runtime.motor_link

    with patch.object(runtime.motor_link, "resolve_motor_root", return_value=None):
        session_closeout._step_write_decision_records(destino, ["WOT-2026-040w"])

    assert not _record(destino, "WOT-2026-040w").exists(), (
        "wrote a decision record blindly because the motor did not resolve"
    )


def test_mixed_flight_writes_only_for_the_stopped_ticket(
    repos: tuple[Path, Path],
) -> None:
    """A flight where some tickets landed and one did not: exactly one record.

    This is the G1 shape (three tickets, mixed outcomes) and the case the
    repo-wide query got wrong in the direction that matters.
    """
    destino, motor = repos
    _commit(motor, "a.py", "WOT-2026-048b: landed")
    _commit(motor, "b.py", "WOT-2026-040e: landed")

    _run_step(destino, motor, ["WOT-2026-048b", "WOT-2026-040e", "WOT-2026-040w"])

    assert not _record(destino, "WOT-2026-048b").exists()
    assert not _record(destino, "WOT-2026-040e").exists()
    assert _record(destino, "WOT-2026-040w").exists(), (
        "the one stopped ticket of the flight got no decision record"
    )
