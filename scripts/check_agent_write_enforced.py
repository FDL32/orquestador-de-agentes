"""WOT-2026-048h: `write: false` se ENFORCE, o el gate lo dice por su nombre.

Cierra la laguna DECLARADA (no escondida) de `WOT-2026-048k`: el docstring de
`_render_readonly_agent_flag` admite que un backend con `write: false` y SIN
`readonly_agent` devuelve `[]` en SILENCIO -- la restriccion no se cablea y
nadie se entera. `write: false` vuelve a ser decorativo para ese par.

POR QUE UN GATE EXTERNO Y NO UN FAIL-CLOSED DENTRO DE LA FUNCION (NON-GOAL de
la ficha, y es una decision MEDIDA, no una preferencia): hacer que
`_render_readonly_agent_flag` lance tumbaria el ensemble ENTERO, incluidos los
perfiles `channel: api` -- que van por HTTP, no tienen system prompt de agente
ni permisos de FS, y por tanto NUNCA tuvieron el vector. Eso es el fail-closed
prematuro que 048k descarto con razon. La asimetria con `_render_model_flag`
(que si lanza) es deliberada.

EL CRITERIO, y por que es el que evita que el gate se relaje solo: se exige
enforcement SOLO a los perfiles con VECTOR REAL, es decir `channel: agent`. Un
gate que exigiera `readonly_agent` a un backend HTTP seria over-gating, y un
gate que grita donde no hay riesgo acaba desactivado o con allowlist -- que es
como mueren los gates. Aqui la poblacion vigilada es exactamente la que puede
escribir en disco.

Before: `agents.json` resoluble con `ensemble_profiles` y `backends`.
During: read-only. Empareja cada perfil `channel: agent` + `write: false` con su
    backend y comprueba que el backend declara `readonly_agent`.
After: exit 0 si no hay pares huerfanos; exit 1 nombrando CADA par
    (perfil, backend) que declara `write: false` sin poder enforcearlo. Exit 2
    si la config no es legible (fail-closed: no poder mirar no es estar limpio).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


# El vector de escritura solo existe cuando el backend corre como AGENTE con
# acceso al arbol. `channel: api` es HTTP puro: sin system prompt de agente y
# sin permisos de FS. Vigilar esos seria over-gating (ver docstring).
VECTOR_CHANNELS = {"agent"}

# Herramientas capaces de MUTAR el arbol. Si una allowlist las excluye todas,
# el backend no puede escribir aunque el modelo lo intente. Se enumeran las
# mutadoras (lista corta y estable) en vez de las de lectura: una allowlist de
# lectura desactualizada dejaria pasar una herramienta nueva de escritura.
WRITE_CAPABLE_TOOLS = {
    "Bash",
    "Edit",
    "Write",
    "NotebookEdit",
    "MultiEdit",
    "Task",
    "Agent",
}


def has_native_sandbox(backend: dict) -> bool:
    """El backend declara en sus `args` un enforcement de solo lectura.

    Dos formas VALIDAS, ambas verificadas por canario el 2026-08-05:
      - sandbox nativo del CLI: par adyacente (`--sandbox`|`-s`, `read-only`).
        `--sandbox` suelto no acredita nada, y `workspace-write` /
        `danger-full-access` son modos de ESCRITURA.
      - allowlist de herramientas sin ninguna mutadora (forma de `claude`):
        `--tools Read,Grep,Glob`. Se comprueba contra `WRITE_CAPABLE_TOOLS`
        (se enumeran las MUTADORAS, no las de lectura: una allowlist de
        lectura desactualizada dejaria pasar una herramienta nueva).

    Before: `backend` es el dict de un backend de `agents.json`.
    During: puro, sin I/O.
    After: True sii los args acreditan que el backend no puede escribir.
    """
    args = [str(a) for a in (backend.get("args") or [])]
    for i, a in enumerate(args[:-1]):
        if a in ("--sandbox", "-s") and args[i + 1] == "read-only":
            return True
        if a in ("--tools", "--allowedTools", "--allowed-tools"):
            granted = {t.strip() for t in args[i + 1].replace(",", " ").split()}
            if granted and not (granted & WRITE_CAPABLE_TOOLS):
                return True
    return False


def find_unenforced_pairs(config: dict) -> list[dict]:
    """Pares (perfil, backend) que declaran `write: false` y no pueden enforcearlo.

    Before: `config` es el dict de `agents.json` ya parseado.
    During: puro, sin I/O. Recorre `ensemble_profiles` y resuelve su backend.
    After: lista de dicts `{profile, backend, channel}`. Vacia = todo enforceado.
        Un perfil cuyo backend NO existe en `backends` tambien se reporta: no se
        puede acreditar enforcement contra un backend que no esta declarado.
    """
    backends = config.get("backends") or {}
    out: list[dict] = []

    for name, profile in (config.get("ensemble_profiles") or {}).items():
        if profile.get("channel") not in VECTOR_CHANNELS:
            continue
        if profile.get("write") is not False:
            continue
        backend_name = profile.get("backend")
        backend = backends.get(backend_name)
        if backend is not None and has_native_sandbox(backend):
            # Segunda forma VALIDA de enforcement, anadida 2026-08-05 tras un
            # incidente real: una lente codex con `write: false` ESCRIBIO en el
            # workspace de otra sesion (4 ficheros de estado). `readonly_agent`
            # es el mecanismo de opencode; codex no lo tiene, pero SI trae un
            # sandbox nativo (`--sandbox read-only`) que el backend puede
            # declarar en sus `args`. Reconocerlo cierra el vector sin obligar a
            # inventar un "agente readonly" que ese CLI no soporta.
            # Verificado por CANARIO: con el flag, un encargo que pide crear un
            # fichero no lo crea; sin el, escribe.
            continue
        if backend is None or not backend.get("readonly_agent"):
            out.append(
                {
                    "profile": name,
                    "backend": backend_name,
                    "channel": profile.get("channel"),
                    "backend_declared": backend is not None,
                }
            )
    return out


# WOT-2026-086 (DEC-086P10-001): comprobacion DINAMICA. `find_unenforced_pairs`
# solo mira si el backend DECLARA `readonly_agent`; nunca si ese agente EXISTE
# desde el cwd real donde `resolve_lens_repo_root` va a lanzar la lente. Fue
# como `challenger_opencode_glm_5_2` (readonly_agent: auditor, repo_scope:
# destino) paso el gate estatico en verde mientras corria con permisos de
# escritura reales: `auditor.md` solo vivia en `<motor>/.opencode/agents/`, y
# con `cwd=<destino>` opencode caia al agente por defecto (`build`).
_AGENT_LINE_RE = re.compile(r"^([a-zA-Z0-9_-]+)\b")

# WOT-2026-059j: formato de salida real medido de `<backend> agent list`:
# una linea sin indentacion con "nombre (primary)" o "nombre (secondary)",
# seguida de un bloque JSON tipo array indentado con espacios, hasta la linea
# que es exactamente "]". Este parser extrae los permisos reales de cada
# agente sin necesidad de I/O adicional.
_AGENT_HEADER_RE = re.compile(r"^([a-zA-Z0-9_-]+)\s+\(")


def _try_parse_block(
    agent_name: str, lines: list[str], result: dict[str, list[dict]]
) -> None:
    """Intenta parsear y añadir un bloque de permisos al resultado.

    Si el bloque reconstruido es JSON valido y es un array, se añade a
    `result[agent_name]`. Si no, se ignora sin elevar excepcion.
    """
    block_text = _reconstruct_block(lines)
    if block_text:
        try:
            parsed = json.loads(block_text)
            if isinstance(parsed, list):
                result[agent_name] = parsed
        except (json.JSONDecodeError, ValueError):
            pass  # bloque invalido: se ignora


def _parse_agent_permission_blocks(stdout: str) -> dict[str, list[dict]]:
    """Parsea el stdout crudo de `<backend> agent list` en un dict de permisos.

    Before: `stdout` es la salida literal del proceso `agent list` (formato real
        medido: cabeceras "nombre (primary/secondary)" sin indentacion seguidas
        de un bloque JSON tipo array hasta una linea `]`).
    During: puro, sin I/O. Recorre linea por linea, detecta cabeceras con regex,
        y recopila bloques JSON. El contenido entre `[` y `]` se reconstruye
        como JSON valido (el formato real de opencode pone la coma del array
        en linea separada del objeto siguiente).
    After: dict `{agent_name: [perm_dict1, perm_dict2, ...]}` en el orden de
        aparicion. Un bloque vacio devuelve lista vacia. Si un bloque JSON es
        invalido se ignora (no se eleva la excepcion: mejor omitir que fallar).
    """
    result: dict[str, list[dict]] = {}
    current_agent: str | None = None
    block_lines: list[str] = []
    in_block = False

    for line in stdout.splitlines():
        m = _AGENT_HEADER_RE.match(line)
        if m:
            # Bloque anterior: anadir ] si falta (truncado por nuevo header)
            if current_agent is not None:
                if "]" not in block_lines:
                    block_lines.append("]")
                _try_parse_block(current_agent, block_lines, result)
                block_lines = []

            current_agent = m.group(1)
            result.setdefault(current_agent, [])
            in_block = True
            continue

        if in_block and current_agent is not None:
            stripped = line.strip()
            if stripped == "]":
                # Cierre de bloque: anadir ] para que _reconstruct_block
                # lo incluya en el JSON reconstruido.
                block_lines.append("]")
                _try_parse_block(current_agent, block_lines, result)
                in_block = False
                block_lines = []
            else:
                # Recopilar linea del bloque JSON (stripped de indentacion)
                block_lines.append(stripped)

    # Cerrar ultimo bloque si queda abierto
    if current_agent is not None and block_lines:
        if "]" not in block_lines:
            block_lines.append("]")
        _try_parse_block(current_agent, block_lines, result)

    return result


def _reconstruct_block(lines: list[str]) -> str | None:
    """Reconstruye un bloque JSON de `agent list` permisos en un string valido.

    Las lineas vienen de strip() de la salida real de opencode. El formato real
    tiene objetos del array en lineas separadas con la coma al final del objeto:
        { ... }
      },
      { ... }
    Al strip/join sin tratamiento, esto produce JSON invalido (coma en linea
    separada del objeto siguiente). Se corrige fusionando `},` con el `{`
    siguiente en `},{`.
    """
    if not lines:
        return None
    raw_parts: list[str] = []
    skip_next_open = False
    for i, line in enumerate(lines):
        if skip_next_open and line.startswith("{"):
            # El `{` siguiente a `},` ya fue fusionado: saltarlo.
            skip_next_open = False
            continue
        skip_next_open = False
        if line == "[":
            raw_parts.append("[")
        elif line == "]":
            raw_parts.append("]")
        elif line == "},":
            # Verificar si la siguiente linea es un objeto (seguira en el array)
            if i + 1 < len(lines) and lines[i + 1].startswith("{"):
                raw_parts.append("},{")
                skip_next_open = True
            else:
                raw_parts.append("}")
        else:
            raw_parts.append(line)
    return "".join(raw_parts)


def _agent_permission_rules(
    executable: str, cwd: str, agent_name: str
) -> list[dict] | None:
    """Obtiene la lista COMPLETA de reglas de permisos de un agente.

    Before: `executable` es el binario del backend; `cwd` es la raiz desde la que
        se lanzaria; `agent_name` es el nombre del agente a consultar.
    During: ejecuta `<executable> agent list`, parsea con
        `_parse_agent_permission_blocks`. Lanza RuntimeError si el proceso falla
        (rc!=0), igual que `_list_agents`.
    After: lista COMPLETA de reglas (orden de aparicion) si el agente existe;
        None si no aparece en el listado. Lista vacia si existe sin reglas.
        NUNCA parsea stdout de un proceso fallido.
    """
    proc = subprocess.run(  # noqa: S603 - executable/cwd vienen de agents.json
        [executable, "agent", "list"],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
        shell=False,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"'{executable} agent list' salio con rc={proc.returncode}: "
            f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        )
    blocks = _parse_agent_permission_blocks(proc.stdout or "")
    if agent_name not in blocks:
        return None
    return blocks[agent_name]


# Tipos de permiso capaces de MUTAR el arbol en el vocabulario de opencode.
# Espejo de `WRITE_CAPABLE_TOOLS` (arriba) pero a nivel de `agent list`:
# coincide exactamente con los 4 permisos que `.opencode/agents/auditor.md`
# deniega explicitamente (edit/bash/task/todowrite).
WRITE_CAPABLE_PERMISSIONS = {"edit", "bash", "task", "todowrite"}


def _effective_action(rules: list[dict], permission: str) -> str | None:
    """Accion EFECTIVA de un tipo de permiso tras aplicar last-match-wins.

    Before: `rules` es la lista COMPLETA de reglas de un agente (no solo la
        primera); `permission` es el tipo exacto a resolver (p.ej. "edit").
    During: puro, sin I/O. Recorre las reglas en orden; una regla cuyo
        `permission` es EXACTAMENTE `permission` o la generica `"*"` puede fijar
        la accion vigente -- la ULTIMA que matchea (de cualquiera de las dos
        formas) gana. Esto refleja el formato REAL medido de `opencode agent
        list` (2026-10-25): la regla generica allow-all siempre aparece
        PRIMERO para TODO agente, y las reglas especificas por tipo que la
        sobreescriben vienen despues en la misma lista.
    After: "allow"/"ask"/"deny" segun la ULTIMA regla que matchea `permission`
        o `"*"`; None si ninguna regla matchea (ausencia total de dato).
    """
    effective: str | None = None
    for rule in rules:
        rule_perm = rule.get("permission")
        if rule_perm == permission or rule_perm == "*":
            action = rule.get("action")
            if action is not None:
                effective = action
    return effective


def _permissive_write_permissions(rules: list[dict] | None) -> list[str]:
    """Permisos de ESCRITURA cuya accion efectiva resuelve a "allow".

    Before: `rules` es la lista COMPLETA de reglas de un agente (o None/vacia
        si no se pudo determinar).

    MEDIDO 2026-10-25 (sesion de cierre nocturno-alvarovans-20261024): la
    version anterior de esta comprobacion (`_is_permissive_rule` sobre
    `rules[0]`) daba FALSO POSITIVO para TODO agente, incluido uno
    correctamente restringido -- `build`, `plan`, `manager` y `auditor`
    muestran identicamente `{permission: "*", action: "allow", pattern: "*"}`
    como primera regla (confirmado via `opencode agent list` real desde el
    cwd del destino); las reglas especificas que SI restringen (`edit: deny`,
    `bash: deny`, `task: deny`, `todowrite: deny` para `auditor`, coincidiendo
    con su YAML) aparecen mas abajo en la MISMA lista y nunca se miraban.

    During: puro, sin I/O. Resuelve la accion EFECTIVA (last-match-wins) de
        cada permiso en `WRITE_CAPABLE_PERMISSIONS` via `_effective_action`.
    After: lista (puede ser vacia) de los permisos de escritura cuya accion
        efectiva es "allow" -- vacia significa que todos resuelven a
        "deny"/"ask", o que `rules` es None/vacia (no se puede afirmar
        permisividad sin datos).
    """
    if not rules:
        return []
    return sorted(
        perm
        for perm in WRITE_CAPABLE_PERMISSIONS
        if _effective_action(rules, perm) == "allow"
    )


def _list_agents(executable: str, cwd: str) -> list[str]:
    """Nombres de agentes que `<executable> agent list` reporta desde `cwd`.

    Before: `executable` es el binario del backend (`opencode`); `cwd` es la
        raiz real desde la que se lanzaria la lente.
    During: ejecuta el subproceso, sin red ni gasto de modelo -- es metadata
        del CLI, no una llamada a un backend LLM. Parsea la primera palabra de
        cada linea no vacia (formato real medido: `build (primary)`,
        `auditor (primary)`, una entrada por linea).
    After: lista de nombres de agente. Lanza si el proceso NO existe/timeout, y
        TAMBIEN si `returncode != 0` (RuntimeError con stdout+stderr) -- un CLI
        que falla puede emitir en stdout un mensaje de error que por casualidad
        contenga el nombre del agente buscado (p.ej. `"auditor: not found"`),
        y parsear esa salida como listado valido seria un FALSO OK del gate de
        seguridad: exactamente el riesgo que 5/5 lentes del bucle adversarial
        de WOT-2026-086 senalaron (BA13/BA24/BA30/BA05, mas BA11 en menor
        severidad). El caller decide como reportar el fallo -- fail-closed,
        nunca "no pude listar, doy por bueno".
    """
    proc = subprocess.run(  # noqa: S603 - executable/cwd vienen de agents.json, no de input externo
        [executable, "agent", "list"],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
        shell=False,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"'{executable} agent list' salio con rc={proc.returncode}: "
            f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        )
    names: list[str] = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line or line.startswith(("[", "{")):
            continue
        m = _AGENT_LINE_RE.match(line)
        if m:
            names.append(m.group(1))
    return names


def find_dynamic_unenforced_pairs(
    config: dict, *, motor_root: str, project_root: str
) -> list[dict]:
    """Pares (perfil, backend) cuyo `readonly_agent` DECLARADO no existe o es permisivo.

    Before: `config` es `agents.json` ya parseado; `motor_root`/`project_root`
        son las raices reales del motor y del destino-rol.
    During: read + un subproceso de metadata por perfil vigilado (sin tocar el
        arbol). Solo se examinan los perfiles `channel: agent` con `write:
        false` y `readonly_agent` declarado (los que la comprobacion estatica
        YA acepto -- este paso audita si esa aceptacion es real). El cwd se
        resuelve con `resolve_lens_repo_root` (no se reimplementa la
        resolucion de ambito): `repo_scope: destino` -> `project_root`;
        cualquier otro caso -> `motor_root`.
    After: lista de dicts `{profile, backend, missing_agent, cwd}` (mas
        `error` si `_list_agents` lanzo) O `{profile, backend, permissive_agent,
        open_permissions, cwd}` para el caso WOT-2026-059j de permiso
        permisivo (`open_permissions` es la lista de permisos de escritura
        cuya accion efectiva resuelve a "allow", ver
        `_permissive_write_permissions`). Vacia = todo enforceado. Un fallo
        del subproceso SE REPORTA, nunca se da por bueno en silencio (misma
        disciplina fail-closed del resto del gate).
    """
    backends = config.get("backends") or {}
    out: list[dict] = []

    for name, profile in (config.get("ensemble_profiles") or {}).items():
        if profile.get("channel") not in VECTOR_CHANNELS:
            continue
        if profile.get("write") is not False:
            continue
        backend_name = profile.get("backend")
        backend = backends.get(backend_name) or {}
        agent = backend.get("readonly_agent")
        if not agent:
            continue  # sin agente declarado: lo cubre find_unenforced_pairs.
        cwd = project_root if profile.get("repo_scope") == "destino" else motor_root
        executable = backend.get("executable") or backend_name
        try:
            available = _list_agents(executable, cwd)
        except Exception as exc:
            out.append(
                {
                    "profile": name,
                    "backend": backend_name,
                    "missing_agent": agent,
                    "cwd": cwd,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        if agent not in available:
            out.append(
                {
                    "profile": name,
                    "backend": backend_name,
                    "missing_agent": agent,
                    "cwd": cwd,
                }
            )
            continue
        # WOT-2026-059j (corregido 2026-10-25, ver docstring de
        # `_permissive_write_permissions`): el agente existe, verificar que
        # sus permisos de ESCRITURA (edit/bash/task/todowrite) no resuelvan a
        # "allow" tras aplicar last-match-wins sobre la lista COMPLETA de
        # reglas -- no solo la primera.
        try:
            rules = _agent_permission_rules(executable, cwd, agent)
        except Exception as exc:
            out.append(
                {
                    "profile": name,
                    "backend": backend_name,
                    "missing_agent": agent,
                    "cwd": cwd,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        open_permissions = _permissive_write_permissions(rules)
        if open_permissions:
            out.append(
                {
                    "profile": name,
                    "backend": backend_name,
                    "missing_agent": None,
                    "permissive_agent": agent,
                    "open_permissions": open_permissions,
                    "cwd": cwd,
                }
            )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default=".agent/config/agents.json",
        help="ruta a agents.json (default: .agent/config/agents.json)",
    )
    parser.add_argument(
        "--check-dynamic",
        action="store_true",
        help=(
            "ademas de la comprobacion estatica, verifica que cada "
            "readonly_agent declarado EXISTE desde el cwd real (requiere "
            "--motor-root y --project-root; WOT-2026-086, DEC-086P10-001)"
        ),
    )
    parser.add_argument("--motor-root", help="raiz del motor (para --check-dynamic)")
    parser.add_argument(
        "--project-root", help="raiz del destino-rol (para --check-dynamic)"
    )
    args = parser.parse_args(argv)
    if args.check_dynamic and not (args.motor_root and args.project_root):
        print(
            "[agent-write] ERROR: --check-dynamic exige --motor-root y --project-root",
            file=sys.stderr,
        )
        return 2
    path = Path(args.config)
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        # Fail-closed: no poder LEER la config no es lo mismo que estar limpio.
        print(f"[agent-write] ERROR: no se pudo leer {path}: {exc}", file=sys.stderr)
        return 2

    pairs = find_unenforced_pairs(config)
    if not pairs:
        print(
            "[agent-write] OK: todo perfil con vector (channel: agent) y "
            "write:false tiene backend con readonly_agent."
        )
        if args.check_dynamic:
            return _run_dynamic_check(config, args.motor_root, args.project_root)
        return 0
    print(
        "[agent-write] FALLO: hay perfiles que declaran write:false sin poder "
        "enforcearlo -- la restriccion es DECORATIVA para estos pares:",
        file=sys.stderr,
    )
    for p in pairs:
        falta = (
            "el backend no esta declarado en `backends`"
            if not p["backend_declared"]
            else "el backend no declara `readonly_agent`"
        )
        print(
            f"  - perfil '{p['profile']}' (channel: {p['channel']}) -> "
            f"backend '{p['backend']}': {falta}",
            file=sys.stderr,
        )
    print(
        "\nRemedio: declara `readonly_agent` en el backend, o cambia el perfil a "
        "un backend que lo tenga. NO 'arregles' esto quitando `write: false`: "
        "eso silencia el gate sin quitar el vector.",
        file=sys.stderr,
    )
    return 1


def _run_dynamic_check(config: dict, motor_root: str, project_root: str) -> int:
    dyn_pairs = find_dynamic_unenforced_pairs(
        config, motor_root=motor_root, project_root=project_root
    )
    if not dyn_pairs:
        print(
            "[agent-write] OK (dinamico): todo readonly_agent declarado existe "
            "desde el cwd real de su perfil y no tiene permisos permisivos."
        )
        return 0

    confirmed = [p for p in dyn_pairs if not p.get("error")]
    measurement_failed = [p for p in dyn_pairs if p.get("error")]

    # Separar "agente permisivo" de "agente ausente"
    permissive = [p for p in confirmed if p.get("permissive_agent") is not None]
    missing = [p for p in confirmed if p.get("permissive_agent") is None]

    has_issues = bool(permissive or missing or measurement_failed)

    if has_issues:
        print(
            "[agent-write] FALLO (dinamico): problemas con readonly_agent "
            "declarado desde el cwd real de su perfil:",
            file=sys.stderr,
        )

    if permissive:
        print(
            "\n  Permisos REALMENTE PERMISIVOS (vector de escritura CONFIRMADO):",
            file=sys.stderr,
        )
        for p in permissive:
            open_perms = ", ".join(p.get("open_permissions", []))
            print(
                f"  - perfil '{p['profile']}' -> backend '{p['backend']}': "
                f"agente '{p['permissive_agent']}' resuelve a allow para: "
                f"{open_perms}",
                file=sys.stderr,
            )

    if missing:
        print(
            "\n  Agentes AUSENTES del listado real:",
            file=sys.stderr,
        )
        for p in missing:
            print(
                f"  - perfil '{p['profile']}' -> backend '{p['backend']}': "
                f"agente '{p['missing_agent']}' ausente en cwd={p['cwd']}",
                file=sys.stderr,
            )

    if measurement_failed:
        print(
            "\n  Medicion FALLIDA (CLI no disponible, timeout, etc.):",
            file=sys.stderr,
        )
        for p in measurement_failed:
            print(
                f"  - perfil '{p['profile']}' -> backend '{p['backend']}': "
                f"agente '{p['missing_agent']}': {p.get('error', 'error desconocido')}",
                file=sys.stderr,
            )

    print(
        "\nRemedio: para perfiles permisivos, corrige los permisos reales del "
        "agente (NO con este gate). Para agentes ausentes, crea el agente "
        "declarado en el cwd real (p.ej. copia el .opencode/agents/<nombre>.md "
        "al destino), o corrige repo_scope/cwd del perfil. Ver "
        "DEC-086P10-001 y WOT-2026-059j.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
