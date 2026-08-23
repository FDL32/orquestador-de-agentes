#!/usr/bin/env python3
"""GSR-subset check for autonomous batch_run reports (WOT-2026-025k).

Contract (WOT-2026-025k): in a `batch_run_<ts>.json` written by the
autonomous ticket batch, `tickets{}` is the CANONICAL index of terminal
states. `group_stop_reports` (GSR) must never reference a ticket ABSENT from
`tickets{}`.

Origin (F1, 2026-07-16): PREDICATE #3 (`contabilidad_completa`) self-declared
PASS while `tickets{}` was incomplete. An auditor re-deriving the universe
SOLELY from `tickets{}` loses any ticket that reached a terminal state only
via a GSR entry -- a silent false green. This check makes that gap explicit
and fails closed.

Second contract (WOT-2026-058t, measured 2026-08-23 on
`FP-20260823-BUS-Y-RECIBO`): the PREDICATE conditions 1/2 (`schema_valido`,
`dag_aciclico`) declared `exit_code: 0` for `validate_batch_dag.py` with the
note "validated pre-execution by the flight plan" while NO DAG-JSON existed
for that flight anywhere in `flight_plans/`. That citation names no
verifiable artifact:
`exit_code: 0` over a command that could never have run is the same false
green family. This script now rejects a batch_run that (i) names a flight in
the `FP-` convention AND (ii) claims conditions 1/2 succeeded (`exit_code:
0`) AND (iii) has no DAG-JSON with a matching stem under `flight_plans/`.
A flight that declares the DAG absent (conditions emitted `N/A`, per the
DoD sin-DAG remedy) does NOT claim 0 and therefore passes: declared absence
is not a verified claim. Historical batch_runs whose `flight` field predates
the `FP-` convention (descriptive text, G-xxxx ids) and reports with no
`flight` field at all are intentionally left unconstrained: the convention
only binds names that opt into it.

Origin scope is deliberately minimal for the GSR part: `tickets` may be a
dict keyed by ticket-id, a list of `{id, ...}` objects, or absent (empty
universe); the check tolerates all three shapes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _ticket_index(payload: dict[str, Any]) -> set[str]:
    """Before: parsed batch_run payload. During: normalize `tickets` (dict keyed
    by id, list of {id,...}, or absent) into a flat id set. After: set of ticket
    ids that count as present in the canonical index (empty if absent/malformed).
    """
    tickets = payload.get("tickets")
    if tickets is None:
        return set()
    if isinstance(tickets, dict):
        return {str(key) for key in tickets}
    if isinstance(tickets, list):
        ids: set[str] = set()
        for entry in tickets:
            if isinstance(entry, dict) and entry.get("id") is not None:
                ids.add(str(entry["id"]))
        return ids
    return set()


def check_batch_run_accounting(batch_run_path: Path) -> list[str]:
    """Before: `batch_run_path` points to an existing batch_run JSON report.
    During: builds the `tickets{}` index (dict|list|absent-tolerant) and scans
    `group_stop_reports` for any `ticket` value missing from that index.
    After: returns the sorted list of orphan ticket ids (empty list = clean).
    Raises OSError/json.JSONDecodeError if the file is unreadable or malformed
    JSON; the caller (CLI) is responsible for surfacing that as a hard failure.
    """
    payload = json.loads(Path(batch_run_path).read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {batch_run_path}")

    index = _ticket_index(payload)
    reports = payload.get("group_stop_reports") or []
    if not isinstance(reports, list):
        reports = []

    orphans: list[str] = []
    for report in reports:
        if not isinstance(report, dict):
            continue
        ticket = report.get("ticket")
        if ticket is None:
            continue
        ticket_str = str(ticket)
        if ticket_str not in index and ticket_str not in orphans:
            orphans.append(ticket_str)
    return orphans


def _flight_name(payload: dict[str, Any]) -> str | None:
    """Batch-run flight citation, or None when absent.

    Before: parsed batch_run payload. During: reads the top-level `flight`
    field, falling back to `start_context_isolation.flight`. After: stripped
    non-empty string or None. Never raises.
    """
    flight = payload.get("flight")
    if not isinstance(flight, str) or not flight.strip():
        isolation = payload.get("start_context_isolation")
        if isinstance(isolation, dict) and isinstance(isolation.get("flight"), str):
            flight = isolation["flight"]
    if isinstance(flight, str) and flight.strip():
        return flight.strip()
    return None


def _predicate_claims_dag(payload: dict[str, Any]) -> bool:
    """True when PREDICATE conditions 1/2 claim `exit_code: 0`.

    Those conditions (`schema_valido`, `dag_aciclico`) are the ones computed
    by `validate_batch_dag.py <dag.json>`; a `0` here is an assertion that a
    DAG WAS validated. `N/A`/absent (the declared sin-DAG remedy) is NOT a
    claim. Never raises; malformed PREDICATE shapes simply do not claim.
    """
    predicate = payload.get("PREDICATE")
    if not isinstance(predicate, dict):
        return False
    for condition in ("schema_valido", "dag_aciclico"):
        entry = predicate.get(condition)
        if isinstance(entry, dict) and entry.get("exit_code") == 0:
            return True
    return False


def _resolve_flight_plans_root(batch_run_path: Path) -> Path | None:
    """Nearest ancestor directory of the report that owns a `flight_plans/`.

    Convention: the DAG-JSON of a flight lives at
    `<destino>/orchestrator_pipeline/flight_plans/`, so the report's own
    ancestor chain is the natural home tree. Returns None when no ancestor
    owns the directory (report inspected outside its tree); the caller then
    skips the flight check rather than guessing a universe.
    """
    try:
        current = Path(batch_run_path).resolve().parent
    except OSError:
        return None
    for _ in range(8):
        candidate = current / "flight_plans"
        if candidate.is_dir():
            return candidate
        if current.parent == current:
            break
        current = current.parent
    return None


def _dag_persisted(base: str, flight_plans_root: Path) -> bool:
    """True when a DAG-JSON matching `base` exists under `flight_plans/`.

    Matches by filename stem (the convention: `<flight>.json`, which the
    whole historical corpus obeys) or, as secondary insurance, by parsed
    top-level `name`/`id` fields. Malformed JSON files are skipped, never
    fatal: a burst of unreadable files must not masquerade as an absent DAG
    nor as a present one.
    """
    for dag in flight_plans_root.rglob("*.json"):
        if dag.stem == base:
            return True
        try:
            data = json.loads(dag.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        if str(data.get("name", "")) == base or str(data.get("id", "")) == base:
            return True
    return False


def check_flight_plan_persisted(
    batch_run_path: Path, flight_plans_root: Path | None = None
) -> list[str]:
    """WOT-2026-058t: reject PREDICATE 1/2 `exit_code: 0` with no DAG-JSON.

    Before: `batch_run_path` points to an existing batch_run JSON report;
    `flight_plans_root` may be the destination's `flight_plans/` directory
    (resolved from the report's ancestor chain when None).
    During: extracts the flight citation; only a `FP-` flight whose PREDICATE
    claims conditions 1/2 succeeded is scrutinized against the tree.
    After: returns finding strings for each non-persisted flight plan (empty
    list = no verified-claim finding). Raises OSError/json.JSONDecodeError/
    ValueError on unreadable or malformed JSON, matching the GSR function.
    """
    payload = json.loads(Path(batch_run_path).read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {batch_run_path}")

    flight = _flight_name(payload)
    if not flight or not flight.startswith("FP-"):
        return []
    if not _predicate_claims_dag(payload):
        return []

    if flight_plans_root is None:
        flight_plans_root = _resolve_flight_plans_root(batch_run_path)
    if flight_plans_root is None:
        return []

    base = flight.split(" (", 1)[0]
    if _dag_persisted(base, Path(flight_plans_root)):
        return []
    return [
        f"PREDICATE condiciones 1/2 citan el flight plan '{flight}' "
        f"(validate_batch_dag.py, exit_code 0) pero no existe DAG-JSON con "
        f"stem '{base}' bajo {flight_plans_root}: exit_code 0 sobre un "
        f"comando que no se pudo ejecutar (WOT-2026-058t)"
    ]


def build_parser() -> argparse.ArgumentParser:
    """Before: none. During: define CLI. After: parser accepting a positional
    path or --file (both resolving to the same batch_run.json target) plus
    an optional --flight-plans-root."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "batch_run",
        nargs="?",
        default=None,
        help="Path to batch_run_<ts>.json (positional).",
    )
    parser.add_argument(
        "--file",
        dest="file",
        default=None,
        help="Path to batch_run_<ts>.json (alternative to the positional arg).",
    )
    parser.add_argument(
        "--flight-plans-root",
        dest="flight_plans_root",
        default=None,
        help=(
            "Path to the destination 'flight_plans/' tree (WOT-2026-058t). "
            "Default: resolved from the report's own ancestor chain."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Before: argv optional. During: resolve target path, run the GSR-subset
    check and the WOT-2026-058t flight-plan-persisted check. After: exit 0 if
    clean on both; exit 1 printing each orphan ticket and/or each unreferenced
    flight plan by name otherwise; exit 2 on missing/invalid path or malformed
    JSON (usage error, not a gate finding)."""
    args = build_parser().parse_args(argv)
    target = args.file or args.batch_run
    if not target:
        print("[check-batch-run-accounting] ERROR: no batch_run path given.")
        return 2

    path = Path(target)
    if not path.exists():
        print(f"[check-batch-run-accounting] ERROR: file not found: {path}")
        return 2

    try:
        orphans = check_batch_run_accounting(path)
        flight_plans_root = (
            Path(args.flight_plans_root) if args.flight_plans_root else None
        )
        plan_findings = check_flight_plan_persisted(path, flight_plans_root)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"[check-batch-run-accounting] ERROR: unreadable/invalid JSON: {exc}")
        return 2

    failures: list[str] = []
    if orphans:
        failures.append(
            "[check-batch-run-accounting] ERROR: orphan GSR ticket(s) "
            "absent from tickets{}:"
        )
        failures.extend(f"    {ticket}" for ticket in orphans)
    if plan_findings:
        failures.append(
            "[check-batch-run-accounting] ERROR: PREDICATE condiciones 1/2 citan "
            "un flight plan que no esta persistido (WOT-2026-058t):"
        )
        failures.extend(f"    {finding}" for finding in plan_findings)

    for line in failures:
        print(line)

    if failures:
        return 1

    print(
        "[check-batch-run-accounting] OK: every GSR ticket is in tickets{} "
        "and every claimed flight plan is persisted."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
