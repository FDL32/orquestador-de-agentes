#!/usr/bin/env python3
"""Compare GLOBAL todo-vs-todo de la base de datos del backlog (F1, WOT-2026-069f).

RECOLECTOR determinista read-only que mide similitud de VOCABULARIO entre todas
las filas/planes/fichas de la DB del backlog y emite LOTES DE REVISION. NO decide
fusiones: el juicio es humano/Manager, par a par (contrato T-069F-001).

Before (pre-condiciones):
    Al menos un universo legible por CLI: `--backlog` (tabla markdown; repetible),
    `--inbox` (dir de fichas), `--queued`/`--in-flight` (dirs de planes),
    `--contracts` (ticket_contracts.md para el mapa FLT). Stdlib only. El tool es
    READ-ONLY sobre toda entrada: el unico efecto de escritura es `--out`/`--out-json`
    y aborta (rc=2) si un destino de salida RESUELVE a un path de entrada.

During (proceso y recursos):
    Tokeniza cada entrada con el tokenizador COMPARTIDO de `find_similar_signals.py`
    (misma semantica: minusculas, tokens >= 4 chars) y aplica encima un filtro corto
    de ruido DECLARADO abajo (stopwords + tokens de estatus/prioridad + anos).
    Construye un indice invertido y calcula el Jaccard RAW (|A int B| / |A un B|)
    de cada par candidato (comparte >= 1 token). Pares con Jaccard >= umbral son
    ARISTAS; las componentes CONEXAS (union-find) de las aristas son los LOTES DE
    REVISION. No-transitividad DECLARADA: un lote es una componente, NO una unidad
    fusionable; A~B y B~C no implican A~C y el informe lista cada par por separado.
    Los pares que NO alcanzan el umbral se publican aparte (seccion CERCANOS, top N).
    `--contracts` aporta el mapa T-* <-> WOT-* (campo `ticket_id` del bloque) y el
    solape de touched-paths por par (senal complementaria, NUNCA arista): cobertura
    y bloques saltados se declaran. I/O solo lectura; memoria O(corpus).

After (post-condiciones y errores):
    `--out` escribe el informe markdown, `--out-json` el JSON; `--json` imprime JSON
    a stdout. Ambos llevan el sello `head_sha` (`--head-sha` explicito o derivado con
    `git -C <--git-root|cwd> rev-parse HEAD`; si git no esta disponible se declara
    `unavailable`, nunca se inventa). La salida es DETERMINISTA: misma entrada =>
    misma salida (sin timestamps ni ordenamientos no especificados). Exit 0 = informe
    emitido (con o sin lotes: "sin lotes" es un resultado, no un fallo). Exit 2 =
    uso/parseo/universo-con-contenido-no-inspeccionado (fail-closed): un universo que
    existe con filas y que el parser no consigue leer NO se degrada a "sin lotes".

CRITERIO DEL UMBRAL (medido 2026-09-14 sobre el UNIVERSO DE DESPLIEGUE real:
    backlog.md vivo 342 + `_archive/backlog_done.md` 516 + `backlog_inbox/` 8 +
    planes `queued/` 19 = 885 entradas; 391.170 pares; metrica IDF con el filtro
    de ruido EXACTO que implementa este modulo):
    Calibradores IDF (n=885): `WOT-2026-060m` vs `060n` 0.6823; triplicado real
    `045c/049h/058u`: 045c-058u 0.2377; 049h-058u 0.1403; 045c-049h 0.1392.
    Estabilidad medida (la senal de no-fosilizacion): el minimo calibrador paso
    de 0.1396 (corpus 858) a 0.1393 (corpus 878) a 0.1392 (corpus 885): deriva
    total -0.0004 al anadir 27 entradas (el IDF depende de n y df; se publica).
    Ruido: mediana de los pares con score>0 = 0.0189 (373.670 de 391.170 pares).
    Barrido (pares / lotes / lote mayor): 0.10 -> 985/99/87; 0.11 -> 751/114/76;
    0.12 -> 582/107/47; 0.13 -> 439/102/25; 0.14 -> 351/102/23; 0.15 -> 286/98/11;
    0.18 -> 150/65/7; 0.20 -> 112/50/6; 0.25 -> 59/29/5; 0.42 -> 7/5/3.
    `UMBRAL_DEFAULT = 0.12` = minimo calibrador (0.1392) menos margen 0.0192
    (14% del calibrador; ~48x la deriva medida al crecer el corpus), 6x la
    mediana del ruido. TRIGGER DE RE-VALIDACION declarado: si el corpus crece
    >25% o el margen calibrador-minimo < 0.005, re-ejecutar el barrido y
    re-fijar el umbral con el resultado publicado (evita umbral fosil).
    LIMITE DECLARADO: la similitud del corpus real es un CONTINUO sin valle
    natural (no hay "meseta" del dato); el umbral es una POLITICA DE CORTE con
    esta evidencia. El 0.42 de la propuesta queda disponible via
    `--threshold 0.42` (a 0.42 el triplicado NO se captura: 7 pares / 5 lotes).
    NO se ajusta el umbral para "conformar" un par concreto.

LIMITE SEMANTICO (se declara, no se esconde): el score mide SOLAPE DE VOCABULARIO,
    no equivalencia semantica. Dos entradas con la misma regla redactada con otra
    ontologia no caen en el umbral; un score alto no es un duplicado confirmado.
    Este tool es GENERADOR DE SENAL (misma familia que `find_similar_signals.py`),
    nunca veredicto: F1 NUNCA archiva, fusiona ni bloquea nada.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


_HERE = Path(__file__).resolve().parent
_MOTOR_ROOT = _HERE.parent
for _p in (str(_MOTOR_ROOT), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Tokenizador COMPARTIDO con el lector de vecindad (comparabilidad entre ambos
# lectores; no se duplica el regex). El parser de tablas tambien se reutiliza.
from find_similar_signals import (  # noqa: E402
    ParseError,
    _header_columns,
    _row_label,
    _split_row,
    tokenize,
)


SCHEMA = "backlog-db-compare/v1"

# Borde MEDIDO sobre el UNIVERSO DE DESPLIEGUE (ver docstring): 0.12 = minimo
# calibrador real (0.1393) menos 0.0193 de margen; trigger de re-validacion
# declarado en el docstring. No es un optimo: es un corte con evidencia.
UMBRAL_DEFAULT = 0.12

TOP_NEAR_DEFAULT = 5

# Filtro de ruido DECLARADO (segunda etapa sobre el tokenizador compartido):
# stopwords cortas es/en + tokens de estatus/prioridad ubicuos + anos. Se
# documenta aqui para que el barrido del docstring sea reproducible token a token.
_STOPWORDS = frozenset(
    [
        "para",
        "como",
        "solo",
        "este",
        "esta",
        "todo",
        "toda",
        "todos",
        "todas",
        "entre",
        "sobre",
        "desde",
        "hasta",
        "pero",
        "porque",
        "cuando",
        "donde",
        "mismo",
        "misma",
        "mediante",
        "segun",
        "tras",
        "ante",
        "bajo",
        "hacia",
        "junto",
        "partir",
        "puede",
        "pueden",
        "hace",
        "hacer",
        "sido",
        "estar",
        "estaba",
        "ese",
        "esa",
        "esos",
        "esas",
        "uno",
        "una",
        "unos",
        "unas",
        "otra",
        "otro",
        "otras",
        "otros",
        "sin",
        "con",
        "los",
        "las",
        "del",
        "la",
        "el",
        "de",
        "que",
        "en",
        "y",
        "no",
        "al",
        "lo",
        "se",
        "su",
        "sus",
        "por",
        "un",
        "ej",
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "are",
        "not",
        "you",
        "all",
        "any",
        "can",
        "will",
        "its",
        "was",
        "were",
    ]
)
_NOISE_TOKENS = frozenset(
    [
        "2019",
        "2020",
        "2021",
        "2022",
        "2023",
        "2024",
        "2025",
        "2026",
        "2027",
        "medido",
        "medida",
        "snapshot",
        "media",
        "alta",
        "baja",
        "pending",
        "blocked",
        "deferred",
        "completed",
        "completed-partial",
        "review",
        "awaiting",
        "manager",
        "ready",
        "ready-for-review",
    ]
)


def _tokens(text: str) -> set[str]:
    """Tokens F1 de un texto: tokenizador compartido + filtro de ruido declarado."""
    return {t for t in tokenize(text) if t not in _STOPWORDS and t not in _NOISE_TOKENS}


class Entry:
    """Una entrada comparable de la DB: fila de tabla, ficha de inbox o plan."""

    __slots__ = ("label", "source", "text", "universe")

    def __init__(self, label: str, text: str, universe: str, source: str) -> None:
        self.label = label
        self.text = text
        self.universe = universe
        self.source = source


class UniverseStats:
    """Denominador publicado por universo (Quality Bar: lista de saltados SIEMPRE)."""

    def __init__(self, surface: str, path: str) -> None:
        self.surface = surface
        self.path = path
        self.total = 0
        self.inspected = 0
        self.skipped: list[dict] = []
        self.empty = False
        self.note = ""

    def skip(self, where: str, reason: str) -> None:
        self.skipped.append({"where": where, "reason": reason})

    def to_dict(self) -> dict:
        return {
            "surface": self.surface,
            "path": self.path,
            "total": self.total,
            "inspected": self.inspected,
            "skipped_count": len(self.skipped),
            "skipped": self.skipped,
            "empty": self.empty,
            "note": self.note,
        }


# ---------------------------------------------------------------------------
# Carga de universos (solo lectura)
# ---------------------------------------------------------------------------


def _merge_table_lines(raw: str) -> list[str]:
    """Une continuaciones multi-linea de filas de tabla (misma regla que el
    lector de vecindad): una fila que empieza con `|` y las lineas de prosa
    siguientes se pegan a la fila vigente."""
    merged: list[str] = []
    for line in raw.splitlines():
        if line.lstrip().startswith("|"):
            merged.append(line.rstrip())
        elif merged and line.strip():
            merged[-1] += " " + line.strip()
    return merged


def load_backlog_rows(path: Path) -> tuple[list[Entry], UniverseStats]:
    """Filas de una tabla markdown de backlog/archive -> entradas con etiqueta.

    Reutiliza la logica de `find_similar_signals.load_backlog` (re-union de
    continuaciones, re-deteccion de cabecera por tabla, `_row_label`) pero
    conservando el DENOMINADOR: cuenta filas vistas, inspeccionadas y saltadas
    con su razon (una fila sin id parseable no desaparece en silencio).
    """
    stats = UniverseStats("backlog", str(path))
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ParseError(f"no se pudo leer {path}: {exc}") from exc

    merged = _merge_table_lines(raw)
    entries: list[Entry] = []
    ticket_col = title_col = None
    for lineno, line in enumerate(merged, 1):
        cells = _split_row(line)
        if not cells or all(set(c) <= {"-", ":", " "} for c in cells if c):
            continue  # separador |---|---|
        header = _header_columns(cells)
        if header is not None:
            ticket_col, title_col = header
            continue
        stats.total += 1
        if ticket_col is None or ticket_col >= len(cells):
            stats.skip(f"fila {lineno}", "fuera de tabla con cabecera (sin esquema)")
            continue
        label = _row_label(cells, ticket_col)
        if not label:
            stats.skip(f"fila {lineno}", "id de ticket no parseable en la fila")
            continue
        start = title_col if title_col is not None and title_col < len(cells) else 0
        text = " ".join(cells[start:])
        entries.append(Entry(label, text, "backlog", str(path)))
        stats.inspected += 1
    if not merged:
        stats.empty = True
        stats.note = "sin filas de tabla (content-empty declarado)"
    return entries, stats


_TICKET_BLOCK_RE = re.compile(r"^##\s+Ticket:\s*(.+?)\s*$", re.MULTILINE)
# El id FP del mundo real aparece en DOS formas (medido 2026-09-14): con slug
# (`FP-20260915-backlog-db-compare`) y pelado (`FP-20260914`); el slug es opcional.
_FP_ID_RE = re.compile(r"FP-\d{8}(?:-[A-Za-z0-9._-]+)*")
_H1_FP_RE = re.compile(rf"^#\s+.*?({_FP_ID_RE.pattern})", re.MULTILINE)


def load_inbox(dirpath: Path) -> tuple[list[Entry], UniverseStats]:
    """Fichas del buzon (`*.tickets.md`) -> una entrada por TICKET de la ficha.

    Dos formatos canonicos observados en la practica (medido 2026-09-14: 8 de 8
    `*.tickets.md` del buzon real; 7 usaban el H1):
    (a) ficha multi-ticket con bloques `## Ticket: <id>` (una entrada por bloque);
    (b) ficha de UN ticket con cabecera `# FP-... -- <titulo>` (una entrada).
    Si la ficha trae bloques `## Ticket:` se usan ESOS y se ignora su H1 (evita
    doble conteo del titulo del fichero); si no, se usa el H1 con id FP.
    Los `*.md` del buzon que no son fichas quedan SALTADOS con razon.
    """
    stats = UniverseStats("inbox", str(dirpath))
    if not dirpath.exists():
        raise ParseError(f"no existe el directorio de inbox {dirpath}")
    files = sorted(p for p in dirpath.iterdir() if p.is_file())
    if not files:
        stats.empty = True
        stats.note = "directorio vacio (content-empty declarado)"
        return [], stats
    entries: list[Entry] = []
    for fp in files:
        if not fp.name.endswith(".tickets.md"):
            stats.skip(fp.name, "no es ficha `*.tickets.md` (declarado)")
            continue
        stats.total += 1
        try:
            content = fp.read_text(encoding="utf-8")
        except OSError as exc:
            raise ParseError(f"no se pudo leer {fp}: {exc}") from exc
        blocks = list(_TICKET_BLOCK_RE.finditer(content))
        found = 0
        if blocks:
            for i, m in enumerate(blocks):
                heading = m.group(1).strip()
                end = blocks[i + 1].start() if i + 1 < len(blocks) else len(content)
                body = content[m.end() : end]
                fp_match = _FP_ID_RE.search(heading)
                label = fp_match.group(0) if fp_match else heading
                entries.append(Entry(label, heading + " " + body, "inbox", fp.name))
                found += 1
        else:
            h1 = _H1_FP_RE.search(content)
            if h1:
                entries.append(Entry(h1.group(1), content, "inbox", fp.name))
                found = 1
        stats.inspected += found
        if found == 0:
            stats.skip(fp.name, "sin bloque `## Ticket:` ni H1 `# FP-<id>` parseable")
    return entries, stats


def load_plans(dirpath: Path) -> tuple[list[Entry], UniverseStats]:
    """Planes de vuelo (`*.md`) -> una entrada por plan (label = stem del fichero)."""
    stats = UniverseStats("plans", str(dirpath))
    if not dirpath.exists():
        raise ParseError(f"no existe el directorio de planes {dirpath}")
    files = sorted(p for p in dirpath.iterdir() if p.is_file())
    if not files:
        stats.empty = True
        stats.note = "directorio vacio (content-empty declarado)"
        return [], stats
    entries: list[Entry] = []
    for fp in files:
        if fp.suffix != ".md":
            stats.skip(fp.name, "no es plan markdown (declarado)")
            continue
        stats.total += 1
        try:
            content = fp.read_text(encoding="utf-8")
        except OSError as exc:
            raise ParseError(f"no se pudo leer {fp}: {exc}") from exc
        entries.append(Entry(fp.stem, content, "plans", fp.name))
        stats.inspected += 1
    return entries, stats


_CONTRACT_HEADING_RE = re.compile(r"^##\s+(T-\S+)\s+--\s+(\S+)", re.MULTILINE)
_TICKET_ID_FIELD_RE = re.compile(r"\*\*ticket_id:\*\*\s*(\S+)")
_FLT_HEADER_RE = re.compile(r"\*\*Files Likely Touched")
_FLT_BULLET_RE = re.compile(r"^\s*-\s+`([^`]+)`\s*$")


def load_contracts(path: Path) -> tuple[dict[str, set[str]], UniverseStats]:
    """`ticket_contracts.md` -> mapa WOT-id -> set(paths FLT) + denominador.

    Resolucion de identidad T-* <-> WOT-* EXPLICITA: se toma del campo
    `ticket_id` del bloque. Un bloque sin `ticket_id` no se adivina: se salta
    con razon y cuenta en la cobertura declarada.
    """
    stats = UniverseStats("contracts", str(path))
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ParseError(f"no se pudo leer {path}: {exc}") from exc

    headings = list(_CONTRACT_HEADING_RE.finditer(content))
    if not headings:
        stats.empty = True
        stats.note = "sin bloques `## T-*` (content-empty declarado)"
        return {}, stats

    flt_map: dict[str, set[str]] = {}
    for idx, m in enumerate(headings):
        stats.total += 1
        t_id = m.group(1)
        end = headings[idx + 1].start() if idx + 1 < len(headings) else len(content)
        block = content[m.start() : end]
        tid_m = _TICKET_ID_FIELD_RE.search(block)
        if not tid_m:
            stats.skip(t_id, "bloque sin campo `ticket_id` (identidad no resoluble)")
            continue
        wot_id = tid_m.group(1).strip()
        paths: set[str] = set()
        flt_m = _FLT_HEADER_RE.search(block)
        if flt_m:
            for line in block[flt_m.end() :].splitlines():
                bm = _FLT_BULLET_RE.match(line)
                if bm:
                    paths.add(bm.group(1).strip())
                elif line.strip().startswith("- **"):
                    break  # siguiente campo del bloque
        flt_map[wot_id] = paths
        stats.inspected += 1
    return flt_map, stats


# ---------------------------------------------------------------------------
# Comparacion (indice invertido + metrica + componentes conexas)
# ---------------------------------------------------------------------------

# Metrica por defecto: Jaccard PONDERADO POR IDF (formula de
# `find_similar_signals.rank_neighbours`: idf = log(1+n/(1+df)) sobre el corpus
# comparado). MEDIDA 2026-09-14: el Jaccard PURO no puede capturar el calibrador
# real del triplicado (0.17-0.28) sin admitir megaclusters (140/106 miembros) de
# filas cortas del archive; el IDF los colapsa. `raw` queda disponible para
# comparacion declarada, nunca como default silencioso.
METRIC_DEFAULT = "idf"


def jaccard_raw(a: set[str], b: set[str]) -> float:
    """Jaccard sin ponderar: |A int B| / |A un B|. 0.0 si ambos son vacios."""
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def compute_idf(token_sets: list[set[str]]) -> tuple[dict[str, float], int]:
    """IDF suavizado y positivo sobre el corpus comparado (misma formula que
    `rank_neighbours`). Devuelve (idf, n) para que el informe declare el
    denominador con el que se calculo."""
    n = len(token_sets)
    df: dict[str, int] = {}
    for ts in token_sets:
        for t in ts:
            df[t] = df.get(t, 0) + 1
    return {w: math.log(1 + n / (1 + c)) for w, c in df.items()}, n


def jaccard_idf(a: set[str], b: set[str], idf: dict[str, float]) -> float:
    """Jaccard ponderado por IDF. 0.0 si no hay denominador positivo."""
    num = sum(idf.get(w, 0.0) for w in (a & b))
    den = sum(idf.get(w, 0.0) for w in (a | b))
    if den <= 0:
        return 0.0
    return num / den


def _candidate_indices(
    toks_i: set[str], index: dict[str, list[int]], i: int
) -> list[int]:
    """Indices j > i que comparten al menos un token con la entrada i."""
    cand: set[int] = set()
    for t in toks_i:
        cand.update(index[t])
    return [j for j in sorted(cand) if j > i]


def _scan_pairs(
    toks: list[set[str]], idf: dict[str, float], metric: str, threshold: float
) -> tuple[
    list[tuple[float, int, int, list[str]]],
    list[tuple[float, int, int, list[str]]],
]:
    """Puntua los pares candidatos y los separa por umbral (no deterministico: el
    orden final lo fijan los `sort` de `find_edges`)."""
    index: dict[str, list[int]] = defaultdict(list)
    for i, ts in enumerate(toks):
        for t in ts:
            index[t].append(i)

    edges: list[tuple[float, int, int, list[str]]] = []
    near: list[tuple[float, int, int, list[str]]] = []
    for i, ti in enumerate(toks):
        for j in _candidate_indices(ti, index, i):
            if metric == "idf":
                s = jaccard_idf(ti, toks[j], idf)
            else:
                s = jaccard_raw(ti, toks[j])
            if s <= 0:
                continue
            rec = (s, i, j, sorted(ti & toks[j])[:6])
            (edges if s >= threshold else near).append(rec)
    return edges, near


def find_edges(
    entries: list[Entry], threshold: float, metric: str = METRIC_DEFAULT
) -> tuple[
    list[tuple[float, int, int, list[str]]],
    list[tuple[float, int, int, list[str]]],
    dict[str, float],
    int,
]:
    """Devuelve (aristas >= umbral, cercanos < umbral, idf, n_corpus), por INDICES.

    Solo se puntuan pares que comparten >= 1 token (indice invertido). El orden
    de salida es determinista: por score desc y luego por indice. `metric`:
    "idf" (default) o "raw".
    """
    toks = [_tokens(e.text) for e in entries]
    if metric == "idf":
        idf, n_corpus = compute_idf(toks)
    else:
        idf, n_corpus = {}, len(toks)
    edges, near = _scan_pairs(toks, idf, metric, threshold)
    edges.sort(key=lambda r: (-r[0], r[1], r[2]))
    near.sort(key=lambda r: (-r[0], r[1], r[2]))
    return edges, near, idf, n_corpus


class _UnionFind:
    """Union-find con compresion de caminos sobre indices de entrada."""

    def __init__(self, size: int) -> None:
        self._parent = list(range(size))

    def find(self, x: int) -> int:
        parent = self._parent
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[ra] = rb


def build_lots(
    entries: list[Entry], edges: list[tuple[float, int, int, list[str]]]
) -> list[dict]:
    """Componentes conexas de las aristas = LOTES DE REVISION.

    Nota de no-transitividad: un lote agrupa por CONECTIVIDAD, no por cliques.
    Cada arista se lista por separado dentro del lote y el informe NUNCA sugiere
    fusionar la componente entera.
    """
    uf = _UnionFind(len(entries))
    for _, i, j, _ in edges:
        uf.union(i, j)

    by_root: dict[int, dict] = {}
    for idx, e in enumerate(entries):
        node = by_root.setdefault(uf.find(idx), {"members": [], "edges": []})
        node["members"].append(e.label)
    for s, i, j, shared in edges:
        by_root[uf.find(i)]["edges"].append(
            {
                "a": entries[i].label,
                "b": entries[j].label,
                "score": round(s, 4),
                "shared_terms": shared,
            }
        )
    lots = [
        {
            "members": sorted(node["members"]),
            "edges": sorted(node["edges"], key=lambda r: (-r["score"], r["a"], r["b"])),
        }
        for node in by_root.values()
        if len(node["members"]) > 1 and node["edges"]
    ]
    lots.sort(key=lambda lot: (-len(lot["members"]), lot["members"][0]))
    for n, lot in enumerate(lots, 1):
        lot["id"] = f"L{n}"
    return lots


def flt_overlaps(lots: list[dict], flt_map: dict[str, set[str]]) -> list[dict]:
    """Solape de touched-paths por par de lote (senal complementaria, NO arista)."""
    out: list[dict] = []
    for lot in lots:
        for edge in lot["edges"]:
            a, b = edge["a"], edge["b"]
            pa, pb = flt_map.get(a), flt_map.get(b)
            if not pa or not pb:
                continue
            inter = sorted(pa & pb)
            if not inter:
                continue
            out.append(
                {
                    "a": a,
                    "b": b,
                    "score": edge["score"],
                    "paths": inter,
                    "ratio_menor": round(len(inter) / min(len(pa), len(pb)), 4),
                }
            )
    out.sort(key=lambda r: (-r["score"], r["a"], r["b"]))
    return out


# ---------------------------------------------------------------------------
# Informe
# ---------------------------------------------------------------------------


def resolve_head_sha(explicit: str | None, git_root: str | None) -> tuple[str, str]:
    """Sello head-sha. Devuelve (sha, origen); nunca inventa un sha."""
    if explicit:
        return explicit, "explicit"
    cwd = git_root or "."
    try:
        proc = subprocess.run(  # noqa: S603 - argv constante, sin input externo
            ["git", "-C", cwd, "rev-parse", "HEAD"],  # noqa: S607 - git del PATH
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return "unavailable", f"git no ejecutable: {exc}"
    if proc.returncode != 0:
        return "unavailable", f"git rev-parse rc={proc.returncode}"
    return proc.stdout.strip(), f"git -C {cwd} rev-parse HEAD"


def build_result(
    entries: list[Entry],
    universes: list[UniverseStats],
    edges: list[tuple[float, int, int, list[str]]],
    near: list[tuple[float, int, int, list[str]]],
    flt_map: dict[str, set[str]],
    contracts_stats: UniverseStats | None,
    threshold: float,
    top_near: int,
    head_sha: str,
    head_origin: str,
    metric: str = METRIC_DEFAULT,
    idf_n: int = 0,
) -> dict:
    lots = build_lots(entries, edges)
    near_top = [
        {
            "a": entries[i].label,
            "b": entries[j].label,
            "score": round(s, 4),
            "shared_terms": shared,
        }
        for s, i, j, shared in near[:top_near]
    ]
    contracts_block = None
    if contracts_stats is not None:
        contracts_block = {
            "path": contracts_stats.path,
            "blocks_total": contracts_stats.total,
            "blocks_resolved": contracts_stats.inspected,
            "skipped": contracts_stats.skipped,
            "flt_entries": {k: sorted(v) for k, v in sorted(flt_map.items())},
        }
    seen: dict[str, int] = {}
    for e in entries:
        seen[e.label] = seen.get(e.label, 0) + 1
    duplicate_labels = sorted(k for k, c in seen.items() if c > 1)
    return {
        "schema": SCHEMA,
        "head_sha": head_sha,
        "head_sha_origin": head_origin,
        "threshold": threshold,
        "entries_total": len(entries),
        "duplicate_labels": duplicate_labels,
        "universes": [u.to_dict() for u in universes],
        "lots": lots,
        "lots_count": len(lots),
        "edges_count": len(edges),
        "near": near_top,
        "flt_overlaps": flt_overlaps(lots, flt_map),
        "contracts": contracts_block,
        "criteria": {
            "threshold_default": UMBRAL_DEFAULT,
            "threshold_used": threshold,
            "metric": metric,
            "idf_corpus_n": idf_n if metric == "idf" else None,
            "note": (
                "score = solape de VOCABULARIO (Jaccard ponderado IDF por defecto), "
                "no equivalencia semantica; lotes = componentes conexas (cada par se "
                "juzga por separado); el umbral es una politica de corte con el "
                "barrido publicado en el docstring"
            ),
        },
    }


def _render_header(result: dict) -> list[str]:
    """Cabecera del informe (schema, sello, umbral, metrica, conteos)."""
    lines = [
        "# backlog db compare -- lotes de revision",
        "",
        f"- schema: `{result['schema']}`",
        f"- head_sha: `{result['head_sha']}` ({result['head_sha_origin']})",
        f"- threshold: `{result['threshold']}` | metrica: "
        f"`{result['criteria']['metric']}`",
        f"- entradas comparadas: `{result['entries_total']}`",
    ]
    if result.get("duplicate_labels"):
        lines.append(
            f"- labels duplicados entre superficies (entradas distintas, mismo id): "
            f"{', '.join(result['duplicate_labels'])}"
        )
    lines.append(
        f"- aristas: `{result['edges_count']}`; lotes: `{result['lots_count']}`"
    )
    lines.append("")
    return lines


def _render_universes(result: dict) -> list[str]:
    """Denominador declarado por universo (con su lista de saltados)."""
    lines = ["## Universos (denominador declarado)", ""]
    for u in result["universes"]:
        lines.append(
            f"- {u['surface']}: `{u['path']}` -> total={u['total']} "
            f"inspeccionadas={u['inspected']} saltadas={u['skipped_count']}"
            + (f" ({u['note']})" if u["note"] else "")
        )
        lines.extend(
            f"    - saltada: {s['where']} -- {s['reason']}" for s in u["skipped"][:20]
        )
        if len(u["skipped"]) > 20:
            lines.append(
                f"    - ... {len(u['skipped']) - 20} saltada(s) mas en el JSON"
            )
    contracts = result.get("contracts")
    if contracts:
        lines.append(
            f"- contracts: `{contracts['path']}` -> bloques={contracts['blocks_total']} "
            f"resueltos={contracts['blocks_resolved']} "
            f"saltados={len(contracts['skipped'])}"
        )
        lines.extend(
            f"    - saltada: {s['where']} -- {s['reason']}"
            for s in contracts["skipped"]
        )
    lines.append("")
    return lines


def _render_lots(result: dict) -> list[str]:
    """Lotes de revision: componente, miembros y cada par con su score."""
    lines = [
        f"## LOTES DE REVISION ({result['lots_count']})",
        "",
        "Un lote es una COMPONENTE CONEXA, no una unidad fusionable: cada par se "
        "juzga por separado (la similitud no es transitiva).",
        "",
    ]
    if not result["lots"]:
        lines.append("Sin lotes en este umbral. (NO certifica ausencia de duplicados:")
        lines.append(
            "vocabulario distinto escapa al score; el juicio sigue siendo tuyo.)"
        )
    for lot in result["lots"]:
        lines.append(f"### {lot['id']} -- {len(lot['members'])} miembros")
        lines.append(f"- miembros: {', '.join(lot['members'])}")
        lines.extend(
            f"- par: {e['a']} <-> {e['b']} | score={e['score']} | "
            f"{', '.join(e['shared_terms'])}"
            for e in lot["edges"]
        )
        lines.append("")
    return lines


def _render_tail(result: dict) -> list[str]:
    """Cercanos bajo umbral, solape FLT y bloque de criterio."""
    lines = [
        f"## CERCANOS (no alcanzan el umbral, top {len(result['near'])})",
        "",
    ]
    lines.extend(
        f"- {e['a']} <-> {e['b']} | score={e['score']}" for e in result["near"]
    )
    lines.append("")
    lines.append("## SOLAPE DE TOUCHED-PATHS (senal complementaria, NO arista)")
    lines.append("")
    if not result["flt_overlaps"]:
        lines.append(
            "Sin solapes de FLT entre pares de lote (cobertura de contratos "
            "declarada arriba)."
        )
    lines.extend(
        f"- {o['a']} <-> {o['b']} | ratio={o['ratio_menor']} | "
        f"paths: {', '.join(o['paths'])}"
        for o in result["flt_overlaps"]
    )
    lines.append("")
    lines.append("## CRITERIO")
    lines.append("")
    lines.append(
        f"- umbral usado: `{result['criteria']['threshold_used']}` "
        f"(default del modulo: `{result['criteria']['threshold_default']}`)"
    )
    lines.append(
        f"- metrica: `{result['criteria']['metric']}`"
        + (
            f" (IDF sobre n={result['criteria']['idf_corpus_n']} entradas)"
            if result["criteria"]["metric"] == "idf"
            else ""
        )
    )
    lines.append(f"- {result['criteria']['note']}")
    lines.append("")
    return lines


def render_md(result: dict) -> str:
    """Informe markdown deterministico (sin timestamps)."""
    lines = _render_header(result)
    lines.extend(_render_universes(result))
    lines.extend(_render_lots(result))
    lines.extend(_render_tail(result))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Compare global entrada-vs-entrada de la DB del backlog: indice "
            "invertido + Jaccard ponderado IDF (--metric raw para el puro) + "
            "solape de touched-paths -> LOTES DE REVISION por no-transitividad. "
            "Read-only; genera senal, nunca decide fusiones."
        )
    )
    p.add_argument(
        "--backlog",
        type=Path,
        action="append",
        default=None,
        help="Tabla markdown de backlog/archive (repetible).",
    )
    p.add_argument(
        "--inbox",
        type=Path,
        default=None,
        help="Directorio de fichas (`*.tickets.md`).",
    )
    p.add_argument(
        "--queued",
        type=Path,
        default=None,
        help="Directorio de planes queued (`*.md`).",
    )
    p.add_argument(
        "--in-flight",
        type=Path,
        default=None,
        help="Directorio de planes in_flight (`*.md`).",
    )
    p.add_argument(
        "--contracts",
        type=Path,
        default=None,
        help="ticket_contracts.md (mapa T-* <-> WOT-* + FLT).",
    )
    p.add_argument(
        "--threshold",
        type=float,
        default=UMBRAL_DEFAULT,
        help=f"Umbral de score (default medido {UMBRAL_DEFAULT}).",
    )
    p.add_argument(
        "--metric",
        choices=("idf", "raw"),
        default=METRIC_DEFAULT,
        help="Metrica de aristas: idf (default, Jaccard ponderado) o raw.",
    )
    p.add_argument(
        "--top-near",
        type=int,
        default=TOP_NEAR_DEFAULT,
        help=f"Pares cercanos bajo umbral a publicar (default {TOP_NEAR_DEFAULT}).",
    )
    p.add_argument("--head-sha", default=None, help="Sello head-sha explicito.")
    p.add_argument(
        "--git-root", default=None, help="Repo del que derivar head-sha (default: cwd)."
    )
    p.add_argument("--out", type=Path, default=None, help="Informe markdown.")
    p.add_argument("--out-json", type=Path, default=None, help="Informe JSON.")
    p.add_argument(
        "--json", action="store_true", help="Imprime el JSON a stdout (maquina)."
    )
    return p


def _collect_universes(
    args: argparse.Namespace,
) -> tuple[list[Entry], list[UniverseStats], dict[str, set[str]], UniverseStats | None]:
    entries: list[Entry] = []
    universes: list[UniverseStats] = []
    for path in args.backlog or []:
        rows, stats = load_backlog_rows(path)
        entries += rows
        universes.append(stats)
    if args.inbox:
        rows, stats = load_inbox(args.inbox)
        entries += rows
        universes.append(stats)
    if args.queued:
        rows, stats = load_plans(args.queued)
        entries += rows
        universes.append(stats)
    if args.in_flight:
        rows, stats = load_plans(args.in_flight)
        entries += rows
        universes.append(stats)
    flt_map: dict[str, set[str]] = {}
    contracts_stats = None
    if args.contracts:
        flt_map, contracts_stats = load_contracts(args.contracts)
    return entries, universes, flt_map, contracts_stats


def _check_output_collision(args: argparse.Namespace) -> str | None:
    """El unico fallo de escritura posible se caza ANTES de computar/escribir."""
    inputs: list[Path] = []
    inputs += list(args.backlog or [])
    for d in (args.inbox, args.queued, args.in_flight):
        if d:
            inputs.append(d)
    if args.contracts:
        inputs.append(args.contracts)
    outs = [o for o in (args.out, args.out_json) if o is not None]
    if not outs:
        return None
    resolved_inputs = {p.resolve() for p in inputs}
    for out in outs:
        if out.resolve() in resolved_inputs:
            return (
                f"--out/--out-json resuelve a una ENTRADA ({out}); un recolector "
                "read-only no sobrescribe la DB: aborta antes de escribir"
            )
    return None


def _fail_closed_message(
    universes: list[UniverseStats], contracts_stats: UniverseStats | None
) -> str | None:
    """Fail-closed: un universo con CONTENIDO que no se inspecciono NO es 'sin
    lotes'. Devuelve el mensaje de error o None si todo esta inspeccionado."""
    for u in universes + ([contracts_stats] if contracts_stats else []):
        if u and u.total > 0 and u.inspected == 0:
            return (
                f"universo {u.surface} `{u.path}` tiene total={u.total} pero "
                "inspeccionadas=0 (fail-closed; ver saltados)"
            )
    return None


def _print_summary(
    result: dict,
    universes: list[UniverseStats],
    entries: list[Entry],
    edges: list[tuple[float, int, int, list[str]]],
    head_sha: str,
    args: argparse.Namespace,
) -> None:
    """Resumen humano a stdout (el json va por --json/--out-json)."""
    print(
        f"[db-compare] head={head_sha} metric={args.metric} "
        f"threshold={args.threshold} entradas={len(entries)} "
        f"aristas={len(edges)} lotes={result['lots_count']}"
    )
    for u in universes:
        print(
            f"[db-compare]   {u.surface}: total={u.total} "
            f"inspeccionadas={u.inspected} saltadas={len(u.skipped)} "
            f"{'(vacio declarado)' if u.empty else ''}"
        )
    for lot in result["lots"][:10]:
        print(f"[db-compare]   {lot['id']}: {', '.join(lot['members'])}")
    if result["lots_count"] > 10:
        print(
            f"[db-compare]   ... {result['lots_count'] - 10} lote(s) mas en el informe"
        )


def _emit_reports(args: argparse.Namespace, md_text: str, json_text: str) -> int | None:
    """Escribe md/json en las rutas declaradas. Devuelve 2 si no se pudo escribir
    (fail-closed), None si todo fue bien."""
    try:
        if args.out:
            args.out.write_text(md_text, encoding="utf-8", newline="\n")
        if args.out_json:
            args.out_json.write_text(json_text, encoding="utf-8", newline="\n")
    except OSError as exc:
        print(f"[db-compare] ERROR al escribir salida: {exc}", file=sys.stderr)
        return 2
    return None


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not any((args.backlog, args.inbox, args.queued, args.in_flight, args.contracts)):
        print(
            "[db-compare] ERROR: declara al menos un universo (--backlog/--inbox/"
            "--queued/--in-flight; --contracts es complementario).",
            file=sys.stderr,
        )
        return 2

    collision = _check_output_collision(args)
    if collision:
        print(f"[db-compare] ERROR: {collision}", file=sys.stderr)
        return 2

    try:
        entries, universes, flt_map, contracts_stats = _collect_universes(args)
    except ParseError as exc:
        print(f"[db-compare] ERROR de parseo: {exc}", file=sys.stderr)
        return 2

    fail_closed = _fail_closed_message(universes, contracts_stats)
    if fail_closed:
        print(f"[db-compare] ERROR: {fail_closed}", file=sys.stderr)
        return 2

    if not entries:
        print(
            "[db-compare] ERROR: cero entradas comparables en los universos "
            "declarados (content-empty); el informe no puede emitirse.",
            file=sys.stderr,
        )
        return 2

    if args.threshold <= 0 or args.threshold > 1:
        print("[db-compare] ERROR: --threshold fuera de (0, 1].", file=sys.stderr)
        return 2

    head_sha, head_origin = resolve_head_sha(args.head_sha, args.git_root)
    edges, near, _idf, idf_n = find_edges(entries, args.threshold, args.metric)
    result = build_result(
        entries,
        universes,
        edges,
        near,
        flt_map,
        contracts_stats,
        args.threshold,
        max(0, args.top_near),
        head_sha,
        head_origin,
        metric=args.metric,
        idf_n=idf_n,
    )

    md_text = render_md(result)
    json_text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    write_error = _emit_reports(args, md_text, json_text)
    if write_error is not None:
        return write_error

    if args.json:
        sys.stdout.write(json_text)
    else:
        _print_summary(result, universes, entries, edges, head_sha, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
