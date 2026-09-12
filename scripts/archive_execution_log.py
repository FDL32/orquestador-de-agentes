from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path


# Bootstrap: motor root on sys.path so bus.ticket_id is importable.
_MOTOR_ROOT_BOOTSTRAP = Path(__file__).resolve().parent.parent
if str(_MOTOR_ROOT_BOOTSTRAP) not in sys.path:
    sys.path.insert(0, str(_MOTOR_ROOT_BOOTSTRAP))

from bus.ticket_id import TICKET_ID_PATTERN  # noqa: E402


# WT-2026-251a: derived from canonical TICKET_ID_PATTERN (accepts WP, WT, 3-letter prefixes).
SECTION_RE = re.compile(r"(?m)^###\s+" + TICKET_ID_PATTERN + r"\b.*$")

# WOT-2026-068d: the DENOMINATOR universe. ANY markdown heading level counts --
# the real logs delimit ticket content with `#`/`##` too, so counting only `###`
# would report present=0 while tickets ARE present. SECTION_RE is NOT widened, so
# nothing starts being archived that was not archived before.
HEADING_RE = re.compile(r"^#{1,6}\s")


def _denominator(text: str) -> tuple[int, int, list[str]]:
    """Return (present, recognized, skipped_heading_lines) for the log text."""
    present = 0
    recognized = 0
    skipped: list[str] = []
    for line in text.splitlines():
        if not HEADING_RE.match(line):
            continue
        present += 1
        if SECTION_RE.match(line):
            recognized += 1
        else:
            skipped.append(line)
    return present, recognized, skipped


def _emit_protocol(
    archived: int, recognized: int, present: int, skipped: list[str], state: str
) -> None:
    """Emit the productor<->consumidor protocol (WOT-2026-068d D1)."""
    print(f"COUNTS archived={archived} recognized={recognized} present={present}")
    print("SKIPPED " + json.dumps(skipped))
    print(f"CONTENT state={state}")


def _find_sections(text: str) -> list[tuple[int, int, str]]:
    matches = list(SECTION_RE.finditer(text))
    sections: list[tuple[int, int, str]] = []
    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        sections.append((start, end, text[start:end].rstrip() + "\n"))
    return sections


def _archive_path(execution_log: Path) -> Path:
    stamp = datetime.now().strftime("%Y-%m")
    return execution_log.parent / "archive" / f"execution_log_{stamp}.md"


def archive_execution_log(
    execution_log: Path, keep_sections: int = 10, dry_run: bool = False
) -> int:
    text = execution_log.read_text(encoding="utf-8")
    sections = _find_sections(text)
    if len(sections) <= keep_sections:
        return 0

    # Split the file:
    #   - header: everything before the first WP section
    #   - to_archive: oldest sections (the ones beyond keep_sections from the tail)
    #   - to_keep: newest keep_sections
    header = text[: sections[0][0]]
    to_archive = [section for _, _, section in sections[:-keep_sections]]
    kept_sections_text = text[sections[-keep_sections][0] :]
    keep_text = (
        header.rstrip() + "\n\n" + kept_sections_text.lstrip()
        if header.strip()
        else kept_sections_text
    )

    archive_file = _archive_path(execution_log)
    existing = archive_file.read_text(encoding="utf-8") if archive_file.exists() else ""
    new_chunks = [chunk for chunk in to_archive if chunk not in existing]

    if dry_run:
        return len(new_chunks)

    archive_dir = execution_log.parent / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    if new_chunks:
        with archive_file.open("a", encoding="utf-8", newline="\n") as fh:
            if existing and not existing.endswith("\n"):
                fh.write("\n")
            for chunk in new_chunks:
                fh.write(chunk)
                if not chunk.endswith("\n"):
                    fh.write("\n")

    execution_log.write_text(keep_text.rstrip() + "\n", encoding="utf-8", newline="\n")
    return len(new_chunks)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Archive old WP sections from execution_log.md"
    )
    parser.add_argument(
        "--execution-log",
        type=Path,
        default=Path(".agent/collaboration/execution_log.md"),
        help="Path to execution_log.md",
    )
    parser.add_argument(
        "--keep",
        type=int,
        default=10,
        help="Number of latest WP sections to keep in the active log",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report how many sections would be archived without writing files",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    try:
        text = args.execution_log.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        # WOT-2026-068d D1: a read failure is NOT an empty universe. Emit the
        # conventional transport protocol and fail closed (exit 1), no writes.
        # The try wraps ONLY the log read: a later error (e.g. an unreadable
        # monthly archive) must NOT be reclassified as `unavailable`.
        print(f"ERROR: cannot read {args.execution_log}: {exc}", file=sys.stderr)
        _emit_protocol(0, 0, 0, [], "unavailable")
        return 1

    present, recognized, skipped = _denominator(text)
    state = "empty" if not text.strip() else "nonempty"

    would_archive = archive_execution_log(
        args.execution_log, keep_sections=args.keep, dry_run=args.dry_run
    )
    if args.dry_run:
        print(f"DRY RUN: would archive {would_archive} section(s)")
    else:
        print(f"Archived {would_archive} section(s)")

    # `archived` in COUNTS is the REAL effect: 0 in --dry-run, independent of the
    # function's return (which stays the forecast). WOT-2026-068d D2.
    archived_effect = 0 if args.dry_run else would_archive
    _emit_protocol(archived_effect, recognized, present, skipped, state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
