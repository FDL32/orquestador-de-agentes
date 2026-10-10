#!/usr/bin/env python3
"""WOT-2026-095b: listado read-only de fichas de backlog por el campo `[LINEA: <nombre>]`.

Herramienta de consulta MANUAL (no es guard ni gate: no se cablea en pre-commit,
CI, prepush, closeout ni ningun camino automatico -- decision de producto,
alcance MINIMO de T-095b-001).

Before (pre-condiciones):
    El proyecto destino se resuelve SOLO via ``--project-root`` o
    ``AGENT_PROJECT_ROOT`` (``resolve_destino_root`` importado de
    ``check_backlog_contract.py``: precedencia CLI -> env, SIN fallback a cwd
    ni a ``__file__``; raiz ausente/no existente es fail-closed exit 1).
    ``<root>/.agent/collaboration/backlog.md`` debe existir (si falta, exit 1).
    ``<root>/.agent/collaboration/_archive/backlog_done.md`` es OPCIONAL: un
    destino fresco no tiene archive; si falta se avisa por stderr y el
    universo queda limitado a la cola viva.

During (proceso y recursos):
    Solo lectura -- no muta ningun fichero, jamas. Lee ambos ficheros con
    encoding ``utf-8`` (``parse_live_backlog_rows``) / ``utf-8`` (scan propio,
    misma via para conservar el paralelismo fila a fila con el parser).
    Universe de fichas (dos clases, ambas alcanzadas -- leccion
    ``a-wired-check-can-be-blind-to-the-layout-where-the-failure-lives``):
      (a) filas Prioridad-led de AMBOS ficheros: reutiliza
          ``backlog_priority_score.parse_live_backlog_rows`` (merge de
          continuaciones multilinea incluido), que expone ticket + Titulo
          crudo donde vive el campo ``[LINEA: ...]``; la celda Estado
          (RAW split index 5) NO la expone ese parser, asi que se obtiene con
          un scan de lineas fisicas bajo el MISMO predicado (Prioridad en
          RAW idx 1, id canonico en RAW idx 2, ``len(cells) >= 9``) y se
          empareja 1:1 en orden con las filas del parser (toda fila parseada
          nace de exactamente una linea fisica que pasa el predicado). Un
          desajuste de conteo aborta con RuntimeError explícito (fail-closed,
          nunca zip silencioso).
      (b) filas compactas del archive ``| <id> | <estado> | <nota...> |``:
          id canonico en RAW idx 1, idx 1 NO es palabra de Prioridad,
          ``len(cells) > 3`` -- mismo predicado que
          ``check_backlog_contract._compact_closure_log_cells`` (WOT-2026-058w).
          Se reimplementa SOLO la recoleccion de celdas porque ese helper
          devuelve unicamente el id y el DoD (a) exige id + estado + valores
          LINEA por fila (justificacion exigida por el contrato: no es ceguera
          al layout, es falta de exposicion de las otras celdas).
    Decisiones tecnicas documentadas (no se preguntan, unico invariante:
    igualdad de VALOR EXACTO, nunca substring):
      * Marcador ``[LINEA:`` case-SENSITIVE. Medido 2026-10-10 sobre el
        destino real (417 hits vivos + 50 archivados): el 100% de las formas
        humanas usa ``LINEA`` en mayusculas; no existe variante minuscula.
      * Tolerancia de espacios: ``[`` y ``LINEA:`` y el valor admiten
        espacios/tabs internos adyacentes (``\\[\\s*LINEA:\\s*...\\s*\\]``).
        El VALOR capturado se trunca de bordes pero NO se normaliza por dentro
        ni se re-cashea: el censo lista vocabulario CRUDO (DoD (b), "sin
        inventar ni normalizar valores").
      * Coincidencia ``--linea``: igualdad exacta de cadena contra cada valor
        ``[LINEA: <valor>]`` de la fila. Una fila con varios campos coincide si
        ALGUNO de sus valores es exactamente la consulta; una fila SIN campo
        no coincide jamas (DoD (c): nunca es "linea vacia").
      * Fichas con dos valores distintos entran en ambos cubos del censo;
        cada ficha cuenta UNA vez por valor (no por ocurrencia).

After (post-condiciones y errores):
    ``--linea X``: salida texto con ID, estado y origen (viva/archive) de cada
    ficha cuyo valor EXACTO es X, mas un recibo de conteo. exit 0 incluso con
    0 fichas (mensaje explicito "0 fichas").
    ``--list-lineas``: censo de valores distintos con fichas totales/viva/
    archive, contador explicito de fichas SIN campo y total del universo.
    exit 0.
    exit 1 fail-closed: sin raiz (--project-root y AGENT_PROJECT_ROOT ambos
    ausentes), raiz inexistente, o backlog.md ausente. exit 2: errores de
    uso de argparse (faltan argumentos mutuamente excluyentes).
    Intercepciones: OSError de lectura -> diagnostico por stderr + exit 1;
    desajuste parser/scan -> RuntimeError (no se convierte en exit 0).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


_MOTOR_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(_MOTOR_ROOT / "scripts"), str(_MOTOR_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Reuso los parsers existentes (Forbidden Surfaces de T-095b-001: IMPORTAR,
# nunca copiar ni editar en sitio).
from backlog_priority_score import parse_live_backlog_rows  # noqa: E402
from check_backlog_contract import _PRIORIDAD_WORDS, resolve_destino_root  # noqa: E402


# Mismo patron de id canonico que parse_live_backlog_rows
# (scripts/backlog_priority_score.py:134, fullmatch). Prefijo-agnostico:
# admite WOT/WP/WT/CTL historicos; Rechaza celdas DEC-* o prose.
_TICKET_ID_RE = re.compile(r"[A-Z]+-\d{4}-\d+[a-z]*")

# Campo editorial ``[LINEA: <valor>]``: marcador case-sensitive, valor hasta
# el primer ``]`` (acotable -- si algun dia dejara de serlo, eso es
# CONTRACT_GAP segun T-095b-001, no se tolera aqui).
_LINEA_RE = re.compile(r"\[\s*LINEA:\s*([^\]\n]+?)\s*\]")

_LIVE_NAME = "backlog.md"
_ARCHIVE_REL = Path("_archive") / "backlog_done.md"

ORIGEN_VIVA = "viva"
ORIGEN_ARCHIVE = "archive"


class Ficha:
    """Una fila de backlog con su id, estado, origen y valores [LINEA:] crudos."""

    __slots__ = ("estado", "origen", "ticket", "valores")

    def __init__(
        self, ticket: str, estado: str, origen: str, valores: list[str]
    ) -> None:
        self.ticket = ticket
        self.estado = estado
        self.origen = origen
        self.valores = valores


def extract_linea_values(text: str) -> list[str]:
    """Valores ``[LINEA: <valor>]`` en ``text``, en orden de aparicion, crudos."""
    return _LINEA_RE.findall(text)


def _estado_cells(path: Path) -> list[str]:
    """Celdas Estado (RAW idx 5) de cada linea fisica Prioridad-led canonica.

    El predicado replica EXACTAMENTE el de ``parse_live_backlog_rows``
    (Prioridad en idx 1, id en idx 2, ``len(cells) >= 9``) para que el
    emparejamiento 1:1 con las filas del parser este garantizado.
    """
    cells: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue  # mismo guard de inicio-pipe que parse_live_backlog_rows
        raw = stripped.split("|")
        if len(raw) < 9:
            continue
        if raw[1].strip() not in _PRIORIDAD_WORDS:
            continue
        if not _TICKET_ID_RE.fullmatch(raw[2].strip()):
            continue
        cells.append(raw[5].strip())
    return cells


def read_prio_fichas(path: Path, origen: str) -> list[Ficha]:
    """Fichas Prioridad-led de ``path`` reutilizando el parser de la cola viva."""
    if not path.exists():
        return []
    rows = parse_live_backlog_rows(path)
    estados = _estado_cells(path)
    if len(rows) != len(estados):
        raise RuntimeError(
            f"desajuste parser/estado-scan en {path}: "
            f"{len(rows)} filas de parse_live_backlog_rows vs {len(estados)} "
            "lineas Prioridad-led -- el predicado compartido se rompio; "
            "reportar como CONTRACT_GAP, no adivinar estados."
        )
    fichas: list[Ficha] = []
    for row, estado in zip(rows, estados, strict=True):
        fichas.append(
            Ficha(row.ticket, estado, origen, extract_linea_values(row.titulo_completo))
        )
    return fichas


def read_compact_fichas(path: Path) -> list[Ficha]:
    """Fichas compactas ``| <id> | <estado> | <nota...> |`` del archive.

    Mismo predicado de clase que ``_compact_closure_log_cells`` (id canonico
    en RAW idx 1, idx 1 no Prioridad, ``len(cells) > 3``); aqui ademas se
    conservan estado (idx 2) y los valores LINEA del resto de celdas, que el
    helper existente no expone.
    """
    if not path.exists():
        return []
    fichas: list[Ficha] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith("| "):
            continue
        raw = stripped.split("|")
        if len(raw) <= 3:
            continue
        candidate = raw[1].strip()
        if candidate in _PRIORIDAD_WORDS:
            continue
        if not _TICKET_ID_RE.fullmatch(candidate):
            continue
        estado = raw[2].strip()
        valores: list[str] = []
        for cell in raw[3:]:
            valores.extend(extract_linea_values(cell))
        fichas.append(Ficha(candidate, estado, ORIGEN_ARCHIVE, valores))
    return fichas


def load_universe(root: Path) -> tuple[list[Ficha], str | None]:
    """Todas las fichas (viva + archive, ambos layouts).

    Returns (fichas, aviso): ``aviso`` no-nulo cuando el archive falta
    (universo reducido a viva, declarado, nunca silencioso).
    """
    live = root / ".agent" / "collaboration" / _LIVE_NAME
    fichas = read_prio_fichas(live, ORIGEN_VIVA)
    archive = root / ".agent" / "collaboration" / _ARCHIVE_REL
    aviso = None
    if archive.exists():
        fichas += read_prio_fichas(archive, ORIGEN_ARCHIVE)
        fichas += read_compact_fichas(archive)
    else:
        aviso = f"archive ausente ({archive}): universo limitado a la cola viva"
    return fichas, aviso


def fichas_by_linea(fichas: list[Ficha], linea: str) -> list[Ficha]:
    """Fichas con un valor EXACTO == ``linea`` (nunca substring)."""
    return [f for f in fichas if linea in f.valores]


def census_lineas(fichas: list[Ficha]) -> dict[str, dict[str, int]]:
    """Valor crudo -> {fichas, viva, archive}. Cuenta por ficha, no por hit."""
    census: dict[str, dict[str, int]] = {}
    for f in fichas:
        for valor in dict.fromkeys(f.valores):  # dedupe intra-ficha, conserva orden
            bucket = census.setdefault(valor, {"fichas": 0, "viva": 0, "archive": 0})
            bucket["fichas"] += 1
            bucket[f.origen] += 1
    return census


def sin_campo_count(fichas: list[Ficha]) -> dict[str, int]:
    """Fichas sin NINGUN campo [LINEA:]. Nunca se tratan como 'linea vacia'."""
    out = {"total": 0, ORIGEN_VIVA: 0, ORIGEN_ARCHIVE: 0}
    for f in fichas:
        if not f.valores:
            out["total"] += 1
            out[f.origen] += 1
    return out


def format_listing(fichas: list[Ficha], linea: str) -> str:
    """Bloque de fichas que coinciden exactamente con ``linea`` + recibo."""
    matches = fichas_by_linea(fichas, linea)
    lines = [f"[LINEA: {linea}] (coincidencia EXACTA de valor)"]
    if not matches:
        lines.append(f"0 fichas con [LINEA: {linea}]")
    lines.extend(f"  {f.ticket}  {f.estado}  {f.origen}" for f in matches)
    viva = sum(1 for f in matches if f.origen == ORIGEN_VIVA)
    arch = sum(1 for f in matches if f.origen == ORIGEN_ARCHIVE)
    lines.append(f"fichas: {len(matches)} (viva: {viva}, archive: {arch})")
    return "\n".join(lines)


def format_census(fichas: list[Ficha]) -> str:
    """Censo de valores distintos + contador explicito de fichas sin campo."""
    census = census_lineas(fichas)
    sin_campo = sin_campo_count(fichas)
    lines = ["valores [LINEA:] distintos (crudos, sin normalizar):"]
    ordered = sorted(census.items(), key=lambda kv: (-kv[1]["fichas"], kv[0]))
    if not ordered:
        lines.append("(ningun valor presente)")
    for valor, c in ordered:
        lines.append(
            f"  {valor}  fichas={c['fichas']}  viva={c[ORIGEN_VIVA]}"
            f"  archive={c[ORIGEN_ARCHIVE]}"
        )
    lines.append(
        f"fichas SIN campo [LINEA: {sin_campo['total']} "
        f"(viva: {sin_campo[ORIGEN_VIVA]}, archive: {sin_campo[ORIGEN_ARCHIVE]})"
    )
    lines.append(f"total fichas en universo: {len(fichas)}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="list_backlog_by_linea.py",
        description=(
            "Listado read-only de fichas de backlog por el campo editorial "
            "[LINEA: <nombre>]. Herramienta de consulta manual; no es guard ni "
            "gate.\n\n"
            "Decisiones tecnicas (ver docstring del modulo): marcador "
            "case-sensitive; coincidencia de valor EXACTA (nunca substring); "
            "el censo lista valores CRUDOS sin normalizar; fichas sin campo se "
            "cuentan aparte y jamas aparecen en un listado por linea; cubre "
            "ambos layouts (Prioridad-led viva+archive y compacto del archive)."
        ),
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="raiz del repo_destino (precede a AGENT_PROJECT_ROOT; fail-closed "
        "sin cwd)",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--linea",
        metavar="<nombre>",
        help="lista las fichas cuyo valor [LINEA:] es EXACTAMENTE <nombre>",
    )
    group.add_argument(
        "--list-lineas",
        action="store_true",
        help="censa los valores [LINEA:] distintos (viva+archive) con conteos "
        "por origen y el contador de fichas sin campo",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # El censo lista valores CRUDOS del backlog (prosa con acentos inclusive):
    # fijar utf-8 evita UnicodeEncodeError segun consola del operador.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    root, error = resolve_destino_root(args.project_root)
    if error or root is None:
        print(f"[FAIL] {error}", file=sys.stderr)
        return 1

    live = root / ".agent" / "collaboration" / _LIVE_NAME
    if not live.exists():
        print(f"[FAIL] fail-closed: no existe {live}", file=sys.stderr)
        return 1

    try:
        fichas, aviso = load_universe(root)
    except OSError as exc:
        print(f"[FAIL] error de lectura: {exc}", file=sys.stderr)
        return 1
    if aviso:
        print(f"[aviso] {aviso}", file=sys.stderr)

    if args.linea is not None:
        print(format_listing(fichas, args.linea))
    else:
        print(format_census(fichas))
    return 0


if __name__ == "__main__":
    sys.exit(main())
