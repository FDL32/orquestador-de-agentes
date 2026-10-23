from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from scripts import project_scanner
from scripts.install_agent_system import (
    DESTINATION_ONLY_PROJECTION_ENTRIES,
    MEMORY_ARCHIVE_REOPEN_LINES,
    PROJECTIONS_GITIGNORE_ENTRIES,
    PROJECTIONS_GITIGNORE_MARKER,
    ensure_destination_projections_ignored,
)


# Any absolute local path shape (drive letter or unix home) is a leak in a
# regenerable projection (WOT-2026-016p / N7).
_ABS_PATH_RE = re.compile(r"[A-Za-z]:[\\/]|/home/")


def _make_destino(tmp_path: Path) -> Path:
    root = tmp_path / "destino_demo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("print('hola')\n", encoding="utf-8")
    return root


class TestEnsureProjectionsIgnored:
    def test_adds_all_entries_when_gitignore_missing(self, tmp_path: Path) -> None:
        root = _make_destino(tmp_path)
        added = ensure_destination_projections_ignored(root)
        # WOT-2026-020t: a destination (default, motor_root=None) also gets the
        # destination-only collaboration entry.
        # WOT-2026-059f: also returns the memory archive reopen lines.
        expected = (
            set(PROJECTIONS_GITIGNORE_ENTRIES)
            | set(DESTINATION_ONLY_PROJECTION_ENTRIES)
            | set(MEMORY_ARCHIVE_REOPEN_LINES)
        )
        assert set(added) == expected
        text = (root / ".gitignore").read_text(encoding="utf-8")
        assert PROJECTIONS_GITIGNORE_MARKER in text
        for entry in expected:
            assert entry in text.splitlines()

    def test_motor_root_noop_for_motor(self, tmp_path: Path) -> None:
        """WOT-2026-020t: the motor versions .agent/collaboration/ for dogfooding;
        when motor_root resolves to project_root the guard is a no-op."""
        root = _make_destino(tmp_path)
        added = ensure_destination_projections_ignored(root, motor_root=root)
        assert added == []
        assert not (root / ".gitignore").exists()

    def test_motor_root_adds_collaboration_files_for_destination(
        self, tmp_path: Path
    ) -> None:
        """WOT-2026-059f: a real destination (motor_root != project_root) gets
        the 6 explicit collaboration files gitignored (not the blanket dir);
        motor_root is explicit.

        HARDCODED, not derived from DESTINATION_ONLY_PROJECTION_ENTRIES: a
        version of that constant reads its own value, so it is a tautology
        that passes under ANY content of the constant, including a reverted
        blanket ".agent/collaboration/" -- measured by the Manager via
        mutation-verify (restoring the pre-fix blanket entry left this test,
        and the other 20 in the two affected modules, all green). The literal
        list below is the actual DoD of WOT-2026-059f and must NOT be
        re-derived from the constant under test."""
        root = _make_destino(tmp_path)
        motor_root = tmp_path / "motor"
        motor_root.mkdir()
        added = ensure_destination_projections_ignored(root, motor_root=motor_root)
        expected_files = {
            ".agent/collaboration/work_plan.md",
            ".agent/collaboration/STATE.md",
            ".agent/collaboration/TURN.md",
            ".agent/collaboration/execution_log.md",
            ".agent/collaboration/notifications.md",
            ".agent/collaboration/review_queue.md",
        }
        assert expected_files.issubset(set(added))
        assert ".agent/collaboration/" not in added, (
            "la entrada blanket NO debe reaparecer: WOT-2026-059f la retiro "
            "porque oculta STRATEGY_WOT-*.md/AUDIT_WOT-*.md, que son "
            "canonicos y deben poder versionarse"
        )
        text = (root / ".gitignore").read_text(encoding="utf-8")
        lines = text.splitlines()
        for entry in expected_files:
            assert entry in lines
        assert ".agent/collaboration/" not in lines

    def test_idempotent_no_duplicates_on_rerun(self, tmp_path: Path) -> None:
        root = _make_destino(tmp_path)
        ensure_destination_projections_ignored(root)
        again = ensure_destination_projections_ignored(root)
        assert again == []
        lines = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
        for entry in (
            PROJECTIONS_GITIGNORE_ENTRIES + DESTINATION_ONLY_PROJECTION_ENTRIES
        ):
            assert lines.count(entry) == 1

    def test_respects_existing_user_entries(self, tmp_path: Path) -> None:
        root = _make_destino(tmp_path)
        (root / ".gitignore").write_text(".venv/\n.agent/runtime/\n", encoding="utf-8")
        added = ensure_destination_projections_ignored(root)
        # runtime ya estaba: no se duplica; el resto se anade
        assert ".agent/runtime/" not in added
        lines = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
        assert lines.count(".agent/runtime/") == 1
        assert ".venv/" in lines  # lo del usuario se conserva

    def test_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        root = _make_destino(tmp_path)
        added = ensure_destination_projections_ignored(root, dry_run=True)
        assert added  # detecta faltantes
        assert not (root / ".gitignore").exists()


class TestGeneratorsPiiSafe:
    def test_project_map_has_no_absolute_paths(self, tmp_path: Path) -> None:
        """DoD #3 + BARRERA: con el comportamiento antiguo (str(project_root))
        este assert falla; con el fix (folder name) pasa."""
        root = _make_destino(tmp_path)
        project_map = project_scanner.scan_project(root)
        assert project_map["project_root"] == root.name
        blob = json.dumps(project_map)
        leaks = _ABS_PATH_RE.findall(blob)
        assert not leaks, f"rutas absolutas en project-map: {leaks[:3]}"

    def test_destination_map_identity_has_no_absolute_paths(
        self, tmp_path: Path
    ) -> None:
        from scripts import destination_context as dc

        root = _make_destino(tmp_path)
        (root / ".agent" / "config").mkdir(parents=True)
        (root / ".agent" / "config" / "motor_destination_link.json").write_text(
            json.dumps(
                {
                    "motor_root": str(tmp_path / "motor_falso"),
                    "motor_version": "9.9",
                }
            ),
            encoding="utf-8",
        )
        motor_link = dc.resolve_motor_link(root)
        assert motor_link is not None
        # La seccion de identidad se construye con nombres, no rutas
        assert Path(str(motor_link.get("motor_root"))).name == "motor_falso"


class TestMemoryArchiveReopenLines:
    """WOT-2026-059f: MEMORY_ARCHIVE_REOPEN_LINES must make the memory archive
    visible to git while keeping .agent/runtime/ and .agent/runtime/memory/
    (non-archive) hidden. Uses real git check-ignore on a scratch repo."""

    @staticmethod
    def _git_check_ignore(repo: Path, path: str) -> bool:
        """Return True if path is ignored, False if not."""
        result = subprocess.run(
            ["git", "-C", str(repo), "check-ignore", path],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0

    def _init_git_repo(self, repo: Path) -> None:
        subprocess.run(
            ["git", "-C", str(repo), "init"],
            capture_output=True,
            check=True,
            text=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.email", "test@example.com"],
            capture_output=True,
            check=True,
            text=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.name", "Test"],
            capture_output=True,
            check=True,
            text=True,
        )

    def test_memory_archive_not_ignored(self, tmp_path: Path) -> None:
        """A file inside .agent/runtime/memory/archive/ must NOT be ignored
        after ensure_destination_projections_ignored runs."""
        root = _make_destino(tmp_path)
        self._init_git_repo(root)
        # Touch a file so git sees the path (git check-ignore works on
        # working tree files, not just the index).
        archive_dir = root / ".agent" / "runtime" / "memory" / "archive"
        archive_dir.mkdir(parents=True)
        (archive_dir / "observations.2026-11.jsonl").write_text(
            "data", encoding="utf-8"
        )

        ensure_destination_projections_ignored(root)

        assert not self._git_check_ignore(
            root, ".agent/runtime/memory/archive/observations.2026-11.jsonl"
        ), ".agent/runtime/memory/archive/ MUST be visible (not ignored)"

    def test_runtime_memory_buffer_still_ignored(self, tmp_path: Path) -> None:
        """A file in .agent/runtime/memory/ (buffer, not inside archive/) MUST
        remain ignored."""
        root = _make_destino(tmp_path)
        self._init_git_repo(root)
        (root / ".agent" / "runtime" / "memory").mkdir(parents=True)
        (root / ".agent" / "runtime" / "memory" / "observations.jsonl").write_text(
            "data", encoding="utf-8"
        )

        ensure_destination_projections_ignored(root)

        assert self._git_check_ignore(
            root, ".agent/runtime/memory/observations.jsonl"
        ), ".agent/runtime/memory/ (buffer) must remain ignored"

    def test_runtime_ensemble_scorecard_still_ignored(self, tmp_path: Path) -> None:
        """A file in .agent/runtime/ensemble/ MUST remain ignored."""
        root = _make_destino(tmp_path)
        self._init_git_repo(root)
        (root / ".agent" / "runtime" / "ensemble").mkdir(parents=True)
        (root / ".agent" / "runtime" / "ensemble" / "scorecard.jsonl").write_text(
            "data", encoding="utf-8"
        )

        ensure_destination_projections_ignored(root)

        assert self._git_check_ignore(
            root, ".agent/runtime/ensemble/scorecard.jsonl"
        ), ".agent/runtime/ensemble/ must remain ignored"

    def test_reopen_lines_are_present_in_gitignore(self, tmp_path: Path) -> None:
        """The reopen lines must actually be written into .gitignore."""
        root = _make_destino(tmp_path)
        ensure_destination_projections_ignored(root)

        text = (root / ".gitignore").read_text(encoding="utf-8")
        for line in MEMORY_ARCHIVE_REOPEN_LINES:
            assert line in text.splitlines(), (
                f"Missing reopen line in .gitignore: {line}"
            )
