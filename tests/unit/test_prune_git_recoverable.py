"""WOT-2026-049b: git-recoverable artifact classification and pruning.

Every test is hermetic: it builds its OWN git repo in tmp_path with controlled
tracked / untracked files under the surface, so nothing depends on the live
repo's orchestrator_pipeline/reports/ or any real artefacts.

Contract under test:
- SAFE = file ever appears in ``git log --all --name-only -- <surface>``.
- RISKY = file never appears in that git log output.
- --dry-run lists both, deletes nothing, exits 0.
- --apply without --confirm-risky deletes ONLY safe files, exits 0.
- --apply --confirm-risky PATH... deletes safe + named risky, exits 0.
- --confirm-risky mismatch (path not in RISKY of THIS run): fail-closed,
  nothing deleted, exit 2, clear stderr.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


# Motor root importable (tests/unit -> parents[2]).
_MOTOR_ROOT = Path(__file__).resolve().parents[2]
if str(_MOTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_MOTOR_ROOT))

from scripts.prune_git_recoverable import (  # noqa: E402
    classify,
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
        file with the SAME name created without track. Should be SAFE because
        git log --all finds the historical commit, even though the working
        tree current file is not tracked."""
        # Step 1: create, add, commit.
        _create_file(git_repo, "orchestrator_pipeline/reports/history.md")
        _git_add_and_commit(git_repo, ["orchestrator_pipeline/reports/history.md"])

        # Step 2: git rm + commit (remove from index and history).
        _git_rm_and_commit(git_repo, ["orchestrator_pipeline/reports/history.md"])

        # Step 3: recreate a file with the same name (untracked).
        _create_file(
            git_repo, "orchestrator_pipeline/reports/history.md", content="new"
        )

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
        SAFE solely because git log --all lists it.

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
        """Cross-branch blocker: a file SAFE because it appears in git log
        --all from another branch (not in the current branch HEAD/index)
        must NOT be deleted when --confirm-risky has a mismatch.

        This is the exact scenario from the BLOCKER report:
        - Create a file on 'side' branch (so git log --all finds it).
        - Checkout main, create the same file on disk (untracked on main).
        - Classify finds it SAFE (git log --all sees it on side).
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
            ["git", "checkout", "-q", "main"],
            cwd=str(side_repo),
            capture_output=True,
            check=True,
            text=True,
        )
        reports_dir.mkdir(parents=True, exist_ok=True)
        side_file.write_text("side content copy on main disk only", encoding="utf-8")

        # Verify: file exists on disk, classified SAFE by git log --all.
        cls = classify(side_repo, "orchestrator_pipeline/reports")
        assert "orchestrator_pipeline/reports/side_only.md" in cls.safe, (
            "File must be SAFE (appears in side branch via git log --all)"
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
        assert (
            side_file.read_text(encoding="utf-8")
            == "side content copy on main disk only"
        ), "side_only.md content must be byte-identical after mismatch"
