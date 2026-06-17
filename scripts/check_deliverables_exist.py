#!/usr/bin/env python3
"""Check that all declared deliverables in work_plan.md exist on disk.

Exits 0 if all exist, 1 if any are missing.

WP-2026-122: Uses runtime.project_root for dynamic project root resolution.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path


# Bootstrap: project root must be on sys.path before importing runtime.project_root.
_PROJECT_ROOT_BOOTSTRAP = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT_BOOTSTRAP) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT_BOOTSTRAP))

# WP-2026-122 / WP-2026-155: Centralized path resolution via runtime.project_root
from runtime.project_root import resolve_project_root  # noqa: E402


PROJECT_ROOT = resolve_project_root()
# Allow overriding PROJECT_ROOT for testing
if "TEST_PROJECT_ROOT" in os.environ:
    PROJECT_ROOT = Path(os.environ["TEST_PROJECT_ROOT"])

WORK_PLAN = PROJECT_ROOT / ".agent" / "collaboration" / "work_plan.md"


def _import_scope_gate():
    """Import scope_gate from the motor .agent/ directory."""
    agent_dir = Path(__file__).resolve().parent.parent / ".agent"
    if str(agent_dir) not in sys.path:
        sys.path.insert(0, str(agent_dir))
    import scope_gate as _sg

    return _sg


def resolve_motor_root() -> Path:
    """Resolve the motor root for namespaced FLT deliverables.

    Before: PROJECT_ROOT must already be resolved (destino or standalone).
    During: Honors TEST_MOTOR_ROOT for tests; otherwise delegates to
        runtime.motor_link.resolve_motor_root against PROJECT_ROOT.
    After: Returns an absolute Path. Falls back to PROJECT_ROOT when no
        motor_destination_link.json exists (standalone/motor-as-root case),
        matching the convention already used by pre_handoff_guard.
    """
    if "TEST_MOTOR_ROOT" in os.environ:
        return Path(os.environ["TEST_MOTOR_ROOT"])

    from runtime.motor_link import resolve_motor_root as _resolve

    motor_root = _resolve(PROJECT_ROOT)
    return motor_root if motor_root is not None else PROJECT_ROOT


def looks_like_path(token: str) -> bool:
    """Determine if a token extracted from backticks looks like a file path candidate."""
    if not token or " " in token:
        return False
    # Exclude obvious non-paths like uppercase variables/constants
    if token.isupper() and "_" in token:
        return False
    # Must have a dot (file extension) or path slashes
    return "." in token or "/" in token or "\\" in token


def resolve_with_fallbacks(token: str) -> Path | None:
    """Resolve a token to a Path using relative, absolute, and common folders fallbacks."""
    p = Path(token)
    if not p.is_absolute():
        p = PROJECT_ROOT / p

    if p.exists():
        return p.resolve()

    # Fallback to search common directories
    name = p.name

    # 1. Check in .agent/collaboration
    collab_path = PROJECT_ROOT / ".agent" / "collaboration" / name
    if collab_path.exists():
        return collab_path.resolve()

    # 2. Check in scripts/
    scripts_path = PROJECT_ROOT / "scripts" / name
    if scripts_path.exists():
        return scripts_path.resolve()

    # 3. Check for hidden file (dot-prepended) in PROJECT_ROOT
    hidden_path = PROJECT_ROOT / f".{name}"
    if hidden_path.exists():
        return hidden_path.resolve()

    # 4. Check in skills/
    skills_dir = PROJECT_ROOT / "skills"
    if skills_dir.exists():
        # Check immediate subdirectories first
        for item in skills_dir.iterdir():
            if item.is_dir() and item.name == name:
                return item.resolve()
            # Check files within skill directories (e.g. SKILL.md)
            skill_file = item / name
            if skill_file.exists():
                return skill_file.resolve()

    return None


def _process_backtick_tokens(line: str, paths: set[Path]) -> None:
    """Extract and validate all backticked tokens from a line, adding them to paths."""
    tokens = re.findall(r"`([^`]+)`", line)
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        if token.endswith("/") or token.endswith("\\"):
            # Explicitly ignore directory trails
            continue
        if any(x in token for x in ["<", ">", "{", "}", "YYYY", "NNN"]):
            # Ignore placeholder paths
            continue
        token = token.rstrip(",").strip()

        if not looks_like_path(token):
            continue

        resolved = resolve_with_fallbacks(token)
        if resolved:
            paths.add(resolved)
        else:
            # If not found but looks like a path, add the default resolved path to missing list
            p = Path(token)
            if not p.is_absolute():
                p = PROJECT_ROOT / p
            paths.add(p.resolve())


def _extract_paths_from_generic_sections(content: str) -> set[Path]:
    """Extract deliverable paths from non-FLT sections (Deliverables, must create/modify).

    Files Likely Touched is handled separately via _extract_flt_paths so that
    motor/destino namespacing resolves against the correct root. This function
    only covers the legacy free-form sections that never had namespace concerns.
    """
    paths: set[Path] = set()
    in_section = False
    skip_subsection = False

    scan_keywords = {"deliverables", "must create", "must modify"}
    stop_headers = {
        "## tareas",
        "## acceptance criteria",
        "## riesgos",
        "## plan de rollback",
        "## orden operativo",
    }

    def _heading_level(line: str) -> int:
        stripped = line.lstrip()
        return len(stripped) - len(stripped.lstrip("#"))

    for line in content.splitlines():
        line_stripped = line.strip()
        line_lower = line_stripped.lower()

        if line_stripped.startswith("#"):
            if any(stop in line_lower for stop in stop_headers):
                in_section = False
                continue

            if any(kw in line_lower for kw in scan_keywords):
                in_section = True
                skip_subsection = False
                continue

            if in_section and _heading_level(line_stripped) > 2:
                skip_subsection = any(
                    marker in line_lower
                    for marker in (
                        "read/inspect",
                        "read-only",
                        "read only",
                        "manager only",
                    )
                )
                continue

            in_section = False
            skip_subsection = False

        if any(f"**{kw}" in line_lower for kw in ["must create", "must modify"]):
            in_section = True

        if in_section and (
            line_stripped.startswith("-") or line_stripped.startswith("*")
        ):
            if skip_subsection:
                continue
            _process_backtick_tokens(line_stripped, paths)

    return paths


_SKIP_SUBHEADER_MARKERS = ("read/inspect", "read-only", "read only", "manager only")


def _flt_subheading_namespace(heading_lower: str) -> str | None:
    """Classify a ### sub-heading under Files Likely Touched.

    Recognizes both bare (``repo_motor``) and compound headings already in
    use across the codebase (``repo_destino - Builder``,
    ``repo_destino - Read/inspect only``) by checking the namespace as a
    leading token rather than requiring an exact match, matching the
    contract already exercised in tests/test_agent_controller.py.
    Returns "motor", "destino", or None when no recognized namespace prefix
    is present (caller falls back to delivery_authority).
    """
    if heading_lower.startswith("repo_motor"):
        return "motor"
    if heading_lower.startswith("repo_destino"):
        return "destino"
    return None


def _resolve_flt_bullet_tokens(
    stripped: str, current_root: Path, paths: set[Path]
) -> None:
    """Resolve a single FLT bullet line to a deliverable path, if it is one.

    Mirrors scope_gate._normalize_flt_line / _looks_like_path_token: a bullet
    is treated as a single declared path, not a bag of every backticked
    substring on the line. This rejects narrative bullets that happen to
    contain backticked filenames in prose (e.g. "Notas: los scripts
    inspeccionados (`foo.py`, `bar.py`) son read-only"), since such lines
    contain spaces once de-quoted and are therefore not a bare path token.
    """
    normalized = (
        stripped.lstrip("*- ")
        .replace("`", "")
        .replace('"', "")
        .replace("'", "")
        .strip()
    )
    if not normalized or " " in normalized:
        return
    token = normalized.rstrip(",").strip()
    if not token or token.endswith(("/", "\\")):
        return
    if any(x in token for x in ["<", ">", "{", "}", "YYYY", "NNN"]):
        return
    if not looks_like_path(token):
        return
    p = Path(token)
    if not p.is_absolute():
        p = current_root / p
    paths.add(p.resolve())


def _extract_flt_paths(content: str) -> set[Path]:
    """Resolve Files Likely Touched deliverables against their namespaced root.

    Before: content is the raw work_plan.md text.
    During: Scans only the "## Files Likely Touched" section. Each ### sub
        heading is classified by _flt_subheading_namespace (prefix match, so
        compound headings like "repo_destino - Builder" still resolve);
        Read/inspect only and Manager-only sub-headings are skipped entirely
        regardless of namespace, matching the long-standing contract. Lines
        with no recognized namespace sub-heading fall back to
        delivery_authority (scope_gate.read_delivery_authority), same as
        scope_gate.parse_flt_namespaced's flat-line behavior.
    After: Returns absolute, existing-or-not Paths rooted against motor_root
        for the motor namespace and PROJECT_ROOT for the destino namespace,
        instead of always rooting against PROJECT_ROOT.
    """
    sg = _import_scope_gate()
    delivery_authority = sg.read_delivery_authority(content)
    motor_root = resolve_motor_root()
    default_root = motor_root if delivery_authority == "repo_motor" else PROJECT_ROOT

    paths: set[Path] = set()
    in_flt = False
    current_root: Path | None = None
    skip_subsection = False

    for line in content.splitlines():
        stripped = line.strip()

        if stripped.startswith("## Files Likely Touched"):
            in_flt = True
            current_root = default_root
            skip_subsection = False
            continue
        if in_flt and stripped.startswith("## ") and not stripped.startswith("### "):
            break
        if not in_flt:
            continue

        if stripped.startswith("### "):
            heading_lower = stripped[4:].strip().lower()
            namespace = _flt_subheading_namespace(heading_lower)
            if namespace == "motor":
                current_root = motor_root
            elif namespace == "destino":
                current_root = PROJECT_ROOT
            else:
                current_root = default_root
            skip_subsection = any(
                marker in heading_lower for marker in _SKIP_SUBHEADER_MARKERS
            )
            continue

        if skip_subsection or current_root is None:
            continue

        if stripped.startswith("-") or stripped.startswith("*"):
            _resolve_flt_bullet_tokens(stripped, current_root, paths)

    return paths


def extract_paths_from_work_plan(content: str) -> set[Path]:
    paths = _extract_paths_from_generic_sections(content)
    paths |= _extract_flt_paths(content)
    return paths


def main() -> int:
    if not WORK_PLAN.exists():
        print(
            f"[check-deliverables] Active work_plan.md not found at {WORK_PLAN}",
            file=sys.stderr,
        )
        return 0  # Fallback if no active plan

    content = WORK_PLAN.read_text(encoding="utf-8")
    declared_paths = extract_paths_from_work_plan(content)

    if not declared_paths:
        print(
            "[check-deliverables] No deliverables declared in work_plan.md",
            file=sys.stderr,
        )
        return 0

    missing = []
    print(f"[check-deliverables] Checking {len(declared_paths)} declared deliverables:")
    for path in sorted(declared_paths):
        try:
            rel_path = path.relative_to(PROJECT_ROOT)
        except ValueError:
            rel_path = path

        if path.exists():
            print(f"  [OK] {rel_path}")
        else:
            print(f"  [MISSING] {rel_path}")
            missing.append(path)

    if missing:
        print(
            f"\n[check-deliverables] ERROR: {len(missing)} deliverable(s) are missing!",
            file=sys.stderr,
        )
        return 1

    print(
        "\n[check-deliverables] SUCCESS: All declared deliverables exist.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
