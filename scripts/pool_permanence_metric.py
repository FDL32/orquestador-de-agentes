#!/usr/bin/env python3
"""Derivador de metrica de permanencia del pool (WOT-2026-027r).

Before: lee scorecard.jsonl via _read_scorecard de ensemble_dispatch (mismo
    patron que check_loop_execution). Requiere --project-root apuntando al
    workspace que contiene .agent/runtime/ensemble/scorecard.jsonl.
During: computa por backend la tasa de conversion de hipotesis:
    adoptadas / total_filas. READ-ONLY sobre el scorecard; no lo reescribe.
After: emite tabla a stdout con la tasa por backend. Exit 0 siempre
    (no es un gate, es un derivador de reporte). Exit 2 si --project-root
    falta o es invalido.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


MOTOR_ROOT = Path(__file__).resolve().parent.parent
if str(MOTOR_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(MOTOR_ROOT / "scripts"))

from ensemble_dispatch import _read_scorecard  # noqa: E402


def compute_conversion_rates(rows: list[dict]) -> dict[str, tuple[int, int]]:
    """Return {backend: (adopted_count, total_count)} from scorecard rows.

    Only rows with event == "adjudicacion" count: these are the final
    decisions where outcome is meaningful.  Rows with event == "ronda"
    are intermediate round outputs and are excluded from the conversion
    rate (they don't represent a hypothesis decision).
    """
    adopted: dict[str, int] = {}
    total: dict[str, int] = {}
    for row in rows:
        if row.get("event") != "adjudicacion":
            continue
        backend = row.get("backend") or "unknown"
        total[backend] = total.get(backend, 0) + 1
        if row.get("outcome") == "adoptada":
            adopted[backend] = adopted.get(backend, 0) + 1
    return {b: (adopted.get(b, 0), total[b]) for b in total}


def format_table(rates: dict[str, tuple[int, int]]) -> str:
    """Format conversion rates as a human-readable table string."""
    if not rates:
        return "Sin datos (0 filas en scorecard)"
    lines = ["Backend          | Adoptadas | Total | Tasa", "-" * 48]
    for backend in sorted(rates, key=lambda b: rates[b][1], reverse=True):
        adop, tot = rates[backend]
        pct = (adop / tot * 100) if tot else 0.0
        lines.append(f"{backend:<16} | {adop:>9} | {tot:>5} | {pct:.1f}%")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deriva la metrica de permanencia del pool por backend.",
    )
    parser.add_argument(
        "--project-root",
        required=True,
        help="Workspace que contiene .agent/runtime/ensemble/scorecard.jsonl",
    )
    args = parser.parse_args(argv)
    project_root = Path(args.project_root)
    if not project_root.is_dir():
        print(f"[ERROR] project-root no existe: {project_root}", file=sys.stderr)
        return 2
    rows, _sha = _read_scorecard(project_root)
    rates = compute_conversion_rates(rows)
    print(format_table(rates))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
