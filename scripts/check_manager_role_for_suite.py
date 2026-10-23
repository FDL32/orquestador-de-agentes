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
- La cadena literal ``ROL ACTIVO: X`` solo aparece como PROSA dentro de
  varios `SKILL.md` -- ningun script del repo IMPRIME esa cadena literal.
- SI existe una superficie reutilizable: `.agent/collaboration/TURN.md`,
  fila `| **ROL** | **<valor>** |`, escrita EXCLUSIVAMENTE por
  `.agent/agent_controller.py::update_turn_file()` (unico productor en todo
  el repo), protegida de ediciones directas por el hook `guard_paths`, y
  proyectada desde el bus (`docs/KNOWN_FAILURE_PATTERNS.md` FP-001).

Este modulo REUTILIZA esa superficie -- no inventa un mecanismo de identidad
nuevo.

LIMITE DECLARADO -- TURN.md proyecta la SIGUIENTE ACCION DEL TICKET, no la
IDENTIDAD DEL PROCESO QUE INVOCA (hallazgo confirmado, revision adversarial
Codex, WOT-2026-117a)
-----------------------------------------------------------------------------
`TURN.md` existe para CUALQUIER ticket gestionado por `agent_controller.py`
-- tambien el de un solo Builder sin Manager/Revisor separados (AGENTS.md
exime EXPLICITAMENTE a ese caso: "el Builder SI es el unico verificador
legitimo de `--level all`" via `scripts/run_gates_dispatch.py` /
`skills/builder-run-quality-gates`). La primera version de este gate asumia
que "TURN.md ausente" bastaba para detectar ese caso exento -- FALSO: un
destino de un solo Builder tiene TURN.md con `ROL=BUILDER` igual que un
destino con trio completo, y `run_gates_dispatch.py` invoca
`run_pytest_safe.py --level all` legitimamente en ambos (WOT-2026-058q). El
gate original bloqueaba esa invocacion sancionada por AGENTS.md -- regresion
confirmada, corregida abajo con una EXENCION EXPLICITA (no inferida).

EXENCION EXPLICITA (la correccion): `scripts/run_gates_dispatch.py` es el
UNICO invocador conocido y nombrado por AGENTS.md como exento. Antes de
invocar `run_pytest_safe.py --level all`, declara la variable de entorno
`SELFCHECK_EXEMPT_ENV` (ver abajo) en el proceso hijo. Este gate la
comprueba PRIMERO, antes de tocar TURN.md: si esta presente, permite sin
mirar el rol -- la exencion es del INVOCADOR CONOCIDO, no una inferencia
sobre el contenido de TURN.md. Una invocacion MANUAL/directa de
`run_pytest_safe.py --level all` (sin pasar por `run_gates_dispatch.py`) NO
lleva esa variable, y por tanto SI queda sujeta al chequeo de TURN.md de
abajo -- que es exactamente el caso que la regla de AGENTS.md ("solo el
Manager corre --level all, tras todos los commits") quiere cubrir.

RIESGO RESIDUAL DECLARADO (no resuelto por este ticket, ver hallazgo #2 de
la revision): incluso con la exencion de arriba, TURN.md sigue siendo una
PROYECCION (FP-001: puede quedar desincronizada del bus) y nunca prueba que
el PROCESO que invoca sea realmente el agente que el controller cree que
tiene el turno -- solo prueba que, SEGUN la ultima proyeccion escrita, el
turno declarado es Manager. Un proceso que invoque `--level all`
manualmente mientras TURN.md aun no se ha actualizado (stale) podria pasar
sin ser realmente el Manager. Resolver esto por completo exigiria un
mecanismo de identidad de PROCESO (p.ej. un token de sesion), que SI seria
una DECISION DE PROCESO nueva (AGENTS.md, "Decision de proceso sin
instruccion exacta") -- fuera del alcance de este ticket, declarado aqui en
vez de ocultado.

Before: `project_root` resuelto (via `runtime.project_root` en el caller).
During: (1) si `SELFCHECK_EXEMPT_ENV` esta presente en `env`, permite sin
    mas. (2) si no, lee `<project_root>/.agent/collaboration/TURN.md` si
    existe; extrae el valor de la fila `**ROL**` con una regex tolerante al
    formato markdown tabla que escribe `update_turn_file()`.
After: devuelve `(allowed: bool, reason: str)`. `allowed=True` si la
    exencion esta presente, si TURN.md no existe, si existe pero no se
    puede parsear/leer una fila `**ROL**` (ambiguo, ver NOTA de fail-open
    declarado abajo), o si el rol es `MANAGER` (case-insensitive).
    `allowed=False` solo cuando el rol parseado es un valor NO-MANAGER
    explicito (p.ej. `BUILDER`, `REVISOR`) Y la exencion no esta presente.

NOTA (fail-open declarado, no fail-closed estricto): un TURN.md malformado o
illegible (incluida una decodificacion UTF-8 invalida) deja pasar. Se acepta
ese riesgo residual porque el caso que SI debe bloquear (bus vivo, rol
BUILDER/REVISOR explicito, invocacion fuera de la exencion) es exactamente
el caso donde TURN.md esta bien formado -- lo escribe el controller, nunca
un humano a mano (el hook `guard_paths` bloquea la edicion directa).
Declarado aqui en vez de oculto en el codigo.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path


MANAGER_ROLE = "MANAGER"
TURN_RELPATH = Path(".agent") / "collaboration" / "TURN.md"

# WOT-2026-117a (fix post-revision): variable que declara la exencion del
# UNICO invocador conocido y nombrado por AGENTS.md (run_gates_dispatch.py /
# skills/builder-run-quality-gates). Presencia (cualquier valor no vacio)
# basta -- no se interpreta como booleano para evitar la trampa clasica de
# `"0"`/`"false"` siendo truthy como cadena.
SELFCHECK_EXEMPT_ENV = "RUN_PYTEST_SAFE_SELFCHECK_EXEMPT"

# Tolera el formato exacto que escribe update_turn_file():
# "| **ROL** | **{action["role"]}** |"
_ROLE_ROW_RE = re.compile(r"\|\s*\*\*ROL\*\*\s*\|\s*\*\*(?P<role>[^*|]+)\*\*\s*\|")


def read_turn_role(turn_path: Path) -> str | None:
    """El valor de la fila ``**ROL**`` de TURN.md, o ``None`` si ausente/no parseable.

    Before: ``turn_path`` puede existir o no, y si existe puede o no tener la
        fila ``**ROL**`` en el formato canonico, o contener bytes que no
        decodifican como UTF-8 valido.
    During: lee el fichero (UTF-8); aplica la regex de fila ROL.
    After: devuelve el valor crudo (sin recortar espacios internos mas alla de
        strip) o ``None`` si el fichero no existe, no se puede leer, no
        decodifica como UTF-8 o no contiene la fila. Nunca lanza.
    """
    try:
        content = turn_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    match = _ROLE_ROW_RE.search(content)
    if not match:
        return None
    return match.group("role").strip()


def evaluate_role_gate(
    project_root: Path, env: Mapping[str, str] | None = None
) -> tuple[bool, str]:
    """``(allowed, reason)`` para permitir ``--level all`` bajo ``project_root``.

    ``env`` es el entorno del proceso a inspeccionar (por defecto
    ``os.environ``); un parametro explicito facilita tests hermeticos sin
    mutar el entorno real del proceso de test.

    Ver docstring del modulo para la superficie leida, la exencion explicita
    del invocador conocido y el criterio de fail-open declarado cuando
    TURN.md esta ausente o es ilegible.
    """
    active_env = os.environ if env is None else env
    if active_env.get(SELFCHECK_EXEMPT_ENV, "").strip():
        return True, (
            f"Exento via {SELFCHECK_EXEMPT_ENV}: invocacion desde el "
            "self-check del Builder (run_gates_dispatch.py), que AGENTS.md "
            "exime explicitamente del protocolo de rol-unico."
        )

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
        "los commits, la suite va la ULTIMA'). Si eres el Builder corriendo "
        "un self-check, usa run_gates_dispatch.py (exento); si eres el "
        "Revisor, pide al Manager que corra --level all por ti."
    )
