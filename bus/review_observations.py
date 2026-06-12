"""Review memory context: observations, anti-patterns and L2 rules.

Extracted from bus/review_bridge.py (monolith decomposition). This module
owns everything the Manager review prompt needs from persistent memory:

- L1 observations from ``.agent/runtime/memory/observations.jsonl``
  (domain-relevance route with legacy topic fallback, WP-2026-177).
- L2 domain rules via ``bus.memory_loader.get_review_context`` (WP-2026-178).
- Canonical anti-pattern inventory from ``skills/_shared/anti-patterns.md``.

All functions are pure or filesystem-read-only; nothing here mutates state.
``ReviewBridge`` delegates to these functions and keeps thin wrappers for
backward compatibility.
"""

from __future__ import annotations

import json
import re
import warnings
from datetime import datetime, timezone
from pathlib import Path

from .memory_loader import get_review_context


MAX_RUBRIC_OBSERVATIONS = 5
MAX_OBSERVATION_SIGNAL_CHARS = 200

# Domain-to-deliverable_type relevance mapping (WP-2026-177)
# Maps each domain to the set of deliverable_types it applies to.
# Canonical entries use 'domain'; legacy entries use topic='manager-review-rubric'.
DOMAIN_DTYPE_MAP: dict[str, set[str]] = {
    "review-quality": {"code", "mixed", "documentation", "research", "analysis"},
    "delivery-hygiene": {"code", "mixed"},
    "builder-contract": {"code", "mixed"},
    "testing": {"code", "mixed"},
    "security-gates": {"code", "mixed"},
    "integration-tests": {"code", "mixed"},
    "protocol-handlers": {"code", "mixed"},
    "bus-architecture": {"code", "mixed"},
    "config-schema": {"code", "mixed"},
}


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def observations_path(project_root: Path) -> Path:
    """Return the canonical observations.jsonl path for a workspace root."""
    return project_root / ".agent" / "runtime" / "memory" / "observations.jsonl"


def canonical_anti_patterns_path() -> Path:
    """Return the motor-relative path to the canonical anti-pattern inventory."""
    return (
        Path(__file__).resolve().parents[1] / "skills" / "_shared" / "anti-patterns.md"
    )


# ---------------------------------------------------------------------------
# Anti-pattern inventory
# ---------------------------------------------------------------------------


def parse_canonical_anti_patterns(content: str) -> list[tuple[str, str]]:
    """Parse ``## AP-NN - Name`` headings into (id, name) tuples."""
    inventory: list[tuple[str, str]] = []
    pattern = re.compile(r"^##\s+(AP-\d{2})\s*-\s*(.+?)\s*$")
    for raw_line in content.splitlines():
        match = pattern.match(raw_line.strip())
        if not match:
            continue
        inventory.append((match.group(1), match.group(2).strip()))
    return inventory


def load_canonical_anti_patterns(path: Path | None = None) -> list[tuple[str, str]]:
    """Load and parse the canonical anti-pattern inventory; warn on failure.

    ``path`` overrides the canonical location (used by tests and callers
    that resolve the inventory through their own seam).
    """
    if path is None:
        path = canonical_anti_patterns_path()
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        warnings.warn(
            f"Canonical anti-pattern inventory unavailable at {path}: {exc}",
            RuntimeWarning,
            stacklevel=2,
        )
        return []

    inventory = parse_canonical_anti_patterns(content)
    if not inventory:
        warnings.warn(
            f"Canonical anti-pattern inventory at {path} is empty or invalid.",
            RuntimeWarning,
            stacklevel=2,
        )
    return inventory


def render_anti_pattern_inventory(inventory: list[tuple[str, str]]) -> str:
    """Render the inventory as a prompt block; empty string if no entries."""
    if not inventory:
        return ""
    lines = ["Canonical anti-pattern inventory (from skills/_shared/anti-patterns.md):"]
    for ap_id, ap_name in inventory:
        lines.append(f"- {ap_id} {ap_name}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Observation record parsing
# ---------------------------------------------------------------------------


def parse_observation_timestamp(raw_timestamp: object) -> datetime:
    """Parse an ISO timestamp; return tz-aware datetime.min on failure."""
    if isinstance(raw_timestamp, str):
        stamp = raw_timestamp.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(stamp)
            return (
                parsed
                if parsed.tzinfo is not None
                else parsed.replace(tzinfo=timezone.utc)
            )
        except ValueError:
            pass
    return datetime.min.replace(tzinfo=timezone.utc)


def truncate_observation_signal(signal: object) -> str:
    """Normalize and truncate an observation signal for prompt inclusion."""
    text = str(signal or "").strip()
    if len(text) <= MAX_OBSERVATION_SIGNAL_CHARS:
        return text
    return text[: MAX_OBSERVATION_SIGNAL_CHARS - 3].rstrip() + "..."


def observation_matches_dtype(record: dict, dtype: str) -> bool:
    """Return True if the observation applies to the given deliverable_type."""
    if dtype == "all":
        return True
    applies_to = record.get("applies_to")
    if applies_to is None or applies_to == "all":
        return True
    targets = applies_to if isinstance(applies_to, list) else [applies_to]
    return dtype in targets or "all" in targets


def parse_observation_record(raw_line: str) -> dict | None:
    """Parse a single JSONL line into a validated dict, or None."""
    line = raw_line.strip()
    if not line:
        return None
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None
    return record if isinstance(record, dict) else None


def record_to_observation_tuple(record: dict) -> tuple[datetime, str, str] | None:
    """Extract (timestamp, signal, source_ticket) from a record, or None."""
    signal = truncate_observation_signal(record.get("signal", ""))
    if not signal:
        return None
    timestamp = parse_observation_timestamp(record.get("timestamp"))
    source_ticket = str(record.get("source_ticket", "")).strip() or "unknown"
    return (timestamp, signal, source_ticket)


def relevant_domains_for_dtype(dtype: str) -> set[str]:
    """Compute the set of domain names relevant to a given deliverable_type."""
    if dtype == "all":
        return set()
    domains: set[str] = set()
    for domain, dtypes in DOMAIN_DTYPE_MAP.items():
        if dtype in dtypes:
            domains.add(domain)
    return domains


# ---------------------------------------------------------------------------
# Observation loading (L1)
# ---------------------------------------------------------------------------


def _read_observation_lines(project_root: Path) -> list[str]:
    """Read observations.jsonl lines; empty list when missing or unreadable."""
    path = observations_path(project_root)
    if not path.exists():
        return []
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []


def load_review_observations_by_domain(
    project_root: Path, dtype: str = "all"
) -> list[tuple[datetime, str, str]]:
    """Load observations by domain relevance to deliverable_type.

    WP-2026-177: Primary route for canonical entries that carry a 'domain'
    field. Returns observations whose domain is relevant to dtype.
    """
    relevant_domains = relevant_domains_for_dtype(dtype)
    observations: list[tuple[datetime, str, str]] = []
    for raw_line in _read_observation_lines(project_root):
        record = parse_observation_record(raw_line)
        if record is None:
            continue
        domain = record.get("domain")
        if not domain:
            continue
        if dtype != "all" and domain not in relevant_domains:
            continue
        if not observation_matches_dtype(record, dtype):
            continue
        obs = record_to_observation_tuple(record)
        if obs:
            observations.append(obs)

    observations.sort(key=lambda item: item[0], reverse=True)
    return observations[:MAX_RUBRIC_OBSERVATIONS]


def load_review_observations(
    project_root: Path, dtype: str = "all"
) -> list[tuple[datetime, str, str]]:
    """Load observations by domain relevance with legacy fallback.

    WP-2026-177: Primary route is domain-based (canonical entries).
    Falls back to topic='manager-review-rubric' for legacy entries
    when no domain-based results are found.
    """
    domain_observations = load_review_observations_by_domain(project_root, dtype)
    if domain_observations:
        return domain_observations

    observations: list[tuple[datetime, str, str]] = []
    for raw_line in _read_observation_lines(project_root):
        record = parse_observation_record(raw_line)
        if record is None:
            continue
        if record.get("topic") != "manager-review-rubric":
            continue
        if not observation_matches_dtype(record, dtype):
            continue
        obs = record_to_observation_tuple(record)
        if obs:
            observations.append(obs)

    observations.sort(key=lambda item: item[0], reverse=True)
    return observations[:MAX_RUBRIC_OBSERVATIONS]


# ---------------------------------------------------------------------------
# Prompt rendering (L2 rules + L1 learnings)
# ---------------------------------------------------------------------------


def render_loader_rules(dtype: str = "all", domains: set[str] | None = None) -> str:
    """Load L2 domain rules from the memory loader as primary memory source.

    WP-2026-178: Uses memory_loader.get_review_context() to load L2 rules
    by domain relevance as the first choice for review memory context.
    Falls back to empty string (caller will use legacy L1 observations).

    ``domains`` overrides the dtype-derived domain set (used by callers that
    resolve relevance through their own seam).
    """
    if dtype == "all":
        return ""

    relevant_domains = (
        domains if domains is not None else relevant_domains_for_dtype(dtype)
    )
    parts: list[str] = []
    seen_blocks: set[str] = set()
    for domain in sorted(relevant_domains):
        domain_rules = get_review_context(domain=domain)
        if domain_rules and domain_rules not in seen_blocks:
            parts.append(domain_rules)
            seen_blocks.add(domain_rules)

    if not parts:
        return ""

    return "\n--- Memory Rules (L2, from memory_loader) ---\n" + "\n\n".join(parts)


def render_review_learnings(project_root: Path, dtype: str = "all") -> str:
    """Render accumulated audit lessons (L1 observations) as a prompt block."""
    observations = load_review_observations(project_root, dtype=dtype)
    if not observations:
        return ""

    lines = ["Lecciones acumuladas de auditoria (de revisiones anteriores):"]
    for timestamp, signal, source_ticket in observations:
        date = timestamp.astimezone(timezone.utc).date().isoformat()
        lines.append(f"- [{date}] {signal} ({source_ticket})")
    return "\n".join(lines)
