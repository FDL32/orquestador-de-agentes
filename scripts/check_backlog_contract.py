#!/usr/bin/env python3
"""WOT-2026-012b: fail-closed gate for the live backlog contract.

Turns the parseable live-queue contract that WOT-2026-012a fixed into an
executable barrier. Reads ONLY the active "Vista rapida" table of
repo_destino/.agent/collaboration/backlog.md and validates its structure and
the closed Status / Reactivation vocabulary.

Before: project_root MUST be given via --project-root or AGENT_PROJECT_ROOT.
    Unlike runtime.project_root.resolve_project_root(), this gate does NOT fall
    back to __file__ derivation: a backlog read relative to the motor cwd would
    be the wrong file (the motor seed, not the destino queue). Missing root is a
    fail-closed error, not a pass-open.
During: parse the markdown table under the "## Vista rapida" header (never HTML
    comments or free prose). For each live row validate: 8 columns, Status in the
    closed vocabulary, and a Reactivation value consistent with the Status.
    Validate that every "### WOT-..." / "### WT-..." ficha header is well formed.
After: exit 0 when the contract holds; exit non-zero with a diagnostic per
    violation otherwise. No mutation, ever.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path


# WOT-2026-012a closed vocabulary for the LIVE queue. Terminal states
# (completed/done/closed/absorbed) must NOT appear here: they belong in history.
LIVE_STATES = (
    "pending",
    "blocked",
    "deferred",
    "ready-for-review",
    "awaiting-manager",
    "completed-partial",
)

# States that REQUIRE a structured Reactivation trigger (not "-").
REACTIVATION_REQUIRED = ("blocked", "deferred", "completed-partial")

# Structured Reactivation trigger prefixes (012a contract). "-" means "no
# trigger" and is only valid for active states without one.
REACTIVATION_PREFIXES = ("condition:", "commit:", "external:")
# A bare ticket id (WOT-YYYY-NNNx / WT-...) is also a valid trigger.
_TICKET_TRIGGER_RE = re.compile(r"^(?:WOT|WP|WT)-\d{4}-\w+$")

# Vocabulary that is NEVER a valid structured trigger (vague prose).
_VAGUE_REACTIVATION = {"n/a", "na", "pendiente", "pending", "tbd", "todo", "?"}

_VISTA_RAPIDA_HEADER = "## Vista rapida"
_TABLE_HEADER_COLS = (
    "Prioridad",
    "Ticket",
    "Titulo",
    "Scope",
    "Estado",
    "Depende de",
    "Origen",
    "Reactivation",
)
_FICHA_RE = re.compile(r"^### (WOT|WP|WT)-\d{4}-\w+(?:\s+-\s+.+)?$")


def resolve_destino_root(cli_value: str | None) -> tuple[Path | None, str | None]:
    """Resolve the destino root strictly. Returns (root, error).

    Precedence: --project-root, then AGENT_PROJECT_ROOT. NO __file__ fallback:
    a missing root is fail-closed (WOT-2026-012b binary criterion).
    """
    raw = (cli_value or "").strip() or os.environ.get("AGENT_PROJECT_ROOT", "").strip()
    if not raw:
        return None, (
            "fail-closed: no project root. Pass --project-root <repo_destino> or "
            "set AGENT_PROJECT_ROOT. This gate never reads backlog relative to cwd."
        )
    root = Path(raw).resolve()
    if not root.exists():
        return None, f"project root does not exist: {root}"
    return root, None


def _extract_active_table(content: str) -> tuple[list[str], str | None]:
    """Return the data rows of the table under '## Vista rapida'.

    Reads ONLY that table; stops at the next blank line after the table or the
    next header. Never consults HTML comments or prose.
    """
    lines = content.splitlines()
    try:
        start = next(
            i for i, line in enumerate(lines) if line.strip() == _VISTA_RAPIDA_HEADER
        )
    except StopIteration:
        return [], f"missing '{_VISTA_RAPIDA_HEADER}' section"

    # Find the table header row (starts with '| Prioridad').
    header_idx = None
    for i in range(start + 1, len(lines)):
        stripped = lines[i].strip()
        if stripped.startswith("## "):  # next section before any table
            break
        if stripped.startswith("| Prioridad"):
            header_idx = i
            break
    if header_idx is None:
        return [], "no table header found under 'Vista rapida'"

    # Validate header columns.
    header_cells = [c.strip() for c in lines[header_idx].strip().strip("|").split("|")]
    if header_cells != list(_TABLE_HEADER_COLS):
        return [], (
            f"table header columns mismatch: expected {list(_TABLE_HEADER_COLS)}, "
            f"got {header_cells}"
        )

    # Data rows start two lines after the header (skip the |---|---| separator).
    rows: list[str] = []
    for i in range(header_idx + 2, len(lines)):
        stripped = lines[i].strip()
        if not stripped or stripped.startswith("## "):
            break
        if stripped.startswith("|"):
            rows.append(stripped)
    return rows, None


def _validate_reactivation(status: str, reactivation: str) -> str | None:
    """Return an error string for an invalid (status, reactivation) pair."""
    react = reactivation.strip()
    if status in REACTIVATION_REQUIRED:
        if react == "-" or not react:
            return f"status '{status}' requires a structured Reactivation, got '-'"
        if react.lower() in _VAGUE_REACTIVATION:
            return f"vague Reactivation '{react}' for status '{status}'"
        if react.startswith(REACTIVATION_PREFIXES) or _TICKET_TRIGGER_RE.match(react):
            return None
        return (
            f"Reactivation '{react}' for status '{status}' is not structured "
            f"(expected one of {REACTIVATION_PREFIXES} or a ticket id)"
        )
    # Active states without a required trigger: '-' is fine; a structured
    # trigger is also allowed, but vague prose is not.
    if react and react != "-" and react.lower() in _VAGUE_REACTIVATION:
        return f"vague Reactivation '{react}' for status '{status}'"
    return None


def validate_backlog(backlog_path: Path) -> list[str]:
    """Return a list of contract violations (empty == valid)."""
    if not backlog_path.exists():
        return [f"backlog not found: {backlog_path}"]
    content = backlog_path.read_text(encoding="utf-8-sig")

    errors: list[str] = []
    rows, table_error = _extract_active_table(content)
    if table_error:
        return [table_error]
    if not rows:
        return ["active 'Vista rapida' table has no rows"]

    for row in rows:
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        if len(cells) != len(_TABLE_HEADER_COLS):
            errors.append(f"row has {len(cells)} columns, expected 8: {row}")
            continue
        ticket, status, reactivation = cells[1], cells[4], cells[7]
        if status not in LIVE_STATES:
            errors.append(
                f"{ticket}: status '{status}' not in live vocabulary {LIVE_STATES}"
            )
        react_err = _validate_reactivation(status, reactivation)
        if react_err:
            errors.append(f"{ticket}: {react_err}")

    # Validate every ficha header is well formed (### WOT-/WT-...).
    for line in content.splitlines():
        is_ticket_ficha = line.startswith("### ") and (
            "WOT-" in line or "WT-" in line or "WP-" in line
        )
        if is_ticket_ficha and not _FICHA_RE.match(line.rstrip()):
            errors.append(f"malformed ficha header: {line.rstrip()!r}")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail-closed gate for the live backlog contract (WOT-2026-012b)."
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="repo_destino root (or set AGENT_PROJECT_ROOT). No cwd fallback.",
    )
    args = parser.parse_args(argv)

    root, root_error = resolve_destino_root(args.project_root)
    if root_error:
        print(f"[backlog-contract] {root_error}", file=sys.stderr)
        return 2

    backlog = root / ".agent" / "collaboration" / "backlog.md"
    violations = validate_backlog(backlog)
    if violations:
        print(
            f"[backlog-contract] {len(violations)} violation(s) in {backlog}:",
            file=sys.stderr,
        )
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        return 1

    print(f"[backlog-contract] OK: live queue contract holds in {backlog}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
