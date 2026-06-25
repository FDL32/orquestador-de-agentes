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

    # Forbidden versioned/history surfaces, populated with OLD entries.
    for rel in (
        "runtime/events/archive",
        "audits/system_health",
        "collaboration/archive",
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
            {"keep_reviews": 0, "keep_packets": 0, "keep_observation_baks": 0},
        )
        all_candidates = [p for paths in selection.values() for p in paths]

        # Exactly the three surfaces are represented.
        assert set(selection) == {"reviews", "review_packets", "observation_baks"}
        # 5 per surface, nothing more (decoys excluded).
        assert len(selection["reviews"]) == 5
        assert len(selection["review_packets"]) == 5
        assert len(selection["observation_baks"]) == 5

        # No non-bak memory file is ever a candidate.
        for p in selection["observation_baks"]:
            assert p.name.startswith("observations.jsonl.bak.")
        cand_names = _names(all_candidates)
        assert "observations.jsonl" not in cand_names
        assert "MEMORY.md" not in cand_names

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
            workspace / ".agent" / "collaboration" / "archive",
            workspace / ".agent" / "collaboration" / "_archive",
        ]
        for cand in all_candidates:
            resolved_parents = set(cand.resolve().parents)
            for root in forbidden_roots:
                assert root.resolve() not in resolved_parents, (
                    f"SPILLOVER: {cand} is under forbidden {root}"
                )
            assert cand.resolve() not in {r.resolve() for r in forbidden_roots}

        # And an apply with max aggression must leave forbidden surfaces intact.
        forbidden_before = _forbidden_snapshot(workspace)
        prune(selection, apply=True)
        assert _forbidden_snapshot(workspace) == forbidden_before

    def test_keep_negative_is_rejected(self, workspace: Path) -> None:
        """A negative keep-count is a programming error, not a silent delete-all."""
        with pytest.raises(ValueError):
            select_candidates(workspace, _surface("reviews"), keep=-1)


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
    """Sorted relative paths of everything under each forbidden root."""
    snap: dict[str, list[str]] = {}
    for rel in (
        "runtime/events/archive",
        "audits/system_health",
        "collaboration/archive",
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
