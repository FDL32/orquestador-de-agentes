#!/usr/bin/env python3
"""Integrated motor<->destino integration gate (WOT-2026-008f).

A single wrapper that validates the motor/destino gearing and operational
lifecycle by DELEGATING to live checks instead of reinventing validators:

- ``motor_destination_link.json`` resolves coherent motor_root + destination_root
  (fail-closed on missing/invalid link).
- destination authority is canonical for the destination tree (reuses
  validate_authority helpers by import; does NOT call its motor-only main()).
- destination context resolves the motor link (reuses destination_context).
- operational pre-push gate (delegates to check_destino_publish_ready.main()).
- OPTIONAL first-publication audit behind an explicit flag (delegates to
  classify_publication.build_manifest(), dry-run, never mutates the repo).

Exit codes:
  0: integration OK (operational gate green; audit clean if requested)
  1: an integration check failed (authority, publish-ready, or audit finding)
  2: pre-push gate reports a non-publishable but non-error state (STATUS gate)
  3: configuration error (link missing/invalid, project root missing)

The default mode is the everyday operational gate. The historical
first-publication scan is more expensive and only runs with
``--audit-publication`` so a pre-push gate is never mixed with a history scan.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


# Bootstrap: motor root on sys.path so scripts.* delegation imports resolve.
_MOTOR_ROOT_BOOTSTRAP = Path(__file__).resolve().parent.parent
if str(_MOTOR_ROOT_BOOTSTRAP) not in sys.path:
    sys.path.insert(0, str(_MOTOR_ROOT_BOOTSTRAP))

from scripts.check_destino_publish_ready import main as publish_ready_main  # noqa: E402
from scripts.classify_publication import build_manifest  # noqa: E402
from scripts.destination_context import resolve_motor_link  # noqa: E402
from scripts.validate_authority import (  # noqa: E402
    detect_legacy_copies,
    find_all_agent_dirs,
    is_canonical_authority,
)


# Exit codes (documented in the module docstring and --help).
EXIT_OK = 0
EXIT_CHECK_FAILED = 1
EXIT_STATUS_NOT_PUBLISHABLE = 2
EXIT_CONFIG_ERROR = 3


def check_destination_authority(project_root: Path) -> tuple[bool, str]:
    """Confirm <project_root>/.agent/collaboration is the canonical authority.

    Reuses validate_authority helpers BY IMPORT (is_canonical_authority,
    find_all_agent_dirs, detect_legacy_copies). This deliberately does NOT use
    validate_authority.main(), which is CLI-only and hardcodes the motor as the
    canonical root; here the canonical root is the destination's own collab dir.

    Before: project_root points at a repo_destino.
    During: treats <project_root>/.agent/collaboration as canonical and scans the
            destination tree for divergent live copies (split-brain).
    After: returns (ok, diagnostic); no mutation.
    """
    canonical_root = project_root / ".agent" / "collaboration"
    if not canonical_root.exists():
        return False, (
            f"[AUTHORITY] canonical .agent/collaboration not found at {canonical_root}"
        )
    copies = find_all_agent_dirs(project_root)
    if not any(is_canonical_authority(p, canonical_root) for p in copies):
        return False, (
            f"[AUTHORITY] {canonical_root} exists but is not an active authority "
            "(no work_plan.md)."
        )
    legacy = detect_legacy_copies(copies, str(canonical_root))
    # Backup snapshots (.agent/backups/, _backups/) are intentional historical
    # copies, not an operational split-brain. detect_legacy_copies only filters
    # test fixtures, so exclude backups here (the guarded validate_authority.py
    # is not modified). Any remaining copy is a real divergence.
    operational_legacy = {
        path: ticket
        for path, ticket in legacy.items()
        if "backup" not in path.lower().replace("\\", "/")
    }
    if operational_legacy:
        listed = ", ".join(sorted(operational_legacy))
        return False, f"[AUTHORITY] split-brain: legacy collaboration copies: {listed}"
    return True, f"[AUTHORITY] single canonical authority: {canonical_root}"


def check_link(project_root: Path, motor_root_arg: Path | None) -> tuple[bool, str]:
    """Validate motor_destination_link.json resolves coherent roots.

    resolve_motor_link() only guarantees the 'motor_root' key, so this also
    validates 'destination_root' (it must exist and match --project-root) and,
    when provided, that --motor-root agrees with the link. Fails closed on a
    missing or invalid link.
    """
    link = resolve_motor_link(project_root)
    if link is None:
        return False, (
            "[LINK] motor_destination_link.json missing or invalid at "
            f"{project_root / '.agent' / 'config' / 'motor_destination_link.json'}"
        )
    motor_root = link.get("motor_root")
    destination_root = link.get("destination_root")
    if not motor_root:
        return False, "[LINK] link has no 'motor_root'."
    if not destination_root:
        return False, "[LINK] link has no 'destination_root'."
    try:
        if Path(destination_root).resolve() != project_root.resolve():
            return False, (
                f"[LINK] destination_root {destination_root} does not match "
                f"--project-root {project_root}"
            )
        if motor_root_arg is not None and (
            Path(motor_root).resolve() != motor_root_arg.resolve()
        ):
            return False, (
                f"[LINK] link motor_root {motor_root} does not match "
                f"--motor-root {motor_root_arg}"
            )
    except (OSError, ValueError) as exc:
        return False, f"[LINK] could not resolve link roots: {exc}"
    return True, f"[LINK] motor_root + destination_root coherent ({motor_root})"


def check_destination_context(project_root: Path) -> tuple[bool, str]:
    """Confirm the destination context resolves the motor link (no mutation)."""
    link = resolve_motor_link(project_root)
    if link is None or not link.get("motor_root"):
        return False, "[CONTEXT] destination context cannot resolve motor link."
    return True, "[CONTEXT] destination context resolves motor link."


def run_publication_audit(motor_root: Path) -> tuple[bool, str]:
    """Optional first-publication audit. Delegates to build_manifest (dry-run).

    Only runs behind --audit-publication. Never mutates the repo. Reports a
    finding (ok=False) if the manifest flags secrets in tree or history.
    """
    manifest = build_manifest(motor_root, scan_history=True, out_path=None)
    tree = manifest.get("tree_secret_scan", {}).get("findings") or []
    history = manifest.get("history_secret_scan", {}).get("findings") or []
    findings = len(tree) + len(history)
    if findings:
        return False, (
            f"[AUDIT] publication audit found {findings} secret finding(s) "
            f"(tree={len(tree)}, history={len(history)}); "
            f"verdict={manifest.get('verdict')}."
        )
    return True, "[AUDIT] publication audit clean (no secret findings)."


def run_integration(
    project_root: Path,
    motor_root_arg: Path | None,
    audit_publication: bool,
) -> int:
    """Run the integration gate. Returns one of the EXIT_* codes."""
    # 1. Link first: everything else needs coherent roots.
    ok, diag = check_link(project_root, motor_root_arg)
    print(diag)
    if not ok:
        return EXIT_CONFIG_ERROR

    # 2. Destination authority (canonical, no split-brain).
    ok, diag = check_destination_authority(project_root)
    print(diag)
    if not ok:
        return EXIT_CHECK_FAILED

    # 3. Destination context resolves the motor link.
    ok, diag = check_destination_context(project_root)
    print(diag)
    if not ok:
        return EXIT_CHECK_FAILED

    # 4. Operational pre-push gate (delegate by import, propagate exit code).
    argv = ["--project-root", str(project_root)]
    if motor_root_arg is not None:
        argv += ["--motor-root", str(motor_root_arg)]
    print("[GATE] delegating to check_destino_publish_ready.main()")
    rc = publish_ready_main(argv)
    if rc == 1 or rc == 3:
        return EXIT_CHECK_FAILED
    if rc == 2:
        return EXIT_STATUS_NOT_PUBLISHABLE

    # 5. Optional first-publication audit (explicit flag only).
    if audit_publication:
        link = resolve_motor_link(project_root)
        motor_root = Path(link["motor_root"])
        ok, diag = run_publication_audit(motor_root)
        print(diag)
        if not ok:
            return EXIT_CHECK_FAILED

    print("[OK] motor<->destino integration gate passed.")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Integrated motor<->destino integration + lifecycle gate.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exit codes: 0 OK; 1 check failed; 2 STATUS not publishable; "
            "3 config error (link/root)."
        ),
    )
    parser.add_argument(
        "--project-root",
        required=True,
        type=Path,
        help="Ruta al repo_destino (workspace activo).",
    )
    parser.add_argument(
        "--motor-root",
        default=None,
        type=Path,
        help="Ruta al repo_motor. Si se omite, se resuelve desde el link.",
    )
    parser.add_argument(
        "--audit-publication",
        action="store_true",
        help="Corre la auditoria de primera publicacion (dry-run, mas cara). "
        "Por defecto solo corre el gate operativo pre-push.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    project_root = args.project_root.resolve()
    if not project_root.exists():
        print(f"[ERROR] --project-root no existe: {project_root}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    return run_integration(project_root, args.motor_root, args.audit_publication)


if __name__ == "__main__":
    sys.exit(main())
