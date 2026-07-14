#!/usr/bin/env python3
"""Guard-of-guards: a guard nobody invokes is a norm, not a barrier (WOT-2026-024u).

The disease this exists to stop
-------------------------------
On 2026-07-14 the same failure appeared five times in one day, always with the same
shape: **the guard existed, worked, was fail-closed -- and nothing invoked it.**

- `check_worktree_topology.py` detects "you are committing from the detached consumption
  checkout" and exits 1 with the right message. It was in ZERO of the 19 pre-commit
  hooks. A session committed there anyway; its two commits landed on a detached HEAD,
  reachable from no branch, one `sync_principal.py` away from being lost.
- `guard_paths.py` (the write-guard) works -- and is wired only in the motor itself,
  in 0 of 13 destinations. A belt hanging in the garage.
- `check_motor_pristine.py --check` has no call-site at all.
- The portable-memory archive is written, versioned and pushed -- and **nothing reads
  it back**.

The measurement, the day this was written: **15 of 25 guards did not run on their own**
(9 cited only in prompts, 6 not cited anywhere). Among the nine "cited but never run"
were `check_backlog_commits_landed`, `validate_batch_dag` and `validate_observations`
-- the three the orchestrator had used *by hand* that same day as mandatory barriers.
They ran because someone remembered. That is not a barrier.

What this checks
----------------
A guard is WIRED if something that runs on its own invokes it: a pre-commit hook, CI,
`prepush_check`, the session closeout, a pipeline preflight, or the controller. Being
cited in a prompt, a skill or AGENTS.md is NOT wiring: it is a norm, and this repo has
broken its own norms repeatedly.

The rule is deliberately asymmetric, for the same reason WOT-2026-024t is:
- **Existing debt WARNS.** Failing on the 15 known-unwired guards would be dead noise
  and would block every close until they are all wired.
- **A NEW guard FAILS.** If you add `scripts/check_foo.py` and wire it nowhere, this
  check stops you. That is the only rule that makes the debt stop growing.

The debt is therefore NAMED IN CODE (`KNOWN_UNWIRED` below), each entry with the ticket
that owns it. A silent allowlist is how debt becomes invisible; a loud one is how it
gets paid.

Before: run from anywhere; resolves the motor root from this file's location.
During: enumerates `scripts/{check,validate,guard}_*.py`, and for each looks for an
        invocation in the self-running paths. Classifies wired / norm-only / orphan.
After:  exit 0 = every unwired guard is a declared, ticketed exception.
        exit 1 = a guard is unwired and undeclared -> wire it, or add it to
        KNOWN_UNWIRED with the ticket that will.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


MOTOR_ROOT = Path(__file__).resolve().parent.parent

GUARD_PREFIXES = ("check_", "validate_", "guard_")

# This module is the guard-of-guards; it cannot meaningfully audit itself.
SELF = "check_guard_wiring"


# Paths that RUN ON THEIR OWN. Being invoked from one of these is what "wired" means.
# A prompt, a skill or AGENTS.md is NOT here on purpose: those are norms, not mechanisms.
def self_running_paths(root: Path) -> list[Path]:
    return [
        root / ".pre-commit-config.yaml",
        *(root / ".github" / "workflows").glob("*.yml"),
        root / "scripts" / "prepush_check.py",
        root / "scripts" / "session_closeout.py",
        *(root / "scripts" / "closeout_steps").glob("*.py"),
        *(root / "scripts").glob("preflight_*.py"),
        root / ".agent" / "agent_controller.py",
    ]


# Known, ticketed debt. Each entry: guard -> the ticket that will wire it (or explain why
# it must not be). Adding an entry here is a DECISION, and it is visible in review.
KNOWN_UNWIRED: dict[str, str] = {
    # Cited in prompts, executed by nobody. The orchestrator ran these BY HAND on
    # 2026-07-14 as mandatory barriers -- they worked because someone remembered.
    "check_backlog_commits_landed": "WOT-2026-024c",  # barrera 6 del batch, a mano
    "validate_batch_dag": "WOT-2026-023t",  # gate de frescura del DAG, a mano
    "validate_observations": "WOT-2026-024r",  # canal de memoria, a mano
    "check_portable_memory_promotion": "WOT-2026-024r",
    "check_motor_pristine": "WOT-2026-023y",  # --check no tiene un solo call-site
    "check_destino_publish_ready": "WOT-2026-023b",
    "check_skill_collisions": "WOT-2026-024u",
    "check_ticket_nomenclature": "WOT-2026-024u",
    "validate_contract_formation": "WOT-2026-023m",
    # Not even cited anywhere.
    "check_closeout_reconciliation": "WOT-2026-024u",
    "check_motor_destination_integration": "WOT-2026-024u",
    "check_publication_gate": "WOT-2026-024u",
    "check_template_conformity": "WOT-2026-024u",
    "validate_agent_config": "WOT-2026-019o",  # su propia ficha lo declara: no valida agents.json
    "validate_authority": "WOT-2026-024u",
}


def find_guards(root: Path) -> list[str]:
    return sorted(
        p.stem
        for p in (root / "scripts").glob("*.py")
        if p.stem.startswith(GUARD_PREFIXES) and p.stem != SELF
    )


def is_wired(guard: str, haystack: str) -> bool:
    """A guard is wired if a self-running path invokes it by filename or import."""
    return (
        f"{guard}.py" in haystack
        or f"scripts.{guard}" in haystack
        or f"from {guard}" in haystack
        or f"import {guard}" in haystack
    )


def audit(root: Path) -> tuple[list[str], list[str]]:
    """Return (wired, unwired) guard names."""
    haystack = "\n".join(
        p.read_text(encoding="utf-8", errors="replace")
        for p in self_running_paths(root)
        if p.exists()
    )
    wired, unwired = [], []
    for g in find_guards(root):
        (wired if is_wired(g, haystack) else unwired).append(g)
    return wired, unwired


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--motor-root", default=str(MOTOR_ROOT))
    ap.add_argument(
        "--strict",
        action="store_true",
        help="fail on ALL unwired guards, including the declared debt (retro audit)",
    )
    args = ap.parse_args(argv)
    root = Path(args.motor_root).resolve()

    wired, unwired = audit(root)
    undeclared = [g for g in unwired if g not in KNOWN_UNWIRED]
    declared = [g for g in unwired if g in KNOWN_UNWIRED]

    print(
        f"[guard-wiring] {len(wired)} wired / {len(unwired)} unwired "
        f"({len(declared)} declared debt, {len(undeclared)} UNDECLARED)"
    )

    if declared:
        print("[guard-wiring] declared debt (WARN, each with its ticket):")
        for g in declared:
            print(f"    {g}  -> {KNOWN_UNWIRED[g]}")

    if undeclared:
        print("\n[guard-wiring] ERROR: guard(s) that run NOWHERE and are NOT declared:")
        for g in undeclared:
            print(f"    {g}")
        print(
            "\n  A guard nobody invokes is a norm, not a barrier -- and this repo has\n"
            "  broken its own norms repeatedly. WIRE IT into a self-running path\n"
            "  (pre-commit, CI, prepush, closeout, preflight, controller), or add it to\n"
            "  KNOWN_UNWIRED with the ticket that will."
        )
        return 1

    if args.strict and declared:
        print("\n[guard-wiring] --strict: the declared debt counts as failure.")
        return 1

    print("[guard-wiring] OK: every unwired guard is a declared, ticketed exception.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
