#!/usr/bin/env python3
"""Monotonicity/integrity guard for the append-only bus and .agent/collaboration/.

WOT-2026-074x. Origin (measured 2026-09-17, destino Crear_Texto_LLM): the event
bus went from 75 lines to 0 (nothing archived) and ``--validate`` returned the
SAME rc=0/errors=0/warnings=1 -- losing the whole bus was indistinguishable
from a healthy state. Same class: the operational state .agent/collaboration/
(backlog_done.md with 205 entries, historic execution_logs, closeouts) can
disappear -- e.g. ``git revert`` of a commit that ADDED tracked-then-ignored
files -- with no guard noticing.

This guard persists a small ANCHOR of counters and FAILS on shrinkage or
disappearance that is not DECLARED. The trade-off is declared in the ticket
itself: the anchor is persisted state that can itself desynchronize; and an
anchor wiped together with the runtime dir loses the witness (an absent anchor
in an otherwise healthy workspace is indistinguishable from a fresh checkout
and only produces a new baseline -- declared limit, never hidden).

Surfaces and rules
------------------
(A) Event bus union = ``<root>/.agent/runtime/events/events.jsonl`` (live) +
    ``<root>/.agent/runtime/events/archive/**/*.jsonl`` (rotated).
    - ``union_lines`` must never decrease (truncation / total loss).
    - ``live_lines`` must never drop below its persisted high-water mark
      without a declaration: legitimate rotations
      (``EventBus.archive_ticket_events``, driven operationally by
      ``scripts/archive_event_bus.py``) move events live->archive preserving
      the union and MUST declare the drop via ``--update --reason``.
(B) Collaboration census = recursive file census of
    ``<root>/.agent/collaboration/`` with DECLARED exclusions whose shrink is
    legitimate by design (each one avoids a measured false positive):
    - ``archive/**`` .............. rotation snapshots + ``prune_runtime_retention``
      keeps 10/20 notification archives (deletes old ones).
    - ``session_bus/locks/**`` .... cohort lock churn (created/removed per round).
    - ``.session_state.json`` ..... ephemeral per-session state (gitignored).
    - ``loop_execution_targets.txt`` ... removable by design (WOT-2026-060k path).
    Rules: the census ``file_count`` must never decrease; live surfaces present
    at anchor time (STATE.md, TURN.md, execution_log.md, backlog.md,
    notifications.md, review_queue.md) must remain present; and
    ``_archive/backlog_done.md`` must not lose lines (Deletion of rows is not a
    rotation).

Anchor: ``<root>/.agent/runtime/state_integrity.json`` (UTF-8, no BOM, atomic
write). ``--check`` updates the anchor upward on growth and PASSES; any
decrease produces a finding (exit 1) unless a matching declaration was
recorded with ``--update --reason "<why>"``.

Docstring-as-spec:
    Before: ``project_root`` resolves to a workspace with (or without) a bus
        and a collaboration dir; it may or may not carry an anchor yet.
    During: censuses bus + collaboration (read-only on the guarded surfaces);
        compares against the anchor; in ``--update`` mode records a
        declaration and rewrites the anchor; in ``--check`` mode updates the
        anchor upward on non-shrink and NEVER heals a shrink.
    After: returns a report dict (``pass|baseline|fail|skip``) with findings;
        CLI exits 0 (pass/baseline/skip), 1 (fail), 2 (usage). The only file
        this module writes is the anchor itself.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = 1
ANCHOR_REL = Path(".agent") / "runtime" / "state_integrity.json"
EVENTS_REL = Path(".agent") / "runtime" / "events"
LIVE_BUS_NAME = "events.jsonl"
ARCHIVE_DIR_NAME = "archive"
COLLAB_REL = Path(".agent") / "collaboration"
BACKLOG_DONE_REL = Path("_archive") / "backlog_done.md"

LIVE_SURFACES = (
    "STATE.md",
    "TURN.md",
    "execution_log.md",
    "backlog.md",
    "notifications.md",
    "review_queue.md",
)

EXCLUDED_TOP_DIRS = ("archive",)
EXCLUDED_TOP_FILES = (".session_state.json", "loop_execution_targets.txt")
EXCLUDED_SESSION_BUS_SUBDIR = "locks"
MAX_DECLARATIONS = 20


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _count_lines(path: Path) -> int:
    """Before: ``path`` is an existing file. During: reads bytes once.
    After: number of lines (an unterminated last line counts as one)."""
    data = path.read_bytes()
    if not data:
        return 0
    count = data.count(b"\n")
    if not data.endswith(b"\n"):
        count += 1
    return count


def _is_excluded(rel: Path) -> bool:
    """Before: ``rel`` is a path relative to the collaboration dir.
    During: applies the declared exclusions (docstring, section B).
    After: True when the path is outside the census universe."""
    parts = rel.parts
    if not parts:
        return False
    if parts[0] in EXCLUDED_TOP_DIRS:
        return True
    if (
        len(parts) >= 2
        and parts[0] == "session_bus"
        and parts[1] == EXCLUDED_SESSION_BUS_SUBDIR
    ):
        return True
    return len(parts) == 1 and parts[0] in EXCLUDED_TOP_FILES


def bus_census(root: Path) -> dict:
    """Before: ``root`` is the project root directory (may lack a bus).
    During: counts live lines and the archive lines/files of the bus.
        Read-only; unreadable archive files count as zero lines rather than
        aborting the census.
    After: dict with ``present``, ``live_present``, ``live_lines``,
        ``archive_files``, ``archive_lines`` and ``union_lines``."""
    events_dir = root / EVENTS_REL
    live = events_dir / LIVE_BUS_NAME
    archive_dir = events_dir / ARCHIVE_DIR_NAME
    live_present = live.is_file()
    live_lines = _count_lines(live) if live_present else 0
    archive_files = 0
    archive_lines = 0
    if archive_dir.is_dir():
        for candidate in sorted(archive_dir.rglob("*.jsonl")):
            if not candidate.is_file():
                continue
            try:
                archive_lines += _count_lines(candidate)
            except OSError:
                continue
            archive_files += 1
    present = live_present or archive_files > 0
    return {
        "present": present,
        "live_present": live_present,
        "live_lines": live_lines,
        "archive_files": archive_files,
        "archive_lines": archive_lines,
        "union_lines": live_lines + archive_lines,
    }


def collab_census(root: Path) -> dict:
    """Before: ``root`` is the project root directory (may lack collaboration).
    During: recursive census of ``.agent/collaboration/`` minus the declared
        exclusions; records live-surface presence and backlog_done lines.
        Read-only.
    After: dict with ``present``, ``file_count``, sorted ``names``,
        ``surfaces`` (live surfaces -> bool) and ``backlog_done_lines``
        (int or None when the file is absent)."""
    collab = root / COLLAB_REL
    surfaces = {name: False for name in LIVE_SURFACES}
    if not collab.is_dir():
        return {
            "present": False,
            "file_count": 0,
            "names": [],
            "surfaces": surfaces,
            "backlog_done_lines": None,
        }
    names: list[str] = []
    for candidate in collab.rglob("*"):
        if not candidate.is_file():
            continue
        rel = candidate.relative_to(collab)
        if _is_excluded(rel):
            continue
        names.append(rel.as_posix())
    names.sort()
    for name in LIVE_SURFACES:
        surfaces[name] = (collab / name).is_file()
    backlog_done = collab / BACKLOG_DONE_REL
    backlog_done_lines = _count_lines(backlog_done) if backlog_done.is_file() else None
    return {
        "present": True,
        "file_count": len(names),
        "names": names,
        "surfaces": surfaces,
        "backlog_done_lines": backlog_done_lines,
    }


def _anchor_path(root: Path) -> Path:
    return root / ANCHOR_REL


def _load_anchor(path: Path) -> tuple[dict | None, str]:
    """Before: ``path`` may or may not exist. During: reads and validates the
    anchor schema. After: (payload, "ok") or (None, reason) where reason is
    ``no_anchor``, ``unreadable_anchor`` or ``unsupported_anchor``. A broken
    anchor degrades to a NEW baseline with an explicit finding -- it never
    fabricates a shrink."""
    if not path.is_file():
        return None, "no_anchor"
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None, "unreadable_anchor"
    if not isinstance(payload, dict):
        return None, "unsupported_anchor"
    if payload.get("schema_version") != SCHEMA_VERSION:
        return None, "unsupported_anchor"
    return payload, "ok"


def _write_anchor(path: Path, payload: dict) -> None:
    """Before: ``payload`` is a serializable anchor. During: atomic write
    (temp + os.replace), UTF-8 without BOM. After: the anchor file holds
    exactly the new payload."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def _build_anchor(root: Path, current: dict, declarations: list[dict]) -> dict:
    bus = current["bus"]
    collab = current["collab"]
    return {
        "schema_version": SCHEMA_VERSION,
        "root": str(root.resolve()),
        "updated_at": _iso_now(),
        "bus": {
            "present": bus["present"],
            "live_lines": bus["live_lines"],
            "live_hwm": bus["live_lines"],
            "union_lines": bus["union_lines"],
            "union_hwm": bus["union_lines"],
            "archive_files": bus["archive_files"],
        },
        "collab": {
            "present": collab["present"],
            "file_count": collab["file_count"],
            "names": collab["names"],
            "surfaces": collab["surfaces"],
            "backlog_done_lines": collab["backlog_done_lines"],
        },
        "declarations": declarations[-MAX_DECLARATIONS:],
    }


def _bump_anchor(anchor: dict, current: dict) -> dict:
    """Before: ``anchor`` passed evaluation (no findings). During: raises the
    persisted high-water marks to the observed values; other fields are
    refreshed. After: a new anchor payload (the declaration history is kept)."""
    updated = json.loads(json.dumps(anchor))
    bus = current["bus"]
    collab = current["collab"]
    dbus = updated.setdefault("bus", {})
    dbus["present"] = bus["present"]
    dbus["live_lines"] = bus["live_lines"]
    dbus["live_hwm"] = max(int(dbus.get("live_hwm", 0)), bus["live_lines"])
    dbus["union_lines"] = bus["union_lines"]
    dbus["union_hwm"] = max(int(dbus.get("union_hwm", 0)), bus["union_lines"])
    dbus["archive_files"] = bus["archive_files"]
    dcollab = updated.setdefault("collab", {})
    dcollab["present"] = collab["present"]
    dcollab["file_count"] = collab["file_count"]
    dcollab["names"] = collab["names"]
    dcollab["surfaces"] = collab["surfaces"]
    dcollab["backlog_done_lines"] = collab["backlog_done_lines"]
    updated["updated_at"] = _iso_now()
    return updated


def _evaluate_bus(anchor_bus: dict, bus: dict) -> list[str]:
    """Bus rules: union never decreases; live never drops below its high-water
    mark (rotations must declare); disappearance is a shrink."""
    findings: list[str] = []
    if not anchor_bus.get("present"):
        return findings
    union_hwm = int(anchor_bus.get("union_hwm", anchor_bus.get("union_lines", 0)))
    live_hwm = int(anchor_bus.get("live_hwm", anchor_bus.get("live_lines", 0)))
    if not bus["present"] and (union_hwm > 0 or live_hwm > 0):
        findings.append(
            f"SHRINK bus: bus desaparecido (anchor union={union_hwm}, live={live_hwm})"
        )
        return findings
    if bus["union_lines"] < union_hwm:
        findings.append(
            "SHRINK bus: union bajo "
            f"{union_hwm} -> {bus['union_lines']} "
            f"(pierde {union_hwm - bus['union_lines']} lineas)"
        )
    if bus["live_lines"] < live_hwm:
        findings.append(
            "SHRINK bus: live bajo su high-water "
            f"{live_hwm} -> {bus['live_lines']} "
            "(rotacion sin declarar? usa --update --reason)"
        )
    return findings


def _evaluate_collab(anchor_collab: dict, collab: dict) -> list[str]:
    """Collaboration rules: census count, required live surfaces and
    backlog_done lines never decrease; disappearance is a shrink."""
    findings: list[str] = []
    if not anchor_collab.get("present"):
        return findings
    if not collab["present"]:
        findings.append(
            "DISAPPEAR collab: .agent/collaboration/ desaparecido "
            f"(anchor file_count={anchor_collab.get('file_count')})"
        )
        return findings
    removed = sorted(set(anchor_collab.get("names") or []) - set(collab["names"]))
    if collab["file_count"] < int(anchor_collab.get("file_count", 0)):
        detail = ", ".join(removed[:8])
        if len(removed) > 8:
            detail += f" ... (+{len(removed) - 8} mas)"
        findings.append(
            "SHRINK collab: file_count "
            f"{anchor_collab.get('file_count')} -> {collab['file_count']}; "
            f"elimina: {detail}"
        )
    for name, was_present in (anchor_collab.get("surfaces") or {}).items():
        if was_present and not collab["surfaces"].get(name):
            findings.append(f"DISAPPEAR collab: superficie viva ausente: {name}")
    anchor_backlog_done = anchor_collab.get("backlog_done_lines")
    if anchor_backlog_done is not None:
        if collab["backlog_done_lines"] is None:
            findings.append(
                "DISAPPEAR collab: _archive/backlog_done.md ausente "
                f"(anchor {anchor_backlog_done} lineas)"
            )
        elif collab["backlog_done_lines"] < int(anchor_backlog_done):
            findings.append(
                "SHRINK collab: backlog_done.md "
                f"{anchor_backlog_done} -> {collab['backlog_done_lines']} lineas"
            )
    return findings


def evaluate(root: Path, anchor: dict | None) -> tuple[str, list[str], dict]:
    """Before: ``root`` exists; ``anchor`` is a loaded anchor or None.
    During: censuses both surfaces and compares against the anchor (pure
        reads; no writes).
    After: (verdict, findings, current) with verdict in
        ``skip|baseline|pass|fail``."""
    current = {"bus": bus_census(root), "collab": collab_census(root)}
    if not current["bus"]["present"] and not current["collab"]["present"]:
        return "skip", [], current
    if anchor is None:
        return "baseline", [], current
    if anchor.get("root") != str(root.resolve()):
        return (
            "baseline",
            ["anchor pertenece a otra raiz; se regenera baseline"],
            current,
        )
    findings = _evaluate_bus(anchor.get("bus") or {}, current["bus"])
    findings.extend(_evaluate_collab(anchor.get("collab") or {}, current["collab"]))
    return ("fail" if findings else "pass"), findings, current


def run_check(
    project_root: Path,
    update: bool = False,
    reason: str | None = None,
    source: str | None = None,
) -> dict:
    """Before: ``project_root`` is the root to guard (workspace or motor).
        ``update=True`` declares a legitimate shrinkage and requires a
        non-empty ``reason``.
    During: loads the anchor, censuses both surfaces, and evaluates. In
        ``--check`` mode a PASS/baseline rewrites the anchor (high-water marks
        only go UP); a FAIL never writes. In ``--update`` mode the current
        state is declared and becomes the new baseline (the declaration
        records before/after for audit).
    After: report dict: ``verdict`` (pass|baseline|fail|skip), ``findings``,
        ``skip_reason``, ``declared`` and the ``current`` census."""
    root = Path(project_root)
    anchor_path = _anchor_path(root)
    anchor, load_reason = _load_anchor(anchor_path)
    verdict, findings, current = evaluate(root, anchor)

    if update:
        if not reason or not reason.strip():
            return {
                "verdict": "fail",
                "findings": ["--update requiere --reason no vacio"],
                "declared": False,
                "current": current,
                "skip_reason": "",
            }
        if verdict == "skip":
            return {
                "verdict": "skip",
                "findings": [],
                "declared": False,
                "current": current,
                "skip_reason": "sin estado operativo (ni bus ni collaboration)",
            }
        declarations = list((anchor or {}).get("declarations") or [])
        declarations.append(
            {
                "at": _iso_now(),
                "surface": "bus+collab",
                "reason": reason.strip(),
                "source": (source or "cli").strip(),
                "before": {
                    "bus_union_hwm": int(
                        ((anchor or {}).get("bus") or {}).get(
                            "union_hwm",
                            ((anchor or {}).get("bus") or {}).get("union_lines", 0),
                        )
                    ),
                    "bus_live_hwm": int(
                        ((anchor or {}).get("bus") or {}).get(
                            "live_hwm",
                            ((anchor or {}).get("bus") or {}).get("live_lines", 0),
                        )
                    ),
                    "collab_file_count": int(
                        ((anchor or {}).get("collab") or {}).get("file_count", 0)
                    ),
                },
                "after": {
                    "bus_union_lines": current["bus"]["union_lines"],
                    "bus_live_lines": current["bus"]["live_lines"],
                    "collab_file_count": current["collab"]["file_count"],
                },
            }
        )
        _write_anchor(anchor_path, _build_anchor(root, current, declarations))
        return {
            "verdict": "pass",
            "findings": [],
            "declared": True,
            "declaration_reason": reason.strip(),
            "current": current,
            "skip_reason": "",
            "prior_findings": findings,
        }

    if verdict == "skip":
        return {
            "verdict": "skip",
            "findings": [],
            "declared": False,
            "current": current,
            "skip_reason": "sin estado operativo (ni bus ni collaboration)",
        }
    if verdict == "baseline":
        notes = list(findings)
        if load_reason in ("unreadable_anchor", "unsupported_anchor"):
            notes.append(
                f"anchor {load_reason}: se regenera baseline (nunca se fabrica un shrink)"
            )
        _write_anchor(anchor_path, _build_anchor(root, current, []))
        return {
            "verdict": "baseline",
            "findings": notes,
            "declared": False,
            "current": current,
            "skip_reason": "",
        }
    if verdict == "fail":
        return {
            "verdict": "fail",
            "findings": findings,
            "declared": False,
            "current": current,
            "skip_reason": "",
        }
    _write_anchor(anchor_path, _bump_anchor(anchor, current))
    return {
        "verdict": "pass",
        "findings": [],
        "declared": False,
        "current": current,
        "skip_reason": "",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Guard de monotonia/integridad del bus (union live+archive) y del "
            "censo de .agent/collaboration/ (WOT-2026-074x)."
        )
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="Raiz del proyecto a guardar (por defecto: AGENT_PROJECT_ROOT resuelto).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Modo por defecto: compara contra el ancla y falla ante mengua no declarada.",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Declara una mengua legitima (requiere --reason) y rebasea el ancla.",
    )
    parser.add_argument("--reason", default=None, help="Motivo de la declaracion.")
    parser.add_argument(
        "--source",
        default=None,
        help="Actor que declara (script, operador). Informativo.",
    )
    parser.add_argument("--json", action="store_true", help="Salida JSON.")
    return parser


def _resolve_default_root() -> Path:
    try:
        _bootstrap = Path(__file__).resolve().parent.parent
        if str(_bootstrap) not in sys.path:
            sys.path.insert(0, str(_bootstrap))
        from runtime.project_root import resolve_project_root

        return Path(resolve_project_root())
    except Exception:
        return Path.cwd()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.check and args.update:
        parser.error("--check y --update son mutuamente excluyentes")
    if args.update and not (args.reason and args.reason.strip()):
        parser.error("--update requiere --reason no vacio")

    root = Path(args.project_root) if args.project_root else _resolve_default_root()
    report = run_check(
        root,
        update=bool(args.update),
        reason=args.reason,
        source=args.source,
    )
    payload = {
        "root": str(root.resolve()) if root.exists() else str(root),
        "verdict": report["verdict"],
        "findings": report["findings"],
        "declared": report.get("declared", False),
        "skip_reason": report.get("skip_reason", ""),
        "bus": report["current"]["bus"],
        "collab": {
            "present": report["current"]["collab"]["present"],
            "file_count": report["current"]["collab"]["file_count"],
            "backlog_done_lines": report["current"]["collab"]["backlog_done_lines"],
        },
    }
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"[state-integrity] verdict={report['verdict']}")
        for finding in report["findings"]:
            print(f"  - {finding}")
        if report.get("declared"):
            print(f"  (declarado: {report.get('declaration_reason')})")
        if report["verdict"] == "skip":
            print(f"  SKIP: {report.get('skip_reason')}")
    return 1 if report["verdict"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
