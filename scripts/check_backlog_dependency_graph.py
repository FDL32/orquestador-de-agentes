#!/usr/bin/env python3
"""WOT-2026-027e: check backlog dependency graph.

Detects "phantom" and "hanging" dependencies in the 'Depende de' cell of the live backlog.
A dependency is a PHANTOM if its ID does not exist in the live backlog or the archive.
A dependency is HANGING if its ID is archived but the cell does not declare it as SATISFECHA.
"""

from __future__ import annotations

import argparse

# Add parent directory to sys.path to allow importing from scripts
import re
import sys
from pathlib import Path
from typing import NamedTuple


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.check_backlog_contract import (
    _DEPENDS_ON_ID_RE,
    _extract_active_table,
    ensure_bound,
)


class CheckResult(NamedTuple):
    """Resultado de un check individual.

    `skipped` distingue "paso porque se ejecuto y valido" de "paso porque no
    habia nada que validar". Los dos llevan `passed=True` y el informe de
    cierre los mostraba identicos (`[OK] <nombre>`), asi que un gate saltado
    era indistinguible de uno cumplido -- incluido en gates BLOQUEANTES.

    Es un campo y no una convencion de texto a proposito: detectarlo con
    `output.startswith("SKIP")` dejaba fuera los saltos redactados de otra
    forma ("No backlog.md at ... (skipped)") y dependia de mayusculas y del
    idioma del mensaje (bucle L700, lentes Codex y GLM-5.2, 2026-08-02).
    """

    name: str
    passed: bool
    output: str
    is_blocking: bool = True
    skipped: bool = False


# Fallback regex for when alternation is not bound (e.g. in unit tests)
_FALLBACK_ID_RE = re.compile(r"\b(?:WOT|WP|WT|CTL)-\d{4}-[a-z0-9]+\b")

# The pattern for 'SATISFECHA' declaration in the cell.
_SATISFECHA_RE = re.compile(r"SATISFECHA", re.IGNORECASE)


def parse_depends_cell(text: str) -> dict[str, list[str] | str]:
    """Parses the 'Depende de' cell content to extract cited IDs and satisfied IDs.

    Args:
        text: The raw text from the 'Depende de' cell.

    Returns:
        A dictionary containing:
        - 'ids': list of all cited ticket IDs.
        - 'satisfied_ids': list of IDs declared as SATISFECHA.
        - 'raw': the original text.
    """
    if not text or text.strip() == "-":
        return {"ids": [], "satisfied_ids": [], "raw": text}

    # Use the module's regex if bound, otherwise use fallback
    pattern = _DEPENDS_ON_ID_RE if _DEPENDS_ON_ID_RE is not None else _FALLBACK_ID_RE

    ids: list[str] = []
    satisfied_ids: list[str] = []

    matches = list(pattern.finditer(text))
    for i, match in enumerate(matches):
        tid = match.group(0)
        ids.append(tid)

        # Check if SATISFECHA follows this match before the next ID
        end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        after_text = text[match.end() : end_pos]

        if _SATISFECHA_RE.search(after_text):
            satisfied_ids.append(tid)

    return {
        "ids": ids,
        "satisfied_ids": satisfied_ids,
        "raw": text,
    }


def check_backlog_integrity(root: Path) -> list[str]:
    """Checks the backlog for phantom and hanging dependencies.

    Args:
        root: The destination project root.

    Returns:
        A list of error messages.
    """
    collab = root / ".agent" / "collaboration"
    backlog_path = collab / "backlog.md"
    archive_path = collab / "_archive" / "backlog_done.md"

    if not backlog_path.exists():
        return [f"backlog.md not found at {backlog_path}"]

    # 1. Load all IDs from both surfaces to build the universe.
    from scripts.check_backlog_contract import (
        _compact_terminal_closure_ids,
        _ticket_row_ids,
    )

    # Live IDs (Prioridad-led rows in backlog.md)
    live_ids_list = _ticket_row_ids(backlog_path)
    live_ids_set = set(live_ids_list)

    # Archive IDs (both snapshot rows and compact terminal rows)
    archive_snapshot_ids = set(_ticket_row_ids(archive_path))
    archive_compact_ids = set(_compact_terminal_closure_ids(archive_path).keys())
    archive_ids_set = archive_snapshot_ids | archive_compact_ids

    # 2. Parse the live backlog table.
    content = backlog_path.read_text(encoding="utf-8-sig")
    rows, table_error = _extract_active_table(content)
    if table_error:
        return [f"Table error in backlog.md: {table_error}"]

    errors: list[str] = []
    for row in rows:
        # Columns: Prioridad (0), Ticket (1), Titulo (2), Scope (3), Estado (4), Depende de (5), Origen (6), Reactivation (7)
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        if len(cells) < 6:
            continue

        ticket = cells[1]
        depends_on_text = cells[5]

        if not depends_on_text or depends_on_text == "-":
            continue

        # Parse the cell
        parsed = parse_depends_cell(depends_on_text)
        cited_ids = parsed["ids"]
        satisfied_ids = parsed["satisfied_ids"]

        for cited_id in cited_ids:
            # Check if it's a phantom
            is_phantom = (cited_id not in live_ids_set) and (
                cited_id not in archive_ids_set
            )
            if is_phantom:
                errors.append(
                    f"{ticket}: Phantom dependency on {cited_id} (not found in backlog or archive)"
                )
                continue

            # Check if it's hanging
            # Hanging: ID is in archive, but NOT declared as SATISFECHA in the cell
            is_in_archive = cited_id in archive_ids_set
            is_satisfied = cited_id in satisfied_ids

            if is_in_archive and not is_satisfied:
                errors.append(
                    f"{ticket}: Hanging dependency on {cited_id} (archived but not marked SATISFECHA)"
                )

    return errors


def run_backlog_dependency_graph_check(project_root: Path) -> CheckResult:
    """Ejecuta el check de grafo de dependencias del backlog.

    Args:
        project_root: Raiz del proyecto.

    Returns:
        CheckResult con el estado del check.
    """
    errors = check_backlog_integrity(project_root)
    if errors:
        return CheckResult(
            name="Backlog Dependency Graph Check",
            passed=False,
            output="\n".join(errors),
            is_blocking=False,
        )
    return CheckResult(
        name="Backlog Dependency Graph Check",
        passed=True,
        output="Dependency graph is valid",
        is_blocking=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Check backlog dependency graph.")
    parser.add_argument(
        "--project-root",
        type=str,
        required=True,
        help="Path to the destination project root.",
    )
    args = parser.parse_args()

    root = Path(args.project_root)

    # 1. Bind patterns
    bound, prefix_err = ensure_bound(root)
    if not bound:
        print(f"Error: {prefix_err}")
        sys.exit(1)

    # 2. Run check
    errors = check_backlog_integrity(root)

    if errors:
        print("Dependency graph violations found:")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)
    else:
        print("Dependency graph is valid.")
        sys.exit(0)


if __name__ == "__main__":
    main()
