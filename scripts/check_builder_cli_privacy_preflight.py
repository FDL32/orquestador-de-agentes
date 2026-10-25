#!/usr/bin/env python
"""Guard: privacidad del contenido del prompt antes de cualquier CLI directo de Builder.

Que protege
-----------
Cualquier CLI directo que invoque un agente como Builder real o Revisor (Kilo via
`kilo run`, Codex via `codex exec`, u otros) NO autocarga `AGENTS.md` ni ningun
puntero de capa 2. Ademas, ningun CLI directo aplica la barrera de privacidad que
`ensemble_dispatch.py` corre para cada envio (`privacy_preflight`, WOT-2026-046c).
Un prompt pasado como fichero que contenga datos sensibles (credenciales, tokens
opacos de alta entropia, rutas a raices privadas) se enviaria al backend sin
deteccion alguna, con riesgo de fuga de contenido privado.

Este guard lee el fichero de prompt ANTES de lanzar el CLI directo y bloquea
(`exit 1`) si detecta contenido sensible y la exencion no esta declarada POR RUTA/
invocacion (via `--trusted-reason`). Reutiliza la MISMA `privacy_preflight` ya auditada
de `ensemble_dispatch.py`, no inventa deteccion de contenido sensible nueva.

Por que un guard y no solo la prosa del contrato
-------------------------------------------------
Un guard que nadie invoca es una NORMA, no una barrera (`AGENTS.md`, "Barrera
cableada"). La invocacion de este guard es POR CONVENCION: se espera que quien
despache un Builder real via cualquier CLI directo (Kilo `kilo run`, Codex
`codex exec`, u otro) lo corra antes de lanzar el prompt
(`prompts/builder_invocation_contract.md`). El despacho de un Builder real
es una invocacion manual de shell, no una llamada a traves de un script de
este motor que un hook pueda interceptar -- mismo motivo estructural que el
guard hermano `check_builder_dispatch_prompt.py`.

ALCANCE DECLARADO (lo que este guard NO hace)
----------------------------------------------
Es una barrera de FORMA sobre el FICHERO de prompt: verifica que el contenido
del fichero no dispare `privacy_preflight`, no sobre todo lo que el Builder
vea en el repo durante su sesion real. No esta cableada automaticamente:
quien despache debe invocar este guard antes de lanzar cualquier CLI directo
(`prompts/builder_invocation_contract.md`).

Before / During / After
-----------------------
Before: recibe la ruta de un fichero de prompt legible en UTF-8 y los
    argumentos de sensibilidad/exencion.
During: importa LAZY `privacy_preflight` / `load_motor_config` desde
    `ensemble_dispatch`; si el import falla, BLOQUEA (exit 2, fail-closed).
    Lee el fichero como payload_text, construye `backend_cfg` con
    `trusted: True` si `--trusted-reason` tiene motivo no vacio, obtiene
    `private_roots` de la config del motor (degrada a lista vacia si
    la config no carga).
After: exit 0 si `allowed`, imprimiendo el motivo; exit 1 si `bloqueado`,
    imprimiendo el motivo y la correccion; exit 2 si el import falla
    o el fichero no existe.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Preflight de privacidad sobre el contenido de un fichero de "
            "prompt antes de cualquier CLI directo de Builder/Revisor "
            "(kilo run, codex exec, etc.). Reutiliza "
            "`privacy_preflight` de `ensemble_dispatch.py`."
        )
    )
    ap.add_argument(
        "prompt",
        help=(
            "ruta del fichero de prompt de arranque (el -f que se pasara "
            "al CLI directo, sea `kilo run` o `codex exec`)"
        ),
    )
    ap.add_argument(
        "--data-sensitivity",
        choices=["public", "private"],
        default=None,
        help=(
            "Sensibilidad del dato que se envia: 'public' o 'private'. "
            "AUSENTE se trata como 'private' (fail-closed). Default: None."
        ),
    )
    ap.add_argument(
        "--trusted-reason",
        default="",
        help=(
            "Exencion declarada POR RUTA/invocacion: si se provee un motivo "
            "no vacio, se trata como backend_cfg={'trusted': True}. El motivo "
            "se imprime siempre (nunca exencion silenciosa)."
        ),
    )
    args = ap.parse_args()

    path = Path(args.prompt)
    if not path.is_file():
        print(
            f"[cli-privacy-preflight] ERROR: prompt no encontrado: {path}",
            file=sys.stderr,
        )
        return 2

    text = path.read_text(encoding="utf-8", errors="replace")

    # Lazy import: mismo patron de run_codex_audit.py:391. Si el import falla,
    # BLOQUEA (fail-closed), nunca fail-open por ausencia del modulo.
    try:
        from ensemble_dispatch import (
            load_motor_config,
            privacy_preflight,
        )
    except Exception as exc:  # ImportError y cualquier fallo de su cadena
        print(
            f"[cli-privacy-preflight] ERROR: privacy_preflight no cargable: {exc}; "
            f"envio BLOQUEADO (fail-closed, WOT-2026-046k)",
            file=sys.stderr,
        )
        return 2

    sensitivity: str = args.data_sensitivity or "private"

    if args.trusted_reason.strip():
        backend_cfg: dict = {"trusted": True}
        print(
            f"[cli-privacy-preflight] exencion declarada (trusted:true): "
            f"{args.trusted_reason.strip()}"
        )
    else:
        backend_cfg = {}

    try:
        motor_cfg = load_motor_config()
        private_roots: list[str] = list(
            motor_cfg.get("ensemble_private_roots", []) or []
        )
    except Exception:
        # Degrada a lista vacia SOLO si la config no carga; nunca trustea
        # a un except: pass que oculte el fallo.
        private_roots = []

    allowed, reason = privacy_preflight(text, sensitivity, backend_cfg, private_roots)

    if allowed:
        print(f"[cli-privacy-preflight] OK: {reason}")
        return 0

    print(
        f"[cli-privacy-preflight] BLOQUEA: {reason}. "
        f"declara --trusted-reason si el envio esta exento, o reduce el "
        f"contenido sensible del prompt.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
