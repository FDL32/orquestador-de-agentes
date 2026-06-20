#!/usr/bin/env python3
"""Dispatch quality gates by deliverable_type from work_plan.md.

Reads .agent/collaboration/work_plan.md, extracts deliverable_type, invokes
the appropriate gate sequence. Fallback to 'code' with warning if missing.

WP-2026-122: Uses runtime.project_root for dynamic project root resolution.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


# Bootstrap: project root must be on sys.path before importing runtime.project_root.
_PROJECT_ROOT_BOOTSTRAP = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT_BOOTSTRAP) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT_BOOTSTRAP))
_AGENT_DIR = _PROJECT_ROOT_BOOTSTRAP / ".agent"
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

# WP-2026-122 / WP-2026-155: Centralized path resolution via runtime.project_root
import scope_gate  # noqa: E402


def resolve_project_root_path() -> Path:
    env_root = os.environ.get("AGENT_PROJECT_ROOT", "").strip()
    if env_root:
        return Path(env_root).resolve()
    return _PROJECT_ROOT_BOOTSTRAP


def get_collab_dir_path(project_root: Path) -> Path:
    return project_root / ".agent" / "collaboration"


PROJECT_ROOT = resolve_project_root_path()


def resolve_motor_root_path(project_root: Path) -> Path:
    link_path = project_root / ".agent" / "config" / "motor_destination_link.json"
    if not link_path.exists():
        return _PROJECT_ROOT_BOOTSTRAP
    try:
        data = json.loads(link_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _PROJECT_ROOT_BOOTSTRAP
    motor_root = data.get("motor_root")
    if not motor_root:
        return _PROJECT_ROOT_BOOTSTRAP
    candidate = Path(motor_root)
    if candidate.exists():
        return candidate.resolve()
    return _PROJECT_ROOT_BOOTSTRAP


# WOT-2026-012b: distinguish project root (operational repo_destino) from
# motor root (portable repo with scripts/tests). All motor scripts are invoked
# by absolute path from MOTOR_ROOT; code gates run against AUTHORITY_ROOT.
MOTOR_ROOT = resolve_motor_root_path(PROJECT_ROOT)
MOTOR_SCRIPTS_DIR = MOTOR_ROOT / "scripts"
WORK_PLAN = get_collab_dir_path(PROJECT_ROOT) / "work_plan.md"
_DELIVERABLE_TYPE_RE = re.compile(
    r"^\s*-\s*\*\*deliverable_type:\*\*\s*(\S+)", re.IGNORECASE | re.MULTILINE
)

_VALID = {"code", "documentation", "research", "analysis", "mixed"}


def read_work_plan_content() -> str | None:
    if not WORK_PLAN.exists():
        return None
    return WORK_PLAN.read_text(encoding="utf-8")


def read_deliverable_type() -> str:
    content = read_work_plan_content()
    if content is None:
        print(
            "[dispatch] work_plan.md not found, defaulting to 'code'", file=sys.stderr
        )
        return "code"
    match = _DELIVERABLE_TYPE_RE.search(content)
    if not match:
        print(
            "[dispatch] no deliverable_type declared, defaulting to 'code'",
            file=sys.stderr,
        )
        return "code"
    value = match.group(1).strip().lower()
    if "+" in value:
        print(f"[dispatch] compound '{value}' treated as 'mixed'", file=sys.stderr)
        return "mixed"
    if value not in _VALID:
        print(
            f"[dispatch] unknown type '{value}', defaulting to 'code'", file=sys.stderr
        )
        return "code"
    return value


def read_delivery_authority() -> str:
    content = read_work_plan_content()
    if content is None:
        return "repo_motor"
    return scope_gate.read_delivery_authority(content, default="repo_motor")


def resolve_authority_root(delivery_authority: str) -> Path:
    if delivery_authority == "repo_destino":
        return PROJECT_ROOT
    return MOTOR_ROOT


def build_project_env(project_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["AGENT_PROJECT_ROOT"] = str(project_root)
    return env


def run_motor_script(
    script_name: str, *args: str, project_root: Path | None = None
) -> int:
    env = None
    if project_root is not None:
        env = build_project_env(project_root)
    return subprocess.run(  # noqa: S603
        [sys.executable, str(MOTOR_SCRIPTS_DIR / script_name), *args],
        cwd=MOTOR_ROOT,
        env=env,
    ).returncode


def has_local_tests(project_root: Path) -> bool:
    """Return True if the project has a local pytest suite to run.

    Before: project_root is a resolved path.
    During: Checks for a ``tests`` directory containing at least one
            ``test_*.py`` or ``*_test.py`` file (structural detection, no pytest
            collection). Host-extends destinos that retired their vendored
            ``tests/`` (WOT-2026-002c A2d) have none.
    After: Returns a bool; no side effects.
    """
    tests_dir = project_root / "tests"
    if not tests_dir.is_dir():
        return False
    for pattern in ("test_*.py", "*_test.py"):
        if next(tests_dir.rglob(pattern), None) is not None:
            return True
    return False


def run_code_gates(delivery_authority: str) -> int:
    authority_root = resolve_authority_root(delivery_authority)

    # 1. ruff check (linter)
    print("[dispatch] Running ruff check .")
    rc_ruff = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "ruff", "check", "."], cwd=authority_root
    ).returncode
    if rc_ruff != 0:
        return rc_ruff

    # 1b. ruff format --check (formatter): la CI quality-gates lo exige.
    # ruff check (linter) y ruff format son cosas distintas; sin este paso
    # un archivo sin formatear pasa el gate local pero rompe la CI.
    print("[dispatch] Running ruff format --check .")
    rc_fmt = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "ruff", "format", "--check", "."], cwd=authority_root
    ).returncode
    if rc_fmt != 0:
        print("[dispatch] ruff format --check failed: ejecuta 'ruff format .'")
        return rc_fmt

    # 2. pytest-safe (skip auditably when the destino has no local tests)
    if has_local_tests(authority_root):
        print("[dispatch] Running pytest-safe")
        rc_pytest = run_motor_script(
            "run_pytest_safe.py",
            project_root=authority_root,
        )
        if rc_pytest != 0:
            return rc_pytest
    else:
        print(
            f"[dispatch] No local tests under {authority_root / 'tests'}; "
            "skipping pytest-safe (destino sin tests locales). "
            "CI uses validate-state."
        )

    # 3. conditional pip-audit
    try:
        from scripts.pip_audit_policy import should_run_pip_audit

        run_audit, reason = should_run_pip_audit(PROJECT_ROOT)
    except ImportError:
        run_audit, reason = True, "Fallback: could not import pip_audit_policy"

    if run_audit:
        print(f"[dispatch] Running pip-audit wrapper ({reason})")
        rc_audit = run_motor_script(
            "pip_audit_project.py",
            project_root=authority_root,
        )
        if rc_audit != 0:
            return rc_audit
    else:
        print(f"[dispatch] Skipping pip-audit ({reason})")

    return 0


def run_deliverable_gates() -> int:
    rc = run_motor_script(
        "check_deliverables_exist.py",
        project_root=PROJECT_ROOT,
    )
    return rc


def main() -> int:
    dtype = read_deliverable_type()
    delivery_authority = read_delivery_authority()
    print(f"[dispatch] deliverable_type='{dtype}'")
    if dtype in ("code", "mixed"):
        rc = run_code_gates(delivery_authority)
        if rc != 0:
            return rc
    if dtype in ("documentation", "research", "analysis", "mixed"):
        rc = run_deliverable_gates()
        if rc != 0:
            return rc

    # Contract barrier: verify prompt<->skill alignment (independent of deliverable_type)
    print("[dispatch] Running discover_skills.py --check-contract")
    rc_contract = run_motor_script(
        "discover_skills.py",
        "--check-contract",
        project_root=PROJECT_ROOT,
    )
    if rc_contract != 0:
        print("[dispatch] Contract check FAILED: prompt<->skill alignment broken")
        return rc_contract

    # Naming barrier (WOT-2026-008d / DEC-008D-001): fail closed on a new
    # prompt/skill name outside the versioned convention. Independent of
    # deliverable_type, same pattern as --check-contract.
    print("[dispatch] Running discover_skills.py --check-naming")
    rc_naming = run_motor_script(
        "discover_skills.py",
        "--check-naming",
        project_root=PROJECT_ROOT,
    )
    if rc_naming != 0:
        print("[dispatch] Naming check FAILED: name outside DEC-008D-001 convention")
        return rc_naming

    # Backlog contract barrier (WOT-2026-012b): fail closed on structural or
    # semantic drift in the live queue (Vista rapida table). Independent of
    # deliverable_type. Reads repo_destino backlog via --project-root (PROJECT_ROOT
    # resolves to the active destino through AGENT_PROJECT_ROOT in the launcher).
    print("[dispatch] Running check_backlog_contract.py")
    rc_backlog = run_motor_script(
        "check_backlog_contract.py",
        "--project-root",
        str(PROJECT_ROOT),
        project_root=PROJECT_ROOT,
    )
    if rc_backlog != 0:
        print("[dispatch] Backlog contract check FAILED: live-queue drift")
        return rc_backlog

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
