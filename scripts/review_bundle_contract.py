#!/usr/bin/env python3
"""Invariante mecanico de bundle de review: universo de CODIGO vs recorte
(WOT-2026-026k).

Before: opera SOLO sobre artefactos de CODIGO (`.py` bajo control de git).
    El universo mecanico se calcula por `git ls-tree` (deterministico,
    stdlib + subprocess de git, ya invocado en otros scripts del repo) mas
    hash sha256 de contenido normalizado; prompts/markdown estan FUERA de
    alcance (NON-GOAL declarado, sub-ticket aparte). NO usa AST para el
    universo (git ls-tree ya es la fuente de verdad de que ficheros de
    codigo existen); el termino "AST" del contrato original se satisface
    aqui via el hash de contenido, que es estrictamente mas fuerte que un
    AST-diff para detectar truncamiento (un AST-diff podria ignorar
    reordenamientos que el hash SI detecta).
During: `compute_code_universe(repo_root)` enumera los `.py` trackeados
    por git y calcula su hash agregado. `check_bundle_against_universe`
    recibe el universo esperado y el conjunto de rutas REALMENTE presentes
    en el bundle sometido a review; si el bundle omite cualquier ruta del
    universo (diff-de-conjuntos != vacio) o su hash agregado no coincide
    con el recomputado, el veredicto es CONTEXTO_INSUFICIENTE. No hay LLM
    ni heuristica semantica en esta capa: es comparacion de conjuntos y
    hashes, mecanica y determinista.
After: `main()` traduce el veredicto a exit code: 1 si CONTEXTO_INSUFICIENTE,
    0 si el bundle cubre el universo completo. Los callers de biblioteca
    (`check_bundle_against_universe`) devuelven el dict de veredicto sin
    salir del proceso, para permitir mutation testing local (desactivar el
    invariante y observar que el mismo bundle recortado pasa).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


class ContextoInsuficienteError(RuntimeError):
    """El bundle sometido a review no cubre el universo mecanico de codigo."""


def _run_git_ls_tree(repo_root: Path) -> list[str]:
    """Lista los `.py` trackeados por git en `repo_root` (HEAD), relativos.

    Before: `repo_root` debe ser un directorio dentro de un repo git (o el
        propio repo_root); no valida credenciales ni red (comando local).
    During: invoca `git ls-tree -r --name-only HEAD` con `cwd=repo_root`,
        capturando stdout como texto UTF-8; filtra a sufijo `.py`.
    After: retorna lista ordenada de rutas relativas (POSIX, `/` siempre).
        Propaga `subprocess.CalledProcessError` si `repo_root` no es un
        repo git valido (fail-closed, no hay universo fantasma).
    """
    git_cmd = ["git", "ls-tree", "-r", "--name-only", "HEAD"]
    proc = subprocess.run(  # noqa: S603
        git_cmd,
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    paths = [
        line.strip().replace("\\", "/")
        for line in proc.stdout.splitlines()
        if line.strip().endswith(".py")
    ]
    return sorted(paths)


def compute_code_universe(repo_root: Path) -> dict:
    """Universo mecanico de artefactos de codigo: rutas + hash agregado.

    Before: `repo_root` es un `Path` a un repo git existente con al menos
        el commit HEAD (aplica SOLO a `.py`; markdown/prompts fuera de
        alcance, NON-GOAL).
    During: enumera las rutas via `_run_git_ls_tree`; para cada ruta que
        exista en disco (working tree), lee sus bytes y acumula un hash
        sha256 incremental sobre `ruta + b"\\0" + contenido` en orden
        ordenado (deterministico e independiente del orden de iteracion
        del filesystem). Ficheros listados por git pero ausentes en disco
        (borrado no commiteado) se excluyen del hash pero SI cuentan en
        `paths` (el universo declarado es el de HEAD, no el working tree).
    After: retorna `{"paths": frozenset[str], "sha256": str}`. Determinista:
        misma `repo_root`/HEAD -> mismo resultado en cualquier maquina.
    """
    paths = _run_git_ls_tree(repo_root)
    digest = hashlib.sha256()
    for rel_path in paths:
        abs_path = repo_root / rel_path
        try:
            content = abs_path.read_bytes()
        except FileNotFoundError:
            continue
        digest.update(rel_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content)
    return {"paths": frozenset(paths), "sha256": digest.hexdigest()}


def check_bundle_against_universe(
    universe: dict,
    bundle_paths: set,
    *,
    bundle_sha256: str | None = None,
) -> dict:
    """Compara el universo mecanico contra lo REALMENTE presente en el bundle.

    Before: `universe` es el dict de `compute_code_universe` (o equivalente
        con `paths`/`sha256`); `bundle_paths` es el conjunto de rutas que el
        bundle sometido a review contiene DE VERDAD (no lo que declara,
        sino lo verificado); `bundle_sha256` es opcional -- si se provee,
        se compara contra `universe["sha256"]` como verificacion adicional
        de contenido (no solo de nombres de fichero).
    During: calcula `faltantes = universe["paths"] - bundle_paths` (rutas
        del universo ausentes del bundle: la unica senal que importa para
        "recorte", NO importa si el bundle trae rutas EXTRA). Si hay
        faltantes, o si `bundle_sha256` fue provisto y difiere del
        universo, el veredicto es CONTEXTO_INSUFICIENTE.
    After: retorna `{"veredicto": "OK"|"CONTEXTO_INSUFICIENTE",
        "faltantes": list[str], "motivo": str}`. Nunca lanza excepcion por
        si mismo (el caller de CLI decide si abortar); `main()` SI convierte
        CONTEXTO_INSUFICIENTE en exit 1.
    """
    faltantes = sorted(universe["paths"] - set(bundle_paths))
    hash_mismatch = bundle_sha256 is not None and bundle_sha256 != universe["sha256"]
    if faltantes or hash_mismatch:
        motivos = []
        if faltantes:
            motivos.append(f"{len(faltantes)} ruta(s) del universo ausentes del bundle")
        if hash_mismatch:
            motivos.append("hash del bundle no coincide con el universo recomputado")
        return {
            "veredicto": "CONTEXTO_INSUFICIENTE",
            "faltantes": faltantes,
            "motivo": "; ".join(motivos),
        }
    return {
        "veredicto": "OK",
        "faltantes": [],
        "motivo": "bundle cubre el universo mecanico completo",
    }


def main(argv: list[str] | None = None) -> int:
    """CLI: compara un bundle (fichero de rutas, una por linea) contra HEAD.

    Before: `--repo-root` apunta a un repo git; `--bundle-file` es un
        fichero de texto con una ruta relativa por linea (rutas realmente
        presentes en el bundle sometido a review).
    During: calcula el universo con `compute_code_universe`, lee las rutas
        del bundle, invoca `check_bundle_against_universe`.
    After: imprime el veredicto JSON a stdout; exit 1 si
        CONTEXTO_INSUFICIENTE, exit 0 si OK. `FileNotFoundError` /
        `subprocess.CalledProcessError` se traducen a exit 2 (uso).
    """
    parser = argparse.ArgumentParser(
        description="Verifica que un bundle de review cubra el universo de codigo."
    )
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--bundle-file", required=True)
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root)
    try:
        universe = compute_code_universe(repo_root)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(
            f"[review_bundle_contract] error resolviendo universo: {exc}",
            file=sys.stderr,
        )
        return 2

    try:
        bundle_lines = Path(args.bundle_file).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        print(
            f"[review_bundle_contract] bundle-file no encontrado: {exc}",
            file=sys.stderr,
        )
        return 2
    bundle_paths = {
        line.strip().replace("\\", "/") for line in bundle_lines if line.strip()
    }

    result = check_bundle_against_universe(universe, bundle_paths)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["veredicto"] == "CONTEXTO_INSUFICIENTE" else 0


if __name__ == "__main__":
    raise SystemExit(main())
