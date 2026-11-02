"""WOT-2026-049b: git-recoverable artifact classification and pruning.

Every test is hermetic: it builds its OWN git repo in tmp_path with controlled
tracked / untracked files under the surface, so nothing depends on the live
repo's orchestrator_pipeline/reports/ or any real artefacts.

Contract under test:
- SAFE = the git hash of the file's CURRENT bytes is a blob that THAT path held
  in a commit reachable from ``--branches --tags --remotes`` (by CONTENT, not
  by path; the stash does not count).
- RISKY = anything else (rewritten, never committed, only staged, renamed...).
- The canonical triage pair and ``.git`` are EXCLUDED: never SAFE, RISKY nor
  deletable, not even with --confirm-risky.
- No mode = --dry-run: lists everything, deletes nothing, exits 0.
- --apply without --confirm-risky deletes ONLY safe files, exits 0.
- --apply --confirm-risky PATH... deletes safe + named risky, exits 0.
- --confirm-risky mismatch (path not in RISKY of THIS run): fail-closed,
  nothing deleted, exit 2, clear stderr.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest


# Motor root importable (tests/unit -> parents[2]).
_MOTOR_ROOT = Path(__file__).resolve().parents[2]
if str(_MOTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_MOTOR_ROOT))

import scripts.prune_git_recoverable as prune_mod  # noqa: E402
from scripts.prune_git_recoverable import (  # noqa: E402
    GitError,
    _delete_files,
    _is_contained,
    _parse_log_raw,
    classify,
    is_protected,
    run,
)


# --- Hermetic git repo fixture ----------------------------------------------


def _init_git_repo(project_root: Path) -> None:
    """Initialize a real git repo with minimal config."""
    subprocess.run(
        ["git", "init"],
        cwd=str(project_root),
        capture_output=True,
        check=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=str(project_root),
        capture_output=True,
        check=True,
        text=True,
    )
    # Never depend on the machine's global/system EOL config (152i, R3).
    subprocess.run(
        ["git", "config", "core.autocrlf", "false"],
        cwd=str(project_root),
        capture_output=True,
        check=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(project_root),
        capture_output=True,
        check=True,
        text=True,
    )


def _create_file(root: Path, rel_path: str, content: str = "x") -> Path:
    """Create a file at the given relative path."""
    full = root / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")
    return full


def _git_add_and_commit(project_root: Path, rel_paths: list[str]) -> None:
    """Git add and commit the given relative paths."""
    for p in rel_paths:
        subprocess.run(
            ["git", "add", p],
            cwd=str(project_root),
            capture_output=True,
            check=True,
            text=True,
        )
    subprocess.run(
        ["git", "commit", "-m", f"Add {rel_paths}"],
        cwd=str(project_root),
        capture_output=True,
        check=True,
        text=True,
    )


def _git_rm_and_commit(project_root: Path, rel_paths: list[str]) -> None:
    """Git rm the given paths and commit the deletion."""
    for p in rel_paths:
        subprocess.run(
            ["git", "rm", p],
            cwd=str(project_root),
            capture_output=True,
            check=True,
            text=True,
        )
    subprocess.run(
        ["git", "commit", "-m", f"Remove {rel_paths}"],
        cwd=str(project_root),
        capture_output=True,
        check=True,
        text=True,
    )


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """Create a real git repo with an orchestrator_pipeline/reports/ surface."""
    _init_git_repo(tmp_path)
    Path(tmp_path / "orchestrator_pipeline" / "reports").mkdir(
        parents=True, exist_ok=True
    )
    return tmp_path


# ═══════════════════════════════════════════════════════════════════════════
# WOT-2026-049b: 11 Test Cases
# ═══════════════════════════════════════════════════════════════════════════


class TestWotCases:
    """The 11 mandatory test cases from the work_plan (Fase 2, section 2.1)."""

    # --- Case 1: tracked file classified safe ---

    def test_tracked_file_classified_safe(self, git_repo: Path) -> None:
        """Case 1: file added+committed inside the surface -> appears in the
        SAFE list of --dry-run."""
        _create_file(git_repo, "orchestrator_pipeline/reports/report1.md")
        _git_add_and_commit(git_repo, ["orchestrator_pipeline/reports/report1.md"])

        cls = classify(git_repo, "orchestrator_pipeline/reports")
        assert "orchestrator_pipeline/reports/report1.md" in cls.safe
        assert "orchestrator_pipeline/reports/report1.md" not in cls.risky

    # --- Case 2: never tracked file classified risky ---

    def test_never_tracked_file_classified_risky(self, git_repo: Path) -> None:
        """Case 2: file created on disk, NEVER git added -> appears in RISKY,
        never in SAFE."""
        _create_file(git_repo, "orchestrator_pipeline/reports/untracked.txt")

        cls = classify(git_repo, "orchestrator_pipeline/reports")
        assert "orchestrator_pipeline/reports/untracked.txt" in cls.risky
        assert "orchestrator_pipeline/reports/untracked.txt" not in cls.safe

    # --- Case 3: committed then deleted from index, still safe ---

    def test_committed_then_deleted_from_index_still_safe(self, git_repo: Path) -> None:
        """Case 3: file committed, then git rm'ed (with commit), then a NEW
        file with the SAME name AND the SAME bytes created without track.
        Should be SAFE because a commit still holds exactly those bytes at
        that path, even though the working tree file is not tracked. (152i:
        the old version recreated DIFFERENT bytes and still asserted SAFE,
        which encoded the by-path defect; see
        ``test_recreated_with_different_bytes_is_risky``.)"""
        # Step 1: create, add, commit.
        _create_file(git_repo, "orchestrator_pipeline/reports/history.md")
        _git_add_and_commit(git_repo, ["orchestrator_pipeline/reports/history.md"])

        # Step 2: git rm + commit (remove from index and history).
        _git_rm_and_commit(git_repo, ["orchestrator_pipeline/reports/history.md"])

        # Step 3: recreate a file with the same name and bytes (untracked).
        _create_file(git_repo, "orchestrator_pipeline/reports/history.md")

        # Verify classify still finds it in historical commits.
        cls = classify(git_repo, "orchestrator_pipeline/reports")
        assert "orchestrator_pipeline/reports/history.md" in cls.safe

    # --- Case 4: dry-run never deletes anything ---

    def test_dry_run_never_deletes_anything(self, git_repo: Path) -> None:
        """Case 4: with a SAFE+RISKY mix, --dry-run leaves BOTH files intact
        (Path.exists), exit 0."""
        _create_file(git_repo, "orchestrator_pipeline/reports/safe_file.md")
        _git_add_and_commit(git_repo, ["orchestrator_pipeline/reports/safe_file.md"])
        _create_file(git_repo, "orchestrator_pipeline/reports/risky_file.md")

        safe_path = git_repo / "orchestrator_pipeline" / "reports" / "safe_file.md"
        risky_path = git_repo / "orchestrator_pipeline" / "reports" / "risky_file.md"

        assert safe_path.exists()
        assert risky_path.exists()

        rc = run(
            [
                "--project-root",
                str(git_repo),
                "--dry-run",
            ]
        )
        assert rc == 0
        assert safe_path.exists(), "--dry-run must not delete SAFE"
        assert risky_path.exists(), "--dry-run must not delete RISKY"

    # --- Case 5: apply without confirm deletes only safe ---

    def test_apply_without_confirm_deletes_only_safe(self, git_repo: Path) -> None:
        """Case 5: --apply without --confirm-risky deletes the SAFE file
        (Path.exists -> False) and preserves the RISKY intact, exit 0."""
        _create_file(git_repo, "orchestrator_pipeline/reports/safe_file.md")
        _git_add_and_commit(git_repo, ["orchestrator_pipeline/reports/safe_file.md"])
        _create_file(git_repo, "orchestrator_pipeline/reports/risky_file.md")

        safe_path = git_repo / "orchestrator_pipeline" / "reports" / "safe_file.md"
        risky_path = git_repo / "orchestrator_pipeline" / "reports" / "risky_file.md"

        rc = run(
            [
                "--project-root",
                str(git_repo),
                "--apply",
            ]
        )
        assert rc == 0
        assert not safe_path.exists(), "SAFE must be deleted"
        assert risky_path.exists(), "RISKY must NOT be deleted"

    # --- Case 6: apply with confirm risky deletes named file ---

    def test_apply_with_confirm_risky_deletes_named_file(self, git_repo: Path) -> None:
        """Case 6: --apply --confirm-risky RISKY_PATH deletes BOTH the SAFE
        and the named RISKY."""
        _create_file(git_repo, "orchestrator_pipeline/reports/safe_file.md")
        _git_add_and_commit(git_repo, ["orchestrator_pipeline/reports/safe_file.md"])
        risky_path = _create_file(
            git_repo, "orchestrator_pipeline/reports/risky_file.md"
        )

        rc = run(
            [
                "--project-root",
                str(git_repo),
                "--apply",
                "--confirm-risky",
                str(risky_path),
            ]
        )
        assert rc == 0

        safe_path = git_repo / "orchestrator_pipeline" / "reports" / "safe_file.md"
        assert not safe_path.exists(), "SAFE must be deleted"
        assert not risky_path.exists(), "RISKY must be deleted"

    # --- Case 7: confirm risky mismatch -> nothing deleted (fail-closed) ---

    def test_confirm_risky_mismatch_deletes_nothing_fail_closed(
        self, git_repo: Path
    ) -> None:
        """Case 7: --apply --confirm-risky PATH_NOT_IN_RISKY (e.g. a SAFE path,
        or nonexistent) -> exit 2, NOTHING deleted in that run.

        Mutation-verify: run again WITHOUT the --confirm-risky argument and
        confirm that SAFE IS deleted, proving the block is the invalid
        --confirm-risky, not a generic bug.
        """
        _create_file(git_repo, "orchestrator_pipeline/reports/safe_file.md")
        _git_add_and_commit(git_repo, ["orchestrator_pipeline/reports/safe_file.md"])

        safe_path = git_repo / "orchestrator_pipeline" / "reports" / "safe_file.md"

        # Use a non-existent path as the confirm-risky argument (mismatch).
        rc = run(
            [
                "--project-root",
                str(git_repo),
                "--apply",
                "--confirm-risky",
                "orchestrator_pipeline/reports/nonexistent.md",
            ]
        )
        assert rc == 2
        assert safe_path.exists(), (
            "MISMATCH must prevent deletion of SAFE too (fail-closed)"
        )

        # Mutation-verify: run again without the wrong --confirm-risky.
        before_count = len(
            list((git_repo / "orchestrator_pipeline" / "reports").iterdir())
        )
        rc2 = run(
            [
                "--project-root",
                str(git_repo),
                "--apply",
            ]
        )
        assert rc2 == 0
        after_count = len(
            list((git_repo / "orchestrator_pipeline" / "reports").iterdir())
        )
        assert after_count < before_count, (
            "Without mismatch, SAFE should have been deleted"
        )

    # --- Case 8: candidate outside surface never reachable ---

    def test_candidate_outside_surface_never_reachable(self, git_repo: Path) -> None:
        """Case 8: a file tracked OUTSIDE --surface (in another folder of the
        same repo) never appears in any classification list, even though it
        is tracked. The surface is the only universe."""
        _create_file(git_repo, "other_folder/tracked_outside.md")
        _git_add_and_commit(git_repo, ["other_folder/tracked_outside.md"])
        _create_file(git_repo, "orchestrator_pipeline/reports/risky_here.md")

        cls = classify(git_repo, "orchestrator_pipeline/reports")
        assert "other_folder/tracked_outside.md" not in cls.safe
        assert "other_folder/tracked_outside.md" not in cls.risky
        # The risky file in the surface should be classified.
        assert "orchestrator_pipeline/reports/risky_here.md" in cls.risky

    # --- Case 9: CLI --help exits zero ---

    def test_cli_help_exits_zero(self) -> None:
        """Case 9: --help exits 0 and documents the modes."""
        result = subprocess.run(
            [
                sys.executable,
                str(_MOTOR_ROOT / "scripts" / "prune_git_recoverable.py"),
                "--help",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0
        assert "dry-run" in result.stdout.lower() or "--dry-run" in result.stdout
        assert "apply" in result.stdout.lower() or "--apply" in result.stdout
        assert (
            "confirm-risky" in result.stdout.lower()
            or "--confirm-risky" in result.stdout
        )

    # --- Case 10: missing surface directory exits 1, no crash ---

    def test_missing_surface_directory_exits_one_no_crash(self, git_repo: Path) -> None:
        """Case 10: --surface pointing to a non-existent path -> exit 1,
        error message on stderr, no Python traceback."""
        result = subprocess.run(
            [
                sys.executable,
                str(_MOTOR_ROOT / "scripts" / "prune_git_recoverable.py"),
                "--project-root",
                str(git_repo),
                "--surface",
                "nonexistent/surface",
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 1
        assert "Error" in result.stderr or "error" in result.stderr
        assert "Traceback" not in result.stderr

    # --- Case 11: history-based, not citation-based ---

    def test_history_based_not_citation_based(self, git_repo: Path) -> None:
        """Case 11: a file tracked in git whose NAME is never cited/referenced
        in any other file of the repo (no prose citation) should be classified
        SAFE solely because a commit reachable from a branch, tag or remote
        holds exactly its bytes at that path.

        This is the case that originated the BLOCKER 5/5 of the backlog row
        (nonce 3de40c07): classification must use git history, never grep by
        prose references.
        """
        # Create a file that nobody references by name (no grep hit).
        _create_file(
            git_repo,
            "orchestrator_pipeline/reports/unique_orphan.md",
            content="unique_orphan_content_no_body_cites_this_file",
        )
        _create_file(
            git_repo,
            "other_folder/reference.md",
            content="this file mentions nothing about unique_orphan.md at all",
        )
        _git_add_and_commit(
            git_repo,
            [
                "other_folder/reference.md",
                "orchestrator_pipeline/reports/unique_orphan.md",
            ],
        )

        cls = classify(git_repo, "orchestrator_pipeline/reports")
        assert "orchestrator_pipeline/reports/unique_orphan.md" in cls.safe, (
            "File must be SAFE by git history, not by prose citation"
        )
        assert "orchestrator_pipeline/reports/unique_orphan.md" not in cls.risky


class TestSafety:
    """Safety invariants beyond the 11 cases."""

    def _build_mixed_repo(self, tmp_path: Path) -> tuple[Path, list[str], list[str]]:
        """Create repo with known safe and risky files. Returns (repo, safe_paths, risky_paths)."""
        _init_git_repo(tmp_path)
        Path(tmp_path / "orchestrator_pipeline" / "reports").mkdir(
            parents=True, exist_ok=True
        )

        safe_paths: list[str] = []
        risky_paths: list[str] = []

        for i in range(3):
            rel = f"orchestrator_pipeline/reports/safe_{i}.md"
            _create_file(tmp_path, rel, f"content_{i}")
            _git_add_and_commit(tmp_path, [rel])
            safe_paths.append(rel)

        for i in range(2):
            rel = f"orchestrator_pipeline/reports/risky_{i}.md"
            _create_file(tmp_path, rel, f"risky_content_{i}")
            risky_paths.append(rel)

        return tmp_path, safe_paths, risky_paths

    def test_all_safe_files_deleted_by_apply(self, tmp_path: Path) -> None:
        """After --apply, ALL safe files must be gone, all risky intact."""
        repo, safe_paths, risky_paths = self._build_mixed_repo(tmp_path)

        rc = run(["--project-root", str(repo), "--apply"])
        assert rc == 0

        for rel in safe_paths:
            assert not (repo / rel).exists(), f"{rel} should be deleted"
        for rel in risky_paths:
            assert (repo / rel).exists(), f"{rel} should NOT be deleted"

    def test_all_risky_deleted_with_confirm(self, tmp_path: Path) -> None:
        """--apply --confirm-risky with ALL risky paths -> all deleted."""
        repo, safe_paths, risky_paths = self._build_mixed_repo(tmp_path)

        rc = run(
            [
                "--project-root",
                str(repo),
                "--apply",
                "--confirm-risky",
                *risky_paths,
            ]
        )
        assert rc == 0

        for rel in safe_paths:
            assert not (repo / rel).exists()
        for rel in risky_paths:
            assert not (repo / rel).exists()

    def test_partial_confirm_risky_succeeds(self, tmp_path: Path) -> None:
        """--apply --confirm-risky with ONLY SOME risky paths -> safe + those risky deleted,
        other risky preserved."""
        repo, safe_paths, risky_paths = self._build_mixed_repo(tmp_path)

        confirm_one = risky_paths[0]
        unconfirmed = risky_paths[1:]

        rc = run(
            ["--project-root", str(repo), "--apply", "--confirm-risky", confirm_one]
        )
        assert rc == 0

        # Safe deleted.
        for rel in safe_paths:
            assert not (repo / rel).exists()
        # Confirmed risky deleted.
        assert not (repo / confirm_one).exists()
        # Unconfirmed risky preserved.
        for rel in unconfirmed:
            assert (repo / rel).exists()

    def test_content_empty_surface(self, git_repo: Path) -> None:
        """Surface exists but has no files -> both lists empty, exit 0."""
        rc = run(
            [
                "--project-root",
                str(git_repo),
                "--dry-run",
            ]
        )
        assert rc == 0

    def test_subclass_dry_run_output_contains_categories(
        self, git_repo: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """--dry-run output must contain both SAFE and RISKY labels when both exist."""
        _create_file(git_repo, "orchestrator_pipeline/reports/s.md")
        _git_add_and_commit(git_repo, ["orchestrator_pipeline/reports/s.md"])
        _create_file(git_repo, "orchestrator_pipeline/reports/r.md")

        rc = run(["--project-root", str(git_repo), "--dry-run"])
        assert rc == 0

        out = capsys.readouterr().out
        assert "SAFE" in out or "safe" in out
        assert "RISKY" in out or "risky" in out

    def test_mismatch_with_safe_path_as_confirm(self, git_repo: Path) -> None:
        """Using a SAFE path as --confirm-risky argument is a mismatch: the
        path is not in the RISKY set. Must fail-closed (exit 2, nothing
        deleted)."""
        _create_file(git_repo, "orchestrator_pipeline/reports/safe_file.md")
        _git_add_and_commit(git_repo, ["orchestrator_pipeline/reports/safe_file.md"])
        _create_file(git_repo, "orchestrator_pipeline/reports/risky_file.md")

        safe_path_str = "orchestrator_pipeline/reports/safe_file.md"

        rc = run(
            [
                "--project-root",
                str(git_repo),
                "--apply",
                "--confirm-risky",
                safe_path_str,
            ]
        )
        assert rc == 2

        # Neither file should be deleted.
        safe_file = git_repo / "orchestrator_pipeline" / "reports" / "safe_file.md"
        risky_file = git_repo / "orchestrator_pipeline" / "reports" / "risky_file.md"
        assert safe_file.exists(), "SAFE must not be deleted on mismatch"
        assert risky_file.exists(), "RISKY must not be deleted on mismatch"

    def test_risky_in_risky_set_but_not_on_disk(self, git_repo: Path) -> None:
        """A file that is RISKY (never tracked in git) but was deleted from
        disk between classify and apply: classify returns empty lists (no file
        to classify), and apply with confirm-risky handles it gracefully."""
        risky_path_str = "orchestrator_pipeline/reports/r.md"

        _create_file(git_repo, risky_path_str)
        cls = classify(git_repo, "orchestrator_pipeline/reports")
        assert risky_path_str in cls.risky

        # Delete the file after classify.
        risky_path = git_repo / "orchestrator_pipeline" / "reports" / "r.md"
        risky_path.unlink()

        # classify now sees an empty surface (file no longer on disk).
        cls2 = classify(git_repo, "orchestrator_pipeline/reports")
        assert cls2.safe == []
        assert cls2.risky == []

        # Apply with confirm-risky should fail-closed (exit 2) because the
        # file no longer exists, classify returns empty lists, and the path
        # is not in the empty RISKY set.
        rc = run(
            [
                "--project-root",
                str(git_repo),
                "--apply",
                "--confirm-risky",
                risky_path_str,
            ]
        )
        assert rc == 2  # fail-closed: path not in empty RISKY set

    def test_safe_only_in_other_branch_restore_fails_on_mismatch(
        self, tmp_path: Path
    ) -> None:
        """Cross-branch blocker: a file SAFE because a commit of another
        branch holds exactly its bytes at that path (it is not in the current
        branch HEAD/index) must NOT be deleted when --confirm-risky has a
        mismatch.

        This is the exact scenario from the BLOCKER report:
        - Create a file on 'side' branch (reachable via ``--branches``).
        - Checkout the base branch, create the same file with the SAME bytes
          on disk (untracked there).
        - Classify finds it SAFE (the side commit holds those bytes, by
          content and at that path).
        - git checkout -- on main would fail (pathspec not in HEAD).
        - --confirm-risky mismatch must leave the file INTACT with bytes.
        """
        side_repo = tmp_path / "repro_repo"
        side_repo.mkdir()
        _init_git_repo(side_repo)

        # Step 1: create file on side branch.
        side_repo.joinpath("README.md").write_text("init", encoding="utf-8")
        subprocess.run(
            ["git", "add", "README.md"],
            cwd=str(side_repo),
            capture_output=True,
            check=True,
            text=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=str(side_repo),
            capture_output=True,
            check=True,
            text=True,
        )

        # Remember the initial branch: it is 'master' or 'main' depending on
        # the machine's init.defaultBranch, so never hardcode it (152i, R7).
        base_branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(side_repo),
            capture_output=True,
            check=True,
            text=True,
        ).stdout.strip()

        # Step 2: create side branch with the file in surface.
        subprocess.run(
            ["git", "checkout", "-b", "side"],
            cwd=str(side_repo),
            capture_output=True,
            check=True,
            text=True,
        )
        reports_dir = side_repo / "orchestrator_pipeline" / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        side_file = reports_dir / "side_only.md"
        side_file.write_text("side content", encoding="utf-8")
        subprocess.run(
            ["git", "add", "orchestrator_pipeline/reports/side_only.md"],
            cwd=str(side_repo),
            capture_output=True,
            check=True,
            text=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "add on side"],
            cwd=str(side_repo),
            capture_output=True,
            check=True,
            text=True,
        )

        # Step 3: switch to main, create same file on disk (untracked on main).
        subprocess.run(
            ["git", "checkout", "-q", base_branch],
            cwd=str(side_repo),
            capture_output=True,
            check=True,
            text=True,
        )
        reports_dir.mkdir(parents=True, exist_ok=True)
        # SAME bytes as the side commit: only then is the file SAFE (152i).
        side_file.write_text("side content", encoding="utf-8")

        # Verify: file exists on disk, classified SAFE by content + path.
        cls = classify(side_repo, "orchestrator_pipeline/reports")
        assert "orchestrator_pipeline/reports/side_only.md" in cls.safe, (
            "File must be SAFE (the side branch commit holds these exact bytes "
            "at this path)"
        )

        # Now run with mismatch confirm-risky.
        rc = run(
            [
                "--project-root",
                str(side_repo),
                "--apply",
                "--confirm-risky",
                "orchestrator_pipeline/reports/nonexistent.md",
            ]
        )
        assert rc == 2

        # THE BLOCKER ASSERTION: file must still exist with INTACT content.
        assert side_file.exists(), (
            "side_only.md must NOT be deleted on --confirm-risky mismatch"
        )
        assert side_file.read_text(encoding="utf-8") == "side content", (
            "side_only.md content must be byte-identical after mismatch"
        )


# ═══════════════════════════════════════════════════════════════════════════
# WOT-2026-152i (049b-r2): SAFE by CONTENT, protected canonical pair, dead
# mutants, dry-run by default. Every test builds its own repo in tmp_path and
# only ever deletes inside it.
# ═══════════════════════════════════════════════════════════════════════════

REL = "orchestrator_pipeline/reports"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        check=True,
        text=True,
        encoding="utf-8",
    ).stdout


def _commit_all(root: Path, message: str = "c") -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message)


def _write(root: Path, rel: str, data: bytes) -> Path:
    full = root / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(data)
    return full


def _symlink(target: Path, link: Path, is_dir: bool = False) -> None:
    try:
        os.symlink(target, link, target_is_directory=is_dir)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks cannot be created on this machine")


@pytest.fixture()
def repo(git_repo: Path) -> Path:
    """A repo whose first commit exists, so HEAD/branches are real."""
    _write(git_repo, "README.md", b"init")
    _commit_all(git_repo, "init")
    return git_repo


class TestSafeByContent:
    """DoD 1: SAFE only if the CURRENT bytes are a blob committed at that path."""

    def test_rewritten_tracked_file_is_risky_and_apply_keeps_it(
        self, repo: Path
    ) -> None:
        full = _write(repo, f"{REL}/x.md", b"v1-old")
        _commit_all(repo)
        full.write_bytes(b"v2-new-live-bytes")

        cls = classify(repo, REL)
        assert f"{REL}/x.md" in cls.risky
        assert f"{REL}/x.md" not in cls.safe

        assert run(["--project-root", str(repo), "--apply"]) == 0
        assert full.read_bytes() == b"v2-new-live-bytes"
        assert _git(repo, "show", f"HEAD:{REL}/x.md") == "v1-old"

    def test_recreated_with_different_bytes_is_risky(self, repo: Path) -> None:
        _write(repo, f"{REL}/h.md", b"original")
        _commit_all(repo)
        _git(repo, "rm", "-q", f"{REL}/h.md")
        _commit_all(repo, "rm")
        full = _write(repo, f"{REL}/h.md", b"other bytes")

        cls = classify(repo, REL)
        assert f"{REL}/h.md" in cls.risky
        assert run(["--project-root", str(repo), "--apply"]) == 0
        assert full.read_bytes() == b"other bytes"

    def test_rewritten_back_to_an_old_committed_version_is_safe(
        self, repo: Path
    ) -> None:
        full = _write(repo, f"{REL}/x.md", b"v1")
        _commit_all(repo)
        full.write_bytes(b"v2")
        _commit_all(repo)
        full.write_bytes(b"v1")

        cls = classify(repo, REL)
        assert f"{REL}/x.md" in cls.safe
        assert (
            cls.safe_blobs[f"{REL}/x.md"]
            == _git(repo, "rev-parse", f"HEAD~1:{REL}/x.md").strip()
        )

    def test_staged_but_not_committed_bytes_are_risky(self, repo: Path) -> None:
        full = _write(repo, f"{REL}/x.md", b"v1")
        _commit_all(repo)
        full.write_bytes(b"v2-only-staged")
        _git(repo, "add", f"{REL}/x.md")
        new = _write(repo, f"{REL}/new.md", b"brand new")
        _git(repo, "add", f"{REL}/new.md")

        cls = classify(repo, REL)
        assert set(cls.risky) == {f"{REL}/x.md", f"{REL}/new.md"}
        assert cls.safe == []
        assert run(["--project-root", str(repo), "--apply"]) == 0
        assert full.exists() and new.exists()

    def test_same_bytes_under_another_path_are_risky(self, repo: Path) -> None:
        _write(repo, f"{REL}/a.md", b"shared bytes")
        _commit_all(repo)
        copy = _write(repo, f"{REL}/copy_never_committed.md", b"shared bytes")

        cls = classify(repo, REL)
        assert cls.safe == [f"{REL}/a.md"]
        assert cls.risky == [f"{REL}/copy_never_committed.md"]
        assert run(["--project-root", str(repo), "--apply"]) == 0
        assert copy.exists()

    def test_empty_file_follows_the_same_rule(self, repo: Path) -> None:
        _write(repo, f"{REL}/empty_committed.md", b"")
        _write(repo, f"{REL}/was_full.md", b"had content")
        _commit_all(repo)
        _write(repo, f"{REL}/was_full.md", b"")
        _write(repo, f"{REL}/empty_untracked.md", b"")

        cls = classify(repo, REL)
        assert cls.safe == [f"{REL}/empty_committed.md"]
        assert cls.safe_sizes[f"{REL}/empty_committed.md"] == 0
        assert set(cls.risky) == {f"{REL}/was_full.md", f"{REL}/empty_untracked.md"}

    def test_unicode_and_space_path_is_classified_by_content(self, repo: Path) -> None:
        name = f"{REL}/reconcile año 1.json"
        _write(repo, name, b"{}")
        _commit_all(repo)

        assert classify(repo, REL).safe == [name]
        _write(repo, name, b'{"changed": true}')
        assert classify(repo, REL).risky == [name]

    def test_crlf_equivalence_follows_the_repo_config_not_the_machine(
        self, tmp_path: Path
    ) -> None:
        on = tmp_path / "eol_on"
        off = tmp_path / "eol_off"
        for root, setting in ((on, "true"), (off, "false")):
            root.mkdir()
            _init_git_repo(root)
            _git(root, "config", "core.autocrlf", setting)
            _write(root, f"{REL}/t.md", b"line1\nline2\n")
            _commit_all(root)
            _write(root, f"{REL}/t.md", b"line1\r\nline2\r\n")

        assert classify(on, REL).safe == [f"{REL}/t.md"]
        assert classify(off, REL).risky == [f"{REL}/t.md"]

    def test_blob_only_in_the_stash_is_not_a_recovery_point(self, repo: Path) -> None:
        full = _write(repo, f"{REL}/x.md", b"v1")
        _commit_all(repo)
        full.write_bytes(b"v2-only-in-stash")
        # Staged first: the stash's INDEX commit then carries the v2 blob, the
        # one a `git log --all` walk would (wrongly) accept as a recovery point.
        _git(repo, "add", f"{REL}/x.md")
        _git(repo, "stash", "push", "-q")
        assert full.read_bytes() == b"v1"
        _git(repo, "stash", "apply", "-q")
        assert full.read_bytes() == b"v2-only-in-stash"
        assert "v2-only-in-stash" in _git(repo, "log", "--all", "-p", "--", REL)

        assert classify(repo, REL).risky == [f"{REL}/x.md"]

    def test_repo_without_commits_classifies_everything_risky(
        self, git_repo: Path
    ) -> None:
        _write(git_repo, f"{REL}/a.md", b"a")
        cls = classify(git_repo, REL)
        assert cls.risky == [f"{REL}/a.md"] and cls.safe == []

    def test_project_root_below_the_git_toplevel(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path)
        sub = tmp_path / "sub"
        _write(sub, f"{REL}/a.md", b"a")
        _commit_all(tmp_path)

        assert classify(sub, REL).safe == [f"{REL}/a.md"]

    def test_git_failure_aborts_and_deletes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
        keep = _write(tmp_path, f"{REL}/a.md", b"a")

        with pytest.raises(GitError):
            classify(tmp_path, REL)
        assert run(["--project-root", str(tmp_path), "--apply"]) == 1
        assert keep.exists()

    def test_missing_git_binary_aborts_and_deletes_nothing(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        keep = _write(repo, f"{REL}/a.md", b"a")
        _commit_all(repo)

        def no_git(*_args: object, **_kwargs: object) -> None:
            raise FileNotFoundError("git")

        monkeypatch.setattr(prune_mod.subprocess, "run", no_git)
        assert run(["--project-root", str(repo), "--apply"]) == 1
        assert keep.exists()


class TestProtectedCanonicalPair:
    """DoD 2: the canonical triage pair is outside every code path that deletes."""

    PROTECTED = (
        f"{REL}/backlog_triage_20261101-053321.json",
        f"{REL}/backlog_triage_20261101-053321.md",
        f"{REL}/batch_run_20260714-0000.json",
        f"{REL}/start_context_isolation.json",
        f"{REL}/audit_autonomous_batch_x.md",
        f"{REL}/integration_receipts/abc.json",
        f"{REL}/_dag_20260901.json",
        f"{REL}/gate/MUTATION_WOT-1.md",
        f"{REL}/Backlog_Triage_UPPER.JSON",
    )

    def _build(self, repo: Path) -> Path:
        for rel in self.PROTECTED:
            _write(repo, rel, b"canonical")
        plain = _write(repo, f"{REL}/reconcile_a/raw/grep_hits.txt", b"junk")
        _commit_all(repo)
        return plain

    def test_default_surface_apply_keeps_the_pair_and_deletes_the_rest(
        self, repo: Path
    ) -> None:
        plain = self._build(repo)

        cls = classify(repo, REL)
        assert set(cls.excluded) == set(self.PROTECTED)
        assert cls.safe == [f"{REL}/reconcile_a/raw/grep_hits.txt"]

        assert run(["--project-root", str(repo), "--apply"]) == 0
        assert not plain.exists()
        for rel in self.PROTECTED:
            assert (repo / rel).exists(), rel

    def test_a_surface_that_is_inside_the_pair_is_fully_excluded(
        self, repo: Path
    ) -> None:
        self._build(repo)
        surface = f"{REL}/integration_receipts"

        cls = classify(repo, surface)
        assert cls.safe == [] and cls.risky == []
        assert run(["--project-root", str(repo), "--surface", surface, "--apply"]) == 0
        assert (repo / f"{REL}/integration_receipts/abc.json").exists()

    def test_confirm_risky_cannot_name_a_protected_path(
        self, repo: Path, capsys: pytest.CaptureFixture
    ) -> None:
        self._build(repo)
        fresh = _write(repo, f"{REL}/backlog_triage_NEW_untracked.json", b"live")
        plain = repo / f"{REL}/reconcile_a/raw/grep_hits.txt"

        rc = run(
            [
                "--project-root",
                str(repo),
                "--apply",
                "--confirm-risky",
                f"{REL}/backlog_triage_NEW_untracked.json",
            ]
        )
        assert rc == 2
        assert "protected path" in capsys.readouterr().err
        assert fresh.exists() and plain.exists()

    def test_git_dir_names_are_protected_everywhere(self, repo: Path) -> None:
        inner = _write(repo, f"{REL}/vendored/.git/config", b"x")
        assert classify(repo, REL).excluded == [f"{REL}/vendored/.git/config"]
        assert (
            run(
                [
                    "--project-root",
                    str(repo),
                    "--apply",
                    "--confirm-risky",
                    f"{REL}/vendored/.git/config",
                ]
            )
            == 2
        )
        assert inner.exists()

    @pytest.mark.parametrize(
        ("rel", "expected"),
        [
            ("a/backlog_triage_1.json", True),
            ("a/BATCH_RUN_1.JSON", True),
            ("a/start_context_isolation/f/receipt.json", True),
            ("x/.GIT/y", True),
            ("a/reconcile_a/raw/grep_hits.txt", False),
            ("a/not_a_batch_run.json", False),
            ("a/.gitignore", False),
        ],
    )
    def test_is_protected(self, rel: str, expected: bool) -> None:
        assert is_protected(rel) is expected


class TestMutantsOfThe049bReview:
    """DoD 3: `_is_contained`, symlinks and sizes had 3 surviving mutants."""

    def test_is_contained_inside_outside_and_prefix_sibling(
        self, tmp_path: Path
    ) -> None:
        surface = tmp_path / "reports"
        surface.mkdir()
        assert _is_contained(surface / "a.md", surface) is True
        assert _is_contained(surface / "sub" / "a.md", surface) is True
        assert _is_contained(surface / ".." / "outside.md", surface) is False
        assert _is_contained(tmp_path / "reports_evil" / "a.md", surface) is False

    def test_delete_files_refuses_a_path_that_escapes_the_surface(
        self, repo: Path
    ) -> None:
        outside = _write(repo, "outside.md", b"must survive")
        (repo / REL).mkdir(parents=True, exist_ok=True)

        with pytest.raises(RuntimeError, match="not contained"):
            _delete_files([f"{REL}/../../outside.md"], repo, REL)
        assert outside.read_bytes() == b"must survive"

    def test_symlinks_are_skipped_never_classified_nor_deleted(
        self, repo: Path
    ) -> None:
        target = _write(repo, "other/tracked.md", b"tracked elsewhere")
        _write(repo, f"{REL}/real.md", b"real")
        _commit_all(repo)
        _symlink(target, repo / REL / "link.md")
        _symlink(repo / "other", repo / REL / "linkdir", is_dir=True)

        cls = classify(repo, REL)
        assert cls.skipped == {
            f"{REL}/link.md": "symlink",
            f"{REL}/linkdir": "symlink",
        }
        assert cls.safe == [f"{REL}/real.md"] and cls.risky == []

        assert (
            run(
                [
                    "--project-root",
                    str(repo),
                    "--apply",
                    "--confirm-risky",
                    f"{REL}/link.md",
                ]
            )
            == 2
        )
        assert run(["--project-root", str(repo), "--apply"]) == 0
        assert os.path.lexists(repo / REL / "link.md")
        assert os.path.lexists(repo / REL / "linkdir")
        assert target.read_bytes() == b"tracked elsewhere"

    def test_a_safe_file_swapped_for_a_symlink_before_unlink_is_refused(
        self, repo: Path
    ) -> None:
        victim = _write(repo, f"{REL}/victim.md", b"safe bytes")
        keep = _write(repo, f"{REL}/other.md", b"other bytes")
        _commit_all(repo)
        cls = classify(repo, REL)
        assert f"{REL}/victim.md" in cls.safe

        victim.unlink()
        _symlink(keep, victim)
        result = _delete_files([f"{REL}/victim.md"], repo, REL, cls.safe_blobs)

        assert result.deleted == []
        assert result.refused == {f"{REL}/victim.md": "symlink or junction"}
        assert os.path.lexists(victim) and keep.read_bytes() == b"other bytes"

    def test_a_safe_file_rewritten_after_classification_is_refused(
        self, repo: Path
    ) -> None:
        full = _write(repo, f"{REL}/x.md", b"committed")
        _commit_all(repo)
        cls = classify(repo, REL)

        full.write_bytes(b"live bytes written after the dry look")
        result = _delete_files(cls.safe, repo, REL, cls.safe_blobs)

        assert result.deleted == []
        assert result.refused == {f"{REL}/x.md": "content changed since classification"}
        assert full.read_bytes() == b"live bytes written after the dry look"

    def test_a_directory_with_a_file_name_is_refused_not_removed(
        self, repo: Path
    ) -> None:
        folder = repo / REL / "d.md"
        folder.mkdir(parents=True)
        result = _delete_files([f"{REL}/d.md"], repo, REL)
        assert result.deleted == []
        assert result.refused == {f"{REL}/d.md": "not a regular file"}
        assert folder.is_dir()

    def test_an_absent_file_is_neither_deleted_nor_refused(self, repo: Path) -> None:
        (repo / REL).mkdir(parents=True, exist_ok=True)
        result = _delete_files([f"{REL}/gone.md"], repo, REL)
        assert result.deleted == [] and result.refused == {}

    def test_unlink_failure_is_refused_and_exit_code_is_one(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        full = _write(repo, f"{REL}/x.md", b"x")
        _commit_all(repo)
        real_unlink = Path.unlink

        def deny(self: Path, *args: object, **kwargs: object) -> None:
            if self.name == "x.md":
                raise PermissionError("denied")
            real_unlink(self, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", deny)
        assert run(["--project-root", str(repo), "--apply"]) == 1
        assert full.exists()

    def test_sizes_are_real_byte_counts_in_data_and_report(
        self, repo: Path, capsys: pytest.CaptureFixture
    ) -> None:
        _write(repo, f"{REL}/seven.md", b"1234567")
        _commit_all(repo)
        _write(repo, f"{REL}/twelve.md", b"123456789012")

        cls = classify(repo, REL)
        assert cls.safe_sizes == {f"{REL}/seven.md": 7}
        assert cls.risky_sizes == {f"{REL}/twelve.md": 12}

        assert run(["--project-root", str(repo), "--dry-run"]) == 0
        out = capsys.readouterr().out
        assert "seven.md (7 bytes)" in out and "twelve.md (12 bytes)" in out
        assert "total: 2 file(s), 19 bytes" in out


class TestModesAndSurface:
    """DoD 4 (dry-run by default) and the surface / confirm-flag guards."""

    def test_no_mode_is_a_dry_run_with_exit_zero(
        self, repo: Path, capsys: pytest.CaptureFixture
    ) -> None:
        safe = _write(repo, f"{REL}/s.md", b"s")
        _commit_all(repo)
        risky = _write(repo, f"{REL}/r.md", b"r")

        assert run(["--project-root", str(repo)]) == 0
        assert safe.exists() and risky.exists()
        assert "[DRY-RUN] no files deleted" in capsys.readouterr().out

    def test_cli_without_mode_exits_zero_and_deletes_nothing(self, repo: Path) -> None:
        safe = _write(repo, f"{REL}/s.md", b"s")
        _commit_all(repo)

        result = subprocess.run(
            [
                sys.executable,
                str(_MOTOR_ROOT / "scripts" / "prune_git_recoverable.py"),
                "--project-root",
                str(repo),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert safe.exists()

    @pytest.mark.parametrize(
        "extra",
        [
            ["--apply", "--confirm-risky"],
            ["--dry-run", "--confirm-risky", f"{REL}/r.md"],
            ["--confirm-risky", f"{REL}/r.md"],
        ],
    )
    def test_confirm_risky_misuse_is_an_error_and_deletes_nothing(
        self, repo: Path, extra: list[str]
    ) -> None:
        safe = _write(repo, f"{REL}/s.md", b"s")
        _commit_all(repo)
        risky = _write(repo, f"{REL}/r.md", b"r")

        assert run(["--project-root", str(repo), *extra]) == 2
        assert safe.exists() and risky.exists()

    @pytest.mark.parametrize("surface", [".", "..", "a/../..", "", ".git", "x/.git/y"])
    def test_surface_outside_or_equal_to_the_repo_root_is_rejected(
        self, repo: Path, surface: str
    ) -> None:
        keep = _write(repo, "README.md", b"init")
        (repo / "x" / ".git" / "y").mkdir(parents=True, exist_ok=True)

        assert run(["--project-root", str(repo), "--surface", surface, "--apply"]) == 1
        assert keep.exists()

    @pytest.mark.parametrize(
        ("surface", "message"),
        [
            (".", "strictly inside"),
            ("..", "strictly inside"),
            ("a/../..", "strictly inside"),
            ("", "strictly inside"),
            (".git", "may not contain .git"),
            ("x/.git/y", "may not contain .git"),
        ],
    )
    def test_validation_rejects_the_surface_itself_not_git_afterwards(
        self, repo: Path, surface: str, message: str
    ) -> None:
        """The guard must fire BEFORE git, with ITS OWN reason (not a later
        GitError or the symlink check that also happens to catch `..`)."""
        (repo / "x" / ".git" / "y").mkdir(parents=True, exist_ok=True)
        with pytest.raises(ValueError, match=message):
            classify(repo, surface)

    def test_absolute_surface_is_rejected(self, repo: Path) -> None:
        keep = _write(repo, f"{REL}/a.md", b"a")
        _commit_all(repo)
        argv = ["--project-root", str(repo), "--surface", str(repo / REL), "--apply"]
        assert run(argv) == 1
        assert keep.exists()

    def test_a_symlinked_surface_is_rejected(self, repo: Path) -> None:
        real = repo / "real_surface"
        keep = _write(repo, "real_surface/a.md", b"a")
        _commit_all(repo)
        _symlink(real, repo / "link_surface", is_dir=True)

        argv = ["--project-root", str(repo), "--surface", "link_surface", "--apply"]
        assert run(argv) == 1
        assert keep.exists()


def _fake_git(
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    make: Callable[[list[str]], subprocess.CompletedProcess],
) -> None:
    """Make ``_run_git`` answer ``make(args)`` for ``command``; real git else."""
    real = prune_mod._run_git

    def fake(root: Path, args: list[str]) -> subprocess.CompletedProcess:
        if command in args:
            return make(args)
        return real(root, args)

    monkeypatch.setattr(prune_mod, "_run_git", fake)


class TestGitFailureIsNotRisky:
    """Round 2 (BA254): a git failure must abort, never read as 'not in git'."""

    def _failing_filter_repo(self, repo: Path) -> tuple[Path, Path]:
        sibling = _write(repo, "r/a.txt", b"a")
        broken = _write(repo, "r/b.bad", b"b")
        _write(repo, ".gitattributes", b"*.bad filter=bad\n")
        _commit_all(repo)
        # The clean filter only starts failing after the commit.
        _git(repo, "config", "filter.bad.clean", "false")
        _git(repo, "config", "filter.bad.required", "true")
        return sibling, broken

    def test_failing_clean_filter_aborts_and_deletes_nothing_not_even_the_safe_one(
        self, repo: Path
    ) -> None:
        sibling, broken = self._failing_filter_repo(repo)

        with pytest.raises(GitError, match="hash-object failed"):
            classify(repo, "r")
        assert run(["--project-root", str(repo), "--surface", "r", "--apply"]) == 1
        assert sibling.exists() and broken.exists()

    def test_failing_clean_filter_with_confirm_risky_deletes_nothing(
        self, repo: Path
    ) -> None:
        sibling, broken = self._failing_filter_repo(repo)
        untracked = _write(repo, "r/c.txt", b"never committed")

        argv = ["--project-root", str(repo), "--surface", "r", "--apply"]
        assert run([*argv, "--confirm-risky", "r/c.txt", "r/b.bad"]) == 1
        assert sibling.exists() and broken.exists() and untracked.exists()

    def test_file_vanishing_between_listing_and_hashing_is_not_a_git_failure(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        keep = _write(repo, "r/keep.txt", b"k")
        gone = _write(repo, "r/gone.txt", b"g")
        _commit_all(repo)
        real = prune_mod._run_git

        def vanishing(root: Path, args: list[str]) -> subprocess.CompletedProcess:
            if args[0] == "hash-object" and args[-1].endswith("gone.txt"):
                gone.unlink(missing_ok=True)
            return real(root, args)

        monkeypatch.setattr(prune_mod, "_run_git", vanishing)
        cls = classify(repo, "r")

        assert cls.safe == ["r/keep.txt"] and cls.risky == []
        assert keep.exists() and not gone.exists()

    def test_hash_object_output_that_is_not_a_hash_aborts(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        keep = _write(repo, "r/a.txt", b"a")
        _commit_all(repo)
        _fake_git(
            monkeypatch,
            "hash-object",
            lambda args: subprocess.CompletedProcess(args, 0, b"not-a-hash\n", b""),
        )

        with pytest.raises(GitError, match="no hash"):
            classify(repo, "r")
        assert run(["--project-root", str(repo), "--surface", "r", "--apply"]) == 1
        assert keep.exists()

    def test_git_failing_right_before_the_unlink_refuses_the_file(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        keep = _write(repo, "r/a.txt", b"a")
        _commit_all(repo)
        cls = classify(repo, "r")
        _fake_git(
            monkeypatch,
            "hash-object",
            lambda args: subprocess.CompletedProcess(args, 128, b"", b"boom"),
        )

        result = _delete_files(cls.safe, repo, "r", cls.safe_blobs)

        assert result.deleted == []
        assert result.refused == {"r/a.txt": "cannot verify content (git failed)"}
        assert keep.exists()


class TestUndecodablePathBytes:
    """Round 2 (BA254 BLOCKER): lossy decoding must not alias a real file."""

    def test_git_path_with_non_utf8_bytes_never_makes_a_lookalike_safe(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The replacement character is built, not typed: the encoding guard
        # (rightly) rejects a literal U+FFFD in any source file.
        name = "reports/" + chr(0xFFFD) + ".md"
        lookalike = _write(repo, name, b"same bytes")
        blob = _git(repo, "hash-object", name).strip()
        # What git would print for a path committed as b"reports/\xff.md".
        raw = b":000000 100644 " + b"0" * 40 + b" " + blob.encode() + b" A\0"
        raw += b"reports/\xff.md\0"
        _fake_git(
            monkeypatch,
            "log",
            lambda args: subprocess.CompletedProcess(args, 0, raw, b""),
        )

        cls = classify(repo, "reports")

        assert cls.safe == []
        assert cls.risky == [name]
        assert (
            run(["--project-root", str(repo), "--surface", "reports", "--apply"]) == 0
        )
        assert lookalike.read_bytes() == b"same bytes"


_ZERO = "0" * 40
_BLOB = "a" * 40
_OTHER = "b" * 40


def _raw(old: str, new: str, status: str, path: str) -> str:
    """One `git log --raw -z` record: header token, path token, separator."""
    mode_old = "000000" if old == _ZERO else "100644"
    mode_new = "000000" if new == _ZERO else "100644"
    return f":{mode_old} {mode_new} {old} {new} {status}\0{path}\0"


class TestStrictLogParsing:
    """Round 3 (BA254 MAJOR): unexpected `git log --raw` output is an error,
    never 'this path has no history'."""

    def test_valid_records_incl_deletion_then_readd_parse_correctly(self) -> None:
        out = (
            _raw(_ZERO, _BLOB, "A", "r/a.txt")
            + "\0"
            + _raw(_BLOB, _ZERO, "D", "r/a.txt")
            + "\0"
            + _raw(_ZERO, _OTHER, "A", "r/a.txt")
            + _raw(_BLOB, _OTHER, "M", "r/b.txt")
            + _raw(_BLOB, _OTHER, "T", "r/c.txt")
        )
        assert _parse_log_raw(out) == {
            "r/a.txt": {_BLOB, _OTHER},
            "r/b.txt": {_OTHER},
            "r/c.txt": {_OTHER},
        }

    def test_deletion_alone_records_the_path_without_a_blob(self) -> None:
        assert _parse_log_raw(_raw(_BLOB, _ZERO, "D", "r/gone.txt")) == {
            "r/gone.txt": set()
        }

    def test_a_deleted_then_recreated_file_is_still_safe_end_to_end(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        full = _write(repo, "r/a.txt", b"same bytes")
        blob = _git(repo, "hash-object", "r/a.txt").strip()
        raw = (
            _raw(blob, _ZERO, "D", "r/a.txt") + "\0" + _raw(_ZERO, blob, "A", "r/a.txt")
        )
        _fake_git(
            monkeypatch,
            "log",
            lambda args: subprocess.CompletedProcess(args, 0, raw.encode(), b""),
        )
        assert classify(repo, "r").safe == ["r/a.txt"]
        assert full.exists()

    def test_a_file_name_starting_with_a_colon_is_a_path_not_a_header(self) -> None:
        out = _raw(_ZERO, _BLOB, "A", ":weird.md") + _raw(
            _ZERO, _OTHER, "A", ":100644 000000 not a header"
        )
        assert _parse_log_raw(out) == {
            ":weird.md": {_BLOB},
            ":100644 000000 not a header": {_OTHER},
        }

    @pytest.mark.parametrize(
        "bad",
        [
            # the BA254 counterexample: invalid new hash that is not all zeros
            f":000000 100644 {_ZERO} not-a-hash A\0r/a.txt\0",
            f":000000 100644 {_ZERO} {_BLOB[:39]} A\0r/a.txt\0",
            # added without a blob / deleted with one
            _raw(_ZERO, _ZERO, "A", "r/a.txt"),
            _raw(_BLOB, _OTHER, "D", "r/a.txt"),
            # statuses that carry two paths or are not understood
            f":100644 100644 {_BLOB} {_OTHER} R100\0old\0new\0",
            f":100644 100644 {_BLOB} {_OTHER} C100\0old\0new\0",
            f":100644 100644 {_BLOB} {_OTHER} X\0r/a.txt\0",
            f":100644 100644 {_BLOB} {_OTHER} M \0r/a.txt\0",
            # malformed header: too few fields, bad mode, trailing newline
            f":100644 {_BLOB} {_OTHER} M\0r/a.txt\0",
            f":10064x 100644 {_BLOB} {_OTHER} M\0r/a.txt\0",
            _raw(_ZERO, _BLOB, "A", "r/a.txt").replace(" A\0", " A\n\0"),
            # header without a path
            f":000000 100644 {_ZERO} {_BLOB} A\0",
            f":000000 100644 {_ZERO} {_BLOB} A\0\0",
            # orphan / stray tokens
            "garbage\0",
            _raw(_ZERO, _BLOB, "A", "r/a.txt") + "stray\0",
            "\n\0",
        ],
    )
    def test_unexpected_output_is_an_error_not_an_absence_of_history(
        self, bad: str
    ) -> None:
        with pytest.raises(GitError):
            _parse_log_raw(bad)

    def test_the_counterexample_aborts_classify_and_every_apply_form(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        a = _write(repo, "r/a.txt", b"a")
        b = _write(repo, "r/b.txt", b"b")
        raw = f":000000 100644 {_ZERO} not-a-hash A\0r/a.txt\0".encode()
        _fake_git(
            monkeypatch,
            "log",
            lambda args: subprocess.CompletedProcess(args, 0, raw, b""),
        )
        base = ["--project-root", str(repo), "--surface", "r"]

        with pytest.raises(GitError):
            classify(repo, "r")
        assert run(base) == 1
        assert run([*base, "--apply"]) == 1
        assert run([*base, "--apply", "--confirm-risky", "r/a.txt"]) == 1
        assert a.exists() and b.exists()


class TestPartialApplicationIsDocumented:
    """Round 3: the 'abort before deleting anything' guarantee is for
    CLASSIFICATION only; while applying, files are removed one by one."""

    def test_second_candidate_failing_in_git_is_refused_after_the_first_went(
        self,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        first = _write(repo, "r/a.txt", b"a")
        second = _write(repo, "r/b.txt", b"b")
        _commit_all(repo)
        real = prune_mod._run_git
        calls = {"hash": 0}

        def fail_on_fourth_hash(root: Path, args: list[str]) -> object:
            if args[0] == "hash-object":
                calls["hash"] += 1
                # 1-2: classify a, b. 3: re-verify a. 4: re-verify b -> fails.
                if calls["hash"] == 4:
                    return subprocess.CompletedProcess(args, 128, b"", b"boom")
            return real(root, args)

        monkeypatch.setattr(prune_mod, "_run_git", fail_on_fourth_hash)
        rc = run(["--project-root", str(repo), "--surface", "r", "--apply"])

        assert rc == 1
        assert not first.exists(), "deleted before the failure (partial deletion)"
        assert second.exists(), "refused, not deleted"
        err = capsys.readouterr().err
        assert "Refused: r/b.txt (cannot verify content (git failed))" in err
        assert calls["hash"] == 4
