#!/usr/bin/env python3
"""Session Close Observations: Generate curated observations at session end.

This script generates candidate observations from a completed work cycle,
filters them through curation rules, and appends valid ones to
observations.jsonl for later consolidation by memory_consolidate.py.

WP-2026-132: Session-close observations for self-improving memory.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# WP-2026-122: Deferred path resolution via runtime.project_root
try:
    from runtime.project_root import get_agent_dir
except ImportError:
    # Fallback if runtime.project_root not available
    get_agent_dir = None

AGENT_DIR = (
    get_agent_dir()
    if get_agent_dir is not None
    else Path(__file__).resolve().parent.parent / ".agent"
)
MEMORY_DIR = AGENT_DIR / "runtime" / "memory"
OBS_FILE = MEMORY_DIR / "observations.jsonl"
REPORT_FILE = MEMORY_DIR / "session_close_report.md"

# Valid categories per work_plan.md
VALID_CATEGORIES = {"convention", "decision", "fact", "pattern"}

# Minimum signal length
MIN_SIGNAL_LEN = 30

# Noise patterns
NOISE_PREFIXES = ("Tool ",)


def parse_timestamp(ts_str: str) -> datetime:
    """Parse ISO timestamp string to datetime.

    Before: Requires ISO format timestamp string.
    During: Handles Z suffix and timezone conversion.
    After: Returns timezone-aware datetime object.
    """
    ts_str = ts_str.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(ts_str)
    except ValueError:
        return datetime.now(timezone.utc)


def is_noise(signal: str) -> bool:
    """Check if signal should be dropped as noise.

    Before: Requires signal string.
    During: Checks length and noise prefix patterns.
    After: Returns True if noise, False if valid signal.
    """
    signal_stripped = signal.strip()
    if len(signal_stripped) < MIN_SIGNAL_LEN:
        return True
    for prefix in NOISE_PREFIXES:
        if signal_stripped.startswith(prefix) and signal_stripped.endswith("called"):
            return True
    return False


def validate_schema(entry: dict[str, Any]) -> tuple[bool, list[str]]:
    """Validate observation schema.

    Before: Requires observation dict.
    During: Checks required fields and types.
    After: Returns (is_valid, list_of_errors).
    """
    errors = []
    required_fields = [
        "timestamp",
        "signal",
        "category",
        "source_ticket",
        "topic",
        "source",
    ]

    # Check required fields
    missing = [f for f in required_fields if f not in entry]
    errors.extend(f"Campo requerido ausente: {field}" for field in missing)

    if errors:
        return False, errors

    # Validate category
    if entry["category"] not in VALID_CATEGORIES:
        errors.append(
            f"Categoria invalida: {entry['category']} (validas: {VALID_CATEGORIES})"
        )

    # Validate signal length
    if len(entry["signal"].strip()) < MIN_SIGNAL_LEN:
        errors.append(
            f"Signal muy corto: {len(entry['signal'])} chars (min {MIN_SIGNAL_LEN})"
        )

    # Validate signal is not noise
    if is_noise(entry["signal"]):
        errors.append("Signal es ruido (Tool X called pattern o muy corto)")

    # Validate timestamp format
    try:
        parse_timestamp(entry["timestamp"])
    except Exception:
        errors.append(f"Timestamp invalido: {entry['timestamp']}")

    return len(errors) == 0, errors


def is_duplicate(entry: dict[str, Any], existing: list[dict[str, Any]]) -> bool:
    """Check if entry is duplicate of existing observation.

    Before: Requires new entry and list of existing observations.
    During: Compares signal+category+topic within 24h window.
    After: Returns True if duplicate, False if unique.
    """
    new_signal = entry.get("signal", "")
    new_category = entry.get("category", "")
    new_topic = entry.get("topic", "")
    new_ts = parse_timestamp(entry.get("timestamp", ""))

    for existing_entry in existing:
        existing_signal = existing_entry.get("signal", "")
        existing_category = existing_entry.get("category", "")
        existing_topic = existing_entry.get("topic", "")
        existing_ts = parse_timestamp(existing_entry.get("timestamp", ""))

        # Exact match on signal+category+topic
        if (
            new_signal == existing_signal
            and new_category == existing_category
            and new_topic == existing_topic
        ):
            # Check if within 24h window
            hours_diff = abs((new_ts - existing_ts).total_seconds()) / 3600
            if hours_diff <= 24:
                return True

    return False


def load_existing_observations() -> list[dict[str, Any]]:
    """Load existing observations from file.

    Before: Requires observations.jsonl to exist (or not).
    During: Parses JSONL, skipping malformed lines.
    After: Returns list of observation dicts.
    """
    if not OBS_FILE.exists():
        return []

    entries = []
    with open(OBS_FILE, encoding="utf-8") as f:
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


def append_observations(entries: list[dict[str, Any]]) -> None:
    """Append observations to file.

    Before: Requires list of validated entries.
    During: Appends each entry as JSON line.
    After: File updated with new entries.
    """
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    with open(OBS_FILE, "a", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def generate_report(
    generated: int,
    passed: int,
    rejected: int,
    appended: int,
    rejected_reasons: list[str],
    topics: list[str],
) -> str:
    """Generate session close report.

    Before: Requires stats and rejection reasons.
    During: Formats markdown report.
    After: Returns report string.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    report = f"""# Session Close Report

**Generated:** {now}

## Summary

| Metric | Count |
|--------|-------|
| Observaciones generadas | {generated} |
| Pasaron filtros | {passed} |
| Rechazadas | {rejected} |
| Appendeadas (no duplicadas) | {appended} |

## Topics Cubiertos

{chr(10).join(f"- {t}" for t in topics) if topics else "- Ninguno"}

## Razones de Rechazo

{chr(10).join(f"- {r}" for r in rejected_reasons) if rejected_reasons else "- Ninguna"}

## Next Steps

1. Review `.agent/runtime/memory/observations.jsonl` for new entries
2. Run `python scripts/memory_consolidate.py --verbose` if session is long
3. Continue with project-finalize Paso 9d
"""
    return report


def process_candidates(
    candidates: list[dict[str, Any]], existing: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Process candidate observations through filters.

    Before: Requires list of candidate observations and existing observations.
    During: Validates schema, applies curation filters, checks duplicates.
    After: Returns (appended_entries, rejection_reasons).
    """
    appended = []
    rejected_reasons = []

    for candidate in candidates:
        # Validate schema
        is_valid, errors = validate_schema(candidate)
        if not is_valid:
            rejected_reasons.extend(
                f"[{candidate.get('source_ticket', 'unknown')}] {error}"
                for error in errors
            )
            continue

        # Check duplicate
        if is_duplicate(candidate, existing):
            rejected_reasons.append(
                f"[{candidate.get('source_ticket', 'unknown')}] Duplicado de observacion existente"
            )
            continue

        appended.append(candidate)

    return appended, rejected_reasons


def extract_candidates_from_ticket(ticket_id: str) -> list[dict[str, Any]]:
    """Extract candidate observations from work plan ticket.

    Before: Requires ticket ID (e.g., WP-2026-132).
    During: Reads work_plan.md and execution_log.md for events.
    After: Returns list of candidate observation dicts.
    """
    candidates = []
    now = datetime.now(timezone.utc)

    # Read work_plan.md
    work_plan_path = AGENT_DIR / "collaboration" / "work_plan.md"
    if work_plan_path.exists():
        content = work_plan_path.read_text(encoding="utf-8")

        # Extract ticket metadata
        if f"ID:** {ticket_id}" in content or f"ID: {ticket_id}" in content:
            # Extract deliverable_type if present
            deliverable_match = re.search(r"deliverable_type:\s*(\w+)", content)
            deliverable = deliverable_match.group(1) if deliverable_match else "unknown"

            # Extract title
            title_match = re.search(r"Titulo:\s*(.+)", content)
            title = title_match.group(1).strip() if title_match else "Unknown"

            # Generate observation for ticket completion
            candidates.append(
                {
                    "timestamp": now.isoformat(),
                    "signal": f"Ticket {ticket_id} completado: {title} (deliverable_type={deliverable})",
                    "category": "fact",
                    "source_ticket": ticket_id,
                    "topic": "ticket-completion",
                    "source": "session-close",
                }
            )

        # Extract decisions from Decision Arquitectonica section
        if "Decision Arquitectonica" in content:
            candidates.append(
                {
                    "timestamp": now.isoformat(),
                    "signal": f"Decisiones arquitectonicas documentadas en {ticket_id}",
                    "category": "decision",
                    "source_ticket": ticket_id,
                    "topic": "architecture",
                    "source": "session-close",
                }
            )

    return candidates


def main() -> int:
    """Main entry point.

    Before: Requires command-line arguments.
    During: Processes candidates, applies filters, appends valid observations.
    After: Returns exit code (0 success, 1 error).
    """
    parser = argparse.ArgumentParser(
        description="Generate curated observations at session close"
    )
    parser.add_argument(
        "--ticket", type=str, required=True, help="Ticket ID (e.g., WP-2026-132)"
    )
    parser.add_argument("--verbose", action="store_true", help="Print detailed output")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate without writing to observations.jsonl (default: write)",
    )

    args = parser.parse_args()

    try:
        # Load existing observations
        existing = load_existing_observations()
        if args.verbose:
            print(f"Loaded {len(existing)} existing observations")

        # Generate candidates from ticket
        candidates = extract_candidates_from_ticket(args.ticket)
        if args.verbose:
            print(f"Generated {len(candidates)} candidate observations")

        # Process through filters
        appended, rejected_reasons = process_candidates(candidates, existing)

        # Append valid observations (skip on dry-run)
        if appended and not args.dry_run:
            append_observations(appended)
            if args.verbose:
                print(f"Appended {len(appended)} observations to {OBS_FILE}")
        elif appended and args.dry_run:
            if args.verbose:
                print(f"[DRY-RUN] Would append {len(appended)} observations to {OBS_FILE}")

        # Generate report
        report = generate_report(
            generated=len(candidates),
            passed=len(appended),
            rejected=len(candidates) - len(appended),
            appended=len(appended),
            rejected_reasons=rejected_reasons,
            topics=list(set(c.get("topic", "unknown") for c in candidates)),
        )

        # Write report
        mode = "DRY-RUN" if args.dry_run else "APPLIED"
        REPORT_FILE.write_text(report, encoding="utf-8")
        print(f"[{mode}] Report written to {REPORT_FILE}")

        if args.verbose:
            print("\n" + report)

        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
