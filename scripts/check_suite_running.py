"""Aviso pre-commit: hay una suite canonica ACTIVAMENTE corriendo ahora mismo.

HALLAZGO QUE LO ORIGINA (medido en el canal manual entre sesiones de esta
misma linea de trabajo, turnos T3-T9, 2026-10-09): dos sesiones Claude Code
sobre el mismo `repo_motor` compartido -- un worktree del `repo_destino`
aisla el destino, pero el motor sigue siendo UN SOLO arbol fisico --
invalidaron 2 corridas completas de `run_pytest_safe.py --level all` (7 a
50 min cada una, `WOT-2026-062e`) porque un commit/escritura ajena toco el
arbol DURANTE la ventana de medicion. Solo la 3a corrida, con el arbol
"quieto" por coordinacion manual activa, dio una medicion valida.

POR QUE NO HACIA FALTA CONSTRUIR UN LOCK NUEVO: `scripts/run_pytest_safe.py`
ya tiene uno completo y en produccion (`acquire_lock`/`get_lock_status`,
PID-based, resuelto contra el arbol real via `runtime.project_root`). El
gap real, confirmado por ausencia (grep en `.pre-commit-config.yaml` y
todos los `scripts/check_*.py`): NINGUN hook de pre-commit lo consultaba.
El lock existente evita 2 `pytest` simultaneos; este guard cierra el otro
lado -- avisa si vas a commitear mientras una suite de OTRO proceso sigue
corriendo.

POR QUE AVISA Y NO BLOQUEA (mismo criterio que check_suite_freshness.py,
WOT-2026-026t): un commit mientras la suite corre puede ser legitimo --
otra sesion puede estar trabajando una superficie totalmente disjunta.
Bloquear obligaria a serializar TODO el trabajo del motor mientras CUALQUIER
suite corre en cualquier sesion, el acoplamiento fragil que la propia ronda
de gobierno de esta propuesta descarto explicitamente (Via C, "solo
protocolo", declarada insuficiente mas NO reemplazada por un bloqueo duro).
Exit 0 SIEMPRE.

CONTRATO READ-ONLY, deliberado (correccion de la ronda de gobierno, lente
codex, 2026-10-09): este guard usa SOLO `get_lock_status()`, nunca
`acquire_lock()`. Un hook de verificacion que solo debe LEER no puede tener
el efecto secundario de CREAR el lock -- eso falsearia el propio hecho que
se esta verificando (un commit que dispara este hook podria terminar
creando un lock "activo" que nadie esta usando de verdad).

FAIL-OPEN EXPLICITO (misma ronda): `get_lock_status()` puede fallar ante
JSON corrupto, PID no numerico, o el fichero desaparecido entre el chequeo
de existencia y la lectura -- todos esos casos deben resolver en silencio,
exit 0, nunca convertir un fallo de telemetria en un bloqueo accidental ni
en un traceback que interrumpa el commit.

Before: se ejecuta desde el repo del motor (cwd = raiz), en el hook
    `pre-commit`. `scripts.run_pytest_safe` debe ser importable (mismo
    arbol).
During: lee `.agent/runtime/pytest-safe/pytest.lock` directamente y
    reutiliza `run_pytest_safe.is_pid_running()` para la verificacion de
    liveness (funcion pura, sin efectos secundarios). Sin I/O de red. No
    escribe nada, no crea el lock si no existe.
After: imprime el aviso si hay un lock activo (PID dueno vivo); exit 0
    SIEMPRE, incluso ante fichero ausente, JSON corrupto, PID invalido o
    el modulo `run_pytest_safe` no importable.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOCK_FILE = PROJECT_ROOT / ".agent" / "runtime" / "pytest-safe" / "pytest.lock"


def _get_lock_status() -> dict | None:
    """Replica run_pytest_safe.get_lock_status() sobre nuestro propio LOCK_FILE.

    No importa ``run_pytest_safe`` ni muta sus atributos de modulo: ese
    modulo resuelve su `LOCK_FILE` via `runtime.project_root` (topologia
    motor/destino), y reasignar una variable global de un modulo ajeno
    desde un hook de solo-lectura es un acoplamiento innecesario (el
    proceso del hook es de vida corta, pero no hay necesidad real de
    tocar estado ajeno cuando la logica -- leer PID, comprobar liveness --
    es trivial de reproducir localmente). Reutiliza SOLO `is_pid_running`,
    que es una funcion pura sin efectos secundarios. Fail-open: cualquier
    error de import, lectura o parseo devuelve None.
    """
    if not LOCK_FILE.exists():
        return {"present": False}

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from scripts.run_pytest_safe import is_pid_running
    except Exception:
        return None

    try:
        lock_data = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None

    try:
        lock_pid = int(lock_data.get("pid", 0) or 0)
    except (TypeError, ValueError):
        return None

    try:
        active = is_pid_running(lock_pid)
    except Exception:
        return None

    return {"present": True, "pid": lock_pid, "active": active, "data": lock_data}


def main() -> int:
    """Exit 0 SIEMPRE. Solo imprime cuando el aviso es accionable."""
    status = _get_lock_status()
    if not status or not status.get("present") or not status.get("active"):
        return 0

    data = status.get("data") or {}
    pid = status.get("pid")
    started_at = data.get("started_at")
    duration_note = f" desde {started_at}" if isinstance(started_at, str) else ""

    print(
        f"[suite-running] AVISO: hay una suite canonica ACTIVA ahora mismo "
        f"(pid={pid}{duration_note}). Tu commit puede invalidar esa medicion "
        "si toca ficheros que esa corrida esta leyendo."
    )
    print(
        "  Si es otra sesion: avisa en el canal manual antes de continuar, o"
        " espera a que termine. No bloquea: commitear ahora es legitimo si tu"
        " cambio es disjunto de lo que la suite activa esta midiendo."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
