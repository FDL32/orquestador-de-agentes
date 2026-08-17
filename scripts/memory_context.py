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
        Indice: archive portable del MOTOR + del root activo (union), mas el
        mejor tier local. Las lineas `...[truncated]` son INDICE; llevan el `id`
        para expandirlas, y el pie declara cuantas lecciones NO muestra.

    python scripts/memory_context.py --recall --query "<termino>" [--limit N]
        Lecciones COMPLETAS, ordenadas por COBERTURA de la consulta (IDF+Jaccard
        via find_similar_signals). Una consulta de varias palabras que no case
        literalmente cae a busqueda por terminos: no devuelve vacio.
        Declara lo que omite, por bytes (--budget) y por cardinalidad (--limit).

    python scripts/memory_context.py --recall --id obs-<slug>
        Expande UNA leccion por su id exacto -- el que imprime --bootstrap.
        Fail-closed: un id inexistente sale con rc=1, nunca cae a recall plano.

    python scripts/memory_context.py --recall --ticket <TICKET_ID>
        Deriva las consultas del work_plan.md activo.

    python scripts/memory_context.py --status
        Que tiers locales existen, y contra que project root se resolvieron.

    python scripts/memory_context.py --compact
        Contexto para el hook de pre-compact (archive capado por recencia + L3/L2).

Nota: si el hook `SessionStart` esta cableado, el INDICE ya entra solo al abrir
sesion. Lo que sigue haciendo falta a mano es la EXPANSION (`--recall`).
"""

from __future__ import annotations

import argparse
import contextlib
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
    (b) `--id`, la puerta "exacta y fail-closed", daba un falso negativo
    indistinguible de la verdad -- con un mensaje que afirmaba que la leccion no
    existia.

    Se respeta una `AGENT_PROJECT_ROOT` ya puesta: si el operador la fijo, manda.
    Solo se rellena cuando falta, y con el workspace de dogfooding que el propio
    motor declara en `.agent/config/motor_workspace.txt` (WOT-2026-053h): un
    NOMBRE resuelto contra `parent(motor_root)`, nunca una ruta, para no pinear
    la maquina.

    NO escribe el entorno del proceso: DEVUELVE la raiz y el llamante la aplica
    con `_anchored_env`, que la restaura al salir. La primera version hacia
    `os.environ[...] = ...` directo y eso convirtio una funcion de lectura en un
    efecto GLOBAL: cualquier test que llamara a `main()` dejaba la variable
    puesta para el resto de la sesion de pytest, y el sintoma aparecia en
    `test_scope_gate` -- un fichero que este ticket no toca (11 rojos en suite,
    32 verdes en aislado). Un state-leak clasico y de los caros: el dano se ve
    lejos de la causa.

    Before: puede haber o no `AGENT_PROJECT_ROOT` en el entorno.
    During: lee el declarante si hace falta. Sin red, sin subprocess, sin
        escrituras, nunca lanza.
    After: devuelve la ruta del workspace declarado, o ``None`` -- que es un
        resultado NORMAL (no hay declarante, o ya hay una raiz fijada).
    """
    import os

    if os.environ.get("AGENT_PROJECT_ROOT"):
        return None
    try:
        decl = _MOTOR_ROOT / ".agent" / "config" / "motor_workspace.txt"
        if not decl.is_file():
            return None
        name = next(
            (
                ln.strip()
                for ln in decl.read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.lstrip().startswith("#")
            ),
            "",
        )
        if (
            not name
            or name in {".", ".."}
            or any(sep in name for sep in ("/", "\\", ":"))
        ):
            return
        candidate = _MOTOR_ROOT.parent / name
        if candidate.is_dir() and (candidate / ".agent").is_dir():
            return candidate
    except (OSError, ValueError):
        return None
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
    get_bootstrap_context,
    get_compact_context,
    get_memory_tier_status,
    recall_observations,
)


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
    for score, surface, _label, terms in ranked:
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
        if omitted or (used + len(line) > budget and used > 0):
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


def main() -> int:
    """Main entry point for memory_context CLI."""
    _ensure_utf8_stdout()
    parser = argparse.ArgumentParser(
        description="Memory context: bootstrap, compact, recall, status"
    )
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="Print bootstrap context (L3 -> L2 -> L1 fallback)",
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
        default=_RECALL_BYTE_BUDGET,
        help=(
            f"Byte budget for --recall output (default: {_RECALL_BYTE_BUDGET}). "
            "Entries beyond it are omitted WHOLE and named, never truncated."
        ),
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

    # Default mode
    if not mode:
        mode = "bootstrap"

    # Execute mode
    if mode == "bootstrap":
        ctx = get_bootstrap_context()
        if ctx:
            print(ctx)
        else:
            print("# Bootstrap Context\n\nNo memory files found.", file=sys.stderr)
            return 1

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
                return 1
            _print_recall(match, budget=args.budget)
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
            return 1
        # El recorte por CARDINALIDAD (`--limit`) tambien se declara: es el que
        # mas muerde (default 15 sobre un pool de cientos) y era el unico corte
        # que quedaba en silencio tras arreglar el de bytes (bucle L915).
        if len(observations) >= args.limit:
            # `limit=0` NO significa "sin tope" en esta puerta: `recall_observations`
            # hace `filtered[:limit]` y devuelve CERO. Medido en el bucle L915 --
            # el mock del test implementaba la semantica que yo supuse y tapaba
            # que la real es otra (mock drift). Se usa un tope alto explicito.
            total = len(recall_observations(query=args.query, limit=1_000_000))
            if total > len(observations):
                print(
                    f"[{total - len(observations)} coincidencia(s) mas no "
                    f"mostradas: --limit {args.limit}. Sube --limit o acota "
                    "--query.]\n"
                )
        _print_recall(observations, budget=args.budget)

    return 0


if __name__ == "__main__":
    sys.exit(main())
