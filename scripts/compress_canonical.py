#!/usr/bin/env python3
"""
compress_canonical.py - Caveman-style canonical doc compression helper.

Inspired by JuliusBrussee/caveman (MIT), this stdlib-only helper reduces
noise in canonical markdown files without touching technical content.

Features:
- --dry-run: preview changes without writing
- --backup: create .original.md backup before overwriting
- --restore: restore from .original.md backup
- Preservation of code fences, inline code, URLs, paths, commands, frontmatter
- Idempotent: compress(compress(x)) == compress(x)

Usage:
    python scripts/compress_canonical.py [--dry-run] [--backup] <file>...
    python scripts/compress_canonical.py --restore <file>.original.md
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


# Patterns that MUST be preserved (not compressed)
PRESERVE_PATTERNS = [
    # Code fences (``` ... ```)
    (r"```[\s\S]*?```", "code_fence"),
    # Inline code (`...`)
    (r"`[^`]+`", "inline_code"),
    # URLs (http://, https://, file://)
    (r'https?://[^\s<>"\')\]]+', "url"),
    # File paths (Windows and Unix style)
    (r'[A-Za-z]:\\[^\s"\'\)]+|(?<![A-Za-z])[./][^\s"\'\)]+', "path"),
    # Commands in backticks or code blocks (already covered)
    # Frontmatter (--- ... ---)
    (r"^---\n[\s\S]*?\n---", "frontmatter"),
    # Headers (#, ##, ###, etc.)
    (r"^#{1,6}\s+.+$", "header", re.MULTILINE),
    # Table rows with pipes
    (r"^\|.*\|$", "table_row", re.MULTILINE),
]


def _mark_preserved_segments(text: str) -> tuple[str, list[tuple[str, str]]]:
    """
    Replace preserved segments with placeholders and return the list of preserved content.

    Before: Scans the text for patterns that must not be modified (code fences,
    URLs, paths, headers, etc.) and replaces them with unique placeholders.
    During: Iterates through preserve patterns in order of priority (longest/most specific first).
    After: Returns the marked-up text and a list of (placeholder, original) tuples for restoration.
    """
    preserved = []
    marked_text = text

    for i, pattern_info in enumerate(PRESERVE_PATTERNS):
        if len(pattern_info) == 3:
            pattern, name, flags = pattern_info
        else:
            pattern, name = pattern_info
            flags = 0

        matches = list(re.finditer(pattern, marked_text, flags))
        # Process in reverse to maintain positions
        for match in reversed(matches):
            placeholder = f"__PRESERVE_{name}_{i}_{match.start()}__"
            preserved.append((placeholder, match.group(0)))
            marked_text = (
                marked_text[: match.start()] + placeholder + marked_text[match.end() :]
            )

    return marked_text, preserved


def _restore_preserved_segments(text: str, preserved: list[tuple[str, str]]) -> str:
    """
    Restore preserved segments from placeholders.

    Before: Requires a marked-up text and a list of (placeholder, original) tuples.
    During: Replaces each placeholder with its original content.
    After: Returns the fully restored text with all technical content intact.
    """
    restored = text
    for placeholder, original in preserved:
        restored = restored.replace(placeholder, original)
    return restored


def _compress_whitespace(text: str) -> str:
    """
    Compress excessive whitespace while preserving structure.

    Before: Takes marked-up text (with preserved segments replaced by placeholders).
    During:
      - Collapses multiple consecutive blank lines into max 2
      - Trims trailing whitespace from lines
      - Normalizes line endings to \n
    After: Returns compressed text with cleaner whitespace.
    """
    # Normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Trim trailing whitespace from each line
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines)

    # Collapse multiple blank lines (more than 2 consecutive empty lines -> 2)
    text = re.sub(r"\n{4,}", "\n\n\n", text)

    return text


def _compress_redundant_phrases(text: str) -> str:
    """
    Compress redundant filler phrases while preserving technical content.

    Before: Takes marked-up text with placeholders for preserved segments.
    During: Replaces common filler phrases with shorter equivalents.
    After: Returns text with reduced verbal noise.

    Note: This is conservative - only removes clearly redundant phrases.
    """
    # Conservative phrase compression (only safe, non-technical replacements)
    replacements = [
        # Redundant intensifiers
        (r"\bvery\s+important\b", "critical"),
        (r"\bvery\s+useful\b", "useful"),
        # Wordy phrases
        (r"\bin\s+order\s+to\b", "to"),
        (r"\bdue\s+to\s+the\s+fact\s+that\b", "because"),
        (r"\bin\s+the\s+event\s+that\b", "if"),
        (r"\bfor\s+the\s+purpose\s+of\b", "for"),
        # Filler words (contextual, conservative)
        (r"\bbasically\b", ""),
        (r"\bsimply\b", ""),
        (r"\bjust\b", ""),
        (r"\bactually\b", ""),
        (r"\bliterally\b", ""),
    ]

    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

    # Clean up multiple spaces resulting from removals
    text = re.sub(r"  +", " ", text)

    # Clean up space before punctuation
    text = re.sub(r" +([.,;:!?])", r"\1", text)

    return text


def compress_markdown(text: str) -> str:
    """
    Compress markdown text while preserving technical content.

    Before: Takes raw markdown text that may contain verbose filler and excessive whitespace.
    During:
      1. Marks all technical segments (code, URLs, paths, headers, tables) with placeholders
      2. Applies whitespace compression
      3. Applies phrase compression
      4. Restores all technical segments from placeholders
    After: Returns compressed markdown with all technical content intact.

    Idempotency: compress_markdown(compress_markdown(x)) == compress_markdown(x)
    """
    # Step 1: Mark preserved segments
    marked_text, preserved = _mark_preserved_segments(text)

    # Step 2: Compress whitespace
    compressed = _compress_whitespace(marked_text)

    # Step 3: Compress redundant phrases
    compressed = _compress_redundant_phrases(compressed)

    # Step 4: Restore preserved segments
    result = _restore_preserved_segments(compressed, preserved)

    return result


def create_backup(file_path: Path) -> Path:
    """
    Create a backup of the file with .original.md extension.

    Before: Requires an existing file at file_path.
    During: Copies the file content to file_path.original.md.
    After: Returns the backup path. Raises FileNotFoundError if source doesn't exist.
    """
    backup_path = file_path.with_name(f"{file_path.stem}.original.md")
    backup_path.write_text(file_path.read_text(encoding="utf-8"), encoding="utf-8")
    return backup_path


def restore_from_backup(backup_path: Path) -> Path:
    """
    Restore a file from its .original.md backup.

    Before: Requires an existing backup file at backup_path (must end with .original.md).
    During: Copies the backup content back to the original file path.
    After: Returns the restored file path. Raises ValueError if not a valid backup path.
    """
    if not backup_path.name.endswith(".original.md"):
        raise ValueError(f"Not a valid backup path: {backup_path}")

    # Derive original path: file.original.md -> file.md
    original_name = backup_path.name.replace(".original.md", ".md")
    original_path = backup_path.with_name(original_name)

    original_path.write_text(backup_path.read_text(encoding="utf-8"), encoding="utf-8")
    return original_path


def process_file(
    file_path: Path, dry_run: bool = False, backup: bool = False
) -> tuple[bool, str, int]:
    """
    Process a single markdown file.

    Before: Requires an existing .md file. Optional flags for dry_run and backup.
    During:
      - Reads the file content
      - Applies compression
      - If dry_run: only reports changes
      - If backup: creates .original.md before writing
      - If not dry_run: writes compressed content
    After: Returns (success, message, change_count).
    """
    if not file_path.exists():
        return False, f"File not found: {file_path}", 0

    if file_path.suffix != ".md":
        return False, f"Not a markdown file: {file_path}", 0

    original_content = file_path.read_text(encoding="utf-8")
    compressed_content = compress_markdown(original_content)

    # Count changes
    if original_content == compressed_content:
        return True, f"No changes needed: {file_path}", 0

    change_count = len(original_content) - len(compressed_content)

    if dry_run:
        return (
            True,
            f"Would compress {file_path} ({change_count} chars saved)",
            change_count,
        )

    # Create backup if requested
    if backup:
        backup_path = create_backup(file_path)
        message = f"Created backup: {backup_path}"

    # Write compressed content
    file_path.write_text(compressed_content, encoding="utf-8")

    if backup:
        message += f" | Compressed: {file_path} ({change_count} chars saved)"
    else:
        message = f"Compressed: {file_path} ({change_count} chars saved)"

    return True, message, change_count


def main() -> int:
    """
    CLI entry point.

    Before: Parses command-line arguments for files, dry-run, backup, and restore modes.
    During:
      - In restore mode: restores files from .original.md backups
      - In normal mode: processes each file with compression
    After: Returns exit code (0 for success, 1 for errors).
    """
    parser = argparse.ArgumentParser(
        description="Caveman-style canonical doc compression helper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Preview changes without modifying files
  python compress_canonical.py --dry-run file.md

  # Compress with backup
  python compress_canonical.py --backup file.md

  # Restore from backup
  python compress_canonical.py --restore file.original.md
        """,
    )

    parser.add_argument("files", nargs="*", type=Path, help="Markdown files to process")

    parser.add_argument(
        "--dry-run", action="store_true", help="Preview changes without modifying files"
    )

    parser.add_argument(
        "--backup",
        action="store_true",
        help="Create .original.md backup before overwriting",
    )

    parser.add_argument(
        "--restore", action="store_true", help="Restore files from .original.md backups"
    )

    args = parser.parse_args()

    if not args.files:
        parser.print_help()
        return 1

    exit_code = 0
    total_changes = 0

    for file_path in args.files:
        if args.restore:
            try:
                restored_path = restore_from_backup(file_path)
                print(f"Restored: {restored_path} from {file_path}")
                total_changes += 1
            except Exception as e:
                print(f"Error restoring {file_path}: {e}", file=sys.stderr)
                exit_code = 1
        else:
            try:
                success, message, change_count = process_file(
                    file_path, dry_run=args.dry_run, backup=args.backup
                )
                print(message)
                if not success:
                    exit_code = 1
                total_changes += change_count
            except Exception as e:
                print(f"Error processing {file_path}: {e}", file=sys.stderr)
                exit_code = 1

    if total_changes > 0 and not args.dry_run and not args.restore:
        print(f"\nTotal: {total_changes} chars saved across {len(args.files)} files")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
