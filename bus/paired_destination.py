#!/usr/bin/env python3
"""Resolvedor de destino pareado por topologia verificada.

WOT-2026-127d. Un worktree del motor T3 (`worktrees/<rama>`) tiene un "par"
topologico `worktrees/<rama>_workspace` que se comporta como un destino
exterior. Este modulo resuelve ese par cuando el motor no declara explícitamente
su workspace de dogfooding en `motor_workspace.txt`, y verifica que el enlace
motor<->destino apunta al mismo directorio (no a otro motor).

Before: ``root`` es la raiz del motor (o cualquier raiz con ``.agent/``).
During: lee ficheros locales; sin red, sin subprocess, nunca lanza.
After: devuelve el Path del destino pareado (con ``.agent/`` existente), o
    ``None`` si no se resuelve -- que es un resultado NORMAL.

NOTA FORENSE (WOT-2026-127d)
-----------------------------
El resolvedor nace de un fallo de arranque en frio: desde el worktree del motor
memoria-opus55-20261024 (HEAD 4c4c0eb0), ``python scripts/memory_context.py
--bootstrap`` entregaba 400 lecciones (motor=400) en vez de 610 (destino=210,
motor=400). Las causas medidas por el bucle UNI-5 (nonce 8675155815e04b27a05ec407d1017261):

(1) anclaje: el hook ``session_start_hook.py::_dogfooding_workspace`` (:156) y el CLI
``scripts/memory_context.py::_anchor_memory_root`` (:20) leian ``motor_workspace.txt``
(archivo gitignored, siempre ausente) como UN NOMBRE contra ``parent(motor_root)``,
que no expresa el layout T3 ``worktrees/<repo>_workspace/<rama>``.
(2) ``motor_workspace.txt`` acepta nombres con ``:`` (p.ej. ``C:rev127d_probe``),
lo que ``Path(m2) / "C:rev127d_probe"`` colapsa BAJO ``m2`` (pathlib descarta el
drive-relativo y une con el base) -> sin ``.agent`` -> None. La version anterior
rechazaba ``:``, ``/`` y ``\\``; se restaura la triple restriccion para paridad
semantica.
(3) un nombre como ``../..`` podria escapar la raiz del motor; ``..`` y ``.``
quedan explicitamente prohibidos en el paso 1.
(4) ``C:/Windows`` con slash fue el vector medido historicamente en el bucle L917:
un ``motor_workspace.txt`` que contuviera ``C:/Windows`` anclaba fuera del motor.
(5) los docstrings originales de ``_dogfooding_workspace`` y ``_anchor_memory_root``
llevaban 342 lineas de explicacion forense vs 207 de medicion de lecciones vigentes
(WOT-2026-057b). Este modulo centraliza esa justificacion: los llamantes remiten
aqui en vez de re-declararla (X-09: skill apunta, prompt gobierna).

"""

from __future__ import annotations

import json
import os
from pathlib import Path


#: Nombres prohibidos en motor_workspace.txt: rutas absolutas, escape de
#: directorio y caracteres de separacion de ruta (incluida ':' en Windows,
#: donde Path() / "C:x" colapsa bajo la raiz sin drive).
_FORBIDDEN_SEPS = ("/", "\\", ":")


def resolve_paired_destination(root: Path) -> Path | None:  # noqa: C901
    """Resolver el destino pareado para ``root``, o ``None``.

    Orden de resolucion:

    1. Si existe ``<root>/.agent/config/motor_workspace.txt``, conserva EXACTAMENTE
       la semantica actual: primera linea no vacia ni comentada = NOMBRE del
       workspace, resuelto contra ``root.parent``. Si resuelve a un directorio
       existente (con ``.agent/``), devuelvelo.

    2. Si no existe el fichero, se construye un candidato topologico:
       ``root.parent.parent / (root.parent.name + "_workspace") / root.name``.
       Se lee ``<candidato>/.agent/config/motor_destination_link.json`` con
       encoding ``utf-8-sig`` (tolerante a BOM de PowerShell 5.1); se acepta
       SOLO si su clave ``motor_root`` apunta al MISMO directorio que ``root``
       (se usa ``os.path.samefile`` dentro de try; si el fichero falta, el JSON
       es invalido, o ``motor_root`` difiere -> ``None``).

    3. Cualquier excepcion -> ``None``.

    Devuelve ``None`` si: no hay declarante ni candidato topologico, el link
    JSON no es un objeto, ``motor_root`` apunta a otro motor, el nombre del
    declarante esta prohibido (absoluto, ``..``, ``.``, o con ``/:/\\``), o el
    candidato no tiene ``.agent/``. Ningun caso de ``None`` indica error: es un
    resultado normal del resolvedor.

    Before: ``root`` es la raiz del motor (o cualquier raiz con ``.agent/``).
    During: solo lectura; nunca lanza -- captura y suprime toda excepcion.
    After: devuelve un Path existente, o ``None`` -- que es un resultado NORMAL
        (no hay declarante, no hay topologia pareada, el link no coincide,
        el JSON no es objeto, o el nombre es prohibido).
    """
    try:
        # Paso 1: motor_workspace.txt (compatibilidad con lo existente)
        decl = root / ".agent" / "config" / "motor_workspace.txt"
        if decl.is_file():
            name = next(
                (
                    ln.strip()
                    for ln in decl.read_text(encoding="utf-8").splitlines()
                    if ln.strip() and not ln.lstrip().startswith("#")
                ),
                "",
            )
            if (
                name
                and name not in {".", ".."}
                and not any(sep in name for sep in _FORBIDDEN_SEPS)
            ):
                candidate = root.parent / name
                if candidate.is_dir() and (candidate / ".agent").is_dir():
                    return candidate

        # Paso 2: candidato topologico (worktrees T3 layout)
        candidate = root.parent.parent / (root.parent.name + "_workspace") / root.name
        if not candidate.is_dir():
            return None
        link = candidate / ".agent" / "config" / "motor_destination_link.json"
        if not link.is_file():
            return None
        data = json.loads(link.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            return None
        motor_root_val = data.get("motor_root")
        if not isinstance(motor_root_val, str):
            return None
        try:
            # Usar samefile de os.path (mejor soporte en Windows que Path.samefile)
            if os.path.samefile(motor_root_val, str(root)):
                return candidate
        except OSError:
            # samefile puede fallar si uno de los dos no existe (aunque
            # candidate.is_dir() ya paso); en ese caso no coinciden.
            return None

        return None
    except Exception:
        # fail-open documentado: el contrato es "nunca lanza"; p.ej. `json.loads`
        # lanza RecursionError con un link anidado (medido por el Revisor, sonda A12)
        return None
