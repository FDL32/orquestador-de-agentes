#!/usr/bin/env python3
r"""Guard: enforce MANIFEST.distribute as the distribution frontier (WOT-2026-025i).

Today check_distribution_agnostic audits AGNOSTICISM (leaks), but nobody enforces
that the manifest entries are valid. This guard closes that gap: it verifies every
manifest entry resolves to >=1 tracked file (no stale entries = no holes in the
frontier).

How it differs from check_distribution_agnostic:
  - That guard: "does what travels contain machine-specific names?" (AGNOSTICISM)
  - This guard: "does every manifest entry correspond to real tracked files?" (BOUNDARY)

The denominator is REUSED from check_distribution_agnostic via import (NOT
rewritten): build_denominator() and manifest_entries().

FAIL-CLOSED:
  - MANIFEST absent or empty -> exit 1
  - git ls-files fails -> exit 1
  - denominator empty -> exit 1
  - stale entry (resolves to 0 tracked files) -> exit 1

Publishes denominator on every path: "<N> entradas -> <M> ficheros versionados
auditados". A guard that doesn't publish its denominator cannot be distinguished
from "0 violations over 0 files".

Direction 2 (WOT-2026-043b, `--skill-citations`): `audit_skill_citations`
enforces the OPPOSITE frontier direction -- a file that travels must not cite a
governing prompt that does NOT travel. It enumerates NORMATIVE citations
(frontmatter `source_prompt`/`source_of_truth`) from `skills/*/SKILL.md` to
`prompts/*.md` and fails when the cited prompt exists in the motor but is absent
from MANIFEST.distribute. In-prose mentions are WARN. The debt measured on
2026-10-07 (14 of 19 normative citations) is FROZEN in `_FROZEN_DEBT` and
adjudicated by WOT-2026-043c; a frozen entry that stops reproducing fails as
STALE. This direction is deliberately NOT wired into pre-commit in this flight.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_distribution_agnostic import (
    build_denominator,
    manifest_entries,
)


MOTOR_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Direction 2: what TRAVELS must not cite what does NOT travel (WOT-2026-043b).
#
# `audit()` above enforces ONE direction of the frontier (manifest entry -> real
# tracked files). Nobody enforced the opposite: every NORMATIVE citation from a
# shipped `skills/*/SKILL.md` to a `prompts/*.md` must resolve to a file that
# MANIFEST.distribute ships. With the repo rule "skill apunta, prompt gobierna"
# (AGENTS.md), a skill that travels without its governing prompt reaches the
# destination as a pointer whose normative criterion is absent.
#
# NORMATIVE vs MENTION (the split the ticket demands, else the guard is
# circumvented): only the frontmatter keys that DECLARE the governing contract
# are ERROR; an in-prose reference is a WARN. `source_prompt` is the live key
# today; `source_of_truth` is accepted as its documented synonym.
# ---------------------------------------------------------------------------
_NORMATIVE_KEYS = ("source_prompt", "source_of_truth")
_PROMPT_REF_RX = re.compile(r"prompts/[A-Za-z0-9_./-]+\.md")

_FROZEN_DEBT_REASON = (
    "deuda congelada por WOT-2026-043b; WOT-2026-043c adjudica (el prompt entra "
    "en MANIFEST.distribute O la skill deja de citarlo)"
)

# FROZEN DEBT. Normative citations that TODAY point to a motor prompt absent from
# MANIFEST.distribute. Measured 2026-10-07 on the real tree: 14 of 19 normative
# citations. This guard does NOT repair the debt (that is WOT-2026-043c) -- it
# FREEZES it: any NEW such citation fails. An entry that stops producing a
# violation is STALE and fails too, so an exception cannot outlive the line that
# justified it (same rule as check_distribution_agnostic).
_FROZEN_DEBT: tuple[tuple[str, str], ...] = (
    (
        "skills/audit-autonomous-ticket-batch/SKILL.md",
        "prompts/audit_autonomous_ticket_batch.md",
    ),
    ("skills/audit-pipeline-codeonly/SKILL.md", "prompts/audit_pipeline_codeonly.md"),
    ("skills/backlog-admit/SKILL.md", "prompts/backlog_admit.md"),
    ("skills/backlog-triage/SKILL.md", "prompts/backlog_triage.md"),
    ("skills/doc-optimization/SKILL.md", "prompts/doc_optimization.md"),
    ("skills/escalate-to-motor/SKILL.md", "prompts/escalate_to_motor.md"),
    (
        "skills/manager-orchestrator-loop/SKILL.md",
        "prompts/manager_orchestrator_loop.md",
    ),
    (
        "skills/orchestrate-autonomous-ticket-batch/SKILL.md",
        "prompts/orchestrator_autonomous_ticket_batch.md",
    ),
    (
        "skills/orchestrate-destination-batch/SKILL.md",
        "prompts/orchestrator_destination_batch.md",
    ),
    (
        "skills/orchestrate-pipeline-codeonly/SKILL.md",
        "prompts/orchestrator_pipeline_codeonly.md",
    ),
    (
        "skills/session-close-full-audit/SKILL.md",
        "prompts/orchestrator_session_close_full_audit.md",
    ),
    ("skills/session-hop/SKILL.md", "prompts/session_hop.md"),
    ("skills/suite-optimization/SKILL.md", "prompts/suite_optimization.md"),
    (
        "skills/system-health-audit/SKILL.md",
        "prompts/audit_post_change_system_health.md",
    ),
)


def _frontmatter_lines(text: str) -> list[str]:
    """Inner lines of the leading ``---`` frontmatter block ([] if malformed).

    Before: ``text`` is the raw SKILL.md content.
    During: detects a leading ``---`` fence and collects lines up to its close.
    After: returns the inner lines, or [] when there is no well-formed fence.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return []
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[1:i]
    return []


def _normative_refs(frontmatter: list[str]) -> list[str]:
    """GOVERNING ``prompts/*.md`` citations declared in the frontmatter.

    Before: ``frontmatter`` are the inner frontmatter lines.
    During: keeps lines whose key is in ``_NORMATIVE_KEYS`` and extracts the first
        ``prompts/*.md`` path from the value; deduplicates, order preserved.
    After: returns the (possibly empty) list of cited prompt paths.
    """
    refs: list[str] = []
    seen: set[str] = set()
    for line in frontmatter:
        key, sep, raw = line.partition(":")
        if not sep or key.strip() not in _NORMATIVE_KEYS:
            continue
        value = raw.strip().strip('"').strip("'")
        match = _PROMPT_REF_RX.search(value)
        if match is None:
            continue
        ref = match.group(0)
        if ref not in seen:
            seen.add(ref)
            refs.append(ref)
    return refs


def _classify_citation(root: Path, ref: str, travels: set[str]) -> str | None:
    """Classify one cited prompt: 'unresolved' | 'violation' | None (travels).

    Before: ``ref`` is a ``prompts/*.md`` path; ``travels`` is the shipped set.
    During: unresolved = not present in the motor; violation = present in the
        motor but NOT shipped; None = shipped (fine).
    After: returns the classification string, or None; never raises.
    """
    if not (root / ref).is_file():
        return "unresolved"
    if ref not in travels:
        return "violation"
    return None


def _scan_skill_citations(
    root: Path, skills: list[Path], travels: set[str]
) -> tuple[
    int,
    list[tuple[str, str]],
    list[tuple[str, str]],
    list[tuple[str, str]],
]:
    """(n_refs, violations, unresolved, mentions) over the given SKILL.md files."""
    violations: list[tuple[str, str]] = []
    unresolved: list[tuple[str, str]] = []
    mentions: list[tuple[str, str]] = []
    n_refs = 0
    for skill in skills:
        rel = skill.relative_to(root).as_posix()
        text = skill.read_text(encoding="utf-8", errors="replace")
        refs = _normative_refs(_frontmatter_lines(text))
        n_refs += len(refs)
        ref_set = set(refs)
        for ref in refs:
            kind = _classify_citation(root, ref, travels)
            if kind == "unresolved":
                unresolved.append((rel, ref))
            elif kind == "violation":
                violations.append((rel, ref))
        mentions.extend(
            (rel, ref)
            for ref in sorted(set(_PROMPT_REF_RX.findall(text)))
            if ref not in ref_set
            and _classify_citation(root, ref, travels) == "violation"
        )
    return n_refs, violations, unresolved, mentions


def _render_skill_citations(
    n_skills: int,
    n_refs: int,
    violations: list[tuple[str, str]],
    unresolved: list[tuple[str, str]],
    mentions: list[tuple[str, str]],
    frozen: set[tuple[str, str]],
) -> tuple[int, list[str]]:
    """Render the direction-2 report and exit code (0 green, 1 red)."""
    unexempt = [(s, p) for s, p in violations if (s, p) not in frozen]
    fired = {(s, p) for s, p in violations if (s, p) in frozen}
    stale = sorted(k for k in frozen if k not in fired)

    out: list[str] = [
        f"[dist-boundary-skills] {n_skills} skills -> {n_refs} referencias "
        f"normativas auditadas ({len(violations)} fuera del manifiesto, "
        f"{len(frozen)} congeladas)"
    ]
    if unresolved:
        out.append(
            f"[dist-boundary-skills] WARN: {len(unresolved)} citas normativas "
            "apuntan a un prompt que NO existe en el motor (no es este eje):"
        )
        out.extend(f"      {s} -> {p}" for s, p in unresolved)
    if mentions:
        out.append(
            f"[dist-boundary-skills] WARN: {len(mentions)} menciones en prosa a un "
            "prompt que no viaja (no son cita normativa; no fallan):"
        )
        out.extend(f"      {s} -> {p}" for s, p in mentions)
    if unexempt:
        out.append("")
        out.append(
            "[dist-boundary-skills] ERROR: cita NORMATIVA a un prompt que existe en "
            "el motor pero NO viaja (no esta en MANIFEST.distribute):"
        )
        out.extend(f"      {s} -> {p}" for s, p in unexempt)
        out.append(
            "  Arreglo: anade el prompt a MANIFEST.distribute, o deja de citarlo "
            "como gobernante (regla: 'skill apunta, prompt gobierna')."
        )
    if stale:
        out.append("")
        out.append(
            "[dist-boundary-skills] ERROR: FROZEN_DEBT STALE (la cita ya no produce "
            "violacion). Motivo declarado: " + _FROZEN_DEBT_REASON
        )
        out.extend(f"      {s} -> {p}" for s, p in stale)
    if unexempt or stale:
        return 1, out
    out.append(
        "[dist-boundary-skills] OK: ninguna cita normativa referencia un prompt que "
        "no viaja."
    )
    return 0, out


def audit_skill_citations(
    root: Path,
    frozen_debt: tuple[tuple[str, str], ...] | None = None,
) -> tuple[int, list[str]]:
    """Audit direction 2: skills that TRAVEL must not cite prompts that do NOT.

    Before: ``root`` is a motor tree with MANIFEST.distribute and a git repo;
        ``frozen_debt`` overrides the module baseline (tests pass an explicit
        tuple so a fixture root does not inherit the real repo's exceptions;
        None = use ``_FROZEN_DEBT``).
    During: builds the shipped-file set via ``build_denominator`` (manifest
        entries expanded by ``git ls-files``), then for every skills/*/SKILL.md
        splits NORMATIVE frontmatter citations (ERROR if the prompt exists in
        the motor but is not shipped) from in-prose mentions (WARN).
    After: returns (exit_code, output_lines). Publishes the denominator on every
        path. exit 1 = a new unexempt citation, a stale baseline entry, a
        fail-closed denominator (git missing / empty), or 0 skills (an explicit
        SKIP, which is NOT a pass). exit 0 = no unexempt citation, no stale.
    """
    frozen = set(_FROZEN_DEBT if frozen_debt is None else frozen_debt)
    skills = sorted((root / "skills").glob("*/SKILL.md"))
    _n_entries, travels, err = build_denominator(root)
    if err is not None:
        return 1, [
            f"[dist-boundary-skills] ERROR: {err}",
            "[dist-boundary-skills] 0 skills -> 0 referencias normativas auditadas "
            "(FAIL-CLOSED)",
        ]
    if not skills:
        return 1, [
            "[dist-boundary-skills] SKIP EXPLICITO: 0 skills/*/SKILL.md auditados; "
            "0 ficheros NO es un PASS (FAIL-CLOSED)."
        ]
    n_refs, violations, unresolved, mentions = _scan_skill_citations(
        root, skills, set(travels)
    )
    return _render_skill_citations(
        len(skills), n_refs, violations, unresolved, mentions, frozen
    )


def _git_ls_files(root: Path, entry: str) -> tuple[int, list[str]]:
    """(returncode, matched tracked paths) for `git ls-files -- <entry>`."""
    git = shutil.which("git")
    if git is None:
        return 1, []
    try:
        p = subprocess.run(  # noqa: S603 - git resuelto por shutil.which, args fijos
            [git, "ls-files", "--", entry],
            capture_output=True,
            text=True,
            cwd=str(root),
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 1, []
    files = [ln.strip() for ln in p.stdout.splitlines() if ln.strip()]
    return p.returncode, files


def audit(root: Path) -> tuple[int, list[str]]:
    """Return (exit_code, output_lines). Publishes denominator on every path."""
    out: list[str] = []

    entries = manifest_entries(root)
    if not entries:
        out.append("[dist-boundary] ERROR: MANIFEST.distribute is missing or empty")
        out.append("[dist-boundary] 0 entradas -> 0 ficheros (FAIL-CLOSED)")
        return 1, out

    n_entries, files, err = build_denominator(root)
    if err is not None:
        out.append(f"[dist-boundary] ERROR: {err}")
        out.append(
            f"[dist-boundary] {n_entries} entradas -> 0 ficheros versionados "
            "auditados (FAIL-CLOSED)"
        )
        return 1, out

    out.append(
        f"[dist-boundary] {n_entries} entradas -> {len(files)} ficheros versionados "
        "auditados"
    )

    stale_entries: list[str] = []
    for entry in entries:
        rc, matched = _git_ls_files(root, entry)
        if rc != 0:
            stale_entries.append(f"  {entry} (git ls-files failed, rc={rc})")
        elif not matched:
            stale_entries.append(f"  {entry} (0 tracked files)")

    if stale_entries:
        out.append(
            "[dist-boundary] ERROR: stale manifest entry (resolves to 0 tracked "
            "files = hole in the frontier):"
        )
        out.extend(stale_entries)
        return 1, out

    out.append("[dist-boundary] OK: all manifest entries resolve to tracked files.")
    return 0, out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--motor-root", default=str(MOTOR_ROOT))
    ap.add_argument(
        "--skill-citations",
        action="store_true",
        help=(
            "audit direction 2: NORMATIVE citations from skills/*/SKILL.md to "
            "prompts/*.md that MANIFEST.distribute does not ship (WOT-2026-043b). "
            "Deliberately NOT wired into pre-commit in this flight."
        ),
    )
    args = ap.parse_args(argv)
    root = Path(args.motor_root).resolve()
    if args.skill_citations:
        code, lines = audit_skill_citations(root)
    else:
        code, lines = audit(root)
    stream = sys.stderr if code else sys.stdout
    for ln in lines:
        print(ln, file=stream)
    return code


if __name__ == "__main__":
    sys.exit(main())
