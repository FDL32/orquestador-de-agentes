"""WOT-2026-067m: retencion de `orchestrator_pipeline/arranques/` por CITACION (DEC-067L-001).

CAUSA RAIZ medible: la carpeta crece sin tope, sin rotacion y sin criterio de
retirada (115 ficheros, 2.0 MB, TODOS versionados el 2026-09-10; +11 en dos dias).
La unica politica que la gobernaba (`arranques/README.md`) defiende NO podar por la
*brecha de citacion* (publicar `backlog.md` citando evidencia no publicada). Ese
argumento protege a los ficheros CITADOS; medido, son 27 de 114. Para los otros 87
la brecha no aplica.

CRITERIO (DEC-067L-001): se CONSERVA en la raiz lo CITADO desde cualquiera de las
TRES superficies publicadas -- `backlog.md` vivo, `_archive/backlog_done.md` y los
mensajes de commit publicados (`git log --format=%s%n%b`). Los NO citados se
proponen para `arranques/_archive/`; la aplicacion la hace `p7_retire
--apply-retire`. NO es un tope numerico por recencia: esa via ([A]) esta
REFUTADA por medicion (varios de los 27 citados son ANTIGUOS y saldrian de la raiz).

Este modulo solo propone y nunca mueve ni borra. La aplicacion aprobada se delega
a P7, que conserva la evidencia bajo su propio contrato.

INDICE = BARRERA (DEC-067L-002): cada movido deja una fila (nombre, fecha, sha256,
motivo) en `_archive/INDEX.md`; el cuadre en AMBAS direcciones lo verifica
`scripts/check_arranques_index.py`, cableado en `scripts/prepush_check.py`
(`run_arranques_index_check`). La propuesta deja el INDEX intacto; P7 aplica la
retirada aprobada.

WOT-2026-161n: proponente de archivado; aplicacion via `p7_retire --apply-retire`.

METODO del censo: un fichero esta CITADO si su stem (nombre sin `.md`) aparece como
SUBSTRING en la union de las tres superficies. Medido 2026-09-10: stem substring ->
27/87; con frontera de palabra -> 26/88. El substring es la variante CONSERVADORA
(un falso-CITADO solo conserva de mas; el falso-NO-CITADO moveria evidencia citada),
y es la que el contrato fija.

GUARDA DE TRABAJO ACTIVO (WOT-2026-089p, 2026-10-08): un NO-CITADO no es sinonimo de
MUERTO. Medido en vivo: un bucle de gobierno de la MISMA sesion que revela este hueco
clasifico como NO-CITADO el prompt de arranque ACTIVO (`ARRANQUE_closeout_preflight_v3.md`)
y una propuesta recien aprobada (`PROPUESTA_..._v4_familias.md`) -- ninguno de los dos
esta citado desde backlog/commits todavia porque la sesion que los escribio no habia
cerrado. Cablear la ejecucion periodica (ver abajo) sin esta guarda archivaria trabajo en
curso. Un NO-CITADO solo es ARCHIVABLE si pasa AMBAS comprobaciones:
  (a) no aparece en `git status --porcelain` del `project_root` (ni untracked ni modified)
  (b) su mtime es mas antiguo que `MIN_AGE_DAYS` (ver abajo)
Fallar (a) o (b) lo deja en una tercera categoria, SKIPPED (no CITADO, no ARCHIVADO), que
se imprime por separado para que el operador vea que sigue en la raiz y por que.

Docstring-as-spec:
  Before: `project_root` es un repo_destino con `orchestrator_pipeline/arranques/`
      y, para el `git log`/`git status`, un arbol git con `.git` PROPIO (hermetico:
      sin el, el walk-up alcanzaria otro repo). `git` debe estar en PATH.
  During: lee las dos colas publicadas (read-only), ejecuta `git -C <root> log`
      (fail-closed: sin git o con rc != 0 ABORTA, porque un censo incompleto
      moveria evidencia). Clasifica en CITADO / SKIPPED (sucio o reciente) / ARCHIVABLE
      y construye una propuesta P7 con ruta relativa y hash actual.
  After: devuelve un reporte con el DENOMINADOR, las listas y la propuesta.
      `main()` devuelve 0 cuando hay 0 archivables con denominador > 0 ("nada
      que proponer"); 1 si el denominador es 0 (VERDE VACUO) o si falla el censo
      o la validacion; 2 si falta el directorio arranques/.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path


_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.flight.p7_common import (  # noqa: E402
    MIN_AGE_DAYS,
    MIN_AGE_SECONDS,
    ArchiveError,
    assert_no_link_ancestors,
    git_dirty_names,
    is_reparse_or_link,
    root_files,
    sha256_file,
)


ARRANQUES_REL = Path("orchestrator_pipeline") / "arranques"
README_NAME = "README.md"
# WOT-2026-089p: un NO-CITADO con menos de MIN_AGE_DAYS de antiguedad se trata como
# trabajo en curso, no como historico. 7 dias cubre con margen una sesion larga que se
# retome tras el fin de semana sin haber cerrado todavia.
_BACKLOG_SURFACES = (
    Path(".agent") / "collaboration" / "backlog.md",
    Path(".agent") / "collaboration" / "_archive" / "backlog_done.md",
)


@dataclass
class ArchiveReport:
    """Resultado de una corrida (dry-run o real), con el denominador publicado.

    `uncited` = `skipped` + `archivable` (WOT-2026-089p): se conserva por
    compatibilidad con consumidores que solo distinguian CITADO/NO-CITADO antes de
    la guarda de trabajo activo; el desglose nuevo vive en los dos campos separados.
    """

    arranques_dir: Path
    denominator: int
    cited: list[str] = field(default_factory=list)
    uncited: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    archivable: list[str] = field(default_factory=list)
    moved: list[str] = field(default_factory=list)
    dry_run: bool = False
    index_path: Path | None = None
    proposal: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "arranques_dir": str(self.arranques_dir),
            "denominator": self.denominator,
            "cited": list(self.cited),
            "uncited": list(self.uncited),
            "skipped": list(self.skipped),
            "archivable": list(self.archivable),
            "moved": list(self.moved),
            "dry_run": self.dry_run,
            "index_path": str(self.index_path) if self.index_path else None,
            "proposal": list(self.proposal),
        }


def validate_proposal(entries: list[dict[str, str]], project_root: Path) -> None:
    """Validate a non-empty P7 proposal against the current project tree.

    Before: ``entries`` contains relative paths and current hashes.
    During: reject malformed schemas, links, unsafe paths, and stale hashes.
    After: return only when every entry names the current regular file.
    """
    if not entries:
        raise ArchiveError("la propuesta esta vacia")
    root = Path(project_root)
    for entry in entries:
        if set(entry) != {"rel", "sha256"}:
            raise ArchiveError("cada entrada debe contener exactamente rel y sha256")
        rel = entry.get("rel")
        digest = entry.get("sha256")
        if not rel or not digest:
            raise ArchiveError("la propuesta requiere rel y sha256 no vacios")
        assert_no_link_ancestors(root, rel)
        path = root / Path(rel)
        if is_reparse_or_link(path) or not path.is_file():
            raise ArchiveError(f"entrada propuesta ausente o enlace: {rel}")
        if sha256_file(path) != digest:
            raise ArchiveError(f"hash de propuesta no coincide: {rel}")


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


_git_dirty_names = git_dirty_names


def classify(
    arranques_dir: Path,
    blob: str,
    *,
    dirty_names: set[str] | None = None,
    now: float | None = None,
    min_age_seconds: int = MIN_AGE_SECONDS,
) -> tuple[list[Path], list[Path], list[Path]]:
    """(citados, skipped, archivables).

    `dirty_names` es opcional por compatibilidad con llamadas read-only que no
    necesitan la guarda (p.ej. un censo que solo cuenta CITADO/NO-CITADO sin
    pretender mover nada). Cuando es `None`, NINGUN NO-CITADO pasa a `archivables`
    (todos quedan `skipped`) -- fail-closed: sin saber que esta sucio, no se mueve
    nada, nunca se asume limpio por omision.
    """
    cited: list[Path] = []
    skipped: list[Path] = []
    archivables: list[Path] = []
    reference_time = now if now is not None else time.time()
    for path in root_files(arranques_dir):
        key = path.stem if path.suffix == ".md" else path.name
        if key in blob:
            cited.append(path)
            continue
        if dirty_names is None or path.name in dirty_names:
            skipped.append(path)
            continue
        age_seconds = reference_time - path.stat().st_mtime
        if age_seconds < min_age_seconds:
            skipped.append(path)
            continue
        archivables.append(path)
    return cited, skipped, archivables


def archive(
    project_root: Path,
    *,
    dry_run: bool = False,
    today: str | None = None,
    min_age_seconds: int = MIN_AGE_SECONDS,
) -> ArchiveReport:
    """Clasifica y propone los ARCHIVABLE para retirada posterior por P7.

    WOT-2026-089p: ya NO mueve todo lo NO-CITADO. Un NO-CITADO sucio (en `git
    status --porcelain`) o reciente (`mtime` dentro de `min_age_seconds`) se
    reporta como `skipped`, no como `archivable` -- la guarda que evita mover
    trabajo en curso de una sesion todavia abierta. `min_age_seconds` es
    inyectable para tests (fixtures que commitean justo antes de llamar y cuyo
    `mtime` es "ahora" por construccion); el CLI real siempre usa el default.
    """
    project_root = Path(project_root)
    arranques_dir = project_root / ARRANQUES_REL
    files = root_files(arranques_dir)
    blob = load_citation_blob(project_root)
    dirty_names = _git_dirty_names(project_root)
    cited, skipped, archivable = classify(
        arranques_dir, blob, dirty_names=dirty_names, min_age_seconds=min_age_seconds
    )

    report = ArchiveReport(
        arranques_dir=arranques_dir,
        denominator=len(files),
        cited=[p.name for p in cited],
        uncited=[p.name for p in skipped] + [p.name for p in archivable],
        skipped=[p.name for p in skipped],
        archivable=[p.name for p in archivable],
        dry_run=dry_run,
    )
    if dry_run or not archivable:
        return report

    report.proposal = [
        {
            "rel": path.relative_to(project_root).as_posix(),
            "sha256": sha256_file(path),
        }
        for path in archivable
    ]
    validate_proposal(report.proposal, project_root)
    return report


def _print_report(report: ArchiveReport, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(report.as_dict()))
        return
    accion = "DRY-RUN" if report.dry_run else "PROPUESTA P7"
    print(f"[arranques-archive] {accion}")
    print(
        f"[arranques-archive] denominador: {report.denominator} "
        "fichero(s) inspeccionado(s)"
    )
    print(
        f"[arranques-archive] CITADOS: {len(report.cited)} | "
        f"NO CITADOS: {len(report.uncited)} (SKIPPED: {len(report.skipped)} | "
        f"ARCHIVABLE: {len(report.archivable)})"
    )
    for name in report.cited:
        print(f"  CITADO     {name}")
    for name in report.skipped:
        print(f"  SKIPPED    {name}  (sucio o <{MIN_AGE_DAYS}d, trabajo en curso)")
    for name in report.archivable:
        print(f"  ARCHIVABLE {name}")
    for entry in report.proposal:
        print(f"  PROPUESTA  {entry['rel']}  {entry['sha256']}")
    if not report.proposal:
        print("[arranques-archive] nada que proponer")


def main(argv: list[str] | None = None) -> int:
    """CLI del proponente de archivado P7 (WOT-2026-161n).

    Before: recibe --project-root de un arbol git hermetico; flags --dry-run/--json.
    During: clasifica arranques/, emite la propuesta P7 e imprime el reporte.
    After: rc 0 si hay 0 archivables con denominador > 0 ("nada que proponer");
        rc 1 si denominador == 0 (VERDE VACUO) o si falla el censo/validacion;
        rc 2 si falta el directorio orchestrator_pipeline/arranques/.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Clasifica arranques/ por CITACION (DEC-067L-001) y propone retirada "
            "via p7_retire --apply-retire (WOT-2026-161n)."
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
