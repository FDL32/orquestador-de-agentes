#!/usr/bin/env python3
"""WOT-2026-022q: read-only suite performance regression REPORT over run_history.

Named a *report*, not a *check_*: it NEVER blocks (exit 0 always, pattern
WOT-2026-022e), so a ``check_``/``validate_``/``guard_`` prefix would be a false
promise of a barrier -- the guard-wiring contract (WOT-2026-024u) reserves those
prefixes for wired barriers. This is an informative reporter, invoked on demand;
its post-suite wiring is a declared follow-up (see WOT-2026-022q contract).

Before: ``scripts/run_pytest_safe.py`` (WOT-2026-021w) appends per-run telemetry
to ``.agent/runtime/pytest-safe/run_history.jsonl`` (counts, ``duration_s``,
``top_slowest``, sha). Nobody compares consecutive runs, so a wall-clock
regression (a new slow test, a fixture that got pricier) stays invisible until
the suite "feels" slow. WOT-2026-021x designed the pilot comparison method.

During: parse the jsonl READ-ONLY, keep only ``level=all`` + ``status=finished``
+ NOT-failed records that carry a real ``duration_s``, compare the CURRENT (last
``level=all``) run against the MEDIAN of the previous K comparable runs, and emit
a classified WARN if the total duration or a ``top_slowest`` nodeid grew beyond a
configurable threshold. Corrupt lines, missing fields, ``dry-run`` rows and
failed runs are SKIPPED, never crash. No write, no mkdir: pure reader.

After: prints a report to stdout and ALWAYS exits 0 (informative, pattern
WOT-2026-022e): this NEVER blocks the suite. A ``dry-run`` or FAILED current run
suppresses the perf comparison (a red suite's wall-clock is not a valid
baseline) with an informative line, not a WARN. Raises nothing on bad input.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any


# WOT-2026-022q [PATH]: resolve independently from __file__ (scripts/ hangs off
# the project root) so this stays stdlib-only and never imports run_pytest_safe
# (which drags `from runtime.project_root import ...`, fragile via sys.path).
_DEFAULT_HISTORY = (
    Path(__file__).resolve().parent.parent
    / ".agent"
    / "runtime"
    / "pytest-safe"
    / "run_history.jsonl"
)

DEFAULT_WINDOW = 5
DEFAULT_THRESHOLD_PCT = 20.0
# Need at least this many comparable historic runs to form a stable median.
MIN_HISTORY = 3
# Per-nodeid comparison needs at least this many historic samples of that nodeid.
MIN_NODEID_SAMPLES = 3


def _iter_records(path: Path) -> list[dict[str, Any]]:
    """Read the jsonl READ-ONLY, skipping corrupt lines (never raises).

    Before: ``path`` may be absent, empty, or contain a half-written line (the
    collector appends concurrently). During: read text, parse line by line,
    dropping any line that is not a JSON object. After: returns the list of
    dict records (possibly empty); never raises on I/O or parse error.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue  # half-written / corrupt line -> skip, do not crash
        if isinstance(obj, dict):
            records.append(obj)
    return records


def _is_failed(rec: dict[str, Any]) -> bool:
    """True if the run recorded failures or errors (unreliable wall-clock)."""
    return bool(rec.get("failed_count") or rec.get("errors"))


def _duration(rec: dict[str, Any]) -> float | None:
    """Return ``duration_s`` as a float, or None if absent/non-numeric."""
    val = rec.get("duration_s")
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return float(val)
    return None


def _is_comparable(rec: dict[str, Any]) -> bool:
    """A record usable as a green baseline: level=all, finished, green, timed."""
    return (
        rec.get("level") == "all"
        and rec.get("status") == "finished"
        and not _is_failed(rec)
        and _duration(rec) is not None
    )


def _nodeid_seconds(rec: dict[str, Any]) -> dict[str, float]:
    """Map nodeid -> seconds from a record's ``top_slowest`` (robust to shape)."""
    out: dict[str, float] = {}
    top = rec.get("top_slowest")
    if not isinstance(top, list):
        return out
    for entry in top:
        if not isinstance(entry, dict):
            continue
        nodeid = entry.get("nodeid")
        secs = entry.get("seconds")
        if isinstance(nodeid, str) and isinstance(secs, (int, float)):
            # A nodeid can appear twice (setup+call+teardown rows); keep the max.
            out[nodeid] = max(out.get(nodeid, 0.0), float(secs))
    return out


def _pct_delta(current: float, baseline: float) -> float | None:
    """Percentage growth of ``current`` over ``baseline`` (None if baseline<=0)."""
    if baseline <= 0:
        return None
    return (current - baseline) / baseline * 100.0


def _check_total_duration(
    current: dict[str, Any], history: list[dict[str, Any]], threshold_pct: float
) -> str | None:
    """WARN string if the current total duration regressed vs the median."""
    cur = _duration(current)
    if cur is None:
        return None
    baseline = statistics.median([_duration(r) for r in history])  # type: ignore[misc]
    delta = _pct_delta(cur, baseline)
    if delta is not None and delta > threshold_pct:
        return (
            f"WARN [total] duration {cur:.1f}s vs median {baseline:.1f}s "
            f"(+{delta:.1f}% > {threshold_pct:.0f}%)"
        )
    return None


def _check_nodeids(
    current: dict[str, Any], history: list[dict[str, Any]], threshold_pct: float
) -> list[str]:
    """WARN strings for each current top_slowest nodeid that regressed."""
    warns: list[str] = []
    cur_map = _nodeid_seconds(current)
    for nodeid, cur_secs in sorted(cur_map.items(), key=lambda kv: -kv[1]):
        samples = [
            s for r in history if (s := _nodeid_seconds(r).get(nodeid)) is not None
        ]
        if len(samples) < MIN_NODEID_SAMPLES:
            continue  # not enough history for this nodeid to judge
        baseline = statistics.median(samples)
        delta = _pct_delta(cur_secs, baseline)
        if delta is not None and delta > threshold_pct:
            warns.append(
                f"WARN [test] {nodeid}: {cur_secs:.2f}s vs median "
                f"{baseline:.2f}s (+{delta:.1f}% > {threshold_pct:.0f}%)"
            )
    return warns


def analyze(
    records: list[dict[str, Any]], window: int, threshold_pct: float
) -> tuple[list[str], str]:
    """Compare the current level=all run against the median of the prior K.

    Before: ``records`` is the parsed jsonl (any order preserved as on disk).
    During: locate the current run, gate on dry-run/failed/insufficient-history,
    then run the total-duration and per-nodeid comparisons. After: returns
    ``(warnings, info)`` -- ``warnings`` is a possibly-empty list of classified
    WARN lines; ``info`` is a single human line describing what happened. Never
    raises.
    """
    level_all = [r for r in records if r.get("level") == "all"]
    if not level_all:
        return [], "sin corridas level=all en run_history -> nada que comparar"

    current = level_all[-1]
    if current.get("status") == "dry-run":
        return [], "la ultima corrida level=all es dry-run -> comparacion omitida"
    if _is_failed(current):
        return [], (
            "la ultima corrida level=all FALLO (failed/errors > 0) -> WARN de "
            "rendimiento SUPRIMIDO (un suite en rojo no es baseline valido)"
        )
    if _duration(current) is None:
        return [], "la ultima corrida level=all no tiene duration_s -> omitida"

    # Comparable history = prior green level=all runs, excluding the current one.
    history = [r for r in level_all[:-1] if _is_comparable(r)][-window:]
    if len(history) < MIN_HISTORY:
        return [], (
            f"historico comparable insuficiente ({len(history)} < {MIN_HISTORY}) "
            f"-> se necesitan mas corridas verdes level=all"
        )

    warns: list[str] = []
    total = _check_total_duration(current, history, threshold_pct)
    if total:
        warns.append(total)
    warns.extend(_check_nodeids(current, history, threshold_pct))

    sha = str(current.get("tested_commit_sha") or "?")[:10]
    if warns:
        info = (
            f"regresion(es) de rendimiento detectada(s) @ {sha} vs mediana de "
            f"{len(history)} corridas (umbral {threshold_pct:.0f}%)"
        )
    else:
        info = (
            f"sin regresion @ {sha} vs mediana de {len(history)} corridas "
            f"(umbral {threshold_pct:.0f}%)"
        )
    return warns, info


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint. ALWAYS returns 0 (informative, never blocks)."""
    parser = argparse.ArgumentParser(
        description=(
            "Check de regresion de rendimiento de la suite (read-only, "
            "informativo). NUNCA bloquea: exit 0 siempre (WOT-2026-022q)."
        )
    )
    parser.add_argument(
        "--history",
        type=Path,
        default=_DEFAULT_HISTORY,
        help="Ruta a run_history.jsonl (default: .agent/runtime/pytest-safe/).",
    )
    parser.add_argument(
        "--window",
        type=int,
        default=DEFAULT_WINDOW,
        help=f"K corridas para la mediana (default {DEFAULT_WINDOW}).",
    )
    parser.add_argument(
        "--threshold-pct",
        type=float,
        default=DEFAULT_THRESHOLD_PCT,
        help=f"Umbral de crecimiento en %% (default {DEFAULT_THRESHOLD_PCT}).",
    )
    args = parser.parse_args(argv)

    if not args.history.exists():
        print(
            f"[suite-regression] run_history ausente ({args.history}) -> nada que hacer"
        )
        return 0

    records = _iter_records(args.history)
    if not records:
        print("[suite-regression] run_history vacio o ilegible -> nada que hacer")
        return 0

    warns, info = analyze(records, args.window, args.threshold_pct)
    print(f"[suite-regression] {info}")
    for w in warns:
        print(f"[suite-regression] {w}")
    return 0  # never blocks


if __name__ == "__main__":
    sys.exit(main())
