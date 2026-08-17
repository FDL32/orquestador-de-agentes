#!/usr/bin/env python3
"""SessionStart hook: inyecta el indice de memoria al ABRIR sesion.

WOT-2026-057b. Cierra la ultima deuda declarada de WOT-2026-057a.

POR QUE EXISTE
--------------
El prompt de arranque dice que expandir la memoria con `--recall` "NO es
opcional". Por la definicion de este repo eso es una NORMA, no una barrera:
*"Citarlo en un prompt, una skill o este AGENTS.md no es cableado: es una
norma, y una norma depende de que alguien se acuerde"*.

Y las normas se olvidan de forma medible. En el bucle L914 se descubrio que
`--recall` llevaba COMENTADO en el prompt de bootstrap sin que nadie lo notara,
y que la memoria solo entraba automaticamente por `PreCompact` -- es decir,
cuando la sesion YA se estaba quedando sin contexto, nunca al empezar. Un
agente frio no recibia memoria por ningun hook.

Este hook es el mecanismo que faltaba: el indice entra solo, sin depender de
que el agente ejecute un comando.

POLITICA DE FALLO: FAIL-OPEN, Y ES DELIBERADO
---------------------------------------------
Objecion BA12-H7 del bucle L914, aceptada: un `SessionStart` fail-CLOSED ante
un archive corrupto impediria abrir *la sesion que vendria a arreglarlo*. Es un
deadlock autoinfligido, y el arreglo requiere una sesion.

Asi que hereda la politica que `bus/memory_loader.py` ya declara para el
archive: degradar el contexto, nunca romper al llamante. La barrera
fail-CLOSED para un archive corrupto existe y esta en otro sitio --
`validate_observations --strict`, cableada en prepush--, que es donde
corresponde: ahi bloquear es barato, aqui bloquea el trabajo.

Contrasta con `claude_guard_entry.py` (PreToolUse), que SI es fail-closed: alli
se impide una ESCRITURA peligrosa y no arrancar es el resultado seguro. Aqui lo
unico en juego es contexto de lectura.

DOS FALLOS DISTINTOS, DOS POLITICAS -- y confundirlos costo una suite roja:

  1. ESTE FICHERO NO EXISTE  -> configuracion ROTA. El lanzador de
     `.claude/settings.json` sale con rc=2 y diagnostico, como todos los demas
     hooks. Es fail-CLOSED y lo exige `check_claude_settings_portability`
     ("nunca un silent exit 0"): un hook que no puede fallar en rojo no es un
     hook, y un lanzador mudo esconde una instalacion rota.
  2. LA MEMORIA NO SE PUEDE LEER -> degradacion NORMAL. Se resuelve DENTRO de
     este script (`_load_context` devuelve "" y `main` sale con 0), que es
     donde se distingue "archive corrupto" de "hook ausente".

La primera version de este hook puso el fail-open en el LANZADOR (rc=0 cuando
el fichero no existia) y con eso enmascaraba el fallo (1) para conseguir el
comportamiento (2). La suite canonica lo caso. El fail-open sigue intacto donde
corresponde -- dentro del script--, y el arranque nunca se bloquea por memoria
ilegible.

Before: recibe el payload JSON de SessionStart por stdin (puede ir vacio).
During: resuelve el project root, carga el indice via `get_bootstrap_context()`
    y lo envuelve. Solo lectura; ninguna escritura en disco.
After: imprime `{"additionalContext": ...}` por stdout y sale con 0 SIEMPRE.
    Ante cualquier error emite un contexto minimo que apunta al comando manual.
"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path


# Instruccion que viaja SIEMPRE, incluso si la memoria no carga: el indice son
# titulares y la regla accionable suele vivir despues del corte, asi que el
# agente necesita saber que existe una puerta de expansion y como cruzarla.
_EXPANSION_HINT = (
    "\n\n---\n"
    "Las lineas marcadas `...[truncated]` son INDICE, no la leccion entera.\n"
    "Expandelas ANTES de medir o disenar nada:\n"
    '  python scripts/memory_context.py --recall --query "<termino de tu tarea>"\n'
    "  python scripts/memory_context.py --recall --id obs-<id-de-la-linea>\n"
)


def _resolve_root() -> Path:
    """Project root: el primer ancestro con `.claude/`, o el cwd."""
    here = Path(".").resolve()
    for candidate in [here, *here.parents]:
        if (candidate / ".claude").exists():
            return candidate
    return here


def _dogfooding_workspace(root: Path) -> Path | None:
    """Workspace de dogfooding declarado por el MOTOR, o ``None``.

    WOT-2026-057b. Sin esto, abrir sesion EN EL MOTOR pierde la memoria del
    destino: la asimetria INVERSA de D1. Medido 2026-08-17 en la ruta
    productiva -- `cwd=destino` daba 342 lecciones y `cwd=motor` solo 207,
    dejando fuera las 14 de TOPOLOGIA motor/destino, que son justo las que
    explican donde vive cada cosa a quien programa el motor.

    El mecanismo NO se inventa aqui: `.agent/config/motor_workspace.txt` existe
    desde WOT-2026-053h y declara ese workspace como un NOMBRE resuelto contra
    `parent(motor_root)` -- un nombre y no una ruta absoluta a proposito, porque
    una ruta pinearia la maquina y rompe la portabilidad del motor. Se lee aqui
    en vez de importar `install_agent_system.read_motor_workspace_root` porque
    este hook no puede depender de `scripts/` (misma frontera que `bus/`), y
    duplicar DIEZ lineas de lectura es mas barato que romperla.

    Before: ``root`` es la raiz resuelta; el fichero puede faltar o traer basura.
    During: lee la primera linea no vacia y no comentada. Sin red, sin
        subprocess, nunca lanza.
    After: devuelve el directorio existente, o ``None`` -- que es un resultado
        NORMAL (un destino no declara workspace de dogfooding), no un error.
    """
    try:
        decl = root / ".agent" / "config" / "motor_workspace.txt"
        if not decl.is_file():
            return None
        name = next(
            (
                ln.strip()
                for ln in decl.read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.lstrip().startswith("#")
            ),
            "",
        )
        # Es un NOMBRE de directorio hermano, nunca una ruta. Sin estas dos
        # comprobaciones el unico predicado era `is_dir()`, y aceptaba de todo
        # (medido en el bucle L917): `'../..'` por traversal, y `'C:/Windows'`
        # porque en Windows `Path(a) / 'C:/x'` DESCARTA la izquierda -- o sea
        # una ruta absoluta saltaba la resolucion contra `parent(motor_root)` y
        # anclaba donde fuera. Escribir una ruta es el error de tipeo natural,
        # porque el fichero pide un nombre y tiene que explicarlo en un comentario.
        #
        # El daño no seria silencioso a medias: `_load_context` ASIGNA
        # `AGENT_PROJECT_ROOT` al ancla, asi que un ancla basura deja al agente
        # arrancando sin memoria -- justo lo que este hook existe para evitar.
        if not name or name in {".", ".."} or any(sep in name for sep in "/\\:"):
            return None
        candidate = root.parent / name
        # `.agent/` es el marcador de workspace: un directorio cualquiera que
        # exista no lo es.
        if not candidate.is_dir() or not (candidate / ".agent").is_dir():
            return None
        return candidate
    except (OSError, ValueError):
        return None


def _load_context(root: Path) -> str:
    """Indice de memoria, o cadena vacia si no se puede cargar.

    Nunca propaga: este hook es fail-open por contrato (ver docstring del
    modulo). Un `except Exception` amplio es lo correcto AQUI y solo aqui --
    cualquier fallo de importacion, de topologia o de parseo debe degradar a
    "sin memoria", jamas impedir que la sesion abra.
    """
    try:
        import os

        # Fallback al motor que ALOJA este hook. Sin link (destino recien
        # creado, o el propio motor) `bus/` no estaria en `sys.path` y el import
        # fallaba con `ModuleNotFoundError`, degradando a "sin memoria" por una
        # razon que no es la memoria. Aqui `__file__` SI es el ancla correcta --
        # al reves que en `memory_loader._resolve_motor_root`, donde romperia el
        # hermetismo de los tests: este fichero VIVE en el motor y se copia con
        # el, asi que su ubicacion es la referencia mas fiable disponible.
        motor = Path(__file__).resolve().parents[2]
        link = root / ".agent" / "config" / "motor_destination_link.json"
        if link.exists():
            data = json.loads(link.read_text(encoding="utf-8"))
            candidate = data.get("motor_root")
            if isinstance(candidate, str) and Path(candidate).is_dir():
                motor = Path(candidate)

        # Anclar la memoria al root DONDE CORRE el hook. Sin esto el loader
        # resuelve por `__file__` -- el motor-- y el indice pierde el archive
        # LOCAL: medido 2026-08-17 desde el destino, 207 entradas en vez de 342.
        # Es la asimetria inversa de D1 (alli se perdia el motor, aqui el
        # destino), y las que se caen son las lecciones de topologia, que son
        # justo las que necesita quien opera en el destino.
        # Asignacion DIRECTA, no `setdefault`: el hook corre en el proceso del
        # arranque, que puede traer heredada una `AGENT_PROJECT_ROOT` de otra
        # sesion o de un vuelo anterior. Con `setdefault` esa variable stale
        # ganaba y el hook leia la memoria de OTRO destino -- medido: el test de
        # anclaje seguia rojo mientras la ruta manual salia verde, que es la
        # contradiccion entre probes que delata el defecto.
        # Si el root es un MOTOR que declara su workspace de dogfooding, se
        # ancla AHI: el loader une entonces workspace + motor y el agente que
        # programa el motor recibe las dos memorias. Sin esta rama, abrir en el
        # motor daba 207 en vez de 342 (ver `_dogfooding_workspace`).
        anchor = _dogfooding_workspace(root) or root
        os.environ["AGENT_PROJECT_ROOT"] = str(anchor)

        if str(motor) not in sys.path:
            sys.path.insert(0, str(motor))
        from bus.memory_loader import get_bootstrap_context

        return get_bootstrap_context() or ""
    except Exception:
        return ""


def main() -> int:
    # Se drena stdin (el payload del hook) sin usarlo: este hook no necesita el
    # evento, pero dejarlo sin leer puede romper la tuberia del llamante.
    with contextlib.suppress(OSError, ValueError):
        sys.stdin.buffer.read()

    root = _resolve_root()
    memory = _load_context(root)

    if memory:
        context = (
            f"**Memoria del proyecto (indice portable)**:\n\n{memory}{_EXPANSION_HINT}"
        )
    else:
        context = (
            "**Memoria del proyecto**: no se pudo cargar el indice en el arranque."
            + _EXPANSION_HINT
        )

    print(json.dumps({"additionalContext": context}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    # Fail-open absoluto: ni siquiera un fallo inesperado en `main()` puede
    # impedir que la sesion abra.
    try:
        sys.exit(main())
    except Exception:
        print(json.dumps({"additionalContext": ""}))
        sys.exit(0)
