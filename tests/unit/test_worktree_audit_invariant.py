"""Tests for the pre/post audit invariant (WOT-2026-040t, Pieza 4).

Piezas 1-3 make the HANDOFF immutable. They do not close the window in which the
orchestrator itself runs a ~6-minute suite over the live working tree
(``run_pytest_safe`` launches pytest with ``cwd=PROJECT_ROOT``). During that
window a concurrent flight can still stash, reset or checkout underneath the
measurement -- which is exactly what produced the 8-failed contaminated suite on
2026-07-25.

REDESIGNED per Codex (adjudicated in the 1->9->2 loop): this is NOT a lock. A
lock file only works if every actor honours it, and an actor that has never
heard of it writes anyway -- decorative. Instead the invariant DETECTS the
mutation after the fact and INVALIDATES the measurement. It promises detection,
which it can actually deliver, rather than exclusion, which it cannot.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from worktree_audit_invariant import (
    AuditInvariantViolationError,
    capture_state,
    verify_unchanged,
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


def test_untouched_tree_keeps_the_measurement_valid(tmp_path: Path) -> None:
    """No mutation during the window -> the measurement stands."""
    repo = tmp_path / "repo"
    init_git_repo(repo)

    pre = capture_state(repo)
    # ... a suite runs here, changing nothing ...
    verify_unchanged(repo, pre)  # must not raise


def test_a_file_modified_during_the_window_invalidates(tmp_path: Path) -> None:
    """THE core case: the tree moved under the measurement."""
    repo = tmp_path / "repo"
    init_git_repo(repo)
    pre = capture_state(repo)

    (repo / "README.md").write_text("# mutated mid-suite\n", encoding="utf-8")

    try:
        verify_unchanged(repo, pre)
    except AuditInvariantViolationError as exc:
        assert "INVALIDADA" in str(exc)
        assert "status" in str(exc).lower()
    else:
        raise AssertionError("a mid-window modification must invalidate")


def test_a_stash_during_the_window_invalidates(tmp_path: Path) -> None:
    """THE 027h shape: the flight stashes while the orchestrator measures.

    Note the tree is dirty BEFORE and clean AFTER, so a naive "is it clean now?"
    check would report improvement. Only comparing against the pre-state catches
    that the ground moved.
    """
    repo = tmp_path / "repo"
    init_git_repo(repo)
    (repo / "work.py").write_text("w = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    pre = capture_state(repo)

    _git(repo, "stash", "push", "-m", "flight-verification")

    try:
        verify_unchanged(repo, pre)
    except AuditInvariantViolationError as exc:
        assert "INVALIDADA" in str(exc)
    else:
        raise AssertionError("a mid-window stash must invalidate")


def test_a_commit_during_the_window_invalidates(tmp_path: Path) -> None:
    """HEAD moving mid-measurement invalidates: the result names another commit."""
    repo = tmp_path / "repo"
    init_git_repo(repo)
    pre = capture_state(repo)

    (repo / "new.py").write_text("n = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "landed mid-suite")

    try:
        verify_unchanged(repo, pre)
    except AuditInvariantViolationError as exc:
        assert "HEAD" in str(exc)
    else:
        raise AssertionError("a mid-window commit must invalidate")


def test_stash_that_is_pushed_and_popped_still_invalidates(tmp_path: Path) -> None:
    """The nastiest shape: mutate and restore, so pre and post LOOK identical.

    A flight that stashes and pops back inside the window leaves HEAD, status
    and the stash list exactly as they were -- yet the suite ran against a tree
    that was, for part of the run, missing its work. That is precisely the
    2026-07-25 contaminated run.

    Recording HEAD's reflog length is what makes this detectable; comparing the
    stash LIST alone would silently pass. The stash's own reflog is no help
    either -- measured: ``git stash pop`` deletes ``refs/stash`` when it pops the
    last entry, taking that reflog with it. HEAD's reflog keeps the
    ``reset: moving to HEAD`` entries that stash writes.
    """
    repo = tmp_path / "repo"
    init_git_repo(repo)
    (repo / "work.py").write_text("w = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    pre = capture_state(repo)

    _git(repo, "stash", "push", "-m", "transient")
    _git(repo, "stash", "pop")

    try:
        verify_unchanged(repo, pre)
    except AuditInvariantViolationError as exc:
        assert "INVALIDADA" in str(exc)
    else:
        raise AssertionError("a push+pop inside the window must still invalidate")


def test_documented_blind_spots_are_real_and_stay_documented(tmp_path: Path) -> None:
    """PIN the measured limits of this mechanism (WOT-2026-040t, review finding).

    An adversarial audit found two mutations the snapshot cannot see. Both are
    real -- verified byte-exact here, not reasoned about. This test exists so the
    limit is a CHECKED property rather than a docstring nobody re-verifies: if
    someone later widens detection, this test fails and forces the docstring to
    be updated with it.

    A barrier believed to see more than it does is worse than a narrow one.
    """
    repo = tmp_path / "repo"
    init_git_repo(repo)
    target = repo / "f.py"
    target.write_bytes(b"v1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "add f")

    # Blind spot 1: transient edit reverted to the IDENTICAL bytes. No git
    # command runs, so nothing in the snapshot moves.
    original = target.read_bytes()
    pre = capture_state(repo)
    target.write_bytes(b"MUTATED MID-SUITE\n")
    target.write_bytes(original)
    verify_unchanged(repo, pre)  # documented as UNDETECTED

    # Blind spot 2: dirty -> differently-dirty. porcelain prints the same
    # " M f.py" line for both contents.
    target.write_bytes(b"v2\n")
    pre_dirty = capture_state(repo)
    target.write_bytes(b"v3\n")
    verify_unchanged(repo, pre_dirty)  # documented as UNDETECTED

    # But the git-mediated family IS caught -- the limit is scoped, not total.
    pre_git = capture_state(repo)
    _git(repo, "stash", "push", "-m", "real-mutation")
    try:
        verify_unchanged(repo, pre_git)
    except AuditInvariantViolationError:
        pass
    else:
        raise AssertionError("a stash must still be detected")


def test_the_invariant_never_mutates_anything(tmp_path: Path) -> None:
    """It DETECTS; it does not exclude, lock, restore or clean up.

    If this ever starts changing the tree it has become concurrency control and
    the hard stop applies.
    """
    repo = tmp_path / "repo"
    init_git_repo(repo)
    (repo / "work.py").write_text("w = 1\n", encoding="utf-8")

    before = _git(repo, "status", "--porcelain").stdout
    pre = capture_state(repo)
    try:
        verify_unchanged(repo, pre)
    except AuditInvariantViolationError:  # pragma: no cover - must not happen here
        raise AssertionError("no mutation occurred; must not invalidate") from None
    after = _git(repo, "status", "--porcelain").stdout

    assert before == after
    assert not (repo / ".worktree-audit.lock").exists(), "must not create a lock"


# =============================================================================
# WOT-2026-073e (Pieza b): ignore_paths filtering with --porcelain -z
# =============================================================================


def test_b1_ignore_tracked_seal_does_not_invalidate(tmp_path: Path) -> None:
    """(b1) Repo tracking the seal (last-run.json); capture with ignore_paths,
    rewrite the seal, verify_unchanged -> no raise.
    """
    repo = tmp_path / "repo"
    init_git_repo(repo)

    seal_dir = repo / ".agent" / "runtime" / "pytest-safe"
    seal_dir.mkdir(parents=True, exist_ok=True)
    (seal_dir / "last-run.json").write_text('{"status": "finished"}', encoding="utf-8")
    _git(repo, "add", ".")
    _git(
        repo,
        "commit",
        "-m",
        "Add seal",
    )

    ignore_paths = frozenset([".agent/runtime/pytest-safe/last-run.json"])
    pre = capture_state(repo, ignore_paths=ignore_paths)
    (seal_dir / "last-run.json").write_text('{"status": "started"}', encoding="utf-8")
    verify_unchanged(repo, pre, ignore_paths=ignore_paths)  # must not raise


def test_b2_other_file_modified_still_invalidates(tmp_path: Path) -> None:
    """(b2) Same fixture but modify a file OUTSIDE ignore_paths -> raises."""
    repo = tmp_path / "repo"
    init_git_repo(repo)

    seal_dir = repo / ".agent" / "runtime" / "pytest-safe"
    seal_dir.mkdir(parents=True, exist_ok=True)
    (seal_dir / "last-run.json").write_text('{"status": "finished"}', encoding="utf-8")
    _git(repo, "add", ".")
    _git(
        repo,
        "commit",
        "-m",
        "Add seal",
    )

    ignore_paths = frozenset([".agent/runtime/pytest-safe/last-run.json"])
    pre = capture_state(repo, ignore_paths=ignore_paths)
    (repo / "other.py").write_text("changed", encoding="utf-8")

    try:
        verify_unchanged(repo, pre, ignore_paths=ignore_paths)
    except AuditInvariantViolationError as exc:
        assert "INVALIDADA" in str(exc)
    else:
        raise AssertionError("modifying a non-ignored file must invalidate")


def test_b3_no_ignore_paths_seal_rewrite_invalidates(tmp_path: Path) -> None:
    """(b3) Without ignore_paths, rewriting the seal -> raises (default unchanged)."""
    repo = tmp_path / "repo"
    init_git_repo(repo)

    seal_dir = repo / ".agent" / "runtime" / "pytest-safe"
    seal_dir.mkdir(parents=True, exist_ok=True)
    (seal_dir / "last-run.json").write_text('{"status": "finished"}', encoding="utf-8")
    _git(repo, "add", ".")
    _git(
        repo,
        "commit",
        "-m",
        "Add seal",
    )

    pre = capture_state(repo)  # no ignore_paths
    (seal_dir / "last-run.json").write_text('{"status": "started"}', encoding="utf-8")

    try:
        verify_unchanged(repo, pre)  # must raise
    except AuditInvariantViolationError as exc:
        assert "INVALIDADA" in str(exc)
    else:
        raise AssertionError("seal rewrite without ignore_paths must invalidate")


def test_b4_space_in_filename_ignored_path(tmp_path: Path) -> None:
    """(b4) Verify -z format: a tracked file with a space in its name,
    modified INSIDE ignore_paths -> no raise. With --porcelain without -z,
    that path would arrive quoted and the text equality filter would silently fail.
    """
    repo = tmp_path / "repo"
    init_git_repo(repo)

    spaced = repo / "file with space.txt"
    spaced.write_text("original", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(
        repo,
        "commit",
        "-m",
        "Add spaced file",
    )

    ignore_paths = frozenset(["file with space.txt"])
    pre = capture_state(repo, ignore_paths=ignore_paths)
    spaced.write_text("modified", encoding="utf-8")
    verify_unchanged(repo, pre, ignore_paths=ignore_paths)  # must not raise


def test_b5_rename_from_ignored_to_outside_raises(tmp_path: Path) -> None:
    """(b5) Rename of a file INSIDE ignore_paths TO a name OUTSIDE the set ->
    raises (the rename is not masked).
    """
    repo = tmp_path / "repo"
    init_git_repo(repo)

    old_name = repo / "seal.json"
    old_name.write_text('{"status": "finished"}', encoding="utf-8")
    _git(repo, "add", "-A")
    _git(
        repo,
        "commit",
        "-m",
        "Add seal",
    )

    ignore_paths = frozenset(["seal.json"])
    pre = capture_state(repo, ignore_paths=ignore_paths)

    # Rename to a name outside ignore_paths
    old_name.rename(repo / "renamed.json")
    _git(repo, "add", "-A")

    try:
        verify_unchanged(repo, pre, ignore_paths=ignore_paths)
    except AuditInvariantViolationError as exc:
        assert "INVALIDADA" in str(exc)
    else:
        raise AssertionError("rename from ignored to outside must invalidate")


def test_b5bis_rename_from_outside_to_ignored_raises(tmp_path: Path) -> None:
    """(b5-bis) Rename of a file FROM a name OUTSIDE ignore_paths TO a name
    INSIDE the set -> raises (symmetric rule: a rename is only filtered if
    BOTH old and new paths match exactly).
    """
    repo = tmp_path / "repo"
    init_git_repo(repo)

    outside_name = repo / "other.txt"
    outside_name.write_text("content", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(
        repo,
        "commit",
        "-m",
        "Add other",
    )

    ignore_paths = frozenset(["seal.json"])
    pre = capture_state(repo, ignore_paths=ignore_paths)

    # Rename TO a name inside ignore_paths
    outside_name.rename(repo / "seal.json")
    _git(repo, "add", "-A")

    try:
        verify_unchanged(repo, pre, ignore_paths=ignore_paths)
    except AuditInvariantViolationError as exc:
        assert "INVALIDADA" in str(exc)
    else:
        raise AssertionError("rename to ignored name must invalidate")


def test_b6_both_seal_files_ignored_together(tmp_path: Path) -> None:
    """(b6) Repo tracking BOTH last-run.json AND last-run.log, both in
    ignore_paths, both rewritten at the same time -> verify_unchanged no raise.
    """
    repo = tmp_path / "repo"
    init_git_repo(repo)

    seal_dir = repo / ".agent" / "runtime" / "pytest-safe"
    seal_dir.mkdir(parents=True, exist_ok=True)
    (seal_dir / "last-run.json").write_text('{"status": "finished"}', encoding="utf-8")
    (seal_dir / "last-run.log").write_text("log line 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(
        repo,
        "commit",
        "-m",
        "Add seal files",
    )

    ignore_paths = frozenset(
        [
            ".agent/runtime/pytest-safe/last-run.json",
            ".agent/runtime/pytest-safe/last-run.log",
        ]
    )
    pre = capture_state(repo, ignore_paths=ignore_paths)
    (seal_dir / "last-run.json").write_text('{"status": "started"}', encoding="utf-8")
    (seal_dir / "last-run.log").write_text("log line 2\n", encoding="utf-8")
    verify_unchanged(repo, pre, ignore_paths=ignore_paths)  # must not raise


def test_b7_status_byte_identical_without_ignore_paths(tmp_path: Path) -> None:
    """(b7) Reconstruction: single modified entry, no ignore_paths -> the
    .status of the resulting WorktreeState is BYTE-IDENTICAL to what the
    current implementation with --porcelain (without -z) produces for the
    same case.
    """
    repo = tmp_path / "repo"
    init_git_repo(repo)

    # Modify a file
    (repo / "test.py").write_text("modified", encoding="utf-8")

    # Capture with -z and no ignore_paths
    state_z = capture_state(repo, ignore_paths=frozenset())

    # Capture with plain --porcelain (current implementation)
    plain_output = _git(repo, "status", "--porcelain").stdout

    assert state_z.status == plain_output, (
        f"-z reconstruction must be byte-identical to plain --porcelain "
        f"when ignore_paths is empty and there are no spaces/renames.\n"
        f"-z status: {state_z.status!r}\n"
        f"plain status: {plain_output!r}"
    )


def test_b8_error_message_counts_entries_correctly(tmp_path: Path) -> None:
    """(b8) verify_unchanged with an entry OUTSIDE ignore_paths that changes ->
    the error message (``status --porcelain cambio (N -> M entradas)``) counts
    entries correctly on the reconstructed status.
    """
    repo = tmp_path / "repo"
    init_git_repo(repo)

    (repo / "other.py").write_text("original", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(
        repo,
        "commit",
        "-m",
        "Add other",
    )

    ignore_paths = frozenset(["seal.json"])
    pre = capture_state(repo, ignore_paths=ignore_paths)

    # Modify a file OUTSIDE ignore_paths
    (repo / "other.py").write_text("modified", encoding="utf-8")

    try:
        verify_unchanged(repo, pre, ignore_paths=ignore_paths)
    except AuditInvariantViolationError as exc:
        error_str = str(exc)
        assert "status --porcelain cambio (0 -> 1 entrada(s))" in error_str, error_str
    else:
        raise AssertionError(
            "changing a non-ignored file must raise with correct message"
        )


def _commit_file(repo: Path, name: str, content: str) -> None:
    (repo / name).write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", f"Add {name}")


def test_b7_rename_status_byte_identical_without_ignore_paths(tmp_path: Path) -> None:
    """(b7-rename) `-z` emits a rename as ``R  new\\0orig\\0`` (NEW path first).
    The reconstruction must still equal plain ``--porcelain``
    (``R  orig -> new``): reading the pair in the wrong order drops the
    destination.
    """
    repo = tmp_path / "repo"
    init_git_repo(repo)
    _commit_file(repo, "a.txt", "contenido\n")
    _git(repo, "mv", "a.txt", "b.txt")

    state_z = capture_state(repo, ignore_paths=frozenset())
    plain_output = _git(repo, "status", "--porcelain").stdout

    assert state_z.status == plain_output, (state_z.status, plain_output)


def test_b7_rename_destination_change_invalidates(tmp_path: Path) -> None:
    """(b7-rename) A rename whose DESTINATION changes during the window must
    invalidate, also without ignore_paths (the default path).
    """
    repo = tmp_path / "repo"
    init_git_repo(repo)
    _commit_file(repo, "a.txt", "contenido\n")
    _git(repo, "mv", "a.txt", "b.txt")
    pre = capture_state(repo)

    _git(repo, "mv", "b.txt", "c.txt")

    try:
        verify_unchanged(repo, pre)
    except AuditInvariantViolationError as exc:
        assert "INVALIDADA" in str(exc)
    else:
        raise AssertionError("a rename moved to another destination must invalidate")


def test_b7_copy_status_byte_identical_without_ignore_paths(tmp_path: Path) -> None:
    """(b7-copy) A copy (``C``, with ``status.renames=copies``) is also a
    two-entry pair in `-z`; it must reconstruct as plain ``--porcelain``.
    """
    repo = tmp_path / "repo"
    init_git_repo(repo)
    _git(repo, "config", "status.renames", "copies")
    _commit_file(repo, "a.txt", "linea1\nlinea2\nlinea3\nlinea4\n")
    (repo / "b.txt").write_text("linea1\nlinea2\nlinea3\nlinea4\n", encoding="utf-8")
    (repo / "a.txt").write_text("linea1\nlinea2\nlinea3\nlinea4\nx\n", encoding="utf-8")
    _git(repo, "add", "-A")

    plain_output = _git(repo, "status", "--porcelain").stdout
    assert "C  a.txt -> b.txt" in plain_output, plain_output

    state_z = capture_state(repo, ignore_paths=frozenset())
    assert state_z.status == plain_output, (state_z.status, plain_output)


def test_b9_rename_with_both_paths_ignored_is_filtered(tmp_path: Path) -> None:
    """(b9) The only branch that DROPS a rename: both the original and the new
    path are in ignore_paths -> the rename is the runner's own write and does
    not invalidate.
    """
    repo = tmp_path / "repo"
    init_git_repo(repo)
    _commit_file(repo, "last-run.json", '{"status": "finished"}')
    ignore_paths = frozenset(["last-run.json", "last-run.log"])
    pre = capture_state(repo, ignore_paths=ignore_paths)

    _git(repo, "mv", "last-run.json", "last-run.log")

    verify_unchanged(repo, pre, ignore_paths=ignore_paths)  # must not raise
