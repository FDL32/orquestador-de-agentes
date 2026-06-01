#!/usr/bin/env python3
"""Claude Memory Mirror — local opt-in sync with Claude memory.

Provides three operating modes:

  --export           Export observations.jsonl entries to
                     ~/.claude/projects/<project-slug>/memory/ as markdown files
                     with YAML frontmatter (one .md per observation).

  --import           Import Claude memory markdown files written by this tool
                     back into observations.jsonl, deduplicating by observation id.

  --check-freshness  Compare mtime of observations.jsonl vs latest exported .md
                     file in the mirror directory to report which is fresher.

All modes support:
  --dry-run  Preview changes without writing (default behavior).
  --apply    Actually write changes.

Architecture decision (WT-2026-192):
  ~/.claude/ is LOCAL PRIVATE developer storage, NEVER a canonical source of truth
  for the portable engine.  This utility is a LOCAL OPT-IN convenience only.
  install, --validate, and --session-close do NOT depend on this script or on
  ~/.claude/ being present.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MEMORY_DIR = Path(".agent") / "runtime" / "memory"
_OBSERVATIONS_FILE = "observations.jsonl"

# Frontmatter metadata keys that are written/read by this tool.
_META_KEYS = {"domain", "confidence", "source", "timestamp"}


# ---------------------------------------------------------------------------
# Project slug derivation  (deterministic, closed algorithm per WT-2026-192)
# ---------------------------------------------------------------------------


def derive_project_slug(project_root: Path | None = None) -> str:
    """Derive the Claude project slug from a project root path.

    Algorithm (closed, from work plan WT-2026-192):
      1. s = str(project_root)
      2. if s[1] == ':' -> s = s[0].lower() + s[1:]
      3. s.replace(":\\\\", "--")
      4. Replace all '\\\\', '/', '_' with '-'

    Args:
        project_root: Project root path.  Auto-detected when None.

    Returns:
        Deterministic slug like ``c--Users-fdl-Proyectos-Python-z-scripts``.
    """
    if project_root is None:
        project_root = _resolve_project_root()

    s = str(project_root.resolve())
    if len(s) >= 2 and s[1] == ":":
        s = s[0].lower() + s[1:]
    s = s.replace(":\\", "--")
    s = s.replace("\\", "-").replace("/", "-").replace("_", "-")
    return s


def _resolve_project_root() -> Path:
    """Resolve the project root path using the canonical runtime module."""
    try:
        from runtime.project_root import resolve_project_root

        return resolve_project_root()
    except ImportError:
        return Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def get_claude_memory_dir(project_root: Path | None = None) -> Path:
    """Return ``~/.claude/projects/<slug>/memory/``.

    Args:
        project_root: Optional explicit project root.

    Returns:
        Absolute path to the Claude memory mirror directory.
    """
    slug = derive_project_slug(project_root)
    return Path.home() / ".claude" / "projects" / slug / "memory"


def get_observations_path(project_root: Path | None = None) -> Path:
    """Return the path to ``observations.jsonl`` in the canonical workspace.

    Args:
        project_root: Optional explicit project root.

    Returns:
        Absolute path to observations.jsonl.
    """
    root = project_root or _resolve_project_root()
    return root / _MEMORY_DIR / _OBSERVATIONS_FILE


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def _read_observations(path: Path) -> list[dict[str, Any]]:
    """Read observations from a JSONL file safely.

    Args:
        path: Path to a ``.jsonl`` file.

    Returns:
        List of observation dicts (empty on any error / missing file).
    """
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    observations: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            if isinstance(entry, dict):
                observations.append(entry)
        except json.JSONDecodeError:
            continue
    return observations


def _write_observations(path: Path, observations: list[dict[str, Any]]) -> None:
    """Write a list of observation dicts to a JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(obs, ensure_ascii=False) for obs in observations)
    if text:
        text += "\n"
    path.write_text(text, encoding="utf-8")


def _generate_obs_id(observation: dict[str, Any]) -> str:
    """Generate a stable, deterministic ID for an observation.

    If the observation already has an ``id`` field, it is returned as-is.
    Otherwise a short hash of ``topic + signal`` is used.

    Returns:
        A kebab-case string suitable as a Claude memory ``name``.
    """
    if (
        "id" in observation
        and isinstance(observation["id"], str)
        and observation["id"].strip()
    ):
        return observation["id"].strip()

    topic = str(observation.get("topic", "general") or "general")
    signal = str(observation.get("signal", "") or "")
    hash_input = f"{topic}:{signal}"
    h = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()[:10]
    return f"{topic}-{h}"


# ---------------------------------------------------------------------------
# Export:  observations.jsonl -> Claude memory markdown files
# ---------------------------------------------------------------------------


def _observation_to_md(observation: dict[str, Any]) -> str:
    """Convert a single observation dict to a markdown string with YAML frontmatter.

    Mapping (closed, WT-2026-192):

      +---------------+---------------+------------------------------------+
      | Field         | Frontmatter   | Notes                              |
      +---------------+---------------+------------------------------------+
      | id            | name          | generated if absent                |
      | signal        | (body)        | full markdown body                 |
      | domain        | metadata.*    |                                    |
      | confidence    | metadata.*    |                                    |
      | source        | metadata.*    |                                    |
      | timestamp     | metadata.*    |                                    |
      +---------------+---------------+------------------------------------+
    """
    obs_id = _generate_obs_id(observation)
    signal = str(observation.get("signal", "") or "").strip()

    # Build frontmatter lines
    fm_lines: list[str] = ["---", f"name: {obs_id}"]

    # Build metadata subsection
    meta: dict[str, Any] = {}
    for key in _META_KEYS:
        if key in observation and observation[key] is not None:
            meta[key] = observation[key]

    if meta:
        fm_lines.append("metadata:")
        for k, v in meta.items():
            if isinstance(v, str):
                escaped = v.replace('"', '\\"')
                fm_lines.append(f'  {k}: "{escaped}"')
            elif isinstance(v, (int, float)):
                fm_lines.append(f"  {k}: {v}")
            else:
                fm_lines.append(f'  {k}: "{v}"')

    fm_lines.append("---")
    fm_lines.append("")

    # Body is the observation signal
    fm_lines.append(signal if signal else "(empty)")

    return "\n".join(fm_lines) + "\n"


def do_export(
    observations_path: Path,
    claude_dir: Path,
    *,
    apply: bool,
) -> tuple[int, list[str]]:
    """Export observations to Claude memory markdown files.

    Args:
        observations_path: Path to observations.jsonl.
        claude_dir:        Target Claude memory directory.
        apply:             If True write files; if False dry-run only.

    Returns:
        (exit_code, messages)
    """
    observations = _read_observations(observations_path)
    if not observations:
        return 0, ["No observations found in workspace memory. Nothing to export."]

    if not apply:
        return 0, [
            f"[DRY-RUN] Would export {len(observations)} observation(s) to {claude_dir}",
        ]

    claude_dir.mkdir(parents=True, exist_ok=True)

    exported = 0
    skipped = 0
    messages: list[str] = []

    for obs in observations:
        obs_id = _generate_obs_id(obs)
        md_content = _observation_to_md(obs)
        md_path = claude_dir / f"{obs_id}.md"

        if md_path.exists():
            # Overwrite silently — export is a push operation
            pass

        try:
            md_path.write_text(md_content, encoding="utf-8")
            exported += 1
        except OSError as e:
            messages.append(f"  WARNING: could not write {md_path.name}: {e}")
            skipped += 1

    summary = f"Exported {exported} observation(s) to {claude_dir}"
    if skipped:
        summary += f" ({skipped} skipped due to errors)"
    messages.insert(0, summary)
    return 0, messages


# ---------------------------------------------------------------------------
# Import:  Claude memory markdown files -> observations.jsonl
# ---------------------------------------------------------------------------


def _parse_nested_metadata(
    lines: list[str],
    start: int,
    end: int,
) -> dict[str, Any]:
    """Parse nested metadata block (indented lines under ``metadata:``).

    Args:
        lines: All frontmatter lines (between ``---`` markers).
        start: Index of ``metadata:`` line.
        end:   Index of closing ``---`` line.

    Returns:
        Dict of nested key-value pairs.
    """
    result: dict[str, Any] = {}
    for line in lines[start + 1 : end]:
        stripped = line.strip()
        if not stripped or stripped.startswith("- "):
            continue
        if not (line.startswith(" ") or line.startswith("\t")):
            break  # Not indented -> end of metadata block
        if ":" in stripped:
            nk, nv = stripped.split(":", 1)
            result[nk.strip()] = nv.strip().strip('"').strip("'")
    return result


def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Parse a markdown string that starts with YAML frontmatter.

    Only recognises the frontmatter format written by ``_observation_to_md``.
    Other formats are ignored (returns empty metadata).

    Args:
        content: Raw markdown string.

    Returns:
        ``(metadata_dict, body_string)``.
    """
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, content

    end_idx: int | None = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        return {}, content

    metadata: dict[str, Any] = {}

    for i in range(1, end_idx):
        stripped = lines[i].strip()
        if not stripped or stripped == "---":
            continue

        if stripped == "metadata:":
            metadata["metadata"] = _parse_nested_metadata(lines, i, end_idx)
            continue

        if ":" in stripped:
            k, v = stripped.split(":", 1)
            metadata[k.strip()] = v.strip().strip('"').strip("'")

    body = "\n".join(lines[end_idx + 1 :]).strip()
    return metadata, body


def _md_to_observation(metadata: dict[str, Any], body: str) -> dict[str, Any]:
    """Convert parsed frontmatter + body back to an observation dict.

    Reverse mapping of ``_observation_to_md``:

      +-----------------+-----------+
      | Frontmatter     | Field     |
      +-----------------+-----------+
      | name            | id        |
      | (body)          | signal    |
      | metadata.domain | domain    |
      | metadata.conf   | confidenc |
      | metadata.source | source    |
      | metadata.ts     | timestamp |
      +-----------------+-----------+
    """
    observation: dict[str, Any] = {}

    if "name" in metadata:
        observation["id"] = str(metadata["name"])

    if body:
        observation["signal"] = body

    inner_meta = metadata.get("metadata", {})
    if isinstance(inner_meta, dict):
        for key in _META_KEYS:
            if key in inner_meta and inner_meta[key] is not None:
                value = inner_meta[key]
                if key == "confidence":
                    with contextlib.suppress(ValueError, TypeError):
                        value = float(value)
                observation[key] = value

    return observation


def _process_import_file(
    md_path: Path,
    existing_ids: set[str],
) -> dict[str, Any] | None:
    """Process a single .md file for import.

    Args:
        md_path:      Path to the markdown file.
        existing_ids: Set of observation IDs already present.

    Returns:
        Observation dict if the file should be imported, or None if skipped.
    """
    try:
        content = md_path.read_text(encoding="utf-8")
    except OSError:
        return None

    frontmatter, body = _parse_frontmatter(content)
    obs_name = frontmatter.get("name", "")

    # Only process files written by our --export
    if not obs_name:
        return None

    inner_meta = frontmatter.get("metadata", {})
    if not isinstance(inner_meta, dict) or not any(k in inner_meta for k in _META_KEYS):
        return None

    # Dedupe by id
    if obs_name in existing_ids:
        return None

    observation = _md_to_observation(frontmatter, body)

    # Ensure source provenance
    if not observation.get("source"):
        observation["source"] = "claude-memory-mirror"

    existing_ids.add(obs_name)
    return observation


def do_import(
    observations_path: Path,
    claude_dir: Path,
    *,
    apply: bool,
) -> tuple[int, list[str]]:
    """Import Claude memory entries into observations.jsonl.

    Only reads ``.md`` files that were previously written by ``do_export``
    (detected by presence of a ``name`` field in frontmatter).

    Dedupes by ``id`` (``name`` in frontmatter): entries whose ``id`` already
    exists in observations.jsonl are silently skipped.

    Args:
        observations_path: Path to observations.jsonl.
        claude_dir:        Source Claude memory directory.
        apply:             If True write changes; if False dry-run.

    Returns:
        (exit_code, messages)
    """
    if not claude_dir.exists():
        return 0, [
            f"Claude memory directory not found: {claude_dir}. "
            "Run '--export --apply' first to create the mirror.",
        ]

    existing = _read_observations(observations_path)
    existing_ids: set[str] = set()
    for obs in existing:
        oid = obs.get("id")
        if isinstance(oid, str) and oid:
            existing_ids.add(oid)

    md_files = sorted(claude_dir.glob("*.md"))
    if not md_files:
        return 0, [f"No markdown files found in {claude_dir}"]

    imported: list[dict[str, Any]] = []

    for md_path in md_files:
        obs = _process_import_file(md_path, existing_ids)
        if obs is not None:
            imported.append(obs)

    messages: list[str] = []
    if not apply:
        messages.append(f"[DRY-RUN] Would import {len(imported)} new observation(s)")
    else:
        if not imported:
            return 0, [
                "No new observations to import (all already present or skipped)."
            ]

        all_observations = existing + imported
        _write_observations(observations_path, all_observations)
        messages.append(f"Imported {len(imported)} observation(s)")

    return 0, messages


# ---------------------------------------------------------------------------
# Check freshness
# ---------------------------------------------------------------------------


def do_check_freshness(
    observations_path: Path,
    claude_dir: Path,
    *,
    apply: bool,
) -> tuple[int, list[str]]:
    """Compare mtime of canonical observations.jsonl vs latest mirror .md file.

    Args:
        observations_path: Path to observations.jsonl.
        claude_dir:        Claude memory mirror directory.
        apply:             Unused (check-freshness is read-only).

    Returns:
        (exit_code, messages)
    """
    messages: list[str] = []

    if not observations_path.exists():
        messages.append("Canonical observations.jsonl does not exist (no memory yet).")
        return 1, messages

    if not claude_dir.exists():
        messages.append("Claude memory directory does not exist (no mirror yet).")
        messages.append("Run '--export --apply' first to create the mirror.")
        return 1, messages

    obs_mtime = datetime.fromtimestamp(
        observations_path.stat().st_mtime, tz=timezone.utc
    )

    md_files = sorted(
        claude_dir.glob("*.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not md_files:
        messages.append("No .md files in Claude memory mirror directory.")
        return 1, messages

    latest_md = md_files[0]
    md_mtime = datetime.fromtimestamp(latest_md.stat().st_mtime, tz=timezone.utc)

    messages.append(f"Canonical observations.jsonl mtime: {obs_mtime.isoformat()}")
    messages.append(f"Latest mirror .md mtime:          {md_mtime.isoformat()}")

    if md_mtime > obs_mtime:
        delta = md_mtime - obs_mtime
        messages.append(
            f"RESULT: Mirror is {delta.total_seconds():.0f}s newer than canonical."
        )
        messages.append("Consider '--import --apply' to sync mirror into canonical.")
    elif obs_mtime > md_mtime:
        delta = obs_mtime - md_mtime
        messages.append(
            f"RESULT: Canonical is {delta.total_seconds():.0f}s newer than mirror."
        )
        messages.append("Consider '--export --apply' to update the mirror.")
    else:
        messages.append("RESULT: Both are equally fresh (identical mtime).")

    return 0, messages


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Claude Memory Mirror - local opt-in sync with Claude memory.\n\n"
            "Export / import observations between the canonical workspace memory "
            "and the local Claude memory directory "
            "(~/.claude/projects/<slug>/memory/).\n\n"
            "This is a LOCAL OPT-IN utility. It does NOT affect install, --validate,\n"
            "or --session-close.  ~/.claude/ is NEVER a canonical source of truth."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--export",
        action="store_true",
        help="Export observations.jsonl entries to Claude memory markdown files",
    )
    parser.add_argument(
        "--import",
        action="store_true",
        dest="import_",
        help="Import Claude memory entries back into observations.jsonl",
    )
    parser.add_argument(
        "--check-freshness",
        action="store_true",
        help="Compare mtime of canonical memory vs local mirror",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing (this is the default)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write changes (overrides dry-run)",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Explicit project root path (default: auto-detect)",
    )

    return parser


def main() -> int:
    """Entry point."""
    parser = build_parser()
    args = parser.parse_args()

    if not args.export and not args.import_ and not args.check_freshness:
        parser.print_help()
        print(
            "\nERROR: specify at least one of --export, --import, or --check-freshness."
        )
        return 1

    # --apply overrides dry-run
    apply = bool(args.apply)

    project_root = args.project_root
    if project_root is None:
        project_root = _resolve_project_root()

    observations_path = get_observations_path(project_root)
    claude_dir = get_claude_memory_dir(project_root)
    slug = derive_project_slug(project_root)

    # Banner
    mode_label = "APPLY" if apply else "DRY-RUN"
    print(f"[{mode_label}] Claude Memory Mirror ({slug})")
    print()

    exit_code = 0
    all_messages: list[str] = []

    if args.export:
        ec, msgs = do_export(observations_path, claude_dir, apply=apply)
        exit_code = exit_code or ec
        all_messages.extend(msgs)

    if args.import_:
        ec, msgs = do_import(observations_path, claude_dir, apply=apply)
        exit_code = exit_code or ec
        all_messages.extend(msgs)

    if args.check_freshness:
        ec, msgs = do_check_freshness(observations_path, claude_dir, apply=apply)
        exit_code = exit_code or ec
        all_messages.extend(msgs)

    for msg in all_messages:
        print(msg)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
