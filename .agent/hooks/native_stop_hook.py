#!/usr/bin/env python3
"""Native stop hook: barrera de clasificacion de evidencia (WOT-2026-044t).

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
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


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
    """
    return any(MARKER_RE.match(line) for line in _lines_outside_fences(message))


def _lines_outside_fences(message: str, fence_markers: tuple[str, ...] = ("```",)):
    """Before: texto crudo y los delimitadores de fence reconocidos; During:
    abre con el primer delimitador que matchee y SOLO cierra con ESE MISMO
    delimitador (nunca cruza tipos); After: produce las lineas utiles.

    Por defecto solo ``` (contrato de WOT-2026-044t, SIN CAMBIOS: con un unico
    delimitador, abrir-con-cualquiera-cierra-con-el-mismo es identico al
    toggle simple de antes). `espera_classifies` pasa ademas ``~~~`` (hallazgo
    codex ronda 2 de lentes, MAJOR: un marcador dentro de un bloque ``~~~``
    se auto-aprobaba porque solo se reconocia ```).
    """
    in_fence = False
    opener = None
    for line in message.replace("\r\n", "\n").split("\n"):
        stripped = line.lstrip()
        if in_fence:
            if stripped.startswith(opener):
                in_fence = False
                opener = None
            continue
        matched = next((m for m in fence_markers if stripped.startswith(m)), None)
        if matched:
            in_fence = True
            opener = matched
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
    (el modo esta "activo" pero sin dato utilizable); el dict parseado en
    cualquier otro caso."""
    target = root / ESPERA_SENTINEL_RELPATH
    try:
        if not target.is_file():
            return None
        raw = target.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _record_espera_observation(
    root: Path, payload: dict, trigger_a: bool, ya_clasificado: bool, message: str
) -> None:
    """Before: datos no sensibles; During: anade JSONL; After: falla abierto si no escribe."""
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
    except (OSError, TypeError, ValueError):
        return


def _decide_espera(root: Path, payload: dict) -> dict:
    """Before: payload y centinela nuevo; During: observa o bloquea; After: devuelve veredicto."""
    sentinel = read_espera_sentinel(root)
    if sentinel is None or sentinel.get("mode") not in ("observe", "block"):
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

    espera_resultado = _decide_espera(root, payload)

    if evidencia_bloquea:
        return {"decision": "block", "reason": _REASON[:REASON_MAX_LEN]}
    return espera_resultado


def main() -> None:
    """Punto de entrada. Fail-open ante cualquier anomalia."""
    try:
        raw = sys.stdin.read()
    except Exception:  # pragma: no cover - stdin ilegible
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
