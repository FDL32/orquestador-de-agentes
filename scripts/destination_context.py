#!/usr/bin/env python3
"""
destination_context.py — Generate a compact context map of a destination project.

This script lives in the motor repository (orquestador_de_agentes) and is always
invoked from there. It reads the destination's motor_destination_link.json to
resolve the link, then generates a bounded map at
<project_root>/.agent/context/destination_map.md.

The map is designed for agents arriving at a destination for the first time:
it provides identity, operational state, git posture, a filtered tree, and
extracts of key manifest files — all within a configurable byte budget and
without requiring Node, Repomix, or Graphify.

Usage:
    python scripts/destination_context.py --bootstrap --project-root <repo_destino>
    python scripts/destination_context.py --bootstrap --project-root <repo_destino> --max-bytes 102400
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


DEFAULT_MAX_BYTES = 204800  # 200 KB
CONTEXT_DIR_REL = Path(".agent") / "context"
LINK_REL = Path(".agent") / "config" / "motor_destination_link.json"
DESTINATION_MAP_NAME = "destination_map.md"

# Directory basenames excluded from the filtered tree walk (matched on entry.name)
EXCLUDED_TREE_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        "__pycache__",
        ".ruff_cache",
        ".venv",
        ".session",
        ".tmp",
        "node_modules",
        ".opencode",
        ".claude",
        ".codex",
        ".claude-plugin",
        "graphify-out",
    }
)

# Relative paths (posix, from project_root) excluded from the tree walk. These
# need full-path matching because a bare basename would over-exclude (e.g. any
# "context" dir) and because entry.name never contains a slash.
EXCLUDED_TREE_RELPATHS: frozenset[str] = frozenset(
    {
        ".agent/runtime",
        ".agent/context",
        ".agent/_archive",
    }
)

# Files to extract previews for (truncatable manifest section)
KEY_DOCUMENTS: list[str] = [
    "AGENTS.md",
    "PROJECT.md",
    "README.md",
    "README",
    "CHANGELOG.md",
    "REPOSITORY_STRUCTURE.md",
]
KEY_CONFIGS: list[str] = [
    "pyproject.toml",
    "uv.lock",
    "pytest.ini",
]


def resolve_motor_link(project_root: Path) -> dict | None:
    """Read and validate motor_destination_link.json.

    Before: project_root/.agent/config/motor_destination_link.json may or
            may not exist.
    During: Reads JSON and validates it is a dict with a 'motor_root' key.
    After: Returns the parsed dict, or None if missing/malformed.
    """
    link_path = project_root / LINK_REL
    if not link_path.exists():
        return None
    try:
        data = json.loads(link_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        return data
    except (json.JSONDecodeError, OSError):
        return None


def get_git_info(project_root: Path) -> dict | None:
    """Get git status if available.

    Before: project_root/.git may or may not exist; git may not be installed.
    During: Runs git commands to extract branch, HEAD, and working tree status.
            Catches subprocess errors gracefully.
    After: Returns dict with git info, or None if not a git repo, or dict
           with 'error' key if git commands failed.
    """
    if not (project_root / ".git").exists():
        return None

    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            cwd=project_root,
            timeout=10,
        ).stdout.strip()

        head_short = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            cwd=project_root,
            timeout=10,
        ).stdout.strip()

        status = subprocess.run(
            ["git", "status", "--porcelain"],  # noqa: S607
            capture_output=True,
            text=True,
            cwd=project_root,
            timeout=10,
        ).stdout.strip()

        modified: list[str] = []
        if status:
            modified = [
                line[:2].strip() + " " + line[3:]
                for line in status.splitlines()
                if len(line) > 3
            ]

        return {
            "branch": branch or "unknown",
            "head_short": head_short or "unknown",
            "dirty": bool(status),
            "modified_count": len(modified),
            "modified": modified[:20],
        }
    except (subprocess.TimeoutExpired, OSError, subprocess.CalledProcessError):
        return {"error": "git command failed"}


def build_tree(project_root: Path, max_depth: int = 4) -> str:
    """Build a filtered directory tree.

    Before: project_root is a valid directory path.
    During: Walks entries sorted alphabetically (directories first), skipping
            excluded dirs and hidden files (except .agent). Stops at max_depth.
    After: Returns a multi-line string representing the tree.
    """
    lines: list[str] = []

    def _walk(dir_path: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(
                dir_path.iterdir(),
                key=lambda p: (not p.is_dir(), p.name.lower()),
            )
        except PermissionError:
            return

        for entry in entries:
            if entry.name in EXCLUDED_TREE_DIRS:
                continue
            if entry.relative_to(project_root).as_posix() in EXCLUDED_TREE_RELPATHS:
                continue
            # Skip hidden entries except .agent
            if entry.name.startswith(".") and entry.name != ".agent":
                continue

            indent = "  " * depth
            if entry.is_dir():
                lines.append(f"{indent}{entry.name}/")
                _walk(entry, depth + 1)
            else:
                lines.append(f"{indent}{entry.name}")

    _walk(project_root, 0)
    return "\n".join(lines)


def extract_file_preview(path: Path, max_lines: int = 30) -> str | None:
    """Extract the first max_lines of a text file as a preview.

    Before: path may or may not exist; may not be readable text.
    During: Reads file with UTF-8 encoding; handles errors gracefully.
    After: Returns string with truncated content, or None if unreadable.
    """
    if not path.exists() or not path.is_file():
        return None
    try:
        content = path.read_text(encoding="utf-8")
        lines = content.splitlines()
        preview = "\n".join(lines[:max_lines])
        if len(lines) > max_lines:
            preview += f"\n... ({len(lines) - max_lines} more lines)"
        return preview
    except (OSError, UnicodeDecodeError):
        return None


def _parse_work_plan(wp_path: Path, state: dict) -> None:
    """Parse work_plan.md metadata into state dict."""
    try:
        for line in wp_path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith("- **ID:**"):
                state["ticket_id"] = (
                    s.split("**ID:**", 1)[1].strip().rstrip("*").strip()
                )
            elif s.startswith("- **Title:**"):
                state["ticket_title"] = (
                    s.split("**Title:**", 1)[1].strip().rstrip("*").strip()
                )
            elif s.startswith("- **Priority:**"):
                state["priority"] = (
                    s.split("**Priority:**", 1)[1].strip().rstrip("*").strip()
                )
            elif s.startswith("- **Estado:**"):
                state["estado"] = (
                    s.split("**Estado:**", 1)[1].strip().rstrip("*").strip()
                )
    except OSError:
        pass


def _parse_turn_file(tm_path: Path, state: dict) -> bool:
    """Parse TURN.md role/action into state dict. Returns True if present."""
    try:
        for line in tm_path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith("| **ROL** |"):
                state["role"] = s.split("|")[2].strip().strip("*").strip()
            elif s.startswith("| **Accion** |") or s.startswith("| **Acción** |"):
                state["action"] = s.split("|")[2].strip().rstrip("*").strip()
        return True
    except OSError:
        return False


def _parse_state_file(sm_path: Path) -> tuple[bool, str | None]:
    """Read STATE.md content. Returns (present, content)."""
    try:
        content = sm_path.read_text(encoding="utf-8").strip()
        return True, content
    except OSError:
        return False, None


def get_operational_state(project_root: Path) -> dict:
    """Read canonical collaboration state from the project.

    Before: .agent/collaboration/ may or may not exist.
    During: Reads work_plan.md, STATE.md, TURN.md and lists PLAN_/AUDIT_ files.
    After: Returns dict with parsed metadata (id, title, estado, priority)
           and presence indicators for STATE.md, TURN.md, plans, audits.
    """
    collab_dir = project_root / ".agent" / "collaboration"
    state: dict = {}

    # Parse work_plan.md
    wp = collab_dir / "work_plan.md"
    if wp.exists():
        _parse_work_plan(wp, state)

    # Parse STATE.md
    sm = collab_dir / "STATE.md"
    present, content = _parse_state_file(sm) if sm.exists() else (False, None)
    state["state_md_present"] = present
    if content:
        state["state_md_content"] = content

    # Parse TURN.md
    tm = collab_dir / "TURN.md"
    state["turn_md_present"] = _parse_turn_file(tm, state) if tm.exists() else False

    # List active plans and audits
    plans = sorted(collab_dir.glob("PLAN_*.md"))
    if plans:
        state["active_plans"] = [p.name for p in plans]
    audits = sorted(collab_dir.glob("AUDIT_*.md"))
    if audits:
        state["active_audits"] = [a.name for a in audits]

    return state


def build_map(project_root: Path, max_bytes: int) -> str:  # noqa: C901
    """Build the full destination_map.md content with truncation.

    Before: project_root is a valid directory with optional .agent/ subtree.
            max_bytes > 0.
    During: Constructs six sections in memory, then serialises in priority
            order: identity (P1), operational (P1), git (P2), manifests (P3),
            tree (P4), graphify (P5). If total exceeds max_bytes, lower-priority
            sections are truncated or dropped.
    After: Returns markdown string that never exceeds max_bytes. Identity and
           operational state are always preserved.
    """
    sections: dict[str, str] = {}

    # ---- Section 1: Identity & Topology (PROTECTED) ----
    identity_lines: list[str] = [
        "# Destination Context Map",
        "",
        "## Identity & Topology",
        f"- **Destination root:** `{project_root.resolve()}`",
    ]

    motor_link = resolve_motor_link(project_root)
    if motor_link:
        identity_lines.append(
            f"- **Motor root:** `{motor_link.get('motor_root', 'unknown')}`"
        )
        identity_lines.append("- **Mode:** destination-hosted")
        identity_lines.append(
            f"- **Motor version:** {motor_link.get('motor_version', 'unknown')}"
        )
        identity_lines.append(
            f"- **Destination ID:** {motor_link.get('destination_id', 'unknown')}"
        )
        tp = motor_link.get("ticket_prefix")
        if tp:
            identity_lines.append(f"- **Ticket prefix:** {tp}")
        identity_lines.append("- **Motor link:** valid")
    else:
        identity_lines.append(
            "- **Motor root:** not resolvable (link missing or invalid)"
        )
        identity_lines.append("- **Mode:** standalone")
        identity_lines.append("- **Motor link:** absent")

    sections["identity"] = "\n".join(identity_lines) + "\n"

    # ---- Section 2: Operational State (PROTECTED) ----
    op_state = get_operational_state(project_root)
    op_lines: list[str] = [
        "",
        "## Operational State",
    ]
    if op_state.get("ticket_id"):
        op_lines.append(f"- **Active Ticket:** {op_state['ticket_id']}")
        if op_state.get("ticket_title"):
            op_lines.append(f"- **Title:** {op_state['ticket_title']}")
        if op_state.get("estado"):
            op_lines.append(f"- **Estado:** {op_state['estado']}")
        if op_state.get("priority"):
            op_lines.append(f"- **Priority:** {op_state['priority']}")
    else:
        op_lines.append("- **Active Ticket:** none")

    op_lines.append(
        f"- **STATE.md:** {'present' if op_state.get('state_md_present') else 'absent'}"
    )
    op_lines.append(
        f"- **TURN.md:** {'present' if op_state.get('turn_md_present') else 'absent'}"
    )

    if op_state.get("role"):
        op_lines.append(f"- **Current role:** {op_state['role']}")
    if op_state.get("action"):
        op_lines.append(f"- **Current action:** {op_state['action']}")
    if op_state.get("active_plans"):
        op_lines.append(f"- **Active plans:** {', '.join(op_state['active_plans'])}")
    if op_state.get("active_audits"):
        op_lines.append(f"- **Active audits:** {', '.join(op_state['active_audits'])}")

    # Include STATE.md raw content if present
    state_content = op_state.get("state_md_content")
    if state_content:
        op_lines.append("")
        op_lines.append("```")
        op_lines.append(state_content)
        op_lines.append("```")

    sections["operational"] = "\n".join(op_lines) + "\n"

    # ---- Section 3: Git State (best effort / truncatable after P1) ----
    git_info = get_git_info(project_root)
    git_lines: list[str] = [
        "",
        "## Git State",
    ]
    if git_info is None:
        git_lines.append("- **Status:** no git repository or .git not found")
    elif "error" in git_info:
        git_lines.append(
            "- **Status:** error reading git state (git unavailable or timeout)"
        )
    else:
        git_lines.append(f"- **Branch:** {git_info['branch']}")
        git_lines.append(f"- **HEAD:** {git_info['head_short']}")
        git_lines.append(
            f"- **Working tree:** {'dirty' if git_info['dirty'] else 'clean'}"
        )
        if git_info.get("modified"):
            git_lines.append(
                f"- **Modified files ({git_info['modified_count']} total, showing first 20):**"
            )
            git_lines.extend(f"  - {mf}" for mf in git_info["modified"][:20])

    sections["git"] = "\n".join(git_lines) + "\n"

    # ---- Section 4: Contracts & Manifests (truncatable) ----
    manifest_lines: list[str] = [
        "",
        "## Contracts & Manifests",
    ]
    for name in KEY_DOCUMENTS + KEY_CONFIGS:
        path = project_root / name
        preview = extract_file_preview(path)
        if preview:
            manifest_lines.append(f"\n### {name}")
            manifest_lines.append("```")
            manifest_lines.append(preview)
            manifest_lines.append("```")

    sections["manifests"] = "\n".join(manifest_lines) + "\n"

    # ---- Section 5: Repository Structure (truncatable) ----
    tree_lines: list[str] = [
        "",
        "## Repository Structure",
    ]
    tree = build_tree(project_root)
    if tree:
        tree_lines.append("```")
        tree_lines.append(tree)
        tree_lines.append("```")
    else:
        tree_lines.append("(empty or unreadable)")

    sections["tree"] = "\n".join(tree_lines) + "\n"

    # ---- Section 6: Graphify Summary (truncatable, optional) ----
    graphify_dir = project_root / "graphify-out"
    graph_lines: list[str] = []
    if graphify_dir.exists():
        graph_lines.append("")
        graph_lines.append("## Graphify Summary")
        report = graphify_dir / "GRAPH_REPORT.md"
        if report.exists():
            preview = extract_file_preview(report, max_lines=20)
            if preview:
                graph_lines.append("```")
                graph_lines.append(preview)
                graph_lines.append("```")
        else:
            graph_lines.append("(graphify-out/ exists but no GRAPH_REPORT.md found)")

    sections["graphify"] = "\n".join(graph_lines) + "\n" if graph_lines else ""

    # ---- Assemble with priority-based truncation ----
    protected = sections["identity"] + sections["operational"]
    protected_bytes = len(protected.encode("utf-8"))

    if protected_bytes > max_bytes:
        # Extreme case: identity + operational alone exceed budget
        result = protected.encode("utf-8")[:max_bytes].decode("utf-8", errors="replace")
        return result

    truncation_note = "\n\n*(map truncated to fit byte budget)*\n"
    reserve = len(truncation_note.encode("utf-8"))
    remaining = max_bytes - protected_bytes
    result = protected

    # Priority order: git -> manifests -> tree -> graphify
    for section_key in ["git", "manifests", "tree", "graphify"]:
        content = sections.get(section_key, "")
        if not content:
            continue
        section_bytes = len(content.encode("utf-8"))
        if section_bytes + reserve <= remaining:
            result += content
            remaining -= section_bytes
        else:
            # Reserve space for the truncation note; fit what we can
            max_section_bytes = max(0, remaining - reserve)
            if max_section_bytes > 0:
                encoded = content.encode("utf-8")
                truncated = encoded[:max_section_bytes].decode(
                    "utf-8", errors="replace"
                )
                result += truncated
                if not truncated.endswith("\n"):
                    result += "\n"
            result += truncation_note
            break

    # Hard safety trim: ensure result never exceeds max_bytes
    result_bytes = result.encode("utf-8")
    if len(result_bytes) > max_bytes:
        result = result_bytes[:max_bytes].decode("utf-8", errors="replace")

    return result


def _write_map(context_dir: Path, content: str) -> Path:
    """Write the map file and return its path.

    Before: context_dir path may or may not exist.
    During: Creates parent directories; writes content with UTF-8.
    After: Returns the path to the written file.
    """
    context_dir.mkdir(parents=True, exist_ok=True)
    map_path = context_dir / DESTINATION_MAP_NAME
    map_path.write_text(content, encoding="utf-8")
    return map_path


def _print_summary(
    project_root: Path, link: dict, map_path: Path, content: str
) -> None:
    """Print a compact summary for the agent reading stdout."""
    actual_bytes = len(content.encode("utf-8"))
    print(f"[OK] Destination map generated: {map_path}")
    print(f"[OK] Size: {actual_bytes} bytes")
    print("")
    print("--- Destination Context Summary ---")
    print(f"Project: {project_root.name}")
    print(f"Motor:   {link.get('motor_root', 'unknown')}")
    print("Mode:    destination-hosted")

    collab = project_root / ".agent" / "collaboration"
    wp = collab / "work_plan.md"
    if wp.exists():
        try:
            for line in wp.read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if s.startswith("- **ID:**"):
                    tid = s.split("**ID:**", 1)[1].strip().rstrip("*").strip()
                    print(f"Ticket:  {tid}")
                elif s.startswith("- **Title:**"):
                    title = s.split("**Title:**", 1)[1].strip().rstrip("*").strip()
                    print(f"Title:   {title}")
        except OSError:
            pass

    print("")
    print("Continue with: rg, read, or open your target files under the project root.")
    print(f"Full map at: {map_path}")


def main(argv: list[str] | None = None) -> int:
    """Entry point for destination_context.py.

    Before: Python 3.10+; argv may be None (uses sys.argv).
    During: Parses arguments, validates project-root, resolves motor link,
            builds and writes the map, prints summary.
    After: Returns 0 on success, 1 on error.
    """
    parser = argparse.ArgumentParser(
        description="Generate a compact context map of a destination project.",
    )
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        required=True,
        help="Generate the destination context map",
    )
    parser.add_argument(
        "--project-root",
        type=str,
        default=".",
        help="Path to the destination project root (default: current directory)",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=DEFAULT_MAX_BYTES,
        help=f"Maximum size of the map in bytes (default: {DEFAULT_MAX_BYTES})",
    )

    args = parser.parse_args(argv)

    if not args.bootstrap:
        print("Error: --bootstrap is required", file=sys.stderr)
        return 1

    if args.max_bytes < 256:
        print("Error: --max-bytes must be at least 256", file=sys.stderr)
        return 1

    project_root = Path(args.project_root).resolve()
    if not project_root.is_dir():
        print(f"Error: project root does not exist: {project_root}", file=sys.stderr)
        return 1

    # Verify motor_destination_link.json exists and is valid
    link = resolve_motor_link(project_root)
    if link is None:
        rel = LINK_REL.as_posix()
        print(
            f"Error: {rel} not found or invalid at {project_root / LINK_REL}",
            file=sys.stderr,
        )
        print(
            "Run install_agent_system.py --install or --sync first to create the link.",
            file=sys.stderr,
        )
        return 1

    # Build the map
    content = build_map(project_root, max_bytes=args.max_bytes)

    # Write to .agent/context/destination_map.md
    context_dir = project_root / CONTEXT_DIR_REL
    map_path = _write_map(context_dir, content)

    _print_summary(project_root, link, map_path, content)
    return 0


if __name__ == "__main__":
    sys.exit(main())
