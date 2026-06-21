#!/usr/bin/env python3
"""
Project paths resolution helper.

Centralized logic for resolving canonical project root and agent directory.
Detects path drift and ensures consistent path handling across scripts.
"""

import os
from pathlib import Path


# WOT-2026-013d: directories pruned before descending in the robust .agent walk.
# Mirrors the volatile/non-product subtrees that must never be entered, so a
# concurrently-deleted subdir (e.g. tests/sandbox/test_runtime/session_<PID>)
# cannot raise FileNotFoundError mid-traversal.
_WALK_PRUNE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "node_modules",
    "build",
    "dist",
    "backups",
}
_WALK_PRUNE_REL_PREFIXES = (
    "tests/sandbox/test_runtime",
    ".agent/runtime/tmp",
)


def _find_agent_dirs(project_root: Path) -> list[Path]:
    """WOT-2026-013d: robustly find ``.agent`` dirs under ``project_root``.

    Replaces ``project_root.rglob(".agent")`` (which raises FileNotFoundError /
    PermissionError when a subtree vanishes mid-scan under concurrent xdist
    workers). Uses ``os.walk`` with an error-swallowing callback and prunes
    volatile/non-product subtrees before descending. ``backups`` is excluded to
    match the prior ``"backups" not in d.parts`` filter at the call site.
    """
    found: list[Path] = []
    root_str = str(project_root)
    for dirpath, dirnames, _files in os.walk(root_str, onerror=lambda _e: None):
        current = Path(dirpath)
        kept = []
        for d in dirnames:
            if d in _WALK_PRUNE_DIRS:
                continue
            try:
                rel = (current / d).relative_to(project_root).as_posix()
            except ValueError:
                rel = ""
            if rel and rel.startswith(_WALK_PRUNE_REL_PREFIXES):
                continue
            kept.append(d)
        if ".agent" in kept:
            found.append(current / ".agent")
            # No need to descend into an .agent we already recorded.
            kept = [d for d in kept if d != ".agent"]
        dirnames[:] = kept
    return found


class ProjectPathsResolver:
    """Resolve canonical project paths and detect drift."""

    CANONICAL_AGENT_MARKERS = (
        "agent_controller.py",
        "project_manifest.toml",
        ".version_manifest.json",
    )

    def __init__(self, start_dir: str | Path):
        self.start_path = Path(start_dir).resolve()
        if not self.start_path.exists():
            raise FileNotFoundError(f"Start directory not found: {start_dir}")

    def resolve_paths(self) -> dict[str, str | bool]:
        """
        Resolve canonical project root and agent directory.

        Returns dict with:
        - project_root: str | None
        - agent_dir: str | None
        - drift_detected: bool
        - drift_type: str | None ('multiple_agent_dirs', 'agent_not_at_root', 'none')
        - message: str

        Drift is detected if:
        - Multiple .agent/ directories found in the tree
        - .agent/ not at project root (though we still resolve it)
        """
        # Find project root by searching upwards for .agent
        project_root = self._find_project_root(self.start_path)
        if not project_root:
            return {
                "project_root": None,
                "agent_dir": None,
                "drift_detected": False,
                "drift_type": None,
                "message": "No .agent directory found",
            }

        agent_dir = project_root / ".agent"

        # Check for drift: multiple operational .agent roots in the tree.
        # Sandbox fixtures are ignored because they are intentionally duplicated
        # for tests and must not block the canonical runtime root.
        # WOT-2026-013d: robust walk instead of bare rglob(".agent"), which raised
        # FileNotFoundError when a sandbox subtree vanished mid-scan under xdist.
        all_agent_dirs = [
            d
            for d in _find_agent_dirs(project_root)
            if d.is_dir() and "backups" not in d.parts
        ]

        drift_detected = False
        drift_type = "none"

        if len(all_agent_dirs) > 1:
            drift_detected = True
            drift_type = "multiple_agent_dirs"
            project_root = None
            agent_dir = None

        message = (
            "Paths resolved successfully"
            if not drift_detected
            else f"Multiple .agent directories found: {[str(d) for d in all_agent_dirs]}"
        )

        return {
            "project_root": str(project_root) if project_root else None,
            "agent_dir": str(agent_dir) if agent_dir else None,
            "drift_detected": drift_detected,
            "drift_type": drift_type,
            "message": message,
        }

    def _find_project_root(self, start_path: Path) -> Path | None:
        """Find the nearest project root with a canonical .agent directory.

        Resolution order:
        1. Prefer the closest ancestor of ``start_path`` that already contains a
           canonical ``.agent`` directory. This keeps local test fixtures and
           nested projects self-contained.

        If no ancestor matches, return ``None``. Callers that need the canonical
        runtime root should provide it explicitly instead of inferring it from a
        parent workspace. This keeps the resolver predictable for tests.
        """
        current = start_path
        sandbox_boundaries = {"factory", "pytest", "tempfile"}

        # First pass: nearest ancestor containing a canonical .agent directory.
        while current != current.parent:
            agent_dir = current / ".agent"
            if (
                agent_dir.exists()
                and agent_dir.is_dir()
                and self._has_agent_markers(agent_dir)
            ):
                return current
            if current.name in sandbox_boundaries:
                break
            current = current.parent

        return None

    def _has_agent_markers(self, agent_dir: Path) -> bool:
        """Check whether the agent directory exposes canonical runtime markers.

        Accepts .agent/ if it contains at least one canonical marker.
        Prevents empty or truly partial fixtures, but allows legacy structures.
        """
        return any(
            (agent_dir / marker).exists() for marker in self.CANONICAL_AGENT_MARKERS
        )

    def get_project_root(self) -> Path | None:
        """Get canonical project root path."""
        result = self.resolve_paths()
        if result["project_root"]:
            return Path(result["project_root"])
        return None

    def get_agent_dir(self) -> Path | None:
        """Get canonical agent directory path."""
        result = self.resolve_paths()
        if result["agent_dir"]:
            return Path(result["agent_dir"])
        return None

    def has_drift(self) -> bool:
        """Check if path drift is detected."""
        return self.resolve_paths()["drift_detected"]

    def get_drift_info(self) -> dict:
        """Get drift information."""
        result = self.resolve_paths()
        return {
            "drift_detected": result["drift_detected"],
            "drift_type": result["drift_type"],
            "message": result["message"],
        }
