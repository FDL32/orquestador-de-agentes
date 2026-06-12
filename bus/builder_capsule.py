"""Builder relaunch capsule assembly extracted from ``builder_lifecycle``.

This module owns evidence gathering for the relaunch capsule that summarizes
work plan, state, execution log, TURN blockers, and bus-derived facts.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

from .event_bus import EventBus


def _capsule_hechos_from_work_plan(work_plan_path: Path) -> list[str]:
    result = []
    try:
        work_plan = work_plan_path.read_text(encoding="utf-8")
        for line in work_plan.split("\n"):
            stripped_line = line.strip()
            for prefix in (
                "**ID:**",
                "**Title:**",
                "**Estado:**",
                "**deliverable_type:**",
            ):
                marker = f"- {prefix}"
                if stripped_line.startswith(marker):
                    value = stripped_line[len(marker) :].strip()
                    key = prefix.strip("*:")
                    result.append(f"{key}: {value}")
    except OSError:
        result.append("(work_plan.md no disponible)")
    return result


def _capsule_hechos_from_state(state_path: Path) -> list[str]:
    try:
        state = state_path.read_text(encoding="utf-8").strip()
        return [f"STATE.md: {state}"] if state else []
    except OSError:
        return ["(STATE.md no disponible)"]


def _capsule_hechos_from_log_tail(log_path: Path) -> list[str]:
    try:
        content = log_path.read_text(encoding="utf-8")
        log_lines = [line for line in content.split("\n") if line.strip()]
        tail_count = min(10, len(log_lines))
        tail = log_lines[-tail_count:] if tail_count > 0 else log_lines
        if not tail:
            return []
        result = ["Execution log tail:"]
        result.extend(f"  {tail_line}" for tail_line in tail)
        return result
    except OSError:
        return ["(execution_log.md no disponible)"]


def _capsule_hechos_from_bus(event_bus: EventBus, ticket_id: str) -> list[str]:
    try:
        events = event_bus.read_events(
            ticket_id=ticket_id,
            event_type="BUILDER_RELAUNCH_ATTEMPTED",
        )
        if events:
            latest = events[-1]
            payload = latest.payload or {}
            return [
                f"Event {latest.sequence_number}: "
                f"outcome={payload.get('outcome', '?')} "
                f"verify_signal={payload.get('verify_signal', '?')}",
            ]
    except Exception as exc:
        print(
            f"[supervisor] capsule bus read error: {exc}",
            file=sys.stderr,
            flush=True,
        )
    return ["(event bus no disponible)"]


def _capsule_blockers_from_turn(turn_path: Path) -> list[str]:
    result = []
    try:
        turn = turn_path.read_text(encoding="utf-8")
        in_blockers = False
        for line in turn.split("\n"):
            if "## Blockers from Manager" in line:
                in_blockers = True
                continue
            if in_blockers:
                if line.startswith("## "):
                    break
                stripped = line.strip()
                if stripped:
                    result.append(stripped)
    except OSError:
        result.append("(TURN.md no disponible)")
    if not result:
        result.append("(No blockers documentados en TURN.md)")
    return result


def _capsule_hipotesis_from_log(log_path: Path) -> list[str]:
    markers = ("hipotesis:", "[hipotesis]")
    try:
        content = log_path.read_text(encoding="utf-8")
        return [
            line.strip()
            for line in content.split("\n")
            if any(marker in line.lower() for marker in markers)
        ][:5]
    except OSError:
        return []


def _build_relaunch_capsule(
    project_root: Path,
    collaboration_dir: Path,
    runtime_dir: Path,
    work_plan_path: Path,
    state_path_file: Path,
    execution_log_path: Path,
    turn_path: Path,
    event_bus: EventBus,
    ticket_id: str,
) -> str:
    hechos = []
    hechos.extend(_capsule_hechos_from_work_plan(work_plan_path))
    hechos.extend(_capsule_hechos_from_state(state_path_file))
    hechos.extend(_capsule_hechos_from_log_tail(execution_log_path))
    hechos.extend(_capsule_hechos_from_bus(event_bus, ticket_id))

    blockers = _capsule_blockers_from_turn(turn_path)
    hipotesis = _capsule_hipotesis_from_log(execution_log_path)
    _ = project_root, collaboration_dir

    siguiente_accion = [
        f"Implementar {ticket_id} segun work_plan.md y ejecutar "
        "ruff + pytest-safe sobre archivos tocados.",
    ]

    now = datetime.now(timezone.utc).isoformat()
    capsule = (
        f"# Capsula de Relaunch - {ticket_id}\n"
        f"Generada: {now}\n\n"
        f"Fuentes: work_plan.md, TURN.md, STATE.md, "
        f"execution_log.md, bus events\n\n"
    )

    capsule += "## 1. Hechos Verificados\n"
    for hecho in hechos:
        capsule += f"- {hecho}\n"

    capsule += "\n## 2. Blockers del Manager\n"
    for blocker in blockers:
        capsule += f"- {blocker}\n"

    capsule += "\n## 3. Hipotesis / Puntos No Verificados\n"
    for hipotesis_item in hipotesis:
        capsule += f"- {hipotesis_item}\n"

    capsule += "\n## 4. Siguiente Accion Esperada\n"
    for action in siguiente_accion:
        capsule += f"- {action}\n"

    capsule += (
        f"\n---\n"
        f"*Capsula generada por supervisor para relaunch de {ticket_id}. "
        "Fuentes primarias: work_plan.md, TURN.md, STATE.md, "
        "execution_log.md, bus events.*\n"
    )

    capsule_path = runtime_dir / "relaunch_capsule.md"
    capsule_path.parent.mkdir(parents=True, exist_ok=True)
    capsule_path.write_text(capsule, encoding="utf-8")
    print(
        f"[ticket-supervisor] Capsula evidence-linked generada: {capsule_path}",
        flush=True,
    )

    return capsule
