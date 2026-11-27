#!/usr/bin/env python3
"""Detect coordinator inactivity after a measured rotation.

Before: the heartbeat supplies explicit flight, operations, and backlog paths.
During: read the roster and registry, evaluate the seven-minute post-ACK
    window, and use the shared alert ledger for one post-relevo key.
After: return 0 when clean or unevaluated, 1 when a condition is active, and
    2 when an input or alert operation cannot be measured safely.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


_role_key_load_error: Exception | None = None
try:
    _role_key_path = (
        Path(__file__).resolve().with_name("roster_role_key.py")
    ).resolve()
    _role_key_name = "_flt_roster_role_key_" + str(_role_key_path).replace(
        "\\", "_"
    ).replace(":", "_")
    _role_key_spec = importlib.util.spec_from_file_location(
        _role_key_name, _role_key_path
    )
    if _role_key_spec is None or _role_key_spec.loader is None:
        raise ImportError("no se pudo cargar roster_role_key.py")
    _role_key_module = importlib.util.module_from_spec(_role_key_spec)
    _role_key_spec.loader.exec_module(_role_key_module)
    RosterRoleKeyError = _role_key_module.RosterRoleKeyError
    orchestrator_entry = _role_key_module.orchestrator_entry
    resolve_orchestrator_role = _role_key_module.resolve_orchestrator_role
    set_orchestrator_entry = _role_key_module.set_orchestrator_entry
except Exception as _role_key_exc:
    _role_key_load_error = _role_key_exc

    class RosterRoleKeyError(ValueError):
        """Fallback resolver error for an isolated FLT copy."""

    def orchestrator_entry(_roles, _error=_role_key_exc):
        raise RosterRoleKeyError("roster_role_key.py no disponible") from _error

    def resolve_orchestrator_role(_roles, _error=_role_key_exc):
        raise RosterRoleKeyError("roster_role_key.py no disponible") from _error

    def set_orchestrator_entry(_roles, _entry, _error=_role_key_exc):
        raise RosterRoleKeyError("roster_role_key.py no disponible") from _error


ACK_RE = re.compile(r"ACTIVA\s*\(ACK medido\s+(?P<ts>[^)]+)\)")
STATE_NAME = "post_relevo_state.json"
_CO_CURRENT_STATUS_PREFIXES = ("ACTIVA", "SUPERVISORA", "FALLIDA", "ENTREGADO")
_CO_SETTLED_STATUS_MARKERS = (
    "ASENTADA",
    "SETTLED",
    "CASCADA ASENTADA",
)


@dataclass(frozen=True)
class CheckResult:
    """The observable result of one detector tick."""

    rc: int
    message: str
    reasons: tuple[str, ...] = ()


def _load_json(path: Path) -> dict:
    """Read one JSON object from an explicit flight path.

    Before: path identifies a required roster or registry file.
    During: decode UTF-8 JSON and validate the top-level object.
    After: return the object or raise a measurement error.
    """
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path.name}")
    return value


def _parse_ts(value: object) -> datetime | None:
    """Parse an ISO timestamp while accepting a trailing Z.

    Before: value is a registry timestamp candidate.
    During: normalize UTC notation and parse an aware datetime.
    After: return a datetime or None for a missing or invalid marker.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.astimezone()


def _session(registry: dict, code: str) -> dict | None:
    """Find one registry session by its stable code."""
    for item in registry.get("sessions", []):
        if isinstance(item, dict) and item.get("code") == code:
            return item
    return None


def _active_marker(session: dict) -> tuple[datetime | None, datetime | None]:
    """Read the explicit deadline or derive it from the measured ACK marker.

    Before: session is the incoming coordinator registry row.
    During: prefer phase-B fields and fall back to ``ACK medido`` history.
    After: return ``(active_ts, deadline)``; both are None when unmeasurable.
    """
    deadline = _parse_ts(session.get("post_relevo_plazo"))
    active = _parse_ts(session.get("activo_ts"))
    if deadline is not None:
        return active or deadline - timedelta(minutes=7), deadline
    match = ACK_RE.search(str(session.get("status", "")))
    ack = _parse_ts(match.group("ts")) if match else None
    return (ack, ack + timedelta(minutes=7)) if ack else (None, None)


def _load_sibling(name: str):
    """Load a read-only sibling flight module by path."""
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(name[:-3], path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _alert(
    key: str,
    message: str,
    ops_dir: Path,
    session_code: str,
    *,
    level: str = "URGENTE",
) -> int:
    """Emit one alert through comms_alert and preserve its ledger contract.

    Before: ops_dir is the explicit heartbeat operations directory.
    During: configure the shared alert module and emit an URGENTE event.
    After: return the shared rc, translating unexpected errors to rc 2.
    """
    try:
        alerts = _load_sibling("comms_alert.py")
        alerts.configure(str(ops_dir))
        return alerts.event(
            key,
            level,
            "Post-relevo",
            message,
            False,
            False,
            owner="post_relevo",
            session_code=session_code,
        )
    except (OSError, ValueError, ImportError, AttributeError) as exc:
        print(f"post-relevo alerta rota: {exc}")
        return 2


def _resolve(key: str, ops_dir: Path) -> int:
    """Resolve one shared alert key and record the resolution in the ledger.

    Before: the shared comms alert state contains the detector key.
    During: call only public comms_alert APIs and append a nine-field resolution row.
    After: return the shared resolution rc; no private comms implementation is used.
    """
    try:
        alerts = _load_sibling("comms_alert.py")
        alerts.configure(str(ops_dir))
        rc = alerts.resolve(key)
        if rc == 0:
            alerts.ledger_append(
                {
                    "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "by": "post_relevo",
                    "a": key,
                    "modo": "heartbeat",
                    "resultado": "RESOLVED",
                    "error": "",
                    "providerInstanceId": "",
                    "mensaje_id": f"post_relevo:{uuid.uuid4()}",
                    "nota": "post-relevo condition resolved",
                }
            )
        return rc
    except (OSError, ValueError, ImportError, AttributeError) as exc:
        print(f"post-relevo resolucion rota: {exc}")
        return 2


def _read_state(path: Path) -> dict:
    """Read or initialize the detector-owned state file."""
    if not path.exists():
        return {"active": []}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("active", []), list):
        raise ValueError("post_relevo_state.json invalido")
    return value


def _write_state(path: Path, state: dict) -> None:
    """Persist detector state safely inside the explicit operations path."""
    data = (json.dumps(state, indent=2) + "\n").encode("utf-8")
    fd, temporary = tempfile.mkstemp(
        prefix=f"{path.stem}-", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def _created_after(sessions: list[dict], active: datetime, incoming: str) -> int:
    """Count IM/TR sessions created after active with the canonical parent field."""
    count = 0
    for item in sessions:
        if item.get("role") not in ("implantacion", "triaje"):
            continue
        if item.get("reporta_a") != incoming:
            continue
        started = _parse_ts(item.get("started"))
        if started is not None and started > active:
            count += 1
    return count


def _apta_unclaimed(backlog: Path, registry_path: Path) -> bool:
    """Return whether cola_apta exposes an eligible unbriefed ticket."""
    checker = _load_sibling("cola_apta.py")
    decisions = checker.cola_apta(backlog, registry_path, backlog.parent)
    return any(item.get("apta") and not item.get("tiene_brief") for item in decisions)


def _co_outside_triad(  # noqa: C901 - triad/status classification mirrors contract clauses
    sessions: list[dict],
    roles: object,
    cadena_contexto: object = None,
    settled=None,
) -> list[str]:
    """Return current coordinator rows whose identity is outside the active triad.

    Before: ``sessions`` is the validated registry list and ``roles`` is the roster
        active-role mapping.
    During: collect session-code and thread-id identities from all active roles,
        add the readable context head when no explicit ancestor exists, then
        select current CO rows whose T3 thread is not settled.
    After: return deterministic coordinator codes without mutating either input.
    """

    if settled is None and callable(cadena_contexto):
        settled = cadena_contexto
        cadena_contexto = None

    def is_current_status(value: object) -> bool:
        """Classify only explicitly current CO status vocabulary."""
        status = str(value or "").strip().upper()
        if not status or any(marker in status for marker in _CO_SETTLED_STATUS_MARKERS):
            return False
        return status.startswith(_CO_CURRENT_STATUS_PREFIXES) or (
            "CASCADA DE CONTEXTO" in status
        )

    triad = set()
    if isinstance(roles, dict):
        for role in roles.values():
            if isinstance(role, dict):
                for field in ("session_code", "threadId"):
                    value = role.get(field)
                    if isinstance(value, str) and value.strip():
                        triad.add(value)
        if "ancestro_directo" in roles:
            ancestor = roles["ancestro_directo"]
            if (
                not isinstance(ancestor, dict)
                or not isinstance(ancestor.get("threadId"), str)
                or not ancestor["threadId"].strip()
                or not isinstance(ancestor.get("session_code"), str)
                or not ancestor["session_code"].strip()
            ):
                raise ValueError("roster no medido")
        elif cadena_contexto not in (None, []):
            if not isinstance(cadena_contexto, list) or not cadena_contexto:
                raise ValueError("roster no medido")
            ancestor = cadena_contexto[0]
            if (
                not isinstance(ancestor, dict)
                or not isinstance(ancestor.get("threadId"), str)
                or not ancestor["threadId"].strip()
                or not isinstance(ancestor.get("session_code"), str)
                or not ancestor["session_code"].strip()
            ):
                raise ValueError("roster no medido")
            triad.update(
                {
                    ancestor["threadId"].strip(),
                    ancestor["session_code"].strip(),
                }
            )
    if settled is None:
        raise ValueError("store T3 no medido")
    candidates = []
    for session in sessions:
        code = session.get("code")
        if not isinstance(code, str) or not code.startswith("CO-"):
            continue
        if not is_current_status(session.get("status")):
            continue
        if code in triad or session.get("threadId") in triad:
            continue
        if settled(session.get("threadId")):
            continue
        candidates.append(code)
    return sorted(set(candidates))


def _reproduction_command(
    flight_dir: Path,
    ops_dir: Path,
    backlog: Path,
    observed: datetime,
    store: Path,
) -> str:
    """Build the literal command needed to reproduce an alerting tick."""
    return (
        "python scripts/flight/post_relevo_check.py"
        f" --flight-dir {flight_dir} --ops-dir {ops_dir} --backlog {backlog}"
        f" --store {store}"
        f" --now {observed.isoformat()}"
    )


def evaluate(  # noqa: C901 - detector branches mirror contract clauses
    flight_dir: Path,
    ops_dir: Path,
    backlog: Path,
    *,
    now: str | None = None,
    store: Path | None = None,
) -> CheckResult:
    """Evaluate one post-rotation heartbeat using only explicit input routes.

    Before: all three paths are supplied by the heartbeat and are readable.
    During: evaluate the deadline, read T3 settlement state, and measure the
        live IM count, reporta_a creations, APTA, and P24.
    After: update detector state and return a stable rc/message result.
    """
    try:
        roster = _load_json(flight_dir / "flight_roster.json")
        registry_path = flight_dir / "session_registry.json"
        registry = _load_json(registry_path)
        sessions = registry.get("sessions")
        if not isinstance(sessions, list) or not all(
            isinstance(item, dict) for item in sessions
        ):
            raise ValueError("registry sessions ilegible")
        incoming_entry = orchestrator_entry(roster["active_roles"])
        if (
            not isinstance(incoming_entry, dict)
            or not isinstance(incoming_entry.get("session_code"), str)
            or not incoming_entry["session_code"].strip()
        ):
            raise ValueError("coordinadora ausente en active_roles")
        incoming = incoming_entry["session_code"]
        session = _session(registry, incoming)
        if session is None:
            raise ValueError(f"entrante ausente: {incoming}")
        active, deadline = _active_marker(session)
        if active is None or deadline is None:
            return CheckResult(0, "NO EVALUADO: no hay activo_ts ni ACK medido")
        observed = _parse_ts(now) if now is not None else datetime.now().astimezone()
        if observed is None:
            raise ValueError("--now invalido")
        key = f"post-relevo-{incoming}"
        state_path = ops_dir / STATE_NAME
        state = _read_state(state_path)
        active_keys = set(state.get("active", []))
        if observed < deadline:
            return CheckResult(
                0, f"NO EVALUADO: plazo activo hasta {deadline.isoformat()}"
            )
        store_path = Path(
            store
            if store is not None
            else os.environ.get(
                "T3_STATE_DB", Path.home() / ".t3" / "userdata" / "statev2.sqlite"
            )
        )
        checker = _load_sibling("check_cell_conformance.py")
        connection = None
        try:
            connection, _, settled = checker._store_lookup(store_path)
        except Exception as exc:
            return CheckResult(2, f"ERROR: store T3 no medido: {exc}")
        live_ims = sum(
            item.get("role") == "implantacion" and checker.is_activa(item.get("status"))
            for item in sessions
        )
        created = _created_after(sessions, active, incoming)
        reasons = []
        if live_ims < 2:
            reasons.append(f"menos de 2 IM vivos ({live_ims})")
        if created == 0:
            reasons.append("sin IM/TR creados tras el ACTIVO con reporta_a")
        if _apta_unclaimed(backlog, registry_path):
            reasons.append("ficha APTA sin brief")
        try:
            co_candidates = _co_outside_triad(
                sessions,
                roster.get("active_roles"),
                roster.get("cadena_contexto"),
                settled,
            )
        except ValueError:
            raise
        except Exception as exc:
            return CheckResult(2, f"ERROR: store T3 no medido: {exc}")
        finally:
            if connection is not None:
                connection.close()
        if co_candidates:
            reasons.append(
                "CO asentable fuera de la terna: " + ", ".join(co_candidates)
            )
        p24_key = f"{key}-p24"
        alert_items = []
        base_reasons = [
            reason
            for reason in reasons
            if not reason.startswith("CO asentable fuera de la terna:")
        ]
        if base_reasons:
            alert_items.append((key, "; ".join(base_reasons)))
        alert_items.extend(
            [(p24_key, "CO asentable fuera de la terna: " + ", ".join(co_candidates))]
            if co_candidates
            else []
        )
        live_keys = {item_key for item_key, _ in alert_items}
        owned_keys = {
            item_key
            for item_key in active_keys
            if item_key in (key, p24_key) or item_key.startswith(f"{p24_key}-")
        }
        for stale_key in sorted(owned_keys - live_keys):
            rc = _resolve(stale_key, ops_dir)
            if rc not in (0, 10):
                return CheckResult(2, "ERROR: no se pudo resolver alerta")
            active_keys.discard(stale_key)
        if not alert_items:
            state["active"] = sorted(active_keys)
            if owned_keys:
                _write_state(state_path, state)
            return CheckResult(0, "OK: relevo atendido")
        command = _reproduction_command(
            flight_dir, ops_dir, backlog, observed, store_path
        )
        for alert_key, alert_reason in alert_items:
            message = f"{incoming}: {alert_reason}"
            rc = _alert(alert_key, message, ops_dir, incoming)
            if rc not in (0, 10):
                return CheckResult(
                    2,
                    f"ERROR: {alert_key}; {message}; comando: {command}",
                    tuple(reasons),
                )
            active_keys.add(alert_key)
        state["active"] = sorted(active_keys)
        _write_state(state_path, state)
        messages = " | ".join(
            f"{incoming}: {alert_reason}" for _, alert_reason in alert_items
        )
        return CheckResult(
            1,
            f"{key}; " + "; ".join(reasons) + f"; {messages}; comando: {command}",
            tuple(reasons),
        )
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        ImportError,
        AttributeError,
    ) as exc:
        return CheckResult(2, f"ERROR: post-relevo no medible: {exc}")


def main(argv=None) -> int:
    """Run the explicit three-route command-line detector.

    Before: the heartbeat passes flight, operations, and backlog paths.
    During: evaluate once and print the stable result message.
    After: return the detector rc, resolving an optional ``--store`` first and
        otherwise using ``T3_STATE_DB`` or the default T3 statev2 path.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--flight-dir", required=True)
    parser.add_argument("--ops-dir", required=True)
    parser.add_argument("--backlog", required=True)
    parser.add_argument("--now", help="test clock hook; heartbeat omits it")
    parser.add_argument("--store", help="optional read-only T3 state store")
    args = parser.parse_args(argv)
    result = evaluate(
        Path(args.flight_dir),
        Path(args.ops_dir),
        Path(args.backlog),
        now=args.now,
        store=Path(args.store) if args.store else None,
    )
    print(result.message)
    return result.rc


if __name__ == "__main__":
    raise SystemExit(main())
