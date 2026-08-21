#!/usr/bin/env python3
"""
Validador de batch_dag.json (WOT-2026-022r)

Verifica que un DAG de grupos producido por /backlog-triage (esquema
"autonomous-batch-dag/v1") sea estructuralmente valido antes de que un
ejecutor (p.ej. /orchestrate-pipeline) lo consuma.

Reglas de rechazo (exit 1):
1. Ciclo en el grafo de grupos (siguiendo depends_on_groups).
2. Inconsistencia entre depends_on_groups y blocks_groups: si G1 declara
   G2 en blocks_groups, G2 debe declarar G1 en depends_on_groups (y
   viceversa).
3. Grupo sin common_gate (falta la clave, es null, o es cadena vacia /
   solo espacios).
4. Solapamiento de shared_surfaces entre DOS GRUPOS INDEPENDIENTES (sin
   camino de dependencia entre ellos en ninguna direccion). Grupos
   conectados por un camino de dependencia (directo o transitivo) pueden
   compartir superficies: se ejecutan en serie, es seguro.
5. Basicos de esquema: "schema" == "autonomous-batch-dag/v1"; claves de
   grupo obligatorias presentes; "class" en {S, M, L}; id de grupo
   desconocido referenciado en depends_on_groups/blocks_groups; un mismo
   ticket apareciendo en dos grupos.

La regla 4 (solapamiento de superficies) es un camino de codigo
INDEPENDIENTE de las reglas 1 y 2 (ciclo / common_gate): debe poder
disparar sobre un DAG aciclico y con todos los grupos gateados (de lo
contrario la regla no tiene dientes). "Independiente" se calcula por
alcanzabilidad/ancestria en el DAG (camino transitivo), no solo por
aristas directas.

Uso:
    python scripts/validate_batch_dag.py <path-a-dag.json> [--json]

Salida:
- Exit 0: el DAG es valido.
- Exit 1: al menos un error encontrado (se listan todos, no solo el primero).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


# WOT-2026-023t: a cell that IS exactly a ticket id (fullmatch on the trimmed
# cell). Cell-based on purpose: the description cell of a backlog row cites
# OTHER ticket ids inside prose, and the word "pending" can appear inside
# prose too -- substring matching would count both (layout/cell trap measured
# in WOT-2026-024c). Prefix legacy-compat: WP-/WT- rows still resolve.
_TICKET_CELL_RE = re.compile(r"[A-Z]{2,4}-\d{4}-\d{3}[a-z]?")


REQUIRED_SCHEMA = "autonomous-batch-dag/v1"
VALID_CLASSES = {"S", "M", "L"}
REQUIRED_GROUP_KEYS = {
    "id",
    "tickets",
    "depends_on_groups",
    "blocks_groups",
    "shared_surfaces",
    "class",
    "autonomy_mode",
    "common_gate",
}


def _errors_single_group(
    group: dict[str, Any], group_ids: set[str], ticket_owner: dict[str, str]
) -> list[str]:
    """Validate one group's required keys, id, class, common_gate, tickets."""
    errors: list[str] = []
    gid = group.get("id")

    missing = REQUIRED_GROUP_KEYS - group.keys()
    if missing:
        errors.append(f"grupo '{gid}': faltan claves obligatorias: {sorted(missing)}")

    if isinstance(gid, str) and gid:
        if gid in group_ids:
            errors.append(f"id de grupo duplicado: '{gid}'")
        group_ids.add(gid)
    else:
        errors.append(f"grupo con 'id' invalido: {gid!r}")

    cls = group.get("class")
    if cls not in VALID_CLASSES:
        errors.append(
            f"grupo '{gid}': class '{cls}' invalida, debe ser uno de "
            f"{sorted(VALID_CLASSES)}"
        )

    gate = group.get("common_gate")
    if not isinstance(gate, str) or not gate.strip():
        errors.append(f"grupo '{gid}': common_gate ausente o vacio")

    for ticket in group.get("tickets") or []:
        if ticket in ticket_owner:
            errors.append(
                f"ticket '{ticket}' aparece en dos grupos: "
                f"'{ticket_owner[ticket]}' y '{gid}'"
            )
        else:
            ticket_owner[ticket] = gid

    return errors


def _errors_unknown_refs(group: dict[str, Any], group_ids: set[str]) -> list[str]:
    """Validate depends_on_groups/blocks_groups reference known group ids."""
    errors: list[str] = []
    gid = group.get("id")
    for ref_field in ("depends_on_groups", "blocks_groups"):
        errors.extend(
            f"grupo '{gid}': '{ref_field}' referencia id desconocido '{ref}'"
            for ref in (group.get(ref_field) or [])
            if ref not in group_ids
        )
    return errors


def _errors_schema_basics(data: dict[str, Any]) -> list[str]:
    """Validate top-level schema tag and per-group required keys/enums."""
    errors: list[str] = []

    schema = data.get("schema")
    if schema != REQUIRED_SCHEMA:
        errors.append(f"schema '{schema}' invalido: se esperaba '{REQUIRED_SCHEMA}'")

    groups = data.get("groups")
    if not isinstance(groups, list):
        errors.append("falta 'groups' (debe ser una lista)")
        return errors

    group_ids: set[str] = set()
    ticket_owner: dict[str, str] = {}

    for group in groups:
        if not isinstance(group, dict):
            errors.append(f"grupo invalido (no es objeto): {group!r}")
            continue
        errors.extend(_errors_single_group(group, group_ids, ticket_owner))

    for group in groups:
        if not isinstance(group, dict):
            continue
        errors.extend(_errors_unknown_refs(group, group_ids))

    return errors


def _build_depends_map(groups: list[dict[str, Any]]) -> dict[str, set[str]]:
    """Map group id -> set of group ids it depends_on (raw, unvalidated refs kept)."""
    depends: dict[str, set[str]] = {}
    for group in groups:
        if not isinstance(group, dict):
            continue
        gid = group.get("id")
        if not isinstance(gid, str):
            continue
        depends[gid] = set(group.get("depends_on_groups") or [])
    return depends


def _errors_cycle(groups: list[dict[str, Any]]) -> list[str]:
    """Detect cycles in the depends_on_groups graph via DFS coloring."""
    depends = _build_depends_map(groups)
    errors: list[str] = []

    white, gray, black = 0, 1, 2
    color: dict[str, int] = dict.fromkeys(depends, white)

    def visit(node: str, stack: list[str]) -> bool:
        color[node] = gray
        stack.append(node)
        for dep in depends.get(node, set()):
            if dep not in color:
                continue
            if color[dep] == gray:
                cycle = [*stack[stack.index(dep) :], dep]
                errors.append(
                    "ciclo detectado en depends_on_groups: " + " -> ".join(cycle)
                )
                return True
            if color[dep] == white and visit(dep, stack):
                return True
        stack.pop()
        color[node] = black
        return False

    for node in list(depends.keys()):
        if color[node] == white and visit(node, []):
            break

    return errors


def _errors_blocks_consistency(groups: list[dict[str, Any]]) -> list[str]:
    """If G1 blocks G2, then G2 must depend_on G1 (and vice versa)."""
    errors: list[str] = []
    depends = _build_depends_map(groups)

    for group in groups:
        if not isinstance(group, dict):
            continue
        gid = group.get("id")
        if not isinstance(gid, str):
            continue
        errors.extend(
            f"inconsistencia: grupo '{gid}' declara blocks_groups "
            f"'{blocked}', pero '{blocked}' no declara '{gid}' en "
            "depends_on_groups"
            for blocked in (group.get("blocks_groups") or [])
            if gid not in depends.get(blocked, set())
        )

    return errors


def _reachable(start: str, depends: dict[str, set[str]]) -> set[str]:
    """All groups reachable from start by following depends_on_groups edges."""
    seen: set[str] = set()
    stack = [start]
    while stack:
        node = stack.pop()
        for dep in depends.get(node, set()):
            if dep not in seen:
                seen.add(dep)
                stack.append(dep)
    return seen


def _normalize_surface(surface: str) -> str:
    """Canonical form of a `shared_surfaces` path, for comparison ONLY.

    WOT-2026-022w: the scan used to compare RAW strings, so two groups declared
    INDEPENDENT could name the SAME file and pass. Verified false-negatives:
        'Scripts/A.py' vs 'scripts/a.py'   (case)
        'scripts/a.py' vs 'scripts\\a.py'   (separator)
        './scripts/a.py' vs 'scripts/a.py' (redundant prefix)
    On Windows all three are one file: the two groups would run in parallel and race
    on writes -- precisely what this scan exists to prevent.

    Normalizes: separator -> '/', collapses '.' segments, case-folds.

    Case-folding ALWAYS (not only on Windows) is deliberate and conservative: the
    failure modes are asymmetric. Over-matching serializes two groups that could have
    run in parallel (a small cost in wall-clock). Under-matching lets two groups write
    the same file concurrently (a corrupted run). When the DAG is portable and the
    executing platform is unknown, pay the cheap error.
    """
    text = surface.replace("\\", "/")
    parts = [p for p in text.split("/") if p not in ("", ".")]
    return "/".join(parts).casefold()


def _errors_surface_overlap(groups: list[dict[str, Any]]) -> list[str]:
    """
    Independent code path: reject shared_surfaces overlap between two
    groups with NO dependency path connecting them in either direction
    (ancestor/descendant via depends_on_groups, transitive).
    """
    errors: list[str] = []
    depends = _build_depends_map(groups)

    valid_groups = [
        g for g in groups if isinstance(g, dict) and isinstance(g.get("id"), str)
    ]

    ancestors_or_descendants: dict[str, set[str]] = {}
    for group in valid_groups:
        gid = group["id"]
        ancestors_or_descendants[gid] = _reachable(gid, depends)

    # Add reverse direction (descendants): if A reaches B, B is connected to A too.
    for gid, reached in list(ancestors_or_descendants.items()):
        for other in reached:
            ancestors_or_descendants.setdefault(other, set()).add(gid)

    n = len(valid_groups)
    for i in range(n):
        for j in range(i + 1, n):
            g1 = valid_groups[i]
            g2 = valid_groups[j]
            id1, id2 = g1["id"], g2["id"]

            connected = id2 in ancestors_or_descendants.get(
                id1, set()
            ) or id1 in ancestors_or_descendants.get(id2, set())
            if connected:
                continue

            # WOT-2026-022w: comparar por la ruta NORMALIZADA, no por la cadena cruda.
            # Se conserva la ruta ORIGINAL para el mensaje (el usuario debe ver lo que
            # escribio, no una forma canonica que no reconoce).
            norm1 = {_normalize_surface(s): s for s in g1.get("shared_surfaces") or []}
            norm2 = {_normalize_surface(s): s for s in g2.get("shared_surfaces") or []}
            overlap = set(norm1) & set(norm2)
            if overlap:
                shown = sorted(
                    {norm1[k] for k in overlap} | {norm2[k] for k in overlap}
                )
                errors.append(
                    f"solapamiento de shared_surfaces entre grupos "
                    f"independientes '{id1}' y '{id2}': {shown}"
                )

    return errors


def _pending_tickets_in_backlog(text: str) -> set[str]:
    """Ticket ids that appear in a LIVE `pending` row of the backlog.

    Before: text is the raw markdown of the live backlog queue.
    During: scans table rows only (lines starting with '|'); a ticket counts
            as pending iff the SAME row has one cell that IS the ticket id
            (fullmatch, trimmed) and another cell exactly equal to 'pending'.
            Cell-based, never substring: prose cells cite other ticket ids and
            may contain the word 'pending' (trap measured in WOT-2026-024c).
    After: returns the set of pending ticket ids; no I/O, no mutation.
    """
    pending: set[str] = set()
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")]
        if "pending" not in cells:
            continue
        pending.update(c for c in cells if _TICKET_CELL_RE.fullmatch(c))
    return pending


def _errors_live_backlog(data: dict[str, Any], backlog_text: str) -> list[str]:
    """WOT-2026-023t: freshness is SEMANTIC, not `motor == HEAD`.

    A schema-valid DAG can be DEAD: the inaugural run consumed a DAG whose
    recommended_start ticket was already closed and archived, and only a human
    caught it. The correct gate, run when the batch STARTS: every ticket of
    `groups` must still be a `pending` row in the live backlog queue. A DAG
    citing a ticket that is archived/completed/absent is a dead DAG -> the
    executor returns it to the triage (re-triage), never patches around it.
    (`state_at_triage.motor != HEAD` is deliberately NOT an error: the motor
    HEAD advances with every close of the batch itself, so an equality gate
    would self-block after the first ticket; it is only a WARN via --head-sha.)
    """
    errors: list[str] = []
    groups = data.get("groups")
    if not isinstance(groups, list):
        return errors
    pending = _pending_tickets_in_backlog(backlog_text)
    for group in groups:
        if not isinstance(group, dict):
            continue
        group_id = group.get("id", "<sin id>")
        tickets = group.get("tickets")
        if not isinstance(tickets, list):
            continue
        errors.extend(
            f"frescura (WOT-2026-023t): el ticket '{ticket}' del grupo "
            f"'{group_id}' no esta 'pending' en la cola viva del backlog -- "
            f"DAG muerto, devolver al triage (re-triage), no ejecutarlo"
            for ticket in tickets
            if isinstance(ticket, str) and ticket not in pending
        )
    return errors


# ---------------------------------------------------------------------------
# WOT-2026-046h: condition 3 (`contabilidad_completa`) had NO teeth.
# `prompts/orchestrator_autonomous_ticket_batch.md:741` fixes the accounting
# universe as the tickets listed in `groups[]` (WOT-2026-025q), and requires
# that a `tickets[]` entry belonging to NO group be ENUMERATED as excluded,
# "never silently omitted". The validator checked NEITHER half: measured on
# the real DAG `backlog_triage_20260820-024142.json`, `WOT-2026-055h` sits in
# a group while being ABSENT from `tickets[]` entirely -- untriaged, with no
# `classification` and no `evidence_label` -- and the validator returned
# `exit 0`. The barrier existed and did not bite where the failure happens.
# ---------------------------------------------------------------------------

# Keys whose entries enumerate a ticket as DELIBERATELY excluded from the
# accounting universe. The contract says "in the DAG or in the batch_run
# accounting note"; this CLI only sees the DAG, so it accepts any of these.
_EXCLUSION_KEYS = (
    "requires_human",
    "premise_verify",
    "excluded",
    "excluded_tickets",
    # Measured on a REAL closed-flight DAG (backlog_triage_output_044_CERRADO):
    # the enumeration of deliberate exclusions lives under this name. Omitting
    # it made this check report 3 false positives on a historically correct DAG.
    "excluded_from_flight",
)


def _ticket_ids(entries: Any) -> set[str]:
    """Ticket ids from a list whose items are either bare strings or objects.

    `tickets[]` carries objects (`{"id": ..., "classification": ...}`) while
    `groups[].tickets` carries bare id strings; the exclusion lists use both
    shapes across real DAGs. Accepting both is deliberate, not laxity: this
    helper answers "which ids are named here", nothing else.

    Before: `entries` is whatever the JSON held (may be any type).
    During: pure; no I/O, no mutation.
    After: returns the set of ids found. Never raises on malformed input.
    """
    ids: set[str] = set()
    if not isinstance(entries, list):
        return ids
    for entry in entries:
        if isinstance(entry, str):
            ids.add(entry)
        elif isinstance(entry, dict) and isinstance(entry.get("id"), str):
            ids.add(entry["id"])
    return ids


def _errors_accounting(data: dict[str, Any]) -> list[str]:
    """WOT-2026-046h: enforce condition 3 (`contabilidad_completa`).

    Two failures, deliberately kept DISTINCT because they mean opposite things:

    (a) A ticket scheduled in `groups[]` but ABSENT from `tickets[]`: it is in
        the accounting universe yet was never triaged, so it carries no
        classification and no evidence. This is the defect measured on the real
        DAG and it is the more dangerous of the two -- the executor would fly a
        ticket the triage never assessed.
    (b) A `tickets[]` entry in NO group and NOT enumerated as excluded: the F3
        ambiguity the contract names verbatim ("never silently omitted").

    A DAG with no root `tickets[]` key at all is NOT an error: this CLI also
    validates generic/handwritten DAGs that carry only `groups[]`, and the
    accounting universe is well defined without the triage roster.

    Before: `data` is the parsed DAG root object.
    During: pure set arithmetic; no I/O, no mutation of `data`.
    After: returns a list of error strings (empty == accounting is complete).
    """
    errors: list[str] = []
    if "tickets" not in data:
        return errors

    rostered = _ticket_ids(data.get("tickets"))
    # Not every DAG's `tickets[]` is a full triage ROSTER. Measured on a real
    # closed flight (backlog_triage_output_044_CERRADO.json): there `tickets[]`
    # enumerates ONLY the excluded entries (`{id, note}`), while the flown
    # tickets live solely in `groups[]`. Reading that as "untriaged" produced 4
    # false positives on a DAG that was correct for its own schema variant.
    # The discriminator is SHAPE, not count: a roster labels its entries
    # (`classification` / `evidence_label`); an exclusion list only annotates.
    is_roster = any(
        isinstance(e, dict) and ("classification" in e or "evidence_label" in e)
        for e in (data.get("tickets") or [])
    )
    grouped: set[str] = set()
    groups = data.get("groups")
    if isinstance(groups, list):
        for group in groups:
            if isinstance(group, dict):
                grouped.update(
                    tk for tk in (group.get("tickets") or []) if isinstance(tk, str)
                )

    if is_roster:
        errors.extend(
            f"contabilidad (WOT-2026-046h): el ticket '{ticket}' esta en un grupo "
            f"pero NO figura en 'tickets[]': entra en el universo de contabilidad "
            f"sin haber pasado por el triaje (sin classification ni evidence_label)"
            for ticket in sorted(grouped - rostered)
        )

    if is_roster:
        excluded: set[str] = set()
        for key in _EXCLUSION_KEYS:
            excluded |= _ticket_ids(data.get(key))

        # An entry that ANNOTATES itself (`note`) is a self-evident exclusion:
        # the contract asks for the exclusion to be enumerated with a reason,
        # and the note IS the reason. Refuted by the adversarial loop (L700,
        # BA11) and reproduced: a MIXED `tickets[]` -- mostly `{id, note}`
        # exclusions plus a single labelled entry -- flipped `is_roster` on and
        # then flagged those annotated exclusions as silent omissions. Reading
        # the shape PER ENTRY instead of per LIST removes that false positive
        # without weakening the check: an entry with neither a group, a note,
        # nor an enumeration is still an error.
        excluded |= {
            e["id"]
            for e in (data.get("tickets") or [])
            if isinstance(e, dict)
            and isinstance(e.get("id"), str)
            and str(e.get("note") or "").strip()
        }

        errors.extend(
            f"contabilidad (WOT-2026-046h): el ticket '{ticket}' de 'tickets[]' no "
            f"pertenece a ningun grupo y NO esta enumerado como excluido en "
            f"{list(_EXCLUSION_KEYS)}: omision silenciosa (condicion 3, F3)"
            for ticket in sorted((rostered - grouped) - excluded)
        )

    return errors


# WOT-2026-046h (F-4, same surface, fused per the ticket): a DAG could stamp
# `evidence_label: VERIFICADO` with no probe and pass `exit 0` (measured H-7 in
# the same session). This CLI cannot verify a probe ran -- that is not knowable
# from the JSON -- so it enforces the part that IS checkable: the label must be
# PRESENT and one of the contract's values. An absent label is the silent case.
_VALID_EVIDENCE_LABELS = {"VERIFICADO", "INFERIDO", "NO_VERIFICADO"}


def _errors_evidence_label(data: dict[str, Any]) -> list[str]:
    """WOT-2026-046h (F-4): every ROSTERED ticket declares a valid evidence_label.

    Scoped to entries of `tickets[]` that are objects: a DAG whose roster is a
    plain list of id strings predates the labelled schema and is left alone
    (backward compatible on purpose -- this check adds teeth, it does not
    retroactively invalidate older artifacts).

    Before: `data` is the parsed DAG root object.
    During: pure; no I/O.
    After: returns error strings for missing/invalid labels.
    """
    errors: list[str] = []
    entries = data.get("tickets")
    if not isinstance(entries, list):
        return errors
    # Same shape guard as _errors_accounting: in the exclusion-list variant the
    # entries are `{id, note}` and never promised a label. Demanding one there
    # would flag a historically correct DAG (measured: 4 false positives).
    if not any(
        isinstance(e, dict) and ("classification" in e or "evidence_label" in e)
        for e in entries
    ):
        return errors
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        # Same per-entry rule as the accounting check: an annotated exclusion
        # is not a roster row and never promised an evidence label.
        if str(entry.get("note") or "").strip():
            continue
        ticket = entry.get("id", "<sin id>")
        if "evidence_label" not in entry:
            errors.append(
                f"evidencia (WOT-2026-046h): el ticket '{ticket}' de 'tickets[]' "
                f"no declara 'evidence_label' (VERIFICADO/INFERIDO sin marcar)"
            )
            continue
        label = entry.get("evidence_label")
        if label not in _VALID_EVIDENCE_LABELS:
            errors.append(
                f"evidencia (WOT-2026-046h): el ticket '{ticket}' declara "
                f"evidence_label {label!r} invalido, debe ser uno de "
                f"{sorted(_VALID_EVIDENCE_LABELS)}"
            )
    return errors


def validate_dag(data: dict[str, Any]) -> list[str]:
    """Run all validation rules and return the combined list of errors."""
    errors: list[str] = []
    errors.extend(_errors_schema_basics(data))

    groups = data.get("groups")
    if not isinstance(groups, list):
        return errors

    errors.extend(_errors_cycle(groups))
    errors.extend(_errors_blocks_consistency(groups))
    errors.extend(_errors_surface_overlap(groups))
    errors.extend(_errors_accounting(data))
    errors.extend(_errors_evidence_label(data))

    return errors


def _backlog_text_as_of(
    live_backlog: Path, as_of: str
) -> tuple[str | None, str | None]:
    """Read the backlog as it stood at commit `as_of`. Returns (text, error).

    WOT-2026-055r: `--live-backlog` run AFTER a flight gives a FALSE RED -- the
    tickets it closed have migrated to the archive, so the gate reports "DAG
    muerto" about a DAG that was perfectly fresh when it was consumed. The only
    workaround was reconstructing the state by hand
    (`git show <sha>:backlog.md`), which no auditor does unless they know.

    Resolution is done in the repo that CONTAINS the backlog (the destino), not
    the motor: the backlog is destino state and `as_of` is a destino sha.

    Before: `live_backlog` exists; `as_of` is a non-empty revision string.
    During: one read-only `git show <as_of>:<relpath>` subprocess.
    After: returns (text, None) on success or (None, error) on failure. The
           error is fail-CLOSED on purpose: an unresolvable `--as-of` must not
           silently degrade into the live read it was meant to replace.
    """
    repo_dir = live_backlog.parent
    try:
        top = subprocess.run(  # noqa: S603
            ["git", "-C", str(repo_dir), "rev-parse", "--show-toplevel"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=10,
        )
        if top.returncode != 0:
            return None, (
                f"frescura (WOT-2026-055r): --as-of={as_of} pero {repo_dir} no "
                f"esta en un repo git: no se puede reconstruir el backlog"
            )
        rel = live_backlog.resolve().relative_to(Path(top.stdout.strip()).resolve())
        shown = subprocess.run(  # noqa: S603
            ["git", "-C", str(repo_dir), "show", f"{as_of}:{rel.as_posix()}"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        return None, (
            f"frescura (WOT-2026-055r): no se pudo reconstruir el backlog en "
            f"--as-of={as_of}: {e}"
        )
    if shown.returncode != 0:
        return None, (
            f"frescura (WOT-2026-055r): --as-of={as_of} no resuelve, o el "
            f"backlog no existia en ese commit: {shown.stderr.strip()}"
        )
    return shown.stdout, None


def _freshness_errors(
    live_backlog: Path | None, data: dict[str, Any], as_of: str | None = None
) -> list[str]:
    """Resolve --live-backlog into freshness errors (fail-closed on I/O).

    With `as_of` (WOT-2026-055r) the queue is reconstructed at that commit, so a
    CLOSED flight can be re-validated for the freshness it had when consumed.
    Without it the check reads the LIVE queue and is therefore PRE-EXECUTION
    only -- stated in the output rather than left as folklore.
    """
    if live_backlog is None:
        return []
    if not live_backlog.exists():
        return [f"frescura (WOT-2026-023t): backlog vivo no existe: {live_backlog}"]
    if as_of:
        backlog_text, error = _backlog_text_as_of(live_backlog, as_of)
        if error:
            return [error]
        return _errors_live_backlog(data, backlog_text or "")
    try:
        backlog_text = live_backlog.read_text(encoding="utf-8")
    except OSError as e:
        return [f"frescura (WOT-2026-023t): no se pudo leer el backlog vivo: {e}"]
    return _errors_live_backlog(data, backlog_text)


def _sha_resolves_in_motor(head_sha: str, motor_root: Path) -> bool | None:
    """True/False if `head_sha` names a commit of the MOTOR repo; None if unknown.

    WOT-2026-051f: `--head-sha` used to compare CADENAS and nothing else, so a
    sha that exists in NO repo (`deadbeef...`) produced `rc=0` plus the ordinary
    staleness WARN -- indistinguishable from a genuinely stale motor.

    Returns None (not False) when the question cannot be answered: git missing,
    `motor_root` not a repo, git erroring for any reason other than "no such
    object". Unknown is NOT "invalid": this CLI must stay usable off-repo, and
    turning an unanswerable question into a warning would cry wolf.

    Before: `head_sha` is a non-empty string; `motor_root` a candidate repo dir.
    During: one read-only `git cat-file -e <sha>^{commit}` subprocess, no writes.
    After: returns bool | None. Never raises.
    """
    try:
        inside = subprocess.run(  # noqa: S603
            ["git", "-C", str(motor_root), "rev-parse", "--is-inside-work-tree"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=10,
        )
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return None
        probe = subprocess.run(  # noqa: S603
            [  # noqa: S607
                "git",
                "-C",
                str(motor_root),
                "cat-file",
                "-e",
                f"{head_sha}^{{commit}}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return probe.returncode == 0


def _head_sha_warnings(
    head_sha: str | None, data: dict[str, Any], motor_root: Path | None = None
) -> list[str]:
    """--head-sha vs state_at_triage.motor: WARN on mismatch, never an error
    (the motor HEAD advances with every close of the batch itself). Prefix
    tolerant so short and long SHAs compare equal.

    WOT-2026-051f: the sha is FIRST resolved against the motor repo. A sha that
    does not resolve gets its OWN warning and SHORT-CIRCUITS -- the staleness
    WARN is deliberately NOT also emitted, because the whole defect was that the
    two cases produced the same message and could not be told apart. Resolution
    failure means "you passed a sha of another repo, or a typo"; staleness means
    "the motor really moved". NON-GOAL (declared in the ticket): the staleness
    semantics are unchanged, and nothing here becomes blocking.
    """
    if not head_sha:
        return []

    root = (
        motor_root if motor_root is not None else Path(__file__).resolve().parent.parent
    )
    resolves = _sha_resolves_in_motor(head_sha, root)
    if resolves is False:
        return [
            f"--head-sha={head_sha} NO resuelve a ningun commit del motor "
            f"({root}): sha de otro repo, truncado o inexistente. El WARN de "
            "staleness NO se emite porque no hay nada con que compararlo "
            "(WARN, no bloquea; WOT-2026-051f)"
        ]

    state = data.get("state_at_triage")
    triage_motor = str(state.get("motor", "")) if isinstance(state, dict) else ""
    if triage_motor and not (
        head_sha.startswith(triage_motor) or triage_motor.startswith(head_sha)
    ):
        return [
            f"state_at_triage.motor={triage_motor} != HEAD={head_sha}: re-verificar "
            "premisas antes de ejecutar (WARN, no bloquea: el HEAD avanza con "
            "cada cierre del propio batch, WOT-2026-023t)"
        ]
    return []


_TRIAGE_NAME_RE = re.compile(r"^backlog_triage_\d{8}-\d{4,6}\.json$")


def _is_triage_artifact_name(name: str) -> bool:
    """True only for a canonical triage artifact: ``backlog_triage_<ts>.json``.

    WOT-2026-051a (d), DECIDED in the ticket, not by the implementer: a JSON
    whose suffix is not a timestamp is IGNORED by the pair check rather than
    rejected. This CLI validates GENERIC DAGs, so demanding an ``.md`` sibling
    from every file merely *starting* with ``backlog_triage_`` would break
    legitimate consumers -- and would resurrect the legacy
    ``backlog_triage_output.json`` name that 049a retired from the contract.

    The second group accepts 4-6 digits because the destination's own history
    holds both widths (``20260711-0239`` alongside ``20260808-010534``).

    Before: `name` is a bare filename, never a path.
    During: pure regex match; no I/O.
    After: returns a bool. Never raises.
    """
    return bool(_TRIAGE_NAME_RE.match(name))


def _pair_completeness_errors(dag_path: Path) -> list[str]:
    """Check that the DAG JSON has a corresponding .md narrative file.

    WOT-2026-049a: the triage produces a pair (JSON + .md). An incomplete pair
    (JSON without .md) indicates an interrupted triage run. This check is
    PROSA-LEVEL: it verifies file existence, not runtime behavior.
    """
    errors: list[str] = []
    if not _is_triage_artifact_name(dag_path.name):
        return errors
    md_path = dag_path.with_suffix(".md")
    if not md_path.exists():
        errors.append(
            f"par incompleto: {dag_path.name} existe pero {md_path.name} no "
            f"(corrida de triaje interrumpida o par corrupto)"
        )
        return errors
    # WOT-2026-051a (e): existence is not completeness. A run that creates the
    # narrative and dies before writing it leaves an EMPTY .md -- exactly the
    # interrupted-run failure this check exists to catch.
    try:
        if not md_path.read_text(encoding="utf-8-sig").strip():
            errors.append(
                f"par incompleto: {md_path.name} existe pero esta vacio "
                f"(corrida de triaje interrumpida o par corrupto)"
            )
    except OSError as e:
        errors.append(f"par incompleto: no se pudo leer {md_path.name}: {e}")
    return errors


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Validar un batch_dag.json contra el esquema autonomous-batch-dag/v1"
    )
    parser.add_argument("dag_path", type=Path, help="Ruta al archivo dag.json")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emitir el resultado en formato JSON (machine-readable)",
    )
    parser.add_argument(
        "--live-backlog",
        type=Path,
        default=None,
        help=(
            "Ruta al backlog.md VIVO del destino. Activa el gate de frescura "
            "WOT-2026-023t: todo ticket de groups debe seguir 'pending' en la "
            "cola viva; un DAG valido-pero-MUERTO falla en vez de pasar."
        ),
    )
    parser.add_argument(
        "--as-of",
        default=None,
        help=(
            "Commit del DESTINO contra el que reconstruir el backlog para el "
            "gate de frescura (WOT-2026-055r). Sin este flag, --live-backlog "
            "lee la cola VIVA y por tanto solo es valido PRE-ejecucion: tras un "
            "vuelo, los tickets cerrados ya migraron al archive y darian un "
            "FALSO ROJO. Usar el sha del triaje para re-validar un vuelo cerrado."
        ),
    )
    parser.add_argument(
        "--head-sha",
        default=None,
        help=(
            "SHA actual del motor. Si difiere de state_at_triage.motor emite "
            "WARN (re-verificar premisas), NUNCA bloquea: el HEAD avanza con "
            "cada cierre del propio batch (WOT-2026-023t)."
        ),
    )

    args = parser.parse_args(argv)

    if not args.dag_path.exists():
        message = f"archivo no existe: {args.dag_path}"
        if args.json:
            print(json.dumps({"valid": False, "errors": [message]}))
        else:
            print(f"ERROR: {message}", file=sys.stderr)
        return 1

    try:
        # WOT-2026-051a: utf-8-sig, not utf-8. A BOM made `json.loads` abort
        # with "Unexpected UTF-8 BOM" BEFORE validate_dag() and before the
        # 049a pair check -- so a single stray BOM disabled every validation
        # this CLI performs. utf-8-sig is a strict superset: it reads files
        # with and without a BOM, so no bomless input changes behavior.
        content = args.dag_path.read_text(encoding="utf-8-sig")
        data = json.loads(content)
    except (OSError, json.JSONDecodeError) as e:
        message = f"no se pudo leer/parsear el archivo: {e}"
        if args.json:
            print(json.dumps({"valid": False, "errors": [message]}))
        else:
            print(f"ERROR: {message}", file=sys.stderr)
        return 1

    if not isinstance(data, dict):
        message = "el contenido raiz debe ser un objeto JSON"
        if args.json:
            print(json.dumps({"valid": False, "errors": [message]}))
        else:
            print(f"ERROR: {message}", file=sys.stderr)
        return 1

    errors = validate_dag(data)
    errors.extend(_freshness_errors(args.live_backlog, data, args.as_of))
    errors.extend(_pair_completeness_errors(args.dag_path))
    warnings = _head_sha_warnings(args.head_sha, data)
    # WOT-2026-055r (b): make the scope of the check explicit in its own output.
    # Without --as-of the queue read is the LIVE one, so a green here means
    # "fresh NOW", never "was fresh when this DAG was consumed".
    if args.live_backlog is not None and not args.as_of:
        warnings.append(
            "frescura evaluada contra la cola VIVA: valido PRE-ejecucion. Para "
            "re-validar un vuelo YA CERRADO usa --as-of <sha-del-triaje>, o los "
            "tickets cerrados daran un falso rojo (WOT-2026-055r)"
        )
    return _emit_result(args.json, args.dag_path, errors, warnings)


def _emit_result(
    json_mode: bool, dag_path: Path, errors: list[str], warnings: list[str]
) -> int:
    """Print the verdict (JSON or human) and return the exit code."""
    if json_mode:
        print(
            json.dumps(
                {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}
            )
        )
        return 0 if not errors else 1

    for warning in warnings:
        print(f"WARN: {warning}", file=sys.stderr)

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(
            f"\nValidacion FALLIDA: {len(errors)} error(es) encontrado(s)",
            file=sys.stderr,
        )
        return 1

    print(f"Validacion EXITOSA: {dag_path} es valido")
    return 0


if __name__ == "__main__":
    sys.exit(main())
