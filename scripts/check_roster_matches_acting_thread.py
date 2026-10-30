#!/usr/bin/env python3
"""WOT-2026-136c: guard que detecta que `active_roles` del roster no coincide
con el hilo que actua (relevo sin registrar pasa el cierre).

Contexto (medido, no relatado): un relevo de orquestador que ocurrio en
``session_registry.json`` sin que ``flight_roster.json`` se actualizara,
o un roster internamente inconsistente, pasan el cierre de sesion porque
nada verifica que el roster y el registry estan sincronizados.

Antes: ``--roster-path`` o ``FLIGHT_ROSTER_PATH`` resuelven un roster de
vuelo; ``--acting-thread`` dice quién actua; ``--registry-path`` el registro.
During: lee el roster, el registro y (para la comprobacion b) los cambios;
       ejecuta las 6 comprobaciones (a)-(f); solo lectura, no muta nada.
After:  exit 0 = PASS (sin violaciones); exit 1 = FAIL (violacion encontrada);
        exit 3 = N/A (no hay roster que comprobar). Cada violacion se nombra
        con su checkpoint (a)-(f) y se imprime por stdout.

Contrato de estados (3, nunca texto):
  0 -> PASS: roster y acting_thread presentes y sin violaciones.
  1 -> FAIL: roster presente pero se encontro una violacion, o
             --acting-thread no suministrado (fail-cerrado por identidad).
  3 -> N/A: ni roster flag ni FLIGHT_ROSTER_PATH resuelven una ruta.
"""

from __future__ import annotations

import argparse

# --- Shared module for mcp: prefix validation (WOT-2026-136h) ---
# Import thread_id by path so the AST of import-statement matching reaches it.
# Registers the module in sys.modules before exec_module and always removes it after.
import importlib.util
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


_THREAD_ID_PATH = Path(__file__).resolve().parent / "flight" / "thread_id.py"
_thread_id_module: object | None = None
_thread_id_load_error: Exception | None = None
try:
    _thread_id_spec = importlib.util.spec_from_file_location(
        "thread_id", _THREAD_ID_PATH
    )
    _thread_id_candidate = importlib.util.module_from_spec(_thread_id_spec)
    sys.modules["thread_id"] = _thread_id_candidate
    _thread_id_spec.loader.exec_module(_thread_id_candidate)
    if not callable(getattr(_thread_id_candidate, "has_mcp_prefix", None)):
        raise ImportError("thread_id.py no define has_mcp_prefix")
    # Published only after a COMPLETE load: a failed load leaves it None.
    _thread_id_module = _thread_id_candidate
except Exception as _exc:  # any load failure must fail closed, never a Traceback
    _thread_id_load_error = _exc
finally:
    sys.modules.pop("thread_id", None)


# Mapa canonico entre nombres de rol del roster y los de session_registry.json.
# Fuente unica de nombres: un renombrado futuro (p.ej. "orquestador"->"coordinador")
# solo requiere editar esta linea.
# WOT-2026-136f: "supervisor" eliminado del mapeo canonico porque su threadId
# se valida mediante check_identity_e y el helper supervisor_esperado, no via
# session_registry.json (el supervisor no tiene entrada ACTIVA en el registry).
_ROSTER_TO_REGISTRY_ROLE: dict[str, str] = {
    "orquestador": "orquestadora",
}

# DEFAULT_ROLE se deriva del propio mapa (la primera clave), nunca un literal.
DEFAULT_ROLE: str = next(iter(_ROSTER_TO_REGISTRY_ROLE))

# Regex de prefijo ACTIVA: captura estados que EMPIEZAN por "ACTIVA" seguido de
# fin de cadena o espacio. NUNCA == estricto (subcuenta multi-ocupacion) ni
# un "in" suelto (falso positivo contra "SUPERSEDED (... estaba ACTIVA ...)").
_RE_ACTIVA_PREFIX: re.Pattern[str] = re.compile(r"^ACTIVA(\s|$)")


# --- Private helpers ---


def _to_utc_aware(dt: datetime) -> datetime:
    """Convert a datetime to UTC-aware.

    Naive datetimes are treated as UTC. Aware datetimes are converted to UTC.

    Before: dt is a datetime (naive or aware).
    During: if tzinfo is None, replaces with UTC; otherwise converts via astimezone.
    After: returns a timezone-aware datetime in UTC.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_ts(ts: str) -> datetime | None:
    """Parse timestamp string, normalizing trailing 'Z' to '+00:00'.

    Before: ts is a non-empty string (possibly ending with 'Z' or '+HH:MM').
    During: tries ``datetime.fromisoformat`` after Z-normalization.
    After: returns a timezone-aware datetime or None on failure.
    """
    if not ts:
        return None
    normalized = ts if not ts.endswith("Z") else ts[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(normalized)
    except (ValueError, TypeError):
        return None


def _find_latest_activa(sessions: list[dict], role: str) -> dict | None:
    """Find the most recent ACTIVA session entry for a given role.

    Filters out entries with started=None and entries whose status does NOT
    start with the ACTIVA prefix. Among the survivors, picks the one with the
    latest parsed started timestamp.

    Before: sessions is a list of session dicts; role is the registry role name.
    During: filters by role and ACTIVA prefix, parses timestamps, picks latest.
    After: returns the dict of the latest ACTIVA entry, or None if none match.
    """
    candidates: list[dict] = []
    for entry in sessions:
        if entry.get("role") != role:
            continue
        if entry.get("started") is None:
            continue
        status = entry.get("status", "")
        if not _RE_ACTIVA_PREFIX.match(status):
            continue
        candidates.append(entry)

    if not candidates:
        return None

    def _sort_key(entry: dict) -> datetime | None:
        raw = _parse_ts(entry.get("started", ""))
        if raw is not None:
            return _to_utc_aware(raw)
        return None

    # Filter out entries that couldn't be parsed (keep parseable ones)
    parseable = [(e, _sort_key(e)) for e in candidates]
    parseable_dt = [(e, dt) for e, dt in parseable if dt is not None]

    if not parseable_dt:
        return None

    return max(parseable_dt, key=lambda x: x[1])[0]


def _read_json_safe(path: Path) -> dict | list | None:
    """Read and parse a JSON file, returning None on any error.

    Before: path is a Path (may or may not exist).
    During: reads with utf-8 encoding, parses JSON.
    After: returns parsed dict/list or None on error.
    """
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _find_latest_canonical_transition(
    changes_log: Path,
    role: str,
    transition_detail: str,
) -> datetime | None:
    """Find the latest canonical change line matching a transition for a role.

    Only considers canonical schema lines (keys: by, change, detail, reason, ts).
    Legacy lines (por, cambio, motivo) are IGNORED (never raise KeyError).

    Before: changes_log points to a roster_changes.jsonl file.
    During: reads each line, checks for canonical schema, filters by role and
            transition detail, parses ts.
    After: returns the latest matching datetime, or None if no match found.

    The transition_detail is expected to contain 'role=<role> ACTIVO -> PENDIENTE_ACK'
    as produced by the flight roster writer (e.g., 'role=orquestador ACTIVO -> PENDIENTE_ACK').
    """
    if not changes_log.exists():
        return None

    latest: datetime | None = None
    text = changes_log.read_text(encoding="utf-8")
    for line_raw in text.splitlines():
        line_raw = line_raw.strip()
        if not line_raw:
            continue
        try:
            entry = json.loads(line_raw)
        except (json.JSONDecodeError, ValueError):
            continue

        # Only canonical schema (has 'by'/'change'/'detail'/'reason'/'ts')
        if not all(k in entry for k in ("by", "change", "detail", "reason", "ts")):
            continue

        if entry.get("change") != "estado_transition":
            continue

        if transition_detail not in entry.get("detail", ""):
            continue

        dt = _parse_ts(entry.get("ts", ""))
        if dt is None:
            # Unparseable ts in canonical line -> fail-closed (return it, caller decides)
            return dt  # type: ignore[return-value]

        dt_aware = _to_utc_aware(dt)
        if latest is None or dt_aware > _to_utc_aware(latest):
            latest = dt_aware

    return latest


# --- Violation checkers ---


def check_identity(active_roles: dict, role: str, acting_thread: str) -> list[str]:
    """Checkpoint (a): roster threadId matches acting_thread.

    After: returns list of violation strings (empty if clean).
    """
    if not isinstance(active_roles, dict):
        return [f"(a) rol '{role}' ausente en active_roles: identidad no verificable"]
    role_entry = active_roles.get(role)
    if role_entry is None:
        return [f"(a) rol '{role}' ausente en active_roles: identidad no verificable"]
    if not isinstance(role_entry, dict):
        return [
            f"(a) rol '{role}' en active_roles no es un mapping: "
            f"identidad no verificable"
        ]
    roster_thread = role_entry.get("threadId", "")
    if roster_thread != acting_thread:
        return [
            f"(a) identidad: roster['active_roles']['{role}']['threadId'] "
            f"'{roster_thread}' != acting_thread '{acting_thread}'"
        ]
    return []


def check_pendiente_ack(
    active_roles: dict,
    role: str,
    changes_log: Path,
) -> list[str]:
    """Checkpoint (b): stale or unexplained PENDIENTE_ACK.

    Before: active_roles[role] is a dict (caller must have checked type).
    During: checks estado=='PENDIENTE_ACK', looks for canonical transition lines.
    After: returns list of violation strings (empty if clean).

    Extension NO literal del DoD (aceptada): si NO hay ninguna linea
    canonica que explique el estado, se trata tambien como violacion.
    """
    role_entry = active_roles.get(role)
    if role_entry is None:
        return []

    estado = role_entry.get("estado")
    if estado != "PENDIENTE_ACK":
        return []

    # Session code (for identifying the transition)
    session_code = role_entry.get("session_code", "")

    # Build the expected transition detail pattern
    # The canonical line from the writer has 'detail' like 'role=<role> ACTIVO -> PENDIENTE_ACK'
    transition_detail = f"role={role} ACTIVO -> PENDIENTE_ACK"

    dt = _find_latest_canonical_transition(changes_log, role, transition_detail)

    if dt is None:
        # No canonical line found (or line with unparseable ts) -> violation
        return [
            f"(b) PENDIENTE_ACK sin linea canonica verificable "
            f"(fail-closed): active_roles['{role}']['estado']='PENDIENTE_ACK'"
        ]

    # Check if ts is older than 15 minutes
    now = datetime.now(timezone.utc)
    # Normalize dt to UTC for comparison (naive timestamps treated as UTC)
    dt_utc = _to_utc_aware(dt)
    elapsed = now - dt_utc
    elapsed_secs = elapsed.total_seconds()
    if elapsed_secs > 900:
        return [
            f"(b) PENDIENTE_ACK caducado: transicion a {session_code} con ts={dt.isoformat()}, "
            f"transcurridos {int(elapsed_secs)}s (> 900s)"
        ]

    return []


def check_double_activa(sessions: list[dict], singleton_roles: set[str]) -> list[str]:
    """Checkpoint (c): multiple ACTIVA entries for singleton roles.

    Before: singleton_roles is derived from _ROSTER_TO_REGISTRY_ROLE values.
    During: groups by role, counts ACTIVA matches with prefix regex.
    After: returns list of violation strings (empty if clean).
    """
    violations: list[str] = []
    for role in singleton_roles:
        activa_count = 0
        for entry in sessions:
            if entry.get("role") != role:
                continue
            status = entry.get("status", "")
            if _RE_ACTIVA_PREFIX.match(status):
                activa_count += 1
        if activa_count >= 2:
            violations.append(
                f"(c) doble ACTIVA para rol singleton '{role}': {activa_count} entradas"
            )
    return violations


def check_roster_outdated(
    sessions: list[dict],
    active_roles: dict,
    roster_to_registry: dict[str, str],
) -> tuple[list[str], list[str]]:
    """Checkpoint (d): roster outdated after a declared relieves.

    Before: sessions from registry; active_roles from roster.
    During: maps roster role to registry role, finds latest ACTIVA entry,
            compares threadId.
    After: returns (violations, notes) tuple. Omission notes do NOT cause FAIL.
    """
    violations: list[str] = []
    notes: list[str] = []

    for roster_role, registry_role in roster_to_registry.items():
        role_entry = active_roles.get(roster_role)
        if role_entry is None:
            notes.append(f"rol '{roster_role}' no mapeado en active_roles, (d) omitida")
            continue

        latest_activa = _find_latest_activa(sessions, registry_role)

        if latest_activa is None:
            notes.append(
                f"(d) rol '{roster_role}': ninguna entrada ACTIVA en registry "
                f"(registry role '{registry_role}'); omission declarada"
            )
            continue

        roster_thread = role_entry.get("threadId", "")
        registry_thread = latest_activa.get("threadId", "")

        if roster_thread != registry_thread:
            violations.append(
                f"(d) roster desactualizado tras relevo: "
                f"active_roles['{roster_role}']['threadId']='{roster_thread}' "
                f"vs registry '{registry_role}' ACTIVA threadId='{registry_thread}'"
            )

    return violations, notes


# --- Main ---


def find_violations(  # noqa: C901
    roster_path: Path,
    acting_thread: str,
    registry_path: Path,
    changes_log: Path,
    role: str,
) -> tuple[list[str], list[str]]:
    """Run all 4 checkpoints and return (violations, notes).

    Empty violations list = clean (all checks pass).
    Non-empty = violations found (exit code 1).
    notes from (d) do NOT cause FAIL exit code.
    """
    roster = _read_json_safe(roster_path)
    registry = _read_json_safe(registry_path)

    if roster is None or not isinstance(roster, dict):
        return [f"no se pudo parsear el roster: {roster_path}"], []

    active_roles = roster.get("active_roles", {})
    if registry is None or not isinstance(registry, dict):
        violations = check_identity(active_roles, role, acting_thread)
        if violations:
            return violations, []
        return ["no se pudo parsear el registro"], []

    sessions = registry.get("sessions", [])

    violations: list[str] = []
    notes: list[str] = []

    # (a) Identity
    violations.extend(check_identity(active_roles, role, acting_thread))

    # (b) PENDIENTE_ACK caducado - MUST filter non-dict entries first
    # active_roles may contain non-mapping entries (e.g., _schema_note as string)
    # active_roles itself may be None if roster has "active_roles": null
    if isinstance(active_roles, dict):
        for check_role, check_entry in active_roles.items():
            if not isinstance(check_entry, dict):
                continue  # Skip strings, None, etc. (e.g., _schema_note)
            if check_role in ("rules", "session_types", "capacity"):
                continue
            violations.extend(
                check_pendiente_ack(active_roles, check_role, changes_log)
            )

    # (c) Doble ACTIVA - singleton roles only, derived from map values
    singleton_roles = set(_ROSTER_TO_REGISTRY_ROLE.values())
    violations.extend(check_double_activa(sessions, singleton_roles))

    # (d) Roster desactualizado - returns (violations, notes)
    # active_roles may be None if roster has "active_roles": null
    if isinstance(active_roles, dict):
        d_violations, d_notes = check_roster_outdated(
            sessions, active_roles, _ROSTER_TO_REGISTRY_ROLE
        )
    else:
        d_violations, d_notes = [], []
    violations.extend(d_violations)
    notes.extend(d_notes)

    # (e) Supervisor identity (WOT-2026-136f)
    if isinstance(active_roles, dict):
        violations.extend(check_identity_e(active_roles, roster, acting_thread))

    # (f) Cascada integrity: orquestador and supervisor not in cascada (WOT-2026-136f)
    if isinstance(active_roles, dict):
        violations.extend(check_cascada_f(active_roles, roster))

    return violations, notes


# --- Supervisor helpers (WOT-2026-136f) ---


def supervisor_esperado(roster: dict) -> str:
    """Determinar el threadId esperado del supervisor desde el predecesor.

    Before: roster es el diccionario completo del flight_roster.json.
    During: si hay excepcion_supervisor vigente (coordinadora_threadId ==
            orquestador.threadId), retorna el supervisor_threadId de la
            excepcion. Si no, retorna el predecessor del orquestador.
    After: threadId esperado como str, o "indeterminado" si no puede derivarse.
    """
    ar = roster.get("active_roles")
    if not isinstance(ar, dict):
        return "indeterminado"
    orq = ar.get("orquestador")
    if not isinstance(orq, dict):
        return "indeterminado"
    orq_thread = orq.get("threadId", "")

    # Check for active exception_supervisor (coordinadora = orquestador activo).
    exc = roster.get("excepcion_supervisor")
    if isinstance(exc, dict):
        exc_coord = exc.get("coordinadora_threadId", "")
        exc_sup = exc.get("supervisor_threadId", "")
        if exc_coord == orq_thread and exc_sup:
            return exc_sup

    pred = orq.get("predecessor_threadId", "")
    if not isinstance(pred, str):
        return "indeterminado"
    if not pred:
        return "indeterminado"
    # Guard against module load error: if the module is missing,
    # we cannot verify the prefix, so return indeterminado.
    if _thread_id_module is not None:
        try:
            if not _thread_id_module.has_mcp_prefix(pred):
                return "indeterminado"
        except (AttributeError, Exception):
            return "indeterminado"
    return pred


def check_identity_e(  # noqa: C901
    active_roles: dict, roster: dict, acting_thread: str
) -> list[str]:
    """Checkpoint (e): supervisor identity matches expected.

    Validates that the supervisor in active_roles matches what is expected
    from the orquestador's predecessor. If the supervisor is the same as the
    orquestador, it is a violation (closed failure).

    Before: active_roles and roster from the roster dict.
    During: checks that supervisor.threadId matches supervisor_esperado()
            or that no exception_supervisor is recorded.
    After: list of violation strings (empty if clean).
    """
    ar = active_roles
    if not isinstance(ar, dict):
        return []  # Other checks will catch this

    sup = ar.get("supervisor")
    if sup is None:
        return []  # No supervisor field -> nothing to validate

    if not isinstance(sup, dict):
        return [
            "(e) active_roles.supervisor no es un mapping: "
            "identidad de supervisor no verificable"
        ]

    sup_thread = sup.get("threadId", "")
    if not isinstance(sup_thread, str):
        return ["(e) supervisor.threadId no es una cadena"]

    orq = ar.get("orquestador")
    if not isinstance(orq, dict):
        return ["(e) active_roles.orquestador no es un mapping"]

    orq_thread = orq.get("threadId", "")

    # Closed failure: supervisor == orquestador
    if sup_thread == orq_thread:
        return [
            f"(e) supervisor == orquestador activo: '{sup_thread}' "
            f"no puede ser el supervisor"
        ]

    # Shape of excepcion_supervisor: always VIOLATION when malformed, even if
    # the supervisor matches the predecessor and even if the expected one is
    # indeterminate. The check goes BEFORE taking the expected.
    if "excepcion_supervisor" in roster:
        exc = roster["excepcion_supervisor"]
        if not isinstance(exc, dict):
            return [
                "(e) excepcion_supervisor presente pero no es un mapping: "
                "valor no mapeable en el roster"
            ]
        # Well-formedness: all four fields must be present and non-empty strings.
        exc_fields = ("coordinadora_threadId", "supervisor_threadId", "motivo", "desde")
        for field in exc_fields:
            val = exc.get(field)
            if not isinstance(val, str) or not val:
                return [
                    "(e) excepcion_supervisor mal formada: "
                    "los cuatro campos (coordinadora_threadId, supervisor_threadId, "
                    "motivo, desde) deben ser strings no vacios"
                ]

    expected = supervisor_esperado(roster)
    if expected == "indeterminado":
        return []  # Cannot determine expected supervisor

    # Exception mode: validate exception is well-formed and the supervisor
    # matches the supervisor_threadId of the exception.
    exc = roster.get("excepcion_supervisor")
    if isinstance(exc, dict):
        # The exception is well-formed here (checked before the expected).
        # The supervisor must match
        # supervisor_threadId of the exception (which supervisor_esperado
        # already validated against the active coordinadora).
        if expected != "indeterminado" and sup_thread == expected:
            return []  # Exception is valid and supervisor matches.
        # Exception exists but supervisor does not match the expected one.
        exc_sup = exc.get("supervisor_threadId", "")
        return [
            f"(e) excepcion vigente: el supervisor esperado es "
            f"'{exc_sup}', no '{sup_thread}'"
        ]

    # Normal mode: supervisor must match expected predecessor.
    if sup_thread != expected:
        return [
            f"(e) supervisor '{sup_thread}' no coincide con el esperado "
            f"'{expected}' (predecesor del orquestador)"
        ]

    return []


def check_cascada_f(  # noqa: C901
    active_roles: dict,
    roster: dict,
) -> list[str]:
    """Checkpoint (f): orquestador and active supervisor not in their own cascada.

    Validates that both the orquestador's threadId and the active supervisor's
    threadId do not appear in the cascada de contexto list at first level
    of the roster. If either does, the supervisor chain is broken.

    Before: active_roles from the roster dict; roster is the full roster dict.
    During: checks that orquestador.threadId and supervisor.threadId are not
        in cascada entries, validates cascada is a list, and each element
        is a mapping with a threadId.
    After: list of violation strings (empty if clean).
    """
    ar = active_roles
    if not isinstance(ar, dict):
        return []

    # Read cascada from first level of roster (not nested under orquestador).
    cascada = roster.get("cadena_contexto") if isinstance(roster, dict) else None
    if cascada is None:
        return []  # No cascada to check

    if not isinstance(cascada, list):
        orq = ar.get("orquestador")
        orq_thread = orq.get("threadId", "") if isinstance(orq, dict) else "?"
        return [
            f"(f) orquestador '{orq_thread}': cadena_contexto no es lista "
            f"(no se puede verificar integridad de cascada)"
        ]

    for entry in cascada:
        if not isinstance(entry, dict):
            orq = ar.get("orquestador")
            orq_thread = orq.get("threadId", "") if isinstance(orq, dict) else "?"
            return [
                f"(f) orquestador '{orq_thread}': elemento de cadena "
                f"no es un mapping (no se puede verificar threadId)"
            ]
        if "threadId" not in entry:
            orq = ar.get("orquestador")
            orq_thread = orq.get("threadId", "") if isinstance(orq, dict) else "?"
            return [
                f"(f) orquestador '{orq_thread}': elemento de cadena "
                f"sin threadId (cadena incompleta)"
            ]

    violations: list[str] = []

    # Check that orquestador is not in its own cascada.
    orq = ar.get("orquestador")
    if isinstance(orq, dict):
        orq_thread = orq.get("threadId", "")
        if isinstance(orq_thread, str):
            for entry in cascada:
                if isinstance(entry, dict) and entry.get("threadId") == orq_thread:
                    violations.append(
                        f"(f) orquestador '{orq_thread}' ya figura en su "
                        f"propia cadena de contexto"
                    )
                    break

    # Check that the active supervisor is not in the cascada.
    sup = ar.get("supervisor")
    if isinstance(sup, dict):
        sup_thread = sup.get("threadId", "")
        if isinstance(sup_thread, str):
            for entry in cascada:
                if isinstance(entry, dict) and entry.get("threadId") == sup_thread:
                    violations.append(
                        f"(f) supervisor '{sup_thread}' ya figura en la "
                        f"cadena de contexto"
                    )
                    break

    return violations


def _build_arg_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser.

    Before: nothing (pure constructor).
    During: creates ArgumentParser with description and 5 add_argument calls.
    After: returns a fully configured argparse.ArgumentParser instance.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Guard que detecta que active_roles del roster no coincide con "
            "el hilo que actua (WOT-2026-136c)."
        )
    )
    parser.add_argument(
        "--roster-path",
        default=None,
        help="Ruta al flight_roster.json (opcional; tambien se prueba FLIGHT_ROSTER_PATH).",
    )
    parser.add_argument(
        "--acting-thread",
        default=None,
        help="threadId de la sesion que actua (quien cierra).",
    )
    parser.add_argument(
        "--registry-path",
        default=None,
        help="Ruta al session_registry.json (default: hermano del roster).",
    )
    parser.add_argument(
        "--changes-log",
        default=None,
        help="Ruta al roster_changes.jsonl (default: hermano del roster).",
    )
    parser.add_argument(
        "--role",
        default=DEFAULT_ROLE,
        help=f"Rol a comprobar (default: '{DEFAULT_ROLE}').",
    )
    return parser


def _print_notes(notes: list[str]) -> None:
    """Print declarative notes if any.

    Before: notes is a list of strings (from checkpoint (d) omisions).
    During: prints header and each note with indent.
    After: no output if notes is empty; prints formatted notes otherwise.
    """
    if notes:
        print("\nNotas declarativas (no son violaciones):")
        for n in notes:
            print(f"  - {n}")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Before: parses arguments; resolves roster path from flag or env.
    During: runs all 4 checkpoints.
    After: returns 0 (PASS), 1 (FAIL), or 3 (N/A).
    """
    parser = _build_arg_parser()

    args = parser.parse_args(argv)

    # --- Resolucion del roster: flag -> env var -> N/A ---
    roster_path_str: str | None = args.roster_path
    if roster_path_str is None:
        roster_path_str = os.environ.get("FLIGHT_ROSTER_PATH", "")
    if not roster_path_str:
        print(
            "[roster-check] N/A: no se encontro roster (sin --roster-path ni "
            "FLIGHT_ROSTER_PATH)"
        )
        return 3

    roster_path = Path(roster_path_str).resolve()

    # --- Defaults ---
    if args.registry_path is None:
        registry_path = roster_path.parent / "session_registry.json"
    else:
        registry_path = Path(args.registry_path).resolve()

    if args.changes_log is None:
        changes_log = roster_path.parent / "roster_changes.jsonl"
    else:
        changes_log = Path(args.changes_log).resolve()

    role = args.role or DEFAULT_ROLE

    # --- Verificacion de identidad (fail-cerrado por identidad) ---
    if not args.acting_thread:
        print(
            "[roster-check] FAIL: --acting-thread no suministrado "
            "(fail-cerrado por identidad, DoD 4). Uso: --acting-thread <threadId>"
        )
        return 1

    # --- Verificar modulo compartido antes de validar roster ---
    if _thread_id_load_error is not None:
        print(
            "[roster-check] FAIL: scripts/flight/thread_id.py "
            "ausente o ilegible (no se puede validar el prefijo mcp:) "
            "- falta scripts/flight/thread_id.py"
        )
        return 1

    # --- Ejecucion de comprobaciones ---
    violations, notes = find_violations(
        roster_path=roster_path,
        acting_thread=args.acting_thread,
        registry_path=registry_path,
        changes_log=changes_log,
        role=role,
    )

    if not violations:
        print(
            f"[roster-check] OK: roster y acting_thread coinciden "
            f"(role='{role}', thread='{args.acting_thread}')"
        )
        _print_notes(notes)
        return 0

    print(
        f"[roster-check] VIOLATION en {roster_path}: {len(violations)} "
        f"infraccion(es) encontrada(s):"
    )
    for v in violations:
        print(f"  - {v}")

    _print_notes(notes)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
