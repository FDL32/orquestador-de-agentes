#!/usr/bin/env python3
"""
Install or sync the Agent System from orquestador_de_agentes/ motor central.

ARCHITECTURE: Central motor + destination workspace.
- The motor (operational code) lives once in the source repo (orquestador_de_agentes).
- The destination workspace keeps only .agent/ state, memory, events, and config.
- The installer prepares (bootstraps) the destination to consume the external motor.
- The motor is NOT copied to the destination.

Usage:
    python orquestador_de_agentes/scripts/install_agent_system.py --install
    python orquestador_de_agentes/scripts/install_agent_system.py --sync
        → Sync + auto-remove residues (strict, default)

    python orquestador_de_agentes/scripts/install_agent_system.py --sync --dry-run
        → Preview changes without modifying

    python orquestador_de_agentes/scripts/install_agent_system.py --sync --prune
        → Sync + interactively choose which residues to remove
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path


# Paths
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATE_ROOT = REPO_ROOT / "orquestador_de_agentes"
TEMPLATE_AGENT = TEMPLATE_ROOT / ".agent"
PROJECT_AGENT = REPO_ROOT / ".agent"

# Directories to preserve in the project instance.
LOCAL_DIRS = {"collaboration", "runtime"}

# Generated / transient directories that should not be part of canonical sync.
IGNORED_NAMES = {"__pycache__", ".ruff_cache", ".tmp"}

VERSION_MANIFEST_NAME = ".version_manifest.json"
HOOKS_CONFIG_REL = Path("config") / "hooks_config.json"

# Host setup hook candidates (detected post-copy in destination)
HOST_SETUP_CANDIDATES = ("host-setup.sh", "host-setup.ps1")

# Manifest file for portable workspace allowlist
MANIFEST_WORKSPACE = "MANIFEST.workspace"
MANIFEST_WORKSPACE_VERSION = "1.0"


def read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[WARN] Invalid JSON in {path}: {exc}")
        return None


def write_json(path: Path, payload: dict, dry_run: bool = False) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def read_manifest_allowlist(template_root: Path) -> set[str]:
    """
    Read MANIFEST.workspace and return set of allowed paths.

    Before: Manifest file may or may not exist at template_root/MANIFEST.workspace.
    During: Parses file, skipping comments and empty lines, stripping whitespace.
    After: Returns set of path strings, or empty set if file missing.

    Args:
        template_root: Root path of the template repository.

    Returns:
        Set of allowed path strings from the manifest.
    """
    manifest_path = template_root / MANIFEST_WORKSPACE
    if not manifest_path.exists():
        return set()

    allowed: set[str] = set()
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        # Skip comments and empty lines
        if not line or line.startswith("#"):
            continue
        allowed.add(line)

    return allowed


def get_manifest_version(agent_dir: Path) -> str | None:
    manifest = read_json(agent_dir / VERSION_MANIFEST_NAME)
    if not manifest:
        return None
    version = manifest.get("version")
    if isinstance(version, str) and version.strip():
        return version.strip()
    agent_core_version = manifest.get("agent_core_version")
    if isinstance(agent_core_version, str) and agent_core_version.strip():
        return agent_core_version.strip()
    return None


def is_preserved(rel_path: Path) -> bool:
    return bool(rel_path.parts) and rel_path.parts[0] in LOCAL_DIRS


def is_ignored(rel_path: Path) -> bool:
    return any(part in IGNORED_NAMES for part in rel_path.parts)


def is_in_allowlist(rel_path: Path, allowlist: set[str]) -> bool:
    """
    Check if a relative path is in the allowlist.

    Supports both exact matches and directory prefixes (e.g., 'skills/' matches 'skills/foo/bar.py').

    Args:
        rel_path: Relative path to check.
        allowlist: Set of allowed paths from MANIFEST.workspace.

    Returns:
        True if path is allowed, False otherwise.
    """
    normalized = rel_path.as_posix()
    candidates = {normalized}
    if normalized.startswith(".agent/"):
        candidates.add(normalized)
    else:
        candidates.add(f".agent/{normalized}")

    # Exact match
    for candidate in candidates:
        if candidate in allowlist:
            return True

    # Directory prefix match (e.g., 'skills/' matches 'skills/test.py')
    for candidate in candidates:
        for allowed in allowlist:
            if allowed.endswith("/") and candidate.startswith(allowed):
                return True
            if allowed.startswith(candidate.rstrip("/") + "/"):
                return True

    return False


def iter_canonical_entries(root: Path, include_ignored: bool = False) -> list[Path]:
    entries: list[Path] = []
    if not root.exists():
        return entries

    for item in root.rglob("*"):
        rel = item.relative_to(root)
        if is_preserved(rel):
            continue
        if not include_ignored and is_ignored(rel):
            continue
        entries.append(rel)

    return entries


def compact_paths(paths: Iterable[Path]) -> list[Path]:
    ordered = sorted(paths, key=lambda p: (len(p.parts), str(p)))
    compacted: list[Path] = []
    for rel in ordered:
        if any(
            rel == existing or rel.is_relative_to(existing) for existing in compacted
        ):
            continue
        compacted.append(rel)
    return compacted


def detect_destination_residues(source: Path, dest: Path) -> list[Path]:
    source_entries = set(iter_canonical_entries(source, include_ignored=False))
    dest_entries = set(iter_canonical_entries(dest, include_ignored=True))
    residues = dest_entries - source_entries
    return compact_paths(residues)


def ensure_parent_dirs(path: Path, dry_run: bool) -> None:
    if path.exists():
        if path.is_file() or path.is_symlink():
            if dry_run:
                return
            path.unlink()
        else:
            return

    if dry_run:
        return
    path.mkdir(parents=True, exist_ok=True)


def copy_tree(  # noqa: C901 - allowlist-aware sync needs explicit branch handling
    source: Path, dest: Path, dry_run: bool = False, allowlist: set[str] | None = None
) -> list[Path]:
    """
    Copy tree from source to dest, respecting allowlist if provided.

    Before: source directory exists; allowlist may be None (copy all non-ignored).
    During: Iterates source items, skips preserved/ignored paths, checks allowlist.
    After: Returns list of copied relative paths; raises if non-allowlisted path found.

    Args:
        source: Source directory root.
        dest: Destination directory root.
        dry_run: If True, simulate without modifying filesystem.
        allowlist: Set of allowed paths from MANIFEST.workspace, or None for legacy behavior.

    Returns:
        List of relative paths that were copied.

    Raises:
        RuntimeError: If a path outside the allowlist would be copied.
    """
    copied: list[Path] = []
    if not source.exists():
        return copied

    for item in source.iterdir():
        rel = item.relative_to(source)
        if is_preserved(rel) or is_ignored(rel):
            continue

        # Check allowlist if provided
        if allowlist is not None and not is_in_allowlist(rel, allowlist):
            if dry_run:
                print(f"[DRY-RUN] Would skip unauthorized path: {rel.as_posix()}")
            else:
                print(f"[SKIP] Unauthorized path outside allowlist: {rel.as_posix()}")
            continue

        dst_item = dest / item.name

        if item.is_dir():
            if dry_run:
                copied.append(rel)
                continue

            if dst_item.exists() and dst_item.is_file():
                dst_item.unlink()
            shutil.copytree(
                item,
                dst_item,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns(*IGNORED_NAMES),
            )
            copied.append(rel)
            continue

        if dry_run:
            copied.append(rel)
            continue

        if dst_item.exists() and dst_item.is_dir():
            shutil.rmtree(dst_item)

        ensure_parent_dirs(dst_item.parent, dry_run=False)
        shutil.copy2(item, dst_item)
        copied.append(rel)

    return copied


def _select_residues_interactive(residues: list[Path]) -> list[Path]:
    """Interactive selection of residues to prune."""
    print("\n[PRUNE] Residues detected:")
    for idx, rel in enumerate(residues, start=1):
        print(f"  {idx}. {rel.as_posix()}")
    try:
        answer = (
            input("\nClean which residues? [all/comma-list/none]: ").strip().lower()
        )
    except (EOFError, KeyboardInterrupt):
        print("[PRUNE] Cancelled.")
        return []

    if not answer or answer in {"none", "no", "n"}:
        return []
    if answer == "all":
        return residues

    indices: list[int] = []
    for chunk in answer.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if not chunk.isdigit():
            print(f"[WARN] Ignoring invalid residue index: {chunk}")
            continue
        idx = int(chunk)
        if 1 <= idx <= len(residues):
            indices.append(idx)
    return [residues[i - 1] for i in sorted(set(indices))]


def _prune_selected_residues(
    dest: Path, selected: list[Path], dry_run: bool
) -> list[Path]:
    """Prune the selected residues."""
    removed: list[Path] = []
    for rel in selected:
        target = dest / rel
        if dry_run:
            print(f"[DRY-RUN] Would prune: {rel.as_posix()}")
            removed.append(rel)
            continue

        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        elif target.exists() or target.is_symlink():
            target.unlink()
        removed.append(rel)
        print(f"[PRUNED] {rel.as_posix()}")

    return removed


def prune_residues(
    dest: Path, residues: list[Path], dry_run: bool, interactive: bool
) -> list[Path]:
    if not residues:
        return []

    selected = residues
    if interactive and not dry_run:
        selected = _select_residues_interactive(residues)
        if not selected:
            return []

    return _prune_selected_residues(dest, selected, dry_run)


def ensure_hooks_config_integrity(agent_dir: Path, dry_run: bool = False) -> bool:
    """
    Validate hooks_config.json structural and semantic integrity.

    Checks:
    - File exists and is valid JSON
    - Root is a dict
    - Has required fields: "version" (string), "enabled" (bool)
    - Does NOT modify any fields (validation only)

    Returns False if validation fails (no drift allowed).
    """
    hooks_config = agent_dir / HOOKS_CONFIG_REL
    payload = read_json(hooks_config)
    if payload is None and dry_run and not hooks_config.exists():
        print(f"[DRY-RUN] hooks_config.json would be created at {hooks_config}")
        return True

    # Check 1: Valid JSON and dict
    if not payload or not isinstance(payload, dict):
        print("[ERROR] hooks_config.json is not a valid dict")
        return False

    # Check 2: Required fields exist with correct types
    required_fields = {
        "version": str,
        "enabled": bool,
    }

    for field_name, expected_type in required_fields.items():
        if field_name not in payload:
            print(f"[ERROR] hooks_config.json missing required field: {field_name}")
            return False

        value = payload[field_name]
        if not isinstance(value, expected_type):
            print(
                f"[ERROR] hooks_config.json field '{field_name}' "
                f"has type {type(value).__name__}, expected {expected_type.__name__}"
            )
            return False

    # All checks passed
    return True


def flip_profile_in_destination(project_agent: Path, dry_run: bool = False) -> None:
    """
    Ensure the active_profile in agents.json is set to 'host-project' at destination.

    Before: The template has 'active_profile': 'engine-dev'.
    During: If CWD is the destination project, we update it to 'host-project' to flip profile.
    After: Destination project has the host-project profile.
    """
    config_file = project_agent / "config" / "agents.json"
    if not config_file.exists():
        return
    try:
        content = config_file.read_text(encoding="utf-8")
        payload = json.loads(content)
        if payload.get("active_profile") == "engine-dev":
            if dry_run:
                print(
                    "[DRY-RUN] Would flip active_profile in agents.json to 'host-project'"
                )
                return
            payload["active_profile"] = "host-project"
            config_file.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            print("[INFO] Flipped destination active_profile to 'host-project'")
    except Exception as e:
        print(f"[WARN] Failed to flip active_profile in {config_file}: {e}")


def write_motor_destination_link(
    project_agent: Path,
    motor_root: Path,
    destination_root: Path,
    motor_version: str | None,
    destination_id: str | None = None,
    ticket_prefix: str | None = None,
    dry_run: bool = False,
) -> None:
    """
    Write the motor-destination link file in the destination workspace.

    Before: Destination .agent/config/ directory exists; link file may or may not exist.
    During: Creates/overwrites motor_destination_link.json with schema fields.
    After: Link file exists with motor_root, destination_root, motor_version, ticket_prefix, etc.

    Schema:
    - motor_root: absolute or derived path to the external motor
    - destination_root: absolute path to the destination workspace
    - motor_version: technical version from .agent/.version_manifest.json
    - destination_id: stable identifier for the destination (optional, derived from path)
    - ticket_prefix: local ticket namespace prefix (e.g., 'XXX' for 'XXX-YYYY-NNN')
    - created_at: ISO-8601 UTC timestamp of install/sync
    - manifest_version: MANIFEST.workspace contract version applied

    Args:
        project_agent: Path to destination .agent/ directory.
        motor_root: Path to the motor central repository.
        destination_root: Path to the destination project root.
        motor_version: Version string from motor's .version_manifest.json.
        destination_id: Optional stable identifier; defaults to destination_root name.
        ticket_prefix: Optional ticket prefix for destination namespace (e.g., 'XXX').
        dry_run: If True, simulate without writing.
    """
    config_dir = project_agent / "config"
    link_file = config_dir / "motor_destination_link.json"

    if destination_id is None:
        destination_id = destination_root.name

    payload = {
        "motor_root": str(motor_root.resolve()),
        "destination_root": str(destination_root.resolve()),
        "motor_version": motor_version or "unknown",
        "destination_id": destination_id,
        "ticket_prefix": ticket_prefix,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "manifest_version": MANIFEST_WORKSPACE_VERSION,
    }

    if dry_run:
        print(f"[DRY-RUN] Would write motor-destination link: {link_file}")
        print(f"[DRY-RUN] Link payload: {json.dumps(payload, indent=2)}")
        return

    config_dir.mkdir(parents=True, exist_ok=True)
    link_file.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"[INFO] Wrote motor-destination link: {link_file}")


def _detect_host_setup(destination: Path) -> Path | None:
    """
    Return the first existing host-setup.{sh,ps1} in destination/.agent/, or None.

    Before: destination/.agent/ directory exists (post-copy).
    During: Scans for host-setup.sh first, then host-setup.ps1.
    After: Returns Path to hook if found, None otherwise.
    """
    agent_dir = destination / ".agent"
    for name in HOST_SETUP_CANDIDATES:
        candidate = agent_dir / name
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _maybe_invoke_host_setup(
    destination: Path,
    *,
    auto_yes: bool = False,
    dry_run: bool = False,
    input_fn=input,
) -> int:
    """
    Detect and optionally invoke .agent/host-setup.{sh,ps1} in destination.

    Before: destination/.agent/ exists post-copy; hook may or may not be present.
    During:
      - Detects hook via _detect_host_setup().
      - If dry_run: prints "Would invoke" message, returns 0.
      - If found: prints first 20 lines, prompts for confirmation (unless auto_yes).
      - If confirmed: executes hook with cwd=destination.
    After:
      - Returns 0 if no hook, user declined, or success.
      - Returns non-zero exit code if hook failed (propagates, does not mask).

    Args:
        destination: Project root directory.
        auto_yes: Skip interactive confirmation (for CI).
        dry_run: Print what would happen without executing.
        input_fn: Injected input function for testing (default: built-in input).

    Returns:
        Exit code: 0 = no hook/skipped/success, non-zero = hook failed.
    """
    hook = _detect_host_setup(destination)
    if hook is None:
        return 0
    rel = hook.relative_to(destination)
    if dry_run:
        print(f"[DRY-RUN] Would invoke host setup hook: {rel}")
        return 0
    print(f"[host-setup] Detected: {rel}")
    print("[host-setup] First 20 lines:")
    for line in hook.read_text(encoding="utf-8").splitlines()[:20]:
        print(f"  {line}")
    if not auto_yes:
        answer = input_fn("[host-setup] Execute this script? (y/N) ").strip().lower()
        if answer != "y":
            print("[host-setup] Skipped by user.")
            return 0
    if hook.suffix == ".sh":
        cmd = ["bash", str(hook)]
    else:
        cmd = ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(hook)]
    rc = subprocess.run(cmd, cwd=destination).returncode  # noqa: S603
    if rc != 0:
        print(f"[host-setup] FAILED with exit code {rc}", file=sys.stderr)
    return rc


def _write_prefix_to_project_md(
    destination_root: Path, prefix: str, dry_run: bool
) -> None:
    """
    Write or update 'Ticket prefix: XXX' in destination PROJECT.md.

    Before: destination_root/PROJECT.md may or may not exist; prefix is a non-empty string.
    During: Reads PROJECT.md, adds or updates 'Ticket prefix:' line.
    After: PROJECT.md contains 'Ticket prefix: {prefix}' near the top.

    Args:
        destination_root: Project root directory.
        prefix: Ticket prefix string (e.g., 'XXX').
        dry_run: If True, simulate without writing.
    """
    project_md = destination_root / "PROJECT.md"
    if not project_md.exists():
        # Create minimal PROJECT.md with prefix
        content = f"# Project: {destination_root.name}\nTicket prefix: {prefix}\n"
        if dry_run:
            print(f"[DRY-RUN] Would create {project_md} with ticket prefix")
            return
        project_md.write_text(content, encoding="utf-8")
        print(f"[INFO] Created {project_md} with ticket prefix")
        return

    content = project_md.read_text(encoding="utf-8")
    lines = content.splitlines()

    # Check if 'Ticket prefix:' already exists
    prefix_line_found = False
    new_lines = []
    for line in lines:
        if line.strip().startswith("Ticket prefix:"):
            prefix_line_found = True
            new_lines.append(f"Ticket prefix: {prefix}")
        else:
            new_lines.append(line)

    if not prefix_line_found:
        # Insert after first line (header)
        new_lines.insert(1, f"Ticket prefix: {prefix}")

    new_content = "\n".join(new_lines) + "\n"
    if dry_run:
        print(f"[DRY-RUN] Would update {project_md} with ticket prefix")
        return
    project_md.write_text(new_content, encoding="utf-8")
    print(f"[INFO] Updated {project_md} with ticket prefix")


# ---------------------------------------------------------------------------
# Memory rules sync (Fase 2 — WP-2026-179)
# ---------------------------------------------------------------------------


def parse_wing_sections(content: str) -> dict[str, str]:
    """Parse memory_rules.md content into sections keyed by Wing name.

    Before: Receives full text of a memory_rules.md file (may be empty).
    During: Looks for ``## Wing: <name>`` H2 headers. If none found, treats
            the entire content as belonging to wing 'project' for
            retrocompatibility with legacy files without Wing headers.
    After: Returns dict mapping lowercase wing name -> section text
           (including its ``## Wing:`` header).
    """
    if not content.strip():
        return {}

    wing_re = re.compile(r"^## Wing:\s*(.+)$", re.MULTILINE)
    matches = list(wing_re.finditer(content))

    if not matches:
        # Retrocompat: no Wing headers → assume all content is 'project'
        return {"project": content}

    sections: dict[str, str] = {}
    for i, match in enumerate(matches):
        wing = match.group(1).strip().lower()
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        sections[wing] = content[start:end].rstrip()

    return sections


def merge_memory_rules(source_content: str, dest_content: str) -> str:
    """Merge portable wings (engine/meta) from source into dest, preserving project.

    Before: source_content is the motor's memory_rules.md; dest_content is the
            destination's (may be empty or legacy).
    During: Extracts engine/meta from source and project from dest. Renders a
            new file with canonical wing order: engine -> meta -> project.
            Idempotent: applying twice produces the same output.
    After: Returns merged markdown string ready to write to disk.
    """
    source_sections = parse_wing_sections(source_content)
    dest_sections = parse_wing_sections(dest_content)

    merged: dict[str, str] = {}
    for wing in ("engine", "meta"):
        if wing in source_sections:
            merged[wing] = source_sections[wing]

    if "project" in dest_sections:
        merged["project"] = dest_sections["project"]

    if not merged:
        return dest_content

    parts = [merged[w] for w in ("engine", "meta", "project") if w in merged]
    return "\n\n".join(parts) + "\n"


def sync_memory_rules(
    template_agent: Path,
    project_agent: Path,
    dry_run: bool = False,
) -> None:
    """Sync portable memory rules (engine/meta wings) from motor to destination.

    Before: template_agent and project_agent are valid ``.agent/`` directories.
    During: Reads motor's runtime/memory/memory_rules.md, extracts engine/meta
            wings, merges with destination's memory_rules.md preserving its
            project wing. Does NOT touch observations.jsonl or memory_profile.md.
    After: destination's memory_rules.md contains updated engine/meta rules
           alongside its original project rules.
    """
    source_rules = template_agent / "runtime" / "memory" / "memory_rules.md"
    dest_rules = project_agent / "runtime" / "memory" / "memory_rules.md"

    if not source_rules.exists():
        print("[INFO] Motor has no memory_rules.md — skipping memory sync.")
        return

    source_content = source_rules.read_text(encoding="utf-8")
    dest_content = dest_rules.read_text(encoding="utf-8") if dest_rules.exists() else ""

    merged = merge_memory_rules(source_content, dest_content)

    if dry_run:
        print(
            f"[DRY-RUN] Would sync memory_rules.md (engine/meta wings): "
            f"{source_rules} -> {dest_rules}"
        )
        return

    dest_rules.parent.mkdir(parents=True, exist_ok=True)
    dest_rules.write_text(merged, encoding="utf-8")
    print(f"[INFO] Synced portable memory rules to {dest_rules}")


def install_agent_system(
    template_agent: Path,
    project_agent: Path,
    ticket_prefix: str | None = None,
    dry_run: bool = False,
    auto_yes: bool = False,
) -> int:
    print("[INSTALL] Agent System from orquestador_de_agentes/")

    if project_agent.exists():
        print(f"[WARN] {project_agent} already exists. Use --sync to update.")
        return 1

    if dry_run:
        print(f"[DRY-RUN] Would create {project_agent}")

    if not dry_run:
        project_agent.mkdir(parents=True, exist_ok=True)

    # Read allowlist from MANIFEST.workspace
    template_root = template_agent.parent
    allowlist = read_manifest_allowlist(template_root)
    if allowlist:
        print(f"[INSTALL] Using MANIFEST.workspace: {len(allowlist)} allowed paths")
    else:
        print("[WARN] MANIFEST.workspace not found, using legacy copy-all behavior")

    copied = copy_tree(
        template_agent, project_agent, dry_run=dry_run, allowlist=allowlist
    )
    flip_profile_in_destination(project_agent, dry_run=dry_run)

    # Write motor-destination link file
    motor_version = get_manifest_version(template_agent)
    destination_root = project_agent.parent
    motor_root = template_agent.parent
    write_motor_destination_link(
        project_agent=project_agent,
        motor_root=motor_root,
        destination_root=destination_root,
        motor_version=motor_version,
        ticket_prefix=ticket_prefix,
        dry_run=dry_run,
    )

    # Write ticket prefix to PROJECT.md if provided
    if ticket_prefix:
        _write_prefix_to_project_md(destination_root, ticket_prefix, dry_run=dry_run)

    # Sync portable memory rules (engine/meta wings) from motor
    sync_memory_rules(template_agent, project_agent, dry_run=dry_run)

    integrity_ok = ensure_hooks_config_integrity(project_agent, dry_run=dry_run)

    if dry_run:
        print(
            f"\n[DRY-RUN] Install plan: {len(copied)} top-level entries would be copied."
        )
        return 0

    # Validate hooks config integrity (critical for "no drift" policy)
    if not integrity_ok:
        print("[ERROR] Hooks config integrity check failed. Install aborted.")
        return 1

    # Invoke host setup hook if present
    rc = _maybe_invoke_host_setup(
        project_agent.parent, auto_yes=auto_yes, dry_run=dry_run
    )
    if rc != 0:
        print("[install] Host setup failed; aborting install.", file=sys.stderr)
        return rc

    print(f"\n[SUCCESS] Agent System installed at {PROJECT_AGENT}")
    return 0


def sync_agent_system(  # noqa: C901
    template_agent: Path,
    project_agent: Path,
    ticket_prefix: str | None = None,
    dry_run: bool = False,
    strict_sync: bool = False,
    prune: bool = False,
    auto_yes: bool = False,
) -> int:
    print("[SYNC] Agent System from orquestador_de_agentes/")

    if not project_agent.exists():
        print("[ERROR] Project .agent/ not found. Run --install first.")
        return 1

    manifest_version = get_manifest_version(template_agent)
    if manifest_version:
        print(f"[INFO] Template version: {manifest_version}")
    else:
        print("[WARN] Template version manifest not found.")

    current_manifest = read_json(project_agent / VERSION_MANIFEST_NAME)
    if current_manifest:
        current_version = current_manifest.get("version") or current_manifest.get(
            "agent_core_version", "unknown"
        )
        print(f"[INFO] Current project version: {current_version}")

    # Read allowlist from MANIFEST.workspace
    template_root = template_agent.parent
    allowlist = read_manifest_allowlist(template_root)
    if allowlist:
        print(f"[SYNC] Using MANIFEST.workspace: {len(allowlist)} allowed paths")
    else:
        print("[WARN] MANIFEST.workspace not found, using legacy copy-all behavior")

    residues = detect_destination_residues(template_agent, project_agent)
    if residues:
        print(f"[WARN] Destination residues detected: {len(residues)}")
        for rel in residues:
            print(f"  - {rel.as_posix()}")
    else:
        print("[OK] No destination residues detected.")

    copied = copy_tree(
        template_agent, project_agent, dry_run=dry_run, allowlist=allowlist
    )
    flip_profile_in_destination(project_agent, dry_run=dry_run)

    # Write motor-destination link file (idempotent update)
    motor_version = get_manifest_version(template_agent)
    destination_root = project_agent.parent
    motor_root = template_agent.parent
    write_motor_destination_link(
        project_agent=project_agent,
        motor_root=motor_root,
        destination_root=destination_root,
        motor_version=motor_version,
        ticket_prefix=ticket_prefix,
        dry_run=dry_run,
    )

    # Update PROJECT.md with ticket prefix if provided
    if ticket_prefix:
        _write_prefix_to_project_md(destination_root, ticket_prefix, dry_run=dry_run)

    # Sync portable memory rules (engine/meta wings) from motor
    sync_memory_rules(template_agent, project_agent, dry_run=dry_run)

    integrity_ok = ensure_hooks_config_integrity(project_agent, dry_run=dry_run)

    # Policy: "no drift" — remove residues by default (strict mode)
    # --prune overrides to ask interactively
    # These flags are now mutually exclusive; default to strict if neither specified
    pruned: list[Path] = []
    if prune:
        # Interactive mode: ask user which residues to remove
        pruned = prune_residues(
            project_agent, residues, dry_run=dry_run, interactive=True
        )
    else:
        # Strict mode (default): remove all residues automatically
        pruned = prune_residues(
            project_agent, residues, dry_run=dry_run, interactive=False
        )

    if dry_run:
        print(
            f"\n[DRY-RUN] Sync plan: {len(copied)} top-level entries would be copied/updated."
        )
        print(f"[DRY-RUN] Residues to prune: {len(residues)}")
        if pruned:
            mode = "interactive" if prune else "automatic (strict)"
            print(f"[DRY-RUN] Residues selected for cleanup ({mode}): {len(pruned)}")
        return 0

    # Validate hooks config integrity (critical for "no drift" policy)
    if not integrity_ok:
        print("[ERROR] Hooks config integrity check failed. Sync aborted.")
        return 1

    print("[OK] Hooks config integrity verified.")

    # Invoke host setup hook if present
    rc = _maybe_invoke_host_setup(
        project_agent.parent, auto_yes=auto_yes, dry_run=dry_run
    )
    if rc != 0:
        print("[sync] Host setup failed; aborting sync.", file=sys.stderr)
        return rc

    print(
        f"\n[SUCCESS] Agent System synced. "
        f"Local dirs preserved: {', '.join(sorted(LOCAL_DIRS))}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install or sync the Agent System from orquestador_de_agentes/.agent"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--install", action="store_true", help="Initial setup")
    group.add_argument("--sync", action="store_true", help="Sync updates")
    parser.add_argument(
        "--source",
        type=Path,
        help="Path to orquestador_de_agentes template (auto-detected if omitted)",
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=Path.cwd(),
        help="Project root destination (default: current directory)",
    )
    parser.add_argument(
        "--prefix",
        type=str,
        default=None,
        help="Ticket prefix for destination namespace (e.g., 'XXX' for 'XXX-YYYY-NNN')",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without copying or deleting",
    )
    # Prune options: mutually exclusive
    prune_group = parser.add_mutually_exclusive_group()
    prune_group.add_argument(
        "--prune",
        action="store_true",
        help="Interactively choose which destination residues to delete",
    )
    prune_group.add_argument(
        "--strict-sync",
        action="store_true",
        help="Explicit strict sync (deprecated: this is now the default)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Keep for backward compatibility (no longer blocks sync)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip interactive confirmation for host-setup hook (CI mode)",
    )
    return parser


def detect_template_root(user_source: Path | None) -> Path:
    if user_source:
        candidate = user_source.resolve()
        if (candidate / ".agent" / "agent_controller.py").exists():
            return candidate
        raise FileNotFoundError(
            f"Provided source does not contain a valid .agent tree: {candidate}"
        )

    candidate = TEMPLATE_ROOT.resolve()
    if (candidate / ".agent" / "agent_controller.py").exists():
        return candidate

    raise FileNotFoundError(
        "Could not detect orquestador_de_agentes template. Provide --source manually."
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    dest = args.dest.resolve()
    if not (dest / ".agent").exists() and not args.install:
        print(f"[ERROR] No .agent/ found at destination: {dest}")
        print("Run --install first or pass the correct --dest.")
        return 1

    try:
        template_root = detect_template_root(args.source)
    except FileNotFoundError as exc:
        print(f"[ERROR] {exc}")
        return 1

    template_agent = template_root / ".agent"
    project_agent = dest / ".agent"

    print(f"[INFO] Template detected: {template_root}")
    print(f"[INFO] Destination:      {dest}")
    print(f"[INFO] Mode:            {'DRY-RUN' if args.dry_run else 'LIVE'}")
    if args.prefix:
        print(f"[INFO] Ticket prefix:    {args.prefix}")

    # Keep behavior explicit: install never touches an existing destination.
    if args.install:
        if project_agent.exists():
            print(f"[WARN] {project_agent} already exists. Use --sync for updates.")
            return 1
        return install_agent_system(
            template_agent=template_agent,
            project_agent=project_agent,
            ticket_prefix=args.prefix,
            dry_run=args.dry_run,
            auto_yes=args.yes,
        )

    # Sync updates from template to project root.
    # The template root is canonical, but the current implementation is local-only
    # and the repository layout is fixed, so we sync using the resolved roots.
    return sync_agent_system(
        template_agent=template_agent,
        project_agent=project_agent,
        ticket_prefix=args.prefix,
        dry_run=args.dry_run,
        strict_sync=args.strict_sync,
        prune=args.prune,
        auto_yes=args.yes,
    )


if __name__ == "__main__":
    sys.exit(main())
