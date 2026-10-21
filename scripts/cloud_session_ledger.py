#!/usr/bin/env python3
"""Ledger JSONL de sesiones cloud (handoff manual + follow-ups programaticos).

Estados: BUNDLED, LAUNCHED_PENDING_ID, RUNNING, AWAITING_REVIEW, MERGED,
REJECTED, ORPHANED, ABANDONED.

Before: el agente preparo un bundle (`prepare_cloud_bundle.py`) o el humano
    lanzo `claude --cloud`.
During: `record` da de alta una sesion (idempotente por task_id+bundle_sha);
    `update` transiciona el estado; `list` deriva el ultimo estado por tarea y
    marca huerfanas por TTL; `sweep` escribe el evento ORPHANED.
After: el ledger `.agent/runtime/cloud_sessions.jsonl` queda append-only.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


STATUSES = frozenset(
    {
        "BUNDLED",
        "LAUNCHED_PENDING_ID",
        "RUNNING",
        "AWAITING_REVIEW",
        "MERGED",
        "REJECTED",
        "ORPHANED",
        "ABANDONED",
    }
)
OPEN_STATUSES = frozenset({"LAUNCHED_PENDING_ID", "RUNNING", "AWAITING_REVIEW"})
DEFAULT_LEDGER = ".agent/runtime/cloud_sessions.jsonl"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _append(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _latest(records: list[dict]) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for record in records:
        task_id = record.get("task_id")
        if isinstance(task_id, str) and task_id:
            merged = latest.setdefault(task_id, {})
            merged.update(record)
    return latest


def _age_minutes(record: dict) -> float | None:
    ts = _parse_ts(record.get("ts"))
    if ts is None:
        return None
    return max(0.0, (_now() - ts).total_seconds() / 60.0)


def _is_open(status: object) -> bool:
    return status in OPEN_STATUSES


def record(
    path: Path,
    *,
    task_id: str,
    session_id: str,
    url: str,
    commit: str,
    branch: str,
    model: str,
    auth_method: str,
    bundle_sha: str,
) -> int:
    """Alta idempotente por (task_id, bundle_sha)."""
    records = _read(path)
    for existing in records:
        if (
            existing.get("event") == "recorded"
            and existing.get("task_id") == task_id
            and existing.get("bundle_sha") == bundle_sha
        ):
            if session_id and not existing.get("session_id"):
                _append(
                    path,
                    {
                        "ts": _iso(_now()),
                        "event": "updated",
                        "task_id": task_id,
                        "status": "RUNNING",
                        "session_id": session_id,
                        "url": url,
                        "note": "session_id provided after initial record",
                    },
                )
                print(f"[OK] task {task_id}: session_id registrado")
            else:
                print(f"[OK] task {task_id} ya registrada (idempotente)")
            return 0
    status = "RUNNING" if session_id else "LAUNCHED_PENDING_ID"
    _append(
        path,
        {
            "ts": _iso(_now()),
            "event": "recorded",
            "task_id": task_id,
            "session_id": session_id,
            "url": url,
            "commit": commit,
            "branch": branch,
            "model": model,
            "auth_method": auth_method,
            "bundle_sha": bundle_sha,
            "status": status,
        },
    )
    print(f"[OK] task {task_id}: {status}")
    return 0


def update(
    path: Path,
    *,
    task_id: str,
    status: str,
    result_ref: str,
    note: str,
) -> int:
    """Transiciona el estado; valida el enum."""
    if status not in STATUSES:
        print(
            f"[ERROR] status invalido: {status}. Validos: {sorted(STATUSES)}",
            file=sys.stderr,
        )
        return 2
    _append(
        path,
        {
            "ts": _iso(_now()),
            "event": "updated",
            "task_id": task_id,
            "status": status,
            "result_ref": result_ref,
            "note": note,
        },
    )
    print(f"[OK] task {task_id}: {status}")
    return 0


def list_sessions(path: Path, *, ttl_minutes: int) -> int:
    """Lista el ultimo estado por tarea y marca huerfanas por TTL."""
    latest = _latest(_read(path))
    rows = []
    for task_id, entry in sorted(latest.items()):
        age = _age_minutes(entry)
        orphan = bool(
            age is not None and age > ttl_minutes and _is_open(entry.get("status"))
        )
        rows.append(
            {
                "task_id": task_id,
                "status": entry.get("status"),
                "session_id": entry.get("session_id", ""),
                "branch": entry.get("branch", ""),
                "age_minutes": round(age, 1) if age is not None else None,
                "orphan": orphan,
            }
        )
    print(json.dumps(rows, indent=2, ensure_ascii=False))
    return 0


def sweep(path: Path, *, ttl_minutes: int) -> int:
    """Marca ORPHANED las tareas abiertas cuyo ultimo evento supera el TTL."""
    latest = _latest(_read(path))
    count = 0
    for task_id, entry in latest.items():
        age = _age_minutes(entry)
        if age is not None and age > ttl_minutes and _is_open(entry.get("status")):
            _append(
                path,
                {
                    "ts": _iso(_now()),
                    "event": "updated",
                    "task_id": task_id,
                    "status": "ORPHANED",
                    "note": f"TTL {ttl_minutes}m excedido",
                },
            )
            count += 1
    print(f"[OK] {count} tarea(s) marcadas ORPHANED")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", default=DEFAULT_LEDGER)
    sub = parser.add_subparsers(dest="command", required=True)

    rec = sub.add_parser("record")
    rec.add_argument("--task-id", required=True)
    rec.add_argument("--session-id", default="")
    rec.add_argument("--url", default="")
    rec.add_argument("--commit", default="")
    rec.add_argument("--branch", default="")
    rec.add_argument("--model", default="sonnet")
    rec.add_argument("--auth-method", default="oauth")
    rec.add_argument("--bundle-sha", default="")

    upd = sub.add_parser("update")
    upd.add_argument("--task-id", required=True)
    upd.add_argument("--status", required=True)
    upd.add_argument("--result-ref", default="")
    upd.add_argument("--note", default="")

    lst = sub.add_parser("list")
    lst.add_argument("--ttl-minutes", type=int, default=120)

    swp = sub.add_parser("sweep")
    swp.add_argument("--ttl-minutes", type=int, default=120)

    args = parser.parse_args(argv)
    path = Path(args.ledger)
    if args.command == "record":
        return record(
            path,
            task_id=args.task_id,
            session_id=args.session_id,
            url=args.url,
            commit=args.commit,
            branch=args.branch,
            model=args.model,
            auth_method=args.auth_method,
            bundle_sha=args.bundle_sha,
        )
    if args.command == "update":
        return update(
            path,
            task_id=args.task_id,
            status=args.status,
            result_ref=args.result_ref,
            note=args.note,
        )
    if args.command == "list":
        return list_sessions(path, ttl_minutes=args.ttl_minutes)
    if args.command == "sweep":
        return sweep(path, ttl_minutes=args.ttl_minutes)
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
