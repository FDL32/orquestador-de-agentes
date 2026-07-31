#!/usr/bin/env python3
"""Enciende/apaga el modo verificacion del Stop hook (WOT-2026-044t).

Por que existe
--------------
`.agent/hooks/native_stop_hook.py` exige que el mensaje final lleve `[EVIDENCIA]`
o `[HIPOTESIS]` cuando el turno MUTO el repo. Esa puerta necesita un baseline
git contra el que comparar, y necesita que alguien la encienda.

Dejar el encendido en manos del operador convierte la barrera en "una norma":
depende de que alguien se acuerde. Este script existe para que el ENCENDIDO lo
haga el flujo (bootstrap de un vuelo o de una sesion de desarrollo) y el APAGADO
lo haga el cierre, sin intervencion manual.

MEDICION QUE JUSTIFICA LA PUERTA DE MUTACION (2026-07-31, no heredada):
sobre 33.476 mensajes finales reales extraidos de 1654 transcripts de esta
maquina, el criterio "falta el marcador" bloqueaba 33.473 (100,0%). Activarlo
sin la puerta de mutacion seria un denial-of-service sobre el agente, no una
barrera. Con la puerta, solo se exige recibo a los cierres que tocaron el arbol.

Before (pre-condiciones)
------------------------
- `--root` apunta a un arbol con `.git` (o se resuelve desde el cwd).
- Para `on`: git debe ser ejecutable; sin el no hay baseline y se aborta.

During (proceso y recursos)
---------------------------
- `on`: mide `git rev-parse HEAD` y `git status --porcelain`, y escribe el
  centinela con ambos valores. Idempotente: re-encender re-mide el baseline.
- `off`: borra el centinela. Idempotente: si no existe, no falla.
- `status`: informa sin mutar nada.

After (post-condiciones y errores)
----------------------------------
- `on` -> existe `.agent/runtime/verification_mode` con JSON valido; rc 0.
- `off` -> el centinela no existe; rc 0.
- Si git falla en `on`, NO escribe centinela y devuelve rc 1: un centinela sin
  baseline dejaria el hook activo pero incapaz de probar mutacion.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SENTINEL_RELPATH = Path(".agent") / "runtime" / "verification_mode"
GIT_TIMEOUT_S = 10


def _git(root: Path, *args: str) -> str | None:
    """Ejecuta git y devuelve stdout, o None si no se pudo medir."""
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


def status_hash(status_text: str) -> str:
    """Hash de `git status --porcelain`, delegado al hook.

    Se IMPORTA en vez de reimplementarse: si las dos normalizaciones divergieran,
    el baseline nunca casaria y la barrera bloquearia siempre o nunca.
    """
    sys.path.insert(0, str(REPO_ROOT / ".agent" / "hooks"))
    from native_stop_hook import status_hash as _hash

    return _hash(status_text)


def ensure_on(root: Path, quiet: bool = False) -> int:
    """Enciende SOLO si no estaba ya encendido. Idempotente y sin rebaseline.

    Diferencia critica con `turn_on`: si el centinela ya existe, NO re-mide el
    baseline. Un `init` de resume o un reintento re-mediria contra el estado
    ACTUAL -- que ya incluye el trabajo hecho -- y borraria la prueba de mutacion,
    dejando la barrera muda justo en la sesion que mas la necesita.

    `quiet=True` suprime stdout: quien invoca desde otro script (p.ej.
    `init_session_scratch.py init`) emite JSON estructurado que otros parsean,
    y un mensaje humano por delante lo corrompe. Medido: sin quiet, `init`
    imprimia "verification_mode ON ..." ANTES de su JSON.

    Exigido por revision adversarial Codex ("E1 ensure-on, no `on` ciego").
    """
    target = root / SENTINEL_RELPATH
    try:
        if target.is_file():
            if not quiet:
                print(f"verification_mode ya ON (baseline conservado): {target}")
            return 0
    except OSError:
        pass
    return turn_on(root, quiet=quiet)


def turn_on(root: Path, quiet: bool = False) -> int:
    """Escribe el centinela con el baseline git actual (RE-MIDE siempre)."""
    head = _git(root, "rev-parse", "HEAD")
    status = _git(root, "status", "--porcelain")
    if head is None or status is None:
        sys.stderr.write(
            f"verification_mode: no se pudo medir el baseline git en {root}; "
            "no se enciende (un centinela sin baseline no puede probar mutacion).\n"
        )
        return 1

    payload = {
        "baseline_head": head.strip(),
        "baseline_status_hash": status_hash(status),
        "activated_at": datetime.now(timezone.utc).isoformat(),
    }
    target = root / SENTINEL_RELPATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if not quiet:
        print(f"verification_mode ON  ({target})")
        print(f"  baseline_head={payload['baseline_head'][:12]}")
    return 0


def turn_off(root: Path) -> int:
    """Borra el centinela. Idempotente."""
    target = root / SENTINEL_RELPATH
    try:
        target.unlink()
        print(f"verification_mode OFF ({target})")
    except FileNotFoundError:
        print("verification_mode ya estaba OFF")
    except OSError as exc:
        sys.stderr.write(f"verification_mode: no se pudo borrar {target}: {exc}\n")
        return 1
    return 0


def show_status(root: Path) -> int:
    """Informa del estado sin mutar nada."""
    target = root / SENTINEL_RELPATH
    if not target.is_file():
        print("verification_mode: OFF")
        return 0
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print("verification_mode: ON (centinela ilegible, sin baseline)")
        return 0
    print("verification_mode: ON")
    print(f"  baseline_head={str(data.get('baseline_head', '?'))[:12]}")
    print(f"  activated_at={data.get('activated_at', '?')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=["on", "ensure-on", "off", "status"])
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Raiz del repo. Por defecto, la raiz del motor.",
    )
    args = parser.parse_args(argv)
    root = (args.root or REPO_ROOT).resolve()

    if args.action == "on":
        return turn_on(root)
    if args.action == "ensure-on":
        return ensure_on(root)
    if args.action == "off":
        return turn_off(root)
    return show_status(root)


if __name__ == "__main__":
    sys.exit(main())
