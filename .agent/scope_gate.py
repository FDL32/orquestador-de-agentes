"""Scope gate helpers extracted from ``agent_controller``.

This module owns parsing, git diff inspection, whitelist/exclusion handling,
and closeout gating primitives extracted from the original controller
monolith. All functions are parameterized and do not depend on controller
globals.
"""

from __future__ import annotations

import re
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


_DOC_DELIVERABLE_TYPES = frozenset({"analysis", "documentation", "research"})
# WOT-2026-019j: deliverable_types that fall back to parsing the ``## Builder``
# section when ``## Files Likely Touched`` yields no entries. Superset of
# _DOC_DELIVERABLE_TYPES that also covers "mixed" tickets declaring their
# deliverables under ``## Builder``. Single source of truth so a future
# surface cannot forget to add "mixed" independently.
_FLT_BUILDER_FALLBACK_TYPES = _DOC_DELIVERABLE_TYPES | {"mixed"}
_DELIVERY_AUTHORITY_RE = re.compile(
    r"(?:delivery_authority|repo\s+de\s+autoridad)"
    r"\**\s*:?\s*\**\s*(`?)(repo_motor|repo_destino)\1",
    re.IGNORECASE,
)


def _looks_like_path_token(token: str) -> bool:
    if not token or " " in token:
        return False
    if token.startswith("."):
        return True
    if "/" in token or "\\" in token:
        return True
    basename = token.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return "." in basename


def _normalize_flt_line(line: str) -> str:
    cleaned = (
        line.lstrip("*- ").replace("`", "").replace('"', "").replace("'", "").strip()
    )
    if not cleaned:
        return cleaned
    # WOT-2026-016s: a bullet may carry a trailing descriptive annotation after
    # the path (e.g. "scripts/x.py (nuevo, el gate)"). Keep only the first
    # whitespace-separated token (the path itself) so _looks_like_path_token
    # does not reject the whole bullet just because the annotation contains a
    # space. Bullets without annotation have no second token, so this is a
    # no-op for the already-covered case.
    return cleaned.split(" ", 1)[0]


def _normalize_raw_flt_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def read_delivery_authority(content: str, default: str = "repo_motor") -> str:
    """Read delivery_authority from markdown metadata or prose."""
    match = _DELIVERY_AUTHORITY_RE.search(content or "")
    if not match:
        return default
    return match.group(2).strip().lower()


def _section_path_tokens(lines: list[str], heading: str) -> list[str]:
    """Raw (unresolved) path tokens from a markdown section, in document order.

    Content-only sibling of ``_extract_section_paths``: reuses the same FLT line
    normalization and path-token heuristic but does NOT resolve against a
    project_root, so it is safe for checks that only need the path text (e.g.
    extension/congruence checks during ``--validate`` where no root is in scope).
    """
    in_section = False
    tokens: list[str] = []
    for raw in lines:
        line = raw.strip()
        if line == f"## {heading}":
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section and line and not line.startswith("---"):
            normalized = _normalize_flt_line(line)
            if normalized and _looks_like_path_token(normalized):
                tokens.append(normalized)
    return tokens


def files_likely_touched_tokens(
    work_plan_content: str, *, deliverable_type: str = "code"
) -> list[str]:
    """Raw FLT/Builder path tokens for extension/congruence checks (no I/O).

    Mirrors ``parse_files_likely_touched``'s section selection (FLT first, then
    the ``## Builder`` section for doc-type tickets) but returns the unresolved
    path text so callers can inspect extensions without a project_root. Does NOT
    read ``## Read/inspect only`` — those are sources, not deliverables.
    """
    lines = work_plan_content.split("\n")
    tokens = _section_path_tokens(lines, "Files Likely Touched")
    if not tokens and deliverable_type in _FLT_BUILDER_FALLBACK_TYPES:
        tokens = _section_path_tokens(lines, "Builder")
    return tokens


def _extract_section_paths(
    lines: list[str], heading: str, project_root: Path
) -> set[str]:
    """Extract resolved paths from a markdown section identified by heading."""
    in_section = False
    files: set[str] = set()
    for line in lines:
        line = line.strip()
        if line == f"## {heading}":
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section and line and not line.startswith("---"):
            normalized = _normalize_flt_line(line)
            if normalized and _looks_like_path_token(normalized):
                path = (project_root / normalized).resolve()
                files.add(str(path))
    return files


def _parse_builder_fallback_entries(
    lines: list[str],
) -> list[tuple[str | None, str]]:
    """Scan the ``## Builder`` section for path tokens (flat, no namespaces).

    WOT-2026-019j fallback: ``## Builder`` never uses ``### `` sub-headings, so
    every entry is flat (namespace ``None``). Same start/end detection as the
    FLT scan in :func:`_parse_flt_section`.
    """
    in_builder = False
    builder_entries: list[tuple[str | None, str]] = []
    for line in lines:
        stripped = line.strip()
        if stripped == "## Builder":
            in_builder = True
            continue
        if (
            in_builder
            and stripped.startswith("## ")
            and not stripped.startswith("### ")
        ):
            break
        if not in_builder:
            continue
        if not stripped or stripped.startswith("---"):
            continue
        normalized = _normalize_flt_line(stripped)
        if normalized and _looks_like_path_token(normalized):
            builder_entries.append((None, normalized))
    return builder_entries


def _parse_flt_section(
    lines: list[str],
    *,
    deliverable_type: str = "code",
) -> tuple[bool, list[tuple[str | None, str]]]:
    """Scan the FLT section and return (has_namespaces, [(namespace, raw_path)]).

    Namespace is ``"motor"``, ``"destino"``, ``"unknown"``, or ``None`` (flat).
    Only yields lines that look like path tokens.

    WOT-2026-019j: if the ``## Files Likely Touched`` scan yields no entries
    and ``deliverable_type`` is in ``_FLT_BUILDER_FALLBACK_TYPES``, re-scans
    ``lines`` for a ``## Builder`` section using the same start/end detection
    logic, and returns those entries as flat (namespace ``None``) since
    ``## Builder`` never uses ``### `` sub-headings.
    """
    in_flt = False
    current_ns: str | None = None
    has_namespaces = False
    entries: list[tuple[str | None, str]] = []

    for line in lines:
        stripped = line.strip()
        if stripped == "## Files Likely Touched":
            in_flt = True
            current_ns = None
            continue
        if in_flt and stripped.startswith("## ") and not stripped.startswith("### "):
            break
        if not in_flt:
            continue
        if stripped.startswith("### "):
            heading = stripped[4:].strip().lower()
            current_ns = (
                "motor"
                if heading == "repo_motor"
                else "destino"
                if heading == "repo_destino"
                else "unknown"
            )
            has_namespaces = True
            continue
        if not stripped or stripped.startswith("---"):
            continue
        normalized = _normalize_flt_line(stripped)
        if normalized and _looks_like_path_token(normalized):
            entries.append((current_ns, normalized))

    if not entries and deliverable_type in _FLT_BUILDER_FALLBACK_TYPES:
        builder_entries = _parse_builder_fallback_entries(lines)
        if builder_entries:
            return False, builder_entries

    return has_namespaces, entries


def parse_flt_namespaced(
    work_plan_content: str,
    *,
    motor_root: Path,
    project_root: Path,
    delivery_authority: str = "repo_motor",
    deliverable_type: str = "code",
) -> dict[str, set[str]]:
    """Parse FLT section with optional namespace sub-headings.

    Returns a dict with keys ``"motor"`` and ``"destino"``, each holding a
    set of resolved absolute paths for that namespace.

    Namespace rules:
    - ``### repo_motor`` lines are resolved against ``motor_root``.
    - ``### repo_destino`` lines are resolved against ``project_root``.
    - Flat lines (no sub-heading) are routed by ``delivery_authority``.
    - Unknown sub-headings are skipped.

    WOT-2026-019j: ``deliverable_type`` (default ``"code"``) is forwarded to
    :func:`parse_flt_raw_buckets` so a ``mixed`` (or doc-type) ticket that
    declares its files under ``## Builder`` resolves a real whitelist through
    the ``--validate`` scope check too, not only through mark-ready.
    """
    buckets = parse_flt_raw_buckets(
        work_plan_content,
        delivery_authority=delivery_authority,
        deliverable_type=deliverable_type,
    )
    motor_files: set[str] = set()
    destino_files: set[str] = set()

    for normalized in buckets["motor"]:
        motor_files.add(str((motor_root / normalized).resolve()))
    for normalized in buckets["destino"]:
        destino_files.add(str((project_root / normalized).resolve()))

    return {"motor": motor_files, "destino": destino_files}


def parse_flt_raw_buckets(
    work_plan_content: str,
    *,
    delivery_authority: str = "repo_motor",
    deliverable_type: str = "code",
) -> dict[str, set[str]]:
    """Parse FLT into raw normalized path buckets without resolving roots.

    Returns a dict with ``motor`` and ``destino`` keys. Namespace rules match
    :func:`parse_flt_namespaced`, but paths remain relative and normalized with
    forward slashes so downstream consumers can choose their own root.
    """
    lines = work_plan_content.split("\n")
    _, entries = _parse_flt_section(lines, deliverable_type=deliverable_type)
    motor_files: set[str] = set()
    destino_files: set[str] = set()

    for ns, raw_path in entries:
        normalized = _normalize_raw_flt_path(raw_path)
        if ns == "motor":
            motor_files.add(normalized)
        elif ns == "destino":
            destino_files.add(normalized)
        elif ns == "unknown":
            continue
        elif delivery_authority == "repo_destino":
            destino_files.add(normalized)
        else:
            motor_files.add(normalized)

    return {"motor": motor_files, "destino": destino_files}


def parse_flt_raw_paths(
    work_plan_content: str,
    *,
    delivery_authority: str = "repo_motor",
    target: str = "authority",
    deliverable_type: str = "code",
) -> set[str]:
    """Return raw normalized FLT paths for one target view.

    ``target`` may be:
    - ``"authority"``: bucket for the productive repo declared by
      ``delivery_authority``.
    - ``"motor"`` / ``"destino"``: explicit bucket.
    - ``"all"``: union of both buckets.
    """
    buckets = parse_flt_raw_buckets(
        work_plan_content,
        delivery_authority=delivery_authority,
        deliverable_type=deliverable_type,
    )
    if target == "motor":
        return set(buckets["motor"])
    if target == "destino":
        return set(buckets["destino"])
    if target == "all":
        return buckets["motor"] | buckets["destino"]
    if target != "authority":
        raise ValueError(f"Unknown FLT raw target: {target}")
    if delivery_authority == "repo_destino":
        return set(buckets["destino"])
    return set(buckets["motor"])


def parse_forbidden_surfaces(
    work_plan_content: str,
    *,
    project_root: Path,
) -> set[str]:
    """Parse the ``## Forbidden Surfaces`` section into resolved absolute paths.

    WOT-2026-010i: Forbidden Surfaces are an executable handoff contract, not
    just audit prose. This reuses :func:`_extract_section_paths` so the same
    path-token heuristics that gate Files Likely Touched also gate forbidden
    routes (a bullet with trailing prose is ignored, not silently treated as a
    path).

    Only entries that look like real path tokens are returned; conceptual
    entries such as ``cache pytest`` or ``xdist/sharding`` that are not concrete
    repo paths are not resolvable to a file and so do not appear here. The
    handoff barrier matches changed files against the concrete paths only.

    Before: work_plan_content is the raw markdown; project_root is the root the
        relative forbidden paths resolve against.
    During: scans the ``## Forbidden Surfaces`` heading; extracts path tokens.
    After: returns a set of resolved absolute path strings (possibly empty).
    """
    lines = work_plan_content.split("\n")
    return _extract_section_paths(lines, "Forbidden Surfaces", project_root)


def parse_files_likely_touched(
    work_plan_content: str,
    *,
    project_root: Path,
    deliverable_type: str = "code",
) -> set[str]:
    """Parse Files Likely Touched entries and resolve them against project_root.

    For analysis/documentation/research tickets that use ``## Builder`` /
    ``## Read/inspect only`` / ``## Manager-only`` instead of
    ``## Files Likely Touched``, falls back to parsing the ``## Builder``
    section so the scope gate receives a real whitelist and does not emit a
    spurious "No Files Likely Touched" warning.
    """
    lines = work_plan_content.split("\n")
    files = _extract_section_paths(lines, "Files Likely Touched", project_root)
    if not files and deliverable_type in _FLT_BUILDER_FALLBACK_TYPES:
        files = _extract_section_paths(lines, "Builder", project_root)
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


def check_cross_root_contamination(
    *,
    other_root: Path,
    other_exclude: set[str],
    run_fn=subprocess.run,
) -> dict[str, set[str]]:
    """Return productive vs operational files found in the non-authority root.

    Before: other_root is a directory; it does not need to be a git repo when
        run_fn is injected (useful for tests).
    During: runs git status --porcelain -z in other_root directly; splits
        results by other_exclude into operational (excluded, OK) vs productive
        (not excluded, contamination).
    After: returns {"productive": set[str], "operational": set[str]} with
        absolute paths. Empty sets if git unavailable or no changes.
    """
    try:
        result = run_fn(
            ["git", "status", "--porcelain", "-z"],
            capture_output=True,
            text=True,
            cwd=other_root,
        )
    except FileNotFoundError:
        return {"productive": set(), "operational": set()}
    if result.returncode != 0 or not result.stdout:
        return {"productive": set(), "operational": set()}
    changed: set[str] = set()
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
    productive: set[str] = set()
    operational: set[str] = set()
    for rel in changed:
        abs_path = str((other_root / rel).resolve())
        if abs_path in other_exclude:
            operational.add(abs_path)
        else:
            productive.add(abs_path)
    return {"productive": productive, "operational": operational}


def check_scope_gate(
    work_plan_content: str,
    changed_files: set[str] | None,
    exclude_files: set[str],
    *,
    parse_files_likely_touched_fn,
    deliverable_type: str = "code",
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

    whitelist = parse_files_likely_touched_fn(
        work_plan_content, deliverable_type=deliverable_type
    )
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


def _relativize_scope_path(path: str, repo_root: Path | None) -> str:
    """Render a scope path without leaking absolute local paths (WOT-2026-016e).

    The scope override note is persisted to execution_log.md, which is part of
    the git history. Writing absolute paths there embeds the local username
    (``C:\\Users\\<user>\\...``) into the history and re-contaminates the repo.

    Paths inside ``repo_root`` are rendered as ``<REPO_ROOT>/rel/path`` with
    forward slashes. Paths that are not relativizable (outside the repo, or when
    ``repo_root`` is unknown) fall back to the basename, NEVER the absolute path.
    """
    if repo_root is not None:
        try:
            rel = Path(path).resolve().relative_to(repo_root)
            return "<REPO_ROOT>/" + rel.as_posix()
        except ValueError:
            # Not under repo_root: fall back to basename (no username leak).
            pass
    return Path(path).name


def record_scope_override(
    scope_override: str,
    problem_files: set[str],
    *,
    update_log_status_fn,
    repo_root: Path | str | None = None,
) -> None:
    """Persist a scope override note via the provided log callback.

    ``repo_root`` is used to relativize the affected file paths so the note
    persisted to execution_log.md never contains absolute local paths
    (WOT-2026-016e). If omitted, paths fall back to their basename.
    """
    root = Path(repo_root).resolve() if repo_root is not None else None
    rendered = sorted(_relativize_scope_path(p, root) for p in problem_files)
    note = f"Scope override: {scope_override}. Affected files: {', '.join(rendered)}"
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
