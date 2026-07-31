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
4. Si el mensaje final NO contiene `[EVIDENCIA]` ni `[HIPOTESIS]` -> `decision: block`.

El criterio es un SUBSTRING CHECK sobre marcadores declarados. No interpreta prosa,
no busca lenguaje causal, no aplica regex sobre contenido: detecta la AUSENCIA de una
marca deliberada. Esto respeta el NON-GOAL literal de WOT-2026-044r ("no analisis
semantico de prosa") y el muro de WOT-2026-025c (8 versiones fallidas de ese enfoque).

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

import json
import sys
from pathlib import Path


#: Marcadores de clasificacion. Su AUSENCIA es lo que se detecta.
MARKERS: tuple[str, ...] = ("[EVIDENCIA]", "[HIPOTESIS]")

#: Centinela opt-in. Sin este fichero el hook es un no-op absoluto.
SENTINEL_RELPATH = Path(".agent") / "runtime" / "verification_mode"

#: Tope defensivo del texto devuelto al agente.
REASON_MAX_LEN = 400

_REASON = (
    "Cierre sin clasificar. Antes de entregar, marca el mensaje final:\n"
    "  [EVIDENCIA] <comando/test/archivo/exit code que lo respalda>\n"
    "  [HIPOTESIS] <que NO comprobaste>\n"
    "Toda afirmacion causal, historica o de estado va precedida de un probe "
    "ejecutado, o marcada como hipotesis. No repitas el mismo cierre sin clasificar."
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


def sentinel_active(root: Path) -> bool:
    """True solo si el centinela existe y es un fichero REGULAR.

    Un centinela que sea directorio o enlace roto se trata como inactivo
    (fail-open), no como activo: ante ambiguedad, el hook no bloquea.
    """
    try:
        return (root / SENTINEL_RELPATH).is_file()
    except OSError:
        return False


def needs_classification(payload: dict) -> bool:
    """Decide si el cierre debe bloquearse por falta de marcador.

    Devuelve True SOLO ante ausencia inequivoca de marcador en un mensaje final
    valido y con el guard de reentrada en estado conocido-inactivo. Cualquier
    ambiguedad devuelve False (fail-open).
    """
    # Guard de reentrada. `stop_hook_active` NO esta documentado, asi que su
    # AUSENCIA se trata como fail-open en vez de asumir "no activo": si el campo
    # desapareciera, asumir lo contrario abriria un bucle de re-entrega.
    if "stop_hook_active" not in payload:
        return False
    if payload.get("stop_hook_active"):
        return False

    message = payload.get("last_assistant_message")
    if not isinstance(message, str) or not message.strip():
        return False

    return not any(marker in message for marker in MARKERS)


def emit(result: dict) -> None:
    """Escribe el veredicto en stdout como JSON y termina con exit 0."""
    print(json.dumps(result))
    sys.exit(0)


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
        cwd = payload.get("cwd")
        start = Path(cwd) if isinstance(cwd, str) and cwd else Path.cwd()
        root = find_repo_root(start.resolve())

        if not sentinel_active(root):
            emit({"continue": True})
            return

        if needs_classification(payload):
            emit({"decision": "block", "reason": _REASON[:REASON_MAX_LEN]})
            return
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover - defensa en profundidad
        sys.stderr.write(
            f"native_stop_hook: fallo interno ({type(exc).__name__}); fail-open.\n"
        )
        emit({"continue": True})
        return

    emit({"continue": True})


if __name__ == "__main__":
    main()
