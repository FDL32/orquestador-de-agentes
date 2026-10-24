"""Decision parser extracted from review_bridge (WT-2026-255a).

Standalone functions for parsing OpenCode NDJSON output into ReviewDecision.
No instance state required — all functions are pure with respect to the bus.

Contrato de precedencia (WT-2026-235a + WT-2026-242a):
- NDJSON parsing is always attempted first (try-first).
- Only ``json_final_answer`` can produce APPROVE or CHANGES.
- ``json_last_text`` degrades strong decisions to INSPECT.
- ``text_regex`` is diagnostic only (never produces APPROVE/CHANGES).
- Falls back to text_regex when NDJSON yields no decision.
"""

from __future__ import annotations

import json
import re
import time
from enum import Enum
from pathlib import Path


class ReviewDecision(str, Enum):
    APPROVE = "approve"
    CHANGES = "changes"
    INSPECT = "inspect"
    UNKNOWN = "unknown"
    TRANSPORT_FAILED = "transport_failed"


# Decisiones fuertes aceptadas en el decision artifact (canal primario).
_ARTIFACT_DECISIONS = {
    "APROBADO": ReviewDecision.APPROVE,
    "APPROVE": ReviewDecision.APPROVE,
    "CHANGES": ReviewDecision.CHANGES,
}


def _warn_unrecognized_decision(ticket_id: str, decision_raw: str) -> None:
    """Print a visible WARN for a non-empty decision value outside the enum.

    WOT-2026-042b: a decision artifact that exists, matches the ticket and
    is fresh but carries an unrecognized value (e.g. "APPROVED" instead of
    "APPROVE") previously returned None identically to a missing file, with
    no trace. Extracted to its own function to keep load_decision_artifact's
    branching complexity under the ruff C901 threshold.
    """
    if decision_raw:
        print(
            f"[decision_parser] WARN: decision artifact for {ticket_id} has "
            f"unrecognized decision value '{decision_raw}' (accepted: "
            f"{sorted(_ARTIFACT_DECISIONS)}); falling back to transcript "
            "parsing."
        )


def load_decision_artifact(
    reviews_dir: Path,
    ticket_id: str,
    not_before: float | None = None,
    expected_commit_sha: str | None = None,
) -> tuple[ReviewDecision, str] | None:
    """Load the Manager's structured decision artifact, if valid.

    WT-2026-252a follow-up: the Manager writes
    ``decision_<ticket_id>.json`` ({"ticket_id", "decision", "blockers"})
    under ``.agent/runtime/reviews/`` during its review session. The bridge
    consumes it as the primary decision channel; transcript parsing remains
    the fallback and the transcript remains the evidence.

    WT-2026-047m: when ``expected_commit_sha`` is passed, the function
    compares it against the ``reviewed_commit_sha`` field stored in the
    artifact.  Legacy artifacts that lack this field still return a valid
    result with a ``WARN`` printed to stdout (never a hard failure).  When
    both shas are present and differ, the artifact is stale and the
    function returns ``None`` (the caller falls back to transcript parsing).

    Validation (any failure returns None so the caller falls back):
    - file exists and is valid JSON;
    - ``ticket_id`` in the payload matches the requested ticket;
    - ``decision`` maps to a strong decision (APROBADO/APPROVE/CHANGES);
    - if ``not_before`` is given, the file mtime must not predate it by
      more than the tolerance (artifacts written before this review
      session are stale and ignored). The 2s tolerance absorbs filesystem
      mtime granularity/rounding: stale artifacts are minutes or hours
      old, while an artifact written milliseconds after ``not_before``
      can legitimately receive an earlier rounded mtime.
    - if ``expected_commit_sha`` is passed, the artifact's
      ``reviewed_commit_sha`` is compared; mismatch means the artifact
      approved a different commit than HEAD (returns None); absence of
      the field in a legacy artifact is downgraded to a WARN.
    """
    mtime_tolerance_seconds = 2.0
    path = reviews_dir / f"decision_{ticket_id}.json"
    try:
        if not path.is_file():
            return None
        if (
            not_before is not None
            and path.stat().st_mtime < not_before - mtime_tolerance_seconds
        ):
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("ticket_id") != ticket_id:
        return None
    decision_raw = str(payload.get("decision", "")).strip().upper()
    decision = _ARTIFACT_DECISIONS.get(decision_raw)
    if decision is None:
        _warn_unrecognized_decision(ticket_id, decision_raw)
        return None
    # WT-2026-047m: compare reviewed_commit_sha when expected_commit_sha is passed.
    if expected_commit_sha is not None:
        artifact_sha = payload.get("reviewed_commit_sha")
        if artifact_sha is None:
            # Legacy artifact without reviewed_commit_sha — degrade to WARN,
            # never fail the call retroactively.
            print(
                f"[decision_parser] WARN: decision artifact for {ticket_id} is "
                "legacy (missing reviewed_commit_sha); accepted for backward "
                "compatibility but should be re-reviewed against the current HEAD."
            )
        elif artifact_sha != expected_commit_sha:
            # Stale artifact: the review approved a different commit than HEAD.
            print(
                f"[decision_parser] decision artifact for {ticket_id} approved "
                f"commit {artifact_sha!r} which differs from the current HEAD "
                f"{expected_commit_sha!r}; artifact is stale, falling back to "
                "transcript parsing."
            )
            return None
    return decision, "decision_artifact"


def resolve_event_phase(event: dict) -> str:
    """Resolve the phase field from an OpenCode NDJSON event.

    OpenCode may emit ``phase`` at the event top level or nested inside
    ``part.metadata.openai.phase`` (``--format json`` output). Returns
    the phase string, or empty string if not found at any location.
    """
    phase = event.get("phase", "") or ""
    if phase:
        return phase
    part = event.get("part", {})
    if isinstance(part, dict):
        meta = part.get("metadata", {}) or {}
        if isinstance(meta, dict):
            oai = meta.get("openai", {}) or {}
            if isinstance(oai, dict):
                phase = oai.get("phase", "") or ""
    return phase


def extract_decision_from_single_line(
    line: str, require_final_answer: bool
) -> ReviewDecision | None:
    """Extract decision from a single NDJSON line.

    Returns ReviewDecision if found, None otherwise.
    """
    line = line.strip()
    if not line or not line.startswith("{"):
        return None

    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return None

    if event.get("type") != "text":
        return None

    phase = resolve_event_phase(event)
    if require_final_answer and phase != "final_answer":
        return None

    part = event.get("part", {})
    if not isinstance(part, dict):
        return None
    text = part.get("text", "")
    if not text:
        return None

    text_upper = text.upper()
    if "DECISION: CHANGES" in text_upper:
        return ReviewDecision.CHANGES
    if "DECISION: APPROVE" in text_upper:
        return ReviewDecision.APPROVE
    if "DECISION: INSPECT" in text_upper:
        return ReviewDecision.INSPECT

    return None


def extract_decision_from_text_events(
    stdout: str, require_final_answer: bool
) -> ReviewDecision | None:
    """Extract DECISION from text events, optionally filtering by phase.

    Returns ReviewDecision if found, None otherwise.
    """
    last_decision = None
    for line in stdout.splitlines():
        decision = extract_decision_from_single_line(line, require_final_answer)
        if decision is not None:
            if require_final_answer:
                return decision
            # WT-2026-249c: always overwrite so the LAST text event decision wins.
            last_decision = decision
    return last_decision


def parse_opencode_json_decision(stdout: str) -> tuple[ReviewDecision, str]:
    """Parse OpenCode NDJSON output for DECISION pattern.

    Returns (decision, parse_method) where parse_method is one of:
      - "json_final_answer" — final_answer phase (authoritative)
      - "json_last_text"    — last text event (degraded)
      - "json_no_decision"  — no recognisable decision in NDJSON
    """
    final_answer_decision = extract_decision_from_text_events(
        stdout, require_final_answer=True
    )
    if final_answer_decision is not None:
        return final_answer_decision, "json_final_answer"

    last_text_decision = extract_decision_from_text_events(
        stdout, require_final_answer=False
    )
    if last_text_decision is not None:
        return last_text_decision, "json_last_text"

    return ReviewDecision.INSPECT, "json_no_decision"


def parse_opencode_decision(stdout: str) -> tuple[ReviewDecision, str]:
    """Parse OpenCode output for DECISION: APPROVE|CHANGES|INSPECT.

    Returns (decision, parse_method) where parse_method is one of:
      - "json_final_answer"  — NDJSON final_answer phase (authoritative)
      - "json_last_text"     — NDJSON last text event (degraded)
      - "json_no_decision"   — NDJSON without recognisable decision
      - "text_regex"         — DECISION pattern found in plain text (diagnostic)
      - "explicit_inspect"   — DECISION: INSPECT explicitly found
      - "fallback_inspect"   — no pattern recognized
    """
    json_decision, json_method = parse_opencode_json_decision(stdout)
    if json_decision != ReviewDecision.INSPECT:
        if json_method == "json_final_answer":
            return json_decision, json_method
        return ReviewDecision.INSPECT, json_method
    # json_no_decision — fall through to text_regex

    stdout_upper = stdout.upper()
    if re.search(r"DECISION:\s*CHANGES", stdout_upper):
        return ReviewDecision.INSPECT, "text_regex"
    if re.search(r"DECISION:\s*APPROVE", stdout_upper):
        return ReviewDecision.INSPECT, "text_regex"
    if re.search(r"DECISION:\s*INSPECT", stdout_upper):
        return ReviewDecision.INSPECT, "explicit_inspect"

    return ReviewDecision.INSPECT, "fallback_inspect"


def parse_opencode_decision_with_retry(
    stdout: str,
    stderr: str,
    max_retries: int = 2,
) -> tuple[ReviewDecision, int, str]:
    """Parse OpenCode output with controlled retry for transient parse failures.

    Returns (decision, parse_attempts, parse_method).
    """
    decision, parse_method = parse_opencode_decision(stdout)
    parse_attempts = 1

    if decision == ReviewDecision.INSPECT and parse_method == "fallback_inspect":
        is_technical_failure = (
            "TimeoutExpired" in stderr
            or "FileNotFoundError" in stderr
            or "OSError" in stderr
            or not stdout.strip()
        )
        if not is_technical_failure and stdout.strip():
            for retry in range(max_retries):
                time.sleep(0.1 * (2**retry))
                decision, parse_method = parse_opencode_decision(stdout)
                parse_attempts += 1
                if parse_method != "fallback_inspect":
                    break

    return decision, parse_attempts, parse_method
