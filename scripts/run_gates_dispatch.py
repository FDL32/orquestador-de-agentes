#!/usr/bin/env python3
"""Dispatch quality gates by deliverable_type from work_plan.md.

Reads .agent/collaboration/work_plan.md, extracts deliverable_type, invokes
the appropriate gate sequence. Fallback to 'code' with warning if missing.

WP-2026-122: Uses runtime.project_root for dynamic project root resolution.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


# Bootstrap: project root must be on sys.path before importing runtime.project_root.
_PROJECT_ROOT_BOOTSTRAP = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT_BOOTSTRAP) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT_BOOTSTRAP))

# WP-2026-122 / WP-2026-155: Centralized path resolution via runtime.project_root
from runtime.project_root import get_collab_dir, resolve_project_root  # noqa: E402


PROJECT_ROOT = resolve_project_root()
WORK_PLAN = get_collab_dir() / "work_plan.md"
_DELIVERABLE_TYPE_RE = re.compile(
    r"^\s*-\s*\*\*deliverable_type:\*\*\s*(\S+)", re.IGNORECASE | re.MULTILINE
)

_VALID = {"code", "documentation", "research", "analysis", "mixed"}


def read_deliverable_type() -> str:
    if not WORK_PLAN.exists():
        print(
            "[dispatch] work_plan.md not found, defaulting to 'code'", file=sys.stderr
        )
        return "code"
    content = WORK_PLAN.read_text(encoding="utf-8")
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


def run_code_gates() -> int:
    # 1. ruff check (linter)
    print("[dispatch] Running ruff check .")
    rc_ruff = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "ruff", "check", "."], cwd=PROJECT_ROOT
    ).returncode
    if rc_ruff != 0:
        return rc_ruff

    # 1b. ruff format --check (formatter): la CI quality-gates lo exige.
    # ruff check (linter) y ruff format son cosas distintas; sin este paso
    # un archivo sin formatear pasa el gate local pero rompe la CI.
    print("[dispatch] Running ruff format --check .")
    rc_fmt = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "ruff", "format", "--check", "."], cwd=PROJECT_ROOT
    ).returncode
    if rc_fmt != 0:
        print("[dispatch] ruff format --check failed: ejecuta 'ruff format .'")
        return rc_fmt

    # 2. pytest-safe
    print("[dispatch] Running pytest-safe")
    rc_pytest = subprocess.run(  # noqa: S603
        [sys.executable, "scripts/run_pytest_safe.py"], cwd=PROJECT_ROOT
    ).returncode
    if rc_pytest != 0:
        return rc_pytest

    # 3. conditional pip-audit
    try:
        from scripts.pip_audit_policy import should_run_pip_audit

        run_audit, reason = should_run_pip_audit(PROJECT_ROOT)
    except ImportError:
        run_audit, reason = True, "Fallback: could not import pip_audit_policy"

    if run_audit:
        print(f"[dispatch] Running pip-audit wrapper ({reason})")
        rc_audit = subprocess.run(  # noqa: S603
            [sys.executable, "scripts/pip_audit_project.py"],
            cwd=PROJECT_ROOT,
        ).returncode
        if rc_audit != 0:
            return rc_audit
    else:
        print(f"[dispatch] Skipping pip-audit ({reason})")

    return 0


def run_deliverable_gates() -> int:
    rc = subprocess.run(  # noqa: S603
        [sys.executable, "scripts/check_deliverables_exist.py"], cwd=PROJECT_ROOT
    ).returncode
    return rc


def main() -> int:
    dtype = read_deliverable_type()
    print(f"[dispatch] deliverable_type='{dtype}'")
    if dtype in ("code", "mixed"):
        rc = run_code_gates()
        if rc != 0:
            return rc
    if dtype in ("documentation", "research", "analysis", "mixed"):
        rc = run_deliverable_gates()
        if rc != 0:
            return rc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
