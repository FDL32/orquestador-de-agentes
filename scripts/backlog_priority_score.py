#!/usr/bin/env python
"""Recolector de score TDS (Technical Debt Score) para desempatar el backlog.

Que protege
-----------
El backlog de este repo clasifica cada ticket en `Prioridad` (Alta/Media/Baja),
pero dentro de una misma categoria no hay ningun orden mecanico: con 110 filas
"Alta", decidir cual va primero queda a criterio manual sin evidencia numerica.
Este script produce una vista de desempate DENTRO de cada categoria, nunca un
reemplazo de la categorizacion humana.

Diseno completo, con las 14 correcciones de dos rondas de auditoria adversarial
(codex + subagente claude + gemma4 + qwen3.6, dos iteraciones):
``.agent/runtime/tmp/backlog_priority_system_design_v3.md`` (gitignored, no
versionado -- este docstring resume el contrato operativo; el diseno completo
con la justificacion de cada decision vive en ese fichero mientras no se
promueva a documentacion permanente).

CONTRATO DE AUTORIDAD (no negociable, mismo patron que collect_session_state.py
y backlog_reconcile.py)
-------------------------------------------------------------------------------
Este script RECOLECTA y PUNTUA; NUNCA decide que ticket implementar, NUNCA
escribe en ``backlog.md``, ``STATE.md`` ni el bus. Su salida es una vista
auxiliar de scoring, con el desglose de cada variable visible para que un
humano audite el numero antes de usarlo -- un TDS sin desglose no es
utilizable para decidir, solo para ordenar (mismo principio CEM que
"un exit 0 no basta, hace falta el artefacto").

Formula (ver docstring de ``compute_tds`` para la justificacion completa de
cada termino, incluida la correccion del bug de v1 donde el boost de
antiguedad invertia su efecto sobre scores negativos):

    base = S*2 + R_score_max*3 + D*1.5 - C*1.2
    dias_clamped = max(0, dias_desde_origen)
    boost = min(1.15, 1 + 0.03*ln(1+dias_clamped))
    TDS = max(0, base)*boost + min(0, base)

Before / During / After
------------------------
Before: ``--project-root`` apunta a un repo_destino existente con
    ``.agent/collaboration/backlog.md``. ``--triage-json`` es opcional.
During: lee ``backlog.md`` (+ ``_archive/backlog_done.md`` si existe) con las
    funciones REALES de ``backlog_db_compare`` (importadas, nunca copiadas) para
    calcular R; lee el propio texto de cada fila para derivar S, C, D con
    reglas de conversion declaradas explicitamente; parsea la fecha de
    ``Origen`` con fallback declarado si falla.
After: imprime JSON (o markdown con ``--format markdown``) con el TDS y el
    desglose completo por ticket, agrupado SIEMPRE por ``Prioridad`` primero
    (nunca un orden global que ignore la categorizacion humana). Exit 0 salvo
    fallo del propio recolector (ruta irresoluble, backlog.md ausente).
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import date, datetime
from pathlib import Path


MOTOR_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(MOTOR_ROOT / "scripts"))

from backlog_db_compare import (  # noqa: E402
    Entry,
    _compute_vecinos,
    build_lots,
    find_edges,
    load_backlog_rows,
)


UMBRAL_SIMILITUD = 0.12  # mismo umbral que backlog_admit.md / backlog_db_compare.py
BOOST_TECHO = 1.15
BOOST_TASA = 0.03

_KEYWORD_PATTERN = re.compile(
    r"\b(guard|gate|security|bloqueante|seguridad)\b", re.IGNORECASE
)
_ROW_PATTERN = re.compile(
    r"^\|\s*(Alta|Media|Baja)\s*\|\s*([A-Z]+-\d{4}-\d+[a-z]*)\s*\|(.*)\|\s*$"
)
_FLT_PATTERN = re.compile(r"`([^`]+\.[a-zA-Z0-9]+)`")
_ORIGEN_DATE_PATTERN = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")


class BacklogRow:
    """Una fila de la cola viva, con los campos crudos necesarios para el score."""

    __slots__ = ("depende_de", "prioridad", "ticket", "titulo_completo")

    def __init__(
        self, prioridad: str, ticket: str, titulo_completo: str, depende_de: str
    ) -> None:
        self.prioridad = prioridad
        self.ticket = ticket
        self.titulo_completo = titulo_completo
        self.depende_de = depende_de


def parse_live_backlog_rows(path: Path) -> list[BacklogRow]:
    """Filas de la cola viva con sus columnas crudas (Prioridad/Ticket/Titulo/Depende).

    Before: ``path`` existe y es un ``backlog.md`` con la tabla ``Vista rapida``
        (formato ``| Prioridad | Ticket | Titulo | Scope | Estado | Depende de |
        Origen | Reactivation |``).
    During: reutiliza el merge de continuaciones multilinea (mismo problema que
        resuelve ``_merge_table_lines`` en ``backlog_db_compare.py``): una fila
        de ticket puede ocupar varias lineas fisicas si el titulo contiene
        saltos de linea sueltos.
    After: devuelve una fila por ticket con id canonico (regex
        ``[A-Z]+-\\d{4}-\\d+[a-z]*``), sin inventar columnas que no existen.
    """
    raw = path.read_text(encoding="utf-8")
    merged: list[str] = []
    for line in raw.splitlines():
        if line.lstrip().startswith("|"):
            merged.append(line.rstrip())
        elif merged and line.strip():
            merged[-1] += " " + line.strip()

    rows: list[BacklogRow] = []
    for line in merged:
        cells = line.split("|")
        if len(cells) < 9:
            continue
        prioridad = cells[1].strip()
        ticket = cells[2].strip()
        if prioridad not in {"Alta", "Media", "Baja"}:
            continue
        if not re.fullmatch(r"[A-Z]+-\d{4}-\d+[a-z]*", ticket):
            continue
        titulo = cells[3].strip()
        depende_de = cells[6].strip() if len(cells) > 6 else ""
        rows.append(BacklogRow(prioridad, ticket, titulo, depende_de))
    return rows


def score_s(titulo: str) -> tuple[int, str]:
    """S -- Severidad/superficie, 1-5, segun conteo de rutas + palabra clave.

    Before: ``titulo`` es el texto completo de la celda Titulo de la fila.
    During: cuenta rutas entre backticks (``\\`archivo.py\\``` como proxy de
        Files Likely Touched citados en prosa) y busca palabras clave de
        superficie sensible.
    After: (S, evidencia). v3: ya NO usa ``shared_surfaces`` del DAG de triage
        -- se retiro tras confirmar que el contrato de ``backlog_triage.md``
        Fase 2 impide que un ticket aparezca en 2+ grupos por diseno (ver
        diseno v3, defecto #11).
    """
    rutas = set(_FLT_PATTERN.findall(titulo))
    n_rutas = len(rutas)
    tiene_keyword = bool(_KEYWORD_PATTERN.search(titulo))

    if n_rutas >= 4 and tiene_keyword:
        s, motivo = 5, f"{n_rutas} rutas + palabra clave de superficie sensible"
    elif n_rutas >= 4:
        s, motivo = 4, f"{n_rutas} rutas citadas"
    elif n_rutas >= 2 and tiene_keyword:
        s, motivo = 3, f"{n_rutas} rutas + palabra clave"
    elif (n_rutas == 1 and tiene_keyword) or (n_rutas >= 2 and not tiene_keyword):
        s, motivo = 2, f"{n_rutas} ruta(s), keyword={tiene_keyword}"
    else:
        s, motivo = 1, f"{n_rutas} ruta(s) citada(s), sin palabra clave"
    return s, motivo


def score_c(titulo: str) -> tuple[int, str, bool]:
    """C -- Coste de arreglo, 1-5, PESO NEGATIVO en la formula.

    Before: ``titulo`` es el texto completo de la celda Titulo (no hay acceso
        directo aqui a un ``work_plan.md`` de ``queued/`` -- esa correlacion
        queda como mejora futura declarada; esta version usa unicamente la
        longitud del propio texto del ticket en ``backlog.md`` como proxy).
    During: cuenta rutas citadas (mismo proxy que S) y longitud del texto como
        indicador de complejidad del DoD.
    After: (C, evidencia, no_estimado). ``no_estimado=True`` si no hay ninguna
        senal de rutas (texto puramente descriptivo, sin FLT citado).
    """
    rutas = set(_FLT_PATTERN.findall(titulo))
    n_rutas = len(rutas)
    longitud = len(titulo)

    if n_rutas == 0:
        if longitud < 400:
            return 3, f"sin rutas citadas, texto corto ({longitud} chars)", True
        if longitud < 1000:
            return 4, f"sin rutas citadas, texto largo ({longitud} chars)", True
        return 5, f"sin rutas citadas, texto muy largo ({longitud} chars)", True
    if n_rutas == 1:
        return 1, "1 ruta citada", False
    if n_rutas <= 3:
        return 2, f"{n_rutas} rutas citadas", False
    return 3, f"{n_rutas}+ rutas citadas", False


def score_d(ticket: str, all_rows: list[BacklogRow]) -> tuple[int, str]:
    """D -- Desbloqueo, 0-3, conteo REAL de filas vivas que dependen de ``ticket``.

    Before: ``all_rows`` son todas las filas vivas ya parseadas.
    During: match por WORD BOUNDARY sobre la columna ``Depende de`` ya
        extraida (no sobre el markdown crudo) buscando el id exacto de
        ``ticket``. FIX (auditoria adversarial codex, 2026-09-25): un
        ``ticket in r.depende_de`` por substring inflaba D con falsos
        positivos. Caso hipotetico de codex ("WOT-2026-010a" dentro de
        "WOT-2026-010aa") no existe hoy en el backlog real, pero el
        patron de fallo SI ocurre de verdad: un ID de FAMILIA sin sufijo
        (ej. "WOT-2026-014") es substring de CADA uno de sus miembros
        ("WOT-2026-014e", "WOT-2026-014n", ...). Medido: 39 pares reales
        de esta forma en el backlog vivo (grep de
        ``WOT-2026-\\d{3}[a-z]?`` cruzado por substring). Se reemplaza por
        un regex con \\b para exigir coincidencia de ID completo.
    After: (D saturado a 3, evidencia).
    """
    ticket_pattern = re.compile(rf"\b{re.escape(ticket)}\b")
    dependientes = [
        r.ticket
        for r in all_rows
        if r.ticket != ticket and ticket_pattern.search(r.depende_de)
    ]
    d = min(3, len(dependientes))
    if dependientes:
        evidencia = f"{len(dependientes)} fila(s) viva(s) dependen: {dependientes[:5]}"
    else:
        evidencia = "0 filas vivas dependen de este ticket"
    return d, evidencia


def compute_similarity_index(
    entries: list[Entry],
) -> tuple[dict[str, list[dict]], dict[str, float]]:
    """Corre backlog_db_compare UNA sola vez para todo el corpus (no por ticket).

    Before: ``entries`` es el corpus completo (backlog vivo + archive).
    During: invoca ``find_edges`` + ``build_lots`` (funciones REALES de
        produccion, importadas, nunca reimplementadas) UNA vez -- es O(n^2) en
        el numero de entries, y llamarlo por ticket (390 veces) es
        catastroficamente ineficiente. v3 corrige este defecto de rendimiento
        detectado durante la prueba funcional (timeout real medido).
    After: (edges_by_ticket, near_top_by_ticket). ``edges_by_ticket[label]``
        es la lista de aristas (score>=umbral) donde aparece ese ticket.
        ``near_top_by_ticket[label]`` es el score informativo mas alto de
        ``near[]`` (por debajo del umbral) para ese ticket, o 0.0.
    """
    edges, near, _idf, _n = find_edges(entries, UMBRAL_SIMILITUD)
    lots = build_lots(entries, edges)

    edges_by_ticket: dict[str, list[dict]] = {}
    for lot in lots:
        for edge in lot["edges"]:
            edges_by_ticket.setdefault(edge["a"], []).append(edge)
            edges_by_ticket.setdefault(edge["b"], []).append(edge)

    near_top_by_ticket: dict[str, float] = {}
    for score, i, j, _shared in near:
        label_i, label_j = entries[i].label, entries[j].label
        near_top_by_ticket[label_i] = max(near_top_by_ticket.get(label_i, 0.0), score)
        near_top_by_ticket[label_j] = max(near_top_by_ticket.get(label_j, 0.0), score)

    return edges_by_ticket, near_top_by_ticket


def score_r(
    ticket: str,
    edges_by_ticket: dict[str, list[dict]],
    near_top_by_ticket: dict[str, float],
) -> tuple[float, str]:
    """R -- Similitud/reincidencia, score crudo 0.0-1.0, via indice precalculado.

    Before: ``edges_by_ticket``/``near_top_by_ticket`` ya calculados UNA vez
        por ``compute_similarity_index`` para todo el corpus.
    During: lookup directo por ticket, sin recalcular la comparacion global.
    After: (R_score_max, evidencia).
    """
    aristas = edges_by_ticket.get(ticket, [])
    if not aristas:
        near_score = near_top_by_ticket.get(ticket, 0.0)
        if near_score:
            fuente = (
                f"sin vecinos >= umbral {UMBRAL_SIMILITUD}; casi-vecino mas "
                f"cercano score={near_score} (informativo, no cuenta como R_score_max)"
            )
        else:
            fuente = f"sin vecinos por encima o cerca del umbral {UMBRAL_SIMILITUD}"
        return 0.0, fuente

    mejor = max(aristas, key=lambda edge: edge["score"])
    otro = mejor["b"] if mejor["a"] == ticket else mejor["a"]
    fuente = f"vecino {otro}, score={mejor['score']}"
    return mejor["score"], fuente


def score_a(origen_texto: str) -> tuple[float, int, bool]:
    """A -- boost de antiguedad, acotado a +15% maximo, aplicado con clamp.

    Before: ``origen_texto`` es el texto libre que documenta cuando se
        descubrio/fue fichado el ticket (columna Origen o prosa del titulo).
    During: busca el primer patron ``YYYY-MM-DD`` en el texto. v3: si la
        fecha resultante es FUTURA o el parseo falla, ``dias`` se clampa a 0
        (boost=1.0) en vez de dejar que ``math.log`` reciba un negativo --
        corrige el hallazgo real de auditoria (dias negativo -> ValueError
        'math domain error' si dias<=-1, o boost<1.0 que penaliza si
        -1<dias<0).
    After: (boost, dias_clamped, origen_parseado).
    """
    match = _ORIGEN_DATE_PATTERN.search(origen_texto)
    if not match:
        return 1.0, 0, False
    try:
        fecha = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return 1.0, 0, False

    dias = (date.today() - fecha).days
    dias_clamped = max(0, dias)
    origen_parseado = dias >= 0  # una fecha futura se parsea pero se marca como tal
    boost = min(BOOST_TECHO, 1 + BOOST_TASA * math.log(1 + dias_clamped))
    return boost, dias_clamped, origen_parseado


def compute_tds(
    s: int, r_score_max: float, d: int, c: int, boost: float
) -> tuple[float, float]:
    """Formula TDS corregida (v2->v3): el boost ya no invierte su efecto.

    Before: componentes ya puntuados individualmente.
    During: separa ``base`` en su parte positiva y negativa; el boost SOLO
        multiplica la parte positiva (``max(0, base)``); la parte negativa se
        suma sin boost (``min(0, base)``). Este es el fix del bug de v1
        (confirmado por 4 lentes adversariales, dos rondas): un ticket con
        ``base`` negativo ya no empeora con la antiguedad, simplemente no
        mejora.
    After: (base, TDS).
    """
    base = s * 2 + r_score_max * 3 + d * 1.5 - c * 1.2
    tds = max(0.0, base) * boost + min(0.0, base)
    return base, tds


def score_ticket(
    row: BacklogRow,
    all_rows: list[BacklogRow],
    edges_by_ticket: dict[str, list[dict]],
    near_top_by_ticket: dict[str, float],
) -> dict:
    """Ensambla el score completo de UN ticket, con desglose auditable.

    Before: ``row`` es la fila del ticket a puntuar; ``all_rows`` da contexto
        para D; ``edges_by_ticket``/``near_top_by_ticket`` ya fueron
        precalculados UNA vez para todo el corpus (ver
        ``compute_similarity_index``) -- nunca se recalcula por ticket.
    During: invoca cada ``score_*`` de forma independiente; ninguno muta
        estado compartido.
    After: dict con TDS, componentes y evidencia por variable -- nunca solo
        el numero (mismo principio que ``value-bar.md``: un score sin
        desglose no es utilizable para decidir).
    """
    s, s_evidencia = score_s(row.titulo_completo)
    c, c_evidencia, c_no_estimado = score_c(row.titulo_completo)
    d, d_evidencia = score_d(row.ticket, all_rows)
    r_score_max, r_evidencia = score_r(row.ticket, edges_by_ticket, near_top_by_ticket)
    boost, dias, origen_parseado = score_a(row.titulo_completo)
    base, tds = compute_tds(s, r_score_max, d, c, boost)

    return {
        "ticket": row.ticket,
        "TDS": round(tds, 3),
        "grupo_prioridad": row.prioridad,
        "componentes": {
            "S": s,
            "R_score_max": round(r_score_max, 4),
            "C": c,
            "D": d,
            "boost_antiguedad": round(boost, 4),
            "base_antes_del_boost": round(base, 3),
        },
        "S_evidencia": s_evidencia,
        "R_evidencia": r_evidencia,
        "C_evidencia": c_evidencia,
        "C_no_estimado": c_no_estimado,
        "D_evidencia": d_evidencia,
        "dias_desde_origen": dias,
        "origen_parseado": origen_parseado,
    }


def _extract_ticket_id_and_priority(row_text: str) -> tuple[str, str]:
    """Extrae ticket y prioridad del texto de fila (para score_single_row).

    Before: ``row_text`` es el texto de la fila (sin la columna Prioridad,
        o con ella si viene completo desde el flujo de alta).
    During: busca el patron canonico ``[A-Z]+-\\d{4}-\\d+[a-z]*`` para el
        ticket y ``Alta|Media|Baja`` para la prioridad (search, no fullmatch,
        porque row_text puede ser una fila markdown completa).
    After: (ticket, prioridad). Si no se puede parsear la prioridad,
        devuelve ``"Desconocida"`` (el scoring sigue adelante sin ella).
    """
    ticket_match = re.search(r"([A-Z]+-\d{4}-\d+[a-z]*)", row_text)
    prioridad = "Desconocida"
    pri_match = re.search(r"\b(Alta|Media|Baja)\b", row_text)
    if pri_match:
        prioridad = pri_match.group(1)

    if ticket_match:
        return ticket_match.group(1), prioridad
    return "", prioridad


def _build_row_text(row: BacklogRow) -> str:
    """Reconstruye el texto de fila markdown a partir de BacklogRow.

    Before: ``row`` es un BacklogRow con sus campos parseados.
    During: construye la cadena completa tal como aparece en el backlog.
    After: texto de fila completo (con Prioridad, Ticket, Titulo, Depende).
    """
    return (
        f"| {row.prioridad} | {row.ticket} | {row.titulo_completo} | "
        f"scope | pending | {row.depende_de} | test | - |"
    )


def _parse_rows_from_text(all_rows_raw: list[Entry]) -> list[BacklogRow]:
    """Convierte corpus Entries -> BacklogRow para uso en D.

    Before: ``all_rows_raw`` son las entradas del corpus (Entry con label+text).
    During: extrae el ticket del label y construye BacklogRow minimo.
    After: lista de BacklogRow con ticket y depende_de vacio (el corpus
        no tiene la columna 'Depende de' estructurada).
    """
    rows: list[BacklogRow] = [
        BacklogRow("Desconocida", e.label, e.text, "") for e in all_rows_raw
    ]
    return rows


def score_single_row(
    row_text: str,
    all_rows: list[BacklogRow],
    corpus_entries: list[Entry],
) -> dict:
    """Calcula el TDS de UN ticket individual reutilizando _compute_vecinos.

    Before: ``row_text`` es el texto de la fila del ticket (titulo completo
        con las columnas relevantes); ``all_rows`` son las filas vivas para D;
        ``corpus_entries`` son las entradas del corpus (backlog+archive) para R.
    During: tokeniza el candidato, invoca ``_compute_vecinos`` para R,
        calcula S/C/D/A independientemente, compila TDS.
    After: dict con TDS, componentes y evidencia por variable -- mismo
        formato que ``score_ticket()`` mas ``r_context`` y ``dias_desde_origen``.
    """
    ticket, prioridad = _extract_ticket_id_and_priority(row_text)
    if not ticket:
        return {
            "ticket": "UNKNOWN",
            "TDS": None,
            "grupo_prioridad": "Desconocida",
            "error": "no se pudo extraer el ticket del row_text",
        }

    # R via _compute_vecinos (O(n), no O(n^2))
    obligatorias_paths = []
    for e in corpus_entries:
        path_str = e.source
        if path_str and path_str not in obligatorias_paths:
            obligatorias_paths.append(path_str)

    vecinos, _vecinos_fallback = _compute_vecinos(
        Path("."), obligatorias_paths, ticket, row_text
    )

    if vecinos:
        mejor = max(vecinos, key=lambda v: v["score"])
        r_score_max = mejor["score"]
        r_evidence = f"vecino {mejor['id']}, score={mejor['score']}"
        r_context = "candidato_no_incluido_en_idf"
    else:
        r_score_max = 0.0
        r_evidence = "sin vecinos (sin coincidencias con umbral)"
        r_context = "candidato_no_incluido_en_idf"

    # S, C, D, A
    s, s_evidence = score_s(row_text)
    c, c_evidence, c_no_estimado = score_c(row_text)
    d, d_evidence = score_d(ticket, all_rows)
    # A: dias_desde_origen=0 explicito para el momento del alta (boost=1.0 neutro)
    dias = 0
    boost = 1.0

    base, tds = compute_tds(s, r_score_max, d, c, boost)

    return {
        "ticket": ticket,
        "TDS": round(tds, 3),
        "grupo_prioridad": prioridad,
        "componentes": {
            "S": s,
            "R_score_max": round(r_score_max, 4),
            "C": c,
            "D": d,
            "boost_antiguedad": round(boost, 4),
            "base_antes_del_boost": round(base, 3),
        },
        "S_evidencia": s_evidence,
        "R_evidence": r_evidence,
        "C_evidencia": c_evidence,
        "C_no_estimado": c_no_estimado,
        "D_evidencia": d_evidence,
        "dias_desde_origen": dias,
        "origen_parseado": False,
        "r_context": r_context,
    }


def _write_shadow_log(
    project_root: Path,
    candidato_id: str,
    corpus_sha: str,
    result: dict,
) -> None:
    """Escribe una linea en el shadow log append-only (gitignored).

    Before: ``project_root`` tiene ``.agent/runtime/audit/backlog_priority/``.
    During: crea el directorio si no existe y append json a tds_shadow_log.jsonl.
    After: linea escrita. Si falla la escritura, se imprime a stderr y se ignora.
    """
    try:
        log_path = (
            project_root
            / ".agent"
            / "runtime"
            / "audit"
            / "backlog_priority"
            / "tds_shadow_log.jsonl"
        )
        log_path.parent.mkdir(parents=True, exist_ok=True)
        import json as _json
        from datetime import datetime

        line = {
            "candidato_id": candidato_id,
            "corpus_sha": corpus_sha,
            "calculado_en": datetime.now().astimezone().isoformat(),
            "TDS": result.get("TDS"),
            "componentes": result.get("componentes"),
            "r_context": result.get("r_context", "no_aplica"),
            "version_formula": "v3",
            "error": result.get("error"),
            "S_evidencia": result.get("S_evidencia"),
            "R_evidence": result.get("R_evidence"),
            "C_evidencia": result.get("C_evidencia"),
            "D_evidence": result.get("D_evidencia"),
            "dias_desde_origen": result.get("dias_desde_origen"),
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(_json.dumps(line, ensure_ascii=False) + "\n")
    except OSError as exc:
        print(
            f"[backlog-priority] WARN: no se pudo escribir shadow log: {exc}",
            file=sys.stderr,
        )


def load_triage_context(triage_json_path: Path | None) -> tuple[set[str], str]:
    """LIKELY_DONE del ultimo triage, si existe, para excluir del ranking.

    Before: ``triage_json_path`` puede ser None o apuntar a un fichero
        inexistente -- ninguno de los dos es un error del recolector.
    During: lee el campo ``tickets[*].reconciliation`` del JSON portable
        ``autonomous-batch-dag/v1`` (schema de ``backlog_triage.md``).
    After: (ids LIKELY_DONE, mensaje de contexto). Nunca falla si el triage
        no existe -- solo lo declara.
    """
    if triage_json_path is None or not triage_json_path.exists():
        return set(), "no encontrado, TDS calculado sin exclusion de LIKELY_DONE"
    try:
        data = json.loads(triage_json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return set(), f"triage-json ilegible ({exc}), TDS calculado sin exclusion"
    likely_done = {
        t["id"]
        for t in data.get("tickets", [])
        if t.get("reconciliation") == "LIKELY_DONE"
    }
    return (
        likely_done,
        f"cargado desde {triage_json_path.name}, {len(likely_done)} LIKELY_DONE excluidos",
    )


def build_report(project_root: Path, triage_json_path: Path | None) -> dict:
    """Ensambla el reporte completo: todos los tickets vivos, agrupados por Prioridad.

    Before: ``project_root`` tiene ``.agent/collaboration/backlog.md``.
    During: carga filas vivas + archive (para R), aplica el contexto de
        triage si existe, puntua cada ticket no excluido.
    After: dict con metadata + lista de tickets, listo para JSON o markdown.
    """
    backlog_path = project_root / ".agent" / "collaboration" / "backlog.md"
    archive_path = (
        project_root / ".agent" / "collaboration" / "_archive" / "backlog_done.md"
    )

    all_rows = parse_live_backlog_rows(backlog_path)

    # v3: --backlog repetido (vivo + archive), NUNCA --archive-file -- ese flag
    # no lo consume _collect_universes() en modo lectura (verificado leyendo
    # el codigo real de backlog_db_compare.py).
    entries: list[Entry] = []
    entries_backlog, _stats = load_backlog_rows(backlog_path)
    entries += entries_backlog
    if archive_path.exists():
        entries_archive, _stats2 = load_backlog_rows(archive_path)
        entries += entries_archive

    likely_done, triage_context = load_triage_context(triage_json_path)

    edges_by_ticket, near_top_by_ticket = compute_similarity_index(entries)
    tickets_scored = [
        score_ticket(row, all_rows, edges_by_ticket, near_top_by_ticket)
        for row in all_rows
        if row.ticket not in likely_done
    ]

    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "project_root": str(project_root),
        "triage_context": triage_context,
        "tickets_evaluados": len(tickets_scored),
        "tickets_excluidos_likely_done": len(likely_done),
        "tickets": tickets_scored,
    }


def render_markdown(report: dict) -> str:
    """Reporte humano: SIEMPRE agrupado por Prioridad primero, TDS ordena dentro.

    Before: ``report`` ya construido por ``build_report``.
    During: agrupa por ``grupo_prioridad`` en el orden Alta/Media/Baja; dentro
        de cada grupo, ordena por TDS descendente. v3: nunca una tabla unica
        global que mezcle prioridades (fix del defecto #7 de v1).
    After: texto markdown con 3 tablas.
    """
    lines = [
        "# Backlog Priority Score (TDS)",
        "",
        f"**Generado:** {report['generated_at']}",
        f"**Contexto de triage:** {report['triage_context']}",
        f"**Tickets evaluados:** {report['tickets_evaluados']} "
        f"(excluidos LIKELY_DONE: {report['tickets_excluidos_likely_done']})",
        "",
    ]
    for grupo in ("Alta", "Media", "Baja"):
        del_grupo = sorted(
            (t for t in report["tickets"] if t["grupo_prioridad"] == grupo),
            key=lambda t: -t["TDS"],
        )
        lines.append(f"## Prioridad: {grupo} ({len(del_grupo)} tickets)")
        lines.append("")
        lines.append("| Ticket | TDS | S | R | C | D | boost | dias |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
        for t in del_grupo:
            comp = t["componentes"]
            lines.append(
                f"| {t['ticket']} | {t['TDS']} | {comp['S']} | {comp['R_score_max']} "
                f"| {comp['C']} | {comp['D']} | {comp['boost_antiguedad']} "
                f"| {t['dias_desde_origen']} |"
            )
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Recolector de score TDS para desempatar el backlog dentro de "
            "cada categoria de Prioridad. RECOLECTA/PUNTUA, nunca decide ni "
            "escribe en backlog.md/STATE.md/bus."
        )
    )
    parser.add_argument("--project-root", required=True, help="raiz del repo_destino")
    parser.add_argument(
        "--triage-json",
        default=None,
        help="JSON portable de backlog_triage.md (opcional)",
    )
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    parser.add_argument(
        "--ticket",
        default=None,
        help=(
            "Recalcular el TDS de un ticket YA existente en backlog.md. "
            "Devuelve JSON individual (no envuelto en build_report)."
        ),
    )
    args = parser.parse_args(argv)

    project_root = Path(args.project_root).resolve()
    if not project_root.exists():
        print(
            f"[backlog-priority] ERROR: --project-root no existe: {project_root}",
            file=sys.stderr,
        )
        return 1

    backlog_path = project_root / ".agent" / "collaboration" / "backlog.md"
    if not backlog_path.exists():
        print(
            f"[backlog-priority] ERROR: backlog.md no existe: {backlog_path}",
            file=sys.stderr,
        )
        return 1

    # Modo --ticket: recalcular TDS de un ticket individual
    if args.ticket:
        archive_path = (
            project_root / ".agent" / "collaboration" / "_archive" / "backlog_done.md"
        )

        all_rows = parse_live_backlog_rows(backlog_path)

        entries: list[Entry] = []
        entries_backlog, _stats = load_backlog_rows(backlog_path)
        entries += entries_backlog
        if archive_path.exists():
            entries_archive, _stats2 = load_backlog_rows(archive_path)
            entries += entries_archive

        # Buscar el ticket en las filas vivas
        target_row = None
        for row in all_rows:
            if row.ticket == args.ticket:
                target_row = row
                break

        if target_row is None:
            print(
                f"[backlog-priority] ERROR: ticket {args.ticket} no encontrado "
                f"en backlog.md",
                file=sys.stderr,
            )
            return 1

        result = score_single_row(_build_row_text(target_row), all_rows, entries)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    triage_json_path = Path(args.triage_json).resolve() if args.triage_json else None
    report = build_report(project_root, triage_json_path)

    if args.format == "markdown":
        print(render_markdown(report))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
