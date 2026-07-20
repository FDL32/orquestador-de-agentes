#!/usr/bin/env python3
"""WOT-2026-024t (superficie 2): a handoff's STATE section must not embed a SHA.

"A DoD is an invariant, not a measurement" applied to handoff docs: a commit SHA
written into the STATE / "where is the flight" section of an ARRANQUE_*.md caducates
the instant HEAD moves (the flight's own ARRANQUE_CONTINUACION said "HEAD esperado
3721537" while HEAD had already advanced). The state must be VERIFIED against git,
not embedded.

Scope is BY SECTION (Markdown heading), never by file: a SHA in a *historical
commits* table, a command example, or a code block is LEGITIMATE and is not flagged.
Only SHAs under a heading that names the current STATE (estado / status / state /
"donde esta" / "where is") are hits. Conservative on purpose: a state section with an
unusual heading is a false negative we accept; we do not want false reds on history.

Surface 1 of the ticket -- detecting a stale MEASUREMENT embedded under a `DoD:`
marker in the backlog -- is an irreducibly fuzzy classifier (CF-audit Codex,
2026-07-17) and was deferred to a design follow-up: ticket WOT-2026-034c
(ex-024t-S1), tracked in the destino backlog.

Before: a project root (repo_destino) whose reports dir may hold handoff docs.
During: parse each handoff doc by heading; collect SHAs under state headings.
After: return the hits; the caller decides WARN vs FAIL. Read-only, no mutation.
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path


# WOT-2026-034b: state-heading detection is accent-normalized and looks at the
# MAIN TERM (the heading's subject), not a raw substring over prose. Two defects
# motivated this (both reproduced live before the fix):
#   (1) false NEGATIVE: an ACCENTED state heading (`## Donde esta el vuelo` with
#       the accents present) did not match the unaccented regex -- IGNORECASE
#       does not fold accents. The motivating flight's own handoff escaped the
#       guard for exactly this reason.
#   (2) false POSITIVE: a heading where the state word is subordinated by a
#       LEADING genitive (`## Resumen del estado del arte` -> the subject is
#       "Resumen", "estado" is its object) was flagged, because `.search()`
#       matched the substring anywhere. That SHA is prose, not stale state.
#
# Deliberately NARROW (WOT-2026-034b re-review, adversarial audit): only a
# genitive BEFORE the term subordinates it. A TRAILING `de(l)` does NOT, because
# `Estado del motor` / `Estado del vuelo` / `Estado de la sesion` are the single
# most natural way to write a real state heading in Spanish -- suppressing them
# would reintroduce the exact false negative this ticket closes (a real
# `## Estado del motor` with an embedded HEAD SHA was found escaping an earlier,
# over-broad version of this guard). The pure idiom `## Estado del arte` as a
# standalone heading therefore stays flagged: an accepted, rare FALSE POSITIVE
# (a self-correcting spurious red) is far safer than a false negative that lets
# a rot-prone SHA escape. Other known accepted limits (conservative by design,
# WOT-2026-024t): plurals/morphology (`estados`, `estatus`), and English
# `of`-genitives (`State of the art` is not folded like `de`/`del`).
#
# Terms that name the CURRENT state of a flight/session (where a SHA rots).
# Split into whole-word terms (need \b bounds) and phrase terms (the
# `donde est...` family deliberately has NO trailing bound so it matches
# `esta`/`esta(n)`/`estamos`, etc., after accent-folding).
_STATE_TERM_RE = re.compile(
    r"(?:\b(?:estado|status|state|situacion)\b)"
    r"|(?:\b(?:donde\s+est|donde\s+va|where\s+is))",
)
# A genitive `de`/`del` BEFORE the term subordinates it to another subject
# (`Resumen del estado ...`) -> prose, not the heading's own state subject.
_GENITIVE_BEFORE_RE = re.compile(r"\b(?:de|del)\b")


def _strip_accents(text: str) -> str:
    """NFD-decompose and drop combining marks, then lowercase (accent-fold)."""
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn").lower()


def _is_state_heading(heading: str) -> bool:
    """True if `heading` names the CURRENT state (accent-folded, main-term).

    A heading is a state heading when a state term appears as the heading's own
    SUBJECT: accent-folded, matched as a word/phrase, and NOT subordinated by a
    genitive `de`/`del` appearing BEFORE it. Conservative by design
    (WOT-2026-024t): an unusual state heading is an accepted false negative; we
    do not want false reds on history/prose. This is a bounded heuristic, not a
    grammar parser -- see the module comment for its declared accepted limits
    (the standalone idiom `estado del arte`, plurals, and English `of`).
    """
    folded = _strip_accents(heading)
    match = _STATE_TERM_RE.search(folded)
    if match is None:
        return False
    return not _GENITIVE_BEFORE_RE.search(folded[: match.start()])


# A git SHA shape: 7-40 hex. `\b` bounds keep it from matching inside longer tokens.
_SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b", re.IGNORECASE)
_HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$")
# Handoff docs: ARRANQUE_*.md (and the bare ARRANQUE.md).
_HANDOFF_GLOBS = ("ARRANQUE*.md",)


def find_state_section_shas(text: str) -> list[dict]:
    """Return [{line, heading, sha}] for SHAs found under a STATE heading.

    Code fences (``` command examples) and non-state sections are skipped: their
    SHAs are legitimate (a command to run, a historical commit), not stale state.
    """
    hits: list[dict] = []
    current_heading = ""
    in_state = False
    in_code = False
    for i, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        hm = _HEADING_RE.match(line)
        if hm:
            current_heading = hm.group(1).strip()
            in_state = _is_state_heading(current_heading)
            continue
        if in_state:
            hits.extend(
                {"line": i, "heading": current_heading, "sha": m.group(0)}
                for m in _SHA_RE.finditer(line)
            )
    return hits


def _iter_handoff_docs(root: Path):
    reports = root / "orchestrator_pipeline" / "reports"
    if not reports.is_dir():
        return
    for pattern in _HANDOFF_GLOBS:
        yield from reports.rglob(pattern)


def scan_handoffs(root: Path) -> list[dict]:
    """Return [{file, line, heading, sha}] across all handoff docs under root."""
    findings: list[dict] = []
    for doc in sorted(_iter_handoff_docs(root)):
        try:
            text = doc.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        findings.extend(
            {"file": str(doc), **hit} for hit in find_state_section_shas(text)
        )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Flag SHAs embedded in handoff STATE sections (WOT-2026-024t)."
    )
    parser.add_argument("--project-root", required=True, help="repo_destino root.")
    args = parser.parse_args(argv)

    root = Path(args.project_root).resolve()
    if not root.exists():
        print(
            f"[handoff-state-sha] project root does not exist: {root}", file=sys.stderr
        )
        return 2

    findings = scan_handoffs(root)
    if findings:
        print(
            f"[handoff-state-sha] {len(findings)} SHA(s) embedded in a handoff STATE "
            f"section (they rot the instant HEAD moves; verify state against git):",
            file=sys.stderr,
        )
        for f in findings:
            print(
                f"  - {f['file']}:{f['line']} under '{f['heading']}': {f['sha']}",
                file=sys.stderr,
            )
        return 1
    print("[handoff-state-sha] OK: no SHA embedded in a handoff state section")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
