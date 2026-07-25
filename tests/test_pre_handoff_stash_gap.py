# WOT-2026-040x: the handoff guard must refuse a pending stash.
#
# WOT-2026-040t Pieza 1 rejects a stash at CLOSEOUT. The 2026-07-25 incident
# happened hours earlier, inside the audit window: a flight stashed while the
# orchestrator audited the same tree, and three measurements of the same tree
# disagreed. Closeout was the wrong moment to find out.
#
# Scope, measured before writing a line of fix (this is the narrow half of what
# the 040x ticket originally claimed):
#   * dirty tree at handoff is ALREADY covered -- get_changed_files() for the
#     destination, and bus.evidence.motor_uncommitted_productive() for the motor
#     via agent_controller.py:3977 on the --mark-ready path. Not a gap.
#   * a pending STASH is covered by NOBODY at handoff time. `grep -c stash`
#     returns 0 in both pre_handoff_guard.py and bus/evidence.py.
# A stash is repo-global: it crosses worktrees, so a flight's stash is visible
# to -- and silently mutates -- the tree an auditor is reading.

from __future__ import annotations

import subprocess
from pathlib import Path

from scripts import pre_handoff_guard
from scripts.pre_handoff_guard import apply_stash_rule

from tests.test_pre_handoff_guard import init_git_repo


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, cwd=cwd, timeout=30
    )


def _stash_something(repo: Path) -> None:
    """Leave exactly one entry in `git stash list`."""
    (repo / "README.md").write_text("# Test Repo\nlocal edit\n")
    _git(["stash", "push", "-m", "wip"], repo)


def test_pending_stash_blocks_handoff(tmp_path: Path) -> None:
    """A stash entry must make the handoff guard refuse.

    Fails before the fix: run_guard never consults `git stash list`, so a tree
    that looks pristine to `git status` while holding stashed work reads as
    ready-to-audit.
    """
    motor = tmp_path / "motor"
    init_git_repo(motor)
    _stash_something(motor)

    # Precondition: the tree is CLEAN by status -- that is the whole trap.
    assert _git(["status", "--porcelain"], motor).stdout.strip() == ""
    assert _git(["stash", "list"], motor).stdout.strip() != ""

    result = pre_handoff_guard.run_guard(motor, "WOT-2026-040x", motor_root=motor)

    assert result["pending_stash"], result
    assert result["valid"] is False, result

    # ``valid is False`` alone proves nothing here: this fixture has no M3
    # checkpoint either, so the guard would refuse anyway and the assertion
    # would pass with the stash rule deleted (measured -- mutation M1 survived
    # the first version of this test). Pin the CAUSE, not just the verdict.
    clean = tmp_path / "clean"
    init_git_repo(clean)
    baseline = pre_handoff_guard.run_guard(clean, "WOT-2026-040x", motor_root=clean)
    assert baseline["pending_stash"] == [], baseline
    assert result["pending_stash"] != baseline["pending_stash"], (
        "the stash is the only difference between these two repos; if the guard "
        "reports the same thing for both, it is not reading the stash"
    )


def test_stash_alone_flips_valid_when_nothing_else_blocks(tmp_path: Path) -> None:
    """The stash must be sufficient on its own to refuse the handoff.

    Isolates the variable by DIFFERENCE rather than by absolute: two repos
    identical but for one stash entry. A bare tmp_path fixture cannot reach
    ``valid is True`` (the guard also wants a canonical suite run and a delivery
    hygiene module that do not exist here), so the assertion is that the stash
    is the thing that changed the refusal reason.

    Without this, ``valid is False`` in the test above is satisfied by the
    missing checkpoint and the stash rule could be deleted unnoticed -- measured:
    mutation M1 survived the first version of this file.
    """
    ticket = "WOT-2026-040x"

    def _repo_with_checkpoint(name: str) -> Path:
        repo = tmp_path / name
        init_git_repo(repo)
        _git(["tag", f"checkpoint/review-{ticket}"], repo)
        return repo

    clean = _repo_with_checkpoint("clean")
    stashed = _repo_with_checkpoint("stashed")
    _stash_something(stashed)

    clean_result = pre_handoff_guard.run_guard(clean, ticket, motor_root=clean)
    stashed_result = pre_handoff_guard.run_guard(stashed, ticket, motor_root=stashed)

    # The stash is the ONLY difference between the two repos, so it must be the
    # only difference in what the guard reports about the stash.
    assert clean_result["pending_stash"] == [], clean_result
    assert stashed_result["pending_stash"], stashed_result
    assert stashed_result["valid"] is False, stashed_result


def test_stash_rule_blocks_on_its_own() -> None:
    """The rule must REFUSE, not merely observe (WOT-2026-040x).

    Tests ``apply_stash_rule`` directly rather than through ``run_guard``. Via
    run_guard this is unprovable: a tmp_path fixture is already ``valid=False``
    for unrelated reasons, so an assertion on ``valid`` holds whether the rule
    fires or not. Measured, not assumed -- a mutant that reported the stash
    without setting ``valid=False`` survived two earlier versions of this test.
    Here ``valid`` starts True, so only this rule can flip it.
    """
    blocked = apply_stash_rule({"valid": True, "pending_stash": []}, ["stash@{0}: wip"])
    assert blocked["valid"] is False
    assert blocked["pending_stash"] == ["stash@{0}: wip"]

    untouched = apply_stash_rule({"valid": True, "pending_stash": []}, [])
    assert untouched["valid"] is True
    assert untouched["pending_stash"] == []


def test_clean_repo_without_stash_is_not_blocked_by_this_rule(
    tmp_path: Path,
) -> None:
    """Anti-false-positive: no stash, no stash-based refusal.

    The guard blocks this fixture for an unrelated reason (no M3 checkpoint),
    so this asserts on the stash flag specifically rather than on ``valid``:
    a rule that fires when its own condition is absent is worse than no rule.
    """
    motor = tmp_path / "motor"
    init_git_repo(motor)

    assert _git(["stash", "list"], motor).stdout.strip() == ""

    result = pre_handoff_guard.run_guard(motor, "WOT-2026-040x", motor_root=motor)

    assert result["pending_stash"] == [], result
