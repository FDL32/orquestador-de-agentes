#!/usr/bin/env python3
"""Memory consolidate V1: dedupe + filter + archive observations.jsonl.

Deterministic, no LLM, no cron. Run manually at session close.
Default dry-run; --apply to write changes.

WP-2026-122: Uses runtime.project_root for dynamic project root resolution.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


# Bootstrap repo_motor before importing sibling packages when executed by
# absolute path with cwd pointing at repo_destino.
_MOTOR_ROOT_BOOTSTRAP = Path(__file__).resolve().parent.parent
if str(_MOTOR_ROOT_BOOTSTRAP) not in sys.path:
    sys.path.insert(0, str(_MOTOR_ROOT_BOOTSTRAP))

from bus.redact import redact_payload  # noqa: E402

# WP-2026-122 / WP-2026-155: Centralized path resolution via runtime.project_root
from runtime.project_root import get_agent_dir  # noqa: E402


AGENT_DIR = get_agent_dir()
MEMORY_DIR = AGENT_DIR / "runtime" / "memory"
ARCHIVE_DIR = MEMORY_DIR / "archive"
OBS = MEMORY_DIR / "observations.jsonl"
MEMORY_MD = MEMORY_DIR / "MEMORY.md"
REPORT = MEMORY_DIR / "CONSOLIDATION_REPORT.md"

NOISE_PREFIXES = ("Tool ",)
MIN_SIGNAL_LEN = 30
DEDUPE_WINDOW_HOURS = 24
MEMORY_MD_LINE_CAP = 80
MEMORY_RULES_MD = MEMORY_DIR / "memory_rules.md"
MEMORY_PROFILE_MD = MEMORY_DIR / "memory_profile.md"
MAX_L2_RULES = 30
MAX_L3_DOMAINS = 8
MAX_L3_OBSERVATIONS_PROFILE = 10


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
    """Generate MEMORY.md content from entries.

    Before: Requires entries list and stats dict.
    During: Groups entries by topic, generates markdown with sections.
    After: Returns markdown string capped at MEMORY_MD_LINE_CAP (80) lines
           with visible truncation marker if exceeded.
    """
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

    content = "\n".join(lines)

    # Apply line cap with truncation marker
    all_lines = content.split("\n")
    if len(all_lines) > MEMORY_MD_LINE_CAP:
        cap_marker_lines = [
            "",
            "---",
            "",
            f"[MEMORY.md truncated at {MEMORY_MD_LINE_CAP} lines. "
            "Full history available in observations.jsonl]",
        ]
        truncate_at = MEMORY_MD_LINE_CAP - len(cap_marker_lines)
        truncated_lines = all_lines[:truncate_at] + cap_marker_lines
        content = "\n".join(truncated_lines)

    return content


def _infer_wing(entry: dict[str, Any]) -> str:
    """Determine wing classification from observation metadata.

    Before: Requires an observation dict.
    During: Checks explicit 'wing' field first. If missing, inspects source,
            topic, and domain for keywords that indicate engine or meta wings.
    After: Returns one of 'engine', 'meta', or 'project' (default).
    """
    explicit_wing = entry.get("wing")
    if explicit_wing and isinstance(explicit_wing, str) and explicit_wing.strip():
        return explicit_wing.strip().lower()

    source = (entry.get("source") or "").lower()
    topic = (entry.get("topic") or "").lower()
    domain = (entry.get("domain") or "").lower()
    combined = f"{source} {topic} {domain}"

    # engine wing: system-level code, tools, architecture
    if any(
        kw in combined
        for kw in [
            "agent_controller",
            "memory_loader",
            "memory_consolidate",
            "install_agent",
            "bus/",
            "script",
            "motor",
            "architecture",
        ]
    ):
        return "engine"

    # meta wing: collaboration, workflow, process
    if any(
        kw in combined
        for kw in [
            "collaborat",
            "workflow",
            "ticket",
            "review",
            "supervisor",
            "process",
            "work_plan",
            "execution_log",
            "turn",
        ]
    ):
        return "meta"

    return "project"


def _extract_rules_from_entries(
    entries: list[dict[str, Any]], max_rules: int = MAX_L2_RULES
) -> list[dict[str, Any]]:
    """Extract rule-like observations grouped by domain.

    Before: Requires a list of consolidated observation dicts.
    During: Filters observations that carry explicit 'domain' or have
            'topic' values resembling patterns/rules. Groups by domain.
            Assigns a 'wing' via _infer_wing() for hierarchical grouping.
    After: Returns a deduplicated, deterministically sorted list of
           rule dicts with 'domain', 'signal', 'rule_id', 'source_ticket', 'wing'.
    """
    seen_signals: set[str] = set()
    rules: list[dict[str, Any]] = []

    for entry in entries:
        signal = (entry.get("signal") or "").strip()
        if not signal or signal in seen_signals:
            continue

        # Only promote entries that carry a rule-like signal (longer than 60 chars
        # and not a pure factual statement). Factual statements are shorter or
        # lack a prescriptive tone.
        if len(signal) < 60:
            continue

        # Score rule-likeness: looks for pattern/rule/avoid/always/never/rule/blocker
        signal_lower = signal.lower()
        rule_keywords = (
            "rule",
            "pattern",
            "avoid",
            "always",
            "never",
            "blocker",
            "when a",
            "if the",
            "must be",
            "should",
        )
        rule_likeness = sum(1 for kw in rule_keywords if kw in signal_lower)

        # Minimal rule-likeness threshold: at least one keyword match or
        # the entry has an explicit domain/anti_pattern_id field.
        has_domain = bool(entry.get("domain") or entry.get("anti_pattern_id"))
        if not has_domain and rule_likeness < 1:
            continue

        seen_signals.add(signal)
        domain = entry.get("domain") or entry.get("topic", "general")
        rules.append(
            {
                "domain": str(domain),
                "signal": signal,
                "source_ticket": entry.get("source_ticket", "unknown"),
                "wing": _infer_wing(entry),
            }
        )
        if len(rules) >= max_rules:
            break

    # Sort deterministically by (domain, signal)
    rules.sort(key=lambda r: (r["domain"], r["signal"]))
    # Assign stable rule IDs
    for i, rule in enumerate(rules, 1):
        rule["rule_id"] = f"R-{i:03d}"
    return rules


def generate_memory_rules_md(entries: list[dict[str, Any]]) -> str:
    """Generate memory_rules.md (L2) from consolidated entries.

    Before: Requires a list of consolidated observation dicts.
    During: Extracts rule-like entries via _extract_rules_from_entries(),
            groups by wing (engine/meta/project) then by domain, and renders
            a parseable markdown document with ``## Wing: <wing>`` and
            ``### Domain: <slug>`` section headers.
    After: Returns a markdown string with deterministic rule IDs and
           a header documenting generation timestamp and stats.
    """
    rules = _extract_rules_from_entries(entries)

    lines = [
        "# Memory Rules (L2)",
        "",
        f"Total rules: {len(rules)}",
        "",
        "Rules derived deterministically from observations.jsonl. "
        "Each rule carries an ID (R-XXX), domain, wing, source ticket, and signal text.",
        "",
    ]

    # Group by wing then domain
    wing_groups: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for rule in rules:
        wing = rule.get("wing", "project")
        domain = rule["domain"]
        if wing not in wing_groups:
            wing_groups[wing] = {}
        if domain not in wing_groups[wing]:
            wing_groups[wing][domain] = []
        wing_groups[wing][domain].append(rule)

    for wing in sorted(wing_groups.keys()):
        lines.append(f"## Wing: {wing}")
        lines.append("")
        domains = wing_groups[wing]
        for domain in sorted(domains.keys()):
            domain_rules = domains[domain]
            lines.append(f"### Domain: {domain}")
            lines.append("")
            for rule in domain_rules:
                lines.append(f"#### {rule['rule_id']}: {rule['signal'][:80].rstrip()}")
                lines.append("")
                lines.append(rule["signal"])
                lines.append("")
                if rule["source_ticket"] != "unknown":
                    lines.append(f"*Source: {rule['source_ticket']}*")
                    lines.append("")
            lines.append("")

    if not rules:
        lines.append(
            "No rules extracted yet. Accumulate more observations to generate rules."
        )
        lines.append("")

    return "\n".join(lines)


def generate_memory_profile_md(entries: list[dict[str, Any]]) -> str:
    """Generate memory_profile.md (L3) from consolidated entries.

    Before: Requires a list of consolidated observation dicts.
    During: Compiles active domains, top patterns, and summary stats
            from the most recent observations.
    After: Returns a brief markdown profile string suitable for bootstrap
           and pre-compact consumption (L3 priority).
    """
    # Count domains from observations
    domain_counts: dict[str, int] = {}
    topic_counts: dict[str, int] = {}
    tickets_seen: set[str] = set()

    for entry in entries:
        domain = entry.get("domain") or entry.get("topic", "general")
        domain_counts[str(domain)] = domain_counts.get(str(domain), 0) + 1
        topic = entry.get("topic", "general")
        topic_counts[str(topic)] = topic_counts.get(str(topic), 0) + 1
        ticket = entry.get("source_ticket", "")
        if ticket:
            tickets_seen.add(ticket)

    # Sort domains by count descending, take top N
    top_domains = sorted(domain_counts.items(), key=lambda x: -x[1])[:MAX_L3_DOMAINS]
    # topic_counts computed but profile prioritizes domain aggregation
    _ = sorted(topic_counts.items(), key=lambda x: -x[1])[:MAX_L3_DOMAINS]

    # Take most recent observations as "active signals"
    sorted_entries = sorted(
        entries,
        key=lambda e: parse_timestamp(e.get("timestamp", "")),
        reverse=True,
    )
    recent_signals = sorted_entries[:MAX_L3_OBSERVATIONS_PROFILE]

    lines = [
        "# Memory Profile (L3)",
        "",
        f"Total observations: {len(entries)}",
        "",
        "High-level profile of project memory for quick context loading. "
        "This is the first memory tier loaded (before L2 rules and L1 raw observations).",
        "",
        "## Active Domains",
        "",
    ]
    for domain, count in top_domains:
        lines.append(f"- {domain}: {count} observations")
    lines.append("")

    if tickets_seen:
        lines.append("## Active Tickets Referenced")
        lines.append("")
        lines.extend(f"- {ticket}" for ticket in sorted(tickets_seen))
        lines.append("")

    lines.append("## Recent Signals")
    lines.append("")
    for entry in recent_signals:
        signal = (entry.get("signal") or "")[:150]
        topic = entry.get("topic", "general")
        source = entry.get("source", "unknown")
        lines.append(f"- [{topic}] {signal} ({source})")
    lines.append("")

    return "\n".join(lines)


def _regenerate_l2_l3(
    recent: list[dict[str, Any]],
    verbose: bool,
) -> None:
    """Regenerate memory_rules.md (L2) and memory_profile.md (L3)."""
    rules_md = generate_memory_rules_md(recent)
    MEMORY_RULES_MD.write_text(rules_md, encoding="utf-8")
    if verbose:
        print(f"Regenerated {MEMORY_RULES_MD}")

    profile_md = generate_memory_profile_md(recent)
    MEMORY_PROFILE_MD.write_text(profile_md, encoding="utf-8")
    if verbose:
        print(f"Regenerated {MEMORY_PROFILE_MD}")


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
        "6. **Generate L2**: memory_rules.md regenerated from rule-like entries",
        "7. **Generate L3**: memory_profile.md regenerated as brief project profile",
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
                "- `memory_rules.md`: Regenerated (L2 rules)",
                "- `memory_profile.md`: Regenerated (L3 profile)",
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


def _redact_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Redact secrets and PII from an observation entry before persistence.

    Before: Requires an observation dict.
    During: Applies redact_payload() recursively to all string values.
            Returns a new dict; the original is not mutated.
    After: Returns redacted copy with secrets replaced by ***REDACTED***.
    """
    return redact_payload(entry)


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
            lines_to_write = [
                json.dumps(_redact_entry(e), ensure_ascii=False) for e in existing
            ]
        else:
            lines_to_write = [
                json.dumps(_redact_entry(e), ensure_ascii=False) for e in archivable
            ]
        archive_file.write_text(
            "\n".join(lines_to_write) + "\n" if lines_to_write else "", encoding="utf-8"
        )
        if verbose:
            print(f"Archived {len(archivable)} entries to {archive_file}")

    new_lines = [json.dumps(_redact_entry(e), ensure_ascii=False) for e in recent]
    OBS.write_text("\n".join(new_lines) + "\n" if new_lines else "", encoding="utf-8")

    if verbose:
        print(f"Rewrote {OBS} with {len(recent)} entries")

    memory_md_content = regen_memory_md(recent, stats)
    MEMORY_MD.write_text(memory_md_content, encoding="utf-8")

    if verbose:
        print(f"Regenerated {MEMORY_MD}")

    _regenerate_l2_l3(recent, verbose)

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
        "--dry-run",
        action="store_true",
        help="Simulate without writing (default behavior)",
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

    dry_run = not args.apply or args.dry_run

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
