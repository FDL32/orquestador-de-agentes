"""
Graph Context Adapter - Lightweight ticket-scoped context extractor.

This adapter reads existing graphify-out artifacts (graph.json and GRAPH_REPORT.md)
and emits a compact ## Project Context block for the active ticket.

Before:
    - Requires graphify-out/graph.json and graphify-out/GRAPH_REPORT.md to exist.
    - Reads the active work_plan.md to determine ticket scope.

During:
    - Parses the graph structure to identify file nodes and edges.
    - Extracts collaboration files relevant to the active ticket.
    - Computes immediate graph neighbors for context files.
    - Generates a deterministic, compact summary (max 30 lines).

After:
    - Returns a string containing the ## Project Context markdown block.
    - Raises FileNotFoundError if graphify artifacts are missing.
    - Raises ValueError if graph.json is malformed.
"""

import json
import re
import sys
from pathlib import Path
from typing import Any


def get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent


def get_graphify_dir() -> Path:
    """Get the graphify output directory."""
    return get_project_root() / "graphify-out"


def get_collaboration_dir() -> Path:
    """Get the collaboration directory."""
    return get_project_root() / ".agent" / "collaboration"


def load_graph() -> dict[str, Any]:
    """
    Load the graph.json file.

    Before: graph.json must exist in graphify-out/.
    During: Reads and parses JSON.
    After: Returns parsed graph data or raises FileNotFoundError/ValueError.
    """
    graph_path = get_graphify_dir() / "graph.json"
    if not graph_path.exists():
        raise FileNotFoundError(f"Graph file not found: {graph_path}")

    with open(graph_path, encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in graph.json: {e}") from e


def load_graph_report() -> str:
    """
    Load the GRAPH_REPORT.md file.

    Before: GRAPH_REPORT.md must exist in graphify-out/.
    During: Reads the markdown file.
    After: Returns file content or raises FileNotFoundError.
    """
    report_path = get_graphify_dir() / "GRAPH_REPORT.md"
    if not report_path.exists():
        raise FileNotFoundError(f"Graph report not found: {report_path}")

    return report_path.read_text(encoding="utf-8")


def parse_report_stats(report_content: str) -> dict[str, int]:
    """
    Parse only the statistics section from GRAPH_REPORT.md.

    The adapter intentionally ignores the project file inventory and consumes
    only the compact statistics block so the prompt budget stays tight.
    """
    stats: dict[str, int] = {}
    in_stats = False

    for raw_line in report_content.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            if in_stats:
                break
            in_stats = bool(re.match(r"^##\s+Estad", line, flags=re.IGNORECASE))
            continue

        if not in_stats or not line.startswith("- "):
            continue

        payload = line[2:].strip().lower()
        match = re.search(r"(\d+)", payload)
        if not match:
            continue

        value = int(match.group(1))
        if payload.startswith("nodos totales:"):
            stats["total_nodes"] = value
        elif payload.startswith("python:"):
            stats["python_nodes"] = value
        elif payload.startswith("markdown:"):
            stats["markdown_nodes"] = value
        elif payload.startswith("enlaces"):
            stats["edges"] = value

    return stats


def format_report_summary(stats: dict[str, int]) -> str | None:
    """Format a one-line summary from the parsed report statistics."""
    if not stats:
        return None

    parts: list[str] = []
    if "total_nodes" in stats:
        parts.append(f"{stats['total_nodes']} nodes")
    if "python_nodes" in stats and "markdown_nodes" in stats:
        parts.append(
            f"({stats['python_nodes']} python, {stats['markdown_nodes']} markdown)"
        )
    if "edges" in stats:
        parts.append(f"{stats['edges']} links")

    if not parts:
        return None

    return f"- **Graph report:** {' '.join(parts)}"


def load_work_plan() -> str:
    """
    Load the active work_plan.md file.

    Before: work_plan.md must exist in .agent/collaboration/.
    During: Reads the markdown file.
    After: Returns file content or raises FileNotFoundError.
    """
    work_plan_path = get_collaboration_dir() / "work_plan.md"
    if not work_plan_path.exists():
        raise FileNotFoundError(f"Work plan not found: {work_plan_path}")

    return work_plan_path.read_text(encoding="utf-8")


def extract_active_ticket_id(work_plan_content: str) -> str | None:
    """
    Extract the active ticket ID from work_plan.md.

    Before: Requires work_plan.md content as string.
    During: Searches for WP-YYYY-NNN pattern in metadata section.
    After: Returns ticket ID (e.g., 'WP-2026-147') or None if not found.
    """
    match = re.search(r"\*\*ID:\*\*\s*(WP-\d{4}-\d{3})", work_plan_content)
    if match:
        return match.group(1)

    match = re.search(r"#\s*Work Plan\s*-\s*(WP-\d{4}-\d{3})", work_plan_content)
    if match:
        return match.group(1)

    return None


def extract_files_likely_touched(work_plan_content: str) -> set[str]:
    """
    Parse Files Likely Touched section from work_plan.md.

    Before: Requires work_plan.md content as string.
    During: Finds the section and extracts file paths.
    After: Returns set of file paths or empty set if section not found.
    """
    lines = work_plan_content.split("\n")
    in_section = False
    files = set()

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## Files Likely Touched"):
            in_section = True
            continue
        if in_section:
            if stripped.startswith("## "):
                break
            if stripped.startswith("- "):
                file_path = stripped[2:].strip().strip("`")
                if file_path and not file_path.startswith("#"):
                    files.add(file_path)

    return files


def get_immediate_neighbors(graph: dict[str, Any], target_files: set[str]) -> set[str]:
    """
    Get immediate neighbors (connected files) from the graph.

    Before: Requires graph dict with 'edges' key and target file set.
    During: Iterates through edges to find connections to/from target files.
    After: Returns set of neighbor file paths (excluding targets themselves).
    """
    neighbors = set()
    edges = graph.get("edges", [])

    for edge in edges:
        source = edge.get("source", "")
        target = edge.get("target", "")

        if source in target_files and target not in target_files:
            neighbors.add(target)
        elif target in target_files and source not in target_files:
            neighbors.add(source)

    return neighbors


def categorize_files(
    nodes: dict[str, Any], files: set[str]
) -> dict[str, list[tuple[str, dict[str, Any]]]]:
    """
    Categorize files by type (Python, Markdown, Other).

    Before: Requires nodes dict and set of file paths.
    During: Groups files by their type field from graph nodes.
    After: Returns dict with 'python', 'markdown', 'other' keys.
    """
    categorized: dict[str, list[tuple[str, dict[str, Any]]]] = {
        "python": [],
        "markdown": [],
        "other": [],
    }

    for file_path in files:
        node_info = nodes.get(file_path, {})
        file_type = node_info.get("type", "unknown")

        if file_type == "python":
            categorized["python"].append((file_path, node_info))
        elif file_type == "markdown":
            categorized["markdown"].append((file_path, node_info))
        else:
            categorized["other"].append((file_path, node_info))

    return categorized


def format_file_size(size_bytes: int) -> str:
    """Format file size in human-readable form."""
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    elif size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes} B"


def _append_line(lines: list[str], line: str, remaining_lines: int) -> int:
    """Append a line if there is remaining budget."""
    if remaining_lines <= 0:
        return 0
    lines.append(line)
    return remaining_lines - 1


def _format_context_section(
    lines: list[str],
    categorized: dict[str, list[tuple[str, dict[str, Any]]]],
    section_name: str,
    file_type: str,
    remaining_lines: int,
    max_entries: int,
) -> int:
    """
    Format a section of files (Python or Markdown) for the context.

    Returns the updated remaining_lines count.
    """
    files = categorized.get(file_type, [])
    if not files or remaining_lines <= 0:
        return remaining_lines

    remaining_lines = _append_line(lines, f"### {section_name}", remaining_lines)
    for file_path, info in sorted(files)[:max_entries]:
        if remaining_lines <= 0:
            return 0
        size = info.get("size_bytes", 0)
        remaining_lines = _append_line(
            lines, f"- `{file_path}` ({format_file_size(size)})", remaining_lines
        )

    if len(files) > max_entries and remaining_lines > 0:
        more_count = len(files) - max_entries
        remaining_lines = _append_line(
            lines,
            f"- ... and {more_count} more {section_name.replace(' Files', '').lower()} files",
            remaining_lines,
        )

    remaining_lines = _append_line(lines, "", remaining_lines)
    return remaining_lines


def _build_context_lines(
    ticket_id: str | None,
    all_context_files: set[str],
    target_files: set[str],
    categorized: dict[str, list[tuple[str, dict[str, Any]]]],
    report_summary: str | None,
    max_lines: int,
) -> list[str]:
    """Build the context lines list."""
    lines: list[str] = []
    remaining_lines = max_lines
    remaining_lines = _append_line(lines, "## Project Context", remaining_lines)
    remaining_lines = _append_line(lines, "", remaining_lines)

    if ticket_id:
        remaining_lines = _append_line(
            lines, f"- **Ticket:** {ticket_id}", remaining_lines
        )

    total_files = len(all_context_files)
    remaining_lines = _append_line(
        lines, f"- **Scope:** {total_files} file(s) in context", remaining_lines
    )
    if report_summary:
        remaining_lines = _append_line(lines, report_summary, remaining_lines)
    remaining_lines = _append_line(lines, "", remaining_lines)

    remaining_lines = _format_context_section(
        lines,
        categorized,
        "Python Files",
        "python",
        remaining_lines,
        max_entries=4,
    )

    remaining_lines = _format_context_section(
        lines,
        categorized,
        "Markdown Files",
        "markdown",
        remaining_lines,
        max_entries=3,
    )

    if target_files and remaining_lines > 0:
        remaining_lines = _append_line(
            lines, "### Ticket Scope (Files Likely Touched)", remaining_lines
        )
        for file_path in sorted(target_files):
            if remaining_lines <= 0:
                break
            remaining_lines = _append_line(lines, f"- `{file_path}`", remaining_lines)

    if len(lines) > max_lines:
        raise ValueError(
            f"Generated context exceeds line budget: {len(lines)} > {max_lines}"
        )

    return lines


def _load_report_summary_from_path(report_path: Path) -> str | None:
    """Load and compact GRAPH_REPORT.md if it exists."""
    try:
        report_content = report_path.read_text(encoding="utf-8")
    except OSError:
        return None

    return format_report_summary(parse_report_stats(report_content))


def generate_project_context(
    max_lines: int = 30,
) -> str:
    """
    Generate a compact ## Project Context block for the active ticket.

    Before:
        - graphify-out/graph.json must exist.
        - graphify-out/GRAPH_REPORT.md must exist.
        - .agent/collaboration/work_plan.md must exist.

    During:
        - Loads and parses all input files.
        - Extracts active ticket ID and Files Likely Touched.
        - Computes immediate graph neighbors.
        - Categorizes files by type.
        - Formats a compact summary within line limit.

    After:
        - Returns markdown string with ## Project Context block.
        - Block does not exceed max_lines (default 30).
        - Raises FileNotFoundError or ValueError on input errors.
    """
    graph = load_graph()
    nodes = graph.get("nodes", {})

    work_plan_content = load_work_plan()
    ticket_id = extract_active_ticket_id(work_plan_content)
    target_files = extract_files_likely_touched(work_plan_content)
    try:
        report_content = load_graph_report()
    except FileNotFoundError:
        report_summary = None
    else:
        report_summary = format_report_summary(parse_report_stats(report_content))

    neighbors = get_immediate_neighbors(graph, target_files)
    all_context_files = target_files | neighbors

    categorized = categorize_files(nodes, all_context_files)
    lines = _build_context_lines(
        ticket_id,
        all_context_files,
        target_files,
        categorized,
        report_summary,
        max_lines,
    )

    return "\n".join(lines)


def generate_context_for_destination(
    dest_project_root: Path,
    max_lines: int = 30,
) -> str | None:
    """
    Generate project context for an external destination project.

    Before:
        - dest_project_root must be a valid path with graphify-out/.
        - graphify artifacts must exist in destination.

    During:
        - Loads graph and work_plan from destination.
        - Generates context block using same logic as generate_project_context.

    After:
        - Returns context block string or None if artifacts missing.
    """
    graph_path = dest_project_root / "graphify-out" / "graph.json"
    work_plan_path = dest_project_root / ".agent" / "collaboration" / "work_plan.md"

    if not graph_path.exists() or not work_plan_path.exists():
        return None

    try:
        with open(graph_path, encoding="utf-8") as f:
            graph = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    try:
        work_plan_content = work_plan_path.read_text(encoding="utf-8")
    except OSError:
        return None

    report_summary = _load_report_summary_from_path(
        dest_project_root / "graphify-out" / "GRAPH_REPORT.md"
    )
    nodes = graph.get("nodes", {})
    ticket_id = extract_active_ticket_id(work_plan_content)
    target_files = extract_files_likely_touched(work_plan_content)
    neighbors = get_immediate_neighbors(graph, target_files)
    all_context_files = target_files | neighbors
    categorized = categorize_files(nodes, all_context_files)

    lines = _build_context_lines(
        ticket_id,
        all_context_files,
        target_files,
        categorized,
        report_summary,
        max_lines,
    )
    return "\n".join(lines)


def main() -> None:
    """Main entry point for CLI usage."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate compact project context from graphify artifacts"
    )
    parser.add_argument(
        "--max-lines",
        type=int,
        default=30,
        help="Maximum lines in output (default: 30)",
    )
    parser.add_argument(
        "--destination",
        type=str,
        help="Path to destination project (optional)",
    )

    args = parser.parse_args()

    try:
        if args.destination:
            dest_root = Path(args.destination)
            context = generate_context_for_destination(dest_root, args.max_lines)
            if context is None:
                print("No graphify artifacts found in destination.", file=sys.stderr)
                sys.exit(1)
        else:
            context = generate_project_context(args.max_lines)

        print(context)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
