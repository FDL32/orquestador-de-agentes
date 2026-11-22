"""Comprueba perfiles activos (opencode/kilo) contra un snapshot de catalogo.

WOT-2026-222a. Dos fuentes, nunca fusionadas: (1) `agents.json` del MOTOR
(`ensemble_profiles`, siempre via `load_motor_config` -- M9, nunca el destino
por `AGENT_PROJECT_ROOT`); (2) un snapshot JSON local con lo que
`opencode models` y `kilo models` sirven REALMENTE (WOT-2026-222a s.4: la
forma exacta de esos dos CLIs queda NO VERIFICADA hasta que el Builder los
pruebe -- este checker consume el snapshot ya capturado, no invoca los CLIs).

Invocacion: SIEMPRE como modulo (`python -m scripts.check_ensemble_profile_catalog
--catalog <ruta> [--config <ruta>]`), nunca como script suelto
(`python scripts/check_ensemble_profile_catalog.py`): sin `--config`, esta
rama llama a `load_motor_config()`, que hace `from scripts.ensemble_dispatch
import ...`; ejecutado como script, `sys.path[0]` es el propio directorio
`scripts/` y ese import falla con `ModuleNotFoundError: No module named
'scripts'` (medido P34 ronda 3, hallazgo ds H-03). Con `-m`, la raiz del repo
(cwd) esta en `sys.path` y el import resuelve.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


class CatalogSnapshotError(ValueError):
    """El snapshot no es una entrada utilizable: falla cerrado (rc 2)."""


def _parse_snapshot_timestamp(raw: object, field: str) -> datetime:
    if not isinstance(raw, str) or not raw:
        raise CatalogSnapshotError(f"snapshot metadata invalid: {field}")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CatalogSnapshotError(f"snapshot metadata invalid: {field}") from exc
    if parsed.tzinfo is None:
        raise CatalogSnapshotError(f"snapshot metadata invalid: {field}")
    return parsed.astimezone(timezone.utc)


def _validate_entries(entries: object) -> None:
    """Forma de los pares servidos: dict con `backend` y `model` no vacios.

    Before: `entries` es el campo `entries` ya extraido del snapshot JSON.
    During: recorre la lista; un elemento que no es dict, o sin `backend`/
        `model` de tipo str no vacio, es snapshot INVALIDO -> CatalogSnapshotError.
        Sin esta validacion la comprension de pares de `check_catalog`
        (`(e["backend"], e["model"])`) escapaba KeyError/TypeError con
        traceback, contra la frase de FICHA s.4 "invalido ... rc 2 ... sin
        traceback" (hallazgo V1 r1).
    After: no retorna nada; lanza CatalogSnapshotError o valida en silencio.
    """
    if not isinstance(entries, list):
        raise CatalogSnapshotError("snapshot metadata invalid: entries")
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("backend"), str)
            or not isinstance(entry.get("model"), str)
            or not entry.get("backend")
            or not entry.get("model")
        ):
            raise CatalogSnapshotError("snapshot metadata invalid: entries")


def _validate_snapshot(catalog: object) -> dict:
    """Valida procedencia, vigencia y forma de `entries`; nunca interpreta
    ausencia como vacio. Un `entry` sin `backend`/`model` (o no dict) es
    snapshot INVALIDO -> CatalogSnapshotError (rc 2 controlado en el CLI,
    FICHA s.4 'invalido ... sin traceback'), nunca KeyError/TypeError."""
    if not isinstance(catalog, dict):
        raise CatalogSnapshotError("snapshot metadata invalid: root")
    required = {"captured_at", "expires_at", "sources", "entries"}
    missing = sorted(required - set(catalog))
    if missing:
        raise CatalogSnapshotError(f"snapshot metadata missing: {','.join(missing)}")
    captured_at = _parse_snapshot_timestamp(catalog["captured_at"], "captured_at")
    expires_at = _parse_snapshot_timestamp(catalog["expires_at"], "expires_at")
    if not catalog["sources"]:
        raise CatalogSnapshotError("snapshot metadata missing: sources")
    if not isinstance(catalog["sources"], list):
        raise CatalogSnapshotError("snapshot metadata invalid: sources")
    required_source_fields = {
        "command",
        "backend",
        "captured_at",
        "sha256",
        "generator_version",
    }
    for source in catalog["sources"]:
        if not isinstance(source, dict):
            raise CatalogSnapshotError("snapshot metadata invalid: sources")
        missing_source_fields = sorted(required_source_fields - set(source))
        if missing_source_fields or not all(
            source.get(f) for f in required_source_fields
        ):
            raise CatalogSnapshotError(
                "snapshot metadata invalid: source missing "
                + ",".join(
                    missing_source_fields
                    or sorted(f for f in required_source_fields if not source.get(f))
                )
            )
    if expires_at <= captured_at or expires_at <= datetime.now(timezone.utc):
        raise CatalogSnapshotError("snapshot expired: expires_at")
    _validate_entries(catalog["entries"])
    return catalog


def load_motor_config() -> dict:
    """Config del MOTOR, nunca la del destino activo (M9)."""
    from scripts.ensemble_dispatch import load_motor_config as _load_motor_config

    return _load_motor_config()


def check_catalog(config_path: Path | None, catalog_path: Path) -> list[str]:
    """Pares inconsistentes entre las dos fuentes, en las dos direcciones.

    Before: `config_path` apunta al `agents.json` del motor (o None para
        `load_motor_config()`); `catalog_path` a un snapshot JSON vigente.
    During: valida vigencia (`_validate_snapshot`, fail-closed) y compara los
        perfiles ACTIVOS opencode/kilo contra los pares `(backend, model)`
        servidos. Un par servido que coincide con un perfil LEGACY existente
        es legado TOLERADO, no huerfano (WOT-2026-222a s.6): solo un par
        servido SIN NINGUN perfil, activo o legacy, es huerfano.
    After: lista estable de errores; vacia = ambas direcciones coherentes.
    """
    try:
        config = (
            load_motor_config()
            if config_path is None
            else json.loads(config_path.read_text(encoding="utf-8"))
        )
        catalog = _validate_snapshot(
            json.loads(catalog_path.read_text(encoding="utf-8"))
        )
    except (OSError, json.JSONDecodeError, CatalogSnapshotError) as exc:
        raise CatalogSnapshotError(f"snapshot unavailable or invalid: {exc}") from exc

    profiles = config.get("ensemble_profiles", {})
    vector_backends = {"opencode", "kilo"}
    served_pairs = {(e["backend"], e["model"]) for e in catalog["entries"]}

    errors: list[str] = []
    for name, profile in profiles.items():
        if profile.get("status") == "legacy":
            continue
        backend = profile.get("backend")
        model = profile.get("model")
        if backend in vector_backends and (backend, model) not in served_pairs:
            errors.append(f"profile model not served: ({backend}, {model}) [{name}]")

    known_pairs = {
        (profile.get("backend"), profile.get("model"))
        for profile in profiles.values()
        if profile.get("backend") in vector_backends
    }
    errors.extend(
        f"served model lacks active profile: {pair}"
        for pair in sorted(served_pairs - known_pairs)
        if pair[0] in vector_backends
    )
    return errors


def main(argv: list[str] | None = None) -> int:
    """Ejecuta la comprobacion y devuelve rc fail-closed (2 en vez de 1 solo
    cuando el snapshot mismo no es legible/vigente; 1 cuando el snapshot es
    valido pero las dos fuentes divergen)."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--catalog", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        errors = check_catalog(args.config, args.catalog)
    except CatalogSnapshotError as exc:
        print(f"[catalog] ERROR: {exc}")
        return 2
    for error in errors:
        print(error)
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
