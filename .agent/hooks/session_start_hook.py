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
During: resuelve el project root; lee el campo `source` del payload (ya no
    elige puerta: diseno v6 usa el MISMO indice acotado, `get_session_index`,
    para todas las fuentes) y ensambla con `assemble_session_context`, que
    respeta `SESSION_CONTEXT_MAX_CHARS` (9.000, bajo el tope de 10k de Claude
    Code). Antepone la pista de momentos de expansion; anade una linea de salud de la memoria (WOT-2026-089e, por
    subproceso de `check_memory_health.py`), DESPUES de la memoria un bloque
    con el backend/modelo de cada rol de capa resuelto desde `agents.json`
    (WOT-2026-098b), y SIEMPRE AL FINAL la seccion M4/M5 (2026-10-15):
    contratos de invocacion leidos EN VIVO desde
    `prompts/orchestrator_launch_builder.md`. Solo lectura; ninguna escritura.
After: imprime `{"hookSpecificOutput": {"hookEventName": "SessionStart",
    "additionalContext": ...}}` por stdout (esquema documentado de Claude Code;
    el `additionalContext` en la raiz que se emitio hasta 2026-10-23 nunca llego
    al modelo) y sale con 0 SIEMPRE. Ante cualquier error emite el imperativo de
    carga manual, y un `systemMessage` para el usuario si la memoria fallo.
    La seccion de roles hereda el mismo fail-open: si `agents.json` falta, esta
    corrupto o no declara `role_mapping`, se OMITE (cadena vacia) sin degradar la
    memoria ya inyectada ni bloquear el arranque. La seccion M4/M5 es distinta:
    NUNCA se omite -- si la lectura en vivo falla, cae a un texto fallback
    fijo (ver `_M4_M5_FALLBACK`), porque la norma de invocacion aplica aunque
    el prompt fuente no resuelva.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


# Instruccion que viaja SIEMPRE, incluso si la memoria no carga: el indice son
# titulares y la regla accionable vive en la leccion entera, asi que el agente
# necesita saber CUANDO cruzar la puerta de expansion, no solo que existe
# (diseno v6: momentos nombrados).
_EXPANSION_HINT = (
    "**Memoria: cuando expandir** (el indice de abajo son titulares, no "
    "lecciones):\n"
    '- al empezar una tarea: python scripts/memory_context.py --recall --query "<dominio de la tarea>"\n'
    "- antes de medir, disenar o proponer una barrera: --recall --query sobre ese tema\n"
    '- antes de commit, suite, push o cierre: --recall --query "<cierre|suite|push>"\n'
    "- al ver un id relevante en el indice: --recall --id <id>\n"
)

# Mensaje de FALLO de carga: distinto del de corpus vacio (ronda 4 #59). Lleva
# el mismo imperativo agnostico que AGENTS.md: si la memoria no entro, cargala.
_LOAD_FAILED = (
    "**Memoria del proyecto**: NO se pudo cargar el indice en este arranque. "
    "Ejecuta `python scripts/memory_context.py --bootstrap` antes de trabajar "
    '(y `--recall --query "<termino>"` para expandir).'
)
_LOAD_EMPTY = (
    "**Memoria del proyecto**: el corpus esta vacio (aun no hay lecciones). "
    'Cuando las haya, se expanden con `--recall --query "<termino>"`.'
)

_LOAD_NO_BUDGET = (
    "**Memoria del proyecto**: indice omitido por presupuesto de arranque (el "
    "corpus NO esta vacio). Enumeralo con `python scripts/memory_context.py "
    '--full` y expande con `--recall --query "<termino>"`.'
)

#: Por debajo de esto el indice no cabe con cabecera y pie utiles: se declara
#: omitido en vez de emitir un bloque recortado o confundirlo con "vacio".
_MIN_INDEX_BUDGET = 1500

# Topes por seccion (chars). El total lo fija `SESSION_CONTEXT_MAX_CHARS` del
# loader; el indice recibe lo que queda tras las partes fijas.
_HEALTH_CAP = 400
_M4_M5_CAP = 3600


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


def _motor_root(root: Path) -> Path:
    """Raiz del motor para este arranque: el link del destino, o el motor que aloja el hook.

    Fallback al motor que ALOJA este hook. Sin link (destino recien creado, o el
    propio motor) `bus/` no estaria en `sys.path` y el import fallaba con
    `ModuleNotFoundError`, degradando a "sin memoria" por una razon que no es la
    memoria. Aqui `__file__` SI es el ancla correcta -- al reves que en
    `memory_loader._resolve_motor_root`, donde romperia el hermetismo de los
    tests: este fichero VIVE en el motor y se copia con el, asi que su ubicacion
    es la referencia mas fiable disponible.

    Before: `root` es la raiz resuelta; el link puede faltar o traer basura.
    During: solo lectura; puede lanzar si el link no es JSON (los llamantes lo
        capturan: este hook es fail-open).
    After: un directorio, nunca `None`.
    """
    motor = Path(__file__).resolve().parents[2]
    link = root / ".agent" / "config" / "motor_destination_link.json"
    if link.exists():
        # `utf-8-sig`: un link escrito por PowerShell 5.1 lleva BOM, y con
        # `utf-8` estricto `json.loads` lanza -> el hook entregaba CERO memoria
        # en ese destino (medido 2026-10-23, FDL32-t3-dev-hub, ronda 5).
        data = json.loads(link.read_text(encoding="utf-8-sig"))
        candidate = data.get("motor_root")
        if isinstance(candidate, str) and Path(candidate).is_dir():
            motor = Path(candidate)
    return motor


def _health_line(root: Path) -> str:
    """Una linea con el estado de la memoria de motor y destino, o "" si no se puede medir.

    WOT-2026-089e (P0). El disparador de `prompts/memory_optimization.md` era prosa
    opcional del cierre; aqui se muestra al ABRIR la sesion, que es lo unico que se
    ejecuta solo en cada arranque. Se llama a `scripts/check_memory_health.py` por
    SUBPROCESO y no se importa: este hook no puede depender de `scripts/` (misma
    frontera que `bus/`, ver `_dogfooding_workspace`). Se omite el validador (c)
    para no frenar el arranque; el paso `memory_health` del cierre si lo ejecuta.

    Before: `root` es la raiz resuelta.
    During: un subproceso de solo lectura con timeout; fail-open (cualquier fallo,
        timeout o salida invalida devuelve "").
    After: una linea breve; con disparadores activos nombra el prompt a aplicar.
    """
    try:
        motor = _motor_root(root)
        script = motor / "scripts" / "check_memory_health.py"
        if not script.is_file():
            return ""
        anchor = _dogfooding_workspace(root) or root
        proc = subprocess.run(  # noqa: S603 - script propio del motor, args controlados
            [
                sys.executable,
                str(script),
                "--project-root",
                str(anchor),
                "--motor-root",
                str(motor),
                "--json",
                "--skip-validate",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if proc.returncode != 0:
            return ""
        parts: list[str] = []
        fired_any = False
        for label, measure in json.loads(proc.stdout).items():
            fired = [t["id"] for t in measure["triggers"] if t["fired"]]
            fired_any = fired_any or bool(fired)
            part = (
                f"{label}: L1 {measure['l1']['parsed']} entradas "
                f"(ruido {measure['l1']['noise']}), "
                f"L2 {measure['l2']['rules']}/{measure['l2']['max_rules']}"
            )
            if fired:
                part += f" -> DISPARA ({','.join(fired)})"
            for warning in measure.get("warnings", []):
                part += f" - AVISO: {warning}"
            parts.append(part)
        # La accion (que prompt aplicar) es lo unico accionable de la linea:
        # el tope `_HEALTH_CAP` recorta la medicion, nunca la accion.
        action = " Aplica prompts/memory_optimization.md." if fired_any else ""
        body = _cap(
            "Salud de la memoria: " + "; ".join(parts) + ".",
            _HEALTH_CAP - len(action),
            "Salud",
        )
        return body + action
    except Exception:
        return ""


# Roles de CAPA del sistema de 4 capas (WOT-2026-098b): los que participan en el
# ciclo de UN ticket, en orden fijo. Los roles de gobierno transversal
# (auditor/challenger) NO entran: no tienen hueco en la secuencia y el objetivo es
# dar al agente en frio el backend/modelo de las capas por las que va a pasar su
# ticket.
_LAYER_ROLES = ("orchestrator", "manager", "revisor", "builder")


def _role_section(root: Path) -> str:
    """Backend/modelo por rol de capa, resuelto desde `agents.json`, o "".

    WOT-2026-098b. Hoy NADIE expone `role_mapping`/`role_models` al propio agente
    que arranca: el unico consumidor real resuelve `"manager"` HARDCODEADO y lo
    invoca el proceso PADRE (bridge), nunca el agente. Esta seccion es el unico
    canal automatico para una sesion PRINCIPAL en TODO arranque (incluida
    post-compactacion), asi que expone el backend/modelo RESUELTO de cada rol.

    Before: `root` es la raiz resuelta; `agents.json` puede faltar, estar corrupto
        o no declarar `role_mapping`.
    During: resuelve el motor (`_motor_root`), importa el loader canonico
        (`.agent/agents_config.py`, la unica capa de schema) y lee el config del
        WORKSPACE donde corre el hook -- el MISMO que usa el runtime
        (`bus/review_bridge.py` resuelve `load_agents_config(project_root)`), para
        no mentir al agente con una config que no es la efectiva.
    After: un bloque compacto (una linea por rol de capa), o "" si algo falla.
        NUNCA propaga: hereda el contrato fail-open del modulo (ver el docstring
        de cabecera); cualquier excepcion degrada a "seccion omitida".
    """
    try:
        motor = _motor_root(root)
        if str(motor) not in sys.path:
            sys.path.insert(0, str(motor))
        # APPEND de `.agent/` (nunca insert(0)): con `.agent` al frente, `runtime`
        # resolveria a `.agent/runtime/` en vez de `<motor>/runtime/` (hazard
        # documentado en AGENTS.md y ya respetado por `_load_context`).
        agent_dir = motor / ".agent"
        if str(agent_dir) not in sys.path:
            sys.path.append(str(agent_dir))

        from agents_config import (
            get_backend_for_role,
            get_model_for_role,
            load_agents_config,
        )

        config = load_agents_config(root)

        def _resolve_role(role: str) -> tuple[str, str | None] | None:
            """(backend, model) del rol, o ``None`` si no resuelve. Fail-open."""
            try:
                return get_backend_for_role(role, config), get_model_for_role(
                    role, config
                )
            except Exception:
                return None

        lines: list[str] = []
        for role in _LAYER_ROLES:
            resolved = _resolve_role(role)
            if resolved is None:
                continue
            backend, model = resolved
            model_txt = model or "(default del backend)"
            lines.append(f"- {role}: backend={backend}, modelo={model_txt}")
        if not lines:
            return ""
        return (
            "**Roles del sistema (backend/modelo por rol, agents.json)**:\n"
            + "\n".join(lines)
        )
    except Exception:
        # Fail-open por contrato (docstring del modulo): un fallo aqui NUNCA
        # bloquea el arranque ni degrada la memoria ya resuelta.
        return ""


# Fase 0 + Via A (M4/M5 integration, 2026-10-15). WOT-2026-057a/b pattern
# applied to a SECOND norma that lived only inside a prompt nobody re-reads
# mid-session: M4 ("validador o contrato citado => leelo ENTERO antes de
# actuar") y M5 ("exit code real, nunca $? tras un pipe"), hoy solo dentro
# de orchestrator_launch_builder.md:327-383 -- un prompt de Builder que un
# agente operando una herramienta con contrato propio desde chat normal
# (p.ej. ensemble_dispatch.py, gobernado por prompts/ensemble_loop.md)
# nunca carga. Medido en vivo (sesion 2026-10-15): tres rondas de
# ensemble_dispatch.py loop-round lanzadas con --profile/--timeout/`| tail`
# inferidos por tanteo, sin haber leido ensemble_loop.md entero, produjeron
# contaminacion real de backend_quarantine.json (timeouts cortos matando
# procesos vivos, registrados como fallos de transporte genuinos).
_M4_M5_SOURCE_REL = Path("prompts") / "orchestrator_launch_builder.md"
_M4_M5_START_MARKER = "### M4."
_M4_M5_END_MARKER = "## Objetivo"

# Fallback usado SOLO si la lectura en vivo falla (fichero ausente, cambio
# de marcador, etc.) -- nunca se usa si la lectura en vivo tiene exito, asi
# que no puede quedar obsoleto en silencio mientras el fichero fuente siga
# resolviendo.
_M4_M5_FALLBACK = (
    "**Contratos de invocacion (M4/M5)**: si el contrato de un ticket, un "
    "prompt o el propio artefacto nombran un validador, gate o CONTRATO "
    "citable para lo que vas a hacer, leelo/ejecutalo ENTERO antes de "
    "actuar -- no lo infieras por grep, analogia o memoria. Nunca captures "
    "$? despues de un pipe (usa PIPESTATUS o evita el pipe): el `rc` tras "
    "`cmd | tail` es del consumidor, no del productor. "
    "(Fuente completa: orchestrator_launch_builder.md, no resoluble en "
    "este arranque.)"
)


def _m4_m5_section(root: Path) -> str:
    """Seccion M4/M5, leida EN VIVO desde el prompt fuente, o el fallback.

    WOT-2026-057a/b pattern: una norma dentro de un prompt que nadie relee
    a mitad de sesion no es cableado. Esta seccion la inyecta el hook SIN
    que el agente tenga que ejecutar nada, igual que ya hace con memoria/
    salud/roles.

    Por que LECTURA EN VIVO y no texto duplicado a mano (correccion
    adoptada tras bucle de gobierno, 2026-10-15): un texto hardcodeado se
    desincroniza del prompt fuente la primera vez que alguien edite M4/M5
    sin acordarse de este hook. Leer en vivo hace que CUALQUIER edicion del
    prompt fuente se refleje aqui sin cambio adicional -- al coste de una
    lectura de fichero mas por arranque (barata: un prompt de ~400 lineas).

    Before: `root` es la raiz resuelta por `_resolve_root`.
    During: resuelve el motor (`_motor_root`, mismo ancla que memoria/roles)
        y lee `prompts/orchestrator_launch_builder.md` ENTERO; extrae el
        tramo entre `_M4_M5_START_MARKER` y `_M4_M5_END_MARKER` (ambos
        literales, sin regex fragil de numero de linea -- los numeros de
        linea citados en el fallback y en memoria del repo son solo
        referencia humana, nunca el ancla real de extraccion).
    After: el tramo extraido (con cabecera explicita de que es LECTURA EN
        VIVO y su ruta de origen), o `_M4_M5_FALLBACK` si el fichero falta,
        los marcadores no se encuentran, o cualquier excepcion ocurre.
        NUNCA lanza: mismo contrato fail-open que el resto del modulo.
    """
    try:
        motor = _motor_root(root)
        source = motor / _M4_M5_SOURCE_REL
        text = source.read_text(encoding="utf-8")
        start = text.index(_M4_M5_START_MARKER)
        end = text.index(_M4_M5_END_MARKER, start)
        excerpt = text[start:end].strip()
        if not excerpt:
            return _M4_M5_FALLBACK
        return (
            f"**Contratos de invocacion (M4/M5, lectura en vivo de "
            f"{_M4_M5_SOURCE_REL.as_posix()})**:\n\n{excerpt}"
        )
    except Exception:
        return _M4_M5_FALLBACK


def _read_source() -> str:
    """Campo `source` del payload de SessionStart, o "" si no se puede leer.

    WOT-2026-100a. NUNCA propaga: la deteccion de `source` no puede ser la razon
    de que una sesion arranque sin memoria. Un payload vacio, no-JSON, no-dict,
    sin `source` o con un `source` no-string devuelve "" -- que enruta al
    fallback fail-open (indice completo). Drena stdin en todos los casos, para no
    dejar la tuberia del llamante a medias.
    """
    try:
        raw = sys.stdin.buffer.read()
        if not raw:
            return ""
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            return ""
        source = payload.get("source")
        return source if isinstance(source, str) else ""
    except Exception:
        return ""


def _load_context(
    root: Path, source: str = "", budget: int | None = None
) -> str | None:
    """Indice ACOTADO de memoria; ``""`` si el corpus esta vacio, ``None`` si fallo.

    Diseno v6 (2026-10-23): TODAS las fuentes (`startup`, `clear`, `resume`,
    `compact`, `fork`, desconocida) usan `get_session_index(budget)`. Antes
    `startup` inyectaba ~33.6k chars y `resume`/`compact` ~29.1k, ambos por
    encima del tope de 10k de `additionalContext` de Claude Code. `source` se
    conserva en la firma por trazabilidad (WOT-2026-100a), ya no elige puerta.

    Nunca propaga: este hook es fail-open por contrato (ver docstring del
    modulo). Un `except Exception` amplio es lo correcto AQUI y solo aqui --
    cualquier fallo de importacion, de topologia o de parseo debe degradar a
    "sin memoria" (``None``, que el llamante distingue de corpus vacio), jamas
    impedir que la sesion abra.
    """
    del source  # ya no decide la puerta; ver docstring
    try:
        import os

        motor = _motor_root(root)

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
        # El anclaje vive SOLO durante la lectura y se restaura (ronda 5,
        # codex): ahora el ensamblador tambien se llama in-process desde el
        # CLI, y una variable global puesta y no restaurada es un state-leak.
        previous = os.environ.get("AGENT_PROJECT_ROOT")
        os.environ["AGENT_PROJECT_ROOT"] = str(anchor)
        try:
            if str(motor) not in sys.path:
                sys.path.insert(0, str(motor))

            from bus.memory_loader import INDEX_BUDGET_CHARS, get_session_index

            return get_session_index(INDEX_BUDGET_CHARS if budget is None else budget)
        finally:
            if previous is None:
                os.environ.pop("AGENT_PROJECT_ROOT", None)
            else:
                os.environ["AGENT_PROJECT_ROOT"] = previous
    except Exception:
        return None


def _cap(text: str, limit: int, label: str) -> str:
    """``text`` recortado a ``limit`` chars, declarando el corte."""
    if len(text) <= limit:
        return text
    note = f"\n[{label} recortado a {limit} chars]"
    if limit <= len(note):
        return text[: max(0, limit)]
    return text[: limit - len(note)].rstrip() + note


def assemble_session_context(  # noqa: C901 - degradacion por prioridad + 3 estados de memoria: ramas inherentes
    root: Path,
    index_for_budget,
    max_chars: int | None = None,
    index_budget: int | None = None,
) -> tuple[str, bool]:
    """Ensambla el contexto de arranque ACOTADO (hook y `memory_context.py --bootstrap`).

    Diseno v6: UN ensamblador para todos los backends. Prioridad de
    presupuesto: pista de momentos > roles > M4/M5 > salud > indice (el indice
    recibe lo que queda, con techo `INDEX_BUDGET_CHARS`). Orden de EMISION:
    pista, indice, salud, roles, M4/M5 (el de siempre, para que la memoria
    vaya primero).

    Before: ``root`` es la raiz resuelta; ``index_for_budget(budget)`` devuelve
        el indice (``""`` vacio, ``None`` fallo) y no escribe el entorno del
        proceso -- el llamante ancla la memoria.
    During: lee roles, M4/M5 y salud (subproceso de solo lectura); sin
        escrituras.
    After: ``(contexto, memoria_fallo)`` con ``len(contexto) <= max_chars``.
        Tres estados de memoria distintos: fallo de carga (`_LOAD_FAILED`,
        ``memoria_fallo=True``), corpus vacio (`_LOAD_EMPTY`) e indice omitido
        por presupuesto (`_LOAD_NO_BUDGET`). Si las partes fijas no dejan
        `_MIN_INDEX_BUDGET`, se degradan (salud, M4/M5 a fallback, roles) antes
        de omitir el indice; el bloque del indice nunca se corta. Nunca lanza.
    """
    try:
        motor = str(_motor_root(root))
        if motor not in sys.path:
            sys.path.insert(0, motor)
        import bus.memory_loader as loader

        index_cap = loader.INDEX_BUDGET_CHARS
        session_cap = loader.SESSION_CONTEXT_MAX_CHARS
    except Exception:
        index_cap, session_cap = 4300, 9000
    # `None` y 0 NO son lo mismo (ronda 5, codex): `x or default` convertia un
    # tope explicito de 0 en el valor por defecto.
    limit = session_cap if max_chars is None else max_chars
    wanted = index_cap if index_budget is None else index_budget

    roles = _role_section(root)
    m4m5 = _cap(_m4_m5_section(root), _M4_M5_CAP, "M4/M5")
    # `_health_line` ya se acota conservando la accion; el `_cap` aqui es la red
    # de seguridad (idempotente) por si un sustituto devuelve algo mayor.
    health = _cap(_health_line(root), _HEALTH_CAP, "Salud")

    def _used() -> int:
        return sum(len(p) + 2 for p in (_EXPANSION_HINT, health, roles, m4m5) if p)

    # Si las partes fijas no dejan sitio al indice minimo, se degradan en orden
    # inverso de prioridad (salud, M4/M5 a su fallback corto, roles) ANTES de
    # tocar nada mas: asi el recorte final nunca cae dentro del bloque del
    # indice (ronda 5, kilo #7).
    for degrade in ("health", "m4m5", "roles"):
        if limit - _used() - 2 >= _MIN_INDEX_BUDGET:
            break
        if degrade == "health":
            health = ""
        elif degrade == "m4m5":
            m4m5 = _M4_M5_FALLBACK
        else:
            roles = ""
    budget = min(wanted, max(0, limit - _used() - 2))

    failed = False
    if budget < _MIN_INDEX_BUDGET:
        # Tercer estado (ronda 5): ni fallo de carga ni corpus vacio.
        memory_part = _LOAD_NO_BUDGET
    else:
        try:
            memory = index_for_budget(budget)
        except Exception:
            memory = None
        failed = memory is None
        if failed:
            memory_part = _LOAD_FAILED
        elif not memory:
            memory_part = _LOAD_EMPTY
        else:
            memory_part = memory

    parts = [_EXPANSION_HINT, memory_part, health, roles, m4m5]
    context = "\n\n".join(p.strip("\n") for p in parts if p)
    if len(context) > limit:
        # Ultimo recurso (solo si la pista sola excede el tope): aqui ya no hay
        # bloque de indice que partir, porque sin presupuesto no se emite.
        context = _cap(context, limit, "Contexto de arranque")
    return context, failed


def _payload(context: str, system_message: str | None = None) -> dict:
    """Payload con el esquema DOCUMENTADO de SessionStart de Claude Code.

    Diseno v6, P0. Claude Code solo lee `hookSpecificOutput.additionalContext`
    (con `hookEventName: "SessionStart"`). Durante meses este hook emitio
    `{"additionalContext": ...}` en la RAIZ: 577 ejecuciones `hook_success` en
    219 sesiones y CERO `hook_additional_context` -- el emisor funcionaba y el
    consumidor lo descartaba. `systemMessage` (raiz) se muestra al usuario.
    """
    payload: dict = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }
    if system_message:
        payload["systemMessage"] = system_message
    return payload


def _print_context_safely(context: str, system_message: str | None = None) -> None:
    """Print the `additionalContext` JSON, tolerant of the terminal's encoding.

    WOT (M4/M5 encoding hardening, 2026-10-15). Medido en vivo: en Windows,
    cuando stdout no es un terminal UTF-8, `print()` codifica con la pagina
    de codigos del sistema (p.ej. `cp1252`). Un SOLO caracter no-ASCII en
    TODO el corpus de memoria (encontrado: una "o" cirilica corrupta en una
    entrada de hace 5 meses, `observations.2026-07.jsonl`) hacia que
    `UnicodeEncodeError` propagara sin capturar hasta el `except Exception`
    de `__main__`, que lo trata igual que "archive corrupto" y degrada a
    `{"additionalContext": ""}` -- PERDIDA TOTAL de memoria, salud, roles y
    M4/M5, no solo del caracter problematico.

    WOT-2026-110a. Aquel hardening reaccionaba al fallo, pero el defecto
    SEGUIA emitiendose: con cwd=destino y `PYTHONIOENCODING=cp1252` el JSON
    salia con bytes de la codepage (medido 2026-10-21: una raya U+2014 del
    archive salia como el byte 0x97 y `stdout.decode("utf-8")` fallaba). Un
    consumidor que decodifica UTF-8 estricto -- lo que hace cualquier
    consumidor JSON -- recibe bytes invalidos ANTES de poder parsear nada.
    `ensure_ascii=True` es la correccion: el payload queda en ASCII puro,
    codificable byte a byte en cualquier codepage, y `json.loads` recupera
    el caracter original a partir del escape `\\uXXXX`.

    Before: `context` es el texto final (memoria + salud + roles + M4/M5).
    During: serializa con `ensure_ascii=True`; si aun asi `print` lanza
        `UnicodeEncodeError` (stdout con una codificacion que no admite ni
        ASCII), re-codifica el payload a los bytes de `sys.stdout.encoding`
        (o UTF-8 si no se puede determinar) con `errors="backslashreplace"` y
        escribe los bytes directamente. Esa rama se CONSERVA por contrato
        (WOT-2026-110a, 4/4 lentes): con `ensure_ascii=True` deja de ser
        alcanzable por un caracter no codificable real, pero sigue siendo la
        red de seguridad del unico canal de salida del hook.
    After: SIEMPRE imprime algo -- nunca degrada a contexto vacio por este
        motivo. Solo un fallo de un tipo DISTINTO (no de codificacion)
        seguiria propagando al `except Exception` de `__main__`.
    """
    payload = json.dumps(_payload(context, system_message), ensure_ascii=True)
    try:
        print(payload)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        safe_bytes = payload.encode(encoding, errors="backslashreplace")
        sys.stdout.buffer.write(safe_bytes + b"\n")
        sys.stdout.flush()


def main() -> int:
    # El payload decide la puerta de memoria (WOT-2026-100a); `_read_source`
    # drena stdin en TODOS los casos (tambien si no trae `source`), para no
    # dejar la tuberia del llamante a medias.
    source = _read_source()

    root = _resolve_root()
    # Salud y roles se OMITEN si fallan (WOT-2026-089e/098b); M4/M5 nunca se
    # omite, cae a su fallback. Todo lo ensambla `assemble_session_context`.
    context, failed = assemble_session_context(
        root, lambda budget: _load_context(root, source, budget)
    )
    _print_context_safely(
        context,
        "Memoria del proyecto no cargada en el arranque: ejecuta "
        "`python scripts/memory_context.py --bootstrap`."
        if failed
        else None,
    )
    return 0


if __name__ == "__main__":
    # Fail-open absoluto: ni siquiera un fallo inesperado en `main()` puede
    # impedir que la sesion abra. Mismo esquema documentado y el imperativo
    # agnostico, nunca un contexto vacio mudo.
    try:
        sys.exit(main())
    except Exception:
        print(json.dumps(_payload(_LOAD_FAILED + "\n\n" + _EXPANSION_HINT)))
        sys.exit(0)
