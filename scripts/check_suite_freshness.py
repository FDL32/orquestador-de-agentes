"""Aviso pre-commit: este commit invalidara la suite canonica verde que ya existe.

EL DESPERDICIO QUE CIERRA (medido 2026-08-04): la secuencia
`suite -> commit -> suite -> commit -> suite` corrio la suite TRES veces en una
sesion. Cada commit posterior invalida la corrida anterior, porque el contrato
exige `tested_commit_sha == HEAD` (`pre_handoff_guard.py:561`). ~22 minutos, de
los cuales ~15 se tiraron.

POR QUE NO BASTABA LO QUE YA HABIA: la comprobacion `tested_commit_sha == HEAD`
EXISTE en dos sitios (`pre_handoff_guard`, `collect_system_health`), pero ambos
corren DESPUES -- en el handoff o en la auditoria de salud. Te avisan cuando ya
pagaste la corrida. Este guard corre ANTES, en `pre-commit`, que es el unico
momento en que la informacion todavia sirve para AHORRAR trabajo.

POR QUE AVISA Y NO BLOQUEA: un commit que invalida la suite es LEGITIMO -- es lo
normal a mitad de una sesion. Bloquearlo obligaria a correr la suite entre cada
par de commits, que es exactamente el desperdicio que se quiere evitar. El guard
informa para que el operador AGRUPE sus commits y corra la suite UNA vez al final.
Exit 0 SIEMPRE: no es una barrera de correccion, es telemetria accionable en el
momento util. La barrera de correccion (no publicar con suite stale) ya la tiene
`pre_handoff_guard`, y ahi si es bloqueante.

Before: se ejecuta desde el repo del motor (cwd = raiz), en el hook `pre-commit`.
During: lee `.agent/runtime/pytest-safe/last-run.json` y compara su
    `tested_commit_sha` con el HEAD actual. Sin I/O de red. No escribe nada.
After: imprime el aviso si procede; exit 0 SIEMPRE, incluso ante fichero
    ausente, JSON corrupto o git no disponible (un aviso roto no debe impedir
    commitear).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LAST_RUN = PROJECT_ROOT / ".agent" / "runtime" / "pytest-safe" / "last-run.json"


def _head() -> str | None:
    """HEAD actual del motor, o None si git no responde."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def _last_run() -> dict | None:
    """Contenido de last-run.json, o None si no se puede leer."""
    try:
        return json.loads(LAST_RUN.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def main() -> int:
    """Exit 0 SIEMPRE. Solo imprime cuando el aviso es accionable."""
    data = _last_run()
    if not data:
        return 0  # sin corrida previa: nada que invalidar

    # Solo avisa sobre una corrida COMPLETA y VERDE: una corrida filtrada o roja
    # no es un activo que perder. `level: all` + `args_mode: default_discovery`
    # es el mismo par que usa el disparador de suite del cierre (WOT-2026-044o).
    if data.get("status") != "finished" or data.get("exit_code") != 0:
        return 0
    if data.get("level") != "all" or data.get("args_mode") != "default_discovery":
        return 0

    tested = str(data.get("tested_commit_sha") or "")
    head = _head()
    if not tested or not head:
        return 0

    if tested != head:
        return 0  # ya estaba desfasada: el aviso llega tarde, no lo repitas
    passed = data.get("passed")
    print(
        f"[suite-freshness] AVISO: hay suite canonica VERDE en {tested[:8]}"
        f"{f' ({passed} passed)' if passed else ''}. Este commit la INVALIDA:"
        " el contrato exige tested_commit_sha == HEAD."
    )
    print(
        "  Si vas a hacer MAS commits, agrupalos y corre la suite UNA vez al"
        " final (~7 min por corrida; medido 2026-08-04: 3 corridas, ~15 min"
        " tirados). No bloquea: commitear ahora es legitimo."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
