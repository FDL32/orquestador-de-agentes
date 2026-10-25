#!/usr/bin/env python3
"""Sonda PRE-REGISTRADA de O6b: carril "Importantes" del indice de arranque (WOT-2026-124h).

Solo lectura. NO modifica `bus/memory_loader.py`: el indice de produccion NO cambia
(DoD c). Mide HOY frente a O6b con el render REAL (`format_memory_index`) y decide
con el criterio de abajo, fijado por el Manager ANTES de cualquier corte medible
(el primero cierra el 2026-11-25). No se ajusta tras ver datos: un cambio de
criterio exige un pre-registro nuevo.

Criterio pre-registrado (literal):

- Corpus en un corte t: la UNION del archive portable del motor y del destino
  construida como `_read_portable_archive` (destino = activo con
  `_origin="local"`; del motor se quitan las entradas cuyo `dedup_key` ya esta en
  el destino, `_origin="motor"`), y solo entradas con `timestamp < t`. Tier local
  vacio (`local_text=""`; limite declarado).
- HOY(t) = `format_memory_index(corpus_t)` real, presupuesto `INDEX_BUDGET_CHARS`.
- O6b(t): (1) Estables = las que muestra HOY(t) en su seccion Estables.
  (2) Importantes = hasta `O6B_IMPORTANT = 8` lecciones vigentes con `id`,
  `is_lesson`, `timestamp < t - 7 dias` (las frescas NO compiten aqui), no
  Estables, con al menos 1 CITA anterior a t; orden (citas desc, timestamp desc);
  una por `topic`; cuota por origen mitad/mitad con sobrante al otro (`by_origin`
  de probe9). (3) Bloque `## Importantes (citadas por otras lecciones)` con
  `index_line` de cada una. (4) Resto = `format_memory_index(corpus_t sin las
  Importantes, budget=INDEX_BUDGET_CHARS - len(bloque) - 1)` con
  `INDEX_FLOOR_TOTAL=18` e `INDEX_FLOOR_PER_ORIGIN=9` aplicados SOLO durante esa
  llamada (parche de atributos del modulo restaurado en `finally`). (5) El bloque
  se inserta tras la seccion Estables (o tras la cabecera si no hay). El render
  final de O6b debe medir `<= INDEX_BUDGET_CHARS`.
- CITA: un `id` (regex `obs-[a-z0-9][a-z0-9-]*[a-z0-9]`) de una leccion vigente
  mencionado en el `signal` de OTRA leccion vigente; sin autocita; no cuentan
  citas hechas por o dirigidas a refutadas/supersedidas. Fecha de la cita =
  timestamp de la leccion que cita.
- Mostradas = ids de las lineas `- <id>:` del render.
- OBJETIVO(t) = citas con fecha en `[t, t+30d)` a lecciones con `timestamp < t`
  (con repeticion, como probe9). Acierto = objetivo mostrado. FRESCAS(t) =
  lecciones vigentes con id, `is_lesson` y `timestamp` en `[t-7d, t)`.
- CORTES (filtro de corte inicial): `O6B_START = 2026-10-26T00:00:00Z`;
  `t_k = O6B_START + 30*k dias`, k >= 0, y solo si `t_k + 30 dias <= now`
  (ventana completa). Ningun corte anterior a `O6B_START` se evalua NUNCA.
  Corte valido = objetivo >= 1.
- SUFICIENCIA: >= 2 cortes validos Y suma de objetivo >= 20. Si no: veredicto
  `INSUFICIENTE` (sin decision; el indice no cambia; se vuelve a medir mas tarde).
- CUMPLE si y solo si: (a) suma de aciertos O6b > suma de aciertos HOY; (b) en
  CADA corte valido, aciertos O6b >= aciertos HOY; (c) FRESCURA, limite explicito
  de perdida frente a HOY: en cada corte valido, frescas mostradas por O6b >=
  frescas mostradas por HOY - max(2, ceil(0.15 * frescas mostradas por HOY)), y en
  el agregado frescas O6b >= 0.90 * frescas HOY. Si no: `NO CUMPLE` (se cierra sin
  cambio).

Precisiones de implementacion (no cambian el criterio): "vigente" es el estado
del archive al MEDIR (como probe9); una entrada sin `timestamp` interpretable no
entra en ningun corte; un `topic` ausente cuenta como topic vacio.

Uso: python scripts/measure_index_o6b.py [--motor-root P] [--project-root P]
     [--now ISO] [--json]
rc 0 siempre que mida (el veredicto va en la salida); rc 2 por argumentos o
rutas invalidas.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import re
import sys
from collections import Counter
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from bus import memory_loader as ml  # noqa: E402
from bus.portable_memory_archive import (  # noqa: E402
    CorruptArchiveError,
    dedup_key,
    is_lesson,
    read_archive_observations,
)


O6B_START = datetime(2026, 10, 26, tzinfo=timezone.utc)
O6B_IMPORTANT = 8
O6B_FLOOR_TOTAL = 18
O6B_FLOOR_PER_ORIGIN = 9
WINDOW = timedelta(days=30)
FRESH = timedelta(days=7)
MIN_VALID_CUTS = 2
MIN_OBJETIVO = 20
FRESH_LOSS_ABS = 2
FRESH_LOSS_REL = 0.15
FRESH_AGGREGATE = 0.90
IMPORTANT_HEADER = "## Importantes (citadas por otras lecciones)"

_STALE = {"refuted", "superseded"}
_CITE_RE = re.compile(r"obs-[a-z0-9][a-z0-9-]*[a-z0-9]")
_SHOWN_RE = re.compile(r"^- (obs-[a-z0-9][a-z0-9-]*[a-z0-9]):", re.MULTILINE)

Entry = dict[str, Any]


def _ts(entry: Entry) -> datetime | None:
    """UTC timestamp of an archive entry.

    Before: ``entry`` is a dict (any ``timestamp`` value).
    During: parses ISO-8601 (``Z`` accepted); a naive value is taken as UTC.
    After: aware UTC datetime, or None if absent/not text/unparseable. Never raises.
    """
    raw = entry.get("timestamp")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def build_union(motor_root: Path, project_root: Path) -> list[Entry]:
    """Archive union as `_read_portable_archive` builds it for a destination.

    Before: both roots exist; their archives may be empty.
    During: reads both archives; drops motor entries whose ``dedup_key`` the
        destination already has; tags ``_origin`` (``local`` / ``motor``).
    After: shallow-copied entries. DELIBERATE divergence from
        `_read_portable_archive` (codex review of f969b620, MAJOR 1): the boot
        index degrades a corrupt or unreadable archive to ``[]`` so a session
        still starts; a MEASUREMENT on that partial corpus would be a false
        reading of a pre-registered criterion, so here
        ``CorruptArchiveError`` propagates and `main` turns it into rc 2.
    """
    active = read_archive_observations(project_root)
    motor = read_archive_observations(motor_root)
    seen = {dedup_key(e) for e in active}
    motor = [e for e in motor if dedup_key(e) not in seen]
    return [{**e, "_origin": "local"} for e in active] + [
        {**e, "_origin": "motor"} for e in motor
    ]


def _vigent_lessons(union: list[Entry]) -> dict[str, Entry]:
    """Vigent lessons of a corpus, by id.

    Before: ``union`` entries from `build_union` (or a time slice of it).
    During: like the renderer (`_dedup_newest` then the stale split), first
        keeps the NEWEST copy of each text ``id`` with an interpretable
        timestamp, then drops it unless it is a lesson and not
        refuted/superseded (codex review of 06b5e896, MINOR 1).
    After: ``id`` -> entry. Never raises.
    """
    newest: dict[str, Entry] = {}
    for e in union:
        eid, ts = e.get("id"), _ts(e)
        if not isinstance(eid, str) or not eid or ts is None:
            continue
        if eid not in newest or ts > _ts(newest[eid]):
            newest[eid] = e
    return {
        eid: e
        for eid, e in newest.items()
        if is_lesson(e) and e.get("status") not in _STALE
    }


def citation_edges(vigent: dict[str, Entry]) -> list[tuple[datetime, str]]:
    """Every CITA of the criterion.

    Before: ``vigent`` from `_vigent_lessons` (stale entries already out, so
        citations made by or aimed at them never appear).
    During: regex over each ``signal``; one edge per distinct cited id per
        citing lesson; self-citations dropped.
    After: list of (date of the citing lesson, cited id).
    """
    return [
        (_ts(e), cited)
        for eid, e in vigent.items()
        for cited in set(_CITE_RE.findall(str(e.get("signal") or "")))
        if cited != eid and cited in vigent
    ]


def shown_ids(render: str) -> set[str]:
    """Shown lessons of a render.

    Before: ``render`` is index text (HOY or O6b).
    During: matches only the LEADING ``- <id>:`` of each line.
    After: set of ids; ids quoted inside a signal or topic lines do not count.
    """
    return set(_SHOWN_RE.findall(render))


def _stable_ids(render: str) -> set[str]:
    """Estables of HOY(t), step (1) of the criterion.

    Before: ``render`` is a `format_memory_index` output.
    During: collects the shown ids between ``## Estables`` and the next heading.
    After: set of ids (empty when the render has no Estables section).
    """
    out: set[str] = set()
    inside = False
    for line in render.splitlines():
        if line.startswith("## "):
            inside = line.startswith("## Estables")
            continue
        if inside:
            out |= shown_ids(line)
    return out


def _origin(entry: Entry) -> str:
    return "destino" if entry.get("_origin") == "local" else "motor"


def by_origin(ranked: list[Entry], n: int) -> list[Entry]:
    """Origin quota of probe9 (``by_origin``).

    Before: ``ranked`` is already in priority order; ``n >= 0``.
    During: each origin gets up to ``n // 2``; what one cannot fill goes to the other.
    After: at most ``n`` entries, motor block first, each block in ``ranked`` order.
    """
    groups = {o: [e for e in ranked if _origin(e) == o] for o in ("motor", "destino")}
    take = {o: min(len(g), n // 2) for o, g in groups.items()}
    rest = n - sum(take.values())
    for o in ("motor", "destino"):
        extra = min(rest, len(groups[o]) - take[o])
        take[o] += extra
        rest -= extra
    return [e for o in ("motor", "destino") for e in groups[o][: take[o]]]


def select_important(
    corpus_t: list[Entry],
    edges: list[tuple[datetime, str]],
    stable: set[str],
    t: datetime,
) -> list[Entry]:
    """Importantes of O6b(t), step (2) of the criterion.

    Before: ``corpus_t`` holds only entries older than ``t``; ``edges`` from
        `citation_edges`; ``stable`` from `_stable_ids` of HOY(t).
    During: vigent lessons older than ``t - 7d``, not stable, with >= 1 citation
        before ``t``; ordered by (citations, timestamp) desc; one per topic.
    After: at most ``O6B_IMPORTANT`` entries after the origin quota.
    """
    past = Counter(cited for date, cited in edges if date < t)
    pool = [
        e
        for e in _vigent_lessons(corpus_t).values()
        if _ts(e) < t - FRESH and e["id"] not in stable and past[e["id"]] >= 1
    ]
    pool.sort(key=lambda e: (past[e["id"]], _ts(e)), reverse=True)
    seen_topics: set[str] = set()
    one_per_topic = []
    for e in pool:
        topic = str(e.get("topic") or "")
        if topic not in seen_topics:
            seen_topics.add(topic)
            one_per_topic.append(e)
    return by_origin(one_per_topic, O6B_IMPORTANT)


@contextlib.contextmanager
def _o6b_floors() -> Iterator[None]:
    """Floors of O6b for ONE render; the module values come back in ``finally``."""
    saved = (ml.INDEX_FLOOR_TOTAL, ml.INDEX_FLOOR_PER_ORIGIN)
    ml.INDEX_FLOOR_TOTAL, ml.INDEX_FLOOR_PER_ORIGIN = (
        O6B_FLOOR_TOTAL,
        O6B_FLOOR_PER_ORIGIN,
    )
    try:
        yield
    finally:
        ml.INDEX_FLOOR_TOTAL, ml.INDEX_FLOOR_PER_ORIGIN = saved


def render_o6b(corpus_t: list[Entry], important: list[Entry]) -> str:
    """O6b(t) render, steps (3)-(5) of the criterion.

    Before: ``important`` comes from `select_important` over the same corpus.
    During: renders the rest with the real `format_memory_index` and the O6b
        floors, then inserts the Importantes block after Estables.
    After: the render; ``len <= INDEX_BUDGET_CHARS`` by construction.
    """
    block = "\n".join([IMPORTANT_HEADER, *(ml.index_line(e) for e in important)])
    ids = {e["id"] for e in important}
    rest_corpus = [e for e in corpus_t if e.get("id") not in ids]
    with _o6b_floors():
        rest = ml.format_memory_index(
            rest_corpus,
            local_text="",
            budget=ml.INDEX_BUDGET_CHARS - len(block) - 1,
        )
    lines = rest.split("\n")
    at = min(2, len(lines))  # tras OPEN + cabecera si no hay Estables
    for i, line in enumerate(lines):
        if line.startswith("## Estables"):
            at = i + 1
            while at < len(lines) and lines[at].startswith("- "):
                at += 1
            break
    return "\n".join([*lines[:at], block, *lines[at:]])


def measure(union: list[Entry], now: datetime) -> list[dict[str, Any]]:
    """Evaluate the cuts of the criterion.

    Before: ``union`` from `build_union`; ``now`` aware UTC.
    During: for ``t = O6B_START + 30k days`` while ``t + 30d <= now``: slices the
        corpus, renders HOY and O6b with the real renderer, counts objective,
        hits and fresh lessons. Pure (no I/O, no state left behind).
    After: one row per evaluated cut (including cuts with objective 0).
    """
    vigent = _vigent_lessons(union)
    edges = citation_edges(vigent)
    rows = []
    t = O6B_START
    while t + WINDOW <= now:
        corpus_t = [e for e in union if (ts := _ts(e)) is not None and ts < t]
        objetivo = [
            cited
            for date, cited in edges
            if t <= date < t + WINDOW and _ts(vigent[cited]) < t
        ]
        hoy = ml.format_memory_index(
            corpus_t, local_text="", budget=ml.INDEX_BUDGET_CHARS
        )
        o6b = render_o6b(
            corpus_t, select_important(corpus_t, edges, _stable_ids(hoy), t)
        )
        hoy_shown, o6b_shown = shown_ids(hoy), shown_ids(o6b)
        fresh = [i for i, e in vigent.items() if t - FRESH <= _ts(e) < t]
        rows.append(
            {
                "t": t.isoformat(),
                "objetivo": len(objetivo),
                "aciertos_hoy": sum(c in hoy_shown for c in objetivo),
                "aciertos_o6b": sum(c in o6b_shown for c in objetivo),
                "frescas": len(fresh),
                "frescas_hoy": sum(i in hoy_shown for i in fresh),
                "frescas_o6b": sum(i in o6b_shown for i in fresh),
                "len_hoy": len(hoy),
                "len_o6b": len(o6b),
            }
        )
        t += WINDOW
    return rows


def verdict(rows: list[dict[str, Any]]) -> tuple[str, list[str]]:
    """Pre-registered decision.

    Before: ``rows`` from `measure`.
    During: keeps valid cuts (objective >= 1); applies SUFICIENCIA, then (a), (b), (c).
    After: (``INSUFICIENTE`` | ``NO CUMPLE`` | ``CUMPLE``, reasons); CUMPLE has none.
    """
    valid = [r for r in rows if r["objetivo"] >= 1]
    total = sum(r["objetivo"] for r in valid)
    reasons = []
    if len(valid) < MIN_VALID_CUTS:
        reasons.append(f"{len(valid)} corte(s) valido(s) < {MIN_VALID_CUTS}")
    if total < MIN_OBJETIVO:
        reasons.append(f"objetivo total {total} < {MIN_OBJETIVO}")
    if reasons:
        return "INSUFICIENTE", reasons
    hoy = sum(r["aciertos_hoy"] for r in valid)
    o6b = sum(r["aciertos_o6b"] for r in valid)
    if not o6b > hoy:
        reasons.append(f"(a) aciertos O6b {o6b} no > HOY {hoy}")
    for r in valid:
        if r["aciertos_o6b"] < r["aciertos_hoy"]:
            reasons.append(
                f"(b) corte {r['t']}: O6b {r['aciertos_o6b']} < HOY {r['aciertos_hoy']}"
            )
        allowed = max(FRESH_LOSS_ABS, math.ceil(FRESH_LOSS_REL * r["frescas_hoy"]))
        if r["frescas_o6b"] < r["frescas_hoy"] - allowed:
            reasons.append(
                f"(c) corte {r['t']}: frescas O6b {r['frescas_o6b']} < HOY "
                f"{r['frescas_hoy']} - {allowed}"
            )
    fresh_hoy = sum(r["frescas_hoy"] for r in valid)
    fresh_o6b = sum(r["frescas_o6b"] for r in valid)
    if fresh_o6b < FRESH_AGGREGATE * fresh_hoy:
        reasons.append(
            f"(c) agregado: frescas O6b {fresh_o6b} < {FRESH_AGGREGATE} * HOY {fresh_hoy}"
        )
    return ("NO CUMPLE", reasons) if reasons else ("CUMPLE", [])


def main(argv: list[str] | None = None) -> int:
    """Command line entry point.

    Before: ``argv`` as for argparse; the destination comes from
        ``--project-root`` or ``AGENT_PROJECT_ROOT``.
    During: validates roots and ``--now``, reads both archives, measures and
        prints the rows and the verdict (text or ``--json``). Read-only.
    After: rc 0 when it measured (the verdict is in the output); rc 2 on a
        missing/invalid root, an invalid ``--now`` or a corrupt archive.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--motor-root", type=Path, default=_REPO_ROOT)
    parser.add_argument("--project-root", type=Path, default=None)
    parser.add_argument("--now", default=None, help="ISO-8601 (por defecto, ahora UTC)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    project = args.project_root or (
        Path(os.environ["AGENT_PROJECT_ROOT"])
        if os.environ.get("AGENT_PROJECT_ROOT")
        else None
    )
    if project is None:
        print("error: falta --project-root (o AGENT_PROJECT_ROOT)", file=sys.stderr)
        return 2
    for label, root in (("--motor-root", args.motor_root), ("--project-root", project)):
        if not root.is_dir():
            print(f"error: {label} no es un directorio: {root}", file=sys.stderr)
            return 2
    now = datetime.now(timezone.utc)
    if args.now is not None:
        parsed = _ts({"timestamp": args.now})
        if parsed is None:
            print(f"error: --now no es ISO-8601: {args.now!r}", file=sys.stderr)
            return 2
        now = parsed
    try:
        union = build_union(args.motor_root, project)
    except CorruptArchiveError as exc:
        print(f"error: archive corrupto, no se mide: {exc}", file=sys.stderr)
        return 2
    rows = measure(union, now)
    result, reasons = verdict(rows)
    if args.json:
        print(
            json.dumps(
                {
                    "now": now.isoformat(),
                    "cortes": rows,
                    "veredicto": result,
                    "motivos": reasons,
                },
                ensure_ascii=False,
            )
        )
        return 0
    print(
        f"O6b (pre-registro WOT-2026-124h) | now {now.isoformat()} | cortes evaluados {len(rows)}"
    )
    for r in rows:
        print(
            f"  corte {r['t']}: objetivo {r['objetivo']} | aciertos HOY {r['aciertos_hoy']} O6b {r['aciertos_o6b']}"
            f" | frescas {r['frescas']} (HOY {r['frescas_hoy']}, O6b {r['frescas_o6b']}) | len {r['len_hoy']}/{r['len_o6b']}"
        )
    print(f"VEREDICTO: {result}" + (f" -- {'; '.join(reasons)}" if reasons else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
