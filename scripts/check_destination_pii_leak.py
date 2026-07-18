#!/usr/bin/env python3
"""WOT-2026-020t: read-only auditor of destination PII-leak surfaces.

A destination repo that TRACKS `.agent/config/motor_destination_link.json` or
`.agent/collaboration/` publishes artifacts that carry absolute local paths
(``C:\\Users\\<user>\\...``) on every push. The installer gitignores those
surfaces (WOT-2026-016p / 020t BUG-2) but gitignore never UN-tracks what a
destination committed before the entry existed (BUG-1). This auditor LISTS the
destinations that still leak, without touching anything: the motor provides the
check, the human decides the action (WOT-2026-023b).

Scope (CF-audit E2): this audits the MANAGED KNOWN surfaces above only. It is
NOT a general PII scanner for anything outside those paths.

Census: reuses check_claude_settings_portability._discover_destinations -- the
single source of the machine census with full accounting
(included+skipped+excluded+deduped == links_total) and the identity-based
exclusion of the motor itself and THIS motor's dogfooding workspace (both
version .agent/collaboration/ on purpose; they are not leaks).

Walk-up guard (CF-audit E1, vector WOT-2026-020r): an INCLUDED destination
without its own ``.git`` is an OPERATIONAL ERROR (exit 2), never a green skip
-- running ``git ls-files`` there would walk up to a parent repo and answer for
the wrong tree, and "0 leaks" must never mean "0 audited".

Before: motor_root resolves to this repo (default) or --motor-root; git must be
        on PATH; sibling repos may carry motor_destination_link.json files.
During: censuses parent(motor_root) one level deep, then per included
        destination runs ``git -C <dest> ls-files -- <spec>`` for each managed
        pathspec (POSIX separators). Read-only: zero writes, zero index/worktree
        mutation anywhere.
After: exit 0 iff every included destination was audited and none leaks;
       exit 1 listing every leaking destination and file; exit 2 on operational
       error (git missing, or an included destination without .git), still
       listing any leaks found. Prints the census accounting so nothing is
       dropped silently.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.check_claude_settings_portability import _discover_destinations
from scripts.prefix_resolver import _git_executable


_MOTOR_ROOT = Path(__file__).resolve().parent.parent

# Managed known surfaces that carry local absolute paths (CF-audit E2: the
# closed audit scope, not a general PII scan). POSIX separators on purpose:
# git pathspecs want `/` even on Windows; never build these with Path().
AUDIT_PATHSPECS: tuple[str, ...] = (
    ".agent/config/motor_destination_link.json",
    ".agent/collaboration/",
)


@dataclass
class DestinationAudit:
    """Audit outcome for one INCLUDED destination.

    Exactly one of the shapes: clean (no leaks, no error), leaking
    (tracked_files non-empty), or unauditable (error is not None -- counts as
    operational failure, never as clean).
    """

    root: Path
    tracked_files: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def leaking(self) -> bool:
        return bool(self.tracked_files)


def _git_ls_files(repo: Path, pathspec: str) -> list[str]:
    """Return tracked files under pathspec in repo (its OWN .git, pre-checked).

    Before: repo/.git exists (caller enforces the walk-up guard E1).
    During: runs ``git -C repo ls-files -- pathspec`` capturing stdout.
    After: returns the tracked paths (possibly empty). Raises RuntimeError on a
    non-zero git exit so the caller records the destination as unauditable.
    """
    git = _git_executable()
    if git is None:
        raise RuntimeError("git not found on PATH")
    proc = subprocess.run(  # noqa: S603
        [git, "-C", str(repo), "ls-files", "--", pathspec],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"git ls-files rc={proc.returncode}: {proc.stderr.strip()[:200]}"
        )
    return [line for line in proc.stdout.splitlines() if line.strip()]


def audit_destination(dest: Path) -> DestinationAudit:
    """Audit one included destination against AUDIT_PATHSPECS.

    Before: dest is an included (external, deduped) destination root.
    During: E1 walk-up guard first -- without dest/.git the destination is
    UNAUDITABLE (git would answer for a parent repo); otherwise collects
    tracked files per managed pathspec.
    After: returns the DestinationAudit; never writes anything.
    """
    if not (dest / ".git").exists():
        return DestinationAudit(
            root=dest,
            error="no .git of its own: NOT audited (git would walk up, 020r)",
        )
    audit = DestinationAudit(root=dest)
    try:
        for spec in AUDIT_PATHSPECS:
            audit.tracked_files.extend(_git_ls_files(dest, spec))
    except (RuntimeError, OSError) as exc:
        audit.error = str(exc)
    return audit


def run_audit(motor_root: Path) -> tuple[list[DestinationAudit], object]:
    """Census + audit every included destination of the machine.

    Before: motor_root is this motor's repo root.
    During: _discover_destinations does the census (motor + dogfooding excluded
    by identity, aliases deduped, broken links skipped with reason); each
    included root is audited read-only.
    After: returns (audits, discovery) -- discovery carries the accounting the
    report prints so nothing is dropped silently.
    """
    discovery = _discover_destinations(motor_root.resolve())
    audits = [audit_destination(dest) for dest in discovery.included]
    return audits, discovery


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only audit: destinations must not track the link file nor "
            ".agent/collaboration/ (PII surfaces, WOT-2026-020t). Lists, never acts."
        )
    )
    parser.add_argument(
        "--motor-root",
        type=Path,
        default=_MOTOR_ROOT,
        help="Motor repo root; census scans its parent directory (default: this repo).",
    )
    args = parser.parse_args(argv)

    if _git_executable() is None:
        print("[pii-leak] ERROR: git not found on PATH; cannot audit.")
        return 2

    motor_root = args.motor_root.resolve()
    audits, discovery = run_audit(motor_root)

    print(
        f"[pii-leak] census: links_total={discovery.links_total} "
        f"included={len(discovery.included)} excluded={len(discovery.excluded)} "
        f"skipped={len(discovery.skipped)} deduped={len(discovery.deduped)}"
    )
    for name, reason in discovery.skipped:
        print(f"[pii-leak]   discovery-skip {name}: {reason}")
    for name, resolved in discovery.excluded:
        print(f"[pii-leak]   excluded-by-identity {name}: {resolved}")

    leaking = [a for a in audits if a.leaking]
    unauditable = [a for a in audits if a.error is not None]
    clean = len(audits) - len(leaking) - len(unauditable)

    for audit in unauditable:
        print(f"[pii-leak] UNAUDITABLE {audit.root}: {audit.error}")
    for audit in leaking:
        print(
            f"[pii-leak] LEAK {audit.root}: {len(audit.tracked_files)} tracked file(s)"
        )
        for f in audit.tracked_files:
            print(f"[pii-leak]     {f}")

    print(
        f"[pii-leak] result: {clean} clean, {len(leaking)} leaking, "
        f"{len(unauditable)} unauditable of {len(audits)} included"
    )
    if unauditable:
        print(
            "[pii-leak] exit 2: an included destination could not be audited "
            "(0 leaks would not mean 0 audited)."
        )
        return 2
    if leaking:
        print(
            "[pii-leak] exit 1: leaking destinations listed above. The fix is "
            "human-gated (WOT-2026-023b): git rm --cached there is NEVER automatic; "
            "the installer only untracks under explicit --untrack-existing."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
