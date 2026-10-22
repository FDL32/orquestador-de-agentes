#!/usr/bin/env python3
"""Registro de excepciones YAML con 4 salvaguardas duras (WOT-2026-119a).

Sustituye el mecanismo de override por COMMIT-MESSAGE (WOT-2026-108d, "G1
flip"): la gramatica `GATE-OVERRIDE: cuspide_growth` / `REASON:` / `AFFECTED:`
dentro de `scripts/check_cuspide_growth_and_drift.py`. Ese mecanismo quedo
IMPOTENTE a proposito el 2026-10-21 (el override deja de exceptuar nada, ni
siquiera el escalon "en deuda" que WOT-2026-116a anadio despues) porque su
diseno era irreparable dentro del patron commit-message:
  - auto-aprobacion: quien escribe el commit controla el override -- el mismo
    commit que introduce el crecimiento puede llevar el override que lo
    excusa, sin ninguna autoridad externa que lo revise antes.
  - sin expiry: una vez aterrizado en el historial, el override vive para
    siempre; nada lo vuelve a mirar ("declarado y olvidado").
  - sin scope: el override es binario -- exceptua TODO el gate de cuspide o
    nada, nunca una ruta concreta.
  - fail-open declarado como norma del motor (`check_commit_message_encoding.py`
    :158-165): razonable para un guard de crecimiento de prosa (bloquear cada
    commit porque el guard se rompio es peor que el gap que cubre), pero
    inaceptable para un mecanismo cuyo PROPIO proposito es conceder
    excepciones de seguridad -- ahi un YAML corrupto que degrada a exit 0 ES
    el bypass silencioso que el mecanismo deberia impedir.

Este modulo no reemplaza el guard de cuspide (sigue BLOCK sin excepcion, por
diseno deliberado de 108d/116a) -- es el mecanismo GENERICO de excepcion que
el consenso R3 (WOT-2026-119a) pidio como sustituto para el resto de guards
del motor, con las 4 salvaguardas explicitas:

  (a) anti-auto-aprobacion: `self_approval_violation` rechaza un override
      anadido/modificado en el MISMO commit (mismo conjunto de ficheros
      staged) que un fichero dentro de su propio `scope`.
  (b) expiry barrido por un proceso REAL: `check_override_registry.py
      --phase pre-commit` corre en CADA commit (cableado en
      `.pre-commit-config.yaml`, no una norma en un prompt) y WARNea; la fase
      `--phase commit-msg` BLOQUEA (exit 1) si un override activo sigue
      expirado y sin archivar -- fuerza su archivado/renovacion, nunca queda
      "declarado y olvidado" como el override de commit-message.
  (c) scope con matching ESTRICTO: `scope` es una lista de rutas LITERALES
      (ni fnmatch ni glob, ninguna libreria de patrones). `scope_matches`
      compara igualdad exacta de string tras normalizar separadores. Un
      comodin dentro de `scope` es un YAML MALFORMADO (fail-closed, ver (d)),
      nunca un patron que se interprete laxo.
  (d) fail-CLOSED: `parse_override` lanza `OverrideRegistryError` ante YAML
      ilegible, campo ausente, tipo incorrecto o comodin en `scope`; la CLI
      (`check_override_registry.py`) sale con exit 1 en ese caso, NUNCA exit
      0 silencioso -- divergencia deliberada del precedente fail-open citado
      arriba, documentada ahi mismo en el modulo CLI.

Busqueda de protocolo previo (CEM, decision de proceso, WOT-2026-119a):
`grep -rli "override\\|excepcion" .agent/rules/common/ docs/ prompts/` --
**NO ENCONTRE PROTOCOLO** documentado para un mecanismo GENERICO de excepcion
con expiry+scope+aprobador. El unico precedente real es el propio
commit-message de cuspide (especifico de ESE guard, ya impotente por diseno,
ver arriba) y el patron de etiquetas de evidencia de
`prompts/orchestrator_pipeline.md:978-1005` (modelo de ESTILO -- gramatica
`CLAVE: valor` en lineas propias -- para la redaccion del YAML, no un
mecanismo de excepcion). Diseno desde cero.

Before: se invoca como libreria desde `check_override_registry.py` (CLI) o
    desde un test; no asume cwd ni variables de entorno.
During: lectura de ficheros `.yaml` bajo `.agent/overrides/` (NUNCA recursiva
    -- `Path.glob("*.yaml")` no desciende a `_archive/`, asi que un override
    ya archivado deja de contar como activo sin necesitar un flag propio) y,
    para el chequeo de auto-aprobacion, `git diff --cached --name-only` sobre
    el repo en curso.
After: devuelve datos (`Override`, listas, bools) o lanza
    `OverrideRegistryError` -- nunca imprime ni hace `sys.exit`; esa decision
    es de la CLI.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import yaml


MOTOR_ROOT = Path(__file__).resolve().parents[1]
OVERRIDES_DIR = MOTOR_ROOT / ".agent" / "overrides"
ARCHIVE_DIR = OVERRIDES_DIR / "_archive"

REQUIRED_FIELDS = ("id", "scope", "expiry", "aprobador", "justificacion")
_WILDCARD_CHARS = ("*", "?", "[", "]")


class OverrideRegistryError(RuntimeError):
    """Error fail-closed: YAML de override ilegible, incompleto o malformado."""


class _StrictNoDuplicateKeysLoader(yaml.SafeLoader):
    """SafeLoader que rechaza claves duplicadas (en vez del last-wins por defecto).

    Hallazgo del Revisor independiente (WOT-2026-119a): un YAML con dos
    bloques `scope:` parsea SIN error con `yaml.safe_load` y la maquina usa
    el ULTIMO silenciosamente, mientras un humano que lo lee por encima ve
    el primero -- ambiguedad real entre lo que el aprobador aprueba y lo que
    el mecanismo ejecuta. Sigue siendo un SafeLoader (ningun constructor de
    `!!python/*`); solo cambia la construccion de mappings.
    """


def _construct_mapping_no_duplicates(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_StrictNoDuplicateKeysLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping_no_duplicates
)


@dataclass(frozen=True)
class Override:
    """Una excepcion registrada. `source_path` es el YAML que la declara."""

    id: str
    scope: tuple[str, ...]
    expiry: date
    aprobador: str
    justificacion: str
    source_path: Path


def normalize_relpath(path_str: str) -> str:
    """Normaliza separadores para comparar rutas de forma portable (Windows/POSIX).

    Solo recorta un prefijo LITERAL `./` (repetido), nunca caracteres sueltos:
    `lstrip("./")` recorta cualquier `.`/`/` iniciales como CONJUNTO de
    caracteres, no como prefijo -- eso colapsaba `.agent/x` en `agent/x` y
    `../x` en `x` (hallazgo del Revisor independiente, WOT-2026-119a,
    bypass de salvaguarda c/a via normalizacion). `_parse_scope` ademas
    rechaza cualquier entrada de `scope` con un segmento `..` (fail-closed).
    """
    normalized = path_str.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _require_nonempty_str(data: dict, field: str, source_path: Path) -> str:
    value = data[field]
    if not isinstance(value, str) or not value.strip():
        raise OverrideRegistryError(
            f"{source_path}: '{field}' debe ser string no vacio"
        )
    return value.strip()


def _parse_scope(data: dict, source_path: Path) -> tuple[str, ...]:
    scope_raw = data["scope"]
    if not isinstance(scope_raw, list):
        raise OverrideRegistryError(f"{source_path}: 'scope' debe ser una lista")
    scope: list[str] = []
    for entry in scope_raw:
        if not isinstance(entry, str) or not entry.strip():
            raise OverrideRegistryError(
                f"{source_path}: entrada de 'scope' invalida: {entry!r}"
            )
        if any(ch in entry for ch in _WILDCARD_CHARS):
            raise OverrideRegistryError(
                f"{source_path}: 'scope' no admite comodines "
                f"(matching estricto, salvaguarda c): {entry!r}"
            )
        normalized_entry = entry.strip().replace("\\", "/")
        if ".." in normalized_entry.split("/"):
            raise OverrideRegistryError(
                f"{source_path}: 'scope' no admite segmentos '..' "
                f"(matching estricto, salvaguarda c): {entry!r}"
            )
        scope.append(normalize_relpath(entry))
    return tuple(scope)


def _parse_expiry(data: dict, source_path: Path) -> date:
    expiry_raw = data["expiry"]
    # `datetime` es subclase de `date`: un `isinstance(x, date)` desnudo
    # aceptaba un timestamp con hora (PyYAML lo autoconvierte) y el TypeError
    # resultante explotaba sin capturar en `is_expired` (hallazgo del Revisor
    # independiente, WOT-2026-119a) -- se rechaza aqui explicitamente, ANTES
    # del isinstance(date) general.
    if isinstance(expiry_raw, datetime):
        raise OverrideRegistryError(
            f"{source_path}: 'expiry' debe ser fecha ISO YYYY-MM-DD sin hora "
            f"(recibido un datetime con hora): {expiry_raw!r}"
        )
    if isinstance(expiry_raw, date):
        return expiry_raw
    if isinstance(expiry_raw, str):
        try:
            return date.fromisoformat(expiry_raw.strip())
        except ValueError as exc:
            raise OverrideRegistryError(
                f"{source_path}: 'expiry' debe ser fecha ISO YYYY-MM-DD, "
                f"recibido {expiry_raw!r}"
            ) from exc
    raise OverrideRegistryError(
        f"{source_path}: 'expiry' debe ser fecha ISO YYYY-MM-DD, "
        f"recibido {expiry_raw!r}"
    )


def parse_override(text: str, source_path: Path) -> Override:
    """Parsea la gramatica exacta del YAML de override. Fail-closed (salvaguarda d).

    Lanza `OverrideRegistryError` ante cualquier desviacion: YAML no parseable,
    no-mapping, campo obligatorio ausente o vacio, tipo incorrecto, o un
    comodin dentro de `scope` (salvaguarda c: el scope es literal, nunca un
    patron laxo).
    """
    try:
        # S506: el linter no distingue loaders por herencia -- este SIGUE
        # siendo un yaml.SafeLoader (ver su definicion arriba), solo con la
        # construccion de mappings sobreescrita para rechazar duplicados.
        data = yaml.load(text, Loader=_StrictNoDuplicateKeysLoader)  # noqa: S506
    except yaml.YAMLError as exc:
        raise OverrideRegistryError(f"{source_path}: YAML ilegible: {exc}") from exc
    if not isinstance(data, dict):
        raise OverrideRegistryError(f"{source_path}: el YAML no es un mapping")

    missing = [
        field
        for field in REQUIRED_FIELDS
        if field not in data or data[field] in (None, "", [])
    ]
    if missing:
        raise OverrideRegistryError(
            f"{source_path}: faltan campos obligatorios: {missing}"
        )

    override_id = _require_nonempty_str(data, "id", source_path)
    scope = _parse_scope(data, source_path)
    expiry = _parse_expiry(data, source_path)
    aprobador = _require_nonempty_str(data, "aprobador", source_path)
    justificacion = _require_nonempty_str(data, "justificacion", source_path)

    return Override(
        id=override_id,
        scope=scope,
        expiry=expiry,
        aprobador=aprobador,
        justificacion=justificacion,
        source_path=source_path,
    )


def load_overrides(directory: Path = OVERRIDES_DIR) -> list[Override]:
    """Carga los overrides ACTIVOS (no archivados) de `directory`.

    No recursivo a proposito: un override movido a `<directory>/_archive/`
    deja de ser alcanzado por `glob("*.yaml")` y por tanto de contar como
    activo, sin necesitar un campo `status` propio.
    """
    if not directory.is_dir():
        return []
    overrides = []
    for path in sorted(directory.glob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        overrides.append(parse_override(text, path))
    return overrides


def scope_matches(override: Override, path_str: str) -> bool:
    """Matching ESTRICTO (salvaguarda c): igualdad exacta tras normalizar."""
    normalized = normalize_relpath(path_str)
    return normalized in override.scope


def is_expired(override: Override, today: date) -> bool:
    return override.expiry < today


def self_approval_violation(
    override: Override, override_rel_path: str, changed_files: Iterable[str]
) -> bool:
    """Salvaguarda (a): True si el override Y un fichero de su scope estan
    en el MISMO conjunto de ficheros (staged o de un commit concreto)."""
    changed = {normalize_relpath(f) for f in changed_files}
    if normalize_relpath(override_rel_path) not in changed:
        return False
    return any(scope_entry in changed for scope_entry in override.scope)


_GIT = shutil.which("git") or "git"


def staged_files(cwd: Path = MOTOR_ROOT) -> list[str]:
    """Ficheros staged para el commit en curso (antes de que exista el SHA).

    `--diff-filter` incluye `R` (renames) a proposito: sin ella, `git mv` deja
    invisible tanto al override (reactivado desde `_archive/` o renombrado)
    como al fichero scoped renombrado, y `self_approval_violation` no puede
    ver lo que nunca aparece en la lista -- bypass de la salvaguarda (a) via
    `git mv`, encontrado por el Revisor independiente (WOT-2026-119a). Con
    `R` en el filtro, `--name-only` reporta la ruta NUEVA del rename, que es
    exactamente la ruta vigente que `scope`/`source_path` necesitan comparar.
    """
    result = subprocess.run(  # noqa: S603
        [_GIT, "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]
