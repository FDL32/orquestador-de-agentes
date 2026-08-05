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
import sys
from pathlib import Path


# El vector de escritura solo existe cuando el backend corre como AGENTE con
# acceso al arbol. `channel: api` es HTTP puro: sin system prompt de agente y
# sin permisos de FS. Vigilar esos seria over-gating (ver docstring).
VECTOR_CHANNELS = {"agent"}


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default=".agent/config/agents.json",
        help="ruta a agents.json (default: .agent/config/agents.json)",
    )
    args = parser.parse_args(argv)
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


if __name__ == "__main__":
    sys.exit(main())
