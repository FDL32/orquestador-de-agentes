import shutil
import subprocess
from pathlib import Path


DOCS_ONLY_PATTERNS = (
    ".agent/collaboration/",
    ".agent/runtime/",
    ".session/",
    "PROJECT.md",
    "AGENTS.md",
    "README.md",
    "CHANGELOG.md",
    "CREDITS.md",
    "REPOSITORY_STRUCTURE.md",
    "repomix.config.json",
)

COLLABORATION_ONLY_PATTERNS = (
    ".agent/collaboration/",
    ".agent/runtime/",
)


def _path_matches_any(path: str, patterns: tuple[str, ...]) -> bool:
    normalized = path.replace("\\", "/")
    return any(pattern in normalized for pattern in patterns)


def _run_git_cmd(args: list[str], cwd: Path) -> set[str]:
    try:
        args_copy = args.copy()
        args_copy[0] = shutil.which(args_copy[0]) or args_copy[0]
        result = subprocess.run(  # noqa: S603
            args_copy, capture_output=True, text=True, cwd=cwd, timeout=10
        )
        if result.returncode == 0:
            return {
                line.strip().replace("\\", "/")
                for line in result.stdout.strip().split("\n")
                if line.strip() and not line.strip().startswith("commit ")
            }
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return set()


def _own_git_root(root: Path | None) -> Path | None:
    """Return `root` only if it carries its OWN .git; otherwise None.

    Git resolves a repository by walking UP from cwd. A directory that sits inside
    the real repo but has no .git of its own therefore answers for the REAL repo --
    and pytest's `tmp_path` lands exactly there in this project. Running git from
    such a root silently reports the developer's working tree, so a "hermetic" test
    ends up asserting against whatever happens to be dirty (WOT-2026-020r).

    `.git` is a FILE in a linked worktree (`_dev` is one), so the predicate is
    existence, not is_dir().
    """
    if root is None:
        return None
    return root if (root / ".git").exists() else None


def motor_uncommitted_productive(motor_root: Path) -> list[str]:
    """Return list of uncommitted productive files in motor_root.

    Only considers working tree and staged changes (git diff + git diff --cached).
    Does NOT include recently committed files — that is what distinguishes this
    from resolve_evidence()["motor_productive"] which can include git log results.

    Returns sorted list of file paths (normalized with forward slashes) that are
    not docs-only or collaboration-only. Empty list means no uncommitted productive
    changes.
    """
    motor_root = _own_git_root(motor_root)
    if motor_root is None:
        return []

    files = set()
    files |= _run_git_cmd(["git", "diff", "--name-only"], motor_root)
    files |= _run_git_cmd(["git", "diff", "--cached", "--name-only"], motor_root)
    files |= _run_git_cmd(
        ["git", "ls-files", "--others", "--exclude-standard"], motor_root
    )

    productive = sorted(
        f for f in files if not _path_matches_any(f, DOCS_ONLY_PATTERNS)
    )
    return productive


def resolve_evidence(
    motor_root: Path, project_root: Path, ticket_id: str | None = None
) -> dict:
    """Resolve implementation evidence from motor and destination repositories.

    Extracts working tree, staged, and recently committed files.
    Always includes recent commits (fixes WT-2026-225a where a dirty working tree
    would hide valid ticket commits).

    Both roots are normalized up front: a root without its own .git is dropped, so
    no git command below can walk UP into the enclosing real repo (WOT-2026-020r).
    This must happen BEFORE the first git call -- `git log --oneline -20` walks up
    just as readily as `git diff` does.
    """
    motor_root = _own_git_root(motor_root)
    project_root = _own_git_root(project_root)

    motor_files_set = set()
    dest_files_set = set()

    has_ticket_commit = False
    if ticket_id:
        roots = {r for r in (motor_root, project_root) if r is not None}
        for r in roots:
            try:
                git_exec = shutil.which("git") or "git"
                result = subprocess.run(  # noqa: S603
                    [git_exec, "log", "--oneline", "-20"],
                    capture_output=True,
                    text=True,
                    cwd=r,
                    timeout=10,
                )
                if result.returncode == 0 and ticket_id in result.stdout:
                    has_ticket_commit = True
                    break
            except Exception:  # noqa: S110
                pass

    if motor_root:
        motor_files_set |= _run_git_cmd(["git", "diff", "--name-only"], motor_root)
        motor_files_set |= _run_git_cmd(
            ["git", "diff", "--cached", "--name-only"], motor_root
        )
        if not ticket_id or has_ticket_commit:
            motor_files_set |= _run_git_cmd(
                ["git", "log", "-10", "--name-only", "--format="], motor_root
            )

    if project_root:
        dest_files_set |= _run_git_cmd(["git", "diff", "--name-only"], project_root)
        dest_files_set |= _run_git_cmd(
            ["git", "diff", "--cached", "--name-only"], project_root
        )
        if not ticket_id or has_ticket_commit:
            dest_files_set |= _run_git_cmd(
                ["git", "log", "-10", "--name-only", "--format="], project_root
            )

    # If roots are the same, dest files will overlap exactly with motor files, which is fine
    motor_files = sorted(motor_files_set)
    destination_files = sorted(dest_files_set)

    all_files = sorted(motor_files_set | dest_files_set)

    docs_only = [f for f in all_files if _path_matches_any(f, DOCS_ONLY_PATTERNS)]
    productive = [f for f in all_files if not _path_matches_any(f, DOCS_ONLY_PATTERNS)]

    motor_productive = [
        f for f in motor_files if not _path_matches_any(f, DOCS_ONLY_PATTERNS)
    ]
    dest_productive = [
        f for f in destination_files if not _path_matches_any(f, DOCS_ONLY_PATTERNS)
    ]

    collab_only = (
        all(_path_matches_any(f, COLLABORATION_ONLY_PATTERNS) for f in all_files)
        if all_files
        else False
    )

    return {
        "motor_files": motor_files,
        "destination_files": destination_files,
        "all_files": all_files,
        "docs_only_files": docs_only,
        "productive_files": productive,
        "is_docs_only": bool(all_files) and not bool(productive),
        "is_collaboration_only": bool(all_files) and collab_only,
        "motor_productive": motor_productive,
        "dest_productive": dest_productive,
        "has_motor_evidence": bool(motor_productive),
        "has_destination_productive": bool(dest_productive),
        "has_productive_evidence": bool(productive),
        "has_ticket_commit": has_ticket_commit,
        "sources_used": ["working_tree", "staged", "recent_commits"],
    }
