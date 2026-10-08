"""WOT-2026-089p: purga por TTL de `orchestrator_pipeline/arranques/_archive/`.

CAMBIO DE POLITICA DELIBERADO sobre `DEC-067L-001` ("SE MUEVE, JAMAS SE BORRA"). Esa
regla protegia contra la *brecha de citacion* en el momento del archivado: mover un
NO-CITADO no debia perder evidencia que un commit publicado pudiera citar despues. El
TTL de este modulo NO reabre esa decision -- actua SOLO sobre lo que ya lleva
`TTL_DAYS` en `_archive/` SIN haber sido re-citado en ese tiempo. Decision del
usuario (2026-10-08): tras ese plazo, el coste de conservar el fichero supera el
riesgo de perder evidencia que, de haber sido citada, ya se habria usado.

POR QUE NO SE BORRA LA FILA DEL INDEX. Borrar la fila entera rompería la propiedad
de "el indice es lo que existio" y ademas `check_arranques_index.check_index_consistency`
fallaria (fichero ausente nombrado en una fila) si alguien purga sin tocar el indice a
la vez. En su lugar, la fila se EDITA IN-PLACE: la celda `Motivo` se sobreescribe con
`PURGADO <fecha>: <motivo original>`, preservando Archivo/Fecha/SHA256 intactos.
`check_index_consistency` se extiende (ver abajo) para no fallar sobre filas marcadas
PURGADO cuyo fichero ya no esta en disco -- es la UNICA excepcion legitima a la regla
"fila sin fichero = hallazgo".

RE-CITACION SIGUE PROTEGIDA: antes de purgar, se vuelve a cargar el mismo blob de
citacion que usa `archive_arranques.py` (backlog vivo + backlog archivado + TODOS los
commits). Un fichero en `_archive/` cuyo stem aparezca ahi (alguien lo citó DESPUES de
archivarlo) NO se purga aunque supere el TTL -- mismo principio de `DEC-067L-001`
aplicado a la segunda mitad del ciclo de vida.

Docstring-as-spec:
  Before: `project_root` es un repo_destino con `_archive/INDEX.md` ya existente
      (si no existe, SKIP, nada que purgar). `git` en PATH para el censo de
      re-citacion (fail-closed igual que `archive_arranques.py`).
  During: lee las filas del INDEX con fecha parseable; para cada una mas antigua
      que `ttl_days`, verifica re-citacion; si NO esta re-citado y el fichero
      sigue en disco, lo BORRA (`Path.unlink`) y reescribe su fila con el prefijo
      `PURGADO <hoy>:`. Salvo `--dry-run`.
  After: devuelve un reporte con el denominador (filas candidatas por edad), las
      re-citadas (protegidas), las purgadas y las ya purgadas antes (idempotente:
      una fila ya marcada PURGADO no se vuelve a tocar). Exit 0 siempre que la
      medicion se complete (purgar 0 ficheros es un resultado valido, no un fallo).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path


_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from archive_arranques import ArchiveError, load_citation_blob  # noqa: E402
from check_arranques_index import ARCHIVE_DIRNAME, INDEX_FILENAME  # noqa: E402


ARRANQUES_REL = Path("orchestrator_pipeline") / "arranques"
# WOT-2026-089p: decision del usuario, "dos o tres meses". 90 dias es el borde
# superior del rango dicho explicitamente, no un valor a mitad de camino inventado.
TTL_DAYS = 90
PURGE_PREFIX_RE = re.compile(r"^PURGADO \d{4}-\d{2}-\d{2}: ")


@dataclass
class PurgeReport:
    archive_dir: Path
    ttl_days: int
    denominator: int
    candidates: list[str] = field(default_factory=list)
    recited: list[str] = field(default_factory=list)
    purged: list[str] = field(default_factory=list)
    already_purged: list[str] = field(default_factory=list)
    already_missing: list[str] = field(default_factory=list)
    rejected_unsafe: list[str] = field(default_factory=list)
    dry_run: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "archive_dir": str(self.archive_dir),
            "ttl_days": self.ttl_days,
            "denominator": self.denominator,
            "candidates": list(self.candidates),
            "recited": list(self.recited),
            "purged": list(self.purged),
            "already_purged": list(self.already_purged),
            "already_missing": list(self.already_missing),
            "rejected_unsafe": list(self.rejected_unsafe),
            "dry_run": self.dry_run,
        }


def _parse_index_rows(index_path: Path) -> list[list[str]]:
    """Filas completas (4 celdas) de `INDEX.md`, en orden; [] si no existe."""
    if not index_path.exists():
        return []
    rows: list[list[str]] = []
    for line in index_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) != 4:
            continue
        first = cells[0]
        if not first or first.lower() == "archivo":
            continue
        if set(first) <= {"-", ":", " "}:
            continue
        rows.append(cells)
    return rows


def _row_is_purged(row: list[str]) -> bool:
    return bool(PURGE_PREFIX_RE.match(row[3]))


def _is_safe_archive_basename(name: str, archive_dir: Path) -> bool:
    """True si `name` es un basename simple que resuelve DENTRO de `archive_dir`.

    WOT-2026-089p, hallazgo de MANAGER_REVIEW (Codex, 2026-10-08): `name` viene de
    la celda 1 de un fichero MARKDOWN EDITABLE (`INDEX.md`), no de un listado de
    disco. `target = archive_dir / name` seguido de `unlink()` sin esta validacion
    permitiria que una fila corrupta o manipulada (`../../../etc/passwd`, una ruta
    absoluta, un separador de carpeta) borre un fichero FUERA de `_archive/`. Dos
    comprobaciones independientes, ambas obligatorias:
      (a) `name` no debe contener un separador de ruta (ni `/` ni `\\`) ni ser `..`
          -- rechaza el caso trivial sin tocar el filesystem.
      (b) el PATH RESUELTO de `archive_dir / name` debe tener a `archive_dir`
          resuelto como ancestro -- cierra el caso de symlinks o normalizaciones
          que (a) por si solo no cubre.
    """
    if not name or name in {".", ".."}:
        return False
    if "/" in name or "\\" in name:
        return False
    resolved_archive = archive_dir.resolve()
    resolved_target = (archive_dir / name).resolve()
    return resolved_target.parent == resolved_archive


def _row_age_days(row: list[str], *, today: date) -> int | None:
    """Edad en dias desde la Fecha de la fila, o None si no es parseable."""
    try:
        moved_on = datetime.strptime(row[1], "%Y-%m-%d").date()
    except ValueError:
        return None
    return (today - moved_on).days


def _resolve_candidate_row(
    row: list[str],
    *,
    archive_dir: Path,
    project_root: Path,
    dry_run: bool,
    blob_cache: dict[str, str | None],
) -> str:
    """Decide el outcome de UNA fila candidata (edad >= ttl_days, no PURGADO).

    WOT-2026-089p: extraido de `purge()` para mantener la complejidad baja y para
    que cada rama de decision (seguridad, re-citacion, ausencia previa) sea
    independientemente legible. `blob_cache` es un dict de 1 entrada usado como
    celda mutable para la carga perezosa de `load_citation_blob` compartida entre
    llamadas sucesivas del mismo `purge()`.

    Devuelve uno de: "unsafe", "recited", "dry_run", "already_missing", "purged".
    """
    name = row[0]
    if not _is_safe_archive_basename(name, archive_dir):
        # (Codex, MANAGER_REVIEW): una fila con una ruta peligrosa NUNCA se toca --
        # ni se borra, ni se marca PURGADO (eso ocultaria la fila corrupta misma).
        return "unsafe"
    if blob_cache["value"] is None:
        blob_cache["value"] = load_citation_blob(project_root)
    key = Path(name).stem if name.endswith(".md") else name
    if key in blob_cache["value"]:
        return "recited"
    if dry_run:
        return "dry_run"
    target = archive_dir / name
    if not target.exists():
        # (Codex, MANAGER_REVIEW): el fichero YA faltaba de disco (perdida previa,
        # ajena a esta corrida). Marcarlo PURGADO fabricaria un exito que nunca
        # ocurrio y ocultaria la inconsistencia real que el guard debe seguir viendo.
        return "already_missing"
    target.unlink()
    return "purged"


def purge(
    project_root: Path,
    *,
    ttl_days: int = TTL_DAYS,
    dry_run: bool = False,
    today: date | None = None,
) -> PurgeReport:
    """Purga ficheros de `_archive/` mas antiguos que `ttl_days` y sin re-citar."""
    project_root = Path(project_root)
    arranques_dir = project_root / ARRANQUES_REL
    archive_dir = arranques_dir / ARCHIVE_DIRNAME
    index_path = archive_dir / INDEX_FILENAME
    reference_date = today or date.today()

    report = PurgeReport(
        archive_dir=archive_dir, ttl_days=ttl_days, denominator=0, dry_run=dry_run
    )
    if not index_path.exists():
        return report

    rows = _parse_index_rows(index_path)
    blob_cache: dict[str, str | None] = {"value": None}

    updated_rows: list[list[str]] = []
    changed = False
    for row in rows:
        name = row[0]
        if _row_is_purged(row):
            report.already_purged.append(name)
            updated_rows.append(row)
            continue
        age = _row_age_days(row, today=reference_date)
        if age is None or age < ttl_days:
            updated_rows.append(row)
            continue
        report.denominator += 1
        report.candidates.append(name)
        outcome = _resolve_candidate_row(
            row,
            archive_dir=archive_dir,
            project_root=project_root,
            dry_run=dry_run,
            blob_cache=blob_cache,
        )
        if outcome == "unsafe":
            report.rejected_unsafe.append(name)
            updated_rows.append(row)
            continue
        if outcome == "recited":
            report.recited.append(name)
            updated_rows.append(row)
            continue
        if outcome == "dry_run":
            updated_rows.append(row)
            continue
        if outcome == "already_missing":
            report.already_missing.append(name)
            updated_rows.append(row)
            continue
        new_motivo = f"PURGADO {reference_date.isoformat()}: {row[3]}"
        updated_rows.append([row[0], row[1], row[2], new_motivo])
        report.purged.append(name)
        changed = True

    if changed and not dry_run:
        _rewrite_index(index_path, updated_rows)

    return report


def _rewrite_index(index_path: Path, rows: list[list[str]]) -> None:
    """Reescribe el INDEX preservando cabecera, con las filas actualizadas."""
    text = index_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    header_lines: list[str] = []
    for line in lines:
        header_lines.append(line)
        if line.strip().startswith("|---"):
            break
    header = "".join(header_lines)
    if not header.endswith("\n"):
        header += "\n"
    body = "".join(f"| {' | '.join(row)} |\n" for row in rows)
    index_path.write_text(header + body, encoding="utf-8")


def _print_report(report: PurgeReport, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(report.as_dict()))
        return
    accion = "DRY-RUN" if report.dry_run else "PURGA"
    print(f"[arranques-purge] {accion} (TTL={report.ttl_days}d)")
    print(
        f"[arranques-purge] denominador (candidatas por edad): {report.denominator} | "
        f"re-citadas (protegidas): {len(report.recited)} | "
        f"purgadas: {len(report.purged)} | "
        f"ya purgadas antes: {len(report.already_purged)}"
    )
    for name in report.recited:
        print(f"  PROTEGIDA (re-citada) {name}")
    for name in report.purged:
        print(f"  PURGADA               {name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Borra de arranques/_archive/ los ficheros con mas de --ttl-days desde "
            "su mudanza, salvo que hayan sido re-citados desde entonces. "
            "Edita su fila en INDEX.md con el prefijo PURGADO en vez de eliminarla."
        )
    )
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument(
        "--ttl-days",
        type=int,
        default=TTL_DAYS,
        help=f"Dias de retencion antes de purgar (default: {TTL_DAYS}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Clasifica y publica el denominador SIN borrar ni escribir nada.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    arranques_dir = Path(args.project_root) / ARRANQUES_REL
    if not arranques_dir.is_dir():
        print(f"ERROR: no existe {arranques_dir}; nada que purgar.", file=sys.stderr)
        return 2

    try:
        report = purge(
            Path(args.project_root), ttl_days=args.ttl_days, dry_run=args.dry_run
        )
    except ArchiveError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    _print_report(report, as_json=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
