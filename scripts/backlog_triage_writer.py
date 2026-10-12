#!/usr/bin/env python3
"""Escritor unico del DAG de triaje (WOT-2026-049c).

Cierra la BARRERA que WOT-2026-049a dejo como NORMA en
``prompts/backlog_triage.md``: hasta ahora el agente escribia el JSON del DAG
con su herramienta de escritura nativa, asi que un triaje nuevo podia
sobrescribir el anterior sin copia previa. Este script es el UNICO dueno de
materializar el DAG en disco.

Contrato (DoD del ticket):

1. Escribe ``backlog_triage_<YYYYMMDD-HHMMSS>.json`` (timestamp de SEGUNDOS,
   el mismo patron que valida ``scripts/validate_batch_dag.py``).
2. ANTES de escribir el fichero nuevo, si existe un DAG previo en el
   directorio destino, lo copia con ``shutil.copy2`` a un nombre derivado con
   sufijo ``_previo`` (``backlog_triage_<ts>_previo.json``). Nunca se
   sobrescribe un DAG sin copia previa: si el timestamp nuevo colisiona con
   uno existente, la copia del previo es lo que lo preserva.
3. La escritura del fichero nuevo es ATOMICA: write-tmp-then-rename
   (``tempfile.NamedTemporaryFile`` en el MISMO directorio + ``os.replace``),
   nunca ``open(path, "w")`` directo sobre el destino final. Un fallo a mitad
   de la serializacion no deja un DAG parcial en la ruta canonica.

Topologia (CONTRACT_GAP del ticket, resuelto por evidencia 2026-10-12): el DAG
de triaje vive en ``<destino>/orchestrator_pipeline/reports/`` -- lo fija
``prompts/backlog_triage.md`` (Salida obligatoria) y lo confirman 40+ DAGs
reales del arbol -- NO en ``<project_root>/.agent/collaboration/``. El default
de ``--out-dir`` se deriva de ``--project-root`` como
``<project-root>/orchestrator_pipeline/reports/``; ``--out-dir`` lo
sobreescribe. Si no hay ni ``--out-dir`` ni ``--project-root`` (ni
``AGENT_PROJECT_ROOT``), el script falla cerrado (exit 2) en vez de improvisar
una ruta.

Uso:
    python scripts/backlog_triage_writer.py write --project-root <destino> \\
        --from-file dag.json
    cat dag.json | python scripts/backlog_triage_writer.py write --out-dir <dir>

Exit codes:
- 0: DAG escrito (o mostrado en ``--dry-run``).
- 2: error de uso/entrada (JSON invalido, ruta de salida no resoluble).
- 1: fallo de I/O al escribir.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# Mismo patron que el VALIDADOR (`validate_batch_dag.py::_TRIAGE_NAME_RE`): un
# DAG canonico lleva timestamp de 4-6 digitos de hora. No se redefine la logica
# del validador; solo se reconoce su forma para elegir el "previo" correcto.
_CANONICAL_DAG_RE = re.compile(r"^backlog_triage_(\d{8}-\d{4,6})\.json$")

# Sufijo del fichero de copia. NO casa `_CANONICAL_DAG_RE` a proposito, asi que
# un `_previo` nunca se confunde con un DAG canonico ni vuelve a copiarse.
PREVIO_SUFFIX = "_previo"

# Subruta del DAG dentro del destino (fuente: prompts/backlog_triage.md).
REPORTS_SUBPATH = ("orchestrator_pipeline", "reports")


def _now_utc() -> datetime:
    """Now in UTC -- timestamp shape is timezone-independent."""
    return datetime.now(timezone.utc)


def _derive_timestamp(now: datetime | None = None) -> str:
    """`YYYYMMDD-HHMMSS` con SEGUNDOS (evita colisiones entre corridas rapidas).

    Before: `now` es opcional (inyectable en tests).
    During: formatea en UTC; sin I/O.
    After: devuelve la cadena de timestamp usada por el nombre del DAG.
    """
    return (now or _now_utc()).strftime("%Y%m%d-%H%M%S")


def _canonical_match(name: str) -> re.Match[str] | None:
    """Match de un nombre de DAG canonico. `_previo` no casa (por diseno)."""
    return _CANONICAL_DAG_RE.match(name)


def _is_previo_name(name: str) -> bool:
    """True si `name` es el fichero de copia derivada, no un DAG canonico."""
    return PREVIO_SUFFIX in Path(name).stem


def _find_previous_dag(out_dir: Path) -> Path | None:
    """El DAG canonico mas reciente en `out_dir`, o None si no hay ninguno.

    Before: `out_dir` existe (el caller lo crea antes).
    During: enumera SOLO nombres que casan `_CANONICAL_DAG_RE` (los ficheros
            `_previo` quedan fuera por su propio nombre); ordena por la parte
            de timestamp del nombre, con el nombre completo como desempate.
    After: devuelve el `Path` del mas reciente, o None. Sin I/O sobre el DAG.
    """
    best: tuple[tuple[str, str], Path] | None = None
    for candidate in out_dir.iterdir():
        match = _canonical_match(candidate.name)
        if match is None or not candidate.is_file():
            continue
        key = (match.group(1), candidate.name)
        if best is None or key > best[0]:
            best = (key, candidate)
    return best[1] if best is not None else None


def _backup_path(prev_path: Path) -> Path:
    """Ruta derivada de la copia: `backlog_triage_<ts>_previo.json`."""
    return prev_path.with_name(f"{prev_path.stem}{PREVIO_SUFFIX}{prev_path.suffix}")


def _preserve_previous(prev_path: Path) -> Path:
    """Copia el DAG previo a su nombre derivado ANTES de escribir el nuevo.

    Before: `prev_path` es un DAG canonico existente.
    During: `shutil.copy2` (conserva metadatos; la copia del previo es lo que
            preserva su contenido cuando el nuevo DAG reutiliza el timestamp).
    After: devuelve el `Path` de la copia; propaga `OSError` si falla.
    """
    backup = _backup_path(prev_path)
    shutil.copy2(str(prev_path), str(backup))
    return backup


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Write-tmp-then-rename: nunca `open(path, "w")` sobre el destino final.

    Before: `path.parent` existe y es escribible.
    During: serializa a un `NamedTemporaryFile` en el MISMO directorio (rename
            atomico solo si tmp y destino comparten filesystem), `flush` +
            `fsync`, cierra y `os.replace`. Si la serializacion falla, el
            destino canonico NUNCA llega a existir (no hay DAG a medias).
    After: el destino contiene el JSON completo, o no existe. El tmp se limpia
           en cualquier salida anomala.
    """
    payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=str(path.parent),
            prefix=f"{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(tmp_path), str(path))
    except BaseException:
        if tmp_path is not None:
            with contextlib.suppress(OSError):
                tmp_path.unlink()
        raise


def write_triage_dag(
    data: dict[str, Any],
    out_dir: Path,
    *,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Escribe el DAG de triaje preservando el previo y de forma atomica.

    Before: `data` es el DAG ya construido por el agente (dict serializable);
            `out_dir` es el directorio de reports (se crea si no existe);
            `timestamp` opcional permite fijar el nombre (tests/reproducibilidad).
    During: crea `out_dir`; localiza el DAG previo mas reciente; lo copia a su
            nombre `_previo` con `shutil.copy2`; y escribe el nuevo DAG con
            write-tmp-then-rename.
    After: devuelve `{"path", "previous", "backup", "timestamp"}`. Propaga las
           excepciones de I/O; el destino final solo existe si la escritura
           atomica se completo.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = timestamp or _derive_timestamp()
    new_path = out_dir / f"backlog_triage_{ts}.json"

    previous = _find_previous_dag(out_dir)
    backup: Path | None = None
    if previous is not None:
        backup = _preserve_previous(previous)

    _atomic_write_json(new_path, data)
    return {
        "path": new_path,
        "previous": previous,
        "backup": backup,
        "timestamp": ts,
    }


def _resolve_out_dir(args: argparse.Namespace) -> Path | None:
    """Resuelve el directorio destino: `--out-dir` gana; si no, del project root.

    Before: `args` trae `out_dir` y/o `project_root` (o `AGENT_PROJECT_ROOT`).
    During: `--out-dir` se usa tal cual; en su ausencia se deriva
            `<project-root>/orchestrator_pipeline/reports/`.
    After: devuelve el `Path`, o None si no hay ninguna fuente (fail-closed).
    """
    if args.out_dir:
        return Path(args.out_dir)
    project_root = args.project_root or os.environ.get("AGENT_PROJECT_ROOT")
    if not project_root:
        return None
    return Path(project_root).joinpath(*REPORTS_SUBPATH)


def _read_dag_payload(
    args: argparse.Namespace,
) -> tuple[dict[str, Any] | None, str | None]:
    """Lee y parsea el DAG desde `--from-file` o stdin. Devuelve (data, error)."""
    try:
        if args.from_file:
            raw = Path(args.from_file).read_text(encoding="utf-8-sig")
        else:
            raw = sys.stdin.read()
    except OSError as exc:
        return None, f"no se pudo leer el DAG de entrada: {exc}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"JSON de entrada invalido: {exc}"
    if not isinstance(data, dict):
        return None, "el DAG debe ser un objeto JSON en la raiz"
    return data, None


def cmd_write(args: argparse.Namespace) -> int:
    """Subcomando `write`: materializa el DAG en disco (o dry-run)."""
    data, error = _read_dag_payload(args)
    if error is not None:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    out_dir = _resolve_out_dir(args)
    if out_dir is None:
        print(
            "ERROR: sin directorio de salida. Pasa --out-dir, o --project-root "
            "(se deriva <project-root>/orchestrator_pipeline/reports/).",
            file=sys.stderr,
        )
        return 2

    assert data is not None  # noqa: S101 -- garantizado por el guard de error
    try:
        result = write_triage_dag(data, out_dir, timestamp=args.timestamp)
    except OSError as exc:
        print(f"ERROR: no se pudo escribir el DAG: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "written": True,
                "path": str(result["path"]),
                "previous": str(result["previous"]) if result["previous"] else None,
                "backup": str(result["backup"]) if result["backup"] else None,
                "timestamp": result["timestamp"],
            }
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    """CLI: un subcomando `write`."""
    parser = argparse.ArgumentParser(
        description=(
            "Escritor unico del DAG de triaje de backlog_triage.md "
            "(WOT-2026-049c): copia el previo y escribe el nuevo atomicamente."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    write_p = subparsers.add_parser(
        "write",
        help="Escribe backlog_triage_<YYYYMMDD-HHMMSS>.json preservando el previo.",
    )
    write_p.add_argument(
        "--out-dir",
        default=None,
        help="Directorio destino del DAG (sobreescribe la derivacion por root).",
    )
    write_p.add_argument(
        "--project-root",
        default=None,
        help=(
            "Raiz del destino. Si no hay --out-dir, el DAG va a "
            "<project-root>/orchestrator_pipeline/reports/."
        ),
    )
    write_p.add_argument(
        "--from-file",
        default=None,
        help="Fichero con el DAG JSON. Si se omite, se lee de stdin.",
    )
    write_p.add_argument(
        "--timestamp",
        default=None,
        help=(
            "Fuerza el timestamp YYYYMMDD-HHMMSS del nombre (tests/"
            "reproducibilidad). Por defecto, la hora UTC actual."
        ),
    )
    write_p.set_defaults(func=cmd_write)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Devuelve el exit code del subcomando."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
