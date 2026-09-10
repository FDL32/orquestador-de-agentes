"""WOT-2026-067m: retencion de `orchestrator_pipeline/arranques/` por CITACION (DEC-067L-001).

CAUSA RAIZ medible: la carpeta crece sin tope, sin rotacion y sin criterio de
retirada (115 ficheros, 2.0 MB, TODOS versionados el 2026-09-10; +11 en dos dias).
La unica politica que la gobernaba (`arranques/README.md`) defiende NO podar por la
*brecha de citacion* (publicar `backlog.md` citando evidencia no publicada). Ese
argumento protege a los ficheros CITADOS; medido, son 27 de 114. Para los otros 87
la brecha no aplica.

CRITERIO (DEC-067L-001): se CONSERVA en la raiz lo CITADO desde cualquiera de las
TRES superficies publicadas -- `backlog.md` vivo, `_archive/backlog_done.md` y los
mensajes de commit publicados (`git log --format=%s%n%b`). Los NO citados se MUEVEN a
`arranques/_archive/`. NO es un tope numerico por recencia: esa via ([A]) esta
REFUTADA por medicion (varios de los 27 citados son ANTIGUOS y saldrian de la raiz).

SE MUEVE, JAMAS SE BORRA. El patron de la casa es mover a un hermano (`_drained/`,
`_retired/`, `collaboration/archive/`). Nada se borra ni se desversiona.

INDICE = BARRERA (DEC-067L-002): cada movido deja una fila (nombre, fecha, sha256,
motivo) en `_archive/INDEX.md`; el cuadre en AMBAS direcciones lo verifica
`scripts/check_arranques_index.py`, cableado en `scripts/prepush_check.py`
(`run_arranques_index_check`). `archive()` invoca ese mismo guard tras cada mudanza
(defensa: nunca deja un estado a medio indexar).

METODO del censo: un fichero esta CITADO si su stem (nombre sin `.md`) aparece como
SUBSTRING en la union de las tres superficies. Medido 2026-09-10: stem substring ->
27/87; con frontera de palabra -> 26/88. El substring es la variante CONSERVADORA
(un falso-CITADO solo conserva de mas; el falso-NO-CITADO moveria evidencia citada),
y es la que el contrato fija.

Docstring-as-spec:
  Before: `project_root` es un repo_destino con `orchestrator_pipeline/arranques/`
      y, para el `git log`, un arbol git con `.git` PROPIO (hermetico: sin el, el
      walk-up alcanzaria otro repo). `git` debe estar en PATH.
  During: lee las dos colas publicadas (read-only), ejecuta `git -C <root> log`
      (fail-closed: sin git o con rc != 0 ABORTA, porque un censo incompleto
      moveria evidencia). Clasifica y, salvo `--dry-run`, MUEVE los no citados a
      `_archive/` y anade su fila al INDEX.
  After: devuelve un reporte con el DENOMINADOR y las dos listas. `main()` publica
      el denominador SIEMPRE (un `exit 0` con denominador 0 es verde vacuo) y
      devuelve 0 con exito, 1 si `archive()` detecta un INDEX inconsistente, 2 si
      la invocacion no midio (falta el tree/dir, git ausente).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from check_arranques_index import (  # noqa: E402
    ARCHIVE_DIRNAME,
    INDEX_FILENAME,
    check_index_consistency,
)


ARRANQUES_REL = Path("orchestrator_pipeline") / "arranques"
README_NAME = "README.md"
MOTIVO = (
    "no citado desde backlog.md vivo, _archive/backlog_done.md ni mensajes de "
    "commit publicados (DEC-067L-001)"
)
_BACKLOG_SURFACES = (
    Path(".agent") / "collaboration" / "backlog.md",
    Path(".agent") / "collaboration" / "_archive" / "backlog_done.md",
)
_INDEX_HEADER = (
    "# Indice de `arranques/_archive/` (WOT-2026-067m)\n"
    "\n"
    "Historico NO CITADO movido desde la raiz de `arranques/` por `DEC-067L-001`.\n"
    "La raiz conserva lo CITADO desde `backlog.md` vivo, `_archive/backlog_done.md`\n"
    "o mensajes de commit publicados. Se MUEVE, jamas se borra: todo lo movido\n"
    "conserva su ruta original aqui, asi que revertir es mover de vuelta.\n"
    "\n"
    "| Archivo | Fecha | SHA256 | Motivo |\n"
    "|---|---|---|---|\n"
)


class ArchiveError(RuntimeError):
    """Fallo de medicion o de mudanza; nunca se degrada a verde."""


@dataclass
class ArchiveReport:
    """Resultado de una corrida (dry-run o real), con el denominador publicado."""

    arranques_dir: Path
    denominator: int
    cited: list[str] = field(default_factory=list)
    uncited: list[str] = field(default_factory=list)
    moved: list[str] = field(default_factory=list)
    dry_run: bool = False
    index_path: Path | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "arranques_dir": str(self.arranques_dir),
            "denominator": self.denominator,
            "cited": list(self.cited),
            "uncited": list(self.uncited),
            "moved": list(self.moved),
            "dry_run": self.dry_run,
            "index_path": str(self.index_path) if self.index_path else None,
        }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def root_files(arranques_dir: Path) -> list[Path]:
    """Ficheros de la RAIZ de `arranques/`, excluidos README, INDEX y `_archive/`.

    `INDEX_FILENAME` se excluye por WOT-2026-067n: un `INDEX.md` en la RAIZ se
    clasificaria como archivable y la mudanza lo dejaria caer ENCIMA del indice
    de `_archive/` (o chocaria con el). No es un caso vivo, pero cuesta un token.
    """
    if not arranques_dir.is_dir():
        return []
    skip = {README_NAME, INDEX_FILENAME}
    return sorted(
        p for p in arranques_dir.iterdir() if p.is_file() and p.name not in skip
    )


def _git_log_surface(project_root: Path) -> str:
    """Mensajes de commit publicados, o ArchiveError (fail-closed, nunca vacio mudo)."""
    git = shutil.which("git")
    if not git:
        raise ArchiveError(
            "git no esta en PATH: no se puede leer la superficie de mensajes de "
            "commit; se aborta para no mover evidencia citada."
        )
    proc = subprocess.run(  # noqa: S603
        # `--all`: sin el, `git log` solo alcanza HEAD, y un arranque citado unicamente
        # desde una rama o tag NO fusionado se clasificaria NO-CITADO y se moveria
        # (WOT-2026-067n). Medido el 2026-09-10 en el destino: `--all --not HEAD` da
        # VACIO -- el riesgo es LATENTE, no vivo, pero el coste de cerrarlo es una
        # palabra y el fallo que evita es perdida de evidencia.
        [git, "-C", str(project_root), "log", "--all", "--format=%s%n%b"],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if proc.returncode != 0:
        raise ArchiveError(
            f"git log fallo en {project_root} (rc={proc.returncode}): "
            f"{proc.stderr.strip()[:200]}. Se aborta: un censo incompleto moveria "
            "evidencia citada."
        )
    return proc.stdout


def load_citation_blob(project_root: Path) -> str:
    """Union de las TRES superficies publicadas de citacion."""
    parts: list[str] = []
    # WOT-2026-067n: la superficie VIVA es obligatoria. Saltarla en silencio dejaba
    # el censo incompleto y podia mover evidencia citada -- justo lo que la rama de
    # `git log` ya trataba como fail-closed. `backlog_done.md` SI puede faltar
    # legitimamente (destino sin ningun ticket archivado todavia).
    live = project_root / _BACKLOG_SURFACES[0]
    if not live.is_file():
        raise ArchiveError(
            f"superficie de citacion VIVA ausente: {live}. Se aborta: un censo "
            "incompleto moveria evidencia citada (DEC-067L-001)."
        )
    for rel in _BACKLOG_SURFACES:
        path = project_root / rel
        if path.is_file():
            parts.append(path.read_text(encoding="utf-8", errors="replace"))
    parts.append(_git_log_surface(project_root))
    return "\n".join(parts)


def classify(arranques_dir: Path, blob: str) -> tuple[list[Path], list[Path]]:
    """(citados, no citados) por SUBSTRING del stem en el blob de superficies."""
    cited: list[Path] = []
    uncited: list[Path] = []
    for path in root_files(arranques_dir):
        key = path.stem if path.suffix == ".md" else path.name
        (cited if key in blob else uncited).append(path)
    return cited, uncited


def append_index_rows(index_path: Path, rows: tuple[str, ...]) -> None:
    """Anade filas al INDEX; crea cabecera si el fichero no existe todavia."""
    prefix = "" if index_path.exists() else _INDEX_HEADER
    existing = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    index_path.write_text(prefix + existing + "".join(rows), encoding="utf-8")


def archive(
    project_root: Path, *, dry_run: bool = False, today: str | None = None
) -> ArchiveReport:
    """Clasifica y (salvo dry-run) mueve los NO citados, indexa y verifica."""
    project_root = Path(project_root)
    arranques_dir = project_root / ARRANQUES_REL
    files = root_files(arranques_dir)
    blob = load_citation_blob(project_root)
    cited, uncited = classify(arranques_dir, blob)

    report = ArchiveReport(
        arranques_dir=arranques_dir,
        denominator=len(files),
        cited=[p.name for p in cited],
        uncited=[p.name for p in uncited],
        dry_run=dry_run,
    )
    if dry_run or not uncited:
        return report

    archive_dir = arranques_dir / ARCHIVE_DIRNAME
    archive_dir.mkdir(exist_ok=True)
    index_path = archive_dir / INDEX_FILENAME
    report.index_path = index_path
    stamp = today or date.today().isoformat()

    # WOT-2026-067n: PLAN COMPLETO antes de mover un solo byte. Comprobar la
    # colision DENTRO del bucle de mudanza dejaba mudanza PARCIAL -- los ficheros
    # anteriores ya movidos y `append_index_rows` sin llegar a correr, porque el
    # `raise` cortaba antes. Ese es justo el estado que el guard declara imposible
    # ("el `_archive/` nace CONSISTENTE"), asi que la premisa era falsa en la ruta
    # de excepcion. Validar primero hace la operacion todo-o-nada por construccion.
    plan: list[tuple[Path, Path, str]] = []
    collisions: list[str] = []
    for path in uncited:
        destination = archive_dir / path.name
        if destination.exists():
            collisions.append(path.name)
            continue
        plan.append((path, destination, sha256_file(path)))
    if collisions:
        raise ArchiveError(
            f"colision: {', '.join(sorted(collisions))} ya existe(n) en "
            f"{archive_dir}; no se sobrescribe historico. NADA se ha movido."
        )

    rows: list[str] = []
    for path, destination, digest in plan:
        shutil.move(str(path), str(destination))
        rows.append(f"| {path.name} | {stamp} | {digest} | {MOTIVO} |\n")
        report.moved.append(path.name)

    append_index_rows(index_path, tuple(rows))

    findings = check_index_consistency(arranques_dir)
    if findings:
        raise ArchiveError(
            "INDEX inconsistente tras la mudanza: " + "; ".join(findings)
        )
    return report


def _print_report(report: ArchiveReport, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(report.as_dict()))
        return
    accion = "DRY-RUN" if report.dry_run else "MUDANZA"
    print(f"[arranques-archive] {accion}")
    print(
        f"[arranques-archive] denominador: {report.denominator} "
        "fichero(s) inspeccionado(s)"
    )
    print(
        f"[arranques-archive] CITADOS: {len(report.cited)} | "
        f"NO CITADOS: {len(report.uncited)}"
    )
    for name in report.cited:
        print(f"  CITADO    {name}")
    for name in report.uncited:
        print(f"  NO-CITADO {name}")
    if not report.dry_run:
        print(
            f"[arranques-archive] movidos: {len(report.moved)} -> {report.index_path}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Clasifica arranques/ por CITACION (DEC-067L-001), publica el "
            "denominador y MUEVE los no citados a _archive/ con su fila en INDEX.md."
        )
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        required=True,
        help="repo_destino cuyo orchestrator_pipeline/arranques/ se retiene.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Clasifica y publica el denominador SIN mover ni escribir nada.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emitir el reporte en JSON (machine-readable).",
    )
    args = parser.parse_args(argv)

    arranques_dir = Path(args.project_root) / ARRANQUES_REL
    if not arranques_dir.is_dir():
        print(
            f"ERROR: no existe {arranques_dir}; nada que clasificar.",
            file=sys.stderr,
        )
        return 2

    try:
        report = archive(Path(args.project_root), dry_run=args.dry_run)
    except ArchiveError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if report.denominator == 0:
        print(
            "[arranques-archive] denominador: 0 fichero(s) inspeccionado(s) -- "
            "VERDE VACUO, no cuenta.",
            file=sys.stderr,
        )
        return 1

    _print_report(report, as_json=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
