#!/usr/bin/env python3
"""Native stop hook: barreras de clasificacion y consulta (WOT-2026-215b).

Contexto
--------
Este hook YA estaba cableado en `.claude/settings.json` (`hooks.Stop`, matcher "")
y era fail-closed, pero su cuerpo era un no-op: leia el payload de stdin y lo
descartaba. WOT-2026-044t le da contenido.

El fallo que ataca NO es una laguna de conocimiento: la norma "toda afirmacion
causal/historica/de estado va precedida de un probe ejecutado, o marcada como
hipotesis" ya vive en multiples superficies de prosa y en memoria con confidence
0.97, y estaba cargada cuando se reincidio 4 veces en una sola sesion. Es un fallo
de EJECUCION. Por eso aqui no se anade prosa normativa: se obliga a una decision
consciente en el ultimo instante antes de entregar.

Before (pre-condiciones)
------------------------
- stdin trae el payload JSON del evento Stop de Claude Code.
- Campos REALES medidos con probe en la ruta productiva (2026-07-31): `session_id`,
  `transcript_path`, `cwd`, `prompt_id`, `permission_mode`, `effort`,
  `hook_event_name`, `stop_hook_active`, `last_assistant_message`,
  `background_tasks`, `session_crons`.
- `last_assistant_message` llega como STRING plano: no hace falta parsear el
  transcript, lo que elimina I/O y fragilidad de parsing JSONL.

During (proceso)
----------------
1. Si no existe el centinela `.agent/runtime/verification_mode` -> no-op absoluto.
2. Si el payload es raro (vacio, no-JSON, campo ausente/no-str/vacio) -> fail-open.
3. Si `stop_hook_active` esta ausente o es truthy -> fail-open (guard de reentrada).
4. PUERTA DE MUTACION: si no HAY PRUEBA de que el repo cambio desde el baseline
   guardado al encender el modo -> fail-open. Un cierre conversacional no debe recibo.
5. Si ninguna LINEA del mensaje final -- FUERA de un bloque de codigo -- ABRE con
   `[EVIDENCIA]` o `[HIPOTESIS]` -> `decision: block`,
   SALVO que el entorno pida modo observacion (`AGENT_VERIFICATION_MODE=observe` o
   `AGENT_DISABLE_VERIFICATION_STOP_HOOK=1`), en cuyo caso REGISTRA el bloqueo
   evitado en `verification_observations.json` y deja pasar. Ese escape existe
   para no estrenar una barrera bloqueante en un vuelo autonomo, que corre sin
   humano delante.

El criterio es un ANCLA POSICIONAL sobre marcadores declarados (el marcador debe
ABRIR una linea), condicionado por un hecho ESTRUCTURAL (git HEAD + status). No
interpreta prosa ni busca lenguaje causal: la regex solo mira DONDE aparece un
literal fijo, no que dice el texto. Esto respeta el NON-GOAL literal de
WOT-2026-044r ("no analisis semantico de prosa") y el muro de WOT-2026-025c.

Fue un SUBSTRING suelto hasta que el canario de WOT-2026-044y lo refuto en vivo:
un cierre que solo MENCIONABA los marcadores al explicar el mecanismo se
auto-aprobaba. Ver `MARKER_RE`.

POR QUE LA PUERTA DE MUTACION NO ES OPCIONAL (medicion 2026-07-31, no heredada):
sobre 33.476 mensajes finales reales extraidos de 1654 transcripts de esta maquina,
el criterio "falta el marcador" A SECAS bloqueaba 33.473, el 100,0%. El 22,5% eran
mensajes de menos de 120 caracteres ("court", "Commiteo el cierre del backlog") sin
afirmacion causal alguna. Sin esta puerta, activar la barrera por defecto seria un
denial-of-service sobre el agente. Con ella, solo paga recibo quien toco el arbol.
Direccion ratificada por revision adversarial de Codex ("C+D minimo").

After (post-condiciones)
------------------------
- Emite `{"decision": "block", "reason": ...}` para bloquear: NO deja parar y devuelve
  `reason` al agente para que corrija. Nunca emite `{"continue": false}`, que segun la
  doc oficial detendria a Claude POR COMPLETO -- lo contrario de una barrera.
- En cualquier otro caso emite `{"continue": true}` y sale 0.
- Nunca refleja el payload ni el mensaje completo en stdout/stderr (evita filtrar
  contenido de sesion a los logs del hook).
- Toda excepcion inesperada -> fail-open. El hook jamas debe ser quien rompa la sesion.

Revision adversarial: Codex (ADOPTAR CON CAMBIOS) exigio los 6 endurecimientos
aplicados aqui, entre ellos tratar `stop_hook_active` AUSENTE como fail-open por ser
campo no documentado en code.claude.com/docs/en/hooks.

Rama de consulta de parada (WOT-2026-215b)
-----------------------
La rama nueva es aditiva y fail-open. Lee un modo opt-in del vuelo y solo
telemetria en ``<flight>/stop_consult_observations.jsonl``. Una excepcion,
un transcript ilegible, un roster ambiguo o un store de T3 no verificable dejan
pasar el Stop; la barrera nunca escribe en ``.agent/runtime`` del motor fuera
del directorio de vuelo y nunca modifica el store.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


_MOTOR_ROOT = Path(__file__).resolve().parents[2]
try:
    _role_key_path = (
        _MOTOR_ROOT / "scripts" / "flight" / "roster_role_key.py"
    ).resolve()
    _role_key_name = "_flt_roster_role_key_" + str(_role_key_path).replace(
        "\\", "_"
    ).replace(":", "_")
    _role_key_spec = importlib.util.spec_from_file_location(
        _role_key_name, _role_key_path
    )
    if _role_key_spec is None or _role_key_spec.loader is None:
        raise ImportError("no se pudo cargar roster_role_key.py")
    _role_key_module = importlib.util.module_from_spec(_role_key_spec)
    _role_key_spec.loader.exec_module(_role_key_module)
    RosterRoleKeyError = _role_key_module.RosterRoleKeyError
    orchestrator_entry = _role_key_module.orchestrator_entry
except Exception as _role_key_exc:

    class RosterRoleKeyError(ValueError):
        """Fallback error when the shared resolver cannot be loaded."""

    def orchestrator_entry(_roles, _error=_role_key_exc):
        """Fail closed for an isolated hook copy without the shared helper."""
        raise RosterRoleKeyError("roster_role_key.py no disponible") from _error


#: Marcadores de clasificacion. Su AUSENCIA es lo que se detecta.
MARKERS: tuple[str, ...] = ("[EVIDENCIA]", "[HIPOTESIS]")

#: El marcador solo CLASIFICA si abre una linea. Un mensaje que se limita a
#: MENCIONARLO ("el hook exige [EVIDENCIA] al cerrar") no esta clasificando nada.
#:
#: DEFECTO REAL medido en el canario de WOT-2026-044y (2026-07-31): al explicar el
#: mecanismo en un cierre, el propio texto contenia los literales y se auto-aprobo
#: (`has_marker: true` en canary_stop.jsonl). Ningun test lo vio porque todos usaban
#: mensajes que o clasificaban de verdad o no mencionaban el marcador.
#:
#: Sigue siendo MECANICO: ancla posicional, no interpretacion de prosa. El prefijo
#: opcional admite el adorno markdown habitual (negrita, cita, vinetas).
MARKER_RE = re.compile(r"(?m)^[ \t>*_]{0,6}\[(?:EVIDENCIA|HIPOTESIS)\]")

#: Centinela opt-in. Sin este fichero el hook es un no-op absoluto.
SENTINEL_RELPATH = Path(".agent") / "runtime" / "verification_mode.json"

# WOT-2026-160p: segunda rama, deliberadamente independiente de WOT-2026-044t.
ESPERA_SENTINEL_RELPATH = Path(".agent") / "runtime" / "espera_checklist_mode.json"
ESPERA_OBSERVATIONS_RELPATH = Path(".agent") / "runtime" / "espera_observations.json"
#: WOT-2026-160z: tope de la telemetria observe con histeresis. NO se reescribe
#: al llegar justo al tope (eso reescribiria en cada parada a partir de ahi);
#: solo se recorta cuando se SUPERA, conservando las ultimas KEEP filas.
ESPERA_OBSERVATIONS_MAX_ROWS = 500
ESPERA_OBSERVATIONS_KEEP_ROWS = 400
_A_ESTRECHO_RE = re.compile(
    r"(sigo esperando|continuo esperando|continúo esperando|sigo a la espera|"
    r"me quedo esperando|quedo esperando)",
    re.IGNORECASE,
)
ESPERA_MARKER_RE = re.compile(r"(?m)^[ \t>*_]{0,6}\[ESPERA:(HECHO|NADA):([^\]]*)\]")

#: WOT-2026-044x: edad maxima del centinela antes de tratarlo como inactivo.
#: Criterio DECLARADO (no hay distribucion empirica de duraciones medida):
#: cubre con margen las sesiones de "varias horas" que acota el DoD (d) de la
#: fila; una sesion viva excepcional que supere 24h pierde la exigencia de
#: recibo en su proximo stop (coste benigno: el hook ya es fail-open ante
#: ambiguedad, tiene escotilla por entorno, y el dueno puede re-armar con
#: `verification_mode.py on`, que re-mide baseline y renueva activated_at).
#: Fecha futura o reloj hacia atras dejan el centinela ARMADO (aritmetica
#: conservadora: nunca producen falso relieve).
SENTINEL_MAX_AGE_S = 24 * 60 * 60

#: Tope defensivo del texto devuelto al agente.
REASON_MAX_LEN = 400

#: Tope de espera de los probes git. Un hook lento degrada cada parada.
GIT_TIMEOUT_S = 5

#: Texto devuelto al agente al bloquear.
#:
#: Los ejemplos van EN LINEA, nunca abriendo linea: si empezaran con el literal,
#: el propio `reason` pasaria el filtro y un agente que lo reenviara tal cual
#: cerraria sin clasificar nada. Lo cazo un test, no una revision.
_REASON = (
    "Cierre sin clasificar tras MUTAR el repo. Abre una linea del mensaje final "
    'con uno de los dos marcadores: "[EVIDENCIA]" seguido del comando, test o '
    'exit code concreto que lo respalda, o "[HIPOTESIS]" seguido de lo que NO '
    "comprobaste. Usa el primero solo si adjuntas recibo; si no mediste, usa el "
    "segundo. Mencionarlos dentro de una frase no clasifica."
)

_ESPERA_REASON = (
    "Cierre que declara espera sin decision. Abre una linea con "
    "[ESPERA:HECHO: texto] si hiciste trabajo avanzable, o con "
    "[ESPERA:NADA: motivo] si no lo hubo; el motivo no puede estar vacio. "
    "Los ejemplos van dentro de una frase para no autoaprobar este reason."
)

# WOT-2026-215b: reason contractual de la consulta. A diferencia de 044t/160z,
# no se recorta: la ficha exige igualdad literal y el texto supera 400 bytes.
_CONSULT_REASON = (
    "BARRERA DE PARADA (WOT-2026-215b): no dejas nada que te responda. Haz una: "
    "(1) ejecuta ya el siguiente paso de tu cola dejando un respondedor "
    "(delegate_task async, schedule_task o tarea en segundo plano); (2) consulta "
    "a tu supervisora con t3_thread_send a <threadId de active_roles.supervisor> "
    "con CONSULTA_SEGUIR_PARAR: <ultima accion> | <cola>, y lanza un temporizador "
    "en segundo plano de 600 s."
)
CONSULT_MODE_RELPATH = Path("stop_consult_mode.json")
CONSULT_PAUSE_RELPATH = Path("stop_consult_pause.json")
CONSULT_OBSERVATIONS_RELPATH = Path("stop_consult_observations.jsonl")
CONSULT_TRANSCRIPT_MAX_BYTES = 8 * 1024 * 1024
CONSULT_TRANSCRIPT_HEAD_BYTES = 128 * 1024
CONSULT_OBSERVATIONS_MAX_BYTES = 8 * 1024 * 1024
CONSULT_OBSERVATIONS_TAIL_BYTES = 512 * 1024
CONSULT_OBSERVATIONS_KEEP_BYTES = 4 * 1024 * 1024
CONSULT_BLOCK_WINDOW_S = 60 * 60
CONSULT_LIVE_WINDOW_S = 10 * 60
CONSULT_ESCAPE_WINDOW_S = 15 * 60
CONSULT_MAX_MINUTES = 60
_CONSULT_ID_RE = re.compile(r"^Eres (CO-\d+),")
_CONSULT_CANONICAL_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def find_repo_root(start: Path) -> Path:
    """Localiza la raiz del repo subiendo hasta encontrar `.claude/`.

    Replica la resolucion del comando inline de `settings.json`. Si no encuentra
    marcador, devuelve `start`: el centinela simplemente no existira y el hook
    quedara en no-op, que es el modo seguro.
    """
    for candidate in [start, *start.parents]:
        if (candidate / ".claude").exists():
            return candidate
    return start


def read_sentinel(root: Path) -> dict | None:
    """Lee el centinela y devuelve su baseline, o None si no esta activo.

    El centinela debe ser un fichero REGULAR. Uno que sea directorio o enlace
    roto se trata como inactivo (fail-open), no como activo: ante ambiguedad,
    el hook no bloquea.

    Contenido esperado: JSON con `baseline_head` y `baseline_status_hash`,
    escrito por quien enciende el modo verificacion. Un centinela vacio o con
    JSON invalido devuelve `{}`: el modo esta activo pero SIN baseline, y
    `repo_mutated` lo tratara como "no se puede probar mutacion" -> no bloquea.
    """
    path = root / SENTINEL_RELPATH
    try:
        if not path.is_file():
            return None
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None

    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def sentinel_expiry(data: dict) -> str:
    """Razon por la que el centinela se trata como INACTIVO ("" si esta vigente).

    WOT-2026-044x: la caducidad se evalua EN LECTURA (NON-GOAL de la fila: ni
    demonio ni limpieza programada). El unico campo con fecha es
    `activated_at` (ISO-8601 UTC, escrito por turn_on).

    - "EXPIRADO: activated_at > SENTINEL_MAX_AGE_S": fecha parseable y mas
      vieja que el umbral (sesion muerta: crash, Ctrl-C, ventana cerrada).
    - "SIN-FECHA-LEGIBLE: activated_at ausente o ilegible": sin prueba de
      vigencia. DoD (e): fail-open, "nunca bloquea ante ambiguedad" -- la unica
      lectura que garantiza no-bloqueo ante edad desconocida es tratarla como
      inactiva, que ademas da relevo a centinelas legacy sin el campo. La
      etiqueta es LITERAL y compartida con `verification_mode.py status`
      (terminologia unica para el operador; adjudicacion L702-A1).

    Las dos etiquetas son literales estables: los tests y el diagnostico del
    operador las matchean por texto.
    """
    raw = data.get("activated_at")
    if not isinstance(raw, str) or not raw.strip():
        return "SIN-FECHA-LEGIBLE: activated_at ausente o ilegible"
    try:
        activated = datetime.fromisoformat(raw.strip())
    except ValueError:
        return "SIN-FECHA-LEGIBLE: activated_at ausente o ilegible"
    if activated.tzinfo is None:
        activated = activated.replace(tzinfo=timezone.utc)
    age_s = (datetime.now(timezone.utc) - activated).total_seconds()
    if age_s > SENTINEL_MAX_AGE_S:
        return f"EXPIRADO: activated_at > {SENTINEL_MAX_AGE_S}s"
    return ""


def _git(root: Path, *args: str) -> str | None:
    """Ejecuta git en `root` y devuelve stdout, o None si no se pudo medir."""
    try:
        proc = subprocess.run(  # noqa: S603
            ["git", "-C", str(root), *args],  # noqa: S607
            capture_output=True,
            timeout=GIT_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8", "replace")


def repo_mutated(root: Path, baseline: dict) -> bool:
    """True solo si HAY PRUEBA de que el arbol cambio desde el baseline.

    Compara HEAD y el hash de `git status --porcelain` contra los valores
    guardados al encender el modo verificacion. Es un hecho ESTRUCTURAL sobre
    el repo, no una interpretacion del texto del agente.

    Devuelve False ante cualquier ambiguedad -- baseline ausente, git ilegible,
    timeout, directorio sin repo -- porque sin prueba de mutacion no hay motivo
    para bloquear (fail-open).
    """
    head_expected = baseline.get("baseline_head")
    status_expected = baseline.get("baseline_status_hash")
    if not isinstance(head_expected, str) or not isinstance(status_expected, str):
        return False

    head_now = _git(root, "rev-parse", "HEAD")
    status_now = _git(root, "status", "--porcelain")
    if head_now is None or status_now is None:
        return False

    if head_now.strip() != head_expected.strip():
        return True
    return status_hash(status_now) != status_expected


def status_hash(status_text: str) -> str:
    """Hash estable de `git status --porcelain`, normalizando saltos de linea.

    Excluye del calculo el propio centinela y su directorio: encender el modo
    ESCRIBE un fichero dentro del arbol, asi que sin esta exclusion el centinela
    se veria a si mismo como mutacion y bloquearia todo cierre desde el primer
    turno. Medido en probe hermetico: tras crear el centinela, `git status`
    pasa de vacio a `?? .agent/`.
    """
    noise = (
        ".agent/runtime/verification_mode.json",
        ".agent/runtime/verification_observations.json",
        ".agent/runtime/",
        ".agent/",
    )
    kept = []
    for line in status_text.replace("\r\n", "\n").split("\n"):
        path = line[3:].strip() if len(line) > 3 else ""
        if path and path in noise:
            continue
        kept.append(line)
    return hashlib.sha256("\n".join(kept).encode("utf-8")).hexdigest()


def classifies(message: str) -> bool:
    """True si alguna linea FUERA de un bloque de codigo abre con un marcador.

    Ignorar los fences cierra el ultimo hueco del ancla posicional: un cierre que
    MUESTRE un ejemplo dentro de ``` se auto-aprobaria, que es la misma familia
    del defecto que el canario cazo en vivo (mencionar != clasificar), solo que
    por otra via.

    Medido sobre el corpus real (33.476 mensajes finales de 1654 transcripts):
    871 llevan fence (2,6%) y CERO tienen su unico marcador dentro de uno. Se
    cierra igual porque el caso natural donde aparece es documentar el propio
    mecanismo -- exactamente lo que ya fallo una vez.

    Sigue siendo mecanico: cuenta delimitadores y mira posicion, no interpreta.

    WOT-2026-160p ronda 3 de lentes (hallazgo codex, MAJOR): esta funcion usaba
    el helper CommonMark-aware `_lines_outside_fences` (tipo+longitud), que
    cambiaba el veredicto real de 044t en mensajes con fences de longitud
    mixta o con texto tras el cierre (medido: `classifies("````text\\n```\\n
    [EVIDENCIA] x")` pasaba de True a False) -- rompiendo el contrato
    "SIN CAMBIOS" de esta barrera, YA EN PRODUCCION, sin que ningun centinela
    de espera estuviera armado. 044t vuelve a su propio helper legado,
    BYTE A BYTE igual al algoritmo original (toggle simple, ignora longitud
    y contenido tras el delimitador); el helper CommonMark-aware queda de uso
    EXCLUSIVO de `espera_classifies`.
    """
    return any(MARKER_RE.match(line) for line in _lines_outside_fences_legacy(message))


def _lines_outside_fences_legacy(message: str):
    """Before: texto crudo; During: alterna con un toggle SIMPLE de ``` (sin
    mirar longitud ni contenido tras el delimitador); After: lineas utiles.

    Uso EXCLUSIVO de `classifies()` (044t): es el algoritmo ORIGINAL de
    WOT-2026-044t, preservado byte a byte tras el hallazgo de la ronda 3 de
    lentes de WOT-2026-160p (ver docstring de `classifies`).
    """
    in_fence = False
    for line in message.replace("\r\n", "\n").split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        yield line


def _fence_open_run(stripped_line: str, char: str) -> int:
    """Before: linea sin indentacion y el caracter de fence; During: cuenta la
    racha inicial de ESE caracter; After: longitud (>=3) o 0 si no abre.

    CommonMark: abre con 3+ backticks/tildes seguidos, pudiendo llevar un
    "info string" detras (ej. "````text"); por eso NO exige que el resto de
    la linea sea tambien el caracter.
    """
    run = 0
    for c in stripped_line:
        if c != char:
            break
        run += 1
    return run if run >= 3 else 0


def _fence_close_run(stripped_line: str, char: str) -> int:
    """Before: linea sin indentacion y el caracter de fence; After: longitud
    si la linea es EXCLUSIVAMENTE ese caracter repetido, 0 en otro caso.

    CommonMark: una linea de cierre no puede llevar nada detras del propio
    delimitador (space/tab aparte, ya recortados por rstrip): "```python" no
    cierra nada, es contenido normal.
    """
    rstripped = stripped_line.rstrip()
    if rstripped and set(rstripped) == {char}:
        return len(rstripped)
    return 0


def _lines_outside_fences(message: str, fence_markers: tuple[str, ...] = ("```",)):
    """Before: texto crudo y los delimitadores de fence reconocidos; During:
    abre con el primer delimitador que matchee y SOLO cierra con el MISMO
    caracter y una racha de longitud >= la de apertura (CommonMark: nunca
    cruza tipos ni longitudes cortas); After: produce las lineas utiles.

    Uso EXCLUSIVO de `espera_classifies` (pasa ``` y ~~~). WOT-2026-160p
    ronda 2 de lentes (hallazgo codex, MAJOR): antes solo se recordaba el
    TIPO de delimitador, no su LONGITUD; una apertura de 4 backticks
    ("````text") se cerraba con una linea de solo 3 ("```"), dejando el
    marcador real "fuera" (visible) cuando en realidad seguia DENTRO del
    bloque sin cerrar. `espera_classifies` pasa ademas ``~~~`` (hallazgo
    previo: un marcador dentro de un bloque ``~~~`` se auto-aprobaba porque
    solo se reconocia ```). WOT-2026-160p ronda 3 de lentes (hallazgo codex,
    MAJOR): este helper NO es equivalente al algoritmo original de 044t para
    fences de longitud mixta o con texto tras el cierre -- 044t usa su PROPIO
    helper legado `_lines_outside_fences_legacy` (ver docstring de
    `classifies`); el valor por defecto `("```",)` de este parametro ya NO es
    el contrato de 044t, es solo la firma por defecto de esta funcion.
    """
    fence_chars = tuple(marker[0] for marker in fence_markers)
    in_fence = False
    fence_char = None
    fence_len = 0
    for line in message.replace("\r\n", "\n").split("\n"):
        stripped = line.lstrip()
        if in_fence:
            if _fence_close_run(stripped, fence_char) >= fence_len:
                in_fence = False
                fence_char = None
                fence_len = 0
            continue
        opened_len = 0
        opened_char = None
        for char in fence_chars:
            run = _fence_open_run(stripped, char)
            if run:
                opened_len = run
                opened_char = char
                break
        if opened_len:
            in_fence = True
            fence_char = opened_char
            fence_len = opened_len
            continue
        yield line


def _espera_guard_allows(payload: dict) -> bool:
    """Before: payload Stop; During: aplica el guard 044t; After: indica si puede actuar."""
    return "stop_hook_active" in payload and not payload.get("stop_hook_active")


def _last_sentence(text: str) -> str:
    """Before: texto crudo; During: separa por puntuacion O por salto de linea
    (sin exigir puntuacion antes del salto); After: devuelve la ultima frase.

    WOT-2026-160p ronda 2 de lentes (hallazgo codex, MAJOR): el regex anterior
    ``(?<=[.!?\\n])\\s+`` exigia que el CARACTER antes del tramo de espacios
    fuera uno de ``.!?\\n`` -- pero un salto de linea SIN puntuacion previa
    (``"Sigo esperando\\nYa termine."``) no cumplia esa condicion (el caracter
    antes del ``\\n`` era una letra), asi que el texto quedaba SIN separar y
    `declares_wait` veia el literal "sigo esperando" aunque la frase real
    (``"Ya termine."``) ya no declarara espera. Ahora cualquier corte de
    linea separa SIEMPRE, independientemente de lo que lo preceda.
    """
    text = text.strip()
    if not text:
        return ""
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    parts = [part for part in parts if part.strip()]
    return parts[-1] if parts else text


def declares_wait(message: str) -> bool:
    """Before: mensaje crudo; During: examina su ultima frase; After: devuelve el disparador A."""
    return bool(_A_ESTRECHO_RE.search(_last_sentence(message)))


def espera_classifies(message: str) -> bool:
    """Before: mensaje final; During: ignora fences ``` y ~~~ y valida motivo;
    After: indica marcador DC valido."""
    for line in _lines_outside_fences(message, fence_markers=("```", "~~~")):
        match = ESPERA_MARKER_RE.match(line)
        if match and match.group(2).strip():
            return True
    return False


def read_espera_sentinel(root: Path) -> dict | None:
    """Before: raiz del repo; During: lee el centinela; After: `None` si NO es
    un fichero regular legible (ausente, directorio, enlace roto -- ninguno
    de esos casos prueba que el modo este activo); `{}` si el fichero SI es
    regular pero esta vacio, con JSON invalido o con JSON que no es un objeto
    (COMPORTAMIENTO REAL, corregido en ronda 3 de lentes: `_decide_espera`
    trata `{}` exactamente IGUAL que `None` -- `{}.get("mode")` nunca esta en
    `("observe", "block")`, asi que no registra ni bloquea; no es un estado
    "activo sin dato", es fail-open total, como el centinela ausente); el
    dict parseado en cualquier otro caso. WOT-2026-160p ronda 2 de lentes
    (hallazgo codex,
    MAJOR): un centinela con BYTES invalidos (no UTF-8) lanzaba
    `UnicodeDecodeError` en `read_text`, que esta funcion no capturaba (solo
    `OSError`); como `_decide` evalua siempre la rama de espera antes de
    devolver el veredicto de 044t, esa excepcion se perdia el bloqueo real
    de 044t. Ahora un fichero REGULAR con contenido illegible (bytes o JSON)
    es el mismo caso que JSON invalido: `{}`, no una excepcion."""
    target = root / ESPERA_SENTINEL_RELPATH
    try:
        if not target.is_file():
            return None
    except OSError:
        return None
    try:
        raw = target.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return {}
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _rotate_espera_observations(target: Path) -> None:
    """Before: JSONL ya escrito; During: recorta SOLO si supera el tope; After:
    conserva las ultimas KEEP filas mediante temporal + `os.replace`.

    WOT-2026-160z: histeresis deliberada. Si se recortase al llegar JUSTO al
    tope, toda parada posterior reescribiria el fichero; aqui solo se paga esa
    reescritura cuando el fichero ya lo supero, y el recorte deja margen.

    Fail-open total: cualquier fallo de lectura o escritura deja el fichero como
    estaba. Es telemetria, nunca el veredicto del gancho. No parsea las lineas
    (conserva las ultimas tal cual), asi que una linea ilegible no puede hacer
    fallar la rotacion.

    Riesgo declarado: varias sesiones pueden anexar a la vez; un recorte
    concurrente puede perder filas recien anexadas por otra sesion (perdida de
    telemetria, NO del veredicto).
    """
    try:
        raw = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    lines = [line for line in raw.splitlines() if line.strip()]
    if len(lines) <= ESPERA_OBSERVATIONS_MAX_ROWS:
        return
    kept = lines[-ESPERA_OBSERVATIONS_KEEP_ROWS:]
    tmp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text("\n".join(kept) + "\n", encoding="utf-8")
        os.replace(tmp, target)
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink()


def _record_espera_observation(
    root: Path, payload: dict, trigger_a: bool, ya_clasificado: bool, message: str
) -> None:
    """Before: datos no sensibles; During: anade JSONL y aplica el tope; After:
    falla abierto si no escribe (el veredicto nunca depende de la telemetria)."""
    try:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": payload.get("session_id"),
            "trigger_a": trigger_a,
            "ya_clasificado": ya_clasificado,
            "background_tasks_nonempty": bool(payload.get("background_tasks")),
            "session_crons_nonempty": bool(payload.get("session_crons")),
            "message_len": len(message),
        }
        target = root / ESPERA_OBSERVATIONS_RELPATH
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        _rotate_espera_observations(target)
    except (OSError, TypeError, ValueError):
        return


def _decide_espera(root: Path, payload: dict) -> dict:
    """Before: payload y centinela nuevo; During: observa o bloquea; After: devuelve veredicto.

    WOT-2026-160z: el centinela de espera se evalua con la MISMA caducidad que
    el de 044t (`sentinel_expiry`, etiquetas EXPIRADO / SIN-FECHA-LEGIBLE). Un
    centinela caducado, vacio o con fecha ilegible queda INACTIVO: no registra
    ni bloquea. Reusar la funcion evita una segunda vara de caducidad.
    """
    sentinel = read_espera_sentinel(root)
    if sentinel is None or sentinel.get("mode") not in ("observe", "block"):
        return {"continue": True}
    expiry = sentinel_expiry(sentinel)
    if expiry:
        sys.stderr.write(
            f"native_stop_hook: centinela de espera {expiry}; tratado como INACTIVO.\n"
        )
        return {"continue": True}
    if not _espera_guard_allows(payload):
        return {"continue": True}
    message = payload.get("last_assistant_message")
    if not isinstance(message, str) or not message.strip():
        return {"continue": True}
    trigger_a = declares_wait(message)
    ya_clasificado = espera_classifies(message)
    if sentinel["mode"] == "observe":
        _record_espera_observation(root, payload, trigger_a, ya_clasificado, message)
        return {"continue": True}
    if trigger_a and not ya_clasificado:
        return {"decision": "block", "reason": _ESPERA_REASON[:REASON_MAX_LEN]}
    return {"continue": True}


def _p9_resolve_co_activa(flight_dir: Path) -> str | None:
    """Before: vuelo con roster; During: detecta una sola clave CO; After: codigo o None fail-closed."""
    try:
        raw = (flight_dir / "flight_roster.json").read_text(encoding="utf-8-sig")
        data = json.loads(raw)
    except (OSError, UnicodeDecodeError, ValueError, TypeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("active_roles"), dict):
        return None
    candidates = []
    for key, value in data["active_roles"].items():
        if key == "_schema_note" or not isinstance(value, dict):
            continue
        if (
            key in ("orquestador", "coordinadora")
            or key.startswith("orquestador")
            or value.get("role") in ("orquestador", "orquestadora")
        ):
            candidates.append(value)
    if len(candidates) != 1:
        return None
    try:
        resolved = orchestrator_entry(data["active_roles"])
    except RosterRoleKeyError:
        return None
    if resolved is None:
        return None
    session_code = resolved.get("session_code") if isinstance(resolved, dict) else None
    if not isinstance(session_code, str) or not session_code.strip():
        return None
    return session_code.strip()


def _p9_gitdir_topology(root: Path) -> tuple[list[Path], list[Path]]:
    """Before: raiz posible de worktree; During: resuelve checkout y link; After: bases y links."""
    bases: list[Path] = []
    link_paths: list[Path] = []
    try:
        git_marker = root / ".git"
        if not git_marker.is_file():
            return bases, link_paths
        marker = git_marker.read_text(encoding="utf-8").strip()
        if not marker.startswith("gitdir:"):
            return bases, link_paths
        gitdir = Path(marker.split(":", 1)[1].strip())
        if not gitdir.is_absolute():
            gitdir = root / gitdir
        current = gitdir.resolve()
        for candidate in (current, *current.parents):
            if candidate.name == ".git":
                base = candidate.parent
                bases.append(base)
                link_paths.append(
                    base / ".agent" / "config" / "motor_destination_link.json"
                )
                break
    except (OSError, RuntimeError, UnicodeDecodeError, ValueError):
        return [], []
    return bases, link_paths


def _p9_destination_roots(link_paths: list[Path]) -> list[Path]:
    """Before: links candidatos; During: lee destinos validos; After: raices destino."""
    roots: list[Path] = []
    for link in link_paths:
        destination = _p9_destination_root(link)
        if destination is not None:
            roots.append(destination)
    return roots


def _p9_destination_root(link: Path) -> Path | None:
    """Before: link JSON; During: extrae destino; After: Path valida o None."""
    try:
        data = json.loads(link.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError, TypeError):
        return None
    destination = data.get("destination_root") if isinstance(data, dict) else None
    if isinstance(destination, str) and destination:
        return Path(destination)
    return None


def _p9_linked_roots(root: Path) -> list[Path]:
    """Before: raiz activa; During: incorpora topologia y links; After: raices a explorar."""
    bases, topology_links = _p9_gitdir_topology(root)
    direct_link = root / ".agent" / "config" / "motor_destination_link.json"
    links = [direct_link, *topology_links]
    return [root, *bases, *_p9_destination_roots(links)]


def _consult_flights(root: Path) -> list[Path]:
    """Before: root may be a motor worktree or destination; During: censuses linked flights; After: returns unique flight dirs."""
    candidates: dict[Path, Path] = {}
    try:
        for base in _p9_linked_roots(root):
            flight_root = base / ".agent" / "runtime" / "flight"
            for roster in flight_root.glob("*/flight_roster.json"):
                if roster.is_file():
                    resolved = roster.resolve()
                    candidates[resolved] = resolved.parent
    except (OSError, RuntimeError, ValueError):
        return []
    return sorted(candidates.values(), key=str)


def _consult_read_mode(flight_dir: Path) -> tuple[str, dict]:
    """Before: a flight directory; During: reads its opt-in mode tolerantly; After: returns mode and object."""
    target = flight_dir / CONSULT_MODE_RELPATH
    try:
        if not target.is_file():
            return "off", {}
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, TypeError):
        return "off", {}
    if not isinstance(data, dict) or data.get("mode") not in {
        "off",
        "observe",
        "canary",
        "block",
    }:
        return "off", {}
    return str(data["mode"]), data


def _consult_parse_dt(value: object) -> datetime | None:
    """Before: an arbitrary timestamp; During: parses ISO-8601; After: returns UTC or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        result = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return (
        result if result.tzinfo else result.replace(tzinfo=timezone.utc)
    ).astimezone(timezone.utc)


def _consult_text(row: dict) -> str | None:
    """Before: one transcript row; During: extracts text blocks; After: returns joined text or None."""
    message = row.get("message") if isinstance(row.get("message"), dict) else row
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None
    parts = [
        block.get("text")
        for block in content
        if isinstance(block, dict) and isinstance(block.get("text"), str)
    ]
    return "".join(parts) if parts else None


def _consult_blocks(row: dict, block_type: str) -> list[dict]:
    """Before: transcript row; During: filters content blocks by type; After: returns dict blocks."""
    message = row.get("message") if isinstance(row.get("message"), dict) else row
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list):
        return []
    return [
        block
        for block in content
        if isinstance(block, dict) and block.get("type") == block_type
    ]


def _consult_read_transcript(
    path: Path, prompt_id: str
) -> tuple[list[dict], dict, dict]:
    """Before: readable JSONL transcript and prompt id; During: reads bounded tail/head; After: turn rows, first user and opener."""
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            handle.seek(max(0, size - CONSULT_TRANSCRIPT_MAX_BYTES))
            tail = handle.read(CONSULT_TRANSCRIPT_MAX_BYTES)
            handle.seek(0)
            head = handle.read(CONSULT_TRANSCRIPT_HEAD_BYTES)
    except (OSError, ValueError) as exc:
        raise ValueError("transcript_ilegible") from exc

    def decode_rows(raw: bytes) -> list[dict]:
        result = []
        for line in raw.decode("utf-8", "replace").splitlines():
            try:
                item = json.loads(line)
            except (TypeError, ValueError):
                continue
            if isinstance(item, dict):
                result.append(item)
        return result

    tail_rows = decode_rows(tail)
    turn = [row for row in tail_rows if row.get("promptId") == prompt_id]
    all_head = decode_rows(head)
    first_user = next((row for row in all_head if row.get("type") == "user"), None)
    opener = next((row for row in turn if row.get("type") == "user"), None)
    if not turn or first_user is None or opener is None:
        raise ValueError("turno_no_delimitado")
    return turn, first_user, opener


def _consult_roster(flight_dir: Path) -> tuple[dict, dict]:
    """Before: flight roster path; During: resolves the sole orchestrator role; After: returns roster and active entry."""
    try:
        data = json.loads(
            (flight_dir / "flight_roster.json").read_text(encoding="utf-8-sig")
        )
        roles = data.get("active_roles") if isinstance(data, dict) else None
        if not isinstance(roles, dict):
            raise ValueError("active_roles ausente")
        entry = orchestrator_entry(roles)
    except (
        OSError,
        UnicodeDecodeError,
        ValueError,
        TypeError,
        RosterRoleKeyError,
    ) as exc:
        raise ValueError("roster_no_medido") from exc
    if not isinstance(entry, dict):
        raise ValueError("roster_no_medido")
    return data, entry


def _consult_record(
    flight_dir: Path,
    payload: dict,
    mode: str,
    *,
    es_orquestadora: bool | None,
    respondedor: str | None,
    pausa: bool,
    decision: str,
    motivo: str,
    has_transcript_path: bool,
    nota: str | None = None,
) -> None:
    """Before: privacy-safe decision metadata; During: appends one JSONL row; After: fails open on write errors."""
    try:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": payload.get("session_id"),
            "prompt_id": payload.get("prompt_id")
            if isinstance(payload.get("prompt_id"), str)
            else None,
            "es_orquestadora": es_orquestadora,
            "modo": mode,
            "respondedor": respondedor,
            "pausa": bool(pausa),
            "decision": decision,
            "motivo": motivo,
            "has_transcript_path": bool(has_transcript_path),
            "payload_keys": sorted(str(key) for key in payload),
        }
        if nota:
            record["nota"] = nota
        target = flight_dir / CONSULT_OBSERVATIONS_RELPATH
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = (
            json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        descriptor = os.open(str(target), os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.write(descriptor, raw)
        finally:
            os.close(descriptor)
        _consult_rotate_observations(target)
    except (OSError, TypeError, ValueError):
        return


def _consult_tail_lines(path: Path, limit: int) -> list[str]:
    """Before: JSONL path and byte limit; During: reads only a complete tail; After: returns lines without a partial head."""
    with path.open("rb") as handle:
        size = handle.seek(0, os.SEEK_END)
        handle.seek(max(0, size - limit))
        raw = handle.read()
    if size > limit:
        separator = raw.find(b"\n")
        raw = raw[separator + 1 :] if separator >= 0 else b""
    return raw.decode("utf-8").splitlines()


def _consult_observation_rows(flight_dir: Path) -> list[dict]:
    """Before: flight observation JSONL; During: parses its bounded tail; After: valid rows only, fail-open on I/O."""
    try:
        lines = _consult_tail_lines(
            flight_dir / CONSULT_OBSERVATIONS_RELPATH,
            CONSULT_OBSERVATIONS_TAIL_BYTES,
        )
    except (OSError, UnicodeDecodeError, ValueError):
        return []
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except (TypeError, ValueError):
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _consult_rotate_observations(target: Path) -> None:
    """Before: appended observation file; During: atomically keeps a complete four-MiB tail; After: bounded JSONL or unchanged file."""
    temporary: Path | None = None
    try:
        if target.stat().st_size <= CONSULT_OBSERVATIONS_MAX_BYTES:
            return
        lines = _consult_tail_lines(target, CONSULT_OBSERVATIONS_KEEP_BYTES)
        temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            if lines:
                handle.write("\n".join(lines) + "\n")
        os.replace(temporary, target)
    except (OSError, UnicodeDecodeError, ValueError):
        if temporary is not None:
            with contextlib.suppress(OSError):
                temporary.unlink()


def _consult_tool_respondedor(  # noqa: C901
    rows: list[dict], payload: dict, supervisor_thread: str | None
) -> str | None:
    """Before: delimited turn rows; During: pairs tool calls/results; After: accredited responder or None."""
    if payload.get("background_tasks"):
        return "background_tasks"
    uses: list[dict] = []
    results: dict[str, dict] = {}
    for row in rows:
        uses.extend(_consult_blocks(row, "tool_use"))
        for block in _consult_blocks(row, "tool_result"):
            tool_id = block.get("tool_use_id")
            if isinstance(tool_id, str):
                results[tool_id] = block
    accredited: list[tuple[str, dict, dict]] = []
    for use in uses:
        tool_id = use.get("id")
        result = results.get(tool_id) if isinstance(tool_id, str) else None
        if result is not None and not result.get("is_error", False):
            accredited.append(
                (str(use.get("name", "")), use.get("input") or {}, result)
            )
    for name, input_data, _result in accredited:
        if (
            name.endswith("delegate_task")
            and input_data.get("mode", "async") == "async"
        ):
            return "delegate_async"
    for name, _input_data, _result in accredited:
        if name.endswith("schedule_task"):
            return "schedule_task"
    for name, input_data, _result in accredited:
        if (
            name.endswith("t3_thread_send")
            and isinstance(supervisor_thread, str)
            and input_data.get("threadId") == supervisor_thread
            and isinstance(input_data.get("message"), str)
            and input_data["message"].startswith("CONSULTA_SEGUIR_PARAR")
            and (
                payload.get("background_tasks")
                or any(n.endswith("schedule_task") for n, _, _ in accredited)
            )
        ):
            return "consulta_supervisora"
    return None


def _consult_origin_user(  # noqa: C901
    flight_dir: Path, opening: dict, roster_entry: dict
) -> tuple[bool, bool]:
    """Before: opening user row and orchestrator roster entry; During: reads T3 store RO and matches normalized text/time; After: (is_user, no_medido).

    The text-plus-nearest-timestamp join is inherently fragile: transcript and
    projection clocks can drift, and duplicate text can be ambiguous. The store
    query is limited to the two hours before the opening row and 200 rows; a
    message queued earlier and consumed later therefore becomes
    ``no_medido_origen`` and never exempts or blocks by itself. Any uncertainty
    is deliberately reported as ``no_medido_origen`` and never becomes a user
    exemption.
    """
    try:
        opening_text = _consult_text(opening)
        opening_raw = opening.get("timestamp") or opening.get("created_at")
        opening_dt = _consult_parse_dt(opening_raw)
        thread_id = roster_entry.get("threadId")
        if (
            not isinstance(opening_text, str)
            or not opening_text
            or not isinstance(opening_raw, str)
            or _CONSULT_CANONICAL_TS_RE.fullmatch(opening_raw) is None
            or opening_dt is None
            or not isinstance(thread_id, str)
        ):
            raise ValueError("origen_no_extraible")
        module_path = (
            _MOTOR_ROOT / "scripts" / "flight" / "verify_user_authorization.py"
        )
        spec = importlib.util.spec_from_file_location(
            "_consult_verify_user_authorization", module_path
        )
        if spec is None or spec.loader is None:
            raise ImportError("verify_user_authorization.py no disponible")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
        finally:
            sys.modules.pop(spec.name, None)
        db_path = os.environ.get("T3_STATE_DB") or str(
            Path.home() / ".t3" / "userdata" / "statev2.sqlite"
        )
        connection = module.open_store_ro(db_path, timeout=1.0)
        try:
            module.check_schema(connection)
            thread_spec = importlib.util.spec_from_file_location(
                "_consult_thread_id",
                _MOTOR_ROOT / "scripts" / "flight" / "thread_id.py",
            )
            if thread_spec is None or thread_spec.loader is None:
                raise ImportError("thread_id.py no disponible")
            thread_module = importlib.util.module_from_spec(thread_spec)
            thread_spec.loader.exec_module(thread_module)
            prefix = str(thread_module.MCP_PREFIX)
            thread_ids = [thread_id]
            if thread_id.startswith(prefix):
                thread_ids.append(thread_id[len(prefix) :])
            else:
                thread_ids.append(prefix + thread_id)
            placeholders = ",".join("?" for _ in thread_ids)
            sql = (
                f"SELECT message_id, thread_id, created_at, updated_at, streaming, payload_json "  # noqa: S608
                f"FROM {module.SCHEMA_MESSAGES} WHERE thread_id IN ({placeholders}) "
                "AND created_at >= ? AND created_at <= ? "
                "ORDER BY created_at DESC LIMIT 200"
            )
            expected = module.normalize_text(opening_text)
            if expected is None:
                raise ValueError("texto_no_normalizable")
            candidates = []
            lower = (opening_dt - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S.%f")[
                :23
            ] + "Z"
            upper = opening_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:23] + "Z"
            parameters = [*thread_ids, lower, upper]
            for row in connection.execute(sql, parameters):
                record = module._row_to_record(row)
                if (
                    record.normalized_text == expected
                    and record.created_dt <= opening_dt
                ):
                    candidates.append(record)
        finally:
            connection.close()
        if not candidates:
            raise ValueError("origen_no_encontrado")
        closest = min(opening_dt - candidate.created_dt for candidate in candidates)
        nearest = [
            candidate
            for candidate in candidates
            if opening_dt - candidate.created_dt == closest
        ]
        if len(nearest) != 1:
            raise ValueError("origen_ambiguo")
        return nearest[0].created_by == "user", False
    except Exception:
        return False, True


def _consult_pause_valid(flight_dir: Path, roster: dict) -> bool:
    """Before: current roster and optional pause JSON; During: checks authority, epoch, expiry and declared duration; After: validity boolean."""
    try:
        data = json.loads(
            (flight_dir / CONSULT_PAUSE_RELPATH).read_text(encoding="utf-8")
        )
        roles = roster["active_roles"]
        supervisor = roles["supervisor"]
        until = _consult_parse_dt(data.get("hasta"))
        set_at = _consult_parse_dt(data.get("set_at"))
        minutes = data.get("minutos")
        now = datetime.now(timezone.utc)
        return bool(
            until
            and set_at
            and now < until
            and str(data.get("epoca")) == str(supervisor.get("version"))
            and data.get("supervisor_threadId") == supervisor.get("threadId")
            and isinstance(minutes, int)
            and not isinstance(minutes, bool)
            and minutes <= CONSULT_MAX_MINUTES
            and (until - set_at).total_seconds() <= minutes * 60 + 5
            and (until - now).total_seconds() <= CONSULT_MAX_MINUTES * 60 + 5
        )
    except (OSError, UnicodeDecodeError, ValueError, TypeError, KeyError):
        return False


def _consult_recent(
    flight_dir: Path,
    session_id: object,
    *,
    decision: str | None = None,
    responder: str | None = None,
    window: int,
) -> bool:
    """Before: flight observation log; During: scans one session and time window; After: matching boolean."""
    try:
        rows = _consult_observation_rows(flight_dir)
    except (OSError, UnicodeDecodeError, ValueError, TypeError):
        return False
    now = datetime.now(timezone.utc)
    for row in rows:
        if not isinstance(row, dict) or row.get("session_id") != session_id:
            continue
        stamp = _consult_parse_dt(row.get("ts"))
        if (
            stamp is None
            or (now - stamp).total_seconds() < 0
            or (now - stamp).total_seconds() > window
        ):
            continue
        if decision is not None and row.get("decision") != decision:
            continue
        if responder is not None and row.get("respondedor") != responder:
            continue
        return True
    return False


def _consult_count(
    flight_dir: Path, session_id: object, *, decision: str, window: int
) -> int:
    """Before: flight observation log; During: counts matching rows in one session/window; After: integer count or zero on read failure."""
    try:
        rows = _consult_observation_rows(flight_dir)
    except (OSError, UnicodeDecodeError, ValueError, TypeError):
        return 0
    now = datetime.now(timezone.utc)
    count = 0
    for row in rows:
        if (
            not isinstance(row, dict)
            or row.get("session_id") != session_id
            or row.get("decision") != decision
        ):
            continue
        stamp = _consult_parse_dt(row.get("ts"))
        if stamp is None:
            continue
        age = (now - stamp).total_seconds()
        if 0 <= age <= window:
            count += 1
    return count


def _consult_branch(root: Path, payload: dict) -> dict:  # noqa: C901
    """Before: Stop payload and resolved repo root; During: evaluates WOT-2026-215b; After: returns block reason or fail-open continue."""
    flight_dir: Path | None = None
    mode = "off"
    active_mode = False
    try:
        flights = _consult_flights(root)
        if len(flights) > 1:
            modes = [_consult_read_mode(flight)[0] for flight in flights]
            if any(mode != "off" for mode in modes):
                sys.stderr.write(
                    "native_stop_hook: vuelo_ambiguo; consulta de parada omitida\n"
                )
            return {"block_reason": None}
        if not flights:
            return {"block_reason": None}
        flight_dir = flights[0]
        mode, mode_data = _consult_read_mode(flight_dir)
        if mode == "off":
            return {"block_reason": None}
        active_mode = True
        transcript_value = payload.get("transcript_path")
        transcript = (
            Path(transcript_value)
            if isinstance(transcript_value, str) and transcript_value
            else None
        )
        has_transcript = bool(transcript and transcript.is_file())
        if "stop_hook_active" not in payload or payload.get("stop_hook_active"):
            reason = (
                "escape_segundo_cierre"
                if _consult_recent(
                    flight_dir,
                    payload.get("session_id"),
                    decision="block",
                    window=CONSULT_ESCAPE_WINDOW_S,
                )
                else "reentrada"
            )
            _consult_record(
                flight_dir,
                payload,
                mode,
                es_orquestadora=None,
                respondedor=None,
                pausa=False,
                decision="continue",
                motivo=reason,
                has_transcript_path=has_transcript,
            )
            return {"block_reason": None}
        prompt_id = payload.get("prompt_id")
        if not has_transcript or not isinstance(prompt_id, str) or not prompt_id:
            _consult_record(
                flight_dir,
                payload,
                mode,
                es_orquestadora=None,
                respondedor=None,
                pausa=False,
                decision="no_medido",
                motivo="sin_transcript",
                has_transcript_path=has_transcript,
            )
            return {"block_reason": None}
        try:
            rows, first_user, opening = _consult_read_transcript(transcript, prompt_id)
        except ValueError as exc:
            _consult_record(
                flight_dir,
                payload,
                mode,
                es_orquestadora=None,
                respondedor=None,
                pausa=False,
                decision="no_medido",
                motivo=str(exc),
                has_transcript_path=has_transcript,
            )
            return {"block_reason": None}
        identity_text = _consult_text(first_user)
        identity = _CONSULT_ID_RE.match(identity_text or "")
        if identity is None:
            _consult_record(
                flight_dir,
                payload,
                mode,
                es_orquestadora=False,
                respondedor=None,
                pausa=False,
                decision="continue",
                motivo="no_orquestadora",
                has_transcript_path=True,
            )
            return {"block_reason": None}
        try:
            roster, entry = _consult_roster(flight_dir)
        except ValueError as exc:
            _consult_record(
                flight_dir,
                payload,
                mode,
                es_orquestadora=None,
                respondedor=None,
                pausa=False,
                decision="no_medido",
                motivo=str(exc),
                has_transcript_path=True,
            )
            return {"block_reason": None}
        if entry.get("estado") != "ACTIVO":
            _consult_record(
                flight_dir,
                payload,
                mode,
                es_orquestadora=None,
                respondedor=None,
                pausa=False,
                decision="no_medido",
                motivo="orquestadora_no_activa",
                has_transcript_path=True,
            )
            return {"block_reason": None}
        if entry.get("session_code") != identity.group(1):
            _consult_record(
                flight_dir,
                payload,
                mode,
                es_orquestadora=False,
                respondedor=None,
                pausa=False,
                decision="continue",
                motivo="identidad_no_casa",
                has_transcript_path=True,
            )
            return {"block_reason": None}
        origin_note = None
        is_user, origin_unmeasured = _consult_origin_user(flight_dir, opening, entry)
        if origin_unmeasured:
            origin_note = "no_medido_origen"
        if is_user:
            _consult_record(
                flight_dir,
                payload,
                mode,
                es_orquestadora=True,
                respondedor=None,
                pausa=False,
                decision="continue",
                motivo="turno_de_usuario",
                has_transcript_path=True,
            )
            return {"block_reason": None}
        supervisor = roster.get("active_roles", {}).get("supervisor", {})
        supervisor_thread = (
            supervisor.get("threadId") if isinstance(supervisor, dict) else None
        )
        responder = _consult_tool_respondedor(rows, payload, supervisor_thread)
        if responder:
            _consult_record(
                flight_dir,
                payload,
                mode,
                es_orquestadora=True,
                respondedor=responder,
                pausa=False,
                decision="continue",
                motivo=responder,
                has_transcript_path=True,
                nota=origin_note,
            )
            return {"block_reason": None}
        if _consult_pause_valid(flight_dir, roster):
            _consult_record(
                flight_dir,
                payload,
                mode,
                es_orquestadora=True,
                respondedor=None,
                pausa=True,
                decision="continue",
                motivo="pausa",
                has_transcript_path=True,
                nota=origin_note,
            )
            return {"block_reason": None}
        if _consult_recent(
            flight_dir,
            payload.get("session_id"),
            responder="consulta_supervisora",
            window=CONSULT_LIVE_WINDOW_S,
        ):
            _consult_record(
                flight_dir,
                payload,
                mode,
                es_orquestadora=True,
                respondedor=None,
                pausa=False,
                decision="continue",
                motivo="espera_temporizador",
                has_transcript_path=True,
                nota=origin_note,
            )
            return {"block_reason": None}
        if (
            _consult_count(
                flight_dir,
                payload.get("session_id"),
                decision="block",
                window=CONSULT_BLOCK_WINDOW_S,
            )
            >= 5
        ):
            _consult_record(
                flight_dir,
                payload,
                mode,
                es_orquestadora=True,
                respondedor=None,
                pausa=False,
                decision="tope",
                motivo="tope",
                has_transcript_path=True,
                nota=origin_note,
            )
            return {"block_reason": None}
        canary_matches = (
            mode == "canary"
            and isinstance(mode_data.get("canary_token"), str)
            and mode_data["canary_token"] in (_consult_text(opening) or "")
        )
        if mode == "observe" or (mode == "canary" and not canary_matches):
            _consult_record(
                flight_dir,
                payload,
                mode,
                es_orquestadora=True,
                respondedor=None,
                pausa=False,
                decision="observe_habria_bloqueado",
                motivo="observe_habria_bloqueado",
                has_transcript_path=True,
                nota=origin_note,
            )
            return {"block_reason": None}
        _consult_record(
            flight_dir,
            payload,
            mode,
            es_orquestadora=True,
            respondedor=None,
            pausa=False,
            decision="block",
            motivo="candidato",
            has_transcript_path=True,
            nota=origin_note,
        )
        return {"block_reason": _CONSULT_REASON}
    except Exception:
        if flight_dir is not None and active_mode:
            _consult_record(
                flight_dir,
                payload,
                mode,
                es_orquestadora=None,
                respondedor=None,
                pausa=False,
                decision="no_medido",
                motivo="excepcion",
                has_transcript_path=False,
            )
        return {"block_reason": None}


def _consult_malformed_input(start: Path) -> None:
    """Before: stdin did not produce a payload; During: best-effort flight lookup; After: records no_medido only for one active flight."""
    try:
        flights = _consult_flights(start.resolve())
        if len(flights) != 1:
            return
        flight = flights[0]
        mode, _data = _consult_read_mode(flight)
        if mode != "off":
            _consult_record(
                flight,
                {},
                mode,
                es_orquestadora=None,
                respondedor=None,
                pausa=False,
                decision="no_medido",
                motivo="sin_transcript",
                has_transcript_path=False,
            )
    except Exception:
        return


def _p9_flight_dir(root: Path) -> Path | None:
    """Before: raiz activa; During: censa vuelos vinculados; After: vuelo unico o None."""
    candidates: dict[Path, Path] = {}
    try:
        for base in _p9_linked_roots(root):
            flight_root = base / ".agent" / "runtime" / "flight"
            for roster in flight_root.glob("*/flight_roster.json"):
                if not roster.is_file():
                    continue
                resolved = roster.resolve()
                candidates[resolved] = resolved.parent
    except (OSError, RuntimeError, ValueError):
        pass
    if len(candidates) != 1:
        return None
    return next(iter(candidates.values()))


def needs_classification(payload: dict) -> bool:
    """Decide si el cierre debe bloquearse por falta de marcador.

    Devuelve True SOLO ante ausencia inequivoca de marcador en un mensaje final
    valido y con el guard de reentrada en estado conocido-inactivo. Cualquier
    ambiguedad devuelve False (fail-open).
    """
    # Guard de reentrada. `stop_hook_active` NO esta documentado, asi que su
    # AUSENCIA se trata como fail-open en vez de asumir "no activo": si el campo
    # desapareciera, asumir lo contrario abriria un bucle de re-entrega.
    if not _espera_guard_allows(payload):
        return False

    message = payload.get("last_assistant_message")
    if not isinstance(message, str) or not message.strip():
        return False

    return not classifies(message)


def _observe_only() -> bool:
    """True si el entorno pide modo observacion (mide, no bloquea).

    Acepta `AGENT_VERIFICATION_MODE=observe` (preferido: dice QUE hace) y
    `AGENT_DISABLE_VERIFICATION_STOP_HOOK=1` (escotilla de emergencia).

    Motivo (revision adversarial Codex): un vuelo autonomo corre SIN humano
    delante. Estrenar ahi una barrera bloqueante mezcla la entrega de los
    tickets con el experimento de un mecanismo nunca ejercitado en vuelo, y
    `stop_hook_active` -- el guard de reentrada que acotaria un bucle -- NO esta
    documentado, luego no puede sostener el argumento de autonomia.
    """
    if os.environ.get("AGENT_VERIFICATION_MODE", "").strip().lower() == "observe":
        return True
    return os.environ.get("AGENT_DISABLE_VERIFICATION_STOP_HOOK", "").strip() == "1"


def _record_observation(root: Path, payload: dict) -> None:
    """Registra un bloqueo EVITADO para poder medir la tasa real.

    Escribe JSONL en `.agent/runtime/verification_observations.json`. Guarda
    metadatos y la LONGITUD del mensaje, nunca su texto: el hook no debe volcar
    contenido de sesion a disco.

    Fail-open total: si no se puede escribir, no pasa nada. La observacion es
    telemetria, no un gate.
    """
    try:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": payload.get("session_id"),
            "cwd": payload.get("cwd"),
            "message_len": len(payload.get("last_assistant_message") or ""),
            "would_have_blocked": True,
        }
        target = root / ".agent" / "runtime" / "verification_observations.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except (OSError, TypeError, ValueError):
        return


def _sentinel_inactive_exit(baseline: dict) -> bool:
    """True si el centinela debe tratarse como INACTIVO (WOT-2026-044x).

    Side-effect deliberado: diagnostico visible en stderr con la etiqueta
    literal (EXPIRADO / SIN-FECHA-LEGIBLE) para que el operador vea POR QUE el
    hook no exige recibo.
    """
    expiry = sentinel_expiry(baseline)
    if expiry:
        sys.stderr.write(
            f"native_stop_hook: centinela {expiry}; tratado como INACTIVO.\n"
        )
        return True
    return False


def emit(result: dict) -> None:
    """Escribe el veredicto en stdout como JSON y termina con exit 0."""
    print(json.dumps(result))
    sys.exit(0)


def _decide(payload: dict) -> dict:
    """Veredicto del hook (WOT-2026-044x lo extrae de main para C901).

    Fail-open ante cualquier anomalia del dominio: toda ambiguedad devuelve
    `{"continue": True}`. Los side-effects (stderr de INACTIVO/OBSERVE,
    observaciones) ocurren aqui; el emision unico lo hace main().

    WOT-2026-160p ronda 2 de lentes (hallazgo codex, MAJOR, decision de
    diseno CONFIRMADA): 044t y la rama de espera son dos barreras con MODOS
    INDEPENDIENTES (DoD-a). Por eso la rama de espera se evalua SIEMPRE --
    incluso cuando 044t ya decidio bloquear -- en vez de devolver en cuanto
    044t bloquea: si no fuera asi, un cierre con 044t en `block` suprimiria
    en silencio el registro `observe` de la rama de espera (044t ganaria el
    veredicto Y le robaria la telemetria a la otra rama, que es justo lo que
    "independiente" prohibe). El VEREDICTO final sigue dando precedencia a
    044t sobre espera cuando ambas bloquean (mismo contrato que ya probaba
    `test_044t_gana_si_ambas_bloquean`); lo que cambia es que la rama de
    espera SIEMPRE corre sus side-effects antes de decidir el ganador.
    """
    cwd = payload.get("cwd")
    start = Path(cwd) if isinstance(cwd, str) and cwd else Path.cwd()
    root = find_repo_root(start.resolve())

    evidencia_bloquea = False
    baseline = read_sentinel(root)
    # WOT-2026-044x: centinela caducado o sin fecha legible -> INACTIVO con
    # diagnostico visible; la segunda rama sigue siendo independiente.
    if (
        baseline is not None
        and not _sentinel_inactive_exit(baseline)
        and repo_mutated(root, baseline)
        and needs_classification(payload)
    ):
        # Escape por entorno (WOT-2026-044t): observe mide pero no bloquea.
        if _observe_only():
            _record_observation(root, payload)
            sys.stderr.write(
                "native_stop_hook: OBSERVE -- habria bloqueado; no bloquea.\n"
            )
        else:
            evidencia_bloquea = True

    # WOT-2026-160p ronda 2 de lentes (hallazgo codex, MAJOR): si algo dentro
    # de la rama de espera lanza (p.ej. UnicodeDecodeError de un centinela con
    # bytes invalidos), la excepcion NO debe propagar hasta el catch-all de
    # `main()`, porque eso perderia `evidencia_bloquea` ya calculado y
    # devolveria un `continue` plano en vez del bloqueo real de 044t. La rama
    # de espera es fail-open TAMBIEN ante sus propios fallos internos.
    try:
        espera_resultado = _decide_espera(root, payload)
    except Exception:
        espera_resultado = {"continue": True}

    try:
        consult_result = _consult_branch(root, payload)
    except Exception:
        consult_result = {"block_reason": None}

    consult_reason = consult_result.get("block_reason")
    reasons: list[str] = []
    if evidencia_bloquea:
        reasons.append(_REASON[:REASON_MAX_LEN])
    if (
        espera_resultado.get("decision") == "block"
        and isinstance(consult_reason, str)
        and consult_reason
    ):
        espera_reason = espera_resultado.get("reason")
        if isinstance(espera_reason, str):
            reasons.append(espera_reason)
    if isinstance(consult_reason, str) and consult_reason:
        reasons.append(consult_reason)
    if reasons:
        return {"decision": "block", "reason": "\n".join(reasons)}
    return espera_resultado


def main() -> None:
    """Punto de entrada. Fail-open ante cualquier anomalia."""
    try:
        raw = sys.stdin.read()
    except Exception:  # pragma: no cover - stdin ilegible
        _consult_malformed_input(Path.cwd())
        emit({"continue": True})
        return

    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("payload no es un objeto JSON")
    except Exception as exc:
        # Diagnostico SIN reflejar el payload: solo el tipo de fallo.
        sys.stderr.write(
            f"native_stop_hook: payload ilegible ({type(exc).__name__}); fail-open.\n"
        )
        _consult_malformed_input(Path.cwd())
        emit({"continue": True})
        return

    try:
        emit(_decide(payload))
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover - defensa en profundidad
        sys.stderr.write(
            f"native_stop_hook: fallo interno ({type(exc).__name__}); fail-open.\n"
        )
        emit({"continue": True})


if __name__ == "__main__":
    main()
