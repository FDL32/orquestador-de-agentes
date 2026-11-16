"""Detect failed live sessions from the flight registry and the T3 store.

Before: the caller declares a flight directory, a read-only T3 store, and an
operations directory through CLI arguments or the documented environment.
During: this module crosses registry statuses with the latest T3 projection run
and emits deduplicated alert events for active sessions only.
After: the CLI returns the documented status code and never writes the registry
or the T3 store.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


try:
    from scripts.flight import comms_alert
    from scripts.flight.verify_user_authorization import InfraError, open_store_ro
except ModuleNotFoundError:  # Direct CLI execution has scripts/flight as sys.path[0].
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.flight import comms_alert
    from scripts.flight.verify_user_authorization import InfraError, open_store_ro


ACTIVE_PREFIXES = ("ACTIVA", "FALLIDA", "SUPERVISORA", "ENTREGADO")
RUN_FAILURES = frozenset({"failed", "interrupted"})
REGISTRY_NAME = "session_registry.json"
RUNS_TABLE = "orchestration_v2_projection_runs"
THREADS_TABLE = "orchestration_v2_projection_threads"
SUBAGENTS_TABLE = "orchestration_v2_projection_subagents"


def _registry_sessions(path: Path) -> list[dict]:
    """Load and validate the registry sessions.

    Before: ``path`` identifies the declared flight registry.
    During: reads one JSON document and validates the sessions collection.
    After: returns session mappings or raises ValueError with a named cause.
    """
    if not path.is_file():
        raise ValueError("registry-missing")
    try:
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            raise ValueError("registry-empty")
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("registry-truncated") from exc
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"registry-unavailable: {type(exc).__name__}") from exc
    sessions = document.get("sessions") if isinstance(document, dict) else None
    if not isinstance(sessions, list):
        raise ValueError("registry-invalid-type")
    if any(not isinstance(session, dict) for session in sessions):
        raise ValueError("registry-invalid-session")
    return sessions


def _check_schema(connection) -> None:
    """Require the projection columns used by this detector.

    Before: ``connection`` was opened by ``open_store_ro``.
    During: checks table and column names through SQLite PRAGMA.
    After: returns None or raises ValueError with a named schema cause.
    """
    required = {
        RUNS_TABLE: {"thread_id", "status", "ordinal"},
        THREADS_TABLE: {"thread_id", "deleted_at"},
        SUBAGENTS_TABLE: {"child_thread_id"},
    }
    for table, columns in required.items():
        found = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if found is None:
            raise ValueError(f"store-schema-missing-table:{table}")
        actual = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
        missing = columns - actual
        if missing:
            raise ValueError(f"store-schema-missing-column:{table}:{sorted(missing)}")


def _latest_runs(connection) -> dict[str, str]:
    """Return the latest ordinal run status for every thread.

    Before: ``connection`` is a read-only T3 projection connection.
    During: selects rows and keeps the greatest ordinal per thread.
    After: returns only thread ids present in the runs projection.
    """
    latest: dict[str, tuple[int, str]] = {}
    for row in connection.execute(
        f'SELECT thread_id, status, ordinal FROM "{RUNS_TABLE}"'  # noqa: S608
    ):
        thread_id, status, ordinal = row
        if not isinstance(thread_id, str) or not isinstance(status, str):
            raise ValueError("store-row-invalid")
        try:
            ordinal_value = int(ordinal)
        except (TypeError, ValueError) as exc:
            raise ValueError("store-ordinal-invalid") from exc
        if thread_id not in latest or ordinal_value > latest[thread_id][0]:
            latest[thread_id] = (ordinal_value, status.casefold())
    return {thread_id: status for thread_id, (_, status) in latest.items()}


def _is_active(status: object) -> bool:
    """Apply fixture-defined active prefixes without requiring a delimiter.

    Before: ``status`` is free text from the registry.
    During: compares the case-folded status with each active prefix.
    After: returns true when any active prefix starts the status text.
    """
    text = str(status or "").casefold()
    return any(text.startswith(prefix.casefold()) for prefix in ACTIVE_PREFIXES)


def detect(
    flight_dir: Path, store_path: Path, ops_dir: str | None, environ: dict[str, str]
) -> int:
    """Detect live failed sessions and emit their alert keys.

    Before: arguments identify a flight, a T3 SQLite store, and an operations directory.
    During: crosses registry status prefixes with the latest read-only store run.
        It deliberately ignores T3 subagent listings and therefore cannot detect children
        that have no registered ``threadId``. Statuses outside the fixture-defined active
        and terminal sets are also ignored; this is a declared detector boundary.
    After: returns 0 for no keys, 1 for emitted keys, or 2 for a named fail-closed cause.
        A missing flight declaration is handled by the CLI as N/A (rc 3).
    """
    try:
        sessions = _registry_sessions(flight_dir / REGISTRY_NAME)
        connection = open_store_ro(store_path)
        try:
            _check_schema(connection)
            latest = _latest_runs(connection)
        finally:
            connection.close()
        resolved_ops = comms_alert.resolve_ops_dir(ops_dir, environ)
        comms_alert.configure(resolved_ops)
    except (InfraError, comms_alert.OpsDirError, OSError, ValueError) as exc:
        cause = getattr(exc, "cause", str(exc))
        print(f"hilo-failed detector fail-closed: {cause}", file=sys.stderr)
        return 2

    candidates = []
    for session in sessions:
        code = session.get("code") or session.get("session_code")
        thread_id = session.get("threadId")
        if (
            not isinstance(code, str)
            or not code
            or not isinstance(thread_id, str)
            or not thread_id
        ):
            continue
        if _is_active(session.get("status")) and latest.get(thread_id) in RUN_FAILURES:
            candidates.append(code)

    for code in sorted(candidates, key=str.casefold):
        key = f"hilo-failed-{code}"
        try:
            event_rc = comms_alert.event(
                key,
                "URGENTE",
                code,
                "La sesion activa tiene una ultima run failed o interrupted",
                False,
                False,
                owner="hilo_failed_detector",
                session_code=code,
            )
        except Exception as exc:  # event failure is fail-closed infrastructure
            print(
                f"hilo-failed detector fail-closed: alert-unavailable: {exc}",
                file=sys.stderr,
            )
            return 2
        if event_rc not in (0, 10):
            print(
                f"hilo-failed detector fail-closed: alert-unavailable: rc={event_rc}",
                file=sys.stderr,
            )
            return 2
        print(key)
    return 1 if candidates else 0


def main(argv: list[str] | None = None) -> int:
    """Parse the detector CLI and return its documented exit code.

    Before: argv contains optional flight, store, and operations directory arguments.
    During: resolves explicit values before consulting the matching environment variables.
    After: returns rc 3 only when no flight directory was declared, otherwise detect's rc.
    """
    parser = argparse.ArgumentParser(description="Detect failed live flight sessions")
    parser.add_argument("--flight-dir", type=Path, default=None)
    parser.add_argument("--store", type=Path, default=None)
    parser.add_argument("--ops-dir", default=None)
    args = parser.parse_args(argv)
    raw_flight = args.flight_dir or os.environ.get("FLIGHT_DIR")
    if not raw_flight:
        print("hilo-failed detector: flight-dir sin declarar", file=sys.stderr)
        return 3
    store = args.store or Path(
        os.environ.get(
            "T3_STATE_DB", Path.home() / ".t3" / "userdata" / "statev2.sqlite"
        )
    )
    return detect(Path(raw_flight), store, args.ops_dir, dict(os.environ))


if __name__ == "__main__":
    raise SystemExit(main())
