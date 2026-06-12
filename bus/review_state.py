"""Adaptive review state: per-ticket persistence and git-delta computation.

Extracted from bus/review_bridge.py (monolith decomposition). This module
owns the adaptive review loop's state (WT-2026-196):

- ``manager_bridge_state.json`` read/merge/write per ticket
  (``adaptive_review`` section, shared with the bridge heartbeat).
- Git HEAD capture and changed-files-since-last-review computation.
- Repeated-blocker detection that drives diagnostic mode.

``ReviewBridge`` delegates to these functions through thin wrappers.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .blocker_signature import (
    compute_blocker_overlap,
    extract_signatures_from_feedback,
)


# ---------------------------------------------------------------------------
# Adaptive state persistence (manager_bridge_state.json)
# ---------------------------------------------------------------------------


def adaptive_state_path(project_root: Path) -> Path:
    """Return path to the manager bridge state (shared with bridge heartbeat)."""
    return project_root / ".agent" / "runtime" / "manager_bridge_state.json"


def load_adaptive_state(project_root: Path, ticket_id: str) -> dict:
    """Load adaptive review state for a given ticket.

    Reads manager_bridge_state.json and extracts adaptive_review[ticket_id].
    Returns a dict with keys matching the canonical schema, or empty dict.
    """
    path = adaptive_state_path(project_root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        adaptive = data.get("adaptive_review", {})
        return adaptive.get(ticket_id, {})
    except (json.JSONDecodeError, ValueError, TypeError, OSError):
        return {}


def save_adaptive_state(project_root: Path, ticket_id: str, state_update: dict) -> None:
    """Save/merge adaptive review state for a ticket.

    Reads the existing file, merges adaptive_review[ticket_id] with the
    update, and writes back (overwrite).

    Schema (WT-2026-196):
        adaptive_review: {
            "<ticket_id>": {
                "last_review_sequence": int,
                "last_git_head": str | null,
                "blocker_signatures": [str, ...],
                "repeated_blockers": [str, ...],
                "diagnostic_mode": bool,
                "changed_files_since_previous_review":
                    [str, ...] | {"status": "unknown", ...}
            }
        }
    """
    path = adaptive_state_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        data = {}
    if "adaptive_review" not in data:
        data["adaptive_review"] = {}
    existing = data["adaptive_review"].get(ticket_id, {})
    existing.update(state_update)
    data["adaptive_review"][ticket_id] = existing
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Git deltas between reviews
# ---------------------------------------------------------------------------


def get_current_git_head(git_root: Path) -> str | None:
    """Return current git HEAD SHA at ``git_root``, or None if unavailable."""
    try:
        git_bin = shutil.which("git") or "git"
        result = subprocess.run(  # noqa: S603
            [git_bin, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=git_root,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:  # noqa: S110
        pass
    return None


def compute_changed_files(  # noqa: C901 - three git probes with shared shaping
    git_root: Path, last_git_head: str | None
) -> list[str] | dict:
    """Compute files changed since the given git HEAD.

    Runs ``git diff --name-only <last>..HEAD`` plus unstaged diff and
    untracked status at ``git_root``. Deduplicates and sorts alphabetically.

    Formato exacto (WT-2026-196 contrato):
        - Si Git disponible: lista JSON de rutas relativas, normalizadas con /,
          sin duplicados, ordenadas alfabeticamente.
        - Si Git no disponible: ``{"status": "unknown", "reason": "<motivo>"}``.
    """
    if last_git_head is None:
        if get_current_git_head(git_root) is None:
            return {
                "status": "unknown",
                "reason": "git is unavailable or not a repository",
            }
        return []  # First review in this ticket, no previous HEAD

    try:
        git_bin = shutil.which("git") or "git"
        files: set[str] = set()

        # Committed changes since last_git_head
        result = subprocess.run(  # noqa: S603
            [git_bin, "diff", "--name-only", f"{last_git_head}..HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=git_root,
            timeout=10,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines():
                fname = line.strip()
                if fname:
                    files.add(fname.replace("\\", "/"))

        # Unstaged changes (working tree)
        result = subprocess.run(  # noqa: S603
            [git_bin, "diff", "--name-only"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=git_root,
            timeout=10,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines():
                fname = line.strip()
                if fname:
                    files.add(fname.replace("\\", "/"))

        # Untracked files
        result = subprocess.run(  # noqa: S603
            [git_bin, "status", "--porcelain", "-z"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=git_root,
            timeout=10,
        )
        if result.returncode == 0:
            entries = result.stdout.split("\0")
            for entry in entries:
                if entry and entry.startswith("?? "):
                    fname = entry[3:].strip()
                    if fname:
                        files.add(fname.replace("\\", "/"))

        if not files:
            return []
        return sorted(files)
    except Exception as exc:
        return {"status": "unknown", "reason": f"git error: {exc}"}


# ---------------------------------------------------------------------------
# Repeated-blocker detection
# ---------------------------------------------------------------------------


def compute_repeated_blockers(
    previous_signatures: list[str],
    current_feedback: str,
) -> tuple[list[str], bool]:
    """Compute repeated blockers and whether diagnostic mode should activate.

    Parses current feedback for blockers, computes signatures, finds the
    intersection between previous and current signatures.
    Returns (repeated_signatures_list, should_activate_diagnostic).

    Diagnostic mode activates when:
    - A blocker signature reappears in consecutive reviews (REPEATED_BLOCKER).
    - The overlap ratio (by signature) exceeds 50%.
    """
    current_sigs = extract_signatures_from_feedback(current_feedback)
    if not previous_signatures or not current_sigs:
        return [], False

    prev_set = set(previous_signatures)
    repeated = list(prev_set & current_sigs)
    if not repeated:
        return [], False

    overlap = compute_blocker_overlap(prev_set, current_sigs)
    should_diagnose = bool(repeated) or (overlap > 0.5)
    return repeated, should_diagnose
