#!/usr/bin/env python3
"""Resolve the current state of an audit report via its append-only event ledger.

WOT-2026-054c: Ledger append-only for audit adjudications.

This module provides a PURE function over files: given a reports directory and
a subject timestamp, it finds the original audit report and all events that
supersede it, validates the chain, and returns the current state.

File naming convention:
  - Original:  audit_autonomous_batch_<ts>.json
  - Events:    audit_autonomous_batch_<ts>.event_<n>.json

The resolver NEVER mutates files. It reads, validates, and returns a result.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


# --- Verdict enum (matches audit_autonomous_ticket_batch.md canonical verdicts) ---

VALID_VERDICTS = frozenset(
    {
        "APROBADO",
        "APROBADO_CON_NITS",
        "CAMBIOS_NECESARIOS",
        "NO_ACEPTAR_TODAVIA",
        "INVALIDADO",
    }
)

# --- Required fields in each event ---

REQUIRED_EVENT_FIELDS = frozenset(
    {
        "event_type",
        "target_artifact",
        "target_sha256",
        "resulting_status",
        "reason",
        "emitted_by",
        "timestamp",
    }
)

OPTIONAL_EVENT_FIELDS = frozenset(
    {
        "supersedes_event",
        "supersedes_artifact",
        "target_json_sha256",
        "challenge_nonce",
    }
)

# --- Result types ---


class LedgerResult:
    """Result of resolving an audit ledger chain."""

    def __init__(
        self,
        *,
        status: str,
        original_path: Path | None = None,
        original_data: dict[str, Any] | None = None,
        current_event_path: Path | None = None,
        current_event_data: dict[str, Any] | None = None,
        chain_length: int = 0,
        errors: list[str] | None = None,
    ) -> None:
        self.status = status
        self.original_path = original_path
        self.original_data = original_data
        self.current_event_path = current_event_path
        self.current_event_data = current_event_data
        self.chain_length = chain_length
        self.errors = errors or []

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"status": self.status, "chain_length": self.chain_length}
        if self.original_path:
            d["original_path"] = str(self.original_path)
        if self.current_event_path:
            d["current_event_path"] = str(self.current_event_path)
        if self.current_event_data:
            verdict = self.current_event_data.get("resulting_status")
            if verdict:
                d["current_verdict"] = verdict
        if self.errors:
            d["errors"] = self.errors
        return d


# --- Helper functions ---


def _compute_sha256(data: dict[str, Any]) -> str:
    """Compute SHA-256 of the JSON-normalized form of a dict."""
    normalized = json.dumps(
        data, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _compute_bytes_sha256(raw_bytes: bytes) -> str:
    """Compute SHA-256 of raw bytes."""
    return hashlib.sha256(raw_bytes).hexdigest()


def _parse_report(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Parse a JSON report with utf-8-sig encoding. Returns (data, error)."""
    try:
        raw = path.read_bytes()
    except OSError as e:
        return None, f"Cannot read {path.name}: {e}"

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        return None, f"Cannot decode {path.name} as utf-8-sig: {e}"

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return None, f"Cannot parse {path.name} as JSON: {e}"

    return data, None


def _validate_event(
    event_data: dict[str, Any],
    expected_target: str,
    previous_bytes_sha256: str,
    previous_json_sha256: str,
) -> list[str]:
    """Validate an event against the chain. Returns list of errors (empty = valid)."""
    errors: list[str] = []

    # Check required fields
    missing = REQUIRED_EVENT_FIELDS - set(event_data.keys())
    if missing:
        errors.append(f"Missing required fields: {sorted(missing)}")

    # Check verdict enum
    verdict = event_data.get("resulting_status", "")
    if verdict not in VALID_VERDICTS:
        errors.append(f"Invalid resulting_status: {verdict!r} (not in enum)")

    # Check target_artifact matches
    target = event_data.get("target_artifact", "")
    if target != expected_target:
        errors.append(
            f"target_artifact {target!r} does not match expected {expected_target!r}"
        )

    # Check supersedes coherence
    supersedes_event = event_data.get("supersedes_event")
    supersedes_artifact = event_data.get("supersedes_artifact")
    if not supersedes_event and not supersedes_artifact:
        errors.append("Neither supersedes_event nor supersedes_artifact present")

    # Check target_sha256 (bytes hash of the file being superseded)
    target_sha256 = event_data.get("target_sha256", "")
    if target_sha256 != previous_bytes_sha256:
        errors.append(
            f"target_sha256 mismatch: got {target_sha256[:16]}..., "
            f"expected {previous_bytes_sha256[:16]}..."
        )

    # Check target_json_sha256 if present
    target_json_sha256 = event_data.get("target_json_sha256")
    if target_json_sha256 and target_json_sha256 != previous_json_sha256:
        errors.append(
            f"target_json_sha256 mismatch: got {target_json_sha256[:16]}..., "
            f"expected {previous_json_sha256[:16]}..."
        )

    return errors


def _extract_ts_from_filename(filename: str) -> str | None:
    """Extract the timestamp portion from an audit filename.

    Matches: audit_autonomous_batch_YYYYMMDD-HHMM.json
    Returns: YYYYMMDD-HHMM or None.
    """
    m = re.match(r"audit_autonomous_batch_(\d{8}-\d{4})", filename)
    return m.group(1) if m else None


def _extract_event_number(filename: str) -> int | None:
    """Extract the event number from an event filename.

    Matches: audit_autonomous_batch_*.event_<n>.json
    Returns: n or None.
    """
    m = re.search(r"\.event_(\d+)\.json$", filename)
    return int(m.group(1)) if m else None


# --- Main resolver ---


def _validate_chain(
    *,
    event_files: list[tuple[int, Path]],
    original_path: Path,
    original_data: dict[str, Any],
    original_pattern: str,
    original_bytes_sha256: str,
    original_json_sha256: str,
) -> LedgerResult:
    """Validate an event chain and return the result."""
    current_bytes_sha256 = original_bytes_sha256
    current_json_sha256 = original_json_sha256
    current_event_path: Path | None = None
    current_event_data: dict[str, Any] | None = None
    errors: list[str] = []

    for i, (num, event_path) in enumerate(event_files):
        expected_num = i + 1
        if num != expected_num:
            errors.append(f"Chain gap: expected event_{expected_num}, got event_{num}")
            return LedgerResult(
                status="INDETERMINADO",
                original_path=original_path,
                original_data=original_data,
                chain_length=i,
                errors=errors,
            )

        event_data, err = _parse_report(event_path)
        if err:
            errors.append(f"Event {num}: {err}")
            return LedgerResult(
                status="INDETERMINADO",
                original_path=original_path,
                original_data=original_data,
                chain_length=i,
                errors=errors,
            )

        event_errors = _validate_event(
            event_data,
            expected_target=original_pattern,
            previous_bytes_sha256=current_bytes_sha256,
            previous_json_sha256=current_json_sha256,
        )

        if event_errors:
            errors.append(f"Event {num} invalid: {'; '.join(event_errors)}")
            return LedgerResult(
                status="INDETERMINADO",
                original_path=original_path,
                original_data=original_data,
                chain_length=i,
                errors=errors,
            )

        event_bytes_sha256 = _compute_bytes_sha256(event_path.read_bytes())
        event_json_sha256 = _compute_sha256(event_data)
        current_bytes_sha256 = event_bytes_sha256
        current_json_sha256 = event_json_sha256
        current_event_path = event_path
        current_event_data = event_data

    return LedgerResult(
        status="SUPERSEDED",
        original_path=original_path,
        original_data=original_data,
        current_event_path=current_event_path,
        current_event_data=current_event_data,
        chain_length=len(event_files),
    )


def resolve_ledger(reports_dir: Path, subject_ts: str) -> LedgerResult:
    """Resolve the current state of an audit ledger for a given subject.

    Args:
        reports_dir: Directory containing the audit reports and events.
        subject_ts: The timestamp portion (e.g. "20260810-2313") identifying
                     the original report.

    Returns:
        LedgerResult with status one of:
          - ORIGINAL: no events, original is current
          - SUPERSEDED: last valid event determines current state
          - INDETERMINADO: chain broken or invalid event encountered
          - NOT_FOUND: original report not found
          - PARSE_ERROR: original or event could not be parsed
    """
    # Find the original report
    original_pattern = f"audit_autonomous_batch_{subject_ts}.json"
    original_path = reports_dir / original_pattern

    if not original_path.exists():
        return LedgerResult(
            status="NOT_FOUND",
            errors=[f"Original report not found: {original_pattern}"],
        )

    # Parse original
    original_data, err = _parse_report(original_path)
    if err:
        return LedgerResult(status="PARSE_ERROR", errors=[err])

    original_bytes_sha256 = _compute_bytes_sha256(original_path.read_bytes())
    original_json_sha256 = _compute_sha256(original_data)

    # Find all events for this subject
    event_files: list[tuple[int, Path]] = []
    for f in reports_dir.iterdir():
        if not f.is_file():
            continue
        if not f.name.startswith(f"audit_autonomous_batch_{subject_ts}.event_"):
            continue
        num = _extract_event_number(f.name)
        if num is not None:
            event_files.append((num, f))

    if not event_files:
        return LedgerResult(
            status="ORIGINAL",
            original_path=original_path,
            original_data=original_data,
            chain_length=0,
        )

    # Sort by event number
    event_files.sort(key=lambda x: x[0])

    # Validate chain
    return _validate_chain(
        event_files=event_files,
        original_path=original_path,
        original_data=original_data,
        original_pattern=original_pattern,
        original_bytes_sha256=original_bytes_sha256,
        original_json_sha256=original_json_sha256,
    )


# --- CLI ---


def main() -> None:
    """CLI entry point for resolve_audit_ledger."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Resolve the current state of an audit ledger chain."
    )
    parser.add_argument(
        "reports_dir",
        help="Directory containing audit reports and events.",
    )
    parser.add_argument(
        "subject_ts",
        help="Timestamp of the original report (e.g. 20260810-2313).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Output result as JSON.",
    )

    args = parser.parse_args()
    reports_path = Path(args.reports_dir)

    result = resolve_ledger(reports_path, args.subject_ts)

    if args.output_json:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(f"Status: {result.status}")
        print(f"Chain length: {result.chain_length}")
        if result.current_event_data:
            verdict = result.current_event_data.get("resulting_status")
            print(f"Current verdict: {verdict}")
        if result.errors:
            print("Errors:")
            for e in result.errors:
                print(f"  - {e}")

    sys.exit(0 if result.status in ("ORIGINAL", "SUPERSEDED") else 1)


if __name__ == "__main__":
    main()
