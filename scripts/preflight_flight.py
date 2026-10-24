#!/usr/bin/env python3
"""Preflight census for autonomous multi-ticket batch (READ-ONLY fail-closed collector).

Censes four classes of blocking conditions BEFORE starting the first ticket.
The Paso 0 of the batch only verifies backend accessibility; this adds a
deterministic deeper census.

Checks:
    (a) GATE NO EJECUTABLE: every group's common_gate script must accept
        --help (argparse exit 0). Scripts that fail with "unrecognized argument"
        or "invalid choice" errors are classified as blocking.
    (c) ESTADO STALE: the workspace session state must not be "stale"
        (derived from init_session_scratch.py list).
    (d) DECISION HUMANA: tickets in autonomous-mode groups must not carry
        REQUIERE_HUMANO or DISENO_PRIMERO in their live backlog row.
    (b) DECLARED NON-GOAL: "gate mide el sitio equivocado" requires judgment
        (adversarial 1->9->2 phase), not a determinista; this script does NOT
        cover it (ficha WOT-2026-037c).

Usage:
    python scripts/preflight_flight.py --dag <path.json> --workspace-root <path> \\
        --backlog <path.md> [--json]

Exit codes:
    0 = all three deterministic classes (a, c, d) passed clean.
    1 = at least one blocking condition found (exit 1 with the list).
    2 = execution/collection error (bad paths, script not found).

Before: --dag, --workspace-root, --backlog point to valid paths; the DAG
    is a dict with a "groups" key; each group has "common_gate" and
    "autonomy_mode"; the backlog is a markdown file with table rows
    (may contain multi-line continuations inside cells).
During: splits common_gate by '&&' and shlex-splits each sub-command;
    runs subprocess --help probes only (never the raw command);
    consumes init_session_scratch list output, parses backlog table rows;
    never mutates the tree.
After: exits 0 if clean, or exits 1 with a list of blocking conditions
    each tagged with its class (a, c, d) and a resolver hint; always
    prints a count summary (groups/tickets censused).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any


# scripts/ is not a package: insert it on sys.path as the script itself does.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


# Derive_session_state is in preflight_codeonly_pipeline; import it for reuse.
# We bootstrap the motor root and let the module handle its own sys.path.
_MOTOR_ROOT_BOOTSTRAP = _SCRIPTS_DIR.parent
if str(_MOTOR_ROOT_BOOTSTRAP) not in sys.path:
    sys.path.insert(0, str(_MOTOR_ROOT_BOOTSTRAP))

try:
    from preflight_codeonly_pipeline import derive_session_state
except ImportError:
    derive_session_state = None  # type: ignore[misc,assignment]


# Backlog literals that signal a human decision is required.
_HUMAN_DECISION_PATTERNS = (
    re.compile(r"REQUIERE_HUMANO", re.IGNORECASE),
    re.compile(r"DISENO_PRIMERO", re.IGNORECASE),
)


def _split_gate_commands(gate: str) -> list[str]:
    """Split a common_gate into sub-commands by '&&'.

    Before: gate is the raw common_gate string (may contain '&&' chains).
    During: splits on literal '&&', trims whitespace.
    After: list of trimmed sub-command strings.
    """
    return [s.strip() for s in gate.split("&&") if s.strip()]


def _strip_matching_quotes(token: str) -> str:
    """Remove matching double-quote delimiters from a token.

    Before: token may be surrounded by matching '"' characters (e.g.
        '"C:/path/script.py"' or 'normal').
    During: checks that len >= 2, first char is '"', last char is '"'.
    After: stripped token without the surrounding quotes, or original if
        no matching pair.
    """
    if len(token) >= 2 and token[0] == '"' and token[-1] == '"':
        return token[1:-1]
    return token


def _shlex_subcommand(sub_cmd: str) -> list[str]:
    """Parse a single sub-command string into a list of tokens.

    Uses shlex.split with posix=False on Windows and posix=True on Unix,
    to correctly handle quoted paths (e.g. "C:/Users/fdl/...").
    After shlex.split, applies _strip_matching_quotes to every token so
    that Windows (posix=False) does not leave literal quote characters
    embedded in the token strings.

    Before: sub_cmd is a single command string (no '&&').
    During: shlex.split respecting quotes, then strips matching quotes.
    After: list of tokens suitable for subprocess.run, with no embedded
        '"' delimiters on any token.

    Known limit: a flag expecting a VALUE (e.g. --real <algo>) could
    absorb a malformed flag argument if passed in wrong order; this
    does not affect the --help probe used here because we only append
    --help AFTER a fully parsed sub-command, never mix flags mid-stream.
    """
    posix = os.name != "nt"
    raw_tokens = shlex.split(sub_cmd, posix=posix)
    return [_strip_matching_quotes(t) for t in raw_tokens]


def _check_subcommand_for_argparse_error(
    sub_cmd_tokens: list[str],
    group_id: str,
    original_gate: str,
) -> dict[str, Any] | None:
    """Run one sub-command with --help appended; return a block if argparse error.

    Before: sub_cmd_tokens is a parsed sub-command list (e.g. ['python',
        'path/to/script.py', '--flag']).
    During: runs subprocess with --help appended, 15s timeout.
    After: a blocking dict if argparse error, or None.
    """
    probe = subprocess.run(  # noqa: S603
        [*sub_cmd_tokens, "--help"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    combined = (probe.stdout + probe.stderr).lower()
    has_usage = "usage:" in combined
    has_unrecognized = "unrecognized argument" in combined
    has_invalid_choice = "invalid choice" in combined

    is_argparse_error = probe.returncode != 0 and (
        not has_usage or has_unrecognized or has_invalid_choice
    )

    if is_argparse_error:
        return {
            "class": "a",
            "group": group_id,
            "command": original_gate,
            "reason": (
                f"sub-comando '{sub_cmd_tokens[0] if sub_cmd_tokens else ''} --help' "
                f"falla con argparse error (exit {probe.returncode}); "
                f"usage present: {has_usage}, "
                f"unrecognized: {has_unrecognized}, "
                f"invalid_choice: {has_invalid_choice}"
            ),
            "resolver": (
                f"revisar el common_gate del grupo '{group_id}': "
                f"el script no reconoce los flags esperados. "
                f"Corregir el comando o el script."
            ),
        }
    return None


def _process_subcommand_for_group(
    sub_cmd: str,
    group_id: str,
    original_gate: str,
) -> list[dict[str, Any]]:
    """Process a single sub-command and check for blocking conditions.

    Before: sub_cmd is a parsed sub-command string.
    During: shlex-splits and checks for script existence and argparse errors.
    After: list of blocking dicts (0 or more).
    """
    blocks: list[dict[str, Any]] = []
    try:
        tokens = _shlex_subcommand(sub_cmd)
    except ValueError:
        blocks.append(
            {
                "class": "a",
                "group": group_id,
                "command": original_gate,
                "reason": f"no se pudo parsear sub-comando: '{sub_cmd}' (shlex falló)",
                "resolver": "verificar la sintaxis del common_gate del grupo",
            }
        )
        return blocks

    if not tokens:
        return blocks

    # Check script existence: first .py token
    for token in tokens:
        if token.endswith(".py"):
            if not Path(token).exists():
                blocks.append(
                    {
                        "class": "a",
                        "group": group_id,
                        "command": original_gate,
                        "reason": f"script '{token}' no existe",
                        "resolver": "verificar que el script existe bajo motor_root",
                    }
                )
                return blocks
            break

    block = _check_subcommand_for_argparse_error(tokens, group_id, original_gate)
    if block:
        blocks.append(block)

    return blocks


def _census_class_a(dag: dict) -> list[dict[str, Any]]:
    """Check (a): GATE NO EJECUTABLE.

    For each group in the DAG, split its common_gate by '&&' into sub-commands,
    shlex-split each into tokens, and run each with --help appended (subprocess,
    15s timeout). If any sub-command produces an argparse error, classify as
    blocking. HARD-STOP naming the group and the exact command.

    This is READ-ONLY: we never execute the original command without --help.
    Known limit: a flag expecting a VALUE could absorb a malformed argument
    in edge cases, but the --help probe does not trigger it.

    Before: dag is the parsed DAG dict with a "groups" key.
    During: runs subprocess with --help flag for each sub-command (never the
        raw command). Never mutates the tree.
    After: list of blocking dicts {group, command, reason} or empty list.
    """
    blocks: list[dict[str, Any]] = []
    groups = dag.get("groups")
    if not isinstance(groups, list):
        return blocks

    for group in groups:
        if not isinstance(group, dict):
            continue
        gid = group.get("id", "<sin id>")
        gate = group.get("common_gate")
        if not isinstance(gate, str):
            continue

        sub_commands = _split_gate_commands(gate)
        for sub_cmd in sub_commands:
            blocks.extend(_process_subcommand_for_group(sub_cmd, gid, gate))

    return blocks


def _census_class_c(workspace_root: Path) -> list[dict[str, Any]]:
    """Check (c): ESTADO STALE heredado.

    Call derive_session_state from preflight_codeonly_pipeline on the given
    workspace_root. If the result is "stale", return a blocking condition.

    Before: workspace_root is the resolved path to the workspace (destino).
    During: consumes init_session_scratch.py list output via the imported
        derive_session_state helper.
    After: list with one blocking dict if state is "stale", empty otherwise.
    """
    if derive_session_state is None:
        return [
            {
                "class": "c",
                "reason": "derive_session_state no disponible (import error)",
                "resolver": "verificar que preflight_codeonly_pipeline.py es accesible",
            }
        ]

    # We need to run the real subprocess that init_session_scratch.py list uses.
    # derive_session_state operates on the parsed sessions list, so we must
    # invoke the CLI first and parse its output.
    motor_root = _MOTOR_ROOT_BOOTSTRAP
    list_result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(motor_root / "scripts" / "init_session_scratch.py"),
            "--project-root",
            str(workspace_root),
            "list",
            "--include-archive",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    sessions: list[dict] = []
    if list_result.returncode == 0 and list_result.stdout.strip():
        try:
            payload = json.loads(list_result.stdout)
            sessions = payload.get("sessions") or []
        except json.JSONDecodeError:
            sessions = []

    state = derive_session_state(sessions)
    if state == "stale":
        return [
            {
                "class": "c",
                "workspace": str(workspace_root),
                "reason": f"session_state es 'stale' en {workspace_root}",
                "resolver": "reclamar o reiniciar la sesion stale antes de volar",
            }
        ]

    return []


def _is_separator_line(line: str) -> bool:
    """Check if a pipe-delimited line is a markdown table separator (all dashes).

    Before: line is a string starting with '|'.
    During: splits by '|', checks if all non-empty cells are only dashes/dots/whitespace.
    After: True if the line is a separator, False otherwise.
    """
    cells = [c.strip() for c in line.split("|")]
    cells = [c for c in cells if c]
    if not cells:
        return False
    separator_chars = set("-.:_ ")
    return all(set(c).issubset(separator_chars) for c in cells)


def _parse_row_line(
    line: str,
    headers: list[str],
) -> dict[str, str] | None:
    """Parse a single pipe-delimited table line into a row dict.

    Before: line is a string starting with '|'; headers is the list of column
        names from the header row.
    During: splits by '|', strips cells, matches to headers.
    After: dict mapping column name -> cell value, or None if cell count
        mismatches or line is a separator.
    """
    if _is_separator_line(line):
        return None
    cells = [c.strip() for c in line.split("|")]
    cells = [c for c in cells if c]
    if len(cells) != len(headers):
        return None
    row_dict: dict[str, str] = {}
    for i, h in enumerate(headers):
        if i < len(cells):
            row_dict[h] = cells[i]
    return row_dict


def _handle_backlog_line(
    stripped: str,
    headers: list[str],
    current_row: dict[str, str] | None,
) -> tuple[dict[str, str] | None, bool]:
    """Handle a single backlog line (new row or continuation).

    Before: stripped is the line content; headers from the header row;
        current_row is the row being accumulated.
    During: checks if line starts with '|' for new row vs continuation.
    After: (new_current_row, should_close) where should_close indicates
        that a new row started and the previous one should be flushed.
    """
    if stripped.startswith("|"):
        new_row = _parse_row_line(stripped, headers)
        if new_row is not None:
            return new_row, current_row is not None
        return current_row, False
    else:
        if current_row is not None:
            last_key = headers[-1] if headers else None
            if last_key is not None:
                current_row[last_key] = current_row[last_key] + " " + stripped
    return current_row, False


def _parse_backlog_rows(backlog_text: str) -> list[dict[str, str]]:
    """Parse markdown backlog table rows into dicts keyed by column header.

    Handles multi-line continuation rows: when a line does not start with '|'
    but the previous line did (and we have an open row), the continuation line
    is appended to the last cell of that row. This prevents false negatives
    when REQUIERE_HUMANO / DISENO_PRIMERO appears in a continuation line.

    Before: backlog_text is the raw markdown of the live backlog queue.
    During: splits by pipe-delimited rows; first header row gives keys.
        Accumulates continuation lines into the last cell of the current row.
    After: list of dicts mapping column name -> cell value.
    """
    rows: list[dict[str, str]] = []
    lines = backlog_text.strip().splitlines()
    if not lines:
        return rows

    header_line = lines[0]
    if not header_line.lstrip().startswith("|"):
        return rows

    headers = [h.strip() for h in header_line.split("|")]
    headers = [h for h in headers if h]

    current_row: dict[str, str] | None = None

    for line in lines[1:]:
        stripped = line.strip()
        if not stripped:
            continue

        next_row, should_close = _handle_backlog_line(stripped, headers, current_row)

        if should_close and current_row is not None:
            rows.append(current_row)

        current_row = next_row

    if current_row is not None:
        rows.append(current_row)

    return rows


def _check_ticket_for_human_decision(
    row: dict[str, str], ticket_id: str
) -> list[dict[str, Any]]:
    """Check one backlog row for human-decision literals.

    Before: row is a parsed backlog row dict; ticket_id is the ticket string.
    During: scans all cell values against _HUMAN_DECISION_PATTERNS.
    After: list of blocking dicts for this ticket, or empty.
    """
    blocks: list[dict[str, Any]] = []
    for cell_value in row.values():
        for pattern in _HUMAN_DECISION_PATTERNS:
            if pattern.search(cell_value):
                blocks.append(
                    {
                        "class": "d",
                        "ticket": ticket_id,
                        "reason": (
                            f"fila de '{ticket_id}' contiene '{pattern.pattern}' "
                            f"(literal detectado en backlog)"
                        ),
                        "resolver": (
                            f"remover '{pattern.pattern}' de la fila de "
                            f"'{ticket_id}' en backlog.md o re-clasificar "
                            f"el grupo del DAG"
                        ),
                    }
                )
                break  # one match per pattern is enough
    return blocks


def _find_ticket_row(
    rows: list[dict[str, str]], ticket_id: str
) -> dict[str, str] | None:
    """Find the live backlog row for a given ticket_id.

    The ticket_id cell must be an exact match (not substring in prose).
    Before: rows is a list of parsed backlog row dicts; ticket_id is a string.
    During: scans the first column matching a ticket-shaped cell.
    After: the row dict for that ticket, or None if not found.
    """
    ticket_re = re.compile(r"[A-Z]{2,4}-\d{4}-\d{3}[a-z]?")
    for row in rows:
        for cell_value in row.values():
            stripped = cell_value.strip()
            if ticket_re.fullmatch(stripped) and stripped == ticket_id:
                return row
    return None


def _census_class_d(dag: dict, backlog_path: Path) -> list[dict[str, Any]]:
    """Check (d): DECISION HUMANA EN GRUPO EJECUTABLE.

    For each group whose autonomy_mode is "autonomous", for each ticket_id
    of that group, look up its live row in backlog.md and check if the row
    prose contains "REQUIERE_HUMANO" or "DISENO_PRIMERO" (case-insensitive).
    Treat any appearance as a blocking condition (fail-closed).
    HARD-STOP naming ticket + group.

    Before: dag is parsed; backlog_path points to the backlog markdown.
    During: reads and parses the backlog table; scans row prose.
    After: list of blocking dicts {group, ticket, reason} or empty.
    """
    blocks: list[dict[str, Any]] = []
    groups = dag.get("groups")
    if not isinstance(groups, list):
        return blocks

    if not backlog_path.exists():
        return [
            {
                "class": "d",
                "reason": f"backlog no existe: {backlog_path}",
                "resolver": "verificar la ruta --backlog",
            }
        ]

    backlog_text = backlog_path.read_text(encoding="utf-8")
    rows = _parse_backlog_rows(backlog_text)

    for group in groups:
        if not isinstance(group, dict):
            continue
        gid = group.get("id", "<sin id>")
        # Only check autonomous-mode groups
        if group.get("autonomy_mode") != "autonomous":
            continue

        tickets = group.get("tickets", [])
        if not isinstance(tickets, list):
            continue

        for ticket_id in tickets:
            if not isinstance(ticket_id, str):
                continue
            row = _find_ticket_row(rows, ticket_id)
            if row is None:
                # Ticket not found in backlog -> treat as blocking (fail-closed)
                blocks.append(
                    {
                        "class": "d",
                        "group": gid,
                        "ticket": ticket_id,
                        "reason": f"ticket '{ticket_id}' no tiene fila viva en backlog",
                        "resolver": f"verificar que '{ticket_id}' esta en el backlog vivo del grupo '{gid}'",
                    }
                )
                continue

            blocks.extend(_check_ticket_for_human_decision(row, ticket_id))

    return blocks


def _count_groups_and_tickets(dag: dict) -> tuple[int, int]:
    """Count total groups and total tickets in the DAG for the summary."""
    groups = dag.get("groups")
    if not isinstance(groups, list):
        return 0, 0
    total_tickets = 0
    for group in groups:
        if isinstance(group, dict):
            total_tickets += len(group.get("tickets", []) or [])
    return len(groups), total_tickets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Preflight census for autonomous multi-ticket batch "
        "(READ-ONLY fail-closed collector, WOT-2026-037c)."
    )
    parser.add_argument("--dag", required=True, help="Path to the DAG JSON file.")
    parser.add_argument(
        "--workspace-root", required=True, help="Path to the workspace (destino) root."
    )
    parser.add_argument("--backlog", required=True, help="Path to the backlog.md file.")
    parser.add_argument(
        "--json", action="store_true", help="Emit structured JSON output to stdout."
    )
    args = parser.parse_args(argv)

    dag_path = Path(args.dag)
    if not dag_path.exists():
        print(f"[ERROR] dag no existe: {dag_path}", file=sys.stderr)
        return 2

    try:
        dag = json.loads(dag_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[ERROR] dag JSON invalido: {exc}", file=sys.stderr)
        return 2

    workspace_root = Path(args.workspace_root)
    backlog_path = Path(args.backlog)

    # Run the three deterministic censuses
    blocks_a = _census_class_a(dag)
    blocks_c = _census_class_c(workspace_root)
    blocks_d = _census_class_d(dag, backlog_path)

    all_blocks = blocks_a + blocks_c + blocks_d
    n_groups, n_tickets = _count_groups_and_tickets(dag)

    summary = {
        "groups_censused": n_groups,
        "tickets_censused": n_tickets,
        "blocks_found": len(all_blocks),
        "details": all_blocks,
    }

    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print("=== PREFLIGHT FLIGHT CENSUS (WOT-2026-037c) ===")
        print(f"groups censused : {n_groups}")
        print(f"tickets censused: {n_tickets}")
        print(f"blocks found    : {len(all_blocks)}")
        if all_blocks:
            for i, b in enumerate(all_blocks, 1):
                print(f"  BLOCK {i} [class {b['class']}]: {b.get('reason', 'unknown')}")
            print("")
            print("=> HARD-STOP: corregir los bloqueos antes de arrancar el batch.")
        else:
            print("=> Preflight clean: las 3 clases deterministas pasaron.")

    # Exit 0 if clean, exit 1 if any blocking condition found
    return 1 if all_blocks else 0


if __name__ == "__main__":
    sys.exit(main())
