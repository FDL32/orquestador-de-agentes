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

    print(
        f"[archive-schema-guard] OK: {len(archive_files)} archive file(s) validos "
        "contra el schema."
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
