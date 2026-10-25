#!/usr/bin/env python3
"""Curate memory: export, apply, and protect entries from a JSONL memory file.

Subcommands:
  export-bundle  Export a JSONL source to an indexed JSON bundle.
  apply          Apply a curation proposal and objections to produce a curated copy.
  --help         Describe the subcommands and flags.

Exit codes:
  0  Success
  2  Argument validation error (missing file, malformed JSON, etc.)
  1  Unhandled exception
"""

import argparse
import json
import re
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Protected patterns (is_protected)
# ---------------------------------------------------------------------------

# (i) "exit_code" or "exit code" (case-insensitive via re.IGNORECASE)
_RE_EXIT_CODE = re.compile(r"exit_code|exit\s+code", re.IGNORECASE)

# (ii) Hex token 7-40 chars as a whole word (candidate SHA)
_RE_HEX_SHA = re.compile(r"\b[0-9a-fA-F]{7,40}\b")

# (iii) Test count: a number followed by tests/test/passed/failed (case-insensitive)
_RE_TEST_COUNT = re.compile(r"\d+\s+(?:tests|test|passed|failed)\b", re.IGNORECASE)

# (iv) File path: at least one path separator followed by a name with extension
_RE_FILE_PATH = re.compile(r"[\\/][^\\/]+(?:\.[^\\/]+)+")


def is_protected(text: str) -> bool:
    """Return True if *text* matches ANY protected pattern.

    Before: *text* is a plain string from a JSONL observation.
    After: evaluated against four regex patterns:
      1. ``exit_code`` / ``exit code`` (case-insensitive)
      2. Hex token 7-40 chars as whole word (SHA candidate)
      3. Test count (number + tests/test/passed/failed)
      4. File path (separator + name with extension)
    """
    for pat in (_RE_EXIT_CODE, _RE_HEX_SHA, _RE_TEST_COUNT, _RE_FILE_PATH):
        if pat.search(text):
            return True
    return False


# ---------------------------------------------------------------------------
# JSONL parsing helpers
# ---------------------------------------------------------------------------


def read_jsonl_entries(
    source: Path, text_field: str = "signal"
) -> list[dict[str, Any]]:
    """Read *source* line by line, yielding dicts with index, text, timestamp.

    Unparseable lines are silently skipped (a warning is printed to stderr
    with the offending line number).  The returned list is 0-indexed in
    file-order.
    """
    entries: list[dict[str, Any]] = []
    with source.open("r", encoding="utf-8", newline="") as fh:
        for lineno, raw_line in enumerate(fh, start=1):
            stripped = raw_line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError:
                print(
                    f"Warning: skipping unparseable line {lineno}",
                    file=sys.stderr,
                )
                continue
            entries.append(
                {
                    "index": len(entries),
                    "text": obj.get(text_field, ""),
                    "timestamp": obj.get("timestamp", None),
                }
            )
    return entries


def read_raw_lines(source: Path) -> list[str]:
    """Read ALL raw lines (including blank / unparseable) preserving line endings."""
    lines: list[str] = []
    with source.open("r", encoding="utf-8", newline="") as fh:
        lines = fh.readlines()
    return lines


def _cmd_export_bundle(args: argparse.Namespace) -> int:
    source = Path(args.source).resolve()
    if not source.is_file():
        print(f"Error: source file not found: {source}", file=sys.stderr)
        return 2

    out = Path(args.out).resolve()
    if out == source:
        print(
            "Error: --out resolves to the same path as --source; "
            "refusing to overwrite the source file.",
            file=sys.stderr,
        )
        return 2

    entries = read_jsonl_entries(source, args.text_field)

    bundle: dict[str, Any] = {"entries": entries}
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        json.dump(bundle, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    print(f"Exported {len(entries)} entries to {out}", file=sys.stderr)
    return 0


def _load_json_file(path: Path, label: str) -> Any:
    if not path.is_file():
        print(f"Error: {label} file not found: {path}", file=sys.stderr)
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        print(
            f"Error: malformed JSON in {label} file {path}: {exc}",
            file=sys.stderr,
        )
        return None


def _check_objection(cidx: int, objected_indices: set[int]) -> bool:
    """Return True if *cidx* is objected."""
    return cidx in objected_indices


def _check_last_n(cidx: int, num_entries: int, last_n: int) -> bool:
    """Return True if *cidx* falls inside the last-n window."""
    return cidx >= num_entries - last_n


def _check_protected(entries: list[dict[str, Any]], cidx: int) -> bool:
    """Return True if the entry at *cidx* matches a protected pattern."""
    if 0 <= cidx < len(entries):
        return is_protected(entries[cidx]["text"])
    return False


def _check_literal_citation(
    entries: list[dict[str, Any]], cidx: int, citation_idx: int
) -> bool:
    """Return True if entry[cidx] text is a literal sub-string of entry[citation_idx]."""
    if 0 <= cidx < len(entries) and 0 <= citation_idx < len(entries):
        entry_text = entries[cidx]["text"]
        citation_text = entries[citation_idx]["text"]
        norm_i = entry_text.lower().strip()
        norm_cit = citation_text.lower().strip()
        if norm_i and norm_i in norm_cit:
            return True
    return False


def _check_source_unchanged(
    source_path: Path, sha_before: str, discarded_indices: list[dict[str, Any]]
) -> bool:
    """Return True if source file is unchanged after curation."""
    if not discarded_indices:
        return True
    sha_after = sha256(source_path.read_bytes()).hexdigest()
    return sha_before == sha_after


def _validate_apply_args(source: Path, proposal: Any, objections_data: Any) -> bool:
    """Validate apply arguments. Return True if valid."""
    if not source.is_file():
        print(f"Error: source file not found: {source}", file=sys.stderr)
        return False
    if proposal is None:
        return False
    if not isinstance(proposal, dict) or "candidates" not in proposal:
        print(
            "Error: --proposal must contain a 'candidates' key",
            file=sys.stderr,
        )
        return False
    if objections_data is None:
        return False
    if not isinstance(objections_data, dict) or "objections" not in objections_data:
        print(
            "Error: --objections must contain an 'objections' key",
            file=sys.stderr,
        )
        return False
    return True


def _classify_candidates(
    proposal: dict[str, Any],
    objected_indices: set[int],
    entries: list[dict[str, Any]],
    last_n: int,
    num_entries: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Classify candidates as discard or survive.

    Returns (discard_info, survivors_with_reason).
    """
    discard_info: list[dict[str, Any]] = []
    survivors_with_reason: list[dict[str, Any]] = []

    for candidate in proposal["candidates"]:
        cidx = candidate.get("index")
        if not isinstance(cidx, int):
            continue
        citation_idx = candidate.get("citation_index")
        reason = candidate.get("reason", "")

        if _check_objection(cidx, objected_indices):
            survivors_with_reason.append(
                {
                    "index": cidx,
                    "citation_index": citation_idx,
                    "reason": reason,
                    "survived": "objetado",
                }
            )
            continue

        if _check_last_n(cidx, num_entries, last_n):
            survivors_with_reason.append(
                {
                    "index": cidx,
                    "citation_index": citation_idx,
                    "reason": reason,
                    "survived": "dentro de last-n",
                }
            )
            continue

        if _check_protected(entries, cidx):
            survivors_with_reason.append(
                {
                    "index": cidx,
                    "citation_index": citation_idx,
                    "reason": reason,
                    "survived": "protegido",
                }
            )
            continue

        citation_valid = _check_literal_citation(entries, cidx, citation_idx)
        if citation_valid:
            discard_info.append(
                {
                    "index": cidx,
                    "citation_index": citation_idx,
                    "reason": reason,
                }
            )
        else:
            survivors_with_reason.append(
                {
                    "index": cidx,
                    "citation_index": citation_idx,
                    "reason": reason,
                    "survived": "sin cita literal valida",
                }
            )

    return discard_info, survivors_with_reason


def _build_output_lines(source: Path, discard_set: set[int]) -> list[str]:
    """Build output lines from source, skipping discarded indices."""
    raw_lines = read_raw_lines(source)
    output_lines: list[str] = []
    entry_counter = 0
    for raw in raw_lines:
        stripped = raw.strip()
        if not stripped:
            output_lines.append(raw)
            continue
        try:
            json.loads(stripped)
        except json.JSONDecodeError:
            output_lines.append(raw)
            continue
        if entry_counter in discard_set:
            entry_counter += 1
            continue
        output_lines.append(raw)
        entry_counter += 1
    return output_lines


def _cmd_apply(args: argparse.Namespace) -> int:
    source = Path(args.source).resolve()
    output = Path(args.output).resolve()
    report = Path(args.report).resolve()

    if _check_self_write(source, output, report):
        return 2

    proposal = _load_json_file(Path(args.proposal), "--proposal")
    objections_data = _load_json_file(Path(args.objections), "--objections")

    if not _validate_apply_args(source, proposal, objections_data):
        return 2

    sha_before = sha256(source.read_bytes()).hexdigest()

    entries = read_jsonl_entries(source, args.text_field)
    num_entries = len(entries)
    last_n = args.last_n

    objected_indices = _build_objection_set(objections_data)
    discard_info, survivors_with_reason = _classify_candidates(
        proposal, objected_indices, entries, last_n, num_entries
    )

    discard_set = {d["index"] for d in discard_info}
    output_lines = _build_output_lines(source, discard_set)

    num_discarded = len(discard_info)
    num_after = num_entries - num_discarded

    _write_output(output_lines, args.output)
    _write_report_data(
        report, num_entries, num_after, discard_info, survivors_with_reason
    )
    _check_source_unchanged(source, sha_before, discard_info)

    print(
        f"Curation applied: {num_entries} -> {num_after} entries "
        f"({num_discarded} discarded)",
        file=sys.stderr,
    )
    return 0


def _check_self_write(source: Path, output: Path, report: Path) -> bool:
    """Check for self-write collisions. Return True if collision found."""
    if output == source:
        print(
            "Error: --output resolves to the same path as --source; "
            "refusing to overwrite the source file.",
            file=sys.stderr,
        )
        return True
    if report == source:
        print(
            "Error: --report resolves to the same path as --source; "
            "refusing to overwrite the source file.",
            file=sys.stderr,
        )
        return True
    if output == report:
        print(
            "Error: --output resolves to the same path as --report; "
            "refusing to write output and report to the same file.",
            file=sys.stderr,
        )
        return True
    return False


def _build_objection_set(objections_data: dict[str, Any]) -> set[int]:
    """Build set of objected indices from objections data."""
    objected_indices: set[int] = set()
    for ob in objections_data["objections"]:
        idx = ob.get("index")
        if isinstance(idx, int):
            objected_indices.add(idx)
    return objected_indices


def _write_output(output_lines: list[str], output_arg: str) -> None:
    """Write output lines to the output file."""
    output_path = Path(output_arg)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as fh:
        fh.writelines(output_lines)


def _write_report_data(
    report_arg: str,
    before: int,
    after: int,
    discard_info: list[dict[str, Any]],
    survivors: list[dict[str, Any]],
) -> None:
    """Write the curation report to disk."""
    report_path = Path(report_arg)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    _write_report(report_path, before, after, discard_info, survivors)


def _write_report(
    path: Path,
    before: int,
    after: int,
    discard_info: list[dict[str, Any]],
    survivors: list[dict[str, Any]],
) -> None:
    diff = before - after
    lines: list[str] = []
    lines.append("# Curacion de memoria -- Informe\n")
    lines.append("## Resumen\n")
    lines.append(f"- Entradas ANTES: {before}\n")
    lines.append(f"- Entradas DESPUES: {after}\n")
    lines.append(f"- Diferencia: {diff}\n")
    lines.append("")

    lines.append("## Indices descartados\n")
    lines.append(
        "| Index | Citation index | Reason |\n|-------|---------------|--------|\n"
    )
    lines.extend(
        f"| {d['index']} | {d.get('citation_index', '')} "
        f"| {d.get('reason', '')[:80]} |\n"
        for d in discard_info
    )
    lines.append("")

    lines.append("## Candidatos que sobrevivieron\n")
    lines.append(
        "| Index | Citation index | Razon del candidato | Motivo supervivencia |\n"
        "|-------|---------------|---------------------|----------------------|\n"
    )
    lines.extend(
        f"| {s['index']} | {s.get('citation_index', '')} "
        f"| {s.get('reason', '')[:60]} | {s['survived']} |\n"
        for s in survivors
    )
    lines.append("")

    with path.open("w", encoding="utf-8") as fh:
        fh.writelines(lines)


def main() -> None:
    try:
        parser = argparse.ArgumentParser(
            prog="curate_memory",
            description="Curate memory entries from a JSONL source file.",
        )
        subparsers = parser.add_subparsers(dest="command")

        # -- export-bundle --
        ep = subparsers.add_parser(
            "export-bundle",
            help="Export a JSONL source to an indexed JSON bundle.",
        )
        ep.add_argument("--source", required=True, help="Path to JSONL source file.")
        ep.add_argument(
            "--text-field",
            default="signal",
            help="Field to extract as text (default: signal).",
        )
        ep.add_argument("--out", required=True, help="Output JSON bundle path.")
        ep.set_defaults(func=_cmd_export_bundle)

        # -- apply --
        ap = subparsers.add_parser(
            "apply",
            help="Apply curation proposal and objections to produce a curated copy.",
        )
        ap.add_argument("--source", required=True, help="Path to JSONL source file.")
        ap.add_argument(
            "--proposal",
            required=True,
            help="Path to candidates JSON file.",
        )
        ap.add_argument(
            "--objections",
            required=True,
            help="Path to objections JSON file.",
        )
        ap.add_argument("--output", required=True, help="Output curated JSONL path.")
        ap.add_argument("--report", required=True, help="Output markdown report path.")
        ap.add_argument(
            "--last-n",
            type=int,
            default=20,
            help="Protect the last N entries (default: 20).",
        )
        ap.add_argument(
            "--text-field",
            default="signal",
            help="Field to extract as text (default: signal).",
        )
        ap.set_defaults(func=_cmd_apply)

        args = parser.parse_args()
        if args.command is None:
            parser.print_help()
            sys.exit(0)
        rc = args.func(args)
        sys.exit(rc if rc else 0)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
