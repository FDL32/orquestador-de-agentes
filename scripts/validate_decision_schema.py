#!/usr/bin/env python
"""
Decision Schema Validator - Exige que decision_*.json enlace su evidencia.

WOT-2026-050b: un `decision_<ticket_id>.json` con la forma historica
`{ticket_id, decision, blockers}` registra un APROBADO/CHANGES sin ninguna
referencia a la revision (transcript, bundle o sesion) que lo justifica. Un
APROBADO sin cadena a la review que lo produjo no es auditable ni aunque el
fichero se versione: la decision queda, pero su justificacion no viaja con
ella.

Este validador exige un campo nuevo, `review_evidence_ref` (ruta, sha o id
del artefacto de review), no vacio. NO sustituye a `reviewed_commit_sha`
(WT-2026-047m, que ata la decision al COMMIT revisado): son ejes distintos
-- uno dice QUE se reviso, el otro dice DONDE vive la review que lo
justifica.

Uso:
    python scripts/validate_decision_schema.py <path-a-decision_*.json> [...]
    python scripts/validate_decision_schema.py --reviews-dir <dir>

Salida:
    - Por defecto: un error por linea, con el fichero y el campo que falta.
    - Exit code: 0 si todos los ficheros validan, 1 si alguno falla.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REQUIRED_EVIDENCE_FIELD = "review_evidence_ref"


def validate_decision_file(path: Path) -> list[str]:
    """Valida un decision_*.json contra el esquema con evidencia obligatoria.

    Before: `path` apunta a un fichero que puede existir o no, ser JSON
        valido o no, y tener cualquier forma.
    During: lee y parsea el fichero; comprueba que `REQUIRED_EVIDENCE_FIELD`
        este presente y sea una cadena no vacia tras `strip()`.
    After: retorna una lista de errores (vacia == valido). Nunca lanza: un
        fichero ilegible o JSON invalido produce un error descriptivo, no
        una excepcion.
    """
    errors: list[str] = []
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{path}: no se pudo leer ({exc})"]
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [f"{path}: JSON invalido ({exc})"]
    if not isinstance(payload, dict):
        return [f"{path}: el payload no es un objeto JSON"]

    evidence_ref = payload.get(REQUIRED_EVIDENCE_FIELD)
    if not isinstance(evidence_ref, str) or not evidence_ref.strip():
        errors.append(
            f"{path}: falta '{REQUIRED_EVIDENCE_FIELD}' (ruta/sha/id del "
            "artefacto de review que justifica la decision) -- "
            "WOT-2026-050b"
        )
    return errors


def validate_paths(paths: list[Path]) -> list[str]:
    """Valida una lista de ficheros decision_*.json y agrega sus errores.

    Before: `paths` es una lista de rutas a validar (ya expandida por el
        caller; este helper no hace globbing).
    During: aplica `validate_decision_file` a cada ruta en orden.
    After: retorna la concatenacion de todos los errores encontrados.
    """
    errors: list[str] = []
    for path in paths:
        errors.extend(validate_decision_file(path))
    return errors


def _discover_decision_files(reviews_dir: Path) -> list[Path]:
    if not reviews_dir.is_dir():
        return []
    return sorted(reviews_dir.glob("decision_*.json"))


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada principal.

    Before: argumentos de linea de comandos parseados (rutas explicitas, o
        `--reviews-dir` para descubrir `decision_*.json` por glob).
    During: resuelve la lista de ficheros a validar y corre
        `validate_paths`.
    After: imprime cada error (si los hay) y retorna 1; retorna 0 y no
        imprime nada si todo valida.
    """
    parser = argparse.ArgumentParser(
        description="Valida que decision_*.json enlace su evidencia de review"
    )
    parser.add_argument(
        "paths",
        type=Path,
        nargs="*",
        help="Rutas explicitas a decision_*.json",
    )
    parser.add_argument(
        "--reviews-dir",
        type=Path,
        default=None,
        help="Directorio donde descubrir decision_*.json por glob",
    )
    args = parser.parse_args(argv)

    targets = list(args.paths)
    if args.reviews_dir is not None:
        targets.extend(_discover_decision_files(args.reviews_dir))

    if not targets:
        print("[validate-decision-schema] 0 ficheros a validar")
        return 0

    errors = validate_paths(targets)
    if errors:
        for error in errors:
            print(f"[validate-decision-schema] FAIL: {error}")
        return 1
    print(f"[validate-decision-schema] OK: {len(targets)} fichero(s) validado(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
