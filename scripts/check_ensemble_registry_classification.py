#!/usr/bin/env python3
"""Lint de clasificacion de endpoints de ensemble (WOT-2026-089h-1, fase F0).

Cada endpoint `active` de `.agent/config/agents.json::ensemble_registry.
backend_keys` declara `lab`, `family`, `tier` y `generation` (y `variant`
opcional). Este modulo es la UNICA capa que valida esa clasificacion.

Esquema CONGELADO Y VERSIONADO (`ensemble_registry.classification.schema_version`):
la version 1 fija los campos requeridos, los tiers y un suelo de laboratorios
(ver `FROZEN`). Un cambio incompatible exige una version nueva y su migracion.
Los dependientes (089i, 089j, 089k) lo citan como
`classification schema v<N> @ <SHA del commit 089h-1>`.

Reglas de campo (v1):
  - `lab`: quien entreno los pesos (no quien los sirve), de la tabla cerrada
    `classification.labs`. Un laboratorio nuevo = ampliar la tabla = decision
    humana.
  - `family`: una palabra en minusculas, sin version ni tamano.
  - `tier`: clase operativa por la nomenclatura del proveedor: `flash` si el id
    lleva flash/mini/haiku/lite/nano, `full` en otro caso. Tamano y especialidad
    van a `variant`, nunca a `tier`.
  - `generation`: entero >= 1, ordinal dentro de (family, tier); lo asigna una
    persona y no se recalcula al leer. Sin version comparable (alias) = 1.
  - `variant`: cadena libre no vacia, opcional.

Este lint NO enruta ni cuenta independencia (089i) y solo mira el agents.json
del MOTOR; no se invoca desde `load_agents_config` para no volver ilegible el
config de un destino desfasado.

Exit codes: 0 (ok), 1 (hallazgos), 2 (no verificable: config ilegible o sin
endpoints; nunca se imprime OK sin haber comprobado ninguno).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


MOTOR_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = MOTOR_ROOT / ".agent" / "config" / "agents.json"

FROZEN: dict[str, dict[str, tuple[str, ...]]] = {
    "1": {
        "required_fields": ("lab", "family", "tier", "generation"),
        "tiers": ("full", "flash"),
        "labs_floor": (
            "Alibaba",
            "Anthropic",
            "Cohere",
            "DeepSeek",
            "Google",
            "MiniMax",
            "Mistral AI",
            "Moonshot",
            "NVIDIA",
            "OpenAI",
            "Xiaomi",
            "Zhipu",
        ),
    }
}
OPTIONAL_FIELDS = ("variant",)
_FAMILY_RE = re.compile(r"^[a-z][a-z0-9]*$")
TIER_FLASH_MARKERS = frozenset({"flash", "mini", "haiku", "lite", "nano"})


def tier_by_rule(model: object) -> str:
    """Tier que dicta la regla mecanica para un id de modelo (v1).

    Before: `model` es el id del registro (cadena) o None (backend sin modelo).
    During: parte el id en tokens alfanumericos (`minimax` y `gemini` NO son el
        token `mini`; `north-mini-code` si) y busca un marcador de pequeno/rapido.
    After: `flash` si algun token es marcador; `full` en otro caso (incluido None).
    """
    if not isinstance(model, str):
        return "full"
    tokens = set(re.split(r"[^a-z0-9]+", model.lower()))
    return "flash" if tokens & TIER_FLASH_MARKERS else "full"


def _lint_block(block: object) -> tuple[dict | None, list[str]]:
    """Valida el bloque `classification`; devuelve (bloque util, errores)."""
    if not isinstance(block, dict):
        return None, ["ensemble_registry.classification ausente o no es un objeto"]
    version = block.get("schema_version")
    if not isinstance(version, str) or version not in FROZEN:
        return None, [
            f"classification.schema_version {version!r} desconocida; "
            f"versiones congeladas: {sorted(FROZEN)}"
        ]
    frozen = FROZEN[version]
    errors: list[str] = []
    if block.get("required_fields") != list(frozen["required_fields"]):
        errors.append(
            f"classification.required_fields {block.get('required_fields')!r} "
            f"difiere del esquema congelado v{version} "
            f"{list(frozen['required_fields'])}: un cambio incompatible exige "
            "subir schema_version"
        )
    if block.get("tiers") != list(frozen["tiers"]):
        errors.append(
            f"classification.tiers {block.get('tiers')!r} difiere del esquema "
            f"congelado v{version} {list(frozen['tiers'])}"
        )
    labs = block.get("labs")
    if (
        not isinstance(labs, list)
        or any(not isinstance(x, str) or not x.strip() for x in labs)
        or len(set(labs)) != len(labs)
    ):
        errors.append("classification.labs debe ser una lista de cadenas unicas")
    else:
        lost = sorted(set(frozen["labs_floor"]) - set(labs))
        if lost:
            errors.append(
                f"classification.labs perdio laboratorios del suelo v{version}: {lost}"
            )
    status_rule = block.get("required_for_status")
    if not isinstance(status_rule, list) or "active" not in status_rule:
        errors.append("classification.required_for_status debe incluir 'active'")
    return block, errors


def _lint_endpoint(key: str, ent: dict, block: dict) -> list[str]:
    """Valida los campos de UN endpoint contra el bloque; mensajes por campo."""
    required = block["required_fields"]
    status = ent.get("status")
    present = [f for f in required if f in ent]
    must = status in block["required_for_status"]
    errors: list[str] = []
    if not must and not present:
        return errors
    for field in required:
        if field not in ent:
            why = f"status={status}" if must else "clasificacion parcial"
            errors.append(f"{key}: campo '{field}' ausente ({why})")
    labs = block["labs"] if isinstance(block.get("labs"), list) else []
    lab = ent.get("lab")
    if "lab" in ent and lab not in labs:
        errors.append(
            f"{key}: campo 'lab' = {lab!r} fuera de la tabla cerrada classification.labs"
        )
    family = ent.get("family")
    if "family" in ent and not (isinstance(family, str) and _FAMILY_RE.match(family)):
        errors.append(
            f"{key}: campo 'family' = {family!r} debe ser una palabra en minusculas"
        )
    if "tier" in ent and ent.get("tier") not in block["tiers"]:
        errors.append(
            f"{key}: campo 'tier' = {ent.get('tier')!r} fuera de {block['tiers']}"
        )
    elif "tier" in ent and ent["tier"] != tier_by_rule(ent.get("model")):
        errors.append(
            f"{key}: campo 'tier' = {ent['tier']!r} contradice la regla de tier "
            f"para el modelo {ent.get('model')!r} (la regla da "
            f"{tier_by_rule(ent.get('model'))!r}); tamano o especialidad van a 'variant'"
        )
    gen = ent.get("generation")
    if "generation" in ent and (
        isinstance(gen, bool) or not isinstance(gen, int) or gen < 1
    ):
        errors.append(f"{key}: campo 'generation' = {gen!r} debe ser un entero >= 1")
    if "variant" in ent and not (
        isinstance(ent["variant"], str) and ent["variant"].strip()
    ):
        errors.append(f"{key}: campo 'variant' debe ser una cadena no vacia")
    return errors


def lint_registry(config: dict) -> list[str]:
    """Lista los hallazgos de clasificacion del registro; vacia = coherente.

    Before: `config` es el dict de un agents.json; se espera
        `ensemble_registry.backend_keys` (dict BAxx -> entrada) y el bloque
        `ensemble_registry.classification`.
    During: valida el bloque contra `FROZEN`, cada endpoint contra el bloque
        (obligatoria si su status esta en `required_for_status`; un endpoint
        no obligatorio con clasificacion parcial tambien falla), que los
        endpoints con el mismo par (backend, model) compartan clasificacion y
        que una `family` pertenezca a un solo `lab`. Solo lee.
    After: devuelve mensajes que nombran endpoint y campo; no lanza por datos
        mal formados (los reporta como hallazgo).
    """
    registry = config.get("ensemble_registry") if isinstance(config, dict) else None
    if not isinstance(registry, dict) or not isinstance(
        registry.get("backend_keys"), dict
    ):
        return ["ensemble_registry.backend_keys ausente o no es un objeto"]
    block, errors = _lint_block(registry.get("classification"))
    if block is None:
        return errors
    frozen = FROZEN[block["schema_version"]]
    labs = block.get("labs")
    status_rule = block.get("required_for_status")
    # Un bloque mal formado ya dio su hallazgo: los endpoints se miden contra el
    # esquema congelado (no contra lo que el bloque dice) para no fabricar ruido.
    effective = {
        "required_fields": list(frozen["required_fields"]),
        "tiers": list(frozen["tiers"]),
        "labs": labs if isinstance(labs, list) else [],
        "required_for_status": status_rule
        if isinstance(status_rule, list)
        else ["active"],
    }
    return errors + _lint_endpoints(registry, effective)


def _lint_endpoints(registry: dict, block: dict) -> list[str]:
    errors: list[str] = []
    by_pair: dict[tuple, tuple[str, tuple]] = {}
    lab_of_family: dict[str, tuple[str, str]] = {}
    for key, ent in registry["backend_keys"].items():
        if not isinstance(ent, dict):
            errors.append(f"{key}: la entrada del registro no es un objeto")
            continue
        errors.extend(_lint_endpoint(key, ent, block))
        if not all(f in ent for f in block["required_fields"]):
            continue
        sig = tuple(ent.get(f) for f in (*block["required_fields"], "variant"))
        pair = (ent.get("backend"), ent.get("model"))
        if pair in by_pair and by_pair[pair][1] != sig:
            errors.append(
                f"{key}: clasificacion distinta de {by_pair[pair][0]} para el "
                f"mismo par (backend, model) = {pair}"
            )
        by_pair.setdefault(pair, (key, sig))
        fam, lab = ent.get("family"), ent.get("lab")
        if fam in lab_of_family and lab_of_family[fam][0] != lab:
            errors.append(
                f"{key}: la family {fam!r} ya pertenece a lab "
                f"{lab_of_family[fam][0]!r} ({lab_of_family[fam][1]}), no a {lab!r}"
            )
        lab_of_family.setdefault(fam, (lab, key))
    return errors


def lint_config_file(path: Path) -> list[str]:
    """Lee un agents.json y devuelve los hallazgos de `lint_registry`.

    Before: `path` apunta al agents.json a revisar (normalmente el del motor).
    During: lee y parsea el JSON (solo lectura).
    After: lista de hallazgos; un fichero ilegible o un registro sin endpoints se
        devuelve como hallazgo (nunca como lista vacia: no hay OK vacuo).
    """
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"no verificable: {path}: {exc}"]
    keys = (config.get("ensemble_registry") or {}).get("backend_keys")
    if not isinstance(keys, dict) or not keys:
        return ["no verificable: ensemble_registry.backend_keys vacio o ausente"]
    return lint_registry(config)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(argv)
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"[classification] NO VERIFICABLE: {args.config}: {exc}")
        return 2
    keys = (config.get("ensemble_registry") or {}).get("backend_keys")
    if not isinstance(keys, dict) or not keys:
        print("[classification] NO VERIFICABLE: ensemble_registry.backend_keys vacio")
        return 2
    errors = lint_registry(config)
    if errors:
        print("[classification] FAIL:")
        for err in errors:
            print(f"  - {err}")
        return 1
    active = sum(1 for e in keys.values() if e.get("status") == "active")
    print(f"[classification] OK: {len(keys)} endpoints revisados ({active} active)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
