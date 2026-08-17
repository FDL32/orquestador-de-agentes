#!/usr/bin/env python3
"""Central memory loader: portable archive (UNION) + best local tier.

Single entry point for project memory across the system (bootstrap, review
bridge, pre-compact hook, recall gate).

WHAT IT LOADS, in this order:

  1. PORTABLE ARCHIVE -- `.agent/runtime/memory/archive/observations.*.jsonl`,
     the ONLY memory surface that travels by git (L1/L2/L3 are gitignored).
     Read as the UNION of the MOTOR's archive and the active root's, because
     they are DISJOINT sets and both matter: the motor carries the engineering
     lessons, the destination the topology ones. Measured 2026-08-17: 207 + 135,
     intersection ZERO under five distinct keys.
  2. BEST LOCAL TIER -- L3 profile (`memory_profile.md`), else L2 rules
     (`memory_rules.md`), else raw L1 (`observations.jsonl`).

The old summary of this module said "L3 -> L2 -> L1 fallback hierarchy". That
described the state BEFORE WOT-2026-024r wired the archive in, and it survived
two tickets after becoming false -- a stale docstring on the module every cold
agent's memory flows through. The tier fallback is now step 2 of two, not the
whole design.

Usage:
    from bus.memory_loader import (
        get_bootstrap_context,   # index: archive union + local tier, CAPPED
        get_review_context,      # by domain, UNCAPPED (a review must not lose)
        get_compact_context,     # pre-compact hook, capped by recency
        recall_observations,     # expansion gate: full signals, no truncation
    )

Design:
    - The bootstrap output is an INDEX, not the corpus: entries over
      `_ARCHIVE_SIGNAL_CAP` carry `...[truncated]` plus their `id`, and the
      footer names how many lessons it withheld. Expansion is
      `memory_context.py --recall --query <term>` or `--id <obs-id>`.
    - Caps are per-CALLER, never global: only the arranque index is capped.
      A cap leaking into `get_review_context` cost the Manager 14 of 74 lessons
      while deciding APPROVE/CHANGES.
    - Quota per origin: capping a UNION by global recency lets whichever repo
      was touched last evict the other wholesale. Recency is not relevance.
    - Safe: never raises on missing/corrupted files; returns empty strings. The
      fail-CLOSED barrier for a corrupt archive is `validate_observations
      --strict`, wired in prepush.
"""

import importlib
import json
import re
import sys
import types
from pathlib import Path
from typing import Any


_PROJECT_ROOT_BOOTSTRAP = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT_BOOTSTRAP) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT_BOOTSTRAP))

_RUNTIME_PACKAGE_ROOT = str(_PROJECT_ROOT_BOOTSTRAP / "runtime")
_runtime_pkg = sys.modules.get("runtime")
if _runtime_pkg is None:
    _runtime_pkg = types.ModuleType("runtime")
    _runtime_pkg.__path__ = [_RUNTIME_PACKAGE_ROOT]
    sys.modules["runtime"] = _runtime_pkg
else:
    runtime_paths = list(getattr(_runtime_pkg, "__path__", []))
    if _RUNTIME_PACKAGE_ROOT not in runtime_paths:
        runtime_paths.insert(0, _RUNTIME_PACKAGE_ROOT)
        _runtime_pkg.__path__ = runtime_paths

get_agent_dir = importlib.import_module("runtime.project_root").get_agent_dir

# WOT-2026-057b: resolucion del motor por el link, via `runtime/` y nunca via
# `scripts/` (ver `_resolve_motor_root`). Se carga con el mismo `importlib` que
# `get_agent_dir` porque este modulo se importa antes de que `runtime` sea un
# paquete normal en `sys.path`.
_resolve_motor_root_from_link = importlib.import_module(
    "runtime.motor_link"
).resolve_motor_root

# WOT-2026-024r (A1): the portable archive reader. Imported from `bus/`, never
# from `scripts/reconcile_portable_memory.py` -- that would invert the dependency
# (bus -> scripts) and drag in `--apply` and the "promoted == is in a commit"
# semantics, which belong to reconcile and not to a reader.
from bus.portable_memory_archive import (  # noqa: E402
    CorruptArchiveError,
    dedup_key,
    is_lesson,
    read_archive_observations,
)


# Default max observations when falling back to raw L1.
_L1_FALLBACK_LIMIT = 15

# WOT-2026-024r (A2): cap on archive entries handed to `get_compact_context`.
# `pre_compact_hook.py` injects that string WHOLE and UNTRUNCATED, so an
# uncapped archive would land 30x the previous payload at the exact moment the
# session compacts for lack of context.
#
# SWEEP (snapshot 2026-08-03, archive of 175 entries; the numbers are EVIDENCE,
# the invariant is "bounded", not any particular figure):
#     cap  10 ->  3046 chars (~760 tokens)
#     cap  25 ->  7375 chars (~1840 tokens)
#     cap  50 -> 14831 chars (~3700 tokens)
#     cap 100 -> 29490 chars (~7370 tokens)
#     cap 175 -> 49526 chars (~12380 tokens)  <- uncapped today
# The cost is LINEAR (~74 chars/entry): there is no plateau and therefore no
# optimum to discover. Picking a cap is choosing a token budget, not tuning a
# threshold -- which is why this is a knob and not a contract. 50 buys ~3700
# tokens, roughly a third of today's archive and the NEWEST third, which is
# what a compaction needs. Below the cap nothing is dropped.
_COMPACT_ARCHIVE_CAP = 50

# WOT-2026-057a. Projection cap for archive index lines, and the marker that
# makes the cut VISIBLE. The marker is the load-bearing half: the previous code
# cut at 200 with no marker, so a decapitated lesson looked exactly like a short
# one and the agent had no way to know 79% of the corpus was missing.
#
# The number is a token budget, not a tuned threshold -- there is no plateau to
# discover (cost is linear in corpus size) and no cap survives growth of ~52
# entries/month. Measured on the 207-entry corpus (2026-08-17):
#     cap  200 ->  40.951 chars (~10.2k tok)   <- previous value, silent
#     cap  320 ->  63.000 chars (~15.8k tok)   <- here
#     cap  600 -> 105.886 chars (~26.5k tok)
#     uncapped -> 194.982 chars (~48.7k tok)
# 320 clears the median first sentence (where a BLUF-written rule states itself)
# without pretending to deliver the lesson. The invariant is "bounded AND
# marked", never any particular figure.
_ARCHIVE_SIGNAL_CAP = 320
_TRUNCATION_MARKER = "...[truncated]"

# WOT-2026-057a. Cardinality cap for the bootstrap index.
#
# This one exists because the union fix CREATED the problem it caps: reading the
# motor as well as the destination took the corpus from 135 to 342 entries and
# the bootstrap from ~5.2k to ~28.7k tokens. Curing blindness by causing an
# overflow is not a cure, it is a relocation -- and the corpus grows ~52
# entries/month, so this is structural, not a one-off.
#
# Measured at 410 chars/line (320 signal + timestamp/topic/id overhead):
#     cap  60 -> ~24.600 chars (~6.1k tok)   <- here
#     cap 120 -> ~49.200 chars (~12.3k tok)
#     uncapped (342 today) -> ~140.000 chars (~35k tok)
#
# 60 newest lessons is what an arranque can carry without crowding out the work.
# The remainder is NOT lost: it stays reachable through `--recall`, which is why
# the index names how many it withheld. The invariant is "bounded AND declared";
# the figure is a budget, and it will need revisiting as the corpus grows.
_BOOTSTRAP_INDEX_CAP = 60

# WOT-2026-057b. Presupuesto en BYTES para `get_review_context`.
#
# La union dejo el review SIN capar a proposito: "un review decide
# APPROVE/CHANGES y no puede perder lecciones", y un cap por CARDINALIDAD ya le
# costo 14 de 74 en su momento. El invariante es correcto; la consecuencia no se
# midio. Medido 2026-08-17 en la ruta productiva:
#     render_loader_rules('code') -> 126.049 chars ~31.512 tok
# o sea ~31.5k tokens antes de que el Manager vea una linea de diff, creciendo
# ~103 entradas/mes. Y contradecia el argumento de este mismo modulo: "curar la
# ceguera causando un desbordamiento no es una cura, es una reubicacion".
#
# La distincion que resuelve la tension: "no puede PERDER lecciones" NO es lo
# mismo que "no puede tener PRESUPUESTO". Se descartan lineas ENTERAS y se
# NOMBRAN -- el patron de `_print_recall` --, nunca un recorte mudo. 40.000
# chars (~10k tok) caben en un prompt de review dejando margen para el diff,
# que es lo que el Manager viene a leer.
_REVIEW_BYTE_BUDGET = 40000


# --- Paths (computed lazily for testability) ---


def _get_memory_dir() -> Path:
    """Get the memory directory path.

    Before: Requires get_agent_dir() to be available.
    During: Computes path lazily each call (no caching) so tests can patch.
    After: Returns Path to .agent/runtime/memory/.
    """
    return get_agent_dir() / "runtime" / "memory"


def _get_observations_file() -> Path:
    """Get path to observations.jsonl."""
    return _get_memory_dir() / "observations.jsonl"


def _get_rules_file() -> Path:
    """Get path to memory_rules.md (L2)."""
    return _get_memory_dir() / "memory_rules.md"


def _get_profile_file() -> Path:
    """Get path to memory_profile.md (L3)."""
    return _get_memory_dir() / "memory_profile.md"


# --- Internal helpers ---


def _try_read_file(path: Path) -> str:
    """Read a text file safely, returning empty string on any error.

    Before: path must be a Path object.
    During: Reads the file with UTF-8 encoding, catching IOErrors.
    After: Returns file content as string, or '' if file missing/unreadable.
    """
    try:
        if path.exists():
            return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        pass
    return ""


def _read_observations(limit: int = _L1_FALLBACK_LIMIT) -> list[dict[str, Any]]:
    """Read the last N observations from observations.jsonl.

    Before: Requires observations.jsonl to exist (or returns empty list).
    During: Parses JSONL lines, keeping only valid dict entries.
            Reads from the end of the file to get the most recent entries.
    After: Returns a list of up to ``limit`` observation dicts, newest first.
           ``limit <= 0`` means unlimited (the whole file).
    """
    obs_file = _get_observations_file()
    if not obs_file.exists():
        return []

    try:
        text = obs_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    lines = text.splitlines()
    # Read from end to collect the most recent entries
    observations: list[dict[str, Any]] = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            if isinstance(entry, dict):
                observations.append(entry)
                # limit <= 0 means unlimited (read the whole file)
                if limit > 0 and len(observations) >= limit:
                    break
        except json.JSONDecodeError:
            continue

    return observations


def _format_observations_as_text(observations: list[dict[str, Any]]) -> str:
    """Format a list of observation dicts as a markdown bullet list.

    Before: Requires a list of observation dicts (may be empty).
    During: Formats each entry as a bullet with timestamp, topic, signal, source.
    After: Returns a markdown string, or empty string if list is empty.
    """
    if not observations:
        return ""

    lines = [
        "# Raw Observations (L1 fallback)",
        "",
        f"Most recent {len(observations)} observations:",
        "",
    ]
    for obs in observations:
        ts = str(obs.get("timestamp") or "")[:19]
        topic = obs.get("topic", "general")
        signal = str(obs.get("signal") or "")[:200]
        source = obs.get("source", "unknown")
        lines.append(f"- [{ts}] **{topic}**: {signal} ({source})")

    return "\n".join(lines)


def _get_repo_root() -> Path:
    """Repo root that owns the portable archive.

    Derived from ``_get_memory_dir()`` (``<root>/.agent/runtime/memory``) rather
    than from ``get_agent_dir()`` so that any caller which redirects the memory
    dir -- as the existing tests do -- also redirects the archive. Resolving the
    root independently would let a test that patched only the memory dir still
    read the REAL motor archive: an isolation leak that turns a hermetic test
    into one that silently depends on this machine's memory.
    """
    return _get_memory_dir().parent.parent.parent


def _resolve_motor_root() -> Path | None:
    """Root of the MOTOR repo, or ``None`` when it cannot be resolved.

    WOT-2026-057a. Deliberately does NOT consult ``AGENT_PROJECT_ROOT``, and
    that omission is the whole point of this function.

    Measured 2026-08-17: without that env var the loader already resolved to the
    motor and read all 207 lessons -- from the motor AND with the cwd in the
    destination. The 135-vs-207 defect appeared ONLY when the var was set to the
    destination, which is the CANONICAL way to operate per AGENTS.md
    ("el motor se invoca siempre con esta variable apuntando al workspace_activo").

    So the defect was never a broken reader: it is a COLLISION OF CONTRACTS.
    ``AGENT_PROJECT_ROOT`` answers "where does the OPERATIONAL STATE live"; the
    archive asks "where does the PORTABLE MEMORY live". Two different questions,
    one variable. The first draft of this fix put that var FIRST in the
    precedence chain -- it reproduced the very cause it meant to remove.

    There is deliberately NO ``__file__`` fallback, and that omission is load
    bearing too. ``__file__`` always points at THIS machine's motor, so a test
    that redirects only the memory dir -- which is exactly what the ``wired``
    fixture does on purpose, documenting that patching ``_get_repo_root`` would
    be "REDUNDANTE" -- would silently read the real 207-entry archive. That is
    the isolation leak ``_get_repo_root``'s own docstring warns about, and
    measured on the first draft of this fix it turned 11 hermetic tests red by
    feeding them this machine's memory. Resolution therefore hangs off the
    ACTIVE root only: redirect the root and the motor lookup follows.

    Before: no state required; the link file may be absent.
    During: reads ``motor_destination_link.json`` via ``resolve_motor_link``,
        anchored at the ACTIVE root. No writes.
    After: returns an existing directory or ``None`` when there is no link --
        in which case the active root already IS the motor (running from it) or
        the motor is genuinely unreachable, and the caller degrades to the local
        archive. Never raises.
    """
    try:
        # `runtime.motor_link`, NUNCA `scripts.destination_context`: `bus/` no
        # puede importar de `scripts/` -- frontera cableada en
        # `tests/test_bus_boundary.py`, con un segundo test que ademas bloquea
        # la evasion por `importlib`. La primera version de este fix cruzo esa
        # frontera y la suite canonica la caso, correctamente.
        #
        # Y el helper correcto YA EXISTIA: `runtime/motor_link.py` se declara
        # "single point of truth for external-motor topology resolution", es
        # puro y devuelve `None` si no hay link. Importar de `scripts/` no solo
        # rompia la frontera: duplicaba logica ya escrita.
        candidate = _resolve_motor_root_from_link(_get_repo_root())
        if candidate is not None and candidate.is_dir():
            return candidate
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def _read_portable_archive() -> list[dict[str, Any]]:
    """Portable archive entries from the MOTOR **and** the active root.

    WOT-2026-024r (A1): the tracked archive is the only memory surface that
    travels by git. Reading it is what turns it from write-only into memory.

    WOT-2026-057a: A1 wired the archive to bootstrap but resolved it from the
    ACTIVE root, so operating a destination (the canonical mode) showed the
    destination's 135 entries and NONE of the motor's 207 -- measured
    intersection ZERO under five distinct keys, including the repo's own
    ``dedup_key``. A1 fixed "memory written and never read" and landed pointing
    at the wrong repo.

    The union is the CONTRACT, not an option. The destination holds 14 lessons
    that exist nowhere else, and they are precisely the motor/destination
    TOPOLOGY ones (where the backlog lives, where the canonical last-run lives)
    -- the lessons an agent working IN the destination needs most. Reading only
    the motor would hide them, which is why the barrier test has two prongs.

    Precedence is per ENTRY and the ACTIVE root wins, same rule A1 already uses
    everywhere else: a local copy may have been edited after being archived.

    Fail-safe by contract of this module ("never raises"): a corrupt archive
    degrades the context instead of breaking every caller of the loader
    (bootstrap, review bridge, pre-compact hook). The fail-CLOSED barrier for a
    corrupt archive is ``validate_observations --strict``, wired in prepush.
    """

    def _safe_read(root: Path | None) -> list[dict[str, Any]]:
        if root is None:
            return []
        try:
            return read_archive_observations(root)
        except (CorruptArchiveError, OSError, ValueError):
            return []

    active_root = _get_repo_root()
    active = _safe_read(active_root)

    motor_root = _resolve_motor_root()
    if motor_root is None or motor_root == active_root:
        return active

    motor = _safe_read(motor_root)
    if not motor:
        return active
    if active:
        seen = {dedup_key(entry) for entry in active}
        motor = [e for e in motor if dedup_key(e) not in seen]
    if not motor:
        return active

    # Tag provenance so the index can reserve a quota per origin. Without it the
    # cap is a global recency race and whichever repo was touched last evicts
    # the other wholesale -- see `_cap_preserving_origins`. Copies are shallow
    # on purpose: entries are read-only here and the tag must not reach disk.
    return [{**entry, "_origin": "local"} for entry in active] + [
        {**entry, "_origin": "motor"} for entry in motor
    ]


def _sorted_newest_first(
    observations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Entries newest-first. A missing ``timestamp`` sorts last, never first."""
    return sorted(
        observations,
        key=lambda obs: str(obs.get("timestamp") or ""),
        reverse=True,
    )


def _cap_by_recency(
    observations: list[dict[str, Any]], cap: int
) -> list[dict[str, Any]]:
    """The ``cap`` newest entries, or all of them when under the cap.

    WOT-2026-024r (A2). Bounds what `get_compact_context` hands to the
    pre-compact hook, which injects it untruncated. Sorting is explicit rather
    than assumed: the archive arrives in file-and-line order (oldest first), so
    slicing without sorting would keep the OLDEST entries -- the exact opposite
    of what a compaction needs.

    Before: ``observations`` may be in any order; ``cap`` is a positive int.
    During: sorts by ``timestamp`` descending; a missing timestamp sorts last
        (empty string) and never jumps ahead of a dated entry.
    After: returns at most ``cap`` entries, newest first. Never raises.
    """
    if len(observations) <= cap:
        return observations
    return sorted(
        observations,
        key=lambda obs: str(obs.get("timestamp") or ""),
        reverse=True,
    )[:cap]


def _cap_preserving_origins(
    observations: list[dict[str, Any]], cap: int
) -> list[dict[str, Any]]:
    """Cap the index WITHOUT letting one origin evict the other.

    WOT-2026-057a. Capping the UNION by global recency treats two corpora as if
    they were one, and they are not. Measured 2026-08-17: the destination's
    archive ends 2026-07-31 while the motor's runs to 2026-08-16, so a plain
    recency cap of 60 yielded 55 motor / 5 destination -- and the destination's
    exclusive lessons are the motor/destination TOPOLOGY ones, precisely what an
    agent operating THERE needs. Fixing one blindness by creating the mirror
    blindness is not a fix.

    Worse, the split was an accident of the calendar: whichever repo happens to
    be active wins, and nothing guarantees the other is represented. Reserving a
    quota turns that accident into an invariant.

    Recency is NOT relevance. Within each origin recency is a reasonable proxy;
    across origins it is just "which repo was touched last".

    Before: ``observations`` carries ``_origin`` on entries the union tagged;
        ``cap`` is positive.
    During: pure list ops. Splits by origin, gives each half of the cap (or all
        it has, redistributing the remainder to the other), then re-sorts the
        merged result newest-first. No I/O.
    After: at most ``cap`` entries, each origin represented in proportion to
        what it can fill. Falls back to plain recency when only one origin is
        present.
    """
    if len(observations) <= cap:
        return observations

    # Las plantillas autogeneradas no compiten por el indice. Medido sobre el
    # corpus real (2026-08-17): de las 135 entradas del destino, 116 son
    # plantillas del paso `observations:` del cierre ("Decisiones
    # arquitectonicas documentadas en X") y solo 19 son lecciones. Al ser mas
    # RECIENTES ocupaban 25 de las 30 plazas de la cuota y dejaban fuera 14 de
    # las 19 lecciones reales: el arranque gastaba su presupuesto en ruido con
    # schema valido. `is_lesson` ya filtra por PROVENIENCIA en la puerta de
    # recall; aqui se aplica donde faltaba. No borra nada -- las plantillas
    # siguen en el archive y siguen alcanzables por `--recall`.
    groups: dict[str, list[dict[str, Any]]] = {}
    for obs in observations:
        groups.setdefault(str(obs.get("_origin") or "local"), []).append(obs)

    # El filtro de plantillas se aplica DENTRO de cada origen, nunca antes de
    # agrupar. Medido en el bucle L917: filtrando primero, un origen cuyas
    # entradas fuesen TODAS plantillas se vaciaba ENTERO antes de que la cuota
    # -- el mecanismo que existe justo para impedirlo -- llegara a protegerlo:
    #     local=80 plantillas + motor=80 lecciones, cap=60 -> {'motor': 60}
    # Es la ceguera D1 con el signo invertido. Y no es hipotetica: el paso
    # `observations:` del cierre genera plantillas AUTOMATICAMENTE mientras las
    # lecciones se escriben a mano, asi que la ratio de un destino tiende
    # monotonamente hacia las plantillas.
    #
    # El `or entries` de cada grupo es la guarda: un origen sin lecciones
    # conserva sus plantillas en vez de desaparecer. Mejor una plantilla visible
    # que un origen invisible -- lo segundo es indistinguible de "no existe".
    groups = {
        name: ([obs for obs in entries if is_lesson(obs)] or entries)
        for name, entries in groups.items()
    }

    if len(groups) < 2:
        only = next(iter(groups.values()))
        return only if len(only) <= cap else _cap_by_recency(only, cap)

    flat = [obs for entries in groups.values() for obs in entries]
    if len(flat) <= cap:
        return flat

    share = cap // len(groups)
    picked: list[dict[str, Any]] = []
    ranked: dict[str, list[dict[str, Any]]] = {}
    for name, entries in groups.items():
        # Ordenar EXPLICITAMENTE, no via `_cap_by_recency(entries, len(entries))`:
        # esa funcion devuelve la lista INTACTA cuando `cap >= len`, asi que
        # usarla para ordenar es un no-op silencioso. Medido en el bucle L915:
        # la cuota salia 30/30 correcta y elegia las 30 entradas MAS ANTIGUAS de
        # cada origen -- reparto correcto sobre la seleccion equivocada.
        ranked[name] = _sorted_newest_first(entries)
        take = min(share, len(entries))
        picked.extend(ranked[name][:take])

    # Redistribute unused quota to origins that still have entries left.
    remaining = cap - len(picked)
    if remaining > 0:
        for entries in ranked.values():
            already = min(share, len(entries))
            extra = entries[already : already + remaining]
            picked.extend(extra)
            remaining -= len(extra)
            if remaining <= 0:
                break

    return _cap_by_recency(picked, cap)


def _format_archive_as_text(
    observations: list[dict[str, Any]],
    cap: int | None = None,
    total_override: int | None = None,
) -> str:
    """Format archive entries as a markdown INDEX, honest about being one.

    ``cap`` is opt-in and belongs to the BOOTSTRAP index alone. It used to live
    inside this function, and that was wrong in a way only measurable from the
    consumers: `get_review_context` inherited it, so a domain with 74 lessons
    emitted 60 and the Manager decided APPROVE/CHANGES missing 14 -- the OLDEST
    ones by recency, which are exactly the sedimented scars that exist to veto
    reincidence. A degraded review approves work that should have been rejected,
    and that gets committed. An arranque budget has no authority over a review.

    ``total_override`` exists because a caller may cap BEFORE formatting
    (`get_compact_context` does, by recency). Without it this function counted
    the already-capped list and announced "50 lesson(s) travel with this repo"
    over a corpus of 342 -- false by ~7x, with no omission notice because
    ``total == len(shown)``. A positive false claim is worse than silence,
    especially at the moment the session is losing context.

    WOT-2026-057a. This projection used to truncate to 200 chars silently and
    print ``source_ticket or id``. Both halves were wrong, and measured:

    - The write contract sets NO length limit (``ap-schema.md``, and
      ``validate_observations`` has no length check), and the corpus complies:
      median signal 877 chars, max 3533. Cutting at 200 dropped 79% of the
      corpus, left 118 of 197 signals severed MID-WORD, and buried the operative
      rule of 82 entries past the cut. ``memory_consolidate`` marks its own cuts
      with ``...[truncated]`` precisely so a reader knows more exists; this
      reader did not, so a decapitated lesson was indistinguishable from a short
      one.
    - ``source_ticket`` is populated in 207/207 entries, so the ``or`` ALWAYS
      won and the ``id`` was never printed -- making expansion by ``id``
      impossible for every entry that had one (197 of 207).

    The fix is not "raise the cap": the full corpus is ~48.7k tokens and grows
    ~52 entries/month, so any fixed number is an expiry date. Instead this stays
    an index and says so, carrying the ``id`` that ``--recall`` needs to expand.

    Before: ``observations`` may be empty.
    During: pure formatting, no I/O.
    After: returns markdown, or ``""``. Truncated entries carry both the marker
        and their ``id``; entries under the cap are emitted whole.
    """
    if not observations:
        return ""
    total = total_override if total_override is not None else len(observations)
    shown = observations if cap is None else _cap_preserving_origins(observations, cap)
    lines = [
        "# Portable Memory (tracked archive)",
        "",
        f"{total} lesson(s) travel with this repo; showing the {len(shown)} newest.",
        "Entries marked [truncated] are INDEX LINES, not the whole lesson:",
        "expand with `python scripts/memory_context.py --recall --query <topic>`.",
        "",
    ]
    for obs in shown:
        ts = str(obs.get("timestamp") or "")[:19]
        topic = obs.get("topic", "general")
        raw = str(obs.get("signal") or "")
        obs_id = obs.get("id")
        ticket = obs.get("source_ticket") or obs_id or "unknown"
        if len(raw) > _ARCHIVE_SIGNAL_CAP:
            signal = raw[:_ARCHIVE_SIGNAL_CAP].rstrip() + _TRUNCATION_MARKER
            tag = f"{ticket} | id: {obs_id}" if obs_id else str(ticket)
        else:
            signal = raw
            tag = str(ticket)
        lines.append(f"- [{ts}] **{topic}**: {signal} ({tag})")
    if total > len(shown):
        lines.append("")
        lines.append(
            f"[{total - len(shown)} leccion(es) mas no mostrada(s) en este indice. "
            "Alcanzalas con `--recall --query <termino>`.]"
        )
    return "\n".join(lines)


# --- Public API ---


def get_bootstrap_context() -> str:
    """Load context for bootstrap: portable archive + best local tier.

    This is the primary entry point for session_bootstrap.md and any agent
    that needs a quick context summary of project memory.

    WOT-2026-024r (A1): the tracked portable archive is now ALWAYS included,
    not used as a last-resort fallback. Before this, memory promoted to the
    archive was versioned, pushed -- and read by nobody: the loader only ever
    looked at L3/L2/L1, all three gitignored. A backend cloning the repo got
    the archive and no way to reach it. Measured cost (2026-07-27): a lesson
    stored twice was repeated anyway and destroyed 7 tests. It was not a memory
    gap; it was memory written, versioned and never read.

    Before: memory files may or may not exist in the memory directory.
    During: reads the tracked archive, then the best available local tier
            (L3 profile -> L2 rules -> L1 raw observations). Entries the local
            tier already holds win over the archived copy: L1 is the LIVE copy
            and may have been edited after being archived, so on a stable-``id``
            collision the live entry is the newer truth.
    After: returns a markdown string combining both. Never returns None;
           returns empty string when there is no memory at all.
    """
    archived = _read_portable_archive()

    # Priority 1: L3 profile (brief, high-level)
    local = _try_read_file(_get_profile_file())
    if not local:
        # Priority 2: L2 rules (domain-organized rules)
        local = _try_read_file(_get_rules_file())
    live: list[dict[str, Any]] = []
    if not local:
        # Priority 3: L1 raw observations (last N entries)
        live = _read_observations()
        local = _format_observations_as_text(live)

    if archived and live:
        # Precedence is per ENTRY, not per source: drop the archived copy only
        # for entries the live tier already carries.
        seen = {dedup_key(entry) for entry in live}
        archived = [e for e in archived if dedup_key(e) not in seen]

    archive_text = _format_archive_as_text(archived, cap=_BOOTSTRAP_INDEX_CAP)
    sections = [s for s in (archive_text, local) if s]
    return "\n\n".join(sections)


def _archive_for_domain(domain: str | None) -> list[dict[str, Any]]:
    """Archive entries relevant to ``domain`` (all of them when domain is None).

    WOT-2026-024r (A2). The archive entries carry a populated ``domain`` field
    that speaks the SAME vocabulary as this gate's callers -- measured on the
    real repo (2026-08-03): 175 entries, ZERO without a domain, across 9 values
    (`delivery-hygiene` 55, `review-quality` 55, `testing` 15, ...), and
    `delivery-hygiene` is literally the domain in this module's own usage
    example. So the filter keys on ``domain``, not on ``topic``/``source``:
    those are free-form labels, while ``domain`` is the field the review gate
    already reasons in.

    Why this matters more than it looks: L2 (`memory_rules.md`) only declares
    the domains `architecture` and `lesson`, so a review asking for
    `delivery-hygiene` matched NOTHING in L2 while 55 lessons on exactly that
    subject sat unread in the tracked archive.

    Before: no state required; the archive may be missing or corrupt.
    During: reads the archive (never raises) and keeps entries whose ``domain``
        matches case-insensitively.
    After: returns the matching entries, or ``[]``. A domain with no matches
        returns ``[]`` -- the caller decides what to do with that, and here it
        deliberately does NOT widen to the whole archive: dumping 175 unrelated
        lessons into a specialised review is the noise this filter exists to
        prevent.
    """
    archived = _read_portable_archive()
    if domain is None:
        return archived
    wanted = domain.strip().lower()
    return [e for e in archived if str(e.get("domain") or "").lower() == wanted]


def get_review_context(domain: str | None = None) -> str:
    """Load context for review: portable archive + L2 rules, falling back to L1.

    WOT-2026-024r (A2): the tracked archive is now read here too. Until this
    ticket only `get_bootstrap_context` (A1) and the recall gate (WOT-2026-047d)
    reached it, so the MANAGER's review context -- the one that decides whether
    work is approved -- was blind to every lesson that travels by git. See
    `_archive_for_domain` for the measured numbers and why the filter keys on
    ``domain``.

    Before: Requires optional domain string (e.g., 'delivery-hygiene').
    During: Reads archive entries for the domain, then L2 rules (filtered by
            domain when given). Falls back to L1 raw observations if L2 is
            empty. Precedence is per ENTRY only against L1, exactly as A1 does
            it: L2 is prose, not entries, so there is nothing to dedup against.
    After: Returns a markdown string combining the portable memory section and
           the local rules/observations. Never returns None.
    """
    archived = _archive_for_domain(domain)

    rules = _try_read_file(_get_rules_file())
    if not rules:
        observations = _read_observations()
        local = _format_observations_as_text(observations) if observations else ""
        if archived and observations:
            # Per-ENTRY precedence: the LIVE L1 copy wins, because it may have
            # been edited after being archived (same rule as A1).
            seen = {dedup_key(entry) for entry in observations}
            archived = [e for e in archived if dedup_key(e) not in seen]
    elif domain is None:
        local = rules
    else:
        # Filter rules by domain; no matching domain rules -> all rules.
        local = _filter_rules_by_domain(rules, domain) or rules

    # Sin cap de CARDINALIDAD -- el review decide APPROVE/CHANGES y un cap por
    # numero de entradas ya le costo 14 de 74. Pero SI con techo en BYTES: ver
    # `_REVIEW_BYTE_BUDGET`. Se recortan lineas ENTERAS por el final (las mas
    # antiguas: el formateador emite newest-first) y se declara cuantas.
    archive_text = _format_archive_as_text(archived)
    if len(archive_text) > _REVIEW_BYTE_BUDGET:
        keep: list[str] = []
        used = 0
        dropped = 0
        for linea in archive_text.split("\n"):
            if linea.startswith("- [") and used + len(linea) + 1 > _REVIEW_BYTE_BUDGET:
                dropped += 1
                continue
            keep.append(linea)
            used += len(linea) + 1
        if dropped:
            keep.extend(
                [
                    "",
                    f"[{dropped} leccion(es) mas no mostrada(s) por presupuesto "
                    "de review. Alcanzalas con `--recall --query <termino>`.]",
                ]
            )
        archive_text = "\n".join(keep)
    sections = [s for s in (archive_text, local) if s]
    return "\n\n".join(sections)


def _has_wing_headers(rules_text: str) -> bool:
    """Check if the rules text uses the new Wing format (H2 Wing headers).

    Before: Requires the full text of memory_rules.md.
    During: Scans for ``## Wing:`` pattern.
    After: Returns True if Wing format detected, False otherwise.
    """
    return bool(re.search(r"^## Wing:\s+", rules_text, re.MULTILINE | re.IGNORECASE))


def _filter_rules_by_domain(rules_text: str, domain: str) -> str:
    """Filter memory_rules.md content to only include sections for a given domain.

    Before: Requires the full text of memory_rules.md and a domain string.
    During: Detects format (legacy H2 vs Wing H2/H3). Uses regex to find the
            matching ``## Domain: <domain>`` (legacy) or ``### Domain: <domain>``
            (Wing format) section and extract its content until the next Domain
            header or end of file.
    After: Returns the filtered section text, or empty string if domain not found.
            Retrocompat: if no Wing headers present, assumes legacy H2 format.
    """
    domain_lower = domain.lower()
    lines = rules_text.splitlines()

    # Detect format: Wing uses H3 (###), legacy uses H2 (##)
    has_wing = _has_wing_headers(rules_text)
    domain_pattern = r"^### Domain:\s*(.+)$" if has_wing else r"^## Domain:\s*(.+)$"
    domain_re = re.compile(domain_pattern, re.IGNORECASE)

    result_lines: list[str] = []
    in_target = False

    for line in lines:
        domain_match = domain_re.match(line)
        if domain_match:
            if in_target:
                break
            current_domain = domain_match.group(1).strip().lower()
            in_target = current_domain == domain_lower

        if in_target:
            result_lines.append(line)

    return "\n".join(result_lines).strip()


def get_compact_context() -> str:
    """Load combined context for pre-compact: portable archive + L3 + L2.

    WOT-2026-024r (A2): the tracked archive is now read here too. This gate
    feeds the pre-compact hook -- the moment a session is about to LOSE its
    context -- so it was the worst possible place to stay blind to the only
    memory surface that survives a clone.

    Unlike `get_review_context` there is no domain to narrow to, so the archive
    is capped by RECENCY instead: `pre_compact_hook.py` injects this string
    WHOLE and UNTRUNCATED into `additionalContext`, and the full archive is
    49526 of 51236 chars (~12400 tokens, measured 2026-08-03) -- a 30x increase
    delivered at the exact moment the session is compacting for lack of room.
    Reading the archive is the ticket; flooding the hook is not. Two review
    lenses flagged this independently and both were right: capping a regression
    introduced by this same change is mitigation, not new design.

    The cap keeps the NEWEST entries because compaction is about carrying the
    session forward, and it is deliberately generous -- it bounds the worst
    case without silently dropping memory in the common one.

    Note on precedence: dedup runs against L1 only. L2 is prose with no stable
    ``id``, so there is nothing to collide with.

    Before: Memory files may or may not exist.
    During: Reads the archive newest-first and caps it, then combines L3
            profile and L2 rules with a separator. Falls back to L1 raw
            observations if neither exists, applying per-ENTRY precedence (the
            live L1 copy wins on a stable-id collision, same rule as A1).
    After: Returns a markdown string with combined memory content.
    """
    # The real corpus size is captured BEFORE capping: the header must state
    # what exists, not what survived the cap. Announcing "50 lesson(s)" over a
    # corpus of 342 is a positive false claim, and it lands at the exact moment
    # the session is losing context (WOT-2026-057a).
    _full = _read_portable_archive()
    _archive_total = len(_full)
    # Cuota por origen, igual que el indice de arranque: el argumento central de
    # este ticket -- "un cap por recencia global sobre corpus unidos borra un
    # origen entero" -- aplica identico aqui. Medido en el bucle L915 antes de
    # este cambio: el compact repartia 46 motor / 4 destino.
    archived = _cap_preserving_origins(_full, _COMPACT_ARCHIVE_CAP)

    parts: list[str] = []

    profile = _try_read_file(_get_profile_file())
    if profile:
        parts.append(profile)

    rules = _try_read_file(_get_rules_file())
    if rules:
        parts.append(rules)

    if parts:
        local = "\n\n---\n\n".join(parts)
    else:
        observations = _read_observations()
        local = _format_observations_as_text(observations) if observations else ""
        if archived and observations:
            seen = {dedup_key(entry) for entry in observations}
            archived = [e for e in archived if dedup_key(e) not in seen]

    archive_text = _format_archive_as_text(archived, total_override=_archive_total)
    sections = [s for s in (archive_text, local) if s]
    return "\n\n".join(sections)


def _recallable_observations() -> list[dict[str, Any]]:
    """The pool `recall_observations` searches: live L1 + tracked archive.

    WOT-2026-047d: the twin of A1's fix, applied to the OTHER memory gate.
    `get_bootstrap_context` has read the portable archive since A1; recall did
    not, so the two doors disagreed about what memory exists. Measured on the
    real repo (2026-08-03): L1 held 427 entries of which 343 (80%) were
    `post_tool_hook` telemetry, while the tracked archive held 174 lessons and
    ZERO telemetry. They are not subsets -- recall reached none of the entries
    that actually travel between machines.

    Two filters, deliberately asymmetric:
      - Telemetry is dropped by PROVENANCE (`is_lesson`), never by label. It is
        80% of L1 and drowns the real lessons in any keyword query.
      - Precedence is per ENTRY, exactly as A1 does it: on a stable-``id``
        collision the LIVE L1 copy wins, because it may have been edited after
        being archived.

    Before: no state required; either source may be missing.
    During: reads all of L1 (limit=0) and every archive month; no writes.
    After: returns the union NEWEST-FIRST -- `_read_observations` is newest-first
        but the archive comes in file-and-line order (oldest first), so the pool
        is re-sorted by `timestamp` rather than concatenated. Never raises -- a
        corrupt archive degrades to L1 only (see `_read_portable_archive`).
    """
    live_all = _read_observations(limit=0)
    live = [obs for obs in live_all if is_lesson(obs)]
    archived = [obs for obs in _read_portable_archive() if is_lesson(obs)]

    if archived and live_all:
        # Dedup contra L1 COMPLETO, no contra `live` ya filtrado. Si una entrada
        # viva dejo de ser leccion (p.ej. se reescribio con un topic
        # autogenerado), sigue siendo la copia MAS RECIENTE de ese `id`:
        # deduplicar contra la lista filtrada la haria invisible en `seen` y el
        # archive REINTRODUCIRIA su version vieja. Es decir, la entrada
        # archivada y OBSOLETA resucitaria, que es justo lo contrario de la
        # precedencia por-entrada de A1.
        seen = {dedup_key(entry) for entry in live_all}
        archived = [e for e in archived if dedup_key(e) not in seen]

    # Orden NEWEST-FIRST sobre el pool unido. No es cosmetico: los consumidores
    # truncan con `limit` (`memory_context.py --recall` hace `[:limit]`), asi que
    # el orden decide QUE lecciones ve el agente. Concatenar `live + archived`
    # dejaba las 174 entradas del archive SIEMPRE detras de las vivas: con un
    # `--limit` pequeño volvian a ser inalcanzables -- el mismo fallo que este
    # ticket corrige, reintroducido por la puerta de atras.
    #
    # Medido el 2026-08-03: con los datos de HOY la concatenacion ya salia
    # ordenada por coincidencia (el L1 vivo filtrado queda casi vacio y domina
    # el archive). Ordenar es lo que convierte esa coincidencia en invariante.
    #
    # `timestamp` ausente ordena al final (cadena vacia), nunca reordena por
    # delante de una entrada fechada.
    return sorted(
        live + archived,
        key=lambda obs: str(obs.get("timestamp") or ""),
        reverse=True,
    )


def recall_observations(
    query: str | None = None,
    limit: int = _L1_FALLBACK_LIMIT,
) -> list[dict[str, Any]]:
    """Recall lessons from live L1 **and** the tracked portable archive.

    WOT-2026-047d: until this ticket the recall gate delegated entirely to
    `observations.jsonl` -- the gitignored buffer -- so the 174 lessons that
    travel by git were unreachable through it. See `_recallable_observations`
    for the measured numbers and the precedence rule.

    Before: Requires no state; neither source needs to exist.
    During: Builds the live+archive pool, optionally filters by keyword match
        on signal, topic or source.
    After: Returns a list of matching observation dicts (live entries first),
        or empty list. Never raises.
    """
    observations = _recallable_observations()

    if query:
        # Filter over the FULL pool, then truncate. Reading only a recent
        # window first (the pre-WOT-2026-021 behavior) made queries blind to
        # older observations even though they exist.
        query_lower = query.lower()
        filtered = []
        for obs in observations:
            signal = (obs.get("signal") or "").lower()
            topic = (obs.get("topic") or "").lower()
            source = (obs.get("source") or "").lower()
            if query_lower in signal or query_lower in topic or query_lower in source:
                filtered.append(obs)
        return filtered[:limit]

    return observations[:limit]


def get_memory_tier_status() -> dict[str, bool]:
    """Check which memory tiers are available.

    Before: Requires no state.
    During: Checks existence of each memory file.
    After: Returns dict with 'l3', 'l2', 'l1' keys indicating availability.
    """
    return {
        "l3": _get_profile_file().exists(),
        "l2": _get_rules_file().exists(),
        "l1": _get_observations_file().exists(),
    }
