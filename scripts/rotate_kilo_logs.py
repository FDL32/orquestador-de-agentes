"""WOT-2026-020s: rotacion/purga de logs Kilo (.agent/planning/**/*.log).

CAMBIO DE POLITICA DELIBERADO: los logs de streaming Kilo crecen indefinidamente
porque nadie los purga. Este modulo comprime logs viejos+inactivos, borra
comprimidos obsoletos, y protege logs de vuelos activos — siguiendo el patron de
archivos standalone con CLI argparse del motor.

Deteccion de inactividad: se basa UNICAMENTE en mtime (sin `time.sleep`).
  La condicion de "inactivo" es `mtime < now - compress_days`.
  Las dos mitigaciones REALES contra la condicion de carrera son los locks
  (`lock_alive_fn`) y la excepcion de vuelo activo (work_plan.md reciente
  sin veredicto terminal).

Docstring-as-spec:
  Before: `project_root` es un repo_destino con `.agent/planning/**/*.log`.
      `lock_alive_fn` comprueba si hay un proceso Kilo vivo. `now` permite
      inyectar hora para tests (si es None, usa datetime.now).
  During: recorre logs por antiguedad; si mtime > COMPRESS_DAYS y locks
      muertos y no hay vuelo activo -> comprime. Si .log.gz mtime >
      DELETE_DAYS -> purga.
  After: devuelve KiloLogReport con denominador, acciones y errores.
"""

from __future__ import annotations

import argparse
import contextlib
import gzip
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path


# Bootstrap: motor root must be on sys.path before importing scripts.closeout_steps.
# Necesario porque este modulo se invoca como subproceso standalone
# (`python <motor>/scripts/rotate_kilo_logs.py`), lo que pone `scripts/` --no su
# padre-- en sys.path[0]; sin esto, `from scripts.closeout_steps...` falla con
# ModuleNotFoundError pese a que el paquete existe (medido 2026-10-19).
_MOTOR_ROOT_BOOTSTRAP = Path(__file__).resolve().parent.parent
if str(_MOTOR_ROOT_BOOTSTRAP) not in sys.path:
    sys.path.insert(0, str(_MOTOR_ROOT_BOOTSTRAP))


# Umbrales canonicos (R13a)
KILO_LOG_COMPRESS_DAYS = 7
KILO_LOG_DELETE_DAYS = 30
KILO_LOG_INACTIVE_MINUTES = 10

# Lock TTL — debe coincidir con LOCK_TTL_MINUTES de session_closeout.py
LOCK_TTL_MINUTES = 15

# Veredictos terminales que cierran un vuelo
_TERMINAL_PATTERNS = re.compile(
    r"(?:builder_recibo|revisor_veredicto|manager_veredicto)_r\d+\.md$"
)

# Timestamp ISO8601 UTC (formato real de bitacoras)
_ISO_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


@dataclass
class KiloLogReport:
    """Reporte de rotacion de logs Kilo."""

    denominator: int = 0
    compressed: list[str] = field(default_factory=list)
    purged: list[str] = field(default_factory=list)
    protected_active_flight: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    dry_run: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "denominator": self.denominator,
            "compressed": list(self.compressed),
            "purged": list(self.purged),
            "protected_active_flight": list(self.protected_active_flight),
            "errors": list(self.errors),
            "dry_run": self.dry_run,
        }


def _load_lock_checker(project_root: Path):
    """Carga is_lock_alive de rotation.py por import dinamico.

    Devuelve una funcion is_lock_alive(lock_path, lock_ttl_minutes) -> bool
    que comprueba builder_lock.txt y supervisor_lock.txt.
    """
    from scripts.closeout_steps.rotation import is_lock_alive as _is_lock_alive

    def checker() -> bool:
        """True si AL MENOS un lock esta vivo."""
        runtime = project_root / ".agent" / "runtime"
        for lock_name in ("builder_lock.txt", "supervisor_lock.txt"):
            lock_path = runtime / lock_name
            if _is_lock_alive(lock_path, lock_ttl_minutes=LOCK_TTL_MINUTES):
                return True
        return False

    return checker


def _is_flight_active(log_path: Path, project_root: Path) -> bool:
    """Verifica si el vuelo asociado a este log esta activo.

    Dado un `.log` en directorio D, busca D/work_plan.md:
    - Si no existe work_plan.md -> NO activo (nada que proteger).
    - Si existe work_plan.md Y hay veredicto terminal (builder/recibo,
      revisor_veredicto, manager_veredicto) -> NO activo (vuelo cerrado).
    - Si existe work_plan.md SIN terminal Y mtime < 30 dias -> activo
      (protege el log aunque supere umbrales).
    - Si existe work_plan.md SIN terminal Y mtime > 30 dias -> abandonado
      (no protege, se permite purga).
    """
    log_dir = log_path.parent
    work_plan = log_dir / "work_plan.md"

    if not work_plan.exists():
        return False

    # Check for any terminal veredicto
    has_terminal = False
    for child in log_dir.iterdir():
        if _TERMINAL_PATTERNS.match(child.name):
            has_terminal = True
            break

    if has_terminal:
        return False

    # No terminal -> check mtime
    try:
        wp_mtime = datetime.fromtimestamp(work_plan.stat().st_mtime, tz=timezone.utc)
        cutoff = datetime.now(timezone.utc) - timedelta(days=KILO_LOG_DELETE_DAYS)
        # Reciente (< 30 dias) -> activo; viejo (> 30 dias) -> abandonado
        return wp_mtime >= cutoff
    except OSError:
        return False


def _compress_log(log_path: Path, dry_run: bool) -> str | None:
    """Comprime un log: renombra a .log.rotating, gzip, borra temporal.

    Retorna None si exito, o un mensaje de error si falla.
    """
    rotating = Path(str(log_path) + ".rotating")

    try:
        # Rename atomico
        log_path.rename(rotating)

        # Comprimir
        with (
            rotating.open("rb") as f_in,
            gzip.open(str(log_path) + ".gz", "wb") as f_out,
        ):
            while True:
                chunk = f_in.read(65536)
                if not chunk:
                    break
                f_out.write(chunk)

        # Borrar temporal si compression exito
        rotating.unlink()
        return None
    except Exception as exc:
        # Si falla, dejar .rotating (nunca perder el original)
        if rotating.exists():
            with contextlib.suppress(OSError):
                rotating.rename(log_path)
        return f"compression failed for {log_path}: {exc}"


def _purge_log_gz(
    log_path: Path,
    dry_run: bool,
    now: datetime | None = None,
) -> str | None:
    """Borra un .log.gz si tiene mtime > delete_days.

    Retorna None si exito o skip, o un mensaje de error si falla.
    """
    try:
        mtime = datetime.fromtimestamp(log_path.stat().st_mtime, tz=timezone.utc)
        current_now = now or datetime.now(timezone.utc)
        cutoff = current_now - timedelta(days=KILO_LOG_DELETE_DAYS)
        if mtime < cutoff:
            if dry_run:
                return "dry_run"
            log_path.unlink()
            return None
        return "too_recent"
    except OSError as exc:
        return f"os error: {exc}"


def _compress_candidates(
    planning_dir: Path,
    lock_alive_fn,
    compress_days: int,
    dry_run: bool,
    current_now: datetime,
    project_root: Path,
) -> dict[str, list[str]]:
    """Phase 1: comprima candidatos .log viejos+inactivos.

    Returns dict with keys: denominator, compressed, protected, errors.
    """
    result: dict[str, list[str]] = {
        "denominator": 0,
        "compressed": [],
        "protected": [],
        "errors": [],
    }
    log_files = sorted(planning_dir.rglob("*.log"))

    for log_path in log_files:
        # Skip .log.rotating (temporal de compresion)
        if log_path.name.endswith(".rotating"):
            continue

        result["denominator"] += 1

        # Check flight activity exception
        if _is_flight_active(log_path, project_root):
            result["protected"].append(str(log_path))
            continue

        # Check if locks are alive
        if lock_alive_fn():
            result["protected"].append(str(log_path))
            continue

        # Check mtime age
        try:
            mtime = datetime.fromtimestamp(log_path.stat().st_mtime, tz=timezone.utc)
            cutoff = current_now - timedelta(days=compress_days)
            if mtime >= cutoff:
                continue  # too recent
        except OSError as exc:
            result["errors"].append(f"stat failed {log_path}: {exc}")
            continue

        # Inactivity: mtime check is sufficient (no sleep).
        # Locks and active flight exception are the real mitigations.

        # Compress (skip actual compression in dry-run mode)
        if dry_run:
            result["compressed"].append(str(log_path))
        else:
            error = _compress_log(log_path, dry_run)
            if error:
                result["errors"].append(error)
            else:
                result["compressed"].append(str(log_path))

    return result


def _purge_candidates(
    planning_dir: Path,
    current_now: datetime,
    dry_run: bool,
    project_root: Path,
) -> dict[str, list[str]]:
    """Phase 2: purga candidatos .log.gz viejos.

    Returns dict with keys: denominator, purged, protected, errors.
    """
    result: dict[str, list[str]] = {
        "denominator": 0,
        "purged": [],
        "protected": [],
        "errors": [],
    }
    log_gz_files = sorted(planning_dir.rglob("*.log.gz"))

    for gz_path in log_gz_files:
        result["denominator"] += 1

        # Check flight activity exception
        if _is_flight_active(gz_path, project_root):
            result["protected"].append(str(gz_path))
            continue

        error = _purge_log_gz(gz_path, dry_run, now=current_now)
        if error == "dry_run":
            result["purged"].append(str(gz_path))
        elif error == "too_recent":
            pass  # skip, too recent
        elif error:
            result["errors"].append(error)
        else:
            result["purged"].append(str(gz_path))

    return result


def rotate_kilo_logs(
    project_root: Path,
    *,
    dry_run: bool = True,
    compress_days: int = KILO_LOG_COMPRESS_DAYS,
    delete_days: int = KILO_LOG_DELETE_DAYS,
    now: datetime | None = None,
) -> KiloLogReport:
    """Rota logs Kilo bajo project_root: comprime viejos+inactivos, purga .log.gz.

    Before: `project_root` contiene `.agent/planning/**/*.log` y locks en
        `.agent/runtime/`. `lock_alive_fn` comprueba si hay un proceso Kilo vivo.
        `now` permite inyectar hora para tests (si es None, usa datetime.now).
    During: recorre todos los .log; si cumplen edad + locks muertos
        y no hay vuelo activo -> comprime. Para .log.gz viejos -> purga.
        Vuelos activos protegen (work_plan.md reciente sin terminal).
        La deteccion de inactividad se basa UNICAMENTE en mtime (sin sleep).
    After: devuelve KiloLogReport con denominador, acciones y errores.
    """
    report = KiloLogReport(dry_run=dry_run)
    planning_dir = project_root / ".agent" / "planning"

    if not planning_dir.is_dir():
        return report

    lock_alive_fn = _load_lock_checker(project_root)
    current_now = now or datetime.now(timezone.utc)

    # Phase 1: Compress old+inactive .log files
    compress_results = _compress_candidates(
        planning_dir, lock_alive_fn, compress_days, dry_run, current_now, project_root
    )
    report.denominator += compress_results["denominator"]
    report.compressed.extend(compress_results["compressed"])
    report.protected_active_flight.extend(compress_results["protected"])
    report.errors.extend(compress_results["errors"])

    # Phase 2: Purge old .log.gz files
    purge_results = _purge_candidates(planning_dir, current_now, dry_run, project_root)
    report.denominator += purge_results["denominator"]
    report.purged.extend(purge_results["purged"])
    report.protected_active_flight.extend(purge_results["protected"])
    report.errors.extend(purge_results["errors"])

    return report


def _print_report(report: KiloLogReport, *, as_json: bool) -> None:
    """Imprime el reporte en formato legible o JSON."""
    if as_json:
        print(json.dumps(report.as_dict()))
        return
    accion = "DRY-RUN" if report.dry_run else "APPLY"
    print(f"[rotate_kilo_logs] {accion}")
    print(
        f"[rotate_kilo_logs] denominador: {report.denominator} | "
        f"comprimidos: {len(report.compressed)} | "
        f"purgados: {len(report.purged)} | "
        f"protegidos_vuelo_activo: {len(report.protected_active_flight)} | "
        f"errores: {len(report.errors)}"
    )
    for name in report.compressed:
        print(f"  COMPRIMIDO   {name}")
    for name in report.purged:
        print(f"  PURGADO      {name}")
    for name in report.protected_active_flight:
        print(f"  PROTEGIDO    {name}")
    for name in report.errors:
        print(f"  ERROR        {name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Rota logs Kilo bajo .agent/planning/: comprime logs viejos+inactivos, "
            "borra .log.gz obsoletos, protege vuelos activos. "
            "Default: dry-run (solo reporta). Usa --apply para ejecutar."
        )
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        required=True,
        help="Raiz del repo_destino.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Modo preview (default: solo reporta sin tocar nada).",
    )
    parser.add_argument(
        "--apply",
        action="store_false",
        dest="dry_run",
        help="Ejecuta compresion y purga real.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Salida en formato JSON.",
    )
    args = parser.parse_args(argv)

    try:
        report = rotate_kilo_logs(
            Path(args.project_root),
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    _print_report(report, as_json=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
