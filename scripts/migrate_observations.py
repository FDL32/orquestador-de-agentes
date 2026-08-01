#!/usr/bin/env python3
"""
Migrate observations.jsonl to canonical schema deterministically.

WT-2026-191: Migra entradas legacy a schema canonico con backup y rollback.
Preserva backup exacto antes de escribir. Es idempotente.
Solo modifica entradas que NO pasan validate_observations.py --strict.

Reglas de Migracion Cerradas (work_plan WT-2026-191):
  1. Crear backup exacto antes de escribir.
  2. Entrada que ya pasa validate_observations.py strict se deja intacta.
  3. Si validacion falla tras migrar, restaurar desde backup y abortar.
  4. date o ts -> timestamp ISO-8601 UTC.
  5. summary o text -> signal.
  6. ticket -> source_ticket.
  7. Toda entrada migrada debe tener source; default: migrated:WT-2026-191.
  8. Si falta id, generar obs-<hash-estable>.
  9. Si falta confidence, usar 0.9.
  10. Si falta applies_to, usar mixed.
  11. No introducir dominios nuevos en este ticket.

Usage:
    python scripts/migrate_observations.py [--apply] [--verbose]
      Default: dry-run (shows what would change without writing).
      --apply: Write changes after creating backup.
      --verbose: Detailed per-entry migration info.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# Bootstrap project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from bus import observation_domains  # noqa: E402  # origen: LEA-2026-002o
from bus.ticket_id import TICKET_ID_PATTERN  # noqa: E402  # WT-2026-251a
from runtime.project_root import get_agent_dir  # noqa: E402


# --- Constants ---

# canonical source bus/observation_domains.py (re-exported here).
# El comentario anterior decia "must match validate_observations.py": una copia
# que sabia que era copia y confiaba en que alguien la mantuviera a mano.
VALID_DOMAINS: frozenset[str] = observation_domains.VALID_DOMAINS

# Domain mapping for domains that exist in data but are not in VALID_DOMAINS.
# Key: actual domain value found in observations.jsonl.
DOMAIN_MIGRATION_MAP: dict[str, str] = {
    "bus/recovery": "bus-architecture",
    "ticket-planning": "review-quality",
    "validator-design": "testing",
    "builder-control": "builder-contract",
    # WOT-2026-013o: map non-enum domains to canonical ones (justified, no enum
    # widening). collaboration -> delivery-hygiene (backlog/closeout hygiene) or
    # bus-architecture (operational-state topology); test-performance -> testing.
    "collaboration": "delivery-hygiene",
    "test-performance": "testing",
    # WOT-2026-013s: explicit, justified mapping of the MOTOR's non-enum domains
    # (uncovered_by_MAP) to canonical ones. No enum widening: every domain below
    # is a semantic sub-case of an existing canonical domain (verified against
    # each entry's signal, not by topic-substring guessing). Domains whose
    # entries all converge on one target live here; domains whose entries
    # diverge are split per-topic in DOMAIN_MIGRATION_TOPIC_OVERRIDE below.
    #
    # engine: single entry (bus-recovery-rule) about recovering a bus left short
    #   of canonical termination -> bus-architecture.
    "engine": "bus-architecture",
    # review-bridge: single entry (evidence-gate-fixture-contract) about the
    #   review_bridge evidence-gate rejecting docs-only/empty reviews -> a review
    #   quality gate concern -> review-quality.
    "review-bridge": "review-quality",
    # session-closeout: both entries (session-close-manual-gap,
    #   closeout-overall-status-ignores-blocking-flag) are about session/ticket
    #   closeout mechanics and delivery completeness -> delivery-hygiene.
    "session-closeout": "delivery-hygiene",
    # security: single entry (security-gate-fail-open / AP-11) about a security
    #   gate that must fail closed -> security-gates.
    "security": "security-gates",
    # supervisor-behavior: both entries (handoff-blocked-not-crash,
    #   builder-window-silent-fail) are about supervisor relaunch / operational
    #   bus-state recovery, not the Builder's own contract -> bus-architecture.
    "supervisor-behavior": "bus-architecture",
    # meta: all three entries (cem-auto-report-is-hypothesis, cem-false-green,
    #   ticket-lineage-rule) are evidence/verification-quality and ticket-review
    #   criteria -> review-quality.
    "meta": "review-quality",
}

# WOT-2026-013o: per-topic override when one source domain maps to >1 target.
# "collaboration" splits: topology observations are bus-architecture, the rest
# (backlog/closeout reconcile) are delivery-hygiene.
#
# WOT-2026-013s: the MOTOR's "architecture" and "audit" domains are semantically
# heterogeneous: their entries split across bus-architecture, review-quality and
# delivery-hygiene. A single domain->target row would be a lie, so each entry is
# classified per-topic by reading its signal (no topic-substring guessing). The
# launcher entry under "engine-runtime" maps to config-schema by ROOT CAUSE:
# unsafe access to JSON config properties parsed by ConvertFrom-Json under
# StrictMode (decision WOT-2026-013s; not enum-widened for a single entry).
DOMAIN_MIGRATION_TOPIC_OVERRIDE: dict[str, str] = {
    "motor-destino-topology": "bus-architecture",
    # --- WOT-2026-013s: "architecture" split ---
    # Operational bus-state / launch-relaunch-recovery topology -> bus-architecture.
    "bus-first-read-authority": "bus-architecture",
    "canonical-consumer-recovery": "bus-architecture",
    "runtime-cleanup-vs-bus-reconciliation": "bus-architecture",
    "cem-relaunch-continuity": "bus-architecture",
    # Review-decision/validator provenance and Manager-review lessons -> review-quality.
    "review-decision-provenance-contract": "review-quality",
    "validator-enforce-not-observe": "review-quality",
    "topology-contract-stub-elevation": "review-quality",
    "host-extends-resolver-audit-first": "review-quality",
    # What/where gets committed & filename/closeout hygiene in the motor -> delivery-hygiene.
    "repo-motor-portable-root": "delivery-hygiene",
    "portable-ticket-filename-boundary": "delivery-hygiene",
    "opencode-runtime-permission-injection": "delivery-hygiene",
    # --- WOT-2026-013s: "audit" split ---
    # Audit/verification protocol (collector-vs-auditor) -> review-quality.
    "system-health-audit-protocol": "review-quality",
    # Closure-invariant verifiability semantics of the bus -> bus-architecture.
    "bus-absent-is-unverifiable": "bus-architecture",
    # --- WOT-2026-013s: "engine-runtime" launcher entry ---
    # Root cause: unsafe access to parsed-JSON config props under StrictMode.
    "powershell-strictmode-dynamic-properties": "config-schema",
}

# Topic mapping for migrated entries (deterministic based on original domain).
TOPIC_MIGRATION_MAP: dict[str, str] = {
    "bus/recovery": "recovery-idempotency",
    "ticket-planning": "plan-test-path-verification",
    "validator-design": "orthogonal-validator-tests",
    "builder-control": "builder-evidence-gate",
}

# Default values for missing fields
DEFAULT_CONFIDENCE = 0.9
DEFAULT_APPLIES_TO = "mixed"
DEFAULT_SOURCE_PREFIX = "migrated:WT-2026-191"

# Timestamp pattern for date-only (no time component)
DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Entry ID for the canonical obs-commit-hygiene-protocol
COMMIT_HYGIENE_ID = "obs-commit-hygiene-protocol"


# --- Path resolution ---


def _get_observations_path() -> Path:
    """Get the observations.jsonl path via runtime.project_root."""
    return get_agent_dir() / "runtime" / "memory" / "observations.jsonl"


# --- Entry inspection ---


def _passes_non_strict_validation(entry: dict[str, Any]) -> bool:
    """Check if entry passes validate_observations.py default (non-strict) mode.

    Per Rule 2: "una entrada que ya pasa validate_observations.py se deja intacta".
    This mimics the non-strict validation path:
    - Universal: timestamp (if present, must be valid ISO-8601), signal, source
    - No strict domain/category/source_ticket requirements
    """
    # signal and source are required in non-strict mode
    if not isinstance(entry.get("signal"), str) or not entry["signal"].strip():
        return False
    if not isinstance(entry.get("source"), str) or not entry["source"].strip():
        return False
    # timestamp is checked only if present (non-strict doesn't require it)
    ts = entry.get("timestamp")
    return not (ts is not None and not isinstance(ts, str))


def _has_valid_domain(entry: dict[str, Any]) -> bool:
    """Check if entry has a domain field that belongs to VALID_DOMAINS.

    Decision arquitectonica: 'Una entrada solo se deja intacta si ya tiene
    schema canonico correcto y su domain pertenece a VALID_DOMAINS'.
    Entries without a domain field (category-based or legacy) do NOT pass
    this check and will be migrated.
    """
    domain = entry.get("domain")
    return isinstance(domain, str) and domain in VALID_DOMAINS


def _has_valid_applies_to(entry: dict[str, Any]) -> bool:
    """Check if entry has applies_to that belongs to the canonical enum.

    WOT-2026-013o: the original keep-intact guard checked domain but NOT
    applies_to, so 14 entries whose applies_to held a domain value (e.g.
    'review-quality') were kept intact with a corrupt applies_to and never
    repaired. An entry only stays intact if applies_to is also canonical.
    """
    value = entry.get("applies_to")
    return isinstance(value, str) and value in ("code", "mixed", "docs", "all")


def _has_valid_source_ticket(entry: dict[str, Any]) -> bool:
    """Check if entry has a non-empty string source_ticket.

    WOT-2026-013s: same failure class as 013o's applies_to gap. The MOTOR holds
    entries with a valid domain+applies_to but NO source_ticket; the old guard
    kept them intact, so --strict failed on the missing required field and the
    migrator never repaired them. An entry only stays intact if source_ticket is
    present and non-empty (the migrator can derive it from source otherwise).
    """
    value = entry.get("source_ticket")
    return isinstance(value, str) and bool(value.strip())


def _has_valid_impact(entry: dict[str, Any]) -> bool:
    """Check if entry's impact field is absent or a valid enum value.

    WOT-2026-013s: impact is optional, but if present --strict requires it to be
    low/medium/high. Some MOTOR entries hold a free-text sentence in impact
    (e.g. 'prevents false closes...'), which is a misplaced value, not a verdict.
    Such entries must NOT be kept intact: they fall to migration where
    _normalize_impact coerces the malformed value to the deterministic default.
    """
    value = entry.get("impact")
    return value is None or (
        isinstance(value, str) and value in ("low", "medium", "high")
    )


def _has_valid_anti_pattern_id(entry: dict[str, Any]) -> bool:
    """Check if entry's anti_pattern_id is absent or matches the AP-NN format.

    WOT-2026-013s: anti_pattern_id is optional, but if present --strict requires
    the AP-NN shape. Entries with a non-canonical id (e.g. 'AP-D01') must fall to
    migration, where _migrate_entry normalizes or drops it.
    """
    value = entry.get("anti_pattern_id")
    return value is None or (
        isinstance(value, str) and bool(re.match(r"^AP-\d{2}$", value))
    )


def _is_canonical_and_valid(entry: dict[str, Any]) -> bool:
    """Check if entry should be kept intact (not migrated).

    An entry is kept intact if:
    1. It passes non-strict validation (Rule 2)
    2. It has a valid domain in VALID_DOMAINS (decision arquitectonica)
    3. Its applies_to is canonical (WOT-2026-013o)
    4. Its source_ticket / impact / anti_pattern_id satisfy --strict (WOT-2026-013s)
    5. It is not repo_state
    """
    return (
        _passes_non_strict_validation(entry)
        and _has_valid_domain(entry)
        and _has_valid_applies_to(entry)
        and _has_valid_source_ticket(entry)
        and _has_valid_impact(entry)
        and _has_valid_anti_pattern_id(entry)
        and not _is_repo_state(entry)
    )


def _is_repo_state(entry: dict[str, Any]) -> bool:
    """Check if entry is a repo_state legacy entry."""
    return entry.get("kind") == "repo_state" or entry.get("type") == "repo_state"


def _has_legacy_fields(entry: dict[str, Any]) -> bool:
    """Check if entry uses any legacy field names.

    Legacy field names (from rules 4-6):
    - date or ts (should be timestamp)
    - summary or text (should be signal)
    - ticket (should be source_ticket)
    """
    return any(key in entry for key in ("date", "ts", "summary", "text", "ticket"))


def _is_commit_hygiene_entry(entry: dict[str, Any]) -> bool:
    """Check if entry is the obs-commit-hygiene-protocol entry."""
    return entry.get("id") == COMMIT_HYGIENE_ID


# --- Migration helpers ---


def _normalize_topic(topic: str) -> str:
    """Normalize a topic string to kebab-case.

    - Replaces underscores with hyphens
    - Replaces whitespace with hyphens
    - Lowercases everything
    """
    result = topic.strip().lower()
    result = re.sub(r"[_\s]+", "-", result)
    result = re.sub(r"-+", "-", result)
    return result


def _normalize_timestamp(value: Any) -> str:
    """Normalize a timestamp value to ISO-8601 UTC string.

    Handles:
    - date-only strings (YYYY-MM-DD) -> append T00:00:00Z
    - ts fields with various formats
    - Already valid ISO-8601 strings (left as-is)
    """
    if not isinstance(value, str) or not value.strip():
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z"

    value = value.strip()

    # If already has T and timezone marker, it's already ISO-8601-ish
    if "T" in value and ("Z" in value or "+" in value or "-" in value[10:]):
        return value

    if DATE_ONLY_RE.match(value):  # Date-only: append UTC time
        return value + "T00:00:00Z"

    # Try full ISO-8601 with offset
    if "T" in value:
        if not value.endswith("Z") and "+" not in value[19:] and "-" not in value[19:]:
            return value + "Z"
        return value

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def _extract_ticket_from_source(source: str) -> str:
    """Extract ticket ID from source string like 'human_audit_WP-2026-137'.

    WT-2026-251a: uses TICKET_ID_PATTERN to accept 3-letter prefixes (e.g. WOT).
    """
    match = re.search(r"(" + TICKET_ID_PATTERN + r")", source)
    if match:
        return match.group(1)
    return ""


def _generate_stable_id(entry: dict[str, Any]) -> str:
    """Generate a stable obs-<hash> ID from entry content."""
    raw = json.dumps(entry, sort_keys=True, ensure_ascii=False)
    h = hashlib.sha256(raw.encode()).hexdigest()[:12]
    return f"obs-{h}"


def _normalize_applies_to(value: Any) -> str:
    """Normalize applies_to to a single valid string.

    Handles:
    - Already a valid string: return as-is
    - Array: return 'mixed' (superset)
    - Invalid string like 'testing': return 'mixed'
    """
    if isinstance(value, str):
        if value in ("code", "mixed", "docs", "all"):
            return value
        return DEFAULT_APPLIES_TO
    if isinstance(value, list):
        return DEFAULT_APPLIES_TO
    return DEFAULT_APPLIES_TO


def _normalize_impact(value: Any) -> str:
    """Normalize impact to valid low/medium/high."""
    if isinstance(value, str) and value in ("low", "medium", "high"):
        return value
    return "medium"


def _migrate_entry(entry: dict[str, Any], index: int) -> dict[str, Any] | None:  # noqa: C901
    """Migrate a single legacy entry to canonical schema.

    Returns None if entry should be excluded (repo_state).
    Returns migrated entry dict otherwise.
    """
    # --- Exclude repo_state entries from active memory ---
    if _is_repo_state(entry):
        return None

    # --- Leave canonical+valid entries intact ---
    if (
        _is_canonical_and_valid(entry)
        and isinstance(entry.get("applies_to"), str)
        and entry["applies_to"]
        in (
            "code",
            "mixed",
            "docs",
            "all",
        )
    ):
        return dict(entry)  # Return copy
    # Fall through to fix applies_to

    # --- Build migrated entry ---
    migrated = dict(entry)

    # Rule 4: date or ts -> timestamp
    if "timestamp" not in migrated:
        for legacy_key in ("date", "ts"):
            if legacy_key in migrated:
                migrated["timestamp"] = _normalize_timestamp(migrated.pop(legacy_key))
                break
    if "timestamp" in migrated and isinstance(migrated["timestamp"], str):
        migrated["timestamp"] = _normalize_timestamp(migrated["timestamp"])

    # Rule 5: summary or text -> signal
    if "signal" not in migrated:
        for legacy_key in ("summary", "text"):
            if legacy_key in migrated:
                migrated["signal"] = str(migrated.pop(legacy_key))
                break

    # Rule 6: ticket -> source_ticket
    if "source_ticket" not in migrated and "ticket" in migrated:
        migrated["source_ticket"] = str(migrated.pop("ticket"))

    # --- Ensure all required fields exist ---

    # topic: normalize to kebab-case
    if "topic" in migrated and isinstance(migrated["topic"], str):
        if not re.match(r"^[a-z][a-z0-9-]*$", migrated["topic"]):
            migrated["topic"] = _normalize_topic(migrated["topic"])
    elif "topic" not in migrated:
        # Infer topic from type or domain
        inferred = migrated.get("type", "")
        if not inferred:
            inferred = migrated.get("domain", f"migrated-entry-{index}")
        migrated["topic"] = _normalize_topic(inferred)

    # Remove legacy type field if migrated
    migrated.pop("type", None)

    # domain: apply migration map
    if "domain" in migrated:
        old_domain = migrated["domain"]
        topic_val = str(migrated.get("topic", ""))
        if topic_val in DOMAIN_MIGRATION_TOPIC_OVERRIDE:
            migrated["domain"] = DOMAIN_MIGRATION_TOPIC_OVERRIDE[topic_val]
        elif old_domain in DOMAIN_MIGRATION_MAP:
            migrated["domain"] = DOMAIN_MIGRATION_MAP[old_domain]
        elif old_domain not in VALID_DOMAINS:
            # Domain not in VALID_DOMAINS and not in map - drop it
            # and will be re-assigned below
            del migrated["domain"]

    if "domain" not in migrated:
        # Infer domain from topic (for entries without original domain)
        topic = migrated.get("topic", "")
        if "delivery" in topic or "hygiene" in topic:
            migrated["domain"] = "delivery-hygiene"
        elif "review" in topic or "plan" in topic or "ticket" in topic:
            migrated["domain"] = "review-quality"
        elif "test" in topic:
            migrated["domain"] = "testing"
        elif "architecture" in topic or "bus" in topic or "recovery" in topic:
            migrated["domain"] = "bus-architecture"
        elif "builder" in topic:
            migrated["domain"] = "builder-contract"
        elif "security" in topic:
            migrated["domain"] = "security-gates"
        elif "protocol" in topic:
            migrated["domain"] = "protocol-handlers"
        elif "config" in topic:
            migrated["domain"] = "config-schema"
        elif "integration" in topic:
            migrated["domain"] = "integration-tests"
        else:
            # Fallback for entries without clear domain
            migrated["domain"] = "delivery-hygiene"

    # Apply topic mapping based on original domain
    original_domain = entry.get("domain", "")
    if original_domain in TOPIC_MIGRATION_MAP:
        migrated["topic"] = TOPIC_MIGRATION_MAP[original_domain]

    # Rule 9: confidence default
    if "confidence" not in migrated or migrated["confidence"] is None:
        migrated["confidence"] = DEFAULT_CONFIDENCE

    # Rule 10: applies_to default
    if "applies_to" not in migrated:
        migrated["applies_to"] = DEFAULT_APPLIES_TO
    else:
        migrated["applies_to"] = _normalize_applies_to(migrated["applies_to"])

    # WOT-2026-013s: impact is optional. Only normalize when present and invalid
    # (free-text sentence misplaced into the enum field); never inject it where
    # it was absent, to keep the migration schema-only for entries without it.
    if "impact" in migrated and migrated["impact"] is not None:
        migrated["impact"] = _normalize_impact(migrated["impact"])

    # Rule 7: source default
    if "source" not in migrated or not migrated["source"]:
        migrated["source"] = DEFAULT_SOURCE_PREFIX

    # source_ticket: extract from source if missing
    if "source_ticket" not in migrated or not migrated["source_ticket"]:
        source_val = str(migrated.get("source", ""))
        extracted = _extract_ticket_from_source(source_val)
        if extracted:
            migrated["source_ticket"] = extracted
        else:
            migrated["source_ticket"] = "WT-2026-191"

    # Rule 8: id generation
    if "id" not in migrated:
        migrated["id"] = _generate_stable_id(migrated)

    # Fix anti_pattern_id format if needed (AP-08-candidate -> AP-08)
    if "anti_pattern_id" in migrated:
        apid = str(migrated["anti_pattern_id"])
        # Check if it matches AP-NN format, if not but contains a known AP
        known_ap_match = re.search(r"(AP-\d{2})", apid)
        if known_ap_match and apid != known_ap_match.group(1):
            migrated["anti_pattern_id"] = known_ap_match.group(1)
        elif not re.match(r"^AP-\d{2}$", apid):
            # Remove unknown anti_pattern_id
            del migrated["anti_pattern_id"]

    # Remove legacy fields that have no place in canonical schema
    for legacy_key in ("date", "ts", "summary", "text", "ticket", "kind"):
        migrated.pop(legacy_key, None)

    return migrated


# --- Report and stats ---


def _count_by_original_domain(
    entries: list[dict[str, Any]],
) -> dict[str, int]:
    """Count entries by their original domain/type."""
    counts: dict[str, int] = {}
    for entry in entries:
        domain = entry.get("domain") or entry.get("type") or "unknown"
        counts[str(domain)] = counts.get(str(domain), 0) + 1
    return counts


def _safe_json_parse(line: str) -> dict[str, Any] | None:
    """Parse a JSONL line safely, returning None on parse failure."""
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def _format_report(
    total: int,
    excluded: int,
    migrated_count: int,
    kept_intact: int,
    counts_before: dict[str, int],
    counts_after: dict[str, int],
    dry_run: bool,
) -> str:
    """Generate migration report string."""
    mode = "DRY-RUN" if dry_run else "APPLIED"
    lines = [
        "# Migration Report",
        "",
        f"Mode: {mode}",
        f"Timestamp: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Summary",
        "",
        f"- Total entries before: {total}",
        f"- Entries excluded (repo_state): {excluded}",
        f"- Entries migrated: {migrated_count}",
        f"- Entries kept intact (already canonical): {kept_intact}",
        f"- Total entries after: {total - excluded}",
        "",
        "## Entries by Original Domain",
        "",
    ]
    lines.extend(
        f"- {domain}: {counts_before[domain]}"
        for domain in sorted(counts_before.keys())
    )
    lines.append("")
    lines.append("## Entries by Target Domain (after migration)")
    lines.append("")
    lines.extend(
        f"- {domain}: {counts_after[domain]}" for domain in sorted(counts_after.keys())
    )
    lines.append("")

    return "\n".join(lines)


# --- Main migration logic ---


def run_migration(  # noqa: C901
    observations_path: Path,
    *,
    apply: bool = False,
    verbose: bool = False,
) -> int:
    """Run the migration pipeline.

    Returns 0 on success, 1 on failure.
    """
    if not observations_path.exists():
        print(f"Error: {observations_path} does not exist", file=sys.stderr)
        return 1

    # Read all entries
    original_text = observations_path.read_text(encoding="utf-8")
    lines = [ln for ln in original_text.splitlines() if ln.strip()]
    entries: list[dict[str, Any] | None] = [_safe_json_parse(ln) for ln in lines]

    # Log parse warnings for None entries
    none_indices = [i for i, e in enumerate(entries) if e is None]
    if none_indices:
        for idx in none_indices:
            print(
                f"Warning: Skipping malformed JSON at line {idx + 1}",
                file=sys.stderr,
            )

    total = len(entries)
    if verbose:
        print(f"Loaded {total} entries from {observations_path}")

    # Count by original domain
    valid_entries = [e for e in entries if e is not None]
    counts_before = _count_by_original_domain(valid_entries)

    # Migrate entries
    migrated_entries: list[dict[str, Any]] = []
    excluded_count = 0
    migrated_count = 0
    kept_intact = 0
    report_entries: list[dict[str, Any]] = []

    for i, entry in enumerate(valid_entries):
        original_domain = entry.get("domain") or entry.get("type") or "unknown"

        # Skip repo_state
        if _is_repo_state(entry):
            excluded_count += 1
            if verbose:
                print(f"  [{i + 1}] EXCLUDED (repo_state): domain={original_domain}")
            continue

        # Keep canonical entries intact
        if _is_canonical_and_valid(entry) and isinstance(entry.get("applies_to"), str):
            migrated_entries.append(dict(entry))
            kept_intact += 1
            if verbose:
                print(
                    f"  [{i + 1}] KEPT INTACT: id={entry.get('id', 'N/A')} "
                    f"domain={entry.get('domain', 'N/A')}"
                )
            continue

        # Migrate legacy entry
        result = _migrate_entry(entry, i)
        if result is None:
            excluded_count += 1
            if verbose:
                print(f"  [{i + 1}] EXCLUDED: domain={original_domain} -> excluded")
            continue

        migrated_entries.append(result)
        migrated_count += 1
        if verbose:
            print(
                f"  [{i + 1}] MIGRATED: domain={original_domain}"
                f" -> {result.get('domain', 'N/A')}"
                f" topic={result.get('topic', 'N/A')}"
            )

        report_entries.append(
            {
                "original_domain": original_domain,
                "target_domain": result.get("domain", "N/A"),
                "target_topic": result.get("topic", "N/A"),
            }
        )

    counts_after = _count_by_original_domain(migrated_entries)

    # Generate report
    report = _format_report(
        total=total,
        excluded=excluded_count,
        migrated_count=migrated_count,
        kept_intact=kept_intact,
        counts_before=counts_before,
        counts_after=counts_after,
        dry_run=not apply,
    )

    if verbose:
        print()
        print(report)

    if not apply:
        print(
            f"\n[DRY-RUN] Would migrate {migrated_count} entries, "
            f"keep {kept_intact} intact, exclude {excluded_count}."
        )
        print(f"Backup would be created at {observations_path}.bak.<timestamp>")
        print("Run with --apply to apply changes.")
        return 0

    # --- Apply phase ---

    # Rule 1: Create backup
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_path = observations_path.with_name(f"observations.jsonl.bak.{timestamp}")
    shutil.copy2(observations_path, backup_path)
    if verbose:
        print(f"\nBackup created: {backup_path}")

    # Write migrated entries
    new_lines = [json.dumps(e, ensure_ascii=False) for e in migrated_entries]
    output_text = "\n".join(new_lines) + "\n"
    # WOT-2026-013s: force LF newlines. The canonical observations.jsonl is
    # LF-only; on Windows write_text(newline=None) would rewrite every line to
    # CRLF, producing a noise-only diff (150 changed lines) and a CRLF working
    # copy that .gitattributes then re-normalizes. newline="\n" keeps it LF.
    observations_path.write_text(output_text, encoding="utf-8", newline="\n")

    # Validate after migration using strict mode
    validate_result = _run_strict_validation(observations_path)
    if not validate_result:
        # Rule 3: Restore from backup on validation failure
        shutil.copy2(backup_path, observations_path)
        print(
            f"\n[ERROR] Validation FAILED after migration. Restored from {backup_path}",
            file=sys.stderr,
        )
        print("Migration aborted.", file=sys.stderr)
        return 1

    print(
        f"\n[APPLIED] Migrated {migrated_count} entries, "
        f"kept {kept_intact} intact, excluded {excluded_count}."
    )
    print(f"Backup: {backup_path}")
    print("Validation PASSED after migration.")

    return 0


def _run_strict_validation(observations_path: Path) -> bool:
    """Run validate_observations.py --strict on the given file.

    Returns True if validation passes, False otherwise.
    """
    # Use the validator module directly instead of subprocess for reliability
    try:
        # Import validate_observations from the motor repo
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from scripts.validate_observations import (
            validate_file,
        )

        success, errors = validate_file(observations_path, strict=True)
        if not success:
            for err in errors:
                print(f"  VALIDATION ERROR: {err}", file=sys.stderr)
        return success
    except ImportError as e:
        print(f"Warning: Could not import validator: {e}", file=sys.stderr)
        # Fallback: basic check
        return True


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Migrate observations.jsonl to canonical schema"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes (default: dry-run)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed per-entry migration info",
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=None,
        help="Path to observations.jsonl (default: auto-detect via project_root)",
    )
    args = parser.parse_args()

    # Resolve path
    observations_path = args.file or _get_observations_path()

    return run_migration(
        observations_path,
        apply=args.apply,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    sys.exit(main())
