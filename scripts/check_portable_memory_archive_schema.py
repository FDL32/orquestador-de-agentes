#!/usr/bin/env python3
"""Guard: SCHEMA de las lecciones portables trackeadas (WOT-2026-035b).

Before (Pre-condiciones):
    - `--motor-root` (opcional) debe ser la raiz (toplevel) de un checkout git;
      por defecto es la raiz del motor resuelta desde `Path(__file__)` (patron
      de los guards `always_run`: `check_guard_wiring.py`, `check_ruff_hook_scope.py`).
    - No requiere `--project-root` obligatorio: el hook de pre-commit no pasa
      `args:`, asi que el default debe bastar por si solo.
    - `scripts/validate_observations.py` debe ser importable como modulo
      (`from scripts.validate_observations import validate_file`) para reusar
      su logica de schema sin reimplementarla.

During (Proceso y Recursos):
    - Resuelve la raiz, valida que sea git toplevel (`assert_git_repo`, mismo
      patron que `check_portable_memory_promotion.py`).
    - Glob de `.agent/runtime/memory/archive/observations.*.jsonl` bajo esa
      raiz (`ARCHIVE_DIR_REL`, patron locator reutilizado literal de
      `check_portable_memory_promotion.py`).
    - Para cada archivo encontrado, llama
      `validate_file(path, strict=True)` -- IMPORTA el modulo
      `validate_observations`, no reimplementa el schema. Esto ademas hace
      que el grafo de wiring (`check_guard_wiring.py`) registre
      `validate_observations` como invocado va import estatico: el detector
      casa el SEGMENTO MODULO de un `ImportFrom`, no el symbol importado, asi
      que el import debe ser `from scripts.validate_observations import
      validate_file` (module=`scripts.validate_observations`), no
      `from scripts import validate_observations` (module=`scripts`, invisible
      para el grafo).
    - No escribe nada; no muta el arbol.

After (Post-condiciones y Errores):
    - Exit 0: todos los archive files encontrados son validos, O NO se
      encontro ningun archive file. CERO archives es OK a proposito: este
      guard vigila SCHEMA, no PRESENCIA. Un repo_destino recien clonado no
      tiene memoria portable todavia y eso no es un fallo de schema. La
      propiedad "el archive debe existir / no debe perderse una leccion" es
      de otro guard (`check_portable_memory_promotion.py`, que audita
      orfandad runtime-vs-archive) y queda fuera de alcance aqui a proposito
      (ver work_plan.md WOT-2026-035b, NON-GOALS).
    - Exit 1: fallo de la HERRAMIENTA (root no es git, root no existe,
      archivo illegible). No es un hallazgo sobre el contenido.
    - Exit 4: HALLAZGO -- al menos una entrada de al menos un archive file es
      invalida contra el schema. Imprime los errores linea a linea que
      devuelve `validate_file`.

Uso:
    python scripts/check_portable_memory_archive_schema.py [--motor-root <repo>]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


MOTOR_ROOT = Path(__file__).resolve().parent.parent

# Bootstrap: motor root on sys.path so `from scripts.validate_observations import
# validate_file` resolves both when this script runs directly
# (`python scripts/check_....py`) and when it is imported/subprocessed from
# elsewhere.
if str(MOTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(MOTOR_ROOT))

ARCHIVE_DIR_REL = Path(".agent/runtime/memory/archive")

EXIT_OK = 0
EXIT_TOOL_ERROR = 1
EXIT_SCHEMA_INVALID = 4
EXIT_IDENTITY_COLLISION = 5

# Pares de identidad (topic, source_ticket) YA REVISADOS como lecciones DISTINTAS y
# legitimas del mismo ticket (WOT-2026-038n, medido 2026-07-20). El reconciliador
# deduplica por (topic, source_ticket); estos comparten esa clave con `id`/`signal`
# distintos. Estan en la allowlist para que el guard bloquee solo colisiones NUEVAS
# sin revisar, no el estado sano actual. Anadir aqui una clave es una DECISION HUMANA
# (declarar "estas dos son lecciones distintas, no una re-edicion").
ACCEPTED_COLLISIONS = frozenset(
    {
        ("manager-review-rubric", "WP-2026-137"),
        ("manager-review-rubric", "WP-2026-133"),
        ("delivery-hook-mutation", "WT-2026-191"),
    }
)


class ToolError(Exception):
    """Fallo de la HERRAMIENTA (exit 1), distinto de un hallazgo (exit 4)."""


def assert_git_repo(root: Path) -> None:
    """`root` debe ser la RAIZ (toplevel) de un checkout/worktree git, no un
    subdirectorio cualquiera dentro de uno (mismo razonamiento que
    `check_portable_memory_promotion.assert_git_repo`: un directorio suelto
    bajo el arbol del motor resuelve al `.git` del motor por herencia y el
    guard auditaria el repo equivocado dandolo por bueno)."""
    r = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],  # noqa: S607
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        raise ToolError(f"{root} no es un repositorio git (returncode={r.returncode})")
    toplevel = Path(r.stdout.strip()).resolve()
    if toplevel != root:
        raise ToolError(
            f"--motor-root debe ser la raiz de un checkout git; {root} esta DENTRO "
            f"de {toplevel} pero no es su raiz"
        )


def find_archive_files(root: Path) -> list[Path]:
    """Archive files trackeados a validar (glob del arbol vivo, no del argv)."""
    archive_dir = root / ARCHIVE_DIR_REL
    if not archive_dir.is_dir():
        return []
    return sorted(archive_dir.glob("observations.*.jsonl"))


def find_identity_collisions(paths: list[Path]) -> dict[tuple[str, str], set[str]]:
    """Colisiones de identidad: claves (topic, source_ticket) con >1 leccion DISTINTA.

    Recorre todos los archive files, agrupa por (topic, source_ticket) y marca como
    colision cualquier clave con mas de un `id` distinto (dos lecciones distintas que
    el dedup del reconciliador fusionaria, perdiendo una). Devuelve {clave: {ids}} solo
    para las claves colisionantes NO presentes en ACCEPTED_COLLISIONS.

    Un registro repetido byte a byte (mismo contenido dos veces) NO es colision de
    identidad: es un duplicado exacto que el dedup resuelve correctamente. Solo CONTENIDO
    DISTINTO bajo la misma clave es el caso peligroso.

    La huella de contenido se calcula sobre el registro SIN su propio `id` (para no
    depender de que `id` este presente ni de si fue regenerado): dos registros con el
    mismo contenido util producen la misma huella aunque a uno le falte el `id`.
    """

    def _fingerprint(rec: dict) -> str:
        body = {k: v for k, v in rec.items() if k != "id"}
        return json.dumps(body, sort_keys=True, ensure_ascii=False)

    by_key: dict[tuple[str, str], set[str]] = {}
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                # El schema-check ya reporta JSON invalido; aqui lo saltamos.
                continue
            key = (rec.get("topic", ""), rec.get("source_ticket", ""))
            by_key.setdefault(key, set()).add(_fingerprint(rec))
    return {
        key: fps
        for key, fps in by_key.items()
        if len(fps) > 1 and key not in ACCEPTED_COLLISIONS
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument(
        "--motor-root",
        default=str(MOTOR_ROOT),
        help="raiz del repo a auditar (default: raiz del motor resuelta desde este script)",
    )
    args = parser.parse_args(argv)

    root = Path(args.motor_root).resolve()

    try:
        if not root.is_dir():
            raise ToolError(f"--motor-root no existe: {root}")
        assert_git_repo(root)
    except ToolError as exc:
        print(f"[archive-schema-guard] ERROR DE HERRAMIENTA: {exc}", file=sys.stderr)
        return EXIT_TOOL_ERROR

    print(f"[archive-schema-guard] repo: {root}")

    archive_files = find_archive_files(root)
    if not archive_files:
        print(
            "[archive-schema-guard] OK: 0 archive file(s) "
            f"({ARCHIVE_DIR_REL.as_posix()}/observations.*.jsonl) -- sin memoria "
            "portable que validar. Un repo_destino fresco no tiene memoria "
            "todavia; esto NO es un hallazgo de schema."
        )
        return EXIT_OK

    # Import diferido, y en la forma `from scripts.validate_observations import
    # validate_file` (no `from scripts import validate_observations`): el
    # detector de check_guard_wiring.py casa el segmento MODULO del
    # ImportFrom, y solo esta forma deja "validate_observations" como modulo.
    from scripts.validate_observations import validate_file

    all_errors: list[str] = []
    for path in archive_files:
        success, errors = validate_file(path, strict=True)
        if not success:
            all_errors.extend(f"{path}: {err}" for err in errors)

    if all_errors:
        print(
            f"[archive-schema-guard] HALLAZGO: {len(all_errors)} error(es) de schema "
            f"en {len(archive_files)} archive file(s):"
        )
        for err in all_errors:
            print(f"[archive-schema-guard]   - {err}", file=sys.stderr)
        print(
            "[archive-schema-guard] Corrige el schema de las entradas listadas "
            "(ver skills/_shared/ap-schema.md) antes de commitear/pushear."
        )
        return EXIT_SCHEMA_INVALID

    collisions = find_identity_collisions(archive_files)
    if collisions:
        print(
            f"[archive-schema-guard] COLISION DE IDENTIDAD: {len(collisions)} clave(s) "
            "(topic, source_ticket) con lecciones DISTINTAS que el dedup fusionaria:"
        )
        for (topic, ticket), fps in sorted(collisions.items()):
            print(
                f"[archive-schema-guard]   - {topic} | {ticket} | "
                f"{len(fps)} lecciones distintas bajo la misma clave",
                file=sys.stderr,
            )
        print(
            "[archive-schema-guard] DECISION HUMANA: son re-ediciones de la MISMA "
            "leccion (fusiona/borra una) o lecciones DISTINTAS del mismo ticket "
            "(anade la clave a ACCEPTED_COLLISIONS)? El dedup del reconciliador "
            "perderia una en silencio; por eso se bloquea (ver WOT-2026-038n)."
        )
        return EXIT_IDENTITY_COLLISION

    print(
        f"[archive-schema-guard] OK: {len(archive_files)} archive file(s) validos "
        "contra el schema (0 colisiones de identidad no revisadas)."
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
