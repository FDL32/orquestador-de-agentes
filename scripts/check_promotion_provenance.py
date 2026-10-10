#!/usr/bin/env python3
"""Guard: PROCEDENCIA de las entradas del archive (WOT-2026-041g).

Before (Pre-condiciones):
    - `--motor-root` (opcional) debe ser la raiz (toplevel) de un checkout git;
      por defecto es la raiz del motor resuelta desde `Path(__file__)`.
    - No requiere `--project-root` obligatorio: el hook de pre-commit no pasa
      `args:`, asi que el default debe bastar por si solo.

During (Proceso y Recursos):
    - Resuelve la raiz, valida que sea git toplevel (mismo patron que
      `check_portable_memory_archive_schema.py`).
    - Glob de `.agent/runtime/memory/archive/observations.*.jsonl` bajo esa
      raiz (`ARCHIVE_DIR_REL`, mismo patron que los guards existentes).
    - Para CADA entrada en CADA archivo del archive:
        * si falta el campo `promoted_via` -> FINDING (nombra `id` o
          `record_key` si no tiene id, y `fichero:linea`);
        * si `promoted_via` no esta en PROMOTED_VIA_ACCEPTED -> FINDING;
    - No escribe nada; no muta el arbol.

After (Post-condiciones y Errores):
    - Exit 0: todas las entradas de todos los archive files tienen
      `promoted_via` en el conjunto aceptado, O NO se encontro ningun
      archive file.
    - Exit 1: fallo de la HERRAMIENTA (root no es git, root no existe,
      archivo ilegible). No es un hallazgo sobre el contenido.
    - Exit 4: HALLAZGO -- al menos una entrada carece de `promoted_via` o
      tiene un valor no aceptado. Imprime los findings linea a linea.
    - Exit 5: el archive no parsea (JSON corrupto -> nomina `fichero:linea`).

Uso:
    python scripts/check_promotion_provenance.py [--motor-root <repo>]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


MOTOR_ROOT = Path(__file__).resolve().parent.parent

# Bootstrap: motor root on sys.path so imports from scripts/ resolve both when
# this script runs directly and when imported from elsewhere.
if str(MOTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(MOTOR_ROOT))

from scripts.reconcile_portable_memory import PROMOTED_VIA_ACCEPTED  # noqa: E402


ARCHIVE_DIR_REL = Path(".agent/runtime/memory/archive")

EXIT_OK = 0
EXIT_TOOL_ERROR = 1
EXIT_PROVENANCE_INVALID = 4
EXIT_JSON_CORRUPT = 5


class ToolError(Exception):
    """Fallo de la HERRAMIENTA (exit 1), distinto de un hallazgo (exit 4)."""


def assert_git_repo(root: Path) -> None:
    """`root` debe ser la RAIZ (toplevel) de un checkout/worktree git."""
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
    """Archive files trackeados (glob del arbol vivo, no del argv)."""
    archive_dir = root / ARCHIVE_DIR_REL
    if not archive_dir.is_dir():
        return []
    return sorted(archive_dir.glob("observations.*.jsonl"))


def _record_key(rec: dict) -> tuple:
    """Clave de dedup: (topic, source_ticket)."""
    return (rec.get("topic", ""), rec.get("source_ticket", ""))


def main(argv: list[str] | None = None) -> int:  # noqa: C901
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
        print(
            f"[promotion-provenance-guard] ERROR DE HERRAMIENTA: {exc}", file=sys.stderr
        )
        return EXIT_TOOL_ERROR

    print(f"[promotion-provenance-guard] repo: {root}")

    archive_files = find_archive_files(root)
    if not archive_files:
        print(
            "[promotion-provenance-guard] OK: 0 archive file(s) "
            f"({ARCHIVE_DIR_REL.as_posix()}/observations.*.jsonl) -- sin memoria "
            "portable que validar. Un repo_destino fresco no tiene memoria "
            "todavia; esto NO es un hallazgo de procedencia."
        )
        return EXIT_OK

    all_findings: list[str] = []
    json_errors: list[str] = []

    for path in archive_files:
        lines = path.read_text(encoding="utf-8").splitlines()
        for line_num, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                json_errors.append(f"{path}:{line_num}: JSON corrupto")
                continue

            promoted_via = rec.get("promoted_via")
            if promoted_via is None:
                # Nombra el id o el record_key si no hay id.
                rec_id = rec.get("id")
                if rec_id:
                    identifier = f"id={rec_id}"
                else:
                    rk = _record_key(rec)
                    identifier = f"record_key=({rk[0]!r},{rk[1]!r})"
                all_findings.append(
                    f"{path}:{line_num}: entrada {identifier} falta promoted_via"
                )
            elif promoted_via not in PROMOTED_VIA_ACCEPTED:
                rec_id = rec.get("id", "sin-id")
                all_findings.append(
                    f"{path}:{line_num}: entrada {rec_id} promoted_via={promoted_via!r} "
                    f"no esta en {PROMOTED_VIA_ACCEPTED!r}"
                )

    if json_errors:
        print(
            f"[promotion-provenance-guard] JSON CORRUPTO en {len(json_errors)} linea(s):"
        )
        for err in json_errors:
            print(f"[promotion-provenance-guard]   - {err}", file=sys.stderr)
        return EXIT_JSON_CORRUPT

    if all_findings:
        print(
            f"[promotion-provenance-guard] HALLAZGO: {len(all_findings)} entrada(s) "
            f"sin procedencia valida en {len(archive_files)} archive file(s):"
        )
        for finding in all_findings:
            print(f"[promotion-provenance-guard]   - {finding}", file=sys.stderr)
        print(
            "[promotion-provenance-guard] Corre la procedencia con el backfill "
            "(`scripts/backfill_promoted_via.py --apply`) antes de commitear."
        )
        return EXIT_PROVENANCE_INVALID

    print(
        f"[promotion-provenance-guard] OK: {len(archive_files)} archive file(s) validos, "
        f"todas las entradas declaran promoted_via aceptado."
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
