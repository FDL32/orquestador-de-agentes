#!/usr/bin/env python3
"""Dispatch quality gates by deliverable_type from work_plan.md.

Reads .agent/collaboration/work_plan.md, extracts deliverable_type, invokes
the appropriate gate sequence. Fallback to 'code' with warning if missing.

WP-2026-122: Uses runtime.project_root for dynamic project root resolution.

WOT-2026-035d: `main()` parses argv via `build_parser()` BEFORE any gate
runs, so `--help`/`-h` (or invalid argv) exits immediately (SystemExit 0/2)
without reading work_plan.md or invoking run_pytest_safe -- previously
`--help` fell through into the full gate run and clobbered the shared
`last-run.json`.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path


# Bootstrap: project root must be on sys.path before importing runtime.project_root.
_PROJECT_ROOT_BOOTSTRAP = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT_BOOTSTRAP) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT_BOOTSTRAP))


def _import_scope_gate():
    """Import scope_gate from the motor .agent/ directory."""
    agent_dir = _PROJECT_ROOT_BOOTSTRAP / ".agent"
    if str(agent_dir) not in sys.path:
        sys.path.insert(0, str(agent_dir))
    import scope_gate as _sg

    return _sg


def resolve_project_root_path() -> Path:
    env_root = os.environ.get("AGENT_PROJECT_ROOT", "").strip()
    if env_root:
        return Path(env_root).resolve()
    return _PROJECT_ROOT_BOOTSTRAP


def get_collab_dir_path(project_root: Path) -> Path:
    return project_root / ".agent" / "collaboration"


PROJECT_ROOT = resolve_project_root_path()


def resolve_motor_root_path(project_root: Path) -> Path:
    """Resolve motor root: delegates to runtime.motor_link.resolve_motor_root.

    Before: project_root is the resolved destination workspace root.
    During: Imports and calls the canonical helper (runtime.motor_link).
            Falls back to _PROJECT_ROOT_BOOTSTRAP when no
            motor_destination_link.json exists (standalone / motor-as-root).
    After: Returns an absolute, .resolve()-normalised Path. Never returns None.
    """
    from runtime.motor_link import resolve_motor_root as _resolve

    motor_root = _resolve(project_root)
    return motor_root if motor_root is not None else _PROJECT_ROOT_BOOTSTRAP


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
    _sg = _import_scope_gate()
    return _sg.read_delivery_authority(content, default="repo_motor")


def resolve_authority_root(delivery_authority: str) -> Path:
    if delivery_authority == "repo_destino":
        return PROJECT_ROOT
    return MOTOR_ROOT


def build_project_env(project_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["AGENT_PROJECT_ROOT"] = str(project_root)
    return env


# WOT-2026-058q: el nivel canonico del gate de codigo. Constante y no
# parametrizable a proposito: un gate de codigo que corre menos que la suite
# canonica es un verde formal-falso, y dejarlo configurable invita a degradarlo.
CANONICAL_SUITE_LEVEL = "all"


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
        # WOT-2026-058q: `--level all` es PARTE del gate, no un adorno.
        # Sin el, `run_pytest_safe` cae a su default `unit` y sella
        # `level=unit` en `last-run.json` -- un ARTEFACTO COMPARTIDO, asi que
        # la corrida SIGUIENTE hereda el sello degradado y falla sin que nadie
        # haya tocado codigo (acoplamiento de ORDEN, medido 2026-08-23 en el
        # cierre de un destino). Es la misma clase de falso-verde formal que
        # WOT-2026-025p documenta: sin `--level all` el verde es unit-only.
        rc_pytest = run_motor_script(
            "run_pytest_safe.py",
            "--level",
            CANONICAL_SUITE_LEVEL,
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


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for this dispatcher.

    Before: none.
    During: declares a description-only parser (no positional/optional
        arguments beyond argparse's built-in `--help`/`-h`). Kept separate
        from `main()` so it can be constructed and inspected (e.g. in
        tests) without triggering any gate side effect.
    After: returns an `argparse.ArgumentParser`. Calling `.parse_args()`
        with `--help`/`-h` prints usage and raises `SystemExit(0)`
        natively; invalid argv raises `SystemExit(2)`. Neither path
        touches `read_deliverable_type()` or runs any gate.
    """
    return argparse.ArgumentParser(
        description=(
            "Dispatch quality gates (ruff, pytest-safe, pip-audit, "
            "deliverable-existence, contract/naming/backlog barriers) "
            "by the deliverable_type declared in work_plan.md. Invoked "
            "with no arguments, it reads work_plan.md and runs the "
            "corresponding gate sequence immediately."
        )
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: dispatch quality gates by deliverable_type.

    Before: `argv` is the raw CLI argument list. Defaults to `[]` (NOT
        `sys.argv[1:]`) when `None`, so calling `main()` bare -- e.g. from
        another module, from tests, or from the `if __name__ ==
        "__main__"` guard below (which passes `sys.argv[1:]` explicitly) --
        preserves the pre-WOT-2026-035d behavior of dispatching immediately
        with no CLI arguments to parse. No side effect has happened yet.
    During: parses `argv` with `build_parser()` FIRST, before touching
        `read_deliverable_type()` or running any gate. `--help`/`-h` and
        invalid argv are intercepted natively by argparse (`SystemExit(0)`
        / `SystemExit(2)` respectively) and propagate out of `main()`
        without reading work_plan.md or invoking any subprocess -- this is
        the WOT-2026-035d fix: previously `--help` fell through into the
        full gate run (including `run_pytest_safe`, which clobbers the
        shared `last-run.json`). With empty argv (the normal dispatch
        path), parsing succeeds trivially and control proceeds exactly as
        before.
    After: on `--help`/invalid argv, raises `SystemExit` (propagated by
        argparse, not caught here) before any gate runs. Otherwise returns
        the same int return code as before this fix (0 on all gates
        passing, first non-zero gate return code otherwise).
    """
    build_parser().parse_args([] if argv is None else argv)

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
    raise SystemExit(main(sys.argv[1:]))
