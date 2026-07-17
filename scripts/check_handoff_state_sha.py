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
2026-07-17) and was deferred to a design follow-up (WOT-2026-024t-S1).

Before: a project root (repo_destino) whose reports dir may hold handoff docs.
During: parse each handoff doc by heading; collect SHAs under state headings.
After: return the hits; the caller decides WARN vs FAIL. Read-only, no mutation.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


# Headings that name the CURRENT state of a flight/session (where a SHA rots).
_STATE_HEADING_RE = re.compile(
    r"estado|status|\bstate\b|donde\s+est|where\s+is|donde\s+va|situacion",
    re.IGNORECASE,
)
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
            in_state = bool(_STATE_HEADING_RE.search(current_heading))
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
