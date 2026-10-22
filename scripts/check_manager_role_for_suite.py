#!/usr/bin/env python3
"""Gate: solo el Manager invoca `run_pytest_safe.py --level all` (WOT-2026-117a).

POR QUE EXISTE
--------------
AGENTS.md ("Orden de trabajo", asignacion de rol en despacho trio) exige que
la suite canonica completa (``--level all``) la corra UNA SOLA VEZ el Manager,
tras todos los commits del ticket -- nunca el Builder ni el Revisor a mitad de
ronda, porque cualquier commit posterior invalida `tested_commit_sha`. Hasta
este ticket esa regla era una NORMA (depende de que el agente se acuerde);
este modulo es la barrera MECANICA que la verifica antes de dejar correr
``--level all``.

QUE SUPERFICIE LEE (investigacion WOT-2026-117a, declarada antes de disenar)
-----------------------------------------------------------------------------
Busqueda previa de un mecanismo de identidad YA EXISTENTE (orden: `.agent/
collaboration/work_plan.md`, `bus/`, `.agent/agents_config.py`,
`scripts/run_gates_dispatch.py`, variables de entorno tipo `ROL ACTIVO`):

- NO existe ningun productor mecanico de "quien actua AHORA MISMO" como
  variable de entorno o campo de config: `role_mapping`/`role_models` en
  `agents.json` (`.agent/agents_config.py`) son mapeos ESTATICOS
  rol->backend/model_id, no "quien esta actuando en este instante".
  `scripts/run_gates_dispatch.py` no referencia rol en absoluto.
- La cadena literal ``ROL ACTIVO: X`` solo aparece como PROSA dentro de
  varios `SKILL.md` (instruccion para que el agente la busque en la salida
  del controller) y en `tests/01-session-management.md` (doc legacy) --
  ningun script del repo IMPRIME esa cadena literal.
- SI existe una superficie reutilizable: `.agent/collaboration/TURN.md`,
  fila `| **ROL** | **<valor>** |`, escrita EXCLUSIVAMENTE por
  `.agent/agent_controller.py::update_turn_file()` (unico productor en todo
  el repo), protegida de ediciones directas por el hook `guard_paths`
  (AGENTS.md / 01-security-architecture.md), y proyectada desde el bus
  (`docs/KNOWN_FAILURE_PATTERNS.md` FP-001: el bus es la autoridad canonica,
  TURN.md es una proyeccion derivada sujeta a drift ya documentado y
  parcialmente cubierta por el gate WOT-2026-060s de sincronizacion Plan ID).

Este modulo REUTILIZA esa superficie -- no inventa un mecanismo de identidad
nuevo. Conclusion de la busqueda de protocolo para la pregunta 4 del ticket
(DECISION DE PROCESO potencial si hiciera falta inventar): NO aplica, porque
la superficie ya existia y no fue necesario inventar nada.

LIMITE DECLARADO (por que este gate falla ABIERTO cuando TURN.md no existe)
----------------------------------------------------------------------------
`TURN.md` es un artefacto de `.agent/collaboration/`, que vive en el
repo_destino con bus vivo (AGENTS.md: "este repositorio es el motor
(code-only)... no leer o escribir `.agent/collaboration/` en este repo salvo
modo standalone/test"). En el motor en CODE-ONLY MODE (como el propio vuelo
que crea este ticket) y en un ticket de un solo Builder sin Revisor/Manager
separados, AGENTS.md YA exime a esos casos de la regla de rol ("el Builder SI
es el unico verificador legitimo de `--level all`"). Por tanto, cuando
`TURN.md` no existe, este gate PERMITE: la ausencia de bus significa que el
protocolo trio no aplica, no que alguien se salto el guard.

Before: `project_root` resuelto (via `runtime.project_root` en el caller).
During: lee `<project_root>/.agent/collaboration/TURN.md` si existe; extrae
    el valor de la fila `**ROL**` con una regex tolerante al formato
    markdown tabla que escribe `update_turn_file()`.
After: devuelve `(allowed: bool, reason: str)`. `allowed=True` si TURN.md no
    existe, si existe pero no se puede parsear una fila `**ROL**` (ambiguo,
    ver NOTA de fail-open declarado abajo), o si el rol es `MANAGER`
    (case-insensitive). `allowed=False` solo cuando el rol parseado es un
    valor NO-MANAGER explicito (p.ej. `BUILDER`, `REVISOR`).

NOTA (fail-open declarado, no fail-closed estricto): un TURN.md malformado
deja pasar. Se acepta ese riesgo residual porque el caso que SI debe
bloquear (bus vivo, rol BUILDER/REVISOR explicito) es exactamente el caso
donde TURN.md esta bien formado -- lo escribe el controller, nunca un
humano a mano (el hook `guard_paths` bloquea la edicion directa). Declarado
aqui en vez de oculto en el codigo.
"""

from __future__ import annotations

import re
from pathlib import Path


MANAGER_ROLE = "MANAGER"
TURN_RELPATH = Path(".agent") / "collaboration" / "TURN.md"

# Tolera el formato exacto que escribe update_turn_file():
# "| **ROL** | **{action["role"]}** |"
_ROLE_ROW_RE = re.compile(r"\|\s*\*\*ROL\*\*\s*\|\s*\*\*(?P<role>[^*|]+)\*\*\s*\|")


def read_turn_role(turn_path: Path) -> str | None:
    """El valor de la fila ``**ROL**`` de TURN.md, o ``None`` si ausente/no parseable.

    Before: ``turn_path`` puede existir o no, y si existe puede o no tener la
        fila ``**ROL**`` en el formato canonico.
    During: lee el fichero (UTF-8); aplica la regex de fila ROL.
    After: devuelve el valor crudo (sin recortar espacios internos mas alla de
        strip) o ``None`` si el fichero no existe, no se puede leer o no
        contiene la fila. Nunca lanza.
    """
    try:
        content = turn_path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = _ROLE_ROW_RE.search(content)
    if not match:
        return None
    return match.group("role").strip()


def evaluate_role_gate(project_root: Path) -> tuple[bool, str]:
    """``(allowed, reason)`` para permitir ``--level all`` bajo ``project_root``.

    Ver docstring del modulo para la superficie leida y el criterio de
    fail-open declarado cuando TURN.md esta ausente o es ilegible.
    """
    turn_path = Path(project_root) / TURN_RELPATH
    if not turn_path.is_file():
        return True, (
            f"TURN.md ausente en {turn_path} (sin bus vivo: el protocolo de "
            "rol-unico no aplica en este contexto -- ver LIMITE DECLARADO "
            "en check_manager_role_for_suite.py). --level all permitido."
        )

    role = read_turn_role(turn_path)
    if role is None:
        return True, (
            f"TURN.md en {turn_path} no tiene una fila **ROL** parseable: "
            "no se bloquea (fail-open declarado, ver NOTA en "
            "check_manager_role_for_suite.py)."
        )

    if role.upper() == MANAGER_ROLE:
        return (
            True,
            f"TURN.md declara ROL={role!r}: Manager autorizado para --level all.",
        )

    return False, (
        f"TURN.md declara ROL={role!r} (no MANAGER): --level all BLOQUEADO. "
        "Solo el Manager corre la suite canonica completa, UNA vez, tras "
        "todos los commits del ticket (AGENTS.md, 'Orden de trabajo: AGRUPA "
        "los commits, la suite va la ULTIMA'). Si eres el Builder o el "
        "Revisor, pide al Manager que corra --level all por ti."
    )
