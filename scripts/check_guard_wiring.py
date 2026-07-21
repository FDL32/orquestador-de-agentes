#!/usr/bin/env python3
r"""Guard-of-guards: a guard nobody invokes is a norm, not a barrier (WOT-2026-024u).

Un guard esta WIRED sii una superficie que CORRE SOLA alcanza una POSICION DE
EJECUCION cuyo argumento es (transitivamente, con UN salto interprocedural) el
nombre de ese guard. Dos ejes ortogonales; ambos deben ser verdad:

  EJE FRONTERA  -- la superficie corre sola: un hook de pre-commit no-manual, un
    step de workflow bajo push/pull_request sin `if:false`, el `command` de un
    hook de settings.json, y el cuerpo (mas su cierre de imports) de prepush /
    session_closeout / closeout_steps / preflight / el controller. Prompts,
    skills, comentarios, docstrings y TESTS no son superficies: son normas.

  EJE POSICION  -- el nombre esta como argumento de un SINK de lista CERRADA
    (subprocess.*, os.system/exec*, runpy, importlib.import_module,
    spec_from_file_location, exec/eval, un import, o un callable INYECTADO por
    parametro), o fluye a el por UN salto: (a) una variable de fichero asignada
    con el string; (b) un wrapper local (una funcion del mismo fichero que
    contiene un sink es ella misma un sink); (c) el return con nombre resuelto de
    una funcion local. En YAML/JSON, el `entry:` / `run:` / `command` ES la
    posicion (se tokeniza como linea de comando).

Todo lo demas es UNWIRED por defecto (FAIL-CLOSED). Un print, un help=, un
mensaje de error, una clave de dict, un `name:` de hook, una lista de bullets, un
`SKIP_GUARDS`, un `if False:`, un `permissions.deny`, un `stages:[manual]`, un
`workflow_dispatch` -- ninguno alcanza un sink bajo una superficie que corre sola.
Preferimos SIEMPRE un falso-UNWIRED ruidoso (el guard grita "declara esto") a un
falso-WIRED silencioso (que apaga la asimetria sin avisar).

Por que existe (y por que esta es la 4a version)
------------------------------------------------
El 2026-07-14 el mismo fallo salio cinco veces en un dia: el guard existia,
funcionaba, era fail-closed... y nada lo invocaba. v1 bendecia COMENTARIOS de
YAML; v2 filtraba comentarios y conservaba cualquier CONSTANTE STRING (print,
help=); v3 clasificaba por CONTENEDOR (listas, path-chains) -- 54 de 56
construcciones de prosa salian WIRED. Las tres midieron su propiedad con una vara
mas floja que la que predican y salieron verdes: 16 tests, 4 gates y 4094 de
suite pasaron sobre el defecto, porque todos eran hermeticos y el fallo vivia en
la frontera con el repo REAL. Los cazo una auditoria adversarial en contexto
fresco. Un workflow de recon+diseno+ataque (3+3+6 agentes) refuto por ejecucion
la "restriccion dura" que yo daba por cierta: posicion + 1 salto SI decide el
cableado aqui (12/12 cableados reales, 0 regresiones), medido en el repo vivo.

La asimetria -- ahora DOBLE (WOT-2026-024u, hallazgo del des-cableado)
---------------------------------------------------------------------
- Un guard NUEVO sin cablear y sin declarar FALLA. Es lo unico que frena la deuda.
- Un guard que ESTABA cableado por un call-site y deja de estarlo tambien FALLA
  (deteccion de des-cableado). v3 era CIEGO a esto: 3 de los cableados se
  sostenian tambien con prosa viva, asi que borrar su call-site real no los ponia
  unwired. El baseline por-ARISTA (fichero) lo caza sin falsos rojos por edits.

LIMITE CONOCIDO Y ABIERTO: la ruta PYTHON-SINK tiene falso-WIRED (WOT-2026-025c)
-------------------------------------------------------------------------------
NO confies en el veredicto WIRED de un guard cuya UNICA evidencia venga de un
string dentro de un fichero .py de la frontera. Esa ruta NO esta cerrada, y esta
seccion existe para que nadie lo descubra por las malas.

La ruta CONFIG (pre-commit `entry:`, workflow `run:`, settings `command`) SI es
solida: se parsea estructuralmente y solo se leen los campos que ejecutan.

La ruta PYTHON-SINK intenta decidir si un string que llega a `subprocess.run(...)`
es un COMANDO o es PROSA. Ocho intentos, ocho agujeros (2026-07-15):

  4o  una FRASE en un sink que no ejecuta:  `run(["echo", "recuerda check_x.py"])`
  5o  una frase que empieza por un lanzador: `echo "python revisa check_x.py"`
  6o  una frase unida por coma o `;`:        `echo "revisa,check_x.py,manual"`
  7o  una frase con una palabra que esta en la lista de subcomandos (run/script/
      exec/tool): `echo "python run check_x.py"`; y args que NO son argv
      (`env={...}`, `input=...`) que igualmente se inspeccionaban
  8o  una frase en kebab/snake_case o con `:`, que no lleva separadores y pasa como
      "un token": `echo "pendiente-cablear-scripts/check_x.py"`  <-- ESTE REPO
      ESCRIBE ASI ("des-cableado", "auto-DoSea"): un recordatorio real lo dispara

Los agujeros 4-6 estan cerrados (`_sink_arg_tokens`, `_prefix_is_command_shaped`,
`_SEP`). El 7o y el 8o siguen ABIERTOS: dos auditorias independientes los
encontraron el mismo dia, en paralelo, sobre el fix del anterior. El patron ya no
es "falto un caso": es que **tokenizar prosa para adivinar si es un comando no
converge**. Mientras el discriminante sea "esto PARECE una linea de comando",
habra frases que lo parezcan.

La reformulacion correcta (solo el argumento que ES el comando; solo elementos
LITERALES de la lista argv; nunca re-tokenizar prosa) es un ANALIZADOR ESTATICO DE
EJECUCION -- otro ticket, no un parche mas: **WOT-2026-025c**. Los 8 vectores estan
en el corpus con su origen, listos para el rediseno.

Que hacer mientras tanto: el veredicto de la ruta config es fiable; el de la ruta
python-sink puede sobre-declarar (falso-WIRED). Si un guard sale WIRED y no ves su
call-site, VERIFICALO A MANO antes de fiarte.

Lo que el AST no decide se DECLARA, no se adivina
-------------------------------------------------
Makefile / shell / callable a >1 salto / glob-discovery / wiring-via-test:
`wired_via` (fichero:linea + probe), con la misma asimetria y deteccion de stale
que `known_unwired`. Guards reales SIN prefijo (`pre_handoff_guard`): `extra_guards`.
Los tres bloques viven en `scripts/guard_wiring_policy.yaml` -- NO en este .py: la
deuda dentro de un fichero de la frontera se auto-DoSea (un paso que la imprima
para reportarla cablearia a los declarados; medido: 2/3).

Antes: se corre desde cualquier sitio; resuelve el motor desde la ruta del fichero.
Despues: exit 0 = cada guard sin cablear es una excepcion declarada y con dueno, y
         cada guard del baseline sigue cableado desde su fichero. exit 1 = un guard
         corre en ningun sitio y no esta declarado, una entrada esta stale, o un
         guard se ha des-cableado.

La TERCERA asimetria: la deuda HUERFANA (WOT-2026-026v)
-------------------------------------------------------
Una declaracion `known_unwired` acota la deuda solo mientras su dueno siga VIVO.
Si el ticket se archiva y el guard sigue sin cablear, ya no queda nadie que vaya a
cablearlo: la declaracion dejo de ACOTAR la deuda y paso a ESCONDERLA -- y este
gate salia verde igual (el mismo mal que su propio docstring predica: medir la
propiedad con una vara mas floja que la que exige). El cruce owner-vivo se hace
contra la cola VIVA del repo_destino (`backlog.md`), resuelto por la via canonica
(`--project-root` / `AGENT_PROJECT_ROOT` / `motor_destination_link.json`).

Sin destino resoluble el check SKIPEA EXPLICITAMENTE y lo IMPRIME (no calla): un
guard del motor que reviente en un destino sin backlog seria peor que la deuda que
cierra. En modo normal es WARN nombrado; con `--strict`, falla.

El SKIP tiene que ser ALCANZABLE, no solo estar escrito: el backlog se decodifica
en ESTRICTO y una cola sin un solo ticket tambien SKIPEA. Un backlog ilegible que
se lee "a la fuerza" produce cero owners vivos, y cero owners vivos se parece
exactamente a "todos archivados" -- o sea, a un informe de huerfanos del 100% que
seria falso entero (medido: 6 falsos vs 3 reales).

Y la comprobacion vive CABLEADA en el cierre (`prepush_check`, closeout_mode), no
en el hook de pre-commit: alli no hay destino que consultar y cablear una ruta de
esta maquina romperia la portabilidad. Un SKIP permanente habria dejado esto en
NORMA -- que es justo lo que este modulo existe para no tolerar.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import yaml


MOTOR_ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = MOTOR_ROOT / "scripts" / "guard_wiring_policy.yaml"
BASELINE_PATH = MOTOR_ROOT / "tests" / "fixtures" / "guard_wiring_wired_baseline.yaml"

GUARD_PREFIXES = ("check_", "validate_", "guard_")
GUARD_DIRS = ("scripts", ".agent/hooks", "skills", "tools", "bus", "runtime")

_TICKET = re.compile(r"^WOT-\d{4}-\d{3}[a-z]$")
# Gemelo NO anclado de _TICKET: _TICKET valida la FORMA de un owner (string
# completo); este scrapea IDs incrustados en la prosa del backlog. Misma
# gramatica a proposito -- si una diverge, un owner valido dejaria de casar
# con su propia fila viva y se reportaria huerfano en falso.
_TICKET_ANYWHERE = re.compile(r"WOT-\d{4}-\d{3}[a-z]")
_BY_DESIGN = "BY-DESIGN:"

# Separadores de token, FUENTE UNICA. El gate de _sink_arg_tokens y el tokenizador
# _path_tokens_in DEBEN usar el mismo conjunto -- el 6o agujero (2026-07-15) fue que
# discrepaban (\s vs [\s,;]+) y una frase unida por coma pasaba el gate.
_SEP = re.compile(r"[\s,;]")

# Lista CERRADA de sinks de ejecucion. `echo`/`print`/`cat` NO estan: eso es lo que
# mata la prosa-con-un-path. Se comparan por nombre punteado y por forma corta.
_EXEC_SINKS = frozenset(
    {
        "subprocess.run",
        "subprocess.Popen",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "os.system",
        "os.popen",
        "os.execv",
        "os.execvp",
        "os.execve",
        "runpy.run_path",
        "runpy.run_module",
        "importlib.import_module",
        "import_module",
        "__import__",
        # carga dinamica por ruta de fichero -> ejecuta el modulo (construct H):
        "importlib.util.spec_from_file_location",
        "util.spec_from_file_location",
        "spec_from_file_location",
        "exec",
        "eval",
        # formas cortas (from subprocess import run):
        "run",
        "Popen",
        "call",
        "check_call",
        "check_output",
        "system",
    }
)

_LAUNCHERS = {
    "python",
    "python3",
    "python.exe",
    "py",
    "uv",
    "uvx",
    "pipx",
    "poetry",
    "hatch",
    "sh",
    "bash",
    "zsh",
    "pwsh",
    "powershell",
    "cmd",
    "node",
    "npx",
    "pytest",
    "pre-commit",
    "make",
    "just",
    "nox",
    "tox",
}
_C_FLAGS = {"-c", "-lc", "-Command", "-command", "/c"}
_AUTO_TRIGGERS = {
    "push",
    "pull_request",
    "pull_request_target",
    "schedule",
    "merge_group",
    "release",
}


# --------------------------------------------------------------------- policy I/O
def _load_policy(path: Path | None = None) -> dict:
    path = path or POLICY_PATH
    if not path.exists():
        return {"known_unwired": {}, "extra_guards": {}, "wired_via": {}}
    data = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
    return {
        "known_unwired": data.get("known_unwired") or {},
        "extra_guards": data.get("extra_guards") or {},
        "wired_via": data.get("wired_via") or {},
    }


def _load_baseline(path: Path | None = None) -> dict[str, list[str]]:
    path = path or BASELINE_PATH
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
    return data.get("wired_baseline") or {}


# --------------------------------------------------------------- form of a token
def _guard_stem(basename: str) -> str | None:
    stem = basename[:-3] if basename.endswith(".py") else basename
    return stem if stem.startswith(GUARD_PREFIXES) else None


def _path_tokens_in(s: str) -> list[str]:
    """Basenames of .py path TOKENS in a command line. A bare stem ('check_x') is
    NOT a token -- that keeps a `name=`/`choices=`/Enum value out. Y una FRASE con
    un .py incrustado en markdown/backticks tampoco casa: el token debe ser limpio."""
    out: list[str] = []
    for raw in _SEP.split(s.strip()):  # misma FUENTE que el gate (ver _SEP)
        tok = raw.strip().strip("\"'")
        if tok.lower().endswith(".py") and re.fullmatch(
            r"[A-Za-z0-9_.:/\\~$@{}+-]+", tok
        ):
            out.append(re.split(r"[/\\]", tok)[-1])
    return out


def _sink_arg_tokens(s: str) -> list[str]:
    """Tokens de guard de un string que llega como ARGUMENTO de un sink (subprocess,
    etc.). Un elemento de argv es UN token de path aislado (`"scripts/check_x.py"`) o
    una linea de comando entera (`"python scripts/check_x.py"`).

    NO una FRASE. Una frase con espacios que MENCIONA un .py (`"recuerda check_x.py a
    mano"`, un mensaje de commit, un log de error) es prosa: llega a un sink real
    (`echo`, `git -m`, `logger`) que NO ejecuta su argumento. v1-v3 murieron por medir
    la propiedad con vara floja; v4 la media bien en la ruta CONFIG (via _command_tokens,
    que exige lanzador en argv[0]) y MAL en la ruta python-sink, donde _path_tokens_in
    extraia el .py de cualquier frase (4o agujero, auditoria hermana 2026-07-15).

    Simetria con el lado config: exigimos que el string sea una linea de comando con
    lanzador reconocido (_command_tokens), O un unico token de path SIN espacios
    (_path_tokens_in sobre un string de un solo token). Una frase no es ninguna cosa.
    """
    cmd = _command_tokens(s)
    if cmd:
        return cmd
    # solo si el string ES un unico token (un elemento de argv), no una frase.
    # 6o agujero (auditoria hermana del fix, 2026-07-15): el gate rechazaba solo por
    # \s, pero _path_tokens_in parte por [\s,;]+ -- una frase unida por COMA o
    # PUNTO-Y-COMA ("revisa,check_x.py,manual") no tiene espacios, pasaba el gate, y el
    # .py se extraia igual (cablaba una lista entera de guards de golpe). El gate DEBE
    # usar los MISMOS separadores que el tokenizador: `_SEP`.
    if s.strip() and not _SEP.search(s.strip()):
        return _path_tokens_in(s)
    return []


def _command_tokens(s: str, depth: int = 0) -> list[str]:  # noqa: C901 - parser de linea de comando: flags/-m/-c/prosa-antes-de-path
    """Path-token basenames of a command line whose argv[0] is an allowlisted
    launcher. Recurses into -c/-lc payloads (depth<=2). Empty for a phrase."""
    s = (s or "").strip()
    if not s or depth > 2:
        return []
    try:
        argv = shlex.split(s, posix=True)
    except ValueError:
        argv = s.split()
    while (
        argv and "=" in argv[0] and not argv[0].startswith("-") and "/" not in argv[0]
    ):
        argv = argv[1:]  # VAR=x prefix
    if not argv:
        return []
    exe = re.split(r"[/\\]", argv[0])[-1].lower()
    if exe not in _LAUNCHERS:
        return []
    out: list[str] = []
    i = 1
    while i < len(argv):
        tok = argv[i]
        if tok in _C_FLAGS and i + 1 < len(argv):
            out += _payload_tokens(argv[i + 1], exe, depth + 1)
            i += 2
            continue
        if tok == "-m" and i + 1 < len(argv):
            mod = argv[i + 1].split(".")[-1]
            if _guard_stem(mod):
                out.append(mod + ".py")
            i += 2
            continue
        pts = _path_tokens_in(tok)
        if pts and not _prefix_is_command_shaped(argv[1:i]):
            # 5o agujero (2026-07-15): una FRASE cuya 1a palabra coincide con un lanzador
            # ("python revisa scripts/check_x.py luego") pasa el filtro exe y luego
            # _path_tokens_in extrae el .py. Un comando REAL solo tiene flags/opciones/
            # subcomandos entre el lanzador y el script; una frase tiene palabras-prosa.
            # Si hay prosa antes de este .py, no es una linea de comando: descartalo.
            i += 1
            continue
        out += pts
        i += 1
    return out


# Subcomandos de lanzadores que preceden legitimamente a un script (uv run python x.py,
# pre-commit run, poetry run). Lista CERRADA: una palabra fuera de aqui, de los flags y
# de los propios paths, es prosa.
_LAUNCHER_SUBCOMMANDS = {
    "run",
    "exec",
    "tool",
    "python",
    "python3",
    "-m",
    "shell",
    "script",
}


def _prefix_is_command_shaped(prefix: list[str]) -> bool:
    """True si todo lo que hay entre el lanzador y un .py es FLAG, opcion o subcomando
    conocido -- no una palabra de prosa. `python revisa check_x.py` tiene "revisa" en
    medio -> prosa -> False. `uv run python check_x.py` -> todo subcomando -> True."""
    for tok in prefix:
        if tok.startswith("-"):
            continue  # flag/opcion
        if tok.lower() in _LAUNCHER_SUBCOMMANDS:
            continue
        if _path_tokens_in(tok) or "/" in tok or "\\" in tok or "=" in tok:
            continue  # un path o una asignacion VAR=x, no prosa
        return False  # una palabra que no es flag/subcomando/path -> prosa
    return True


def _payload_tokens(payload: str, exe: str, depth: int) -> list[str]:
    """A -c payload: python source (parse it) or a shell line (recurse)."""
    if exe.startswith("py"):
        try:
            return [b for b, _ in _python_invocations(payload)]
        except SyntaxError:
            return []
    out: list[str] = []
    for line in re.split(r"[\n;&|]+", payload):
        out += _command_tokens(line, depth)
    return out


# ------------------------------------------------ python: position + 1 hop
def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    return ""


def _strings_in(node: ast.AST) -> list[str]:
    return [
        n.value
        for n in ast.walk(node)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]


def _is_const_false(node: ast.AST) -> bool:
    """`False`, `0`, `None` como condicion literal de un `if` -> rama muerta."""
    return isinstance(node, ast.Constant) and not node.value


def _prune_dead_branches(tree: ast.AST) -> None:
    """Vacia in-place el cuerpo de cada `if <falsy-literal>:` (deja el `orelse`).

    No es un evaluador de constantes general (eso seria adivinar): solo el literal
    directo, que es la forma de la familia disabled_code (`if False:`)."""
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            block = getattr(node, field, None)
            if not isinstance(block, list):
                continue
            for stmt in block:
                if isinstance(stmt, ast.If) and _is_const_false(stmt.test):
                    stmt.body = []  # la rama que nunca corre


def _python_invocations(src: str) -> list[tuple[str, int]]:  # noqa: C901 - el nucleo del analisis: 3 aristas de 1 salto + sinks + imports en una pasada
    """(basename, lineno) de cada token de path de un guard en POSICION DE
    EJECUCION de `src`, siguiendo las tres aristas de 1 salto. Los imports cuentan
    (importar ejecuta el cuerpo).

    Posicion, nunca contenedor: `["python", "scripts/check_x.py"]` casa porque es
    una lista de comando en un arg de subprocess; `LINES = ["- check_x.py -manual"]`
    no, porque el string es una frase (sin lanzador) y su lista no es arg de sink.
    """
    tree = ast.parse(src)
    _prune_dead_branches(tree)
    funcs: dict[str, ast.AST] = {
        n.name: n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
    }

    def _has_sink(fn: ast.AST, depth: int = 2) -> bool:
        for n in ast.walk(fn):
            if isinstance(n, ast.Call):
                d = _dotted(n.func)
                if d in _EXEC_SINKS:
                    return True
                if depth and d in funcs and _has_sink(funcs[d], depth - 1):
                    return True
        return False

    wrappers = {name for name, fn in funcs.items() if _has_sink(fn)}
    sinks = _EXEC_SINKS | wrappers

    env: dict[str, list[str]] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    env.setdefault(t.id, []).extend(_strings_in(n.value))
        elif isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name):
            env.setdefault(n.target.id, []).extend(_strings_in(n.value))

    returns: dict[str, list[str]] = {}
    for name, fn in funcs.items():
        rs: list[str] = []
        for n in ast.walk(fn):
            if isinstance(n, ast.Return) and n.value is not None:
                rs += _strings_in(n.value)
                for sub in ast.walk(n.value):
                    if isinstance(sub, ast.Name) and sub.id in env:
                        rs += env[sub.id]
        returns[name] = rs
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    for sub in ast.walk(n.value):
                        if isinstance(sub, ast.Call) and _dotted(sub.func) in returns:
                            env.setdefault(t.id, []).extend(returns[_dotted(sub.func)])

    out: list[tuple[str, int]] = []

    # imports = ejecucion. Casar el segmento MODULO, no un symbol importado (una
    # colision de nombres bendeciria `from scripts.check_x import main` como `main`).
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                for seg in a.name.split("."):
                    if _guard_stem(seg):
                        out.append((seg + ".py", n.lineno))  # noqa: PERF401
        elif isinstance(n, ast.ImportFrom):
            for seg in (n.module or "").split("."):
                if _guard_stem(seg):
                    out.append((seg + ".py", n.lineno))  # noqa: PERF401

    params_of: dict[str, set[str]] = {}
    for name, fn in funcs.items():
        params_of[name] = {a.arg for a in fn.args.args} | {
            a.arg for a in getattr(fn.args, "kwonlyargs", [])
        }

    for scope in [tree, *funcs.values()]:
        sname = getattr(scope, "name", None)
        params = params_of.get(sname, set())
        for n in ast.walk(scope):
            if not isinstance(n, ast.Call):
                continue
            d = _dotted(n.func)
            injected = isinstance(n.func, ast.Name) and n.func.id in params
            if d not in sinks and not injected:
                continue
            args = list(n.args) + [kw.value for kw in n.keywords]
            for arg in args:
                for s in _strings_in(arg):
                    for base in _sink_arg_tokens(s):
                        out.append((base, getattr(arg, "lineno", n.lineno)))  # noqa: PERF401
                for sub in ast.walk(arg):
                    if isinstance(sub, ast.Name):
                        for s in env.get(sub.id, []) + returns.get(sub.id, []):
                            for base in _sink_arg_tokens(s):
                                out.append((base, n.lineno))  # noqa: PERF401
                    if isinstance(sub, ast.Call) and _dotted(sub.func) in returns:
                        for s in returns[_dotted(sub.func)]:
                            for base in _sink_arg_tokens(s):
                                out.append((base, n.lineno))  # noqa: PERF401
    return out


# -------------------------------------------------- config: does it run on its own
def _git() -> str:
    return shutil.which("git") or "git"


def _tracked(root: Path) -> list[str]:
    try:
        p = subprocess.run(  # noqa: S603
            [_git(), "-C", str(root), "ls-files"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if p.returncode == 0 and p.stdout.strip():
            return p.stdout.splitlines()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return [
        str(x.relative_to(root)).replace("\\", "/")
        for x in root.rglob("*")
        if x.is_file()
    ]


def _hook_fires(hook: dict, default_stages, files: list[str]) -> bool:
    stages = hook.get("stages") or default_stages or []
    if stages and all(s == "manual" for s in stages):
        return False  # manual-only: es una norma
    if hook.get("always_run"):
        return True
    inc, exc = hook.get("files"), hook.get("exclude")
    cands = files
    if inc:
        cands = [f for f in cands if re.search(inc, f)]
    if exc:
        cands = [f for f in cands if not re.search(exc, f)]
    return bool(cands)  # exclude:'.*' o files:'^$' -> nunca dispara


def _workflow_runs(data: dict) -> bool:
    on = data.get("on")
    if on is None:
        on = data.get(True)  # PyYAML parsea `on:` a secas como True
    if isinstance(on, str):
        on = [on]
    if isinstance(on, dict | list):
        return bool(_AUTO_TRIGGERS & set(on))
    return False


def _step_runs(step: dict) -> bool:
    cond = step.get("if")
    if cond is None:
        return True
    c = str(cond).strip().lower().replace("${{", "").replace("}}", "").strip()
    return c not in {"false", "0", "'false'"}


def _config_commands(root: Path) -> list[tuple[str, str]]:  # noqa: C901 - un parser por formato de config (yaml/json), ramas inherentes
    """Cada comando que un ROOT config entrega a un shell, estructuralmente: (where,
    cmd). Solo campos que EJECUTAN: `entry:` de un hook no-manual, `run:` de un step
    vivo bajo un trigger automatico, `command` de un hook de settings.json
    habilitado. Nunca `name:`, `exclude:`, `permissions.deny`, ni el dict/texto."""
    cmds: list[tuple[str, str]] = []

    pc = root / ".pre-commit-config.yaml"
    if pc.exists():
        data = yaml.safe_load(pc.read_text(encoding="utf-8", errors="replace")) or {}
        files = _tracked(root)
        ds = data.get("default_stages")
        for repo in data.get("repos", []):
            for h in repo.get("hooks", []):
                if _hook_fires(h, ds, files) and h.get("entry"):
                    entry_cmd = " ".join([h["entry"], *(h.get("args") or [])])
                    cmds.append((f"{pc.name}:{h.get('id')}", entry_cmd))

    wdir = root / ".github" / "workflows"
    if wdir.exists():
        for wf in sorted(list(wdir.glob("*.yml")) + list(wdir.glob("*.yaml"))):
            data = (
                yaml.safe_load(wf.read_text(encoding="utf-8", errors="replace")) or {}
            )
            if not _workflow_runs(data):
                continue
            for jname, job in (data.get("jobs") or {}).items():
                if str((job or {}).get("if", "")).strip().lower() in (
                    "false",
                    "${{ false }}",
                ):
                    continue
                for step in (job or {}).get("steps") or []:
                    if not _step_runs(step) or not step.get("run"):
                        continue
                    for line in re.split(r"[\n;]+|&&|\|\|", step["run"]):
                        line = line.split("#", 1)[0].strip()
                        if line:
                            cmds.append((f"{wf.name}:{jname}", line))

    st = root / ".claude" / "settings.json"
    if st.exists():
        try:
            data = json.loads(st.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            data = {}
        for event, groups in (data.get("hooks") or {}).items():
            for g in groups or []:
                for h in g.get("hooks") or []:
                    if h.get("enabled") is False or h.get("type") != "command":
                        continue
                    if h.get("command"):
                        cmds.append((f"settings.json:{event}", h["command"]))
    return cmds


# ---------------------------------------------------------- derived frontier
_DECLARED_ROOTS = (
    "scripts/prepush_check.py",
    "scripts/session_closeout.py",
    ".agent/agent_controller.py",
)
_DECLARED_ROOT_GLOBS = ("scripts/preflight_*.py",)


def _settings_py_literals(root: Path) -> list[Path]:
    """Hallazgo #6: los hooks de settings.json son `python -c "<shim>"`. El shim es
    un bootstrap sin prosa cuyo unico fin es localizar+ejecutar UN hook. MAX-RECALL
    acotado: absorbe TODO `.py`-literal del payload a la frontera (la forma
    `next(cands)` esconde el nombre de un sink; aqui la recall es segura porque no
    hay superficie de prosa dentro de un shim de subprocess)."""
    out: list[Path] = []
    st = root / ".claude" / "settings.json"
    if not st.exists():
        return out
    try:
        data = json.loads(st.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return out
    for groups in (data.get("hooks") or {}).values():
        for g in groups or []:
            for h in g.get("hooks") or []:
                if h.get("enabled") is False:
                    continue
                cmd = h.get("command") or ""
                for m in re.finditer(r"[\w./\\-]+\.py", cmd):
                    base = re.split(r"[/\\]", m.group(0))[-1]
                    for d in (".agent/hooks", "scripts", ".", "tools"):
                        p = root / d / base
                        if p.exists():
                            out.append(p)
    return out


def self_running_paths(root: Path) -> list[Path]:  # noqa: C901 - frontera derivada: semillas + config + cierre de imports
    """La frontera DERIVADA: semillas + lo que ejecutan + su cierre de imports."""
    seen: set[Path] = set()
    order: list[Path] = []

    def add(p: Path):
        p = p.resolve()
        if p.exists() and p not in seen:
            seen.add(p)
            order.append(p)

    for rel in _DECLARED_ROOTS:
        add(root / rel)
    for pat in _DECLARED_ROOT_GLOBS:
        for p in root.glob(pat):
            add(p)
    for _where, raw in _config_commands(root):
        for base in _command_tokens(raw):
            for d in ("scripts", ".agent/hooks", ".", "tools", "skills"):
                add(root / d / base)
    for p in _settings_py_literals(root):
        add(p)

    queue = list(order)
    while queue:
        cur = queue.pop()
        if cur.suffix != ".py":
            continue
        try:
            tree = ast.parse(cur.read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, OSError):
            continue
        mods: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mods.append(node.module)
        for m in mods:
            cand = root.joinpath(*m.split("."))
            for p in (cand.with_suffix(".py"), cand / "__init__.py"):
                if p.exists() and p.resolve() not in seen:
                    add(p)
                    queue.append(p.resolve())
    return sorted(order)


# -------------------------------------------------------------- the audit
def find_guards(root: Path, extra_guards: dict | None = None) -> dict[str, Path]:
    """Denominador. rglob (no glob plano: v3 era ciego a subdirectorios) + los
    guards sin prefijo DECLARADOS (no hay heuristica fiable de "esto es un guard")."""
    names: dict[str, Path] = {}
    for d in GUARD_DIRS:
        base = root / d
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            if p.stem.startswith(GUARD_PREFIXES):
                names.setdefault(p.stem, p)
    for stem, rel in (extra_guards or {}).items():
        p = root / rel
        if p.exists():
            names[stem] = p
    return names


def collect_evidence(
    root: Path, extra_guards: dict | None = None
) -> dict[str, list[tuple[str, int]]]:
    """guard -> [(fichero_relativo, linea)] que lo cablean. La ARISTA (que fichero)
    es subproducto: la usa la deteccion de des-cableado."""
    ev: dict[str, list[tuple[str, int]]] = {}
    extra_stems = set(extra_guards or {})

    def push(base: str, where: str, line: int):
        stem = base[:-3] if base.endswith(".py") else base
        g = _guard_stem(base) or (stem if stem in extra_stems else None)
        if g:
            ev.setdefault(g, []).append((where, line))

    for where, raw in _config_commands(root):
        for base in _command_tokens(raw):
            push(base, where, 0)

    for p in self_running_paths(root):
        if p.suffix != ".py":
            continue
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
            rel = (
                str(p.relative_to(root)).replace("\\", "/")
                if root in p.parents
                else p.name
            )
            for base, line in _python_invocations(src):
                push(base, rel, line)
        except (SyntaxError, OSError, ValueError):
            continue
    return ev


def audit(root: Path, policy: dict | None = None):
    """Devuelve (wired, unwired) -- compat con la firma de v1-v3."""
    policy = policy or _load_policy()
    guards = find_guards(root, policy["extra_guards"])
    ev = collect_evidence(root, policy["extra_guards"])
    wired, unwired = [], []
    for g in sorted(guards):
        (wired if ev.get(g) else unwired).append(g)
    return wired, unwired


def wiring_edges(root: Path, policy: dict | None = None) -> dict[str, set[str]]:
    """guard -> conjunto de FICHEROS que lo cablean. La 'arista' robusta a edits
    inocentes (no fija numeros de linea, solo el fichero+config de origen)."""
    policy = policy or _load_policy()
    ev = collect_evidence(root, policy["extra_guards"])
    return {g: {where.split(":")[0] for where, _ln in sites} for g, sites in ev.items()}


# ---------------------------------------------------------------- format-check
def _bad_owners(known_unwired: dict) -> list[str]:
    return [
        f"{g} -> {owner!r}"
        for g, owner in known_unwired.items()
        if not (_TICKET.match(str(owner)) or str(owner).startswith(_BY_DESIGN))
    ]


def _resolve_destino_root(
    project_root: str | None, workspace_root: str | None
) -> tuple[Path | None, str | None]:
    """Resolve the repo_destino whose backlog says which owners are still alive.

    Before: ``project_root``/``workspace_root`` come from the CLI, both optional
    (the pre-commit call-site passes neither).
    During: precedence (1) ``--project-root`` verbatim; (2) ``AGENT_PROJECT_ROOT``;
    (3) the workspace's ``motor_destination_link.json`` ``destination_root``. The
    link is machine-specific/gitignored, so it is resolved at runtime.
    After: returns ``(Path, None)`` on success, or ``(None, reason)`` so the caller
    SKIPS explicitly. Never raises: a motor guard that crashes in a destination
    without a backlog is worse than the debt it closes.

    Mirror of ``check_backlog_commits_landed._resolve_destino_root``.
    """
    if project_root:
        return Path(project_root).resolve(), None
    env_root = os.environ.get("AGENT_PROJECT_ROOT")
    if env_root:
        return Path(env_root).resolve(), None
    if not workspace_root:
        return None, "no --project-root, no AGENT_PROJECT_ROOT and no --workspace-root"
    link = (
        Path(workspace_root).resolve()
        / ".agent"
        / "config"
        / "motor_destination_link.json"
    )
    try:
        data = json.loads(link.read_text(encoding="utf-8"))
    except OSError:
        return None, f"motor_destination_link.json not found under {workspace_root}"
    except json.JSONDecodeError as exc:
        return None, f"motor_destination_link.json unreadable: {exc}"
    dest = data.get("destination_root")
    if not dest:
        return None, "motor_destination_link.json has no destination_root"
    return Path(dest).resolve(), None


def _live_owner_tickets(dest_root: Path) -> tuple[set[str] | None, str | None]:
    """Ticket IDs present in the DESTINO's LIVE backlog queue.

    Before: ``dest_root`` is a resolved repo_destino.
    During: reads ``.agent/collaboration/backlog.md`` and scrapes every canonical
    ticket ID. Only the LIVE queue counts -- an ID that survives solely in
    ``_archive/backlog_done.md`` is precisely the archived owner we hunt.
    After: ``(set, None)``, or ``(None, reason)`` when the backlog is absent,
    unreadable or unparseable, so the caller SKIPS instead of inventing orphans.

    La lectura es ESTRICTA a proposito. Con ``errors="replace"`` un backlog no-UTF8
    (UTF-16, ANSI de Windows...) no lanzaba: devolvia mojibake, el scraper no
    encontraba NINGUN ticket, y ese conjunto vacio es indistinguible de "todos los
    owners estan archivados" -- el SKIP que este contrato promete se volvia
    INALCANZABLE y el cierre acusaba de huerfana a TODA la deuda declarada,
    incluidos owners literalmente presentes y VIVOS en el fichero. Medido: 6
    huerfanos falsos frente a los 3 reales. Es la misma enfermedad que el ticket
    cierra: medir con una vara mas floja que la que se predica.
    """
    backlog = dest_root / ".agent" / "collaboration" / "backlog.md"
    try:
        content = backlog.read_bytes().decode("utf-8-sig")
    except OSError as exc:
        return None, f"cannot read {backlog}: {exc}"
    except UnicodeDecodeError as exc:
        return None, f"{backlog} is not valid UTF-8 ({exc.reason}); refusing to guess"
    live = set(_TICKET_ANYWHERE.findall(content))
    if not live:
        # Una cola viva SIN UN SOLO ticket no sostiene la conclusion "todos
        # archivados": es mucho mas probable un backlog truncado, a medio escribir
        # o en otro formato. Fail-safe hacia el SKIP nombrado, nunca hacia acusar
        # de huerfana a toda la deuda declarada.
        return (
            None,
            f"{backlog} names no ticket at all; refusing to read that as 'all archived'",
        )
    return live, None


def _orphan_owners(
    known_unwired: dict, declared: list[str], live: set[str]
) -> list[str]:
    """Declared debt whose OWNER is archived while the guard is STILL unwired.

    Before: ``declared`` are the guards this run found unwired AND declared;
    ``live`` are the ticket IDs still in the destino's live backlog.
    During: an entry is an orphan iff its owner is a ticket (BY-DESIGN entries are
    always exempt -- they have no owner to archive) that is NOT live. Guards that got
    wired are not considered: they are already reported as ``stale``.
    After: returns the sorted ``guard -> owner`` lines. The INVARIANT is the
    criterion (archived owner + still unwired), never a count (WOT-2026-024t).
    """
    return sorted(
        f"{g} -> {known_unwired[g]}"
        for g in declared
        if _TICKET.match(str(known_unwired[g])) and str(known_unwired[g]) not in live
    )


def _dewired(root: Path, policy: dict) -> list[str]:
    """Guards del baseline que YA NO se cablean desde su fichero declarado. La
    asimetria gemela: un guard que estaba WIRED por un call-site y lo perdio."""
    baseline = _load_baseline()
    if not baseline:
        return []
    edges = wiring_edges(root, policy)
    bad: list[str] = []
    for guard, expected_files in baseline.items():
        got = edges.get(guard, set())
        exp = {e.split(":")[0] for e in expected_files}
        if not got or not (got & exp):
            bad.append(
                f"{guard}: esperaba cableado desde {sorted(exp)}, ahora {sorted(got) or 'NADA'}"
            )
    return bad


def main(argv: list[str] | None = None) -> int:  # noqa: C901 - CLI: format-check + des-cableado + declarados + stale
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--motor-root", default=str(MOTOR_ROOT))
    ap.add_argument(
        "--strict",
        action="store_true",
        help="fail on the declared debt too (retro audit; BY-DESIGN never fails)",
    )
    ap.add_argument(
        "--project-root",
        default=None,
        help="repo_destino whose live backlog decides if a debt owner is still alive",
    )
    ap.add_argument(
        "--workspace-root",
        default=None,
        help="workspace holding .agent/config/motor_destination_link.json (fallback)",
    )
    args = ap.parse_args(argv)
    root = Path(args.motor_root).resolve()
    policy = _load_policy()
    known = policy["known_unwired"]
    wired_via = policy["wired_via"]

    bad = _bad_owners(known)
    if bad:
        print("[guard-wiring] ERROR: allowlist entries with an unusable owner:")
        for b in bad:
            print(f"    {b}")
        print("  An owner must be a ticket (WOT-YYYY-NNNx) or start with 'BY-DESIGN:'.")
        return 1

    wired, unwired = audit(root, policy)
    unwired = [g for g in unwired if g not in wired_via]
    undeclared = [g for g in unwired if g not in known]
    declared = [g for g in unwired if g in known]
    stale = sorted((set(known) | set(wired_via)) & set(wired))

    print(
        f"[guard-wiring] {len(wired)} wired / {len(unwired)} unwired "
        f"({len(declared)} declared, {len(undeclared)} UNDECLARED, "
        f"{len(wired_via)} via, {len(stale)} stale)"
    )

    dewired = _dewired(root, policy)
    if dewired:
        print("\n[guard-wiring] ERROR: guard(s) DES-CABLEADOS (estaban wired, ya no):")
        for d in dewired:
            print(f"    {d}")
        print(
            "\n  La asimetria gemela: un guard que perdio su call-site real sigue\n"
            "  pareciendo cableado si otra cosa (prosa, otro fichero) lo menciona.\n"
            "  Restaura el cableado, o si el des-cableado es intencional actualiza\n"
            "  tests/fixtures/guard_wiring_wired_baseline.yaml en este mismo commit."
        )
        return 1

    if declared:
        print("[guard-wiring] declared, each with its owner:")
        for g in declared:
            print(f"    {g}  -> {known[g]}")

    if undeclared:
        print("\n[guard-wiring] ERROR: guard(s) that run NOWHERE and are NOT declared:")
        for g in undeclared:
            print(f"    {g}")
        print(
            "\n  A guard nobody invokes is a norm, not a barrier. WIRE IT into a\n"
            "  self-running path, or declare it in scripts/guard_wiring_policy.yaml\n"
            "  (known_unwired with a ticket, or wired_via with file:line + probe)."
        )
        return 1

    if stale:
        print("\n[guard-wiring] ERROR: stale declaration(s) -- wired now, or gone:")
        for g in stale:
            print(f"    {g}  (declared unwired/via, but it IS wired)")
        print(
            "\n  Remove them from guard_wiring_policy.yaml. A cemetery pre-blesses any\n"
            "  future file with that name -- the exact false-green this module stops."
        )
        return 1

    # WOT-2026-026v: la declaracion existe para ACOTAR la deuda; si su dueno se
    # archiva y el guard sigue sin cablear, la declaracion se vuelve su ESCONDITE
    # y este gate seguia saliendo verde. El criterio es el INVARIANTE (owner
    # archivado + aun sin cablear), nunca un conteo (WOT-2026-024t).
    dest_root, dest_err = _resolve_destino_root(args.project_root, args.workspace_root)
    if dest_root is None:
        print(f"[guard-wiring] SKIP orphan-owner check: {dest_err}.")
    else:
        live, live_err = _live_owner_tickets(dest_root)
        if live is None:
            print(f"[guard-wiring] SKIP orphan-owner check: {live_err}.")
        else:
            orphans = _orphan_owners(known, declared, live)
            if orphans:
                label = "ERROR" if args.strict else "WARN"
                print(
                    f"\n[guard-wiring] {label}: deuda HUERFANA "
                    "-- owner archivado y guard AUN sin cablear:"
                )
                for o in orphans:
                    print(f"    {o}")
                print(
                    "\n  El ticket dueno ya no esta en la cola viva, asi que nadie va a\n"
                    "  cablear este guard: la declaracion dejo de acotar la deuda y paso\n"
                    "  a esconderla. Reabre el ticket, cablea el guard, o re-declaralo\n"
                    "  con un dueno VIVO en scripts/guard_wiring_policy.yaml."
                )
                if args.strict:
                    return 1

    debt = [g for g in declared if not str(known[g]).startswith(_BY_DESIGN)]
    if args.strict and debt:
        print(
            f"\n[guard-wiring] --strict: {len(debt)} guard(s) of declared debt count as failure."
        )
        return 1

    print(
        "[guard-wiring] OK: cada guard sin cablear esta declarado; el baseline se sostiene."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
