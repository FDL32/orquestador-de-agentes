"""Review attempt persistence and human escalation report.

Extracted from bus/review_bridge.py (monolith decomposition). This module
owns the on-disk artifacts of the review cycle:

- ``.agent/runtime/reviews/<TICKET>/attempt-N.md`` (idempotent per attempt).
- ``.agent/runtime/review_packets/<TICKET>_attempt-N.md`` path resolution.
- ``human_review_report.md`` generated when the review budget is exhausted
  (5 consecutive CHANGES), consolidating blockers, adaptive-state deltas
  (WT-2026-196) and the last Manager proposal.

``ReviewBridge`` delegates to these functions through thin wrappers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .blocker_signature import blocker_lines_from_signature
from .decision_parser import ReviewDecision


_FALLBACK_REPORT_TEMPLATE = """# Human Review Report

## Ticket
- **Ticket ID:** {{ticket_id}}
- **Generated at:** {{generated_at}}
- **Review attempts:** {{review_attempt_count}}

## Summary
{{summary}}

## Decision Context
- **Last decision:** {{last_decision}}
- **Escalation reason:** {{escalation_reason}}

## Consolidated Blockers
{{blockers}}

## Notes
{{notes}}
"""


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def review_log_path(project_root: Path, ticket_id: str) -> Path:
    """Return (and create) the review log directory for a ticket."""
    ticket_dir = project_root / ".agent" / "runtime" / "reviews" / ticket_id
    ticket_dir.mkdir(parents=True, exist_ok=True)
    return ticket_dir


def review_packet_path(project_root: Path, ticket_id: str, attempt: int) -> Path:
    """Return (and create dir for) the canonical review packet path."""
    packets_dir = project_root / ".agent" / "runtime" / "review_packets"
    packets_dir.mkdir(parents=True, exist_ok=True)
    return packets_dir / f"{ticket_id}_attempt-{attempt}.md"


# ---------------------------------------------------------------------------
# Attempt persistence
# ---------------------------------------------------------------------------


def persist_review_attempt(
    project_root: Path,
    ticket_id: str,
    attempt: int,
    stdout: str,
    stderr: str,
    decision: ReviewDecision,
    review_packet: Path | None = None,
    parse_method: str = "",
    transport_ok: bool = True,
    transport_error: str = "",
    changes_structure: dict[str, str] | None = None,
) -> Path:
    """Persist a review attempt to attempt-N.md idempotently.

    ``changes_structure`` carries the pre-parsed SUMMARY/BLOCKERS/SUGGESTIONS
    sections for CHANGES decisions (the caller owns transcript parsing).
    Returns the Path to the persisted review file.
    """
    ticket_dir = review_log_path(project_root, ticket_id)
    attempt_file = ticket_dir / f"attempt-{attempt}.md"

    content_parts = [
        f"# Review Attempt {attempt}",
        "",
        f"## Ticket: {ticket_id}",
        f"## Decision: {decision.value.upper()}",
        f"## Parse Method: {parse_method or 'unknown'}",
        f"## Transport OK: {transport_ok}",
        "",
        "## Review Packet",
        "",
        str(review_packet.relative_to(project_root).as_posix())
        if review_packet is not None
        else "[not recorded]",
        "",
        "## Transport Error",
        "",
        transport_error or "[none]",
        "",
        "## STDOUT",
        "",
        stdout or "[empty]",
        "",
        "## STDERR",
        "",
        stderr or "[empty]",
        "",
    ]

    if decision == ReviewDecision.CHANGES:
        structured = changes_structure or {}
        content_parts.extend(
            [
                "",
                "## SUMMARY",
                "",
                structured.get("summary", "[no summary provided]"),
                "",
                "## BLOCKERS",
                "",
                structured.get("blockers", "[no blockers provided]"),
                "",
                "## SUGGESTIONS",
                "",
                structured.get("suggestions", "[no suggestions provided]"),
                "",
            ]
        )

    attempt_file.write_text("\n".join(content_parts), encoding="utf-8")
    return attempt_file


# ---------------------------------------------------------------------------
# Human escalation report
# ---------------------------------------------------------------------------


def _render_adaptive_sections(adaptive_state: dict) -> tuple[str, str, str]:
    """Render (repeated_blockers, changed_files, last_proposal) blocks."""
    repeated_blockers_report = ""
    changed_files_report = ""
    last_proposal = ""

    repeated_sigs = adaptive_state.get("repeated_blockers", [])
    if repeated_sigs:
        repeated_lines = [
            "## Repeated BLOCKERS",
            "",
            "The following BLOCKERS reappeared in consecutive reviews:",
        ]
        repeated_lines.extend(
            f"- {line}"
            for sig in repeated_sigs
            for line in blocker_lines_from_signature(sig)
        )
        repeated_blockers_report = "\n".join(repeated_lines) + "\n\n"

    chg = adaptive_state.get("changed_files_since_previous_review", [])
    if isinstance(chg, list):
        if chg:
            changed_files_report = (
                "## Files touched since previous review\n\n"
                + "\n".join(f"- {f}" for f in chg)
                + "\n\n"
            )
        else:
            changed_files_report = (
                "## Files touched since previous review\n\n"
                "(none detected — Builder may not have modified the affected files)\n\n"
            )
    elif isinstance(chg, dict):
        changed_files_report = (
            "## File change tracking\n\n"
            f"Status: {chg.get('status', 'unknown')}\n"
            f"Reason: {chg.get('reason', 'N/A')}\n\n"
        )

    last_feedback = adaptive_state.get("last_feedback", "")
    if last_feedback:
        last_proposal = f"## Last Manager proposal\n\n{last_feedback[:2000]}\n\n"

    return repeated_blockers_report, changed_files_report, last_proposal


def generate_human_review_report(
    project_root: Path,
    ticket_id: str,
    review_attempts: list[dict],
    last_decision: ReviewDecision,
    adaptive_state: dict | None = None,
) -> Path:
    """Generate human_review_report.md from template at 5th rejection.

    Reads the template from ``.agent/templates/human_review_report.md``
    (inline fallback when absent), consolidates blockers and adaptive-state
    context, writes the report under the ticket's review directory and
    returns its Path.
    """
    adaptive_state = adaptive_state or {}
    template_path = project_root / ".agent" / "templates" / "human_review_report.md"
    if template_path.exists():
        template = template_path.read_text(encoding="utf-8")
    else:
        template = _FALLBACK_REPORT_TEMPLATE

    # Consolidate blockers from all attempts
    all_blockers = []
    for attempt in review_attempts:
        payload = attempt.get("payload", {})
        blockers = payload.get("blockers", "")
        if blockers:
            all_blockers.append(
                f"### Attempt {attempt.get('attempt', '?')}\n{blockers}"
            )

    # Build summary
    summary_lines = [
        f"Ticket {ticket_id} reached HUMAN_GATE after {len(review_attempts)} consecutive CHANGES decisions.",
        "",
        "## Review History",
        "",
    ]
    for attempt in review_attempts:
        payload = attempt.get("payload", {})
        summary_lines.append(
            f"- Attempt {attempt.get('attempt', '?')}: "
            f"exit_code={payload.get('exit_code', 'N/A')}, "
            f"duration={payload.get('duration_seconds', 'N/A')}s"
        )

    # WT-2026-196: adaptive-state context blocks
    repeated_blockers_report, changed_files_report, last_proposal = (
        _render_adaptive_sections(adaptive_state)
    )

    notes_lines = [
        "This report was auto-generated when the review budget was exhausted. Human review required.",
        "",
    ]
    if repeated_blockers_report:
        notes_lines.insert(0, repeated_blockers_report)
    if changed_files_report:
        notes_lines.insert(0, changed_files_report)
    if last_proposal:
        notes_lines.insert(0, last_proposal)

    report_content = (
        template.replace("{{ticket_id}}", ticket_id)
        .replace("{{generated_at}}", datetime.now(timezone.utc).isoformat())
        .replace("{{review_attempt_count}}", str(len(review_attempts)))
        .replace("{{summary}}", "\n".join(summary_lines))
        .replace("{{last_decision}}", last_decision.value.upper())
        .replace(
            "{{escalation_reason}}",
            f"Reached {len(review_attempts)} consecutive CHANGES decisions (threshold: 5)"
            + (
                f". Repeated blockers detected: {len(adaptive_state.get('repeated_blockers', []))}"
                if adaptive_state.get("repeated_blockers")
                else ""
            ),
        )
        .replace(
            "{{blockers}}",
            "\n\n".join(all_blockers)
            if all_blockers
            else "[No structured blockers found]",
        )
        .replace(
            "{{notes}}",
            "\n".join(notes_lines).strip()
            or "This report was auto-generated when the review budget was exhausted. Human review required.",
        )
    )

    report_path = review_log_path(project_root, ticket_id) / "human_review_report.md"
    report_path.write_text(report_content, encoding="utf-8")
    return report_path
