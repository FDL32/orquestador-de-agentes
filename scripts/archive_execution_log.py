from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path


SECTION_RE = re.compile(r"(?m)^###\s+WP-\d{4}-\d{3}\b.*$")


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
    archived = archive_execution_log(
        args.execution_log, keep_sections=args.keep, dry_run=args.dry_run
    )
    if args.dry_run:
        print(f"DRY RUN: would archive {archived} section(s)")
    else:
        print(f"Archived {archived} section(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
