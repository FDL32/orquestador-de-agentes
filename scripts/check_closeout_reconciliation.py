#!/usr/bin/env python3
"""WOT-2026-015l: fail-closed gate that reconciles the backlog against the bus.

Barrera anti auto-reporte de cierre. Compara el estado DECLARADO por el backlog
del workspace contra la fuente de verdad -- los eventos ``SUPERVISOR_CLOSED`` del
bus del WORKSPACE de dogfooding (NO del repo_motor: el motor es agnostico, sin
estado operativo, y mirarlo da un falso negativo verificado en vivo). Dos
sintomas reales lo motivaron: (1) un ticket ``completed`` en el bus que sigue
``pending`` en el backlog durante horas/dias; (2) un ticket declarado en
``_archive/backlog_done.md`` que nunca recibio su evento de cierre.

Decision de diseno (AP-D04): este gate NO reimplementa la lectura de bus. Toma
el mismo enfoque tolerante a corrupcion que ``scripts/preflight_reconcile.py``
(leer ``events.jsonl`` linea a linea, saltando lineas ilegibles) y el mismo
parseo de la tabla ``## Vista rapida`` que ``scripts/check_backlog_contract.py``.

Before (pre-condiciones): ``--project-root`` o ``AGENT_PROJECT_ROOT`` apunta al
    workspace de dogfooding (el que tiene ``.agent/runtime/events/`` y
    ``.agent/collaboration/backlog.md``). SIN fallback a ``__file__``: leer el bus
    relativo al motor seria el archivo equivocado -- fail-closed, igual que
    check_backlog_contract.py.
During (proceso y recursos): lee (a) los ``SUPERVISOR_CLOSED`` de
    ``events.jsonl`` (vivo) MAS ``events/archive/*.jsonl``; (b) los IDs vivos
    (``pending``/``blocked``) de ``## Vista rapida``; (c) los IDs declarados
    terminales de ``_archive/backlog_done.md``. Solo lectura. No muta estado.
After (post-condiciones y errores): reporta dos checks --
    ``drift`` (ningun cerrado-en-bus sigue vivo en backlog) y
    ``orphan_declared`` (todo declarado-cerrado tiene evento de bus) --
    en humano o ``--json``. Exit 0 si ambos pasan; exit 1 si alguno viola o si
    el bus/backlog no se pueden leer (fail-closed).
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
from pathlib import Path
from typing import Any


# --- Rutas relativas al workspace (project_root) ---
RUNTIME_EVENTS_REL = Path(".agent") / "runtime" / "events" / "events.jsonl"
RUNTIME_EVENTS_ARCHIVE_GLOB = str(
    Path(".agent") / "runtime" / "events" / "archive" / "*.jsonl"
)
BACKLOG_REL = Path(".agent") / "collaboration" / "backlog.md"
BACKLOG_DONE_REL = Path(".agent") / "collaboration" / "_archive" / "backlog_done.md"

# El evento que declara un cierre canonico.
CLOSED_EVENT_TYPE = "SUPERVISOR_CLOSED"

# Parseo de la cola viva (mismo contrato que check_backlog_contract.py).
_VISTA_RAPIDA_HEADER = "## Vista rapida"
# Estados que cuentan como "vivo bloqueante" para el drift (check A). NOTA:
# ``completed-partial`` es un estado vivo LEGITIMO (tiene reactivacion pendiente
# por diseno) y ademas puede portar un SUPERVISOR_CLOSED historico de su parte
# cerrada -- NO es drift. Se excluye deliberadamente del conjunto de drift.
_LIVE_STATES = {
    "pending",
    "blocked",
    "deferred",
    "ready-for-review",
    "awaiting-manager",
}

# Estados terminales que declaran un cierre en backlog_done.md.
_TERMINAL_STATES = {"completed", "done", "closed", "superseded", "absorbed"}

# IDs de ticket reconocidos (WOT/WP/WT-AAAA-suffix).
_TICKET_ID_RE = re.compile(r"\b((?:WOT|WP|WT)-\d{4}-\w+)\b")


class ReconcileError(Exception):
    """Fail-closed: el bus o el backlog no se pueden leer con garantias."""


def resolve_project_root(cli_value: str | None) -> Path:
    """Resolver el workspace. Fail-closed: NO deriva de ``__file__``.

    Un backlog/bus leido relativo al cwd del motor seria el archivo equivocado
    (la semilla del motor, no la cola del workspace). Root ausente es un error
    fail-closed, no un pass-open -- mismo patron que check_backlog_contract.py.
    """
    raw = cli_value or os.environ.get("AGENT_PROJECT_ROOT")
    if not raw:
        raise ReconcileError(
            "project root ausente: pasa --project-root o exporta "
            "AGENT_PROJECT_ROOT apuntando al workspace de dogfooding"
        )
    root = Path(raw).resolve()
    if not root.is_dir():
        raise ReconcileError(f"project root no es un directorio: {root}")
    return root


def _iter_event_lines(path: Path) -> list[dict[str, Any]]:
    """Leer un events.jsonl tolerando lineas corruptas (patron preflight_reconcile)."""
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                # Linea ilegible: se salta (no falsear el conjunto por 1 corrupta).
                continue
    except OSError as exc:
        raise ReconcileError(f"no se pudo leer el bus {path}: {exc}") from exc
    return records


def read_bus(project_root: Path) -> tuple[dict[str, int], set[str]]:
    """Leer el bus del workspace (vivo + archive) en UNA pasada.

    Devuelve una tupla ``(closed, present)``:
      - ``closed`` = {ticket_id: sequence_number} de los ``SUPERVISOR_CLOSED``.
      - ``present`` = set de todo ticket_id con CUALQUIER evento en el bus.

    La union vivo+archive es obligatoria: los tickets ya archivados (p.ej.
    016o/016p) viven SOLO en ``archive/*.jsonl``; mirar solo el vivo produce un
    falso negativo. ``present`` habilita el criterio pre-bus del check B: un
    declarado-cerrado con CERO eventos es historia legada (antes del bus), no un
    auto-reporte. Falla fail-closed si NINGUNA fuente de bus existe.
    """
    events_path = project_root / RUNTIME_EVENTS_REL
    archive_paths = [
        Path(p) for p in glob.glob(str(project_root / RUNTIME_EVENTS_ARCHIVE_GLOB))
    ]
    if not events_path.exists() and not archive_paths:
        raise ReconcileError(
            f"bus de eventos ausente en {project_root / RUNTIME_EVENTS_REL.parent}: "
            "no se puede reconciliar (fail-closed)"
        )

    closed: dict[str, int] = {}
    present: set[str] = set()
    for path in [events_path, *archive_paths]:
        for rec in _iter_event_lines(path):
            ticket = rec.get("ticket_id")
            if not ticket:
                continue
            present.add(ticket)
            if rec.get("event_type") != CLOSED_EVENT_TYPE:
                continue
            seq = int(rec.get("sequence_number", 0) or 0)
            # Conservar el seq mayor si el ticket aparece en vivo y archive.
            if ticket not in closed or seq > closed[ticket]:
                closed[ticket] = seq
    return closed, present


def _vista_rapida_rows(path: Path) -> list[str]:
    """Filas de datos de la tabla bajo ``## Vista rapida`` (solo la tabla).

    Nunca prosa ni comentarios HTML (mismo contrato 012a/012b que
    check_backlog_contract.py). Lee con utf-8-sig por el BOM heredado.
    Fail-closed si falta el backlog, la seccion o la cabecera de tabla.
    """
    if not path.exists():
        raise ReconcileError(f"backlog ausente: {path}")
    lines = path.read_text(encoding="utf-8-sig").splitlines()

    try:
        start = next(
            i for i, ln in enumerate(lines) if ln.strip() == _VISTA_RAPIDA_HEADER
        )
    except StopIteration:
        raise ReconcileError(
            f"backlog sin seccion '{_VISTA_RAPIDA_HEADER}': {path}"
        ) from None

    header_idx: int | None = None
    for i in range(start + 1, len(lines)):
        stripped = lines[i].strip()
        if stripped.startswith("## "):
            break
        if stripped.startswith("| Prioridad"):
            header_idx = i
            break
    if header_idx is None:
        raise ReconcileError(f"no hay tabla bajo '{_VISTA_RAPIDA_HEADER}' en {path}")

    rows: list[str] = []
    for i in range(header_idx + 2, len(lines)):  # +2 salta el separador |---|
        stripped = lines[i].strip()
        if not stripped or stripped.startswith("## "):
            break
        if stripped.startswith("|"):
            rows.append(stripped)
    return rows


def read_live_backlog(project_root: Path) -> set[str]:
    """IDs con estado vivo (pending/blocked/...) en la tabla ``## Vista rapida``."""
    live: set[str] = set()
    for row in _vista_rapida_rows(project_root / BACKLOG_REL):
        cells = [c.strip() for c in row.strip("|").split("|")]
        if len(cells) < 5:
            continue
        ticket, status = cells[1], cells[4]
        if status in _LIVE_STATES:
            m = _TICKET_ID_RE.search(ticket)
            if m:
                live.add(m.group(1))
    return live


def read_declared_done(project_root: Path) -> set[str]:
    """IDs declarados terminales en la tabla ``| Ticket | Estado | Nota |``.

    Ausencia de backlog_done.md NO es error (un workspace joven puede no tener
    aun historico): devuelve conjunto vacio. Solo cuenta filas cuyo Estado esta
    en el vocabulario terminal.
    """
    path = project_root / BACKLOG_DONE_REL
    if not path.exists():
        return set()
    content = path.read_text(encoding="utf-8-sig")

    declared: set[str] = set()
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 2:
            continue
        ticket_cell, status_cell = cells[0], cells[1]
        if status_cell.lower() not in _TERMINAL_STATES:
            continue
        m = _TICKET_ID_RE.search(ticket_cell)
        if m:
            declared.add(m.group(1))
    return declared


def run_gate(project_root: Path) -> dict[str, Any]:
    """Reconciliar y devolver el reporte agregado (no muta estado).

    Check A (drift): ningun SUPERVISOR_CLOSED del bus sigue vivo en el backlog.
    Check B (orphan_declared): todo declarado-terminal tiene evento de bus.
    """
    closed_bus, present_in_bus = read_bus(project_root)  # {id: seq}, {ids}
    live_backlog = read_live_backlog(project_root)
    declared_done = read_declared_done(project_root)

    # A: cerrado-en-bus PERO aun-vivo-en-backlog.
    drift_ids = sorted(set(closed_bus) & live_backlog)
    drift_findings = [
        {
            "ticket_id": tid,
            "sequence_number": closed_bus[tid],
            "detail": (
                f"{tid} tiene {CLOSED_EVENT_TYPE} en el bus (seq "
                f"{closed_bus[tid]}) pero sigue vivo en '## Vista rapida'"
            ),
            "fix": (
                f"retira {tid} de la cola viva del backlog (esta cerrado en el "
                "bus); si procede, muevelo a _archive/backlog_done.md"
            ),
        }
        for tid in drift_ids
    ]

    # B: declarado-terminal PERO sin evento de cierre en el bus. Se EXIME la
    # historia pre-bus: un ticket declarado que NO tiene NINGUN evento en el bus
    # (present_in_bus) es legado anterior a la existencia del bus, no un
    # auto-reporte. Un ticket que SI tuvo actividad en el bus pero nunca recibio
    # SUPERVISOR_CLOSED (se cerro por otra via) SI se reporta.
    orphan_ids = sorted((declared_done & present_in_bus) - set(closed_bus))
    orphan_findings = [
        {
            "ticket_id": tid,
            "detail": (
                f"{tid} esta declarado terminal en backlog_done.md y tuvo "
                f"actividad en el bus pero NUNCA recibio {CLOSED_EVENT_TYPE} "
                "(cierre no canonico / posible auto-reporte)"
            ),
            "fix": (
                f"verifica el cierre real de {tid}: o cierralo canonicamente "
                "(manager-approve emite el evento) o corrige backlog_done.md"
            ),
        }
        for tid in orphan_ids
    ]

    drift_check = {
        "pass": not drift_findings,
        "findings": drift_findings,
    }
    orphan_check = {
        "pass": not orphan_findings,
        "findings": orphan_findings,
    }
    all_pass = drift_check["pass"] and orphan_check["pass"]

    prebus_exempt = sorted(declared_done - present_in_bus)

    return {
        "project_root": str(project_root),
        "closed_in_bus_count": len(closed_bus),
        "live_backlog_count": len(live_backlog),
        "declared_done_count": len(declared_done),
        "prebus_exempt_count": len(prebus_exempt),
        "checks": {"drift": drift_check, "orphan_declared": orphan_check},
        "all_pass": all_pass,
    }


def _render_human(report: dict[str, Any]) -> str:
    lines: list[str] = []
    verdict = "PASS" if report["all_pass"] else "FAIL"
    lines.append(f"CLOSEOUT RECONCILIATION [{verdict}] -- {report['project_root']}")
    lines.append(
        f"  bus_closed={report['closed_in_bus_count']} "
        f"live_backlog={report['live_backlog_count']} "
        f"declared_done={report['declared_done_count']} "
        f"prebus_exempt={report['prebus_exempt_count']}"
    )
    for name, check in report["checks"].items():
        mark = "PASS" if check["pass"] else "FAIL"
        n = len(check["findings"])
        lines.append(f"  [{mark}] {name}: {n} violacion(es)")
        for f in check["findings"]:
            lines.append(f"        - {f['detail']}")
            lines.append(f"          fix: {f['fix']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Gate de cierre: reconcilia el backlog del workspace contra los "
            "eventos SUPERVISOR_CLOSED del bus (bidireccional, fail-closed)."
        )
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help=(
            "Workspace de dogfooding (con .agent/runtime/events y "
            ".agent/collaboration/backlog.md). Fallback: AGENT_PROJECT_ROOT."
        ),
    )
    parser.add_argument("--json", action="store_true", help="Emitir JSON unico.")
    args = parser.parse_args(argv)

    try:
        project_root = resolve_project_root(args.project_root)
        report = run_gate(project_root)
    except ReconcileError as exc:
        diag = {"all_pass": False, "error": str(exc)}
        if args.json:
            print(json.dumps(diag, ensure_ascii=False, indent=2))
        else:
            print(f"CLOSEOUT RECONCILIATION [FAIL]\n  error: {exc}")
        return 1

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_render_human(report))

    return 0 if report["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
