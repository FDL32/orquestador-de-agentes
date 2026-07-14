#!/usr/bin/env python3
"""Guard-of-guards: a guard nobody invokes is a norm, not a barrier (WOT-2026-024u).

The disease this exists to stop
-------------------------------
On 2026-07-14 the same failure appeared five times in one day, always with the same
shape: **the guard existed, worked, was fail-closed -- and nothing invoked it.**

- `check_worktree_topology.py` detects "you are committing from the detached consumption
  checkout" and exits 1 with the right message. It was in ZERO of the pre-commit hooks.
  A session committed there anyway; its two commits landed on a detached HEAD, reachable
  from no branch, one `sync_principal.py` away from being lost.
- `check_motor_pristine.py --check` has no call-site at all.
- The portable-memory archive is written, versioned and pushed -- and **nothing reads
  it back** (`bus/memory_loader.py` reads the gitignored runtime file, not the archive).

What counts as WIRED (and what emphatically does not)
-----------------------------------------------------
A guard is WIRED if something that RUNS ON ITS OWN invokes it: an automatic pre-commit
hook, CI, `prepush_check`, the session closeout, a pipeline preflight, the controller, or
the Claude Code tool-call hooks. Being cited in a prompt, a skill or AGENTS.md is NOT
wiring: it is a norm, and this repo has broken its own norms repeatedly.

The first version of this module was itself a false-green -- caught by an adversarial
sibling audit before it ever reached origin. It matched guard names against the raw TEXT
of the self-running files, which meant:

- a guard named only inside a **YAML comment** counted as wired (`check_ruff_hook_scope`
  appears exactly once in `.pre-commit-config.yaml`, in the comment on the ruff hook --
  and nothing executes it);
- a hook with **`stages: [manual]`** counted as wired, though a manual hook is by
  definition something a human must remember to run (`check_hook_interpreter`);
- a **substring** counted as a match, so a future `scripts/check_backlog.py` would have
  been blessed by the existing `check_backlog_commits_landed`;
- and the inventory only globbed `scripts/`, so it never even saw `.agent/hooks/
  guard_paths.py` -- the write-guard, the very example the docstring above cites.

So this version extracts invocations STRUCTURALLY (YAML is parsed; Python is parsed with
`ast`, and comments and docstrings are discarded) and matches on word boundaries. A guard
mentioned in prose is not a guard that runs.

The asymmetric rule
-------------------
- **Existing debt WARNS.** Failing on every unwired guard would be dead noise and would
  block every close until they are all wired.
- **A NEW guard FAILS.** If you add a guard and wire it nowhere, this check stops you.
  That is the only rule that makes the debt stop growing.
- **A STALE entry FAILS.** If a declared-unwired guard gets wired (or deleted), its
  allowlist entry must go. Otherwise the allowlist rots into a cemetery that pre-blesses
  any future file with that name.

The debt is NAMED IN CODE (`KNOWN_UNWIRED`), each entry with the ticket that owns it, or
an explicit `BY-DESIGN:` reason. A silent allowlist is how debt becomes invisible; a loud
one is how it gets paid. The owner is format-checked: a free-text owner is how the ghost
ticket WOT-2026-021a survived (decision accepted, zero rows in the backlog).

This module does NOT exempt itself. It cannot fail when it is unwired -- nothing would run
it -- but `tests/unit/test_check_guard_wiring.py` audits the real repo, and the suite runs
in CI. Remove the hook and CI goes red. That is what closes the loop.

Before: run from anywhere; resolves the motor root from this file's location.
After:  exit 0 = every unwired guard is a declared, ticketed exception.
        exit 1 = a guard runs nowhere and is undeclared, or an allowlist entry is stale.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

import yaml


MOTOR_ROOT = Path(__file__).resolve().parent.parent

GUARD_PREFIXES = ("check_", "validate_", "guard_")

# Where a guard can live. `scripts/` is not the only place: the write-guard lives in
# `.agent/hooks/`, and the first version of this module was blind to it.
GUARD_DIRS = ("scripts", ".agent/hooks", "skills", "tools", "bus", "runtime")

# An owner is a ticket that will wire it, or an explicit by-design exemption. Free text is
# how a ghost ticket (WOT-2026-021a: decision accepted, zero rows in the backlog) survives.
_TICKET = re.compile(r"^WOT-\d{4}-\d{3}[a-z]$")
_BY_DESIGN = "BY-DESIGN:"

KNOWN_UNWIRED: dict[str, str] = {
    # Cited in prompts, executed by nobody. The orchestrator ran these BY HAND on
    # 2026-07-14 as mandatory barriers -- they worked because someone remembered.
    "check_backlog_commits_landed": "WOT-2026-024c",  # barrera 6 del batch, a mano
    "validate_batch_dag": "WOT-2026-023t",  # gate de frescura del DAG, a mano
    "validate_observations": "WOT-2026-024r",  # canal de memoria, a mano
    "check_portable_memory_promotion": "WOT-2026-024r",
    "check_motor_pristine": "WOT-2026-023y",  # --check no tiene un solo call-site
    "check_destino_publish_ready": "WOT-2026-023b",
    "validate_contract_formation": "WOT-2026-023m",
    "validate_agent_config": "WOT-2026-019o",  # su ficha lo declara: no valida agents.json
    # Deuda que el parser HONESTO destapo (la version anterior los daba por cableados).
    # WOT-2026-024w es el ticket que los cablea o los retira: un dueno REAL, no un puntero
    # al propio 024u, cuyos NON-GOALS dicen por escrito que no los va a cablear.
    "check_ruff_hook_scope": "WOT-2026-024w",  # su unica cita era un COMENTARIO del yaml
    "check_skill_collisions": "WOT-2026-024w",
    "check_ticket_nomenclature": "WOT-2026-024w",
    "check_closeout_reconciliation": "WOT-2026-024w",
    "check_motor_destination_integration": "WOT-2026-024w",
    "check_publication_gate": "WOT-2026-024w",
    "check_template_conformity": "WOT-2026-024w",
    "validate_authority": "WOT-2026-024w",
    # Exencion DELIBERADA, no deuda: un hook automatico seria circular -- el propio hook
    # roto no puede invocar de forma fiable al check que detecta que esta roto.
    "check_hook_interpreter": (
        f"{_BY_DESIGN} stage manual deliberado; un hook automatico seria circular "
        "(el hook roto no puede invocar al check que detecta que esta roto)"
    ),
}


def self_running_paths(root: Path) -> list[Path]:
    """Paths that RUN ON THEIR OWN. Being invoked from one of these is what wired means.

    Prompts, skills and AGENTS.md are deliberately absent: those are norms, not mechanisms.
    """
    return [
        root / ".pre-commit-config.yaml",
        *(root / ".github" / "workflows").glob("*.yml"),
        root / ".claude" / "settings.json",  # los hooks de tool-call: corren solos
        root
        / ".agent"
        / "hooks"
        / "claude_guard_entry.py",  # el dispatcher del write-guard
        root / "scripts" / "prepush_check.py",
        root / "scripts" / "session_closeout.py",
        *(root / "scripts" / "closeout_steps").glob("*.py"),
        *(root / "scripts").glob("preflight_*.py"),
        root / ".agent" / "agent_controller.py",
    ]


def _hook_runs_on_its_own(hook: dict) -> bool:
    """A hook whose ONLY stage is `manual` does not run on its own: it is a norm."""
    stages = hook.get("stages")
    if not stages:
        return True  # sin `stages` -> todos los stages por defecto
    return any(s != "manual" for s in stages)


def _invocations_in_yaml(path: Path) -> str:
    """Parse the YAML. Comments vanish; manual-only pre-commit hooks are dropped."""
    data = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
    if path.name == ".pre-commit-config.yaml":
        auto = [
            h
            for repo in data.get("repos", [])
            for h in repo.get("hooks", [])
            if _hook_runs_on_its_own(h)
        ]
        return json.dumps(auto)
    return json.dumps(data)


def _invocations_in_python(path: Path) -> str:
    """Strings and imports, via `ast`. Comments and docstrings are NOT invocations."""
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        is_scope = isinstance(
            node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
        )
        if is_scope and node.body and isinstance(node.body[0], ast.Expr):
            val = node.body[0].value
            if isinstance(val, ast.Constant) and isinstance(val.value, str):
                docstrings.add(id(val))
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant):
            if isinstance(node.value, str) and id(node) not in docstrings:
                out.append(node.value)
        elif isinstance(node, ast.Import):
            out.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            out.append(mod)
            out.extend(f"{mod}.{a.name}" for a in node.names)
    return "\n".join(out)


def invocation_text(root: Path) -> str:
    """The haystack: only what the self-running paths actually INVOKE."""
    chunks: list[str] = []
    for p in self_running_paths(root):
        if not p.exists():
            continue
        try:
            if p.suffix in (".yaml", ".yml"):
                chunks.append(_invocations_in_yaml(p))
            elif p.suffix == ".py":
                chunks.append(_invocations_in_python(p))
            else:
                chunks.append(p.read_text(encoding="utf-8", errors="replace"))
        except (yaml.YAMLError, SyntaxError, OSError) as exc:
            # Fail-closed: si no puedo LEER un camino automatico, no puedo afirmar que un
            # guard este cableado. Callarme aqui es exactamente el fallo que persigo.
            raise SystemExit(
                f"[guard-wiring] ERROR: no puedo analizar {p}: {exc}"
            ) from exc
    return "\n".join(chunks)


def find_guards(root: Path) -> list[str]:
    names = {
        p.stem
        for d in GUARD_DIRS
        for p in (root / d).glob("*.py")
        if p.stem.startswith(GUARD_PREFIXES)
    }
    return sorted(names)


def is_wired(guard: str, haystack: str) -> bool:
    """Word-boundary match: `check_backlog` must NOT match `check_backlog_commits_landed`.

    `_` is a word character, so `\\b` does not fire between `backlog` and `_commits`.
    """
    return re.search(rf"\b{re.escape(guard)}\b", haystack) is not None


def audit(root: Path) -> tuple[list[str], list[str]]:
    haystack = invocation_text(root)
    wired, unwired = [], []
    for g in find_guards(root):
        (wired if is_wired(g, haystack) else unwired).append(g)
    return wired, unwired


def _bad_owners() -> list[str]:
    return [
        f"{g} -> {owner!r}"
        for g, owner in KNOWN_UNWIRED.items()
        if not (_TICKET.match(owner) or owner.startswith(_BY_DESIGN))
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--motor-root", default=str(MOTOR_ROOT))
    ap.add_argument(
        "--strict",
        action="store_true",
        help="fail on the declared debt too (retro audit; the BY-DESIGN entries never fail)",
    )
    args = ap.parse_args(argv)
    root = Path(args.motor_root).resolve()

    bad = _bad_owners()
    if bad:
        print("[guard-wiring] ERROR: allowlist entries with an unusable owner:")
        for b in bad:
            print(f"    {b}")
        print("  An owner must be a ticket (WOT-YYYY-NNNx) or start with 'BY-DESIGN:'.")
        return 1

    wired, unwired = audit(root)
    undeclared = [g for g in unwired if g not in KNOWN_UNWIRED]
    declared = [g for g in unwired if g in KNOWN_UNWIRED]
    stale = sorted(set(KNOWN_UNWIRED) - set(unwired))

    print(
        f"[guard-wiring] {len(wired)} wired / {len(unwired)} unwired "
        f"({len(declared)} declared, {len(undeclared)} UNDECLARED, {len(stale)} stale)"
    )

    if declared:
        print("[guard-wiring] declared, each with its owner:")
        for g in declared:
            print(f"    {g}  -> {KNOWN_UNWIRED[g]}")

    if undeclared:
        print("\n[guard-wiring] ERROR: guard(s) that run NOWHERE and are NOT declared:")
        for g in undeclared:
            print(f"    {g}")
        print(
            "\n  A guard nobody invokes is a norm, not a barrier -- and this repo has\n"
            "  broken its own norms repeatedly. WIRE IT into a self-running path\n"
            "  (pre-commit, CI, prepush, closeout, preflight, controller, tool-call\n"
            "  hooks), or add it to KNOWN_UNWIRED with the ticket that will."
        )
        return 1

    if stale:
        print(
            "\n[guard-wiring] ERROR: stale allowlist entr(ies) -- wired now, or gone:"
        )
        for g in stale:
            print(f"    {g}  (declared unwired, but it is not)")
        print(
            "\n  Remove them. An allowlist that keeps entries for guards that no longer\n"
            "  need them rots into a cemetery, and pre-blesses any future file with that\n"
            "  name -- the exact false-green this module exists to stop."
        )
        return 1

    debt = [g for g in declared if not KNOWN_UNWIRED[g].startswith(_BY_DESIGN)]
    if args.strict and debt:
        print(
            f"\n[guard-wiring] --strict: {len(debt)} guard(s) of declared debt count as failure."
        )
        return 1

    print("[guard-wiring] OK: every unwired guard is a declared, owned exception.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
