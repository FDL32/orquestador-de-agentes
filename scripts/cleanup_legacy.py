#!/usr/bin/env python3
"""
Cleanup legacy files after agent system upgrade.

Identifies and removes old system files that are superseded by the new version.
Useful after running upgrade.py to clean up deprecated code and configuration.

Usage:
  python scripts/cleanup_legacy.py /path/to/project --dry-run
  python scripts/cleanup_legacy.py /path/to/project --confirm
  python scripts/cleanup_legacy.py /path/to/project --list-only
"""

import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import ClassVar


class LegacyCleanup:
    """Identify and remove legacy files from older agent system versions."""

    # Old script names that were renamed
    OLD_SCRIPT_NAMES: ClassVar[list[str]] = [
        "detect_agent_system_version.py",
        "test_goose_realworld.py",
    ]

    # Debug/temporary files from execution
    DEBUG_FILES: ClassVar[list[str]] = [
        "debug_output.txt",
        "output.txt",
        "temp_output.txt",
        "*.log",
    ]

    # Old configuration files
    OLD_CONFIG_FILES: ClassVar[list[str]] = [
        "UPGRADE_GUIDE.md",
    ]

    # Directories that should be cleaned
    LEGACY_DIRS: ClassVar[list[str]] = [
        ".ruff_cache",
        ".agent/legacy",
        "test_logs",
        ".agent/backups",
        "graphify-out/cache",
    ]
    EXCLUDED_PATH_MARKERS: ClassVar[list[str]] = [
        "/.venv/",
        "/node_modules/",
        "/.git/",
        "/tests/sandbox/",
    ]

    def __init__(self, project_dir: str):
        self.project_path = Path(project_dir).resolve()
        self.scripts_dir = self.project_path / "scripts"
        self.agent_dir = self.project_path / ".agent"
        self.session_dir = self.project_path / ".session"
        self.archive_dir = self.session_dir / "archive"
        self.cleanup_log = self.session_dir / "cleanup_log.md"

        if not self.project_path.exists():
            raise FileNotFoundError(f"Project directory not found: {project_dir}")

    def find_legacy_files(self) -> dict[str, list[str]]:
        """Find all legacy files in the project."""
        legacy = {
            "old_scripts": [],
            "debug_files": [],
            "archive_docs": [],
            "pycache": [],
            "other": [],
        }

        legacy["old_scripts"].extend(self._find_old_scripts())
        legacy["debug_files"].extend(self._find_debug_files())
        legacy["archive_docs"].extend(self._find_archive_docs())
        legacy["pycache"].extend(self._find_pycache_dirs())
        legacy["other"].extend(self._find_legacy_dirs())

        return legacy

    def _find_old_scripts(self) -> list[str]:
        matches: list[str] = []
        for old_name in self.OLD_SCRIPT_NAMES:
            path = self.scripts_dir / old_name
            if path.exists():
                matches.append(str(path))
        return matches

    def _find_debug_files(self) -> list[str]:
        return [
            str(file)
            for pattern in self.DEBUG_FILES
            for file in self.project_path.glob(f"**/{pattern}")
            if file.is_file() and not self._is_excluded_path(file)
        ]

    def _find_archive_docs(self) -> list[str]:
        matches: list[str] = []
        for old_file in self.OLD_CONFIG_FILES:
            path = self.project_path / old_file
            if path.exists():
                matches.append(str(path))
        return matches

    def _find_pycache_dirs(self) -> list[str]:
        return [
            str(pycache)
            for pycache in self.project_path.glob("**/__pycache__")
            if pycache.is_dir() and not self._is_excluded_path(pycache)
        ]

    def _find_legacy_dirs(self) -> list[str]:
        matches: list[str] = []
        for dir_name in self.LEGACY_DIRS:
            path = self.project_path / dir_name
            if path.exists() and path.is_dir() and not self._is_excluded_path(path):
                matches.append(str(path))
        return matches

    def run(self, mode: str = "dry-run") -> int:
        """Execute cleanup in specified mode."""
        legacy = self.find_legacy_files()

        if mode == "list-only":
            self.list_only(legacy)
            return 0
        elif mode == "dry-run":
            self.dry_run(legacy)
            return 0
        elif mode == "confirm":
            _removed, failed = self.confirm_removal(legacy)
            return 0 if failed == 0 else 1
        return 2

    def list_only(self, legacy):
        print(f"\nLegacy files found in {self.project_path}:")
        total = sum(len(v) for v in legacy.values())
        print(f"Total: {total} items\n")

    def dry_run(self, legacy):
        print("\n[DRY RUN] Legacy cleanup would remove:")
        for category, files in legacy.items():
            if files:
                label = "archive_docs" if category == "archive_docs" else category
                print(f"\n{label}:")
                for f in files:
                    print(f"  - {f}")

    def confirm_removal(self, legacy):
        removed = 0
        failed = 0
        removed_items: list[str] = []
        archived_items: list[str] = []
        failed_items: list[str] = []

        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)

        for path_str in (
            legacy["old_scripts"]
            + legacy["debug_files"]
            + legacy["pycache"]
            + legacy["other"]
        ):
            path = Path(path_str)
            if self._is_within_project(path):
                if self._remove_path(path):
                    removed += 1
                    removed_items.append(path_str)
                else:
                    failed += 1
                    failed_items.append(path_str)

        for path_str in legacy["archive_docs"]:
            path = Path(path_str)
            if self._is_within_project(path):
                archived_path = self.archive_dir / path.name
                if self._archive_path(path, archived_path):
                    removed += 1
                    archived_items.append(f"{path_str} -> {archived_path}")
                else:
                    failed += 1
                    failed_items.append(path_str)

        self._write_cleanup_log(removed_items, archived_items, failed_items)
        return removed, failed

    def _is_within_project(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
        except OSError:
            return False
        return resolved == self.project_path or self.project_path in resolved.parents

    def _is_excluded_path(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
        except OSError:
            return True
        normalized = f"/{resolved.as_posix().lower()}/"
        return any(marker in normalized for marker in self.EXCLUDED_PATH_MARKERS)

    def _remove_path(self, path: Path) -> bool:
        try:
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
            return True
        except OSError as exc:
            print(f"Error removing {path}: {exc}", file=sys.stderr)
            return False

    def _archive_path(self, source: Path, destination: Path) -> bool:
        try:
            if destination.exists():
                if destination.is_dir():
                    shutil.rmtree(destination)
                else:
                    destination.unlink()
            shutil.move(str(source), str(destination))
            return True
        except OSError as exc:
            print(f"Error archiving {source} -> {destination}: {exc}", file=sys.stderr)
            return False

    def _write_cleanup_log(
        self,
        removed_items: list[str],
        archived_items: list[str],
        failed_items: list[str],
    ) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        lines = [
            "# Cleanup Log",
            "",
            f"- Timestamp: {timestamp}",
            f"- Project: {self.project_path}",
            f"- Removed items: {len(removed_items)}",
            f"- Archived items: {len(archived_items)}",
            f"- Failed items: {len(failed_items)}",
            "",
            "## Removed",
        ]
        lines.extend(f"- {item}" for item in removed_items or ["(none)"])
        lines.extend(["", "## Archived"])
        lines.extend(f"- {item}" for item in archived_items or ["(none)"])
        lines.extend(["", "## Failed"])
        lines.extend(f"- {item}" for item in failed_items or ["(none)"])
        lines.append("")
        self.cleanup_log.write_text("\n".join(lines), encoding="utf-8")


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir", nargs="?", default=".")
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--confirm", action="store_true", default=False)
    parser.add_argument("--list-only", action="store_true", default=False)

    args = parser.parse_args()

    try:
        cleanup = LegacyCleanup(args.project_dir)
        mode = (
            "confirm"
            if args.confirm
            else ("list-only" if args.list_only else "dry-run")
        )
        return cleanup.run(mode)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
