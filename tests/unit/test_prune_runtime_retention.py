"""WOT-2026-013l: barriers for the opt-in runtime retention utility.

Every test is hermetic: it builds its OWN tmp project-root with the three target
surfaces (and, for the safety test, the forbidden versioned-history surfaces),
so nothing depends on the live dogfooding workspace.

Contract under test:
- The selector considers ONLY reviews/, review_packets/ and
  observations.jsonl.bak.* — never versioned/history surfaces.
- Retention keeps the newest N per surface (deterministic by mtime then name).
- --dry-run never deletes; --apply removes only the selected candidates.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


# Motor root importable (tests/unit -> parents[2]).
_MOTOR_ROOT = Path(__file__).resolve().parents[2]
if str(_MOTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_MOTOR_ROOT))

from scripts.prune_runtime_retention import (  # noqa: E402
    SURFACES,
    prune,
    run,
    select_all,
    select_candidates,
)


# --- Hermetic workspace fixture --------------------------------------------


def _touch_with_mtime(path: Path, mtime: float, *, is_dir: bool = False) -> Path:
    """Create a file or dir and stamp a deterministic mtime."""
    if is_dir:
        path.mkdir(parents=True, exist_ok=True)
        # A dir's mtime is what we stamp; put a marker file inside so rmtree has work.
        (path / "decision.json").write_text("{}", encoding="utf-8")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return path


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Build a hermetic project-root with all three target surfaces populated and
    every forbidden history surface populated with OLD entries (to prove they are
    never selected)."""
    agent = tmp_path / ".agent"
    base = time.time()

    # reviews/: 5 ticket dirs, ascending mtime (older -> newer).
    reviews = agent / "runtime" / "reviews"
    for i in range(5):
        _touch_with_mtime(reviews / f"WT-2026-{100 + i}", base + i, is_dir=True)

    # review_packets/: 5 files.
    packets = agent / "runtime" / "review_packets"
    for i in range(5):
        _touch_with_mtime(packets / f"WT-2026-{100 + i}_attempt-1.md", base + i)

    # observations.jsonl.bak.*: 5 files + non-bak files that must be ignored.
    memory = agent / "runtime" / "memory"
    for i in range(5):
        _touch_with_mtime(memory / f"observations.jsonl.bak.2026010{i}120000", base + i)
    # Decoys in the same dir that must NEVER be candidates.
    _touch_with_mtime(memory / "observations.jsonl", base - 100)
    _touch_with_mtime(memory / "MEMORY.md", base - 100)
    _touch_with_mtime(memory / "archive" / "old_snapshot.md", base - 100, is_dir=False)

    # collaboration/archive/: 5 prunable notifications_<ts>.md + decoys that must
    # NEVER be candidates (WOT-2026-013k: only the notifications_ family is local).
    collab_archive = agent / "collaboration" / "archive"
    for i in range(5):
        _touch_with_mtime(
            collab_archive / f"notifications_2026010{i}_120000.md", base + i
        )
    # Decoys in collaboration/archive/ that share the dir but are NOT the family.
    _touch_with_mtime(collab_archive / "review_queue_2026-06-11.md", base - 100)
    _touch_with_mtime(collab_archive / "manager_feedback.md", base - 100)
    _touch_with_mtime(collab_archive / "recovered_work_plan.md", base - 100)
    _touch_with_mtime(collab_archive / "ancient.md", base - 1000)

    # Forbidden versioned/history surfaces, populated with OLD entries. Note
    # collaboration/archive/ is intentionally NOT here: it is reachable ONLY for
    # the notifications_ family; its non-notification files are decoys above.
    for rel in (
        "runtime/events/archive",
        "audits/system_health",
        "collaboration/_archive/plan_audit",
    ):
        _touch_with_mtime(agent / rel / "ancient.md", base - 1000)

    return tmp_path


def _names(paths: list[Path]) -> set[str]:
    return {p.name for p in paths}


# ═══════════════════════════════════════════════════════════════════════════
# TestRuntimeRetentionSelection
# ═══════════════════════════════════════════════════════════════════════════


class TestRuntimeRetentionSelection:
    def test_collects_only_gitignored_runtime_targets(self, workspace: Path) -> None:
        """The selector considers ONLY reviews / review_packets / bak files, and
        never the memory decoys or any versioned-history surface."""
        # Keep 0 everywhere so EVERY prunable entry surfaces as a candidate.
        selection = select_all(
            workspace,
            {
                "keep_reviews": 0,
                "keep_packets": 0,
                "keep_observation_baks": 0,
                "keep_notification_archives": 0,
            },
        )
        all_candidates = [p for paths in selection.values() for p in paths]

        # Exactly the four surfaces are represented (WOT-2026-013k added the 4th).
        assert set(selection) == {
            "reviews",
            "review_packets",
            "observation_baks",
            "notification_archives",
        }
        # 5 per surface, nothing more (decoys excluded).
        assert len(selection["reviews"]) == 5
        assert len(selection["review_packets"]) == 5
        assert len(selection["observation_baks"]) == 5
        assert len(selection["notification_archives"]) == 5

        # No non-bak memory file is ever a candidate.
        for p in selection["observation_baks"]:
            assert p.name.startswith("observations.jsonl.bak.")
        # Only the notifications_ family in collaboration/archive/ is a candidate.
        for p in selection["notification_archives"]:
            assert p.name.startswith("notifications_") and p.name.endswith(".md")
        cand_names = _names(all_candidates)
        assert "observations.jsonl" not in cand_names
        assert "MEMORY.md" not in cand_names
        # collaboration/archive/ decoys must never be candidates.
        assert "review_queue_2026-06-11.md" not in cand_names
        assert "manager_feedback.md" not in cand_names
        assert "recovered_work_plan.md" not in cand_names
        assert "ancient.md" not in cand_names

        # No candidate lives outside the three target roots.
        target_roots = [workspace / ".agent" / s.rel_root for s in SURFACES]
        for cand in all_candidates:
            assert any(
                root.resolve() in cand.resolve().parents for root in target_roots
            ), cand

    def test_keep_count_prunes_old_review_and_packet_entries(
        self, workspace: Path
    ) -> None:
        """Keeping N retains the N NEWEST; the rest (oldest) are the candidates,
        deterministically. Spillover or a broken order would change the set."""
        reviews_keep2 = select_candidates(workspace, _surface("reviews"), keep=2)
        packets_keep2 = select_candidates(workspace, _surface("review_packets"), keep=2)

        # 5 entries, keep 2 -> 3 oldest pruned.
        assert len(reviews_keep2) == 3
        assert len(packets_keep2) == 3
        # The kept (newest) ones are 103, 104; pruned are the 3 oldest (100-102).
        assert _names(reviews_keep2) == {"WT-2026-100", "WT-2026-101", "WT-2026-102"}
        assert _names(packets_keep2) == {
            "WT-2026-100_attempt-1.md",
            "WT-2026-101_attempt-1.md",
            "WT-2026-102_attempt-1.md",
        }
        # Determinism: identical inputs -> identical selection.
        again = select_candidates(workspace, _surface("reviews"), keep=2)
        assert [p.name for p in reviews_keep2] == [p.name for p in again]

    def test_observation_backups_follow_the_same_retention_policy(
        self, workspace: Path
    ) -> None:
        """bak files use the SAME keep-newest-N policy, not a separate opaque one."""
        baks_keep2 = select_candidates(workspace, _surface("observation_baks"), keep=2)
        assert len(baks_keep2) == 3
        for p in baks_keep2:
            assert p.name.startswith("observations.jsonl.bak.")
        # Keeping all -> nothing pruned; keeping more than present -> nothing.
        assert select_candidates(workspace, _surface("observation_baks"), keep=5) == []
        assert select_candidates(workspace, _surface("observation_baks"), keep=99) == []

    def test_review_directories_are_ranked_by_directory_mtime_not_nested_file_mtime(
        self, tmp_path: Path
    ) -> None:
        """Construct two review dirs where DIRECTORY mtime and newest-inner-file
        mtime DISAGREE, then prove the selector follows the DIRECTORY mtime.

        - dir_new_dir: newest DIRECTORY mtime, but holds an OLD inner file.
        - dir_old_dir: oldest DIRECTORY mtime, but holds a NEW inner file.
        With keep=1, ranking by DIRECTORY mtime keeps dir_new_dir and prunes
        dir_old_dir. If anyone silently switched to ranking by the newest nested
        file, the kept/pruned sets would flip and this test FAILS.
        """
        reviews = tmp_path / ".agent" / "runtime" / "reviews"
        reviews.mkdir(parents=True)
        base = time.time()

        dir_new_dir = reviews / "WT-2026-NEWDIR"
        dir_new_dir.mkdir()
        # OLD inner file, but we stamp the DIRECTORY as NEW (after creating the file).
        old_inner = dir_new_dir / "decision.json"
        old_inner.write_text("{}", encoding="utf-8")
        os.utime(old_inner, (base - 1000, base - 1000))
        os.utime(dir_new_dir, (base + 1000, base + 1000))

        dir_old_dir = reviews / "WT-2026-OLDDIR"
        dir_old_dir.mkdir()
        # NEW inner file, but we stamp the DIRECTORY as OLD.
        new_inner = dir_old_dir / "decision.json"
        new_inner.write_text("{}", encoding="utf-8")
        os.utime(new_inner, (base + 9999, base + 9999))
        os.utime(dir_old_dir, (base - 9999, base - 9999))

        pruned = select_candidates(tmp_path, _surface("reviews"), keep=1)
        pruned_names = {p.name for p in pruned}

        # By DIRECTORY mtime: NEWDIR (dir mtime newest) is kept, OLDDIR is pruned.
        assert pruned_names == {"WT-2026-OLDDIR"}, pruned_names
        # Guard against the per-nested-file interpretation: NEWDIR (old inner file)
        # must NOT be the one pruned.
        assert "WT-2026-NEWDIR" not in pruned_names

    def test_notification_archives_are_collected_as_gitignored_local_surface(
        self, workspace: Path
    ) -> None:
        """WOT-2026-013k: notifications_<ts>.md is the 4th selectable surface.

        Regression: without the surface, notification_archives would be absent
        from the selection (or empty), and this test FAILS.
        """
        selection = select_all(
            workspace,
            {
                "keep_reviews": 99,
                "keep_packets": 99,
                "keep_observation_baks": 99,
                "keep_notification_archives": 0,
            },
        )
        assert "notification_archives" in selection
        archives = selection["notification_archives"]
        assert len(archives) == 5
        for p in archives:
            assert p.name.startswith("notifications_") and p.name.endswith(".md")
            assert p.parent.name == "archive"

    def test_keep_count_prunes_only_old_notification_archives(
        self, workspace: Path
    ) -> None:
        """keep=N retains the N newest notifications_*.md and prunes only the rest,
        deterministically; no non-notification file is ever returned."""
        kept2 = select_candidates(workspace, _surface("notification_archives"), keep=2)
        # 5 archives, keep 2 -> 3 oldest pruned.
        assert len(kept2) == 3
        assert _names(kept2) == {
            "notifications_20260100_120000.md",
            "notifications_20260101_120000.md",
            "notifications_20260102_120000.md",
        }
        # keep >= count -> nothing pruned.
        assert (
            select_candidates(workspace, _surface("notification_archives"), keep=5)
            == []
        )
        assert (
            select_candidates(workspace, _surface("notification_archives"), keep=99)
            == []
        )
        # Determinism.
        again = select_candidates(workspace, _surface("notification_archives"), keep=2)
        assert [p.name for p in kept2] == [p.name for p in again]


# ═══════════════════════════════════════════════════════════════════════════
# TestRuntimeRetentionCLI
# ═══════════════════════════════════════════════════════════════════════════


class TestRuntimeRetentionCLI:
    def test_dry_run_reports_without_deleting(
        self, workspace: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """--dry-run prints candidates and touches NOTHING on disk."""
        before = _surface_snapshot(workspace)
        rc = run(
            [
                "--project-root",
                str(workspace),
                "--dry-run",
                "--keep-reviews",
                "2",
                "--keep-packets",
                "2",
                "--keep-observation-baks",
                "2",
            ]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "[DRY-RUN]" in out
        # Nothing deleted: the on-disk snapshot is identical.
        assert _surface_snapshot(workspace) == before

    def test_apply_deletes_only_selected_candidates(self, workspace: Path) -> None:
        """--apply removes exactly the selected (oldest) candidates and nothing in
        the forbidden surfaces."""
        forbidden_before = _forbidden_snapshot(workspace)
        rc = run(
            [
                "--project-root",
                str(workspace),
                "--apply",
                "--keep-reviews",
                "2",
                "--keep-packets",
                "2",
                "--keep-observation-baks",
                "2",
            ]
        )
        assert rc == 0
        # Each target surface keeps exactly 2 newest.
        reviews = workspace / ".agent" / "runtime" / "reviews"
        packets = workspace / ".agent" / "runtime" / "review_packets"
        memory = workspace / ".agent" / "runtime" / "memory"
        assert len(list(reviews.iterdir())) == 2
        assert len(list(packets.iterdir())) == 2
        baks = [
            p for p in memory.iterdir() if p.name.startswith("observations.jsonl.bak.")
        ]
        assert len(baks) == 2
        # Decoys survived.
        assert (memory / "observations.jsonl").exists()
        assert (memory / "MEMORY.md").exists()
        # Forbidden surfaces are byte-for-byte untouched.
        assert _forbidden_snapshot(workspace) == forbidden_before

    def test_requires_explicit_mode(self, workspace: Path) -> None:
        """Without --dry-run or --apply, argparse rejects the call (no deletion)."""
        before = _surface_snapshot(workspace)
        with pytest.raises(SystemExit) as exc:
            run(["--project-root", str(workspace), "--keep-reviews", "2"])
        assert exc.value.code != 0
        assert _surface_snapshot(workspace) == before


# ═══════════════════════════════════════════════════════════════════════════
# TestRuntimeRetentionSafety
# ═══════════════════════════════════════════════════════════════════════════


class TestRuntimeRetentionSafety:
    def test_versioned_history_surfaces_are_never_selected(
        self, workspace: Path
    ) -> None:
        """No matter how aggressive the keep-counts, the selector never reaches a
        versioned/history surface. With keep=0 everywhere (max aggression), the
        candidate set must contain ZERO paths under any forbidden root."""
        selection = select_all(
            workspace,
            {"keep_reviews": 0, "keep_packets": 0, "keep_observation_baks": 0},
        )
        all_candidates = [p for paths in selection.values() for p in paths]

        forbidden_roots = [
            workspace / ".agent" / "runtime" / "events" / "archive",
            workspace / ".agent" / "audits" / "system_health",
            workspace / ".agent" / "collaboration" / "_archive",
        ]
        for cand in all_candidates:
            resolved_parents = set(cand.resolve().parents)
            for root in forbidden_roots:
                assert root.resolve() not in resolved_parents, (
                    f"SPILLOVER: {cand} is under forbidden {root}"
                )
            assert cand.resolve() not in {r.resolve() for r in forbidden_roots}

        # And an apply with max aggression must leave fully-forbidden surfaces
        # intact AND must never touch the non-notification archive decoys.
        forbidden_before = _forbidden_snapshot(workspace)
        decoys_before = _archive_decoys_snapshot(workspace)
        prune(selection, apply=True)
        assert _forbidden_snapshot(workspace) == forbidden_before
        assert _archive_decoys_snapshot(workspace) == decoys_before

    def test_keep_negative_is_rejected(self, workspace: Path) -> None:
        """A negative keep-count is a programming error, not a silent delete-all."""
        with pytest.raises(ValueError):
            select_candidates(workspace, _surface("reviews"), keep=-1)

    def test_non_notification_collaboration_archive_files_are_never_selected(
        self, workspace: Path
    ) -> None:
        """WOT-2026-013k: only the notifications_<ts>.md family in
        collaboration/archive/ is prunable. review_queue_*.md, manager_feedback,
        recovered_*, ancient.md and any other archive file are NEVER candidates,
        even at maximum aggression (keep=0).

        Regression: if the surface filter widened to all archive files (or to a
        weaker pattern), these decoys would surface and this test FAILS.
        """
        archives = select_candidates(
            workspace, _surface("notification_archives"), keep=0
        )
        names = {p.name for p in archives}
        for decoy in (
            "review_queue_2026-06-11.md",
            "manager_feedback.md",
            "recovered_work_plan.md",
            "ancient.md",
        ):
            assert decoy not in names, f"{decoy} must never be selected"
        # Every selected entry IS a notifications_ family file.
        for p in archives:
            assert p.name.startswith("notifications_") and p.name.endswith(".md")
        # Apply at max aggression must leave the decoys on disk.
        decoys_before = _archive_decoys_snapshot(workspace)
        prune(
            {"notification_archives": archives},
            apply=True,
        )
        assert _archive_decoys_snapshot(workspace) == decoys_before


# --- helpers ---------------------------------------------------------------


def _surface(key: str):
    for s in SURFACES:
        if s.key == key:
            return s
    raise KeyError(key)


def _surface_snapshot(workspace: Path) -> dict[str, list[str]]:
    """Sorted names of the live entries in each target surface (for no-op checks)."""
    snap: dict[str, list[str]] = {}
    for s in SURFACES:
        root = workspace / ".agent" / s.rel_root
        if root.is_dir():
            snap[s.key] = sorted(p.name for p in root.iterdir())
        else:
            snap[s.key] = []
    return snap


def _forbidden_snapshot(workspace: Path) -> dict[str, list[str]]:
    """Sorted relative paths under each FULLY-forbidden root.

    WOT-2026-013k: collaboration/archive/ is intentionally NOT here, because its
    notifications_<ts>.md family is now a prunable surface. Its non-notification
    decoys are asserted intact separately (see _archive_decoys_snapshot).
    """
    snap: dict[str, list[str]] = {}
    for rel in (
        "runtime/events/archive",
        "audits/system_health",
        "collaboration/_archive",
    ):
        root = workspace / ".agent" / rel
        files = (
            sorted(str(p.relative_to(root)) for p in root.rglob("*"))
            if root.is_dir()
            else []
        )
        snap[rel] = files
    return snap


def _archive_decoys_snapshot(workspace: Path) -> list[str]:
    """Sorted names of the NON-notification files in collaboration/archive/ that
    must always survive (never selected by the notifications_ surface)."""
    root = workspace / ".agent" / "collaboration" / "archive"
    if not root.is_dir():
        return []
    return sorted(
        p.name
        for p in root.iterdir()
        if p.is_file()
        and not (p.name.startswith("notifications_") and p.name.endswith(".md"))
    )


def test_cli_subprocess_dry_run_is_hermetic(workspace: Path) -> None:
    """Smoke: the real CLI dispatch runs against a hermetic project-root and exits
    0 in dry-run without deleting (parity with the in-process tests)."""
    before = _surface_snapshot(workspace)
    result = subprocess.run(
        [
            sys.executable,
            str(_MOTOR_ROOT / "scripts" / "prune_runtime_retention.py"),
            "--project-root",
            str(workspace),
            "--dry-run",
            "--keep-reviews",
            "2",
            "--keep-packets",
            "2",
            "--keep-observation-baks",
            "2",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "[DRY-RUN]" in result.stdout
    assert _surface_snapshot(workspace) == before


# ═══════════════════════════════════════════════════════════════════════════
# WOT-2026-013v: reviews/ recency semantics are DIRECTORY mtime (made explicit)
# ═══════════════════════════════════════════════════════════════════════════


def _help_text() -> str:
    """The real --help output of the CLI (subprocess, no live workspace dep)."""
    result = subprocess.run(
        [
            sys.executable,
            str(_MOTOR_ROOT / "scripts" / "prune_runtime_retention.py"),
            "--help",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


class TestRuntimeRetentionDocs:
    """Nominal barriers locking the documented recency semantics of reviews/."""

    def test_help_makes_directory_mtime_semantics_explicit(self) -> None:
        """The --help must state that reviews/ is ranked by the DIRECTORY mtime.

        Regression barrier: if the help stops spelling out "DIRECTORY" mtime for
        reviews, the ambiguity returns and this test FAILS.
        """
        help_text = _help_text().lower()
        assert "directory" in help_text
        # The reviews keep-flag specifically must tie "review dirs" to dir mtime.
        assert "review dirs" in help_text
        # Must explicitly disclaim the per-nested-file reading.
        assert "newest file inside" in help_text

    def test_reviews_semantics_do_not_claim_last_logical_attempt(self) -> None:
        """The help/docstring must NOT (re)claim a 'last logical attempt' or
        per-inner-file semantics for reviews/.

        Regression barrier: any wording that sells reviews recency as the newest
        nested file / last logical attempt (without the explicit DIRECTORY
        qualifier) FAILS this test.
        """
        from scripts import prune_runtime_retention as mod

        sources = [_help_text(), mod.__doc__ or ""]
        for src in sources:
            low = src.lower()
            # If "last logical attempt" appears at all, it must appear only as the
            # NEGATED form ("not ... last logical attempt"), never as a claim.
            if "last logical attempt" in low:
                assert (
                    "not the most recent file inside" in low or "not the newest" in low
                ), src
            # A bare "newest file inside the dir" claim is only allowed when negated.
            if "newest file inside the dir" in low:
                assert "not the newest file inside the dir" in low, src
