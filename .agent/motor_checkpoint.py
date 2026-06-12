"""Motor checkpoint and delivery-evidence git operations.

Extracted from agent_controller.py (monolith decomposition, giro 13).
This module owns the pre-handoff / mark-ready support cluster:

- Live-surface classification and Files Likely Touched parsing.
- Motor checkpoint resolution: contiguous ticket commits, file sets,
  HEAD/tag SHA resolution and ancestry checks.
- Motor commit/tag creation for delivery evidence (M3 checkpoint).
- Launcher root resolution (motor / destino / workspace).

All functions are parameterized on paths/content - no controller
globals. agent_controller keeps name-stable aliases so existing
call sites and test monkeypatches (agent_controller._*) keep working.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


# Global noqa for subprocess lint rules - all calls use hardcoded command lists
# ruff: noqa: S603,S607

LIVE_SURFACES_REL = {
    ".agent/collaboration/TURN.md",
    ".agent/collaboration/STATE.md",
    ".agent/collaboration/execution_log.md",
    ".agent/collaboration/notifications.md",
    ".agent/collaboration/review_queue.md",
    ".agent/collaboration/work_plan.md",
    ".agent/collaboration/backlog.md",
    ".agent/collaboration/archive/",
    ".agent/collaboration/_archive/",
    ".agent/runtime/memory/session_close_report.md",
    ".agent/runtime/events/events.jsonl",
    ".agent/runtime/store.json",
    ".agent/runtime/builder_lock.txt",
    ".agent/runtime/circuit_breaker.json",
    ".agent/runtime/supervisor_lock.txt",
    ".agent/runtime/events/",
    ".agent/runtime/approvals/",
    ".agent/context/project-map.json",
    "PROJECT.md",
}

WORKSPACE_EXCLUDED_PREFIXES = {
    ".agent/collaboration/PLAN_WP-",
    ".agent/collaboration/PLAN_WT-",
    ".agent/collaboration/AUDIT_WP-",
    ".agent/collaboration/AUDIT_WT-",
    ".agent/collaboration/manager_feedback_",
    # WT-2026-249b: BUILDER_BRIEF_ artefacts are operational handoff files
    # generated for the active ticket. They must not block --pre-handoff.
    ".agent/collaboration/BUILDER_BRIEF_",
}

LIVE_SURFACE_DIRS = {
    ".agent/collaboration/archive",
    ".agent/collaboration/_archive",
    ".agent/runtime/events",
    ".agent/runtime/approvals",
}


def build_live_surface_sets(
    project_root: Path,
) -> tuple[set[str], set[str]]:
    """Build absolute path sets for live surfaces.

    Returns:
        tuple[set[str], set[str]]: (live_files, live_dirs)
    """
    live_files: set[str] = set()
    live_dirs: set[str] = set()

    for rel_path in LIVE_SURFACES_REL:
        full_path = (project_root / rel_path).resolve()
        if rel_path.endswith("/"):
            live_dirs.add(str(full_path))
        else:
            live_files.add(str(full_path))

    for rel_dir in LIVE_SURFACE_DIRS:
        live_dirs.add(str((project_root / rel_dir).resolve()))

    # Include all files under archive/ and _archive/plan_audit/
    for sub in ("archive", "_archive/plan_audit"):
        d = project_root / ".agent" / "collaboration" / sub
        if d.exists():
            for f in d.glob("*"):
                live_files.add(str(f.resolve()))

    return live_files, live_dirs


def is_live_surface(
    file_abs: str,
    project_root: Path,
    live_files: set[str],
    live_dirs: set[str],
) -> bool:
    """Check if an absolute path belongs to a live surface."""
    if file_abs in live_files:
        return True
    p = Path(file_abs)
    # Check if file is in a live surface directory
    for d in live_dirs:
        if path_is_under(p, Path(d)):
            return True
    # Check workspace excluded prefixes
    try:
        rel = str(p.relative_to(project_root)).replace("\\", "/")
        return any(rel.startswith(prefix) for prefix in WORKSPACE_EXCLUDED_PREFIXES)
    except ValueError:
        return False


def path_is_under(child: Path, parent: Path) -> bool:
    """Return True if child is under parent directory."""
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def parse_raw_flt_paths(plan_content: str) -> set[str]:  # noqa: C901
    """Parse Files Likely Touched returning motor-relative paths with /.

    Unlike parse_files_likely_touched(), this function does NOT resolve paths
    against PROJECT_ROOT. It returns raw relative paths normalized to forward
    slashes, suitable for comparison with motor_uncommitted_productive() output.

    Before: plan_content contains a ``## Files Likely Touched`` section.
    During: Scans lines, normalizes backticks/quotes, strips bullets.
    After: Returns set of motor-relative paths with forward slashes.
    """
    lines = plan_content.split("\n")
    in_section = False
    paths: set[str] = set()

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
                p = normalized.replace("\\", "/")
                if p.startswith("./"):
                    p = p[2:]
                paths.add(p)
    return paths


def resolve_motor_checkpoint_files(
    motor_root: Path, ticket_id: str
) -> tuple[bool, set[str], str]:
    """Resolve checkpoint files from motor git repo.

    WT-2026-232a: Helper for motor-aware scope gate in mark-ready.

    Before: motor_root is a git repo with checkpoint/review-<ticket_id> tag.
    During: Runs git rev-parse, merge-base --is-ancestor, verifies tag == HEAD,
            then git log and git diff-tree.
    After: Returns (True, files_set, '') on valid checkpoint,
           (False, set(), error_msg) on failure.
    """
    tag_name = f"checkpoint/review-{ticket_id}"

    try:
        # Step 1: Get SHA of the checkpoint tag
        sha_ok, sha_result = resolve_git_tag_sha(motor_root, tag_name)
        if not sha_ok:
            return False, set(), sha_result
        sha = sha_result

        # Step 2: Check SHA is ancestor of HEAD (not stale/detached)
        if not is_git_ancestor_of_head(motor_root, sha):
            return (
                False,
                set(),
                f"Tag {tag_name}@{sha[:8]} is not an ancestor of HEAD",
            )

        # Step 3: Require the checkpoint tag to anchor the exact handoff HEAD.
        head_ok, head_result = resolve_git_head_sha(motor_root)
        if not head_ok:
            return False, set(), head_result
        head_sha = head_result
        if sha != head_sha:
            return (
                False,
                set(),
                f"Tag {tag_name}@{sha[:8]} is stale; expected HEAD {head_sha[:8]}",
            )

        # Step 4: Verify checkpoint commit message contains ticket_id
        log_proc = subprocess.run(
            ["git", "log", "-1", "--format=%s", sha],
            capture_output=True,
            text=True,
            cwd=motor_root,
            timeout=30,
        )
        if log_proc.returncode != 0:
            return False, set(), f"git log failed for {sha[:8]}"
        if ticket_id not in log_proc.stdout:
            return (
                False,
                set(),
                f"Commit {sha[:8]} ({tag_name}) message does not contain {ticket_id}",
            )

        delivery_commits, history_error = contiguous_ticket_commits(
            motor_root, sha, ticket_id
        )
        if history_error:
            return False, set(), history_error

        files, files_error = files_from_commits(motor_root, delivery_commits)
        if files_error:
            return False, set(), files_error
        return True, files, ""

    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return False, set(), f"Git operation failed: {e}"


def contiguous_ticket_commits(
    motor_root: Path, checkpoint_sha: str, ticket_id: str
) -> tuple[list[str], str]:
    """Return contiguous first-parent commits for the ticket at the checkpoint."""
    history_proc = subprocess.run(
        ["git", "log", "--first-parent", "--format=%H%x00%s", checkpoint_sha],
        capture_output=True,
        text=True,
        cwd=motor_root,
        timeout=30,
    )
    if history_proc.returncode != 0:
        return [], f"git history failed for {checkpoint_sha[:8]}"

    commits: list[str] = []
    for line in history_proc.stdout.splitlines():
        commit_sha, separator, subject = line.partition("\0")
        if not separator or ticket_id not in subject:
            break
        commits.append(commit_sha)
    if not commits:
        return [], f"No contiguous {ticket_id} commits at checkpoint"
    return commits, ""


def files_from_commits(
    motor_root: Path, commit_shas: list[str]
) -> tuple[set[str], str]:
    """Return the union of motor-relative files changed by the given commits."""
    files: set[str] = set()
    for commit_sha in commit_shas:
        diff_proc = subprocess.run(
            [
                "git",
                "diff-tree",
                "--root",
                "--no-commit-id",
                "-r",
                "--name-only",
                commit_sha,
            ],
            capture_output=True,
            text=True,
            cwd=motor_root,
            timeout=30,
        )
        if diff_proc.returncode != 0:
            return set(), f"git diff-tree failed for {commit_sha[:8]}"
        files.update(
            line.strip() for line in diff_proc.stdout.splitlines() if line.strip()
        )
    return files, ""


def resolve_git_head_sha(git_root: Path) -> tuple[bool, str]:
    """Return HEAD SHA for git_root or a diagnostic error string."""
    head_proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        cwd=git_root,
        timeout=30,
    )
    if head_proc.returncode != 0:
        return False, "Unable to resolve HEAD in motor repo"

    head_sha = head_proc.stdout.strip()
    if not head_sha:
        return False, "Empty SHA from rev-parse HEAD"
    return True, head_sha


def print_motor_checkpoint_guidance(plan_id: str, cp_error: str) -> None:
    """Print Builder-facing recovery guidance for motor checkpoint failures."""
    print(f"[ERROR] No valid motor checkpoint for {plan_id}: {cp_error}")
    if "stale; expected HEAD" in cp_error:
        print(
            "Checkpoint M3 exists but is outdated. Run `--pre-handoff` again after "
            "the latest repo_motor commit so checkpoint/review-<ticket> is recreated "
            "on the current HEAD."
        )
        print(
            "Do not use --scope-override for this case: the handoff anchor itself "
            "must be refreshed."
        )
        return

    print("Run --pre-handoff first to create checkpoint/review-<ticket> in repo_motor.")


def resolve_git_tag_sha(git_root: Path, tag_name: str) -> tuple[bool, str]:
    """Return the peeled commit SHA for tag_name or a diagnostic error string."""
    rev_proc = subprocess.run(
        ["git", "rev-parse", f"{tag_name}^{{}}"],
        capture_output=True,
        text=True,
        cwd=git_root,
        timeout=30,
    )
    if rev_proc.returncode != 0:
        return False, f"Tag {tag_name} not found in motor repo"

    sha = rev_proc.stdout.strip()
    if not sha:
        return False, f"Empty SHA from rev-parse {tag_name}"
    return True, sha


def is_git_ancestor_of_head(git_root: Path, sha: str) -> bool:
    """Return True when sha is an ancestor of HEAD in git_root."""
    ancestor_proc = subprocess.run(
        ["git", "merge-base", "--is-ancestor", sha, "HEAD"],
        capture_output=True,
        text=True,
        cwd=git_root,
        timeout=30,
    )
    return ancestor_proc.returncode == 0


def resolve_launcher_roots(project_root: Path | None) -> dict[str, str]:
    """Resolve the three canonical root paths for the launcher.

    WT-2026-232a: Single source of truth for launcher root resolution.
    Used by --resolve-launcher-roots --json --project-root <dest>.

    Before: project_root is either None or a valid Path.
    During: Resolves motor_root from file location, destino_root
            from project_root or motor_destination_link.json, and
            workspace_activo_root as the directory containing .agent/.
    After: Returns dict with three normalized string keys.
           Raises RuntimeError if any root cannot be resolved.
    """
    motor_root = Path(__file__).resolve().parent.parent
    destino_root = resolve_destino_root(motor_root, project_root)
    workspace_activo_root = resolve_workspace_root(motor_root, destino_root)
    result = {
        "repo_motor_root": str(motor_root).replace("\\", "/"),
        "repo_destino_root": str(destino_root).replace("\\", "/"),
        "workspace_activo_root": str(workspace_activo_root).replace("\\", "/"),
    }
    for key, value in result.items():
        if not value:
            raise RuntimeError(f"Cannot resolve empty '{key}'")
    return result


def resolve_destino_root(motor_root: Path, project_root: Path | None) -> Path:
    """Resolve repo_destino_root from project_root or motor_destination_link.json."""
    if project_root is not None:
        return Path(project_root).resolve()
    link_path = motor_root / ".agent" / "config" / "motor_destination_link.json"
    if link_path.exists():
        try:
            link_data = json.loads(link_path.read_text(encoding="utf-8"))
            dest = link_data.get("destination_root")
            if dest:
                return Path(dest).resolve()
        except (json.JSONDecodeError, OSError):
            pass
    return motor_root


def resolve_workspace_root(motor_root: Path, destino_root: Path) -> Path:
    """Resolve workspace_activo_root as directory containing .agent/."""
    if (destino_root / ".agent").is_dir():
        return destino_root
    for parent in [motor_root, motor_root.parent]:
        if (parent / ".agent").is_dir():
            return parent
    return motor_root


def try_motor_commit(
    motor_root: Path, paths: list[str], plan_id: str, json_output: bool
) -> tuple[bool, str]:
    """Commit paths in motor_root with retry for hooks that modify staged files.

    Before: motor_root is a git repo with uncommitted changes in listed paths.
    During: git add + git commit. If commit fails (e.g. pre-commit hook modifies
            staged files), checks remaining uncommitted changes within the same
            paths and retries once. Never re-adds paths outside the original list.
    After: Returns (True, '') on success, (False, error_message) on failure.
    """
    add_proc = subprocess.run(
        ["git", "add", "--", *paths],
        capture_output=True,
        text=True,
        cwd=motor_root,
    )
    if add_proc.returncode != 0:
        return False, (
            f"[ERROR] git add failed:\n"
            f"{add_proc.stderr.strip() or add_proc.stdout.strip()}"
        )

    commit_msg = f"chore({plan_id}): pre-handoff checkpoint"
    commit_proc = subprocess.run(
        ["git", "commit", "-m", commit_msg],
        capture_output=True,
        text=True,
        cwd=motor_root,
    )
    if commit_proc.returncode == 0:
        if not json_output:
            print(f"[OK] Committed in repo_motor: {commit_msg}")
        return True, ""

    # Attempt 2: commit failed - check for hook that modified staged files
    from bus.evidence import motor_uncommitted_productive

    remaining = motor_uncommitted_productive(motor_root)
    remaining_in_flt = [f for f in remaining if f in paths]

    if remaining_in_flt:
        add_retry = subprocess.run(
            ["git", "add", "--", *remaining_in_flt],
            capture_output=True,
            text=True,
            cwd=motor_root,
        )
        if add_retry.returncode != 0:
            return False, (
                f"[ERROR] git add failed on retry:\n"
                f"{add_retry.stderr.strip() or add_retry.stdout.strip()}"
            )

        commit_retry = subprocess.run(
            ["git", "commit", "-m", commit_msg],
            capture_output=True,
            text=True,
            cwd=motor_root,
        )
        if commit_retry.returncode == 0:
            if not json_output:
                print(f"[OK] Committed in repo_motor (retry): {commit_msg}")
            return True, ""
        else:
            err = commit_retry.stderr.strip() or commit_retry.stdout.strip()
            pending = "\n".join(f"  {f}" for f in remaining_in_flt)
            return False, (
                f"[ERROR] git commit failed after retry:\n{err}\n"
                f"Pending paths motor-relative:\n{pending}"
            )

    err = commit_proc.stderr.strip() or commit_proc.stdout.strip()
    return False, f"[ERROR] git commit failed:\n{err}"


def try_motor_tag(
    motor_root: Path, plan_id: str, json_output: bool
) -> tuple[bool, str]:
    """Create or refresh checkpoint/review-<ticket> tag in motor_root.

    Before: motor_root is a git repo.
    During: If tag exists, deletes it first. Creates annotated tag at HEAD.
    After: Returns (True, '') on success, (False, error_message) on failure.
    """
    tag_name = f"checkpoint/review-{plan_id}"

    try:
        check_proc = subprocess.run(
            ["git", "rev-parse", f"{tag_name}^{{}}"],
            capture_output=True,
            text=True,
            cwd=motor_root,
        )
        tag_exists = check_proc.returncode == 0

        if tag_exists:
            del_proc = subprocess.run(
                ["git", "tag", "-d", tag_name],
                capture_output=True,
                text=True,
                cwd=motor_root,
            )
            if del_proc.returncode != 0:
                err = del_proc.stderr.strip() or del_proc.stdout.strip()
                return False, f"[ERROR] Failed to delete tag {tag_name}:\n{err}"

        tag_msg = f"Checkpoint M3 for {plan_id}"
        tag_proc = subprocess.run(
            ["git", "tag", "-a", tag_name, "-m", tag_msg],
            capture_output=True,
            text=True,
            cwd=motor_root,
        )
        if tag_proc.returncode != 0:
            err = tag_proc.stderr.strip() or tag_proc.stdout.strip()
            return False, f"[ERROR] Failed to create tag {tag_name}:\n{err}"

        if not json_output:
            print(f"[OK] Created/refreshed tag: {tag_name}")
        return True, ""
    except FileNotFoundError:
        return False, "[ERROR] git not available for tag operation"
