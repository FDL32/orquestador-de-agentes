#!/usr/bin/env python3
"""Gate: `role_models.BUILDER` != `role_models.REVISOR` (WOT-2026-098b).

POR QUE EXISTE
--------------
El sistema de 4 capas (orchestrator/manager/revisor/builder) exige que la Capa 2
(`revisor`) y la Capa 3 (`builder`) NO compartan el mismo `model_id`: el revisor
audita el diff que produce el builder, y si ambos son el MISMO modelo la revision
es una firma de complacencia, no una verificacion independiente. La regla dura
vive en la propuesta origen (`PROPUESTA_vocabulario_roles_capas_20261011.md` v6,
Seccion 8.3) como NORMA; este script es la BARRERA mecanica que la comprueba sin
depender de que un agente la recuerde.

QUE COMPARA (y que NO)
----------------------
Solo `model_id`s TIPADOS y comparables:
  - un valor `null` (o ausente) NO es un `model_id` -> nunca cuenta como colision
    (`null` significa "usa el default de `role_mapping.<rol>.backend`", no un
    modelo concreto que pueda coincidir con otro).
  - un NOMBRE DE BACKEND (una clave de `config["backends"]`, p.ej. `"opencode"`)
    TAMPOCO es un `model_id` -> no cuenta como colision (comparar dos cadenas
    que no son modelos es la auto-contradiccion que la propuesta v6 cerro).
Colision = ambos valores son cadenas no vacias, ninguno es un backend conocido,
y son IGUALES.

Antes: resuelve el `agents.json` del motor (o el `--project-root` dado) y lo
    valida con el MISMO parser que consume el runtime (`load_agents_config`, la
    unica capa de schema; este script no re-parsea JSON a mano).
During: lee `role_models.BUILDER` y `role_models.REVISOR`, aplica la tipificacion
    de arriba, imprime SIEMPRE los 2 valores comparados (diagnostico sin reabrir
    el JSON) y decide la colision. Solo lectura.
After: exit 0 si no hay colision (o si alguno de los dos no es comparable);
    exit 1 si ambos son `model_id`s reales e IGUALES; exit 2 si la config no se
    puede cargar (barrera fail-closed: un gate que no puede leer lo que guarda no
    debe salir verde por defecto).

NOTA DE CABLEADO (WOT-2026-098b): el sitio de invocacion NATURAL de este gate es
`bus/review_bridge.py` "antes de lanzar la Capa 2" -- FORBIDDEN SURFACE de este
ticket (ver Non-goals del work_plan). El MECANISMO se entrega aqui; su cableado
desde el review bridge es follow-up declarado y el guard queda declarado en
`scripts/guard_wiring_policy.yaml` mientras tanto (mismo patron que
`check_prompt_bias`/`check_bundle_receipts`).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


# Motor-explicit root (M9): el repo que POSEE este script, nunca el env -- la
# resolucion por AGENT_PROJECT_ROOT apuntaria al agents.json de un workspace.
# APPEND a `.agent/` (nunca insert(0)): con `.agent` al frente, `runtime`
# resolveria a `.agent/runtime/` en vez de `<motor>/runtime/` (hazard documentado
# en AGENTS.md).
MOTOR_ROOT = Path(__file__).resolve().parent.parent
_AGENT_DIR = MOTOR_ROOT / ".agent"
if str(_AGENT_DIR) not in sys.path:
    sys.path.append(str(_AGENT_DIR))

from agents_config import AgentsConfigError, load_agents_config  # noqa: E402


_BUILDER_ROLE = "BUILDER"
_REVISOR_ROLE = "REVISOR"


def _typed_model_id(value: object, backends: set[str]) -> str | None:
    """El `model_id` comparable de un valor de `role_models`, o ``None``.

    ``None`` cuando el valor no es un `model_id` tipado: ausente, `null`, cadena
    vacia, no-string, o un NOMBRE DE BACKEND. En los 4 casos el valor no puede
    formar una colision de modelos (regla de la Seccion 8.3 v6).
    """
    if not isinstance(value, str) or not value.strip():
        return None
    if value in backends:
        return None
    return value


def compare_role_models(config: dict) -> tuple[object, object, bool]:
    """(builder_raw, revisor_raw, collision) para el `config` ya validado.

    Before: `config` es el dict cargado por `load_agents_config` (o uno
        equivalente, para tests hermeticos).
    During: lee `role_models.BUILDER`/`role_models.REVISOR`, tipifica ambos con
        `_typed_model_id` y decide colision. Sin I/O.
    After: devuelve los 2 valores RAW (para imprimirlos) y el booleano de
        colision. Nunca lanza por una seccion `role_models` ausente o malformada
        (se trata como "sin valores comparables").
    """
    role_models = config.get("role_models")
    if not isinstance(role_models, dict):
        role_models = {}
    backends = config.get("backends")
    backend_names = set(backends) if isinstance(backends, dict) else set()

    builder_raw = role_models.get(_BUILDER_ROLE)
    revisor_raw = role_models.get(_REVISOR_ROLE)
    builder_model = _typed_model_id(builder_raw, backend_names)
    revisor_model = _typed_model_id(revisor_raw, backend_names)
    collision = (
        builder_model is not None
        and revisor_model is not None
        and builder_model == revisor_model
    )
    return builder_raw, revisor_raw, collision


def _format(value: object) -> str:
    return "<ausente>" if value is None else repr(value)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument(
        "--project-root",
        default=str(MOTOR_ROOT),
        help="raiz cuyo .agent/config/agents.json se audita (default: el motor)",
    )
    args = ap.parse_args(argv)

    project_root = Path(args.project_root).resolve()
    try:
        config = load_agents_config(project_root)
    except (AgentsConfigError, OSError) as exc:
        print(
            "[role-models-distinct] ERROR: no se pudo cargar agents.json de "
            f"{project_root}: {exc}",
            file=sys.stderr,
        )
        print(
            "  Un gate que no puede leer lo que guarda NO sale verde por defecto.",
            file=sys.stderr,
        )
        return 2

    builder_raw, revisor_raw, collision = compare_role_models(config)
    print(
        "[role-models-distinct] role_models.BUILDER="
        f"{_format(builder_raw)}  role_models.REVISOR={_format(revisor_raw)}"
    )

    if collision:
        print(
            "[role-models-distinct] ERROR: BUILDER y REVISOR comparten el MISMO "
            f"model_id real ({builder_raw!r}). La Capa 2 (revisor) audita el diff "
            "de la Capa 3 (builder): con el mismo modelo, la revision no es "
            "independiente. Declara un model_id DISTINTO para uno de los dos "
            "(PROPUESTA_vocabulario_roles_capas_20261011.md Seccion 8.3).",
            file=sys.stderr,
        )
        return 1

    print(
        "[role-models-distinct] OK: BUILDER y REVISOR no colisionan "
        "(el gate solo compara model_ids tipados; null o un nombre de backend "
        "nunca cuentan como colision)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
