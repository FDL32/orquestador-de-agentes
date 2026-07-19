#!/usr/bin/env python3
"""Census of dogfooding NARRATIVE vs traceability ANCHOR on the distributed
surface (WOT-2026-025h).

Policy (DEC-025H-001, human-resolved 2026-07-19): on the surface that TRAVELS to
a foreign destination (MANIFEST.distribute), a ticket citation should reduce to
RULE + ANCHOR -- the ``WOT-2026-XXX`` id kept as a MINIMAL traceable reference so
a reader can find the origin. The PROSE that narrates the dogfooding case/session/
date to that foreign reader is CONTAMINATION (it belongs in CHANGELOG/memory, not
in the contract a foreign project receives).

This script CLASSIFIES, it NEVER prunes (NON-GOAL of 025h). Pruning is applied
later, per surface, by its owner (G-AGENTS-SLIM over AGENTS.md, WOT-2026-036i over
the rest), each with its own 1->9->2 verification over THIS census.

Design contract (CONTRACT_AUDIT 1->9->2, 2026-07-19; Codex refuter
PROCEED_code_gap_closeable): this is a DETERMINISTIC, HIGH-PRECISION,
EXPLICITLY NON-EXHAUSTIVE policy classifier -- NOT a semantic oracle. Natural
language narrative cannot be exhaustively decided by a closed marker set, so:
  - a hit is NARRATIVA only if it matches a CLOSED narrative-marker set AND passes
    the anchor-guards (code-comment / bare-anchor / date-only are NOT narrative);
  - everything else defaults to ANCLA (keep) -- a false-negative (missed narrative)
    is SAFE (nothing is pruned by this tool); a false-positive (flagging a real
    anchor) is the dangerous one, so the guards target it;
  - a soft LOW_CONFIDENCE tier surfaces "ticket id + past-fix verb, no hard marker"
    lines as REVIEW CANDIDATES without asserting they are narrative. They are NOT
    counted as NARRATIVA; they are a hint for the human/036i pass.
The classifier is LINE-SCOPED: a hit is one line, and NARRATIVA requires a
narrative marker on the SAME line as the ticket id. This matches how real
distributed narrative reads (`Caso fundacional (2026-07-15): WOT-2026-020o-B...`
is one line). Narrative that spans lines away from its ticket id is an accepted
FALSE-NEGATIVE (safe: this tool never prunes) surfaced, if it carries a soft
verb, as LOW_CONFIDENCE.

The published counts are a DATED SNAPSHOT of evidence, NEVER a DoD criterion
(rule WOT-2026-024t).

Before:
  - --root points at a git repo whose HEAD has a MANIFEST.distribute.
During:
  - Build the denominator via check_distribution_agnostic.build_denominator
    (MANIFEST.distribute entries -> git ls-files), read each file (bytes +
    errors='replace'; a non-utf8 file is audited degraded, never skipped
    silently), and classify every ticket-citation line.
After:
  - Prints a human summary and, with --json, emits the full machine report
    (read-only: {file,line,ticket_ids,classification,marker,text}). Returns 0 on
    success, 1 on denominator/path error. Never writes to the audited tree.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


# Reuse the SAME denominator the distribution-agnostic guard publishes: one source
# of truth for "what travels" (52 entries -> 143 files today). No second parser.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_distribution_agnostic import build_denominator


# --- Classifier contract ----------------------------------------------------

# Canonical ticket id on the distributed surface (WOT/WP/WT/CTL/EXF + 3-letter).
TICKET_RE = re.compile(r"\b(?:[A-Z]{2,3})-\d{4}-\d{3}[a-z]?\b")

# CLOSED narrative-marker set: prose that NARRATES a dogfooding case/session to a
# foreign reader. Kept deliberately small and high-precision (Codex G1: a closed
# set is not an oracle; prefer misses over false anchors). Extend ONLY with a
# marker observed to introduce narrative, never a generic verb.
NARRATIVE_MARKERS = (
    re.compile(r"\bCaso\s+fundacional\b", re.IGNORECASE),
    re.compile(r"\bCaso\s+historico\b", re.IGNORECASE),
    re.compile(r"\bCasos?:\s"),  # "Caso:" / "Casos:" + incident prose
    re.compile(r"\bEvidencia\s+origen:\s"),  # provenance-narration marker
)

# ANCHOR-GUARDS (win over markers; target the DANGEROUS false-positive):
#   - a code comment `# <TICKET>: ...` is procedencia and STAYS (AGENTS.md's own
#     generador-vs-historia rule; may be asserted by a test, e.g. guard_wiring).
CODE_COMMENT_ANCHOR_RE = re.compile(r"^\s*#\s*(?:[A-Z]{2,3})-\d{4}-\d{3}[a-z]?\s*:")
#   - a bare rule anchor: the ONLY ticket reference on the line is a parenthetical
#     `(WOT-...)` (optionally with an origin date). A DATE ALONE is NOT a narrative
#     marker (Codex G3: else PROJECT.md status/provenance rows become accidental
#     narrative). This guard is implicit: such lines simply match no marker.

# LOW_CONFIDENCE soft signal: a past-fix / provenance verb co-located with a
# ticket id but WITHOUT a hard marker. Surfaced as a REVIEW CANDIDATE, never
# auto-classified NARRATIVA.
SOFT_VERB_RE = re.compile(
    r"\b(?:se\s+corrigio|se\s+corrig[ió]|corrigio en|la\s+causa\s+raiz|"
    r"diagnostico\s+falso|el\s+bug\s+no\s+existia|midio\s+\w+\s+en|"
    r"disparado\s+por|vivieron\s+sin\s+detectar|dio\s+exit\s+0)\b",
    re.IGNORECASE,
)

ANCLA = "ANCLA"
NARRATIVA = "NARRATIVA"
LOW_CONFIDENCE = "LOW_CONFIDENCE"


@dataclass(frozen=True)
class Hit:
    file: str
    line: int
    ticket_ids: tuple[str, ...]
    classification: str
    marker: str  # which marker/guard fired (audit trail)
    text: str


def classify_line(line: str) -> tuple[str, str] | None:
    """Classify ONE line that cites at least one ticket id.

    Returns (classification, marker) or None if the line cites no ticket.
    Precedence: code-comment anchor (guard) -> narrative marker -> soft verb
    (low-confidence) -> default ANCLA.
    """
    if not TICKET_RE.search(line):
        return None
    # Anchor-guard: a `# <TICKET>: ...` code comment is ALWAYS ANCLA, even if the
    # description contains an incident verb (protects test-asserted ids).
    if CODE_COMMENT_ANCHOR_RE.search(line):
        return ANCLA, "code-comment-anchor"
    for rx in NARRATIVE_MARKERS:
        m = rx.search(line)
        if m:
            return NARRATIVA, f"marker:{m.re.pattern[:24]}"
    if SOFT_VERB_RE.search(line):
        return LOW_CONFIDENCE, "soft-verb"
    return ANCLA, "default-bare-anchor"


def scan_file(root: Path, rel: str) -> list[Hit]:
    """Classify every ticket-citing line of one distributed file (degraded read
    on non-utf8, never a silent skip)."""
    p = root / rel
    try:
        text = p.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return []
    hits: list[Hit] = []
    for i, line in enumerate(text.splitlines(), start=1):
        result = classify_line(line)
        if result is None:
            continue
        classification, marker = result
        ids = tuple(sorted(set(TICKET_RE.findall(line))))
        hits.append(
            Hit(
                file=rel,
                line=i,
                ticket_ids=ids,
                classification=classification,
                marker=marker,
                text=line.strip()[:300],
            )
        )
    return hits


def run_census(root: Path) -> tuple[dict, str | None]:
    """Build the full read-only census report. Returns (report, error_or_None)."""
    n_entries, files, err = build_denominator(root)
    if err:
        return {}, err
    all_hits: list[Hit] = []
    inspected = 0
    for rel in files:
        inspected += 1
        all_hits.extend(scan_file(root, rel))
    by_class = {NARRATIVA: 0, ANCLA: 0, LOW_CONFIDENCE: 0}
    for h in all_hits:
        by_class[h.classification] += 1
    files_with_narrative = sorted(
        {h.file for h in all_hits if h.classification == NARRATIVA}
    )
    report = {
        "ticket": "WOT-2026-025h",
        "policy": "DEC-025H-001 (CONSERVAR ANCLA, PODAR NARRATIVA)",
        "classifier": "deterministic, high-precision, NON-EXHAUSTIVE (not an oracle)",
        "denominator": {
            "manifest_entries": n_entries,
            "distributed_files_inspected": inspected,
            "files_skipped": len(files) - inspected,
        },
        "counts": {
            "hit_lines_total": len(all_hits),
            "narrativa": by_class[NARRATIVA],
            "ancla": by_class[ANCLA],
            "low_confidence": by_class[LOW_CONFIDENCE],
        },
        "files_with_narrative": files_with_narrative,
        "note": (
            "Counts are a DATED SNAPSHOT of evidence, NEVER a DoD criterion "
            "(WOT-2026-024t). LOW_CONFIDENCE lines are REVIEW CANDIDATES for the "
            "per-surface pruning pass (G-AGENTS-SLIM / WOT-2026-036i), NOT "
            "classified as narrative. This census NEVER prunes."
        ),
        "hits": [asdict(h) for h in all_hits],
    }
    return report, None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Census of dogfooding NARRATIVE vs ANCHOR on the distributed surface "
            "(WOT-2026-025h). Read-only; classifies, never prunes."
        )
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="Motor repo root (must contain MANIFEST.distribute). Default: cwd.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the full machine report as JSON (read-only).",
    )
    return parser


def _emit_json(report: dict) -> None:
    """Write the report as UTF-8 JSON, robust to any stdout.

    The Windows console default codec (cp1252) chokes on non-latin1 chars like
    U+2194 in the report, so we must NOT rely on a plain ``print``. But we also
    must NOT assume ``sys.stdout.buffer`` exists -- a programmatic caller or
    pytest capture (``io.StringIO``) has no ``.buffer`` (Codex MANAGER_REVIEW,
    2026-07-19). Prefer the byte buffer; fall back to a text write that cannot
    raise UnicodeEncodeError.
    """
    payload = json.dumps(report, ensure_ascii=False, indent=1)
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is not None:
        buffer.write(payload.encode("utf-8"))
        buffer.write(b"\n")
        return
    # No binary buffer (captured/StringIO stdout): write text, and if the
    # underlying encoding can't represent a char, degrade with a replacement
    # rather than crash.
    try:
        sys.stdout.write(payload + "\n")
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        sys.stdout.write(payload.encode(enc, "replace").decode(enc) + "\n")


def run(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    root: Path = args.root
    report, err = run_census(root)
    if err:
        print(f"Error: {err}", file=sys.stderr)
        return 1
    if args.json:
        _emit_json(report)
        return 0
    d = report["denominator"]
    c = report["counts"]
    print(f"[census WOT-2026-025h] {report['policy']}")
    print(f"  classifier: {report['classifier']}")
    print(
        f"  denominator: {d['manifest_entries']} manifest entries -> "
        f"{d['distributed_files_inspected']} files inspected "
        f"({d['files_skipped']} skipped)"
    )
    print(
        f"  hits: {c['hit_lines_total']} lines | NARRATIVA {c['narrativa']} | "
        f"ANCLA {c['ancla']} | LOW_CONFIDENCE {c['low_confidence']}"
    )
    print(f"  files with narrative ({len(report['files_with_narrative'])}):")
    for f in report["files_with_narrative"]:
        print(f"    - {f}")
    print(f"  {report['note']}")
    return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())
