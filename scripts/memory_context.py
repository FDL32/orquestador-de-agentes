#!/usr/bin/env python3
"""CLI de memoria: INDICE de arranque y puerta de EXPANSION.

WT-2026-191 lo creo como comando determinista para no depender de prosa en el
prompt de arranque. WOT-2026-057a/b lo convirtio en dos cosas distintas:

    --bootstrap  entrega un INDICE (titulares). NO es el corpus.
    --recall     entrega la LECCION ENTERA. Es la puerta de expansion.

Esa distincion es el nucleo del contrato. Con mediana de 877 chars por leccion,
la regla accionable de 82 entradas vive DESPUES del corte del indice: leer solo
`--bootstrap` da titulares, y un titular no impide cometer el error que la regla
previene.

Usage:
    python scripts/memory_context.py --bootstrap
        Arranque ACOTADO (el mismo que inyecta el hook SessionStart): pista de
        cuando expandir + indice de memoria (archive del MOTOR + root activo,
        tier local) + salud + roles + M4/M5, <= 9.000 chars. Cada linea del
        indice lleva el `id` para expandirla; el pie declara cuantas omite.

    python scripts/memory_context.py --full
        Corpus ENTERO, sin tope. Para enumerar lo que el indice omite.

    python scripts/memory_context.py --recall --query "<termino>" [--limit N]
        Lecciones COMPLETAS, ordenadas por COBERTURA de la consulta (IDF+Jaccard
        via find_similar_signals). Una consulta de varias palabras que no case
        literalmente cae a busqueda por terminos: no devuelve vacio.
        Declara lo que omite, por bytes (--budget) y por cardinalidad (--limit).

    python scripts/memory_context.py --recall --query "<termino>" --headlines
        Formato compacto: una linea por leccion con su titular (``_short_signal``).
        Aplica a ``--query``, ``--ticket``, ``--id`` y al recall plano.
        Mide el tope en BYTES UTF-8; el pie se reserva antes del bucle.
        Presupuesto por defecto: 2000 bytes (24000 sin ``--headlines``).

    python scripts/memory_context.py --recall --id obs-<slug>
        Expande UNA leccion por su id exacto -- el que imprime --bootstrap.
        Fail-closed: un id inexistente sale con rc=1, nunca cae a recall plano.

    python scripts/memory_context.py --recall --ticket <TICKET_ID>
        Deriva las consultas del work_plan.md activo.

    python scripts/memory_context.py --status
        Que tiers locales existen, y contra que project root se resolvieron.

    python scripts/memory_context.py --compact
        Contexto para el hook de pre-compact (archive capado por recencia + L3/L2).

    python scripts/memory_context.py --usage-report --since <ISO-8601> [--window-days N]
        Lee ``.agent/runtime/memory/recall_log.jsonl`` y emite un JSON a stdout
        con conteos de llamadas reales (caller en REAL_USE_CALLERS), sesiones
        distintas, dias distintos y un veredicto (hay uso real / uso insuficiente
        / ventana abierta). Nunca escribe en el log.

Nota: si el hook `SessionStart` esta cableado, el INDICE ya entra solo al abrir
sesion. Lo que sigue haciendo falta a mano es la EXPANSION (`--recall`).
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
from pathlib import Path


# Bootstrap project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

#: Raiz del motor. Se separa de `_PROJECT_ROOT` para que los tests puedan
#: redirigirla sin tocar `sys.path`.
_MOTOR_ROOT = _PROJECT_ROOT


def _anchor_memory_root() -> Path | None:
    """Anclar el root de memoria igual que hace el hook `SessionStart`.

    WOT-2026-057b. Sin esto el CLI y el hook leian universos DISTINTOS, y el
    lector-FS lo midio en el bucle L917:

        cd <motor>; --recall --id obs-<del-destino>   -> rc=1 ("no esta en este
                                                       archive" -- FALSO, si esta)
        AGENT_PROJECT_ROOT=<destino> ... mismo comando -> rc=0
        --bootstrap por CLI -> 207   |   por hook -> 342

    Dos consecuencias, ambas graves: (a) el fallback documentado para backends
    SIN hooks (Codex, Kilo) reintroducia la ceguera que este ticket cierra; y
    (b) ``--id``, la puerta "exacta y fail-closed", daba un falso negativo
    indistinguible de la verdad -- con un mensaje que afirmaba que la leccion no
    existia.

    Se respeta una `AGENT_PROJECT_ROOT` ya puesta: si el operador la fijo, manda.
    Solo se rellena cuando falta, y delega en el resolvedor compartido
    ``bus.paired_destination.resolve_paired_destination`` (WOT-2026-127d), que
    unifica la logica del hook y el CLI. Justificacion forense completa:
    motivo del filtro de nombres (traversal ``'../..'`` y ``'C:/Windows'``; ver
    ``bus/paired_destination.py``).

    NO escribe el entorno del proceso: DEVUELVE la raiz y el llamante la aplica
    con `_anchored_env`, que la restaura al salir. La primera version hacia
    `os.environ[...] = ...` directo y eso convirtio una funcion de lectura en un
    efecto GLOBAL: cualquier test que llamara a `main()` dejaba la variable
    puesta para el resto de la sesion de pytest, y el sintoma aparecia en
    `test_scope_gate` -- un fichero que este ticket no toca (11 rojos en suite,
    32 verdes en aislado). Un state-leak clasico y de los caros: el dano se ve
    lejos de la causa.

    Before: puede haber o no `AGENT_PROJECT_ROOT` en el entorno.
    During: delega en el resolvedor para unificar hook y CLI. Sin red, sin
        subprocess, sin escrituras, nunca lanza.
    After: devuelve la ruta del workspace declarado, o ``None`` -- que es un
        resultado NORMAL (no hay declarante, no hay topologia pareada, o ya hay
        una raiz fijada).
    """
    import os

    if os.environ.get("AGENT_PROJECT_ROOT"):
        return None
    # Ronda 5 (kilo #2): sin la variable, resolver como el hook SessionStart --
    # el primer ancestro del cwd con `.claude/` y `.agent/` -- antes que el
    # motor. La invocacion documentada para backends sin hook es
    # `<MOTOR_ROOT>/scripts/memory_context.py --bootstrap` CON cwd en el
    # destino; resolviendo solo por `_MOTOR_ROOT` el CLI leia la memoria del
    # motor y perdia la del destino (medido: canario local 0 por CLI, presente
    # por hook en el mismo cwd).
    try:
        here = Path.cwd().resolve()
        motor = _MOTOR_ROOT.resolve()
        for candidate in (here, *here.parents):
            if (candidate / ".claude").is_dir():
                # Un checkout del MOTOR (otro worktree) no es un destino: lo
                # delata su propio `scripts/memory_context.py`. Para el motor
                # manda el workspace de dogfooding de abajo (test 057b). El
                # link motor<->destino gana a esa heuristica (ronda 6, kilo):
                # un destino que vendorice el script sigue siendo destino.
                is_destino = (
                    candidate / ".agent" / "config" / "motor_destination_link.json"
                ).is_file()
                is_motor = (
                    not is_destino
                    and (candidate / "scripts" / "memory_context.py").is_file()
                )
                if (
                    candidate != motor
                    and not is_motor
                    and (candidate / ".agent").is_dir()
                ):
                    return candidate
                break
    except OSError:
        pass
    try:
        if str(_MOTOR_ROOT) not in sys.path:
            sys.path.insert(0, str(_MOTOR_ROOT))
        from bus.paired_destination import resolve_paired_destination

        return resolve_paired_destination(_MOTOR_ROOT)
    except ImportError:
        return None
    except OSError:
        return None


@contextlib.contextmanager
def _anchored_env():
    """Aplica la raiz de memoria SOLO durante el bloque, y la restaura.

    WOT-2026-057b. El anclaje tiene que ser visible para `bus.memory_loader`,
    que lo lee del entorno -- pero un CLI no debe dejar variables globales
    puestas al salir. Medido: hacerlo directo contaminaba toda la sesion de
    pytest y ponia en rojo un fichero ajeno al ticket.
    """
    import os

    anchor = _anchor_memory_root()
    if anchor is None:
        yield
        return
    previo = os.environ.get("AGENT_PROJECT_ROOT")
    os.environ["AGENT_PROJECT_ROOT"] = str(anchor)
    try:
        yield
    finally:
        if previo is None:
            os.environ.pop("AGENT_PROJECT_ROOT", None)
        else:
            os.environ["AGENT_PROJECT_ROOT"] = previo


from bus.memory_loader import (  # noqa: E402
    INDEX_BUDGET_CHARS,
    get_compact_context,
    get_memory_tier_status,
    get_session_index,
    index_line,
    recall_observations,
)
from bus.portable_memory_archive import iter_archive_months  # noqa: E402


# WOT-2026-057a. Byte budget for `--recall`, the EXPANSION gate.
#
# Two opposite defects lived in this command (measured 2026-08-17, 207 entries):
#   - It truncated to 150 chars -- LESS than the bootstrap index (200) it was
#     supposed to expand, so with a median signal of 877 the operative rule was
#     unreachable by ANY route.
#   - But removing that cap with no ceiling is worse: `--query gate` returns 42
#     hits (~12.6k tokens) and `--query de` returns 197 (~47.8k). `--limit` caps
#     CARDINALITY, not bytes, so `--limit 100` is a self-inflicted overflow.
#
# 24000 bytes is ~6k tokens: enough for a dozen full lessons at the median,
# bounded well under any arranque budget. The invariant is "bounded, whole, and
# declared", not this figure -- `--budget` overrides it.
_RECALL_BYTE_BUDGET = 24000

#: Default byte budget for `--recall --headlines`.
_HEADLINES_BYTE_BUDGET = 2000

#: Minimum budget for ``--headlines`` (max footer + one headline line).
#: Below this the command must fail with rc 2, never print silently.
_MIN_HEADLINES_BUDGET = 300

#: WOT-2026-124g. Closed list of real-use callers; everything else is telemetry
#: or validation noise.  The default ``--caller`` value is ``"agent"`` so that an
#: untagged invocation (copied from a prompt or index) is already identified as
#: real use.  ``"unknown"`` is never produced any more.
REAL_USE_CALLERS = frozenset({"agent"})

#: Recall log schema version (WOT-2026-124g).  v2 adds the ``session`` field.
RECALL_LOG_VERSION = 2


def _resolve_recall_budget(args: argparse.Namespace) -> int:
    """Resolve the effective byte budget for recall output.

    Priority: explicit ``--budget`` always wins.  Without explicit value,
    ``--headlines`` defaults to ``_HEADLINES_BYTE_BUDGET`` (2000),
    otherwise ``_RECALL_BYTE_BUDGET`` (24000).

    Before: ``args`` from ``parser.parse_args()``; ``--budget`` may be None.
    During: pure computation, no I/O.
    After: returns the effective budget as a positive int.
    """
    if args.budget is not None:
        return args.budget
    if args.headlines:
        return _HEADLINES_BYTE_BUDGET
    return _RECALL_BYTE_BUDGET


def _pool_for_multiword(query: str) -> list[dict]:
    """Union of per-term matches, for a query the literal filter cannot match.

    WOT-2026-057b. `recall_observations` matches by LITERAL SUBSTRING, so a
    phrase only hits when it appears verbatim. Measured on the real corpus
    (2026-08-17): `"pipe"` -> 16 hits, but `"suite verde head"` -> 0 and
    `"gate que bloquea"` -> 0. The ranking wired above then ran over an EMPTY
    list, so it could not help.

    This is the case that matters for a cold start: an agent describes its task
    as a phrase ("the suite went stale after the commit"), not as one keyword,
    and the bootstrap prompt now tells it to run
    `--recall --query <domain-of-the-task>`.

    So when the phrase matches nothing, each term is queried separately and the
    union becomes the pool. Widening membership is safe HERE and only here,
    because `_rank_by_similarity` then orders by whole-query similarity: recall
    goes up, and precision is restored by the ranker instead of by the filter.

    Before: ``query`` holds 2+ whitespace-separated terms.
    During: one `recall_observations` call per term of 3+ chars, deduplicated by
        stable ``id`` (falling back to the signal text when absent). No writes.
    After: returns the union, possibly empty. Never raises.
    """
    seen: set[str] = set()
    pool: list[dict] = []
    for term in query.split():
        if len(term) < 3:
            continue
        for obs in recall_observations(query=term, limit=1_000_000):
            key = str(obs.get("id") or obs.get("signal") or "")
            if key and key not in seen:
                seen.add(key)
                pool.append(obs)
    return pool


def _rank_by_similarity(observations: list[dict], query: str | None) -> list[dict]:
    """Order lessons by IDF-weighted Jaccard against ``query``, best first.

    WOT-2026-057b. `recall_observations` filters by plain substring and returns
    `filtered[:limit]` in POOL order, so with `--limit 15` over 80 hits WHICH
    lessons reached the agent was arbitrary. `find_similar_signals.py`
    (WOT-2026-039m) already implements the ranking -- IDF + weighted Jaccard,
    stdlib only -- and its own docstring already diagnosed the failure this
    fixes: *"las lecciones del archive estan redactadas como REGLAS ABSTRACTAS
    y los candidatos nuevos como CASOS CONCRETOS; un grep por keyword no cruza
    esos dos registros"*. It was written in July and never wired to this gate.
    Reusing it here is the whole change; no new ranking code exists.

    Before: ``observations`` is the full filtered pool; ``query`` may be None.
    During: pure computation, no I/O. Degrades to the input order if the ranking
        module cannot be imported -- a missing optional ranker must not break
        recall, which is the only expansion gate an agent has.
    After: returns the same entries reordered, best match first. Entries with no
        term overlap keep their relative order at the tail rather than being
        dropped: this is a RANKER, not a second filter -- the substring match
        already decided membership.
    """
    if not query or len(observations) < 2:
        return observations
    try:
        from scripts.find_similar_signals import rank_neighbours, tokenize
    except ImportError:
        return observations

    corpus = [
        (str(i), str(obs.get("topic") or ""), str(obs.get("signal") or ""))
        for i, obs in enumerate(observations)
    ]
    try:
        ranked = rank_neighbours(query, corpus, top=len(corpus))
    except (ValueError, ZeroDivisionError):
        return observations

    # Reordenar por COBERTURA de la consulta, con la similitud como desempate.
    #
    # `rank_neighbours` puntua con Jaccard, cuyo denominador es |consulta UNION
    # documento|: un documento LARGO se penaliza por su propia longitud. Eso es
    # correcto para su proposito original (detectar DUPLICADOS, donde dos textos
    # deben parecerse entre si), pero es el criterio equivocado para RECUPERAR:
    # aqui importa cuanto de lo que el agente pidio aparece en la leccion.
    #
    # Medido sobre el corpus real (2026-08-17, `--query "suite verde head"`):
    #     GANABA  capturing-rc-after-a-pipe...      comparte {head}              0.0333
    #     posicion 6  suite-green-needs-sha-equals-head  comparte {suite,verde,head}
    # El corpus tiene mediana de 877 chars porque las lecciones son densas: sin
    # esta correccion el ranker castiga justo la virtud del corpus.
    query_terms = {t for t in tokenize(query) if t}
    by_index: dict[int, tuple[float, float]] = {}
    for score, surface, _label, terms, _shared_surfaces in ranked:
        covered = (
            len(query_terms & set(terms)) / len(query_terms) if query_terms else 0.0
        )
        by_index[int(surface)] = (covered, score)

    order = sorted(by_index, key=lambda i: (-by_index[i][0], -by_index[i][1], i))
    seen = set(order)
    return [observations[i] for i in order] + [
        obs for i, obs in enumerate(observations) if i not in seen
    ]


def _print_recall(observations: list[dict], budget: int) -> None:
    """Print recalled lessons WHOLE, dropping entire entries past ``budget``.

    Adopts the `maxBytes` pattern from `deepseek-ai/deepseek-harness`
    (`packages/context/agent-instructions`, MIT): when the budget binds, discard
    whole units and NAME them, rather than mutilating every unit. Applied here
    that means an agent either gets a lesson it can act on, or is told the
    lesson exists and how to reach it -- never half a rule cut mid-word, which
    is the exact failure this ticket fixes in the bootstrap index.

    Before: ``observations`` is the already-filtered, already-limited list;
        ``budget`` is a positive byte count.
    During: emits entries in order until the next one would exceed ``budget``.
        Pure stdout, no I/O beyond printing.
    After: every printed signal is COMPLETE. When entries were dropped, a final
        line names how many and their topics, so the omission is visible.
    """
    used = 0
    omitted: list[str] = []
    for obs in observations:
        ts = str(obs.get("timestamp") or "")[:19]
        topic = obs.get("topic", "general")
        signal = str(obs.get("signal") or "")
        source = obs.get("source", "unknown")
        line = f"- [{ts}] **{topic}**: {signal} ({source})"
        # Cada entrada se mide por SI MISMA: una omitida no arrastra a las
        # siguientes (antes `if omitted or ...` descartaba todo lo posterior
        # aunque cupiera, y el pie lo contaba como "por presupuesto").
        if used + len(line) > budget and used > 0:
            omitted.append(str(topic))
            continue
        print(line)
        used += len(line)

    if omitted:
        shown = ", ".join(omitted[:5])
        more = f", +{len(omitted) - 5} mas" if len(omitted) > 5 else ""
        print(
            f"\n[{len(omitted)} entrada(s) omitida(s) por presupuesto "
            f"({used}/{budget} bytes): {shown}{more}]\n"
            f"Sube el tope con --budget N, o acota con --query."
        )


def _print_headlines(
    observations: list[dict], budget: int, *, limit_warning: str = ""
) -> None:
    """Print recalled lessons as headlines, one line each, within ``budget``.

    Each line uses ``bus.memory_loader.index_line`` (headline/short signal).
    The footer is reserved BEFORE the loop; lines are added until the first
    one that would exceed the budget is dropped (break, no continue).
    Cap measured in UTF-8 bytes.  All stdout output (headlines + limit warning
    + footer) respects ``--budget``.

    Before: ``observations`` is the already-filtered, already-limited list;
        ``budget`` is a positive byte count; ``limit_warning`` is "" or a
        precomputed warning line (may be printed if there are omitted entries).
    During: computes the max footer size using the SAME truncation for both
        reserve and print; reserves it plus the limit warning; iterates
        observations using break (not continue) at the first line that won't fit.
        Tracks actual bytes used (each print() adds \\n) and enforces budget.
        Always emits the limit warning when reserved, regardless of omission.
    After: every printed signal is COMPLETE. When entries were dropped,
        a final line names how many and their topics.  Fails with rc=2 if
        budget is below minimum.  Never raises (except SystemExit on rc=2).
    """
    # Build the WORST-CASE footer text topics (truncated to 40 chars).
    # This is the ONLY place topics are truncated -- both the reserved size
    # and the printed footer use this exact text.  Change 1 (BLOCKER).
    max_footer_topics = ", ".join(obs.get("topic") or "general" for obs in observations)
    if len(max_footer_topics) > 40:
        max_footer_topics = max_footer_topics[:40] + "..."

    # Build the max footer text (worst-case: ALL observations omitted).
    # Change 2 (MAJOR): removed the false number "({15 * _RECALL_BYTE_BUDGET}
    # sin --headlines)".  Format is now the canonical one.
    # Account for the max ", +N mas" suffix (up to all observations except
    # 5 shown + the one that broke the loop).
    max_more = ""
    if len(observations) > 5:
        max_more = f", +{len(observations) - 5} mas"
    max_footer_template = (
        f"[{len(observations)} leccion(es) mas no mostradas: --budget {budget}. "
        f"Sube --budget o acota --query. "
        f"({max_footer_topics}{max_more})]\n"
        f"Sube el tope con --budget N, o acota con --query."
    )

    # Reserve space for limit_warning (if any) + the full footer.
    # The reserve includes the footer template (without trailing \n because
    # print() adds it) and the limit_warning string as-is.  The +1 accounts
    # for the trailing \n that print() adds to the footer.
    reserve_text = (limit_warning or "") + max_footer_template
    reserve_bytes = len(reserve_text.encode("utf-8")) + 1

    # Compute the real minimum budget required: reserve + smallest headline
    # line + its \n. If observations exist, we need room for at least one
    # line. If no observations, we need at least reserve + footer \n.
    if observations:
        min_line_bytes = min(
            len(index_line(obs).encode("utf-8")) + 1 for obs in observations
        )
        min_real = reserve_bytes + min_line_bytes
    else:
        min_real = reserve_bytes + 1

    # If budget is too small, fail with rc=2 and stderr.
    if budget < min_real:
        print(
            f"Error: budget {budget} is too small for --headlines output. "
            f"Minimum required: {min_real} bytes.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    # Track actual bytes used in stdout output.
    # Each print() adds \n (+1 byte), except limit_warning which is a
    # pre-formatted string that already carries its own newline.
    used = reserve_bytes
    omitted: list[str] = []

    # Headline loop -- break, not continue.
    # Also count ALL remaining observations as omitted.
    for obs_idx, obs in enumerate(observations):
        headline = index_line(obs)
        line_bytes = len(headline.encode("utf-8")) + 1  # print() adds \n
        if used + line_bytes > budget:
            omitted.extend(
                str(r.get("topic") or "general") for r in observations[obs_idx:]
            )
            break
        print(headline)
        used += line_bytes

    # Always emit the limit warning if reserved (pre-formatted string with \n).
    if limit_warning:
        sys.stdout.write(limit_warning)
        used += len(limit_warning.encode("utf-8"))

    # Print the omission footer only when there are omitted entries.
    if omitted:
        shown_topics = ", ".join(omitted[:5])
        if len(shown_topics) > 40:
            shown_topics = shown_topics[:40] + "..."
        more = f", +{len(omitted) - 5} mas" if len(omitted) > 5 else ""
        footer_text = (
            f"[{len(omitted)} leccion(es) mas no mostradas: --budget {budget}. "
            f"Sube --budget o acota --query. "
            f"({shown_topics}{more})]\n"
            f"Sube el tope con --budget N, o acota con --query."
        )
        print(footer_text)


#: Campos de procedencia que el schema YA declara (WOT-2026-049j). NO se
#: inventan campos nuevos -- es el NON-GOAL (b) del ticket: si uno falta en
#: una entrada real, `_print_why` lo DICE en vez de omitirlo en silencio.
_PROVENANCE_FIELDS = (
    "source",
    "source_ticket",
    "evidence",
    "timestamp",
    "confidence",
    "impact",
    "domain",
)


def _file_contains_record(path: Path, wanted: tuple) -> bool:
    """True si alguna linea JSONL de ``path`` casa ``record_key(..) == wanted``.

    Antes de buscar, una linea en blanco o corrupta se salta sin lanzar -- el
    mismo fail-soft que ya usan ``_read_observations``/``read_archive_observations``
    para una sola linea defectuosa (el fichero entero no deja de escanearse
    por una linea rota).

    Codex Review 2 (WOT-2026-049j, commit d5b60b7): la version original solo
    capturaba ``(ValueError, TypeError)`` alrededor de ``json.loads`` +
    ``record_key``, dejando sin capturar dos casos reales: una linea JSON
    valida pero de tipo NO-dict (p.ej. ``[]``), que hace que
    ``record_key``'s ``record.get(...)`` lance ``AttributeError``; y bytes no
    UTF-8 validos, que hacen que ``read_text(encoding="utf-8")`` lance
    ``UnicodeDecodeError`` (subclase de ``ValueError`` en realidad, pero
    `OSError` no la cubre y quedaba fuera del catch de lectura). Ambos se
    degradan ahora a "no coincide esta linea/fichero", nunca a un traceback.
    """
    import json

    from bus.portable_memory_archive import record_key

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return False
    for line in lines:
        if not line.strip():
            continue
        try:
            if record_key(json.loads(line)) == wanted:
                return True
        except (ValueError, TypeError, AttributeError):
            continue
    return False


def _locate_provenance_file(entry: dict) -> str:
    """En que fichero vive ``entry``: L1 (``observations.jsonl``) o un mes
    concreto del archive portable (``observations.YYYY-MM.jsonl``), y en que
    root (motor o activo) si ambos existen.

    WOT-2026-049j DoD (a): "si esta en L1/archive y en que fichero" -- ninguno
    de los dos lectores de bajo nivel (`_read_observations`,
    `_read_portable_archive`) etiqueta sus entradas con el origen; el pool
    unido de `recall_observations` las pierde del todo. Esta funcion vuelve a
    leer los ficheros CRUDOS por separado -- nunca escribe, nunca toca el
    loader (NON-GOAL declarado) -- y busca la linea EXACTA por `record_key`
    (topic, source_ticket), la misma identidad que ya usa el reconciliador,
    para no inventar una clave de coincidencia nueva.

    Before: ``entry`` es un dict de observacion ya resuelto (p.ej. por
        ``recall_observations``).
    During: compara por ``record_key`` contra L1 del root activo y contra
        cada fichero mensual del archive portable (root activo + motor, si
        difieren), en ese orden -- el mismo orden de precedencia que ya usa
        ``_recallable_observations`` (vivo antes que archivado).
    After: devuelve una cadena legible ("observations.jsonl (L1, activo)",
        "observations.2026-07.jsonl (archive, motor)", ...), o
        "desconocido (no se encontro en ningun fichero escaneado)" si no
        aparece en ninguna de las rutas escaneadas, O si cualquier paso de
        resolucion de rutas falla -- nunca lanza (Codex Review 2,
        WOT-2026-049j: la version original no capturaba fallos de
        ``resolve_project_root``/``_resolve_motor_root``/``iter_archive_months``,
        contradiciendo su propio contrato "nunca lanza").
    """
    try:
        return _locate_provenance_file_unsafe(entry)
    except Exception:
        return "desconocido (no se encontro en ningun fichero escaneado)"


def _locate_provenance_file_unsafe(entry: dict) -> str:
    """Cuerpo real de `_locate_provenance_file`, sin el catch-all exterior.

    Separada para que el catch-all de la funcion publica no oculte, al
    leerla, DONDE puede fallar -- esta funcion puede lanzar; la publica no.
    """
    from bus.memory_loader import _get_observations_file, _resolve_motor_root
    from bus.portable_memory_archive import record_key
    from runtime.project_root import resolve_project_root

    wanted = record_key(entry)
    active_root = resolve_project_root()

    obs_file = _get_observations_file()
    if obs_file.is_file() and _file_contains_record(obs_file, wanted):
        return f"{obs_file.name} (L1, activo)"

    roots = [("activo", active_root)]
    motor_root = _resolve_motor_root()
    if motor_root is not None and motor_root != active_root:
        roots.append(("motor", motor_root))

    for label, root in roots:
        for path in iter_archive_months(root):
            if _file_contains_record(path, wanted):
                return f"{path.name} (archive, {label})"

    return "desconocido (no se encontro en ningun fichero escaneado)"


def _print_why(entries: list[dict]) -> None:
    """Imprime la procedencia COMPLETA de una o mas entradas (`--why`).

    WOT-2026-049j: distinta de `_print_recall` (una linea compacta por
    leccion) -- esta es una vista DETALLADA pensada para UNA entrada (o unas
    pocas bajo el mismo `topic`), con cada campo de procedencia del schema
    nombrado explicitamente.

    Before: ``entries`` no vacio.
    During: por cada entry, imprime los campos de `_PROVENANCE_FIELDS` tal
        cual existen en el dict -- NON-GOAL (b): un campo ausente se declara
        "(ausente)", nunca se omite ni se inventa un valor.
    After: imprime a stdout. No retorna nada, no lanza.
    """
    for i, entry in enumerate(entries):
        if i:
            print()
        print(f"## {entry.get('topic', 'general')} / {entry.get('id', '(sin id)')}")
        for field in _PROVENANCE_FIELDS:
            value = entry.get(field)
            print(f"- {field}: {value if value not in (None, '') else '(ausente)'}")
        print(f"- fichero: {_locate_provenance_file(entry)}")
        print(f"- signal: {entry.get('signal', '(ausente)')}")


def _format_status() -> str:
    """Format memory tier status as human-readable string.

    Includes the resolved ``Project root:`` so callers (and adoption gates) can
    confirm the memory status was read against the intended destination, not the
    motor. Without this line the root is invisible and downstream checks that
    verify topology have nothing to assert against.
    """
    from runtime.project_root import resolve_project_root

    status = get_memory_tier_status()
    parts: list[str] = ["# Memory Tier Status", ""]
    parts.append(f"Project root: {resolve_project_root()}")
    parts.append("")
    for tier in ("l3", "l2", "l1"):
        label = {
            "l3": "L3 (memory_profile.md)",
            "l2": "L2 (memory_rules.md)",
            "l1": "L1 (observations.jsonl)",
        }[tier]
        status_icon = "yes" if status[tier] else "no"
        parts.append(f"- {label}: {status_icon}")
    parts.append("")
    parts.append("Loading order: L3 → L2 → L1")
    return "\n".join(parts)


def _ensure_utf8_stdout() -> None:
    """Ensure stdout uses UTF-8 encoding to avoid UnicodeEncodeError."""
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
    except (OSError, AttributeError):
        pass


def _queries_from_work_plan(ticket_id: str) -> list[str]:
    """Derive recall queries from the active work_plan.md for a ticket.

    Pulls the plan title terms and the stems of 'Files Likely Touched'
    so the agent gets ticket-relevant memory without guessing keywords.
    Returns [] when the plan is missing or belongs to another ticket.
    """
    import re

    from runtime.project_root import get_collab_dir

    plan_path = get_collab_dir() / "work_plan.md"
    try:
        content = plan_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if ticket_id not in content:
        return []

    queries: set[str] = set()
    # File stems from Files Likely Touched bullets (e.g. `bus/review_bridge.py`)
    for match in re.finditer(r"[`\s]([\w/\\.-]+\.(?:py|md|ps1|json))", content):
        stem = Path(match.group(1)).stem
        if len(stem) >= 4:
            queries.add(stem)
    # Title words (first heading line), skipping short/stop tokens
    for line in content.splitlines():
        if line.startswith("#"):
            queries.update(
                w for w in re.findall(r"[a-zA-Z_]{5,}", line) if w.lower() != ticket_id
            )
            break
    return sorted(queries)[:8]


def _session_context_sha256() -> str | None:
    """Return the first 12 hex chars of sha256(CLAUDE_CODE_SESSION_ID), or None.

    WOT-2026-124g. Only ``CLAUDE_CODE_SESSION_ID`` is verified (Claude Code,
    2026-10-25); the raw value is NEVER written.  In other backends it stays
    ``null`` (``None`` here, rendered as JSON null).

    Before: ``CLAUDE_CODE_SESSION_ID`` may or may not exist in the environment.
    During: pure computation, no I/O, never raises.
    After: returns a 12-char hex string or ``None``.
    """
    import hashlib

    sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if not sid:
        return None
    return hashlib.sha256(sid.encode("utf-8")).hexdigest()[:12]


def _parse_iso_date(s: str) -> datetime | None:  # noqa: F821
    """Try to parse an ISO-8601 date string; returns None on failure.

    Returns an offset-aware datetime (UTC) so it can be compared with
    ``now`` which is always UTC-aware.
    """
    from datetime import datetime as dt, timezone as tz

    try:
        parsed = dt.fromisoformat(s)
    except (ValueError, TypeError):
        parsed = None
    if parsed is None:
        # Try common ISO formats that fromisoformat may not handle in Python 3.10.
        for fmt in (
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ):
            try:
                parsed = dt.strptime(s, fmt)
                break
            except ValueError:
                continue
    if parsed is not None and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz.utc)
    return parsed


def _usage_report(  # noqa: C901
    root: Path,
    since_str: str | None,
    window_days: int,
    *,
    now: datetime | None = None,  # noqa: F821
) -> int:
    """Produce a usage report from the recall log (read-only).

    WOT-2026-124g. Reads ``<raiz>/.agent/runtime/memory/recall_log.jsonl``,
    counts lines matching criteria, and prints a JSON object to stdout.

    Before: ``root`` is the project root; ``since_str`` is an ISO-8601 date
        string (required); ``window_days`` is the window for verdict (default 30);
        ``now`` can be injected for tests.
    During: opens and scans the log file (read-only), counts by category,
        computes the verdict, writes ONE JSON line to stdout.
    After: returns 0 if the log is readable (even if empty/missing); returns 2
        if ``since_str`` is not a valid date; returns 1 (stderr) if the log
        exists but cannot be read.  A line that is not JSON, not an object, or
        carries a non-int ``v`` / non-text ``timestamp``/``caller`` / non-text
        non-null ``session`` counts as ``lineas_invalidas``.  Never raises.
    """
    import json
    from datetime import datetime as dt, timezone as tz

    if not since_str:
        print("--since is required with --usage-report", file=sys.stderr)
        return 2

    since = _parse_iso_date(since_str)
    if since is None:
        print(f"Error: invalid --since value: {since_str!r}", file=sys.stderr)
        return 2

    log_file = root / ".agent" / "runtime" / "memory" / "recall_log.jsonl"

    if now is None:
        now = dt.now(tz.utc)

    llamadas_reales = 0
    sesiones_distintas: set[str] = set()
    dias_distintos: set[str] = set()
    lineas_fuera_de_lista = 0
    lineas_invalidas = 0
    has_any_session = False  # True if any real-use line has a non-null session

    log_lines: list[str] = []
    if log_file.is_file():
        try:
            # errors="replace": a corrupt byte makes that line invalid JSON
            # (counted below), not a crash of the whole report.
            log_lines = log_file.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
        except OSError as exc:
            print(f"Error: cannot read {log_file}: {exc}", file=sys.stderr)
            return 1
    if log_lines:
        for line in log_lines:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                lineas_invalidas += 1
                continue

            # Valid JSON is not a valid record: a list/null/string line, or a
            # non-text timestamp/caller/session, is counted as invalid instead
            # of raising (codex review of ae04a8fe, MAJOR 1).
            if not isinstance(rec, dict):
                lineas_invalidas += 1
                continue
            v = rec.get("v")
            if type(v) is not int or v not in (1, 2):
                lineas_invalidas += 1
                continue

            ts_str = rec.get("timestamp")
            caller = rec.get("caller", "unknown")
            session_val = rec.get("session")
            if (
                not isinstance(ts_str, str)
                or not ts_str
                or not isinstance(caller, str)
                or not (session_val is None or isinstance(session_val, str))
            ):
                lineas_invalidas += 1
                continue

            try:
                ts = dt.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=tz.utc)
            except ValueError:
                lineas_invalidas += 1
                continue

            if ts < since:
                continue

            if caller not in REAL_USE_CALLERS:
                lineas_fuera_de_lista += 1
                continue

            # Real use line (caller in REAL_USE_CALLERS, v in {1, 2}, ts >= since)
            llamadas_reales += 1

            # Track session and day
            if session_val is not None:
                has_any_session = True
                sesiones_distintas.add(session_val)
            # Track day for every real-use line
            day_key = ts.strftime("%Y-%m-%d")
            dias_distintos.add(day_key)

    # Compute verdict
    verdict = ""
    if llamadas_reales >= 30:
        if len(sesiones_distintas) >= 3:
            verdict = "hay uso real"
        elif not has_any_session and len(dias_distintos) >= 3:
            # No session in any real-use line, but >= 3 distinct days
            verdict = "hay uso real"
        else:
            # Check if window has passed
            delta = now - since
            if delta.days >= window_days:
                verdict = "uso insuficiente"
            else:
                verdict = "ventana abierta"
    else:
        delta = now - since
        verdict = (
            "uso insuficiente" if delta.days >= window_days else "ventana abierta"
        )  # SIM108

    result = {
        "since": since_str,
        "window_days": window_days,
        "now": now.isoformat(),
        "llamadas_reales": llamadas_reales,
        "sesiones_distintas": len(sesiones_distintas),
        "dias_distintos": len(dias_distintos),
        "lineas_fuera_de_lista": lineas_fuera_de_lista,
        "lineas_invalidas": lineas_invalidas,
        "veredicto": verdict,
    }

    print(json.dumps(result, ensure_ascii=False))
    return 0


def _write_recall_log(
    root: Path,
    caller: str,
    mode: str,
    query: str,
    observations: list[dict],
) -> None:
    """Append a JSON line with telemetry for this recall execution.

    WOT-2026-124f / WOT-2026-124g. A JSON line per --recall execution
    (query/ticket/id/plain), append-only, at ``<raiz>/.agent/runtime/memory/recall_log.jsonl``.

    Schema v2 (WOT-2026-124g): adds ``session`` (first 12 hex chars of
    ``sha256(CLAUDE_CODE_SESSION_ID)``, or null).  The raw environment
    variable value is NEVER written.  The ``v`` field is always
    ``RECALL_LOG_VERSION`` (currently 2).

    Before: ``root`` is the project root (AGENT_PROJECT_ROOT or _PROJECT_ROOT);
        ``caller`` is the --caller flag (default "agent"); ``mode`` is
        "query", "ticket", "id" or "plain"; ``query`` is the --query text,
        the --ticket ID, the requested id, or empty string in plain;
        ``observations`` are the returned results (after --limit).
    During: creates the directory if needed; writes ONE JSON line with \n final;
        never raises, never modifies stdout or exit code.
    After: the file grows by append; a failure is reported to stderr.
    """
    import json
    from datetime import datetime, timezone

    log_dir = root / ".agent" / "runtime" / "memory"
    log_file = log_dir / "recall_log.jsonl"

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        print(
            f"[WARN] recall log: cannot create directory {log_dir}",
            file=sys.stderr,
        )
        return

    results: list = []
    for obs in observations:
        oid = obs.get("id")
        if isinstance(oid, str) and oid:
            results.append(oid)
        else:
            # No id: store dedup_key as a plain list.
            from bus.portable_memory_archive import dedup_key

            dk = dedup_key(obs)
            results.append(list(dk))

    entry = {
        "v": RECALL_LOG_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "caller": caller,
        "mode": mode,
        "query": query,
        "results": results,
        "session": _session_context_sha256(),
    }

    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        print(
            f"[WARN] recall log: cannot write to {log_file}",
            file=sys.stderr,
        )


def _session_context() -> tuple[str, bool]:
    """Arranque ACOTADO completo, el MISMO que inyecta el hook SessionStart.

    Diseno v6 (ronda 4 #49): un backend sin hook (Codex, Kilo, OpenCode) que
    ejecuta `--bootstrap` recibe pista de momentos + indice + salud + roles +
    M4/M5, no solo el indice. Reutiliza `assemble_session_context` del hook,
    cargado por ruta (el hook vive en `.agent/hooks/` y no es un paquete). Si el
    hook no se puede cargar, degrada al indice solo -- nunca a nada.

    Before: el entorno ya esta anclado (`_anchored_env`).
    During: lee memoria, roles y M4/M5; un subproceso de salud; sin escrituras.
    After: ``(contexto, fallo_de_memoria)``.
    """
    import importlib.util
    import os

    root = Path(os.environ.get("AGENT_PROJECT_ROOT") or _PROJECT_ROOT)

    def _index(budget: int) -> str | None:
        try:
            return get_session_index(budget)
        except Exception:
            return None

    hook_path = _MOTOR_ROOT / ".agent" / "hooks" / "session_start_hook.py"
    try:
        spec = importlib.util.spec_from_file_location("_session_start_hook", hook_path)
        if spec is None or spec.loader is None:
            raise ImportError(str(hook_path))
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        return hook.assemble_session_context(root, _index)
    except Exception:
        memory = _index(INDEX_BUDGET_CHARS)
        return (memory or ""), memory is None


def main() -> int:
    """Main entry point for memory_context CLI."""
    _ensure_utf8_stdout()
    parser = argparse.ArgumentParser(
        description="Memory context: bootstrap, compact, recall, status"
    )
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help=(
            "Print the BOUNDED session start context (same as the SessionStart "
            "hook: expansion hint + memory index + health + roles + M4/M5)"
        ),
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help=(
            "Print the WHOLE memory corpus (unbounded), wrapped in the same "
            "memory-index block. Use to enumerate lessons the index omits."
        ),
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Print compact context (L3 + L2 combined)",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show which memory tiers are available",
    )
    parser.add_argument(
        "--recall",
        action="store_true",
        help="Recall raw observations (use with --query and --limit)",
    )
    parser.add_argument(
        "--why",
        type=str,
        default=None,
        metavar="ID_OR_TOPIC",
        help=(
            "Provenance view for ONE lesson by stable id (obs-xxx) or ALL "
            "lessons under one topic: source, source_ticket, evidence, "
            "timestamp, confidence, impact, domain, and which file (L1 or "
            "which archive month) it lives in. A missing field is named, "
            "never invented (WOT-2026-049j)."
        ),
    )
    parser.add_argument(
        "--query",
        type=str,
        default=None,
        help="Keyword filter for --recall (ranked by similarity)",
    )
    parser.add_argument(
        "--id",
        type=str,
        default=None,
        dest="obs_id",
        help=(
            "Expand ONE lesson by its stable id, as printed by --bootstrap "
            "(`id: obs-xxx`). Fails closed when the id does not exist."
        ),
    )
    parser.add_argument(
        "--ticket",
        type=str,
        default=None,
        help=(
            "Derive recall queries from the active work_plan.md of this ticket "
            "(title terms + Files Likely Touched stems) instead of --query"
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=15,
        help="Max observations to return (default: 15)",
    )
    parser.add_argument(
        "--budget",
        type=int,
        default=None,
        help=(
            f"Byte budget for --recall output (default: {_RECALL_BYTE_BUDGET} "
            f"without --headlines, 2000 with --headlines). Entries beyond it "
            f"are omitted WHOLE and named, never truncated."
        ),
    )
    parser.add_argument(
        "--headlines",
        action="store_true",
        help=(
            "Compact output: one line per lesson with its headline "
            "(short signal). Same selection and order as full recall. "
            "Budget cap measured in UTF-8 bytes; footer is reserved before "
            "the loop. Default budget: 2000 bytes (24000 without --headlines)."
        ),
    )
    parser.add_argument(
        "--caller",
        type=str,
        default="agent",
        help=(
            "Identifier for the caller of this recall (e.g. session id, "
            "agent name). Written to the recall telemetry log. "
            "Default: agent."
        ),
    )
    parser.add_argument(
        "--usage-report",
        action="store_true",
        help=(
            "Print a usage report from the recall log (read-only). Requires "
            "--since <ISO-8601 date>.  Mutually exclusive with other modes."
        ),
    )
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        help=(
            "Start date for --usage-report (ISO-8601).  Required with --usage-report."
        ),
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=30,
        help=("Window in days for --usage-report verdict (default: 30)."),
    )

    args = parser.parse_args()

    # El anclaje vive SOLO durante el trabajo y se restaura al salir:
    # un CLI no deja variables globales puestas. Ver `_anchored_env`.
    with _anchored_env():
        return _run(args)


def _run(args: argparse.Namespace) -> int:  # noqa: C901
    """Cuerpo de `main` con la raiz de memoria ya anclada."""
    # Determine mode from flags
    mode = "bootstrap" if args.bootstrap else ""

    if args.full:
        if mode:
            print("Error: Use only one mode flag at a time", file=sys.stderr)
            return 1
        mode = "full"

    if args.compact:
        if mode:
            print("Error: Use only one mode flag at a time", file=sys.stderr)
            return 1
        mode = "compact"

    if args.status:
        if mode:
            print("Error: Use only one mode flag at a time", file=sys.stderr)
            return 1
        mode = "status"

    if args.recall:
        if mode:
            print("Error: Use only one mode flag at a time", file=sys.stderr)
            return 1
        mode = "recall"

    if args.why:
        if mode:
            print("Error: Use only one mode flag at a time", file=sys.stderr)
            return 1
        mode = "why"

    if args.usage_report:
        if mode:
            print("Error: Use only one mode flag at a time", file=sys.stderr)
            return 1
        mode = "usage_report"

    # Default mode
    if not mode:
        mode = "bootstrap"

    # Execute mode
    if mode == "bootstrap":
        ctx, failed = _session_context()
        print(ctx)
        if failed:
            print("Memory index could not be loaded.", file=sys.stderr)
            return 1

    elif mode == "full":
        # El indice SIN presupuesto: todas las lecciones, mismo formato y
        # envoltorio que `--bootstrap` (ronda 5: antes llamaba a
        # `get_bootstrap_context`, capado a 60 y con `[truncated]`). Corpus
        # vacio = rc 0 con mensaje, igual que `--bootstrap`; fallo de carga =
        # rc 1 con aviso, tambien igual (ronda 6, sonnet).
        try:
            ctx = get_session_index(None)
        except Exception as exc:
            print(
                f"Memory index could not be loaded ({type(exc).__name__}: {exc}).",
                file=sys.stderr,
            )
            return 1
        print(
            ctx or "Memoria del proyecto: el corpus esta vacio (aun no hay lecciones)."
        )

    elif mode == "compact":
        ctx = get_compact_context()
        if ctx:
            print(ctx)
        else:
            print("# Compact Context\n\nNo memory files found.", file=sys.stderr)
            return 1

    elif mode == "status":
        print(_format_status())

    elif mode == "recall":
        # Track recall telemetry: mode + query before producing output.
        if args.obs_id:
            recall_mode = "id"
            recall_query = args.obs_id.strip()
        elif args.ticket:
            recall_mode = "ticket"
            recall_query = args.ticket
        elif args.query:
            recall_mode = "query"
            recall_query = args.query
        else:
            recall_mode = "plain"
            recall_query = ""

        if args.obs_id:
            # Resolucion EXACTA por id, y fail-CLOSED si no existe. Nunca cae al
            # recall plano: devolver ruido cuando el agente pidio una leccion
            # concreta es un falso verde silencioso -- el agente creeria estar
            # leyendo lo que pidio. WOT-2026-057b.
            wanted = args.obs_id.strip()
            match = [
                obs
                for obs in recall_observations(query=None, limit=1_000_000)
                if str(obs.get("id") or "") == wanted
            ]
            if not match:
                print(
                    f"No lesson with id {wanted!r}. Los ids salen de --bootstrap "
                    "(`id: obs-xxx`); si no aparece, la leccion no esta en este "
                    "archive.",
                    file=sys.stderr,
                )
                _write_recall_log(
                    Path(os.environ.get("AGENT_PROJECT_ROOT") or _PROJECT_ROOT),
                    args.caller,
                    recall_mode,
                    recall_query,
                    [],
                )
                return 1
            effective_budget = _resolve_recall_budget(args)
            if args.headlines:
                _print_headlines(match, budget=effective_budget)
            else:
                _print_recall(match, budget=effective_budget)
            _write_recall_log(
                Path(os.environ.get("AGENT_PROJECT_ROOT") or _PROJECT_ROOT),
                args.caller,
                recall_mode,
                recall_query,
                match,
            )
            return 0

        if args.ticket:
            # Ticket-relevant recall: multi-query derived from the work plan,
            # deduplicated by signal.
            queries = _queries_from_work_plan(args.ticket)
            if not queries:
                print(
                    f"No work_plan context found for {args.ticket}; "
                    "falling back to plain recall.",
                    file=sys.stderr,
                )
            seen: set[str] = set()
            observations = []
            for q in queries or [None]:
                for obs in recall_observations(query=q, limit=args.limit):
                    sig = str(obs.get("signal") or "")
                    if sig not in seen:
                        seen.add(sig)
                        observations.append(obs)
            observations = observations[: args.limit]
        else:
            # Se recupera el pool COMPLETO y se ordena por relevancia ANTES de
            # cortar. Al reves (cortar y luego ordenar) el `--limit` decide por
            # orden de pool y el ranking solo reordena lo que ya sobrevivio --
            # que es exactamente el defecto que esto corrige. WOT-2026-057b.
            pool = recall_observations(query=args.query, limit=1_000_000)
            if not pool and args.query and len(args.query.split()) > 1:
                pool = _pool_for_multiword(args.query)
            observations = _rank_by_similarity(pool, args.query)[: args.limit]
        if not observations:
            print("No observations found.", file=sys.stderr)
            _write_recall_log(
                Path(os.environ.get("AGENT_PROJECT_ROOT") or _PROJECT_ROOT),
                args.caller,
                recall_mode,
                recall_query,
                [],
            )
            return 1
        # El recorte por CARDINALIDAD (`--limit`) tambien se declara: es el que
        # mas muerde (default 15 sobre un pool de cientos) y era el unico corte
        # que quedaba en silencio tras arreglar el de bytes (bucle L915).
        # Change 4 (MAJOR): in headlines mode the warning is reserved in the
        # footer budget; in plain mode it prints as before.
        limit_warning = ""
        if len(observations) >= args.limit:
            total = len(recall_observations(query=args.query, limit=1_000_000))
            if total > len(observations):
                limit_warning = (
                    f"[{total - len(observations)} coincidencia(s) mas no "
                    f"mostradas: --limit {args.limit}. Sube --limit o acota "
                    "--query.]\n"
                )
                if not args.headlines:
                    print(limit_warning)
        effective_budget = _resolve_recall_budget(args)
        if args.headlines:
            _print_headlines(
                observations, budget=effective_budget, limit_warning=limit_warning
            )
        else:
            _print_recall(observations, budget=effective_budget)
        _write_recall_log(
            Path(os.environ.get("AGENT_PROJECT_ROOT") or _PROJECT_ROOT),
            args.caller,
            recall_mode,
            recall_query,
            observations,
        )

    elif mode == "why":
        # Matchea por id EXACTO si parece uno (prefijo `obs-`), si no por
        # TOPIC (puede devolver varias entradas bajo el mismo topic -- el DoD
        # dice "para un id/topic dado", no "exactamente una entrada").
        wanted = args.why.strip()
        if not wanted:
            # Codex Review 2 (WOT-2026-049j): `if args.why:` acepta
            # "   " (solo espacios) porque la cadena es truthy ANTES del
            # .strip(); sin este rechazo explicito, un topic vacio buscaria
            # entradas con `topic == ""`, un caso legitimo pero NO lo que el
            # usuario quiso decir al pasar solo espacios.
            print(
                "--why necesita un id (obs-xxx) o topic no vacio.",
                file=sys.stderr,
            )
            return 1
        pool = recall_observations(query=None, limit=1_000_000)
        if wanted.startswith("obs-"):
            matches = [obs for obs in pool if str(obs.get("id") or "") == wanted]
        else:
            matches = [obs for obs in pool if str(obs.get("topic") or "") == wanted]
        if not matches:
            print(
                f"No lesson with id/topic {wanted!r}. Los ids salen de "
                "--bootstrap (`id: obs-xxx`); los topics de cualquier entrada "
                "de --recall.",
                file=sys.stderr,
            )
            return 1
        _print_why(matches)

    elif mode == "usage_report":
        return _usage_report(
            Path(os.environ.get("AGENT_PROJECT_ROOT") or _PROJECT_ROOT),
            args.since,
            args.window_days,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
