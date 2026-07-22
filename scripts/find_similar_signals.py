#!/usr/bin/env python3
"""Lector de vecindad: lista las entradas mas proximas a un candidato de memoria/backlog.

GENERADOR DE SENAL, NUNCA VEREDICTO (WOT-2026-039m). Este script NO decide si algo
es un duplicado -- eso es juicio semantico y es un NON-GOAL duro del ticket. Lista
vecinos para que un humano/agente los LEA ENTEROS y decida.

Por que existe (medido 2026-07-22): 4 duplicados de memoria/backlog en UN dia, tres
de ellos declarando "busque duplicados". La causa raiz NO fue descuido: el dedupe
existente compara solo claves exactas -- `reconcile_portable_memory.record_key()` usa
`(topic, source_ticket)` e igualdad de `id`; `memory_consolidate` dedupea por
`(signal, source, topic)` con igualdad EXACTA de cadena. Ninguna ruta compara el
CONTENIDO del `signal` entre entradas distintas. Ademas las lecciones del archive
estan redactadas como REGLAS ABSTRACTAS y los candidatos nuevos como CASOS CONCRETOS;
un grep por keyword no cruza esos dos registros. Y el barrido se hacia contra UNA
superficie por vez (archive O backlog) cuando la deuda vive en LAS DOS.

Este script NO toca el contrato de ESCRITURA de la memoria: es un lector puro.

Before (pre-condiciones):
    Un texto candidato (via --text o --text-file). Al menos una superficie legible:
    archive JSONL de memoria y/o tabla markdown de backlog. Stdlib only.

During (proceso y recursos):
    Tokeniza el SIGNAL (no el id ni el topic) de cada entrada de cada superficie,
    pondera por IDF sobre el corpus unido -- sin IDF los tokens ubicuos (`2026`,
    `regla`, `solo`, `ticket`, `commit`) dominan el ranking y el detector degenera
    en el mismo grep ciego que pretende sustituir -- y ordena por Jaccard ponderado.
    I/O: solo lectura. Memoria: O(corpus); 684KB de backlog es trivial.

After (post-condiciones y errores):
    Imprime hasta --top vecinos con su score, los terminos que causaron el match y
    un aviso de que score alto NO es duplicado confirmado, mas la cobertura real
    escaneada. Exit 0 = analisis completado (CON o SIN vecinos: no encontrar nada
    NO es un fallo y jamas bloquea una promocion). Exit 2 = error de parseo/uso, que
    es un estado distinto de "no hay similares" para que ningun consumidor confunda
    "limpio" con "no llegue a mirar".
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path


# Borde INFERIOR de la meseta medida contra el corpus REAL (132 entradas del archive
# del motor + los 4 casos reales de duplicado del 2026-07-22), NO contra fixtures
# escritos para el barrido -- barrer contra fixtures propios mide los fixtures.
# Barrido: N=1 -> 3/4 casos listados | N=2 -> 3/4 | N=3 -> 4/4 | ... | N=20 -> 4/4.
# La COTA SUPERIOR queda ABIERTA: subir N no pierde ningun caso, solo alarga la lista
# que el humano debe leer. 5 es N=3 (borde medido) + margen de lectura, no un optimo.
DEFAULT_TOP = 5

# Longitud minima de token. Corta articulos/preposiciones sin necesidad de una lista
# de stopwords por idioma (el corpus mezcla castellano e ingles). Los terminos ubicuos
# que SI pasan el filtro los neutraliza el IDF, que es la barrera real contra el ruido.
_MIN_TOKEN_LEN = 4
_TOKEN_RE = re.compile(rf"[a-z0-9_]{{{_MIN_TOKEN_LEN},}}")

# Identificador de ticket: prefijo canonico `WOT-` y los legacy/por-destino en uso
# (`WP-`, `WT-`, `CTL-`, `EXF-`, ...). Cualquier prefijo de 2-4 mayusculas vale: el
# registro de prefijos vive en los links por-destino, no aqui, y este lector solo
# necesita reconocer la FORMA para no etiquetar una fila con su prosa.
_TICKET_RE = re.compile(r"[A-Z]{2,4}-\d{4}-\d{3}[a-z]?(?:-[A-Za-z0-9]+)?")


def tokenize(text: str | None) -> set[str]:
    """Extrae el conjunto de terminos de un texto. Tolera None y no-str."""
    if not text:
        return set()
    if not isinstance(text, str):
        text = str(text)
    return set(_TOKEN_RE.findall(text.lower()))


class ParseError(RuntimeError):
    """Fallo al leer una superficie. Se reporta con exit 2, nunca como 'sin vecinos'."""


def load_archive(path: Path) -> list[tuple[str, str]]:
    """Lee un archive JSONL de memoria -> [(label, signal)].

    Tolera entradas SIN `id` (medido: 10 de 132 en el archive del motor no lo tienen,
    y asumir `record['id']` peta con KeyError): degrada a `topic` y luego al indice.
    """
    out: list[tuple[str, str]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ParseError(f"no se pudo leer el archive {path}: {exc}") from exc
    for idx, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ParseError(f"{path}:{idx + 1}: JSON invalido ({exc})") from exc
        if not isinstance(rec, dict):
            continue
        signal = rec.get("signal")
        if not signal:
            continue
        label = rec.get("id") or rec.get("topic") or f"#{idx + 1}"
        out.append((str(label), str(signal)))
    return out


def _split_row(line: str) -> list[str]:
    """Parte una fila markdown en celdas respetando los pipes escapados (`\\|`)."""
    cells, buf, prev_escape = [], [], False
    for ch in line:
        if ch == "|" and not prev_escape:
            cells.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        prev_escape = ch == "\\" and not prev_escape
    cells.append("".join(buf))
    if cells and not cells[0].strip():
        cells = cells[1:]
    if cells and not cells[-1].strip():
        cells = cells[:-1]
    return [c.strip() for c in cells]


def load_backlog(path: Path) -> list[tuple[str, str]]:
    """Lee una tabla markdown de backlog -> [(label, texto)].

    Robusto a celdas MULTILINEA: una linea que no abre con `|` es continuacion de la
    fila anterior, no una fila nueva. Con un split ingenuo, 684KB de backlog_done se
    corrompen en silencio y el detector produce falsos negativos sistematicos.

    Localiza las columnas por CABECERA y la RE-DETECTA en cada tabla: un mismo fichero
    contiene VARIAS tablas con esquemas distintos (medido en backlog_done.md:
    `| Ticket | Estado | Nota |` en l.36, `| Prioridad | Ticket | ... |` en l.102,
    `| Ticket | Titulo | Commit(s) |` en l.596). Fijar la cabecera una sola vez
    etiqueta filas con la columna equivocada -- se vio en dogfooding un vecino
    etiquetado `Media` (la celda de prioridad) en vez de su ticket. Las filas
    ANTERIORES a cualquier cabecera se descartan: sin esquema no hay etiqueta fiable.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ParseError(f"no se pudo leer el backlog {path}: {exc}") from exc

    # Re-une las continuaciones antes de partir en filas.
    merged: list[str] = []
    for line in raw.splitlines():
        if line.lstrip().startswith("|"):
            merged.append(line.rstrip())
        elif merged and line.strip():
            merged[-1] += " " + line.strip()

    out: list[tuple[str, str]] = []
    ticket_col = title_col = None
    for line in merged:
        cells = _split_row(line)
        if not cells or all(set(c) <= {"-", ":", " "} for c in cells if c):
            continue  # separador |---|---|
        header = _header_columns(cells)
        if header is not None:
            ticket_col, title_col = header  # la cabecera no es un dato
            continue
        if ticket_col is None or ticket_col >= len(cells):
            continue
        label = _row_label(cells, ticket_col)
        if not label:
            continue
        # Todo el texto de la fila es señal util: el titulo lleva el enunciado, pero
        # el detalle de la ficha vive en las celdas siguientes. `title_col` puede
        # caer fuera de rango si la prosa de la ficha metio pipes extra, asi que se
        # comprueba contra ESTA fila y no contra el esquema de la cabecera.
        start = title_col if title_col is not None and title_col < len(cells) else 0
        out.append((label, " ".join(cells[start:])))
    return out


def _header_columns(cells: list[str]) -> tuple[int | None, int | None] | None:
    """Devuelve (ticket_col, title_col) si la fila es una CABECERA, si no None.

    Se re-evalua en cada fila a proposito: un mismo fichero encadena varias tablas
    con esquemas distintos y arrastrar el indice de la anterior desalinea la etiqueta.
    """
    lowered = [c.lower() for c in cells]
    if not any(h.startswith("ticket") for h in lowered):
        return None
    ticket_col = title_col = None
    for i, h in enumerate(lowered):
        if h.startswith("ticket") and ticket_col is None:
            ticket_col = i
        elif h.startswith(("titulo", "título", "title")) and title_col is None:
            title_col = i
    return ticket_col, title_col


def _row_label(cells: list[str], ticket_col: int) -> str:
    """Etiqueta de la fila: el id de ticket real, no lo que diga el esquema.

    La celda que marca la cabecera es la INTENCION; el patron de ticket es el HECHO.
    Una ficha cuya prosa lleva un `|` sin escapar desplaza las celdas y el indice de
    cabecera acaba apuntando a texto libre (medido: 26 de 113 filas del backlog vivo
    quedaban etiquetadas con media ficha). Se usa `search` y no `fullmatch` porque en
    ese caso el id queda EMBEBIDO en la prosa ("con pipe WOT-2026-003c"), no solo.
    """
    label = cells[ticket_col]
    if _TICKET_RE.fullmatch(label or ""):
        return label
    found = next((m for c in cells if (m := _TICKET_RE.search(c))), None)
    return found.group(0) if found else ""


def rank_neighbours(
    candidate: str, corpus: list[tuple[str, str, str]], top: int
) -> list[tuple[float, str, str, list[str]]]:
    """Ordena el corpus por Jaccard ponderado por IDF contra el candidato.

    Devuelve [(score, surface, label, terminos_compartidos)] de mayor a menor,
    truncado a `top` y descartando los de solape nulo.
    """
    docs = [(surface, label, tokenize(text)) for surface, label, text in corpus]
    total = len(docs)
    if not total:
        return []
    df: Counter[str] = Counter()
    for _, _, toks in docs:
        df.update(toks)
    # IDF suavizado y SIEMPRE POSITIVO. El `1 +` interno es lo que evita que un
    # termino presente en TODO el corpus reciba peso <= 0: con `log(total/(1+df))`
    # a secas, df == total da logaritmo NEGATIVO y el score se anula o se invierte
    # -- un corpus pequeno (destino recien instalado) dejaba de listar hasta un
    # vecino IDENTICO. El peso decrece con la frecuencia pero nunca cruza el cero,
    # asi que un termino ubicuo pesa poco en vez de restar.
    idf = {w: math.log(1 + total / (1 + c)) for w, c in df.items()}

    cand = tokenize(candidate)
    scored: list[tuple[float, str, str, list[str]]] = []
    for surface, label, toks in docs:
        shared = cand & toks
        if not shared:
            continue
        num = sum(idf.get(w, 0.0) for w in shared)
        den = sum(idf.get(w, 0.0) for w in (cand | toks))
        if den <= 0:
            continue
        terms = sorted(shared, key=lambda w: idf.get(w, 0.0), reverse=True)[:6]
        scored.append((num / den, surface, label, terms))
    scored.sort(key=lambda t: (-t[0], t[1], t[2]))
    return scored[:top]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Lista los vecinos mas proximos a un candidato por solape de terminos "
            "del SIGNAL, cruzando memoria y backlog. Genera SENAL, no veredicto: "
            "nunca decide si algo es duplicado y nunca bloquea una promocion."
        )
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--text", help="Texto candidato literal.")
    src.add_argument("--text-file", type=Path, help="Fichero con el texto candidato.")
    p.add_argument(
        "--archive",
        type=Path,
        action="append",
        default=None,
        help="Archive JSONL de memoria (repetible).",
    )
    p.add_argument(
        "--backlog",
        type=Path,
        action="append",
        default=None,
        help="Tabla markdown de backlog (repetible; incluye backlog_done).",
    )
    p.add_argument(
        "--top", type=int, default=DEFAULT_TOP, help=f"(default {DEFAULT_TOP})"
    )
    p.add_argument("--json", action="store_true", help="Salida JSON en vez de texto.")
    return p


def _load_corpus(
    archives: list[Path], backlogs: list[Path]
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Une ambas superficies en un corpus etiquetado + su recuento por fichero.

    El recuento se devuelve para poder IMPRIMIR la cobertura: un "sin vecinos" que
    en realidad venia de no haber escaneado nada seria un falso verde silencioso.
    """
    corpus: list[tuple[str, str, str]] = []
    coverage: list[str] = []
    for surface, paths, loader in (
        ("archive", archives, load_archive),
        ("backlog", backlogs, load_backlog),
    ):
        for path in paths:
            entries = loader(path)
            corpus += [(surface, lb, sg) for lb, sg in entries]
            coverage.append(f"{len(entries)} de {path}")
    return corpus, coverage


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.text_file:
        try:
            candidate = args.text_file.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"[similar-signals] ERROR: {exc}", file=sys.stderr)
            return 2
    else:
        candidate = args.text

    if not tokenize(candidate):
        print(
            "[similar-signals] ERROR: el candidato no aporta ningun termino util "
            f"(minimo {_MIN_TOKEN_LEN} caracteres por termino).",
            file=sys.stderr,
        )
        return 2

    if not args.archive and not args.backlog:
        print(
            "[similar-signals] ERROR: indica al menos una superficie "
            "(--archive y/o --backlog). El barrido de UNA sola superficie es "
            "justamente el fallo que este lector existe para evitar.",
            file=sys.stderr,
        )
        return 2

    try:
        corpus, coverage = _load_corpus(args.archive or [], args.backlog or [])
    except ParseError as exc:
        # Exit 2, NO 0: "no pude parsear" jamas debe leerse como "no hay similares".
        print(f"[similar-signals] ERROR de parseo: {exc}", file=sys.stderr)
        return 2

    neighbours = rank_neighbours(candidate, corpus, args.top)

    if args.json:
        print(
            json.dumps(
                {
                    "scanned": len(corpus),
                    "coverage": coverage,
                    "neighbours": [
                        {
                            "score": round(s, 4),
                            "surface": surf,
                            "label": lb,
                            "shared_terms": terms,
                        }
                        for s, surf, lb, terms in neighbours
                    ],
                    "note": "score alto NO es duplicado confirmado; lee cada entrada entera",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    by_surface = Counter(s for s, _, _ in corpus)
    print(
        f"[similar-signals] escaneadas {len(corpus)} entradas: " + ", ".join(coverage)
    )
    print(f"[similar-signals] por superficie: {dict(by_surface)}")
    if not neighbours:
        print(
            "\nSin vecinos con terminos en comun. Esto NO certifica que no exista un "
            "duplicado:\npuede que este redactado con otro vocabulario. El barrido "
            "manual sigue siendo tuyo."
        )
        return 0

    print(f"\n{len(neighbours)} vecino(s) mas proximo(s), de mayor a menor solape:\n")
    for i, (score, surface, label, terms) in enumerate(neighbours, 1):
        print(f"  {i}. [{score:.4f}] {surface}:{label}")
        print(f"     terminos compartidos: {', '.join(terms)}")
    print(
        "\nAVISO: el score mide solape de vocabulario, NO equivalencia semantica.\n"
        "Un score alto NO es un duplicado confirmado y uno bajo NO lo descarta.\n"
        "LEE CADA ENTRADA ENTERA antes de decidir; no la descartes por su titulo\n"
        "(ese fue exactamente el fallo medido el 2026-07-22). Esta herramienta no\n"
        "decide y no bloquea nada: la decision es tuya."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
