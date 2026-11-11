#!/usr/bin/env python3
"""Arma el centinela manual de checklist de espera (WOT-2026-160p).

Before: el operador decide explicitamente si quiere medir o exigir el marcador
de decision de espera; este centinela es independiente de verification_mode.py
porque el DoD de 160p exige una segunda rama independiente de WOT-2026-044t.
During: `on` escribe solo el modo y una fecha UTC, `off` borra el centinela y
`status` informa incluso ante JSON ilegible, siempre en modo fail-open.
After: el estado queda en el centinela de espera bajo `.agent/runtime/`; este
script no se cablea en bootstrap ni en cierre de sesion porque su armado es
manual durante el periodo de observacion. El arranque avisa ante centinela
EXPIRADO o ILEGIBLE con `CENTINELA-ESPERA-EXPIRADO` o
`CENTINELA-ESPERA-ILEGIBLE`, en fail-open y solo lectura. No avisa ante fichero
ausente, vacio/{} ni `{"mode":"off"}`. `{mode:off}` solo existe escrito a mano:
`turn_on` solo admite `observe|block` y `turn_off` borra el fichero.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_hook_module():
    """Carga `native_stop_hook` desde `.agent/hooks`, igual que verification_mode.py.

    Before: nada; During: inserta el directorio de hooks en sys.path e importa
    el modulo del gancho (solo define constantes y funciones, sin side-effects
    al importar); After: devuelve el modulo.

    WOT-2026-160z: la ruta del centinela tiene UNA sola definicion, en el hook
    (`ESPERA_SENTINEL_RELPATH`); este script la IMPORTA en vez de repetir el
    literal, para que el armador y el lector no puedan divergir. La direccion
    elegida (script -> hook) es la que ya usa `verification_mode.py`: el gancho
    NO debe importar nada nuevo, porque corre en cada parada de cada sesion y
    su lanzador es fail-closed si el fichero no existe.
    """
    hooks_dir = REPO_ROOT / ".agent" / "hooks"
    sys.path.insert(0, str(hooks_dir))
    try:
        import native_stop_hook
    finally:
        with contextlib.suppress(ValueError):
            sys.path.remove(str(hooks_dir))
    return native_stop_hook


_hook = _load_hook_module()
SENTINEL_RELPATH = _hook.ESPERA_SENTINEL_RELPATH
_sentinel_expiry = _hook.sentinel_expiry


def turn_on(root: Path, mode: str) -> int:
    """Escribe el modo solicitado y la fecha UTC de activacion."""
    target = root / SENTINEL_RELPATH
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {
                    "mode": mode,
                    "activated_at": datetime.now(timezone.utc).isoformat(),
                }
            ),
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"espera_checklist_mode: no se pudo encender: {exc}", file=sys.stderr)
        return 1
    print(f"espera_checklist_mode ON (mode={mode}, {target})")
    return 0


def turn_off(root: Path) -> int:
    """Borra el centinela; la operacion es idempotente."""
    target = root / SENTINEL_RELPATH
    try:
        target.unlink()
    except FileNotFoundError:
        print("espera_checklist_mode ya estaba OFF")
        return 0
    except OSError as exc:
        print(f"espera_checklist_mode: no se pudo borrar: {exc}", file=sys.stderr)
        return 1
    print(f"espera_checklist_mode OFF ({target})")
    return 0


def show_status(root: Path) -> int:
    """Informa de OFF, ON legible u ON pero ILEGIBLE sin bloquear."""
    target = root / SENTINEL_RELPATH
    if not target.is_file():
        print("espera_checklist_mode: OFF")
        return 0
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print("espera_checklist_mode: ON pero ILEGIBLE")
        return 0
    if not isinstance(data, dict):
        print("espera_checklist_mode: ON pero ILEGIBLE")
        return 0
    if data.get("mode") == "off":
        print("espera_checklist_mode: OFF (mode=off)")
        return 0
    expiry = _sentinel_expiry(data)
    if expiry:
        # WOT-2026-160z: mismo veredicto que el gancho (un centinela caducado,
        # vacio o sin fecha legible es INACTIVO). El operador debe verlo igual.
        print(f"espera_checklist_mode: ON pero INACTIVO ({expiry})")
        return 0
    print(
        f"espera_checklist_mode: ON (mode={data.get('mode', '?')}, "
        f"activated_at={data.get('activated_at', '?')})"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    """Parsea la accion manual y devuelve su codigo de salida."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=["on", "off", "status"])
    parser.add_argument("--mode", choices=["observe", "block"], default="observe")
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(argv)
    root = (args.root or REPO_ROOT).resolve()
    if args.action == "on":
        return turn_on(root, args.mode)
    if args.action == "off":
        return turn_off(root)
    return show_status(root)


if __name__ == "__main__":
    sys.exit(main())
