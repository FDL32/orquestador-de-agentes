#!/usr/bin/env python3
"""Memory consolidate V1: dedupe + filter + archive observations.jsonl.

Deterministic, no LLM, no cron. Run manually at session close.
Default dry-run; --apply to write changes.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MEMORY_DIR = PROJECT_ROOT / ".agent" / "runtime" / "memory"
ARCHIVE_DIR = MEMORY_DIR / "archive"
OBS = MEMORY_DIR / "observations.jsonl"
MEMORY_MD = MEMORY_DIR / "MEMORY.md"
REPORT = MEMORY_DIR / "CONSOLIDATION_REPORT.md"

NOISE_PREFIXES = ("Tool ",)
MIN_SIGNAL_LEN = 30
DEDUPE_WINDOW_HOURS = 24


def is_noise(signal: str) -> bool:
    """Check if signal should be dropped as noise."""
    signal_stripped = signal.strip()
    if len(signal_stripped) < MIN_SIGNAL_LEN:
        return True
    for prefix in NOISE_PREFIXES:
        if signal_stripped.startswith(prefix) and signal_stripped.endswith("called"):
            return True
    return False


def parse_entries(path: Path) -> list[dict[str, Any]]:
    """Parse JSONL file, skipping malformed lines with warning."""
    entries = []
    if not path.exists():
        return entries
    with open(path, encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                entries.append(entry)
            except json.JSONDecodeError:
                print(f"Warning: Skipping malformed JSON at line {line_num}")
    return entries


def parse_timestamp(ts_str: str) -> datetime:
    """Parse ISO timestamp string to datetime."""
    ts_str = ts_str.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(ts_str)
    except ValueError:
        return datetime.now(timezone.utc)


def dedupe(entries: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Dedupe entries within 24h window. Returns (kept_entries, dropped_count)."""
    if not entries:
        return [], 0

    keyed: dict[tuple[str, str, str], dict[str, Any]] = {}
    dropped = 0

    for entry in entries:
        signal = entry.get("signal", "")
        source = entry.get("source", "unknown")
        topic = entry.get("topic", "general")
        ts_str = entry.get("timestamp", "")
        ts = parse_timestamp(ts_str)

        key = (signal, source, topic)

        if key in keyed:
            existing_ts = parse_timestamp(keyed[key].get("timestamp", ""))
            hours_diff = abs((ts - existing_ts).total_seconds()) / 3600
            if hours_diff <= DEDUPE_WINDOW_HOURS:
                if ts >= existing_ts:
                    keyed[key] = entry
                dropped += 1
            else:
                keyed[f"{key}_{ts_str}"] = entry
        else:
            keyed[key] = entry

    return list(keyed.values()), dropped


def split_by_age(
    entries: list[dict[str, Any]], days: int = 30
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split entries into recent and archivable by age."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    recent = []
    archivable = []

    for entry in entries:
        ts_str = entry.get("timestamp", "")
        ts = parse_timestamp(ts_str)
        if ts < cutoff:
            archivable.append(entry)
        else:
            recent.append(entry)

    return recent, archivable


def group_by_topic(entries: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group entries by topic."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        topic = entry.get("topic", "general")
        if topic not in grouped:
            grouped[topic] = []
        grouped[topic].append(entry)
    return grouped


def regen_memory_md(entries: list[dict[str, Any]], stats: dict[str, int]) -> str:
    """Generate MEMORY.md content from entries."""
    now = datetime.now(timezone.utc).isoformat()
    grouped = group_by_topic(entries)

    lines = [
        "# MEMORY",
        "",
        f"Regenerated: {now}",
        "",
        f"Total observations: {len(entries)}",
        "",
    ]

    for topic in sorted(grouped.keys()):
        topic_entries = grouped[topic]
        topic_name = topic.replace("_", " ").title()
        lines.append(f"- {topic_name} ({len(topic_entries)} observations)")

    lines.append("")

    for topic in sorted(grouped.keys()):
        topic_entries = sorted(
            grouped[topic],
            key=lambda e: parse_timestamp(e.get("timestamp", "")),
            reverse=True,
        )[:10]
        lines.append(f"## {topic}")
        for entry in topic_entries:
            signal = entry.get("signal", "")[:200]
            lines.append(f"- {signal}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Archive Pointers")
    lines.append("")
    if ARCHIVE_DIR.exists():
        archive_files = sorted(ARCHIVE_DIR.glob("observations.*.jsonl"))
        if archive_files:
            lines.append("Historical archives:")
            lines.extend(f"- `{af.name}`" for af in archive_files)
        else:
            lines.append("No archive files yet.")
    else:
        lines.append("Archive directory does not exist yet.")

    lines.append("")
    lines.append(
        f"Stats: kept={stats['kept']}, deduped={stats['deduped']}, dropped={stats['dropped']}, archived={stats['archived']}"
    )

    return "\n".join(lines)


def write_report(stats: dict[str, Any], dry_run: bool = True) -> None:
    """Write CONSOLIDATION_REPORT.md."""
    now = datetime.now(timezone.utc).isoformat()
    mode = "DRY-RUN" if dry_run else "APPLIED"

    report_lines = [
        "# Consolidation Report",
        "",
        f"Timestamp: {now}",
        f"Mode: {mode}",
        "",
        "## Summary",
        "",
        f"- Total entries processed: {stats['total']}",
        f"- Entries kept: {stats['kept']}",
        f"- Entries deduped: {stats['deduped']}",
        f"- Entries dropped (noise): {stats['dropped']}",
        f"- Entries archived (>30d): {stats['archived']}",
        "",
        "## Pipeline Steps",
        "",
        "1. **Read & parse**: Loaded entries from observations.jsonl",
        "2. **Drop noise**: Removed Tool X called patterns and entries <30 chars",
        "3. **Dedupe**: Removed duplicates within 24h window",
        "4. **Archive**: Moved entries older than 30 days to archive/",
        "5. **Regenerate**: MEMORY.md regenerated from consolidated entries",
        "",
    ]

    if dry_run:
        report_lines.append(
            "> This was a DRY-RUN. No files were modified. "
            "Run with --apply to apply changes."
        )
    else:
        report_lines.extend(
            [
                "## Files Modified",
                "",
                f"- `observations.jsonl`: Replaced with {stats['kept']} entries",
                "- `observations.jsonl.bak.*`: Backup created",
                "- `MEMORY.md`: Regenerated",
            ]
        )
        if stats["archived"] > 0:
            report_lines.append(
                f"- `archive/observations.*.jsonl`: {stats['archived']} entries archived"
            )

    report_lines.append("")

    REPORT.write_text("\n".join(report_lines), encoding="utf-8")


def _run_pipeline(
    args: argparse.Namespace,
) -> tuple[list[dict[str, Any]], dict[str, int], int, int]:
    """Run the consolidation pipeline and return (recent, stats, dropped, dedupe_count)."""
    since_days = 30
    if args.since.endswith("d"):
        since_days = int(args.since[:-1])

    if not OBS.exists():
        print(f"Error: {OBS} does not exist")
        return [], {}, 0, 0

    entries = parse_entries(OBS)
    total = len(entries)

    if args.verbose:
        print(f"Loaded {total} entries from {OBS}")

    filtered = [e for e in entries if not is_noise(e.get("signal", ""))]
    dropped = total - len(filtered)

    if args.verbose:
        print(f"After noise filter: {len(filtered)} entries ({dropped} dropped)")

    deduped, dedupe_count = dedupe(filtered)

    if args.verbose:
        print(f"After dedupe: {len(deduped)} entries ({dedupe_count} removed)")

    recent, archivable = split_by_age(deduped, since_days)

    if args.verbose:
        print(f"Recent: {len(recent)}, Archivable: {len(archivable)}")

    stats = {
        "total": total,
        "kept": len(recent),
        "deduped": dedupe_count,
        "dropped": dropped,
        "archived": len(archivable),
    }

    return recent, stats, dropped, dedupe_count


def _apply_consolidation(
    recent: list[dict[str, Any]],
    archivable: list[dict[str, Any]],
    stats: dict[str, int],
    verbose: bool,
) -> None:
    """Apply consolidation: backup, archive, rewrite files."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_path = MEMORY_DIR / f"observations.jsonl.bak.{timestamp}"
    shutil.copy2(OBS, backup_path)

    if verbose:
        print(f"Backup created: {backup_path}")

    if archivable:
        now = datetime.now(timezone.utc)
        archive_file = ARCHIVE_DIR / f"observations.{now.strftime('%Y-%m')}.jsonl"
        if archive_file.exists():
            existing = parse_entries(archive_file)
            existing.extend(archivable)
            lines_to_write = [json.dumps(e, ensure_ascii=False) for e in existing]
        else:
            lines_to_write = [json.dumps(e, ensure_ascii=False) for e in archivable]
        archive_file.write_text(
            "\n".join(lines_to_write) + "\n" if lines_to_write else "", encoding="utf-8"
        )
        if verbose:
            print(f"Archived {len(archivable)} entries to {archive_file}")

    new_lines = [json.dumps(e, ensure_ascii=False) for e in recent]
    OBS.write_text("\n".join(new_lines) + "\n" if new_lines else "", encoding="utf-8")

    if verbose:
        print(f"Rewrote {OBS} with {len(recent)} entries")

    memory_md_content = regen_memory_md(recent, stats)
    MEMORY_MD.write_text(memory_md_content, encoding="utf-8")

    if verbose:
        print(f"Regenerated {MEMORY_MD}")

    print(
        f"\n[APPLIED] Kept {len(recent)} entries, dropped {stats['dropped']}, deduped {stats['deduped']}, archived {stats['archived']}"
    )
    print(f"Backup: {backup_path}")


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Consolidate observations.jsonl: dedupe + filter + archive"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes (default: dry-run)",
    )
    parser.add_argument(
        "--since",
        default="30d",
        help="Archive entries older than N days (default: 30d)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed output",
    )
    args = parser.parse_args()

    dry_run = not args.apply

    recent, stats, dropped, dedupe_count = _run_pipeline(args)

    if not stats:
        return

    write_report(stats, dry_run=dry_run)

    if args.verbose:
        print(f"Report written to {REPORT}")

    if dry_run:
        print(
            f"\n[DRY-RUN] Would keep {len(recent)} entries, drop {dropped}, dedupe {dedupe_count}, archive {stats['archived']}"
        )
        print("Run with --apply to apply changes.")
        return

    _, archivable = split_by_age(
        [e for e in parse_entries(OBS) if not is_noise(e.get("signal", ""))],
        30 if args.since.endswith("d") else int(args.since[:-1]),
    )
    _apply_consolidation(recent, archivable, stats, args.verbose)


if __name__ == "__main__":
    main()
