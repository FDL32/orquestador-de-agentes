#!/usr/bin/env python3
"""WOT-2026-034c: fail-closed detector for MEASUREMENTS THAT EXPIRE IN SILENCE.

A DoD must be an INVARIANT, not a MEASUREMENT. A criterion that pins a number
("quedan 11 hits", "243 auditorias", "177 filas") EXPIRES: the repo stays alive
and the number drifts without anyone touching the ficha, so the Builder receives
a FALSE contract -- and worse, cannot tell "the number changed because the world
moved" from "the number changed because I broke something".

The number is not garbage: it is EVIDENCE, and it must live LABELLED AS A DATED
SNAPSHOT, never as a criterion. This guard makes that rule executable.

Before: the destino root MUST be given via --project-root / --workspace-root or
    AGENT_PROJECT_ROOT. A backlog read relative to the motor cwd would be the
    wrong file (the motor seed, not the destino queue), so a missing root is a
    fail-closed error, never a pass-open.
During: parse the live "Vista rapida" table (delegated wholesale to
    check_backlog_contract._extract_active_table -- this guard NEVER reimplements
    the markdown-table regex, per WOT-2026-040s/054b) and, for every figure+noun
    token, require a temporal anchor (MEDIDO <fecha> | snapshot <sha7>) in the
    SAME SENTENCE.
After: exit 0 when every live figure is anchored or allowlisted; exit 1 with one
    named violation per offending row otherwise. No mutation, ever.

WIRING: standalone by design. Cabling this into prepush is a declared NON-GOAL of
    WOT-2026-034c and will be requested as its own follow-up ticket; this module
    is CLI-only until then, and that debt is DECLARED here so the wiring audit can
    see it rather than infer an orphan.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# WOT-2026-034c: the table parser is IMPORTED, never duplicated. Reimplementing
# the row regex is exactly how WOT-2026-040s (glued logical rows) and
# WOT-2026-054b (orphan fragments) got their corrections stranded in one copy.
from scripts.check_backlog_contract import (
    _extract_active_table,
    resolve_destino_root,
)


EXIT_OK = 0
EXIT_VIOLATIONS = 1
EXIT_SELF_FAIL = 2

# Figure+noun: the shape of an embedded measurement. The unit list is CLOSED --
# an open \w+ noun would match every ordinal in the corpus.
_FIGURE_RE = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:%|filas|entradas|tokens|bytes|ms|s\b)",
    re.IGNORECASE,
)

# Temporal anchor that REDEEMS a figure: an explicit measurement date or a
# snapshot pinned to a short sha (7+ hex, matching the repo convention).
_ANCHOR_RE = re.compile(
    r"MEDIDO\s+\d{4}-\d{2}-\d{2}|snapshot\s+[0-9a-f]{7,}",
    re.IGNORECASE,
)

# MEASURED FALSE-POSITIVE CLASS (2026-08-27, 268 live rows): the naive
# figure regex matches the TAIL OF A TICKET ID -- `WOT-2026-027s` yields the
# token `027s` via the `\d+\s*s\b` branch. 26 of 390 matches (6.7%) were this
# and nothing else. A ticket id is an IDENTIFIER, never a measurement, so its
# span is excised before the figure scan. Same family as the archive-side
# lesson: anchor to the row SHAPE, never to a loose id.
# MEASURED 2026-08-27: live ids are not all numeric-suffixed --
# `WOT-2026-STATE-RECON-A` is a real live row. A too-narrow id shape made the
# guard report `<unknown>`, which would have entered the census as junk.
_TICKET_ID_SPAN_RE = re.compile(
    r"(?:WOT|WP|WT|CTL)-\d{4}-\w+(?:-\w+)*",
    re.IGNORECASE,
)

# Sentence boundary for the anchor window. A backlog cell is not prose: the
# separators that actually delimit one claim from the next are the cell pipe,
# a period, a newline, the `==` rule and the literal `DoD:` lead-in.
_SENTENCE_SPLIT_RE = re.compile(r"\n|==|(?<!\d)\.(?!\d)|DoD:|\|")

# Versioned allowlist for the HISTORICAL corpus (WOT-2026-034c). Rows already
# carrying an unanchored figure BEFORE this guard existed are debt, not new
# breakage: silencing them keeps the gate honest for NEW writing while the
# backlog is drained. Entries are ticket ids; removing one re-arms the check.
# Anything added here later must cite why, or the allowlist becomes a mute button.
# SNAPSHOT eca1e16 (MEDIDO 2026-08-27): 89 offending live rows of 268 at the
# moment this guard was born. The census is EVIDENCE, dated -- never a criterion.
_DOD_METRIC_LEGACY_BASELINE: frozenset[str] = frozenset(
    (
        "WOT-2026-016v",
        "WOT-2026-020p",
        "WOT-2026-021j",
        "WOT-2026-022j",
        "WOT-2026-024p",
        "WOT-2026-024r",
        "WOT-2026-025t",
        "WOT-2026-025w",
        "WOT-2026-026a",
        "WOT-2026-026o",
        "WOT-2026-026x",
        "WOT-2026-027j",
        "WOT-2026-027m",
        "WOT-2026-027s",
        "WOT-2026-034a",
        "WOT-2026-036b",
        "WOT-2026-036f",
        "WOT-2026-037a",
        "WOT-2026-038a",
        "WOT-2026-038f",
        "WOT-2026-038i",
        "WOT-2026-039e",
        "WOT-2026-039f",
        "WOT-2026-040g",
        "WOT-2026-040i",
        "WOT-2026-040p",
        "WOT-2026-041n",
        "WOT-2026-041t",
        "WOT-2026-041u",
        "WOT-2026-042e",
        "WOT-2026-042h",
        "WOT-2026-042k",
        "WOT-2026-042r",
        "WOT-2026-043c",
        "WOT-2026-043m",
        "WOT-2026-043p",
        "WOT-2026-043s",
        "WOT-2026-043y",
        "WOT-2026-044b",
        "WOT-2026-044c",
        "WOT-2026-044e",
        "WOT-2026-044h",
        "WOT-2026-044i",
        "WOT-2026-044l",
        "WOT-2026-044u",
        "WOT-2026-045c",
        "WOT-2026-045d",
        "WOT-2026-045e",
        "WOT-2026-045f",
        "WOT-2026-046b",
        "WOT-2026-046e",
        "WOT-2026-046j",
        "WOT-2026-047a",
        "WOT-2026-047i",
        "WOT-2026-047p",
        "WOT-2026-048e",
        "WOT-2026-048j",
        "WOT-2026-048m",
        "WOT-2026-048t",
        "WOT-2026-048v",
        "WOT-2026-049b",
        "WOT-2026-049h",
        "WOT-2026-051e",
        "WOT-2026-053d",
        "WOT-2026-054f",
        "WOT-2026-054h",
        "WOT-2026-054l",
        "WOT-2026-054m",
        "WOT-2026-054o",
        "WOT-2026-055a",
        "WOT-2026-055e",
        "WOT-2026-055h",
        "WOT-2026-055m",
        "WOT-2026-055o",
        "WOT-2026-055t",
        "WOT-2026-055v",
        "WOT-2026-055y",
        "WOT-2026-056e",
        "WOT-2026-058a",
        "WOT-2026-058b",
        "WOT-2026-058c",
        "WOT-2026-058f",
        "WOT-2026-058h",
        "WOT-2026-058n",
        "WOT-2026-058o",
        "WOT-2026-058u",
        "WOT-2026-059h",
        "WOT-2026-059n",
        "WOT-2026-STATE-RECON-A",
    )
)


def _strip_ticket_ids(text: str) -> str:
    """Blank out ticket-id spans, preserving offsets so slices stay aligned."""
    return _TICKET_ID_SPAN_RE.sub(lambda m: " " * (m.end() - m.start()), text)


def _sentence_around(text: str, start: int, end: int) -> str:
    """Return the sentence window containing [start, end)."""
    left = 0
    right = len(text)
    for m in _SENTENCE_SPLIT_RE.finditer(text):
        if m.end() <= start:
            left = m.end()
        elif m.start() >= end:
            right = m.start()
            break
    return text[left:right]


def _row_ticket_id(row: str) -> str:
    """Ticket id of a Vista rapida row, read from its CELL (never the prose)."""
    cells = row.strip().strip("|").split("|")
    if len(cells) > 1:
        candidate = cells[1].strip()
        if _TICKET_ID_SPAN_RE.fullmatch(candidate):
            return candidate
    return "<unknown>"


def find_violations(rows: list[str]) -> list[str]:
    """Return one diagnostic per row carrying an UNANCHORED figure+noun."""
    violations: list[str] = []
    for row in rows:
        ticket = _row_ticket_id(row)
        if ticket in _DOD_METRIC_LEGACY_BASELINE:
            continue
        scan = _strip_ticket_ids(row)
        for match in _FIGURE_RE.finditer(scan):
            sentence = _sentence_around(scan, match.start(), match.end())
            if _ANCHOR_RE.search(sentence):
                continue
            violations.append(
                f"{ticket}: figure {match.group(0).strip()!r} has no temporal "
                f"anchor (MEDIDO <fecha> | snapshot <sha7>) in its sentence -- "
                f"a number without a dated snapshot is a criterion that expires. "
                f"Sentence: {sentence.strip()[:160]!r}"
            )
            break
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root")
    parser.add_argument("--workspace-root")
    parser.add_argument("--backlog", help="explicit backlog.md path (tests/fixtures)")
    args = parser.parse_args(argv)

    if args.backlog:
        backlog = Path(args.backlog)
    else:
        dest_root, err = resolve_destino_root(args.project_root or args.workspace_root)
        if dest_root is None:
            print(
                f"[dod-metric] ERROR: backlog root unresolved ({err})", file=sys.stderr
            )
            return EXIT_SELF_FAIL
        backlog = dest_root / ".agent" / "collaboration" / "backlog.md"

    try:
        content = backlog.read_text(encoding="utf-8-sig")
    except OSError as exc:
        print(
            f"[dod-metric] ERROR: cannot read backlog {backlog}: {exc}", file=sys.stderr
        )
        return EXIT_SELF_FAIL

    rows, err = _extract_active_table(content)
    if err is not None:
        print(f"[dod-metric] ERROR: cannot parse live table: {err}", file=sys.stderr)
        return EXIT_SELF_FAIL

    violations = find_violations(rows)
    print(f"[dod-metric] live_rows={len(rows)} violations={len(violations)}")
    for v in violations:
        print(f"[dod-metric]   VIOLATION: {v}")
    return EXIT_VIOLATIONS if violations else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
