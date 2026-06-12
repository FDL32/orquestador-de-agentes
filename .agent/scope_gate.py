"""Scope gate helpers extracted from ``agent_controller``.

This module owns parsing, git diff inspection, whitelist/exclusion handling,
and closeout gating primitives extracted from the original controller
monolith. All functions are parameterized and do not depend on controller
globals.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


EXCLUDE_FILES_REL = {
    "work_plan.md",
    "execution_log.md",
    "STATE.md",
    "TURN.md",
    "notifications.md",
    ".session_state.json",
}


def exclude_files(
    *,
    collab_dir: Path,
    agent_dir: Path,
    context_dir: Path,
    exclude_files_rel: set[str] | None = None,
) -> set[str]:
    """Return absolute paths that should not count against the scope gate."""
    rel_paths = exclude_files_rel or EXCLUDE_FILES_REL
    excluded = {str((collab_dir / file_name).resolve()) for file_name in rel_paths}

    if collab_dir.exists():
        for path in collab_dir.glob("*"):
            if path.is_file():
                excluded.add(str(path.resolve()))

    archive_dir = collab_dir / "_archive"
    if archive_dir.exists():
        for path in archive_dir.rglob("*"):
            if path.is_file():
                excluded.add(str(path.resolve()))
        excluded.add(str(archive_dir.resolve()))
        for subdir in archive_dir.iterdir():
            if subdir.is_dir():
                excluded.add(str(subdir.resolve()))

    excluded.add(str((context_dir / "project-map.json").resolve()))
    excluded.add(str((agent_dir / "runtime" / "events" / "events.jsonl").resolve()))
    excluded.add(str((agent_dir / "config").resolve()))
    return excluded


def parse_files_likely_touched(
    work_plan_content: str, *, project_root: Path
) -> set[str]:
    """Parse Files Likely Touched entries and resolve them against project_root."""
    lines = work_plan_content.split("\n")
    in_section = False
    files = set()

    def _looks_like_path_token(token: str) -> bool:
        if not token or " " in token:
            return False
        if token.startswith("."):
            return True
        if "/" in token or "\\" in token:
            return True
        basename = token.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        return "." in basename

    for line in lines:
        line = line.strip()
        if "## Files Likely Touched" in line:
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section and line and not line.startswith("---"):
            normalized = (
                line.lstrip("*- ")
                .replace("`", "")
                .replace('"', "")
                .replace("'", "")
                .strip()
            )
            if normalized and _looks_like_path_token(normalized):
                path = (project_root / normalized).resolve()
                files.add(str(path))
    return files


def git_log_recent_files(
    git_root: Path,
    *,
    n: int = 10,
    run_fn=subprocess.run,
) -> set[str]:
    """Return relative file paths from the last n commits in git_root."""
    try:
        result = run_fn(
            ["git", "log", f"-{n}", "--name-only", "--format="],
            capture_output=True,
            text=True,
            cwd=git_root,
            timeout=30,
        )
        if result.returncode == 0:
            return {line.strip() for line in result.stdout.split("\n") if line.strip()}
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return set()


def get_changed_files(
    *,
    project_root: Path,
    motor_root: Path | None,
    run_fn=subprocess.run,
) -> set[str] | None:
    """Return changed files from the active git root, or None if no git repo exists."""
    git_root = (
        project_root
        if (project_root / ".git").exists()
        else (motor_root if motor_root and (motor_root / ".git").exists() else None)
    )
    if git_root is None:
        return None
    try:
        result = run_fn(
            ["git", "status", "--porcelain", "-z"],
            capture_output=True,
            text=True,
            cwd=git_root,
        )
        changed = set()
        entries = result.stdout.split("\0")
        index = 0
        while index < len(entries):
            entry = entries[index]
            if not entry:
                index += 1
                continue
            if len(entry) >= 3:
                status = entry[:2]
                path = entry[3:] if entry[2] == " " else entry[2:]
                if status[0] == "R" and index + 1 < len(entries):
                    new_path = entries[index + 1]
                    if new_path:
                        changed.add(new_path)
                    index += 2
                    continue
                changed.add(path)
            index += 1
        return {str((git_root / path).resolve()) for path in changed}
    except FileNotFoundError:
        return None


def check_scope_gate(
    work_plan_content: str,
    changed_files: set[str] | None,
    exclude_files: set[str],
    *,
    parse_files_likely_touched_fn,
) -> dict:
    """Check if changed files stay within the declared Files Likely Touched scope."""
    if changed_files is None:
        return {
            "valid": True,
            "out_of_scope": set(),
            "missing_from_diff": set(),
            "covered_files": set(),
            "warnings": ["Repository is not git-managed"],
            "blocked_reason": None,
        }

    whitelist = parse_files_likely_touched_fn(work_plan_content)
    if not whitelist:
        return {
            "valid": True,
            "out_of_scope": set(),
            "missing_from_diff": set(),
            "covered_files": set(),
            "warnings": ["No Files Likely Touched section in work_plan.md"],
            "blocked_reason": None,
        }

    relevant_changed = changed_files - exclude_files
    relevant_whitelist = whitelist - exclude_files
    covered_files = relevant_changed & relevant_whitelist
    missing_from_diff = relevant_whitelist - relevant_changed
    out_of_scope = relevant_changed - relevant_whitelist

    warnings: list[str] = []
    blocked_reason = None
    valid = len(out_of_scope) == 0

    if relevant_whitelist and not covered_files:
        valid = False
        blocked_reason = (
            "None of the declared Files Likely Touched entries appeared in the diff"
        )
    elif covered_files and missing_from_diff:
        warnings.append(
            "Partial scope coverage: "
            f"{len(covered_files)} of {len(relevant_whitelist)} declared files touched"
        )

    return {
        "valid": valid,
        "out_of_scope": out_of_scope,
        "missing_from_diff": missing_from_diff,
        "covered_files": covered_files,
        "warnings": warnings,
        "blocked_reason": blocked_reason,
    }


def record_scope_override(
    scope_override: str,
    problem_files: set[str],
    *,
    update_log_status_fn,
) -> None:
    """Persist a scope override note via the provided log callback."""
    note = (
        f"Scope override: {scope_override}. "
        f"Affected files: {', '.join(sorted(problem_files))}"
    )
    update_log_status_fn("READY_FOR_REVIEW", note)


def scope_gate_allows_close(
    gate_result: dict,
    scope_override: str | None,
    *,
    update_log_status_fn,
    record_scope_override_fn,
    print_fn=print,
) -> bool:
    """Apply the final scope gate decision using injected side-effect callbacks."""
    if gate_result["valid"]:
        for warning in gate_result["warnings"]:
            print_fn(f"[WARN] {warning}")
        update_log_status_fn("READY_FOR_REVIEW", "Marked ready by Builder")
        return True

    if not scope_override:
        print_fn("[ERROR] Scope violation detected:")
        if gate_result.get("blocked_reason"):
            print_fn(f"  {gate_result['blocked_reason']}")
        for file_path in sorted(gate_result["out_of_scope"]):
            print_fn(f"  - {file_path}")
        missing = sorted(gate_result.get("missing_from_diff", set()))
        for file_path in missing:
            print_fn(f"  - missing: {file_path}")
        workspace_memory = ".agent/runtime/memory/"
        memory_missing = [
            file_path
            for file_path in missing
            if workspace_memory in file_path.replace("\\", "/")
        ]
        if memory_missing:
            print_fn(
                "[HINT] Some missing files live in the workspace portable "
                "(.agent/runtime/memory/) and are not tracked in the motor git diff. "
                "This is expected (CL-08). Use --scope-override with reason:\n"
                '  --scope-override "Memory files modified in workspace portable; '
                'motor git diff cannot reflect .agent/runtime/memory/ changes."'
            )
        print_fn('Use --scope-override "reason" to proceed.')
        return False

    print_fn(f"[INFO] Scope override applied: {scope_override}")
    problem_files = set(gate_result["out_of_scope"]) | set(
        gate_result.get("missing_from_diff", set())
    )
    record_scope_override_fn(scope_override, problem_files)
    return True
