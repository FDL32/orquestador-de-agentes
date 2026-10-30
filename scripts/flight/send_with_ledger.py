#!/usr/bin/env python3
"""Flight supervision ledger helper: VALIDATES and REGISTERS sends, never sends.

The agent sends messages via t3_thread_send (an MCP tool, not a program).
This helper validates before and registers after; the decision to send
stays with the agent.

CLI subcommands:
    check  -- read the ledger, return authorized or refused.
    record -- append a single line with fixed schema.

Exit codes:
    0 = authorized / written
    1 = refused (reason printed to stdout)
    2 = usage error or illegible input

Before: the ledger path is provided via --ledger; by and mensaje_id are
    required arguments.
During: check reads the ledger and applies the attempt rule; record appends
    a single line with the fixed schema.
After: exit code 0/1/2; the ledger file is append-only.

Fixed schema keys (9): ts, by, a, modo, resultado, error, providerInstanceId,
    mensaje_id, nota.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


# Load thread_id by path so the AST of import-statement matching reaches it.
# This is NOT a package import: it is a path-resolved exec_module call that
# registers the module in sys.modules before executing it.
# If the load fails, the error is captured and stored so callers can handle it.
_THREAD_ID_PATH = Path(__file__).resolve().parent / "thread_id.py"
_thread_id_module: object | None = None
_thread_id_load_error: Exception | None = None

try:
    _spec = importlib.util.spec_from_file_location("thread_id", _THREAD_ID_PATH)
    _candidate = importlib.util.module_from_spec(_spec)
    sys.modules["thread_id"] = _candidate
    _spec.loader.exec_module(_candidate)
    if not callable(getattr(_candidate, "has_mcp_prefix", None)):
        raise ImportError("thread_id.py no define has_mcp_prefix")
    # Published only after a COMPLETE load: a failed load leaves it None.
    _thread_id_module = _candidate
except Exception as _exc:  # any load failure must fail closed, never a Traceback
    _thread_id_load_error = _exc
finally:
    sys.modules.pop("thread_id", None)


def _get_has_mcp_prefix():
    """Return the has_mcp_prefix function or None if the module failed to load.

    Before: nothing.
    During: reads the module published by the load block above.
    After: returns the function, or None when the load failed (the cause is in
        _thread_id_load_error). Never raises.
    """
    if _thread_id_module is not None:
        return _thread_id_module.has_mcp_prefix
    return None


def _load_failure_message() -> str:
    """Build the stdout cause for a failed load of the shared module.

    Before: _get_has_mcp_prefix() returned None.
    During: formats the stored load error.
    After: returns a one-line message naming scripts/flight/thread_id.py.
    """
    return (
        "error de entorno: no se pudo cargar scripts/flight/thread_id.py ("
        + repr(_thread_id_load_error)
        + ")"
    )


# Valid modes from t3_thread_send scheme (N4).
VALID_MODES: frozenset[str] = frozenset({"auto", "queue", "steer", "restart"})

# Valid result values (P-N3b).
VALID_RESULTADOS: frozenset[str] = frozenset(
    {"enviado", "parent_not_active", "thread_not_found", "error"}
)

# The fixed schema keys (N3).
FIXED_KEYS: frozenset[str] = frozenset(
    {
        "ts",
        "by",
        "a",
        "modo",
        "resultado",
        "error",
        "providerInstanceId",
        "mensaje_id",
        "nota",
    }
)


def _now_iso() -> str:
    """Current UTC time as ISO 8601 string with seconds precision.

    Before: nothing.
    During: queries the system clock.
    After: returns a timestamp string (P-N3a: always from the helper clock).
    """
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_ledger_lines(path: Path) -> tuple[list[str], bool]:
    """Read all lines from a ledger file, skipping non-JSON lines.

    Before: path points to a ledger file that may or may not exist, may be empty,
        may contain non-JSON lines, may lack a final newline, and may be non-UTF-8.
    During: reads the file, splits by lines (splitlines handles trailing no-newline),
        parses each line as JSON, keeps track of read and parse errors.
        Catches UnicodeDecodeError separately from OSError.
    After: returns (valid_records, file_readable). valid_records is a list of dicts;
        file_readable is False if the file could not be opened or read at all.
    """
    if not path.exists():
        return [], True  # nonexistent is readable (advisory)

    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return [], False  # non-UTF-8 = illegible
    except OSError:
        return [], False  # cannot read = illegible

    records: list[dict] = []
    for line_raw in raw.splitlines():
        line_raw = line_raw.strip()
        if not line_raw:
            continue
        try:
            obj = json.loads(line_raw)
            if isinstance(obj, dict):
                records.append(obj)
        except (json.JSONDecodeError, ValueError):
            # Non-JSON lines are silently ignored for counting purposes.
            continue

    return records, True


def cmd_check(
    ledger_path: Path, by: str, mensaje_id: str, a: str, modo: str
) -> tuple[int, str]:
    """Validate whether a send is authorized based on the ledger.

    Before: the ledger exists (or not), by, mensaje_id, a, and modo are provided.
    During: validates the prefix of `a` using the shared module (must start with
        "mcp:"); validates `modo` is in the valid set; then reads the ledger,
        counts attempts for this mensaje_id, applies the attempt rule:
        - If the same mensaje_id has a prior "parent_not_active" -> refuse
          immediately (zero retries rule, applies before any other check).
        - If the same mensaje_id has a prior "enviado" -> authorize (ledger
          is a register, not a state machine).
        - Count failed records with resultado in {thread_not_found, error}:
          two or more -> refuse (tope de 2 fallidos).
          A resultado outside the closed vocabulary is NOT a failure.
        - Otherwise -> authorize.
        - If the ledger is missing or illegible -> authorize (advisory).
    After: returns (rc, reason) where rc is 0 (authorized), 1 (refused) or 2
        (environment error: the shared module scripts/flight/thread_id.py
        could not be loaded; the cause is in reason, nothing is read or written).
        reason explains the decision.
    """
    # Validate destination prefix and mode (rc 2 if the shared module is unavailable).
    refused = _refuse_destination_or_mode(a, modo)
    if refused is not None:
        return refused

    records, readable = _read_ledger_lines(ledger_path)

    if not readable:
        # Ledger illegible -> advisory, authorize.
        return (0, "autorizado: ledger ilegible, se autoriza (advisory)")

    # Filter records for this mensaje_id.
    matching = [r for r in records if r.get("mensaje_id") == mensaje_id]

    if not matching:
        return (0, "autorizado: sin intentos previos para este mensaje_id")

    # P-N2: parent_not_active ALWAYS blocks (zero retries), checked first.
    parent_not_active = [
        r for r in matching if r.get("resultado") == "parent_not_active"
    ]
    if parent_not_active:
        return (
            1,
            "rehusado: existe un intento previo con parent_not_active "
            "(cero reintentos)",
        )

    # Check for "enviado" after parent_not_active: prior sent is NOT terminal.
    enviados = [r for r in matching if r.get("resultado") == "enviado"]
    if enviados:
        return (0, "autorizado: ya se envio previamente para este mensaje_id")

    # Count failed attempts: only resultados in the closed vocabulary.
    failed = [
        r for r in matching if r.get("resultado") in {"thread_not_found", "error"}
    ]
    if len(failed) >= 2:
        return (
            1,
            "rehusado: tope de 2 intentos fallidos alcanzado para este mensaje_id",
        )

    # One failed attempt or unknown -> authorize a retry.
    return (0, "autorizado: se permite un reintento tras fallo")


def _refuse_destination_or_mode(a: str, modo: str) -> tuple[int, str] | None:
    """Validate the destination prefix and the send mode shared by check and record.

    Before: `a` and `modo` are strings taken from the command line.
    During: loads the shared prefix function (never raises) and checks `a`, then
        checks `modo` against VALID_MODES. Reads and writes nothing.
    After: returns None when both are valid; (2, cause) when the shared module
        cannot be loaded (environment error); (1, reason) when refused.
    """
    has_mcp = _get_has_mcp_prefix()
    if has_mcp is None:
        return (2, _load_failure_message())
    if not has_mcp(a):
        return (1, "rehusado: el destino no tiene prefijo mcp: " + repr(a))
    if modo not in VALID_MODES:
        return (1, "rehusado: modo desconocido " + repr(modo))
    return None


def cmd_record(
    ledger_path: Path,
    by: str,
    mensaje_id: str,
    a: str,
    modo: str,
    resultado: str,
    error: str = "",
    provider_instance_id: str = "",
    nota: str = "",
) -> tuple[int, str]:
    """Append a single line with fixed schema to the ledger.

    Before: by, mensaje_id, a, modo, resultado are provided and non-empty
        (by and mensaje_id are also required as CLI args).
    During: validates that the prefix of `a` has mcp:, that `modo` is in
        the valid set, that `resultado` is in the valid set, and that the
        ledger can be opened for append. Then appends one line with the
        fixed schema.
    After: returns (rc, message). rc is 0 on success, 1 on validation error,
        2 on ledger write error or when the shared module cannot be loaded
        (nothing is written in that case). The ledger is append-only (one line).

    Raises no Traceback on validation errors: returns rc 1 with the reason.
    """
    # Validate required arguments.
    if not by or not by.strip():
        return (1, "rehusado: --by es obligatorio y no puede estar vacio")
    if not mensaje_id or not mensaje_id.strip():
        return (
            1,
            "rehusado: --mensaje_id es obligatorio y no puede estar vacio",
        )

    # Validate destination prefix and mode (rc 2 if the shared module is unavailable).
    refused = _refuse_destination_or_mode(a, modo)
    if refused is not None:
        return refused

    # Validate resultado.
    if resultado not in VALID_RESULTADOS:
        return (1, "rehusado: resultado desconocido " + repr(resultado))

    # Open ledger for append.
    try:
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        # Check if file exists and is writable by attempting to open it.
        # If the file exists and is non-empty and does NOT end with \n,
        # we must append a newline first to avoid merging two JSON lines.
        ensure_newline = False
        if ledger_path.exists() and ledger_path.stat().st_size > 0:
            raw = ledger_path.read_bytes()
            if raw[-1:] != b"\n":
                ensure_newline = True

        with open(ledger_path, "a", encoding="utf-8", newline="\n") as f:
            if ensure_newline:
                f.write("\n")
            line = (
                json.dumps(
                    {
                        "ts": _now_iso(),
                        "by": by,
                        "a": a,
                        "modo": modo,
                        "resultado": resultado,
                        "error": error,
                        "providerInstanceId": provider_instance_id,
                        "mensaje_id": mensaje_id,
                        "nota": nota,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            f.write(line)
        return (0, "escrito: linea anadida al ledger")
    except OSError as exc:
        # Ledger exists but cannot be opened for append -> rc 2, no write.
        return (2, "error de entorno: no se puede anexar al ledger: " + str(exc))


def main(argv: list[str] | None = None) -> int:
    """Parse CLI arguments and dispatch to check or record.

    Before: CLI arguments are parsed from argv (or sys.argv).
    During: dispatches to cmd_check or cmd_record based on subcommand.
    After: returns exit code 0/1/2.
    """
    parser = argparse.ArgumentParser(
        description="Flight supervision ledger helper (validates and registers, never sends)."
    )
    sub = parser.add_subparsers(dest="subcommand")

    # check subcommand
    check_p = sub.add_parser(
        "check", help="Read the ledger, return authorized or refused"
    )
    check_p.add_argument(
        "--ledger", required=True, help="Path to the ledger JSONL file"
    )
    check_p.add_argument("--by", required=True, help="Actor who is checking")
    check_p.add_argument("--mensaje-id", required=True, help="The message id to check")
    check_p.add_argument("--a", required=True, help="Destination (threadId)")
    check_p.add_argument(
        "--modo", required=True, help="Send mode (auto, queue, steer, restart)"
    )

    # record subcommand
    record_p = sub.add_parser("record", help="Append a line to the ledger")
    record_p.add_argument(
        "--ledger", required=True, help="Path to the ledger JSONL file"
    )
    record_p.add_argument("--by", required=True, help="Actor recording")
    record_p.add_argument("--mensaje-id", required=True, help="The message id")
    record_p.add_argument("--a", required=True, help="Destination (threadId)")
    record_p.add_argument("--modo", required=True, help="Send mode")
    record_p.add_argument("--resultado", required=True, help="Result of the send")
    record_p.add_argument("--error", default="", help="Error description (if any)")
    record_p.add_argument(
        "--provider-instance-id", default="", help="Provider instance id"
    )
    record_p.add_argument("--nota", default="", help="Free note")

    args = parser.parse_args(argv)

    if not args.subcommand:
        parser.print_help()
        return 2

    ledger_path = Path(args.ledger)

    if args.subcommand == "check":
        rc, msg = cmd_check(ledger_path, args.by, args.mensaje_id, args.a, args.modo)
        print(msg)
        return rc

    if args.subcommand == "record":
        rc, msg = cmd_record(
            ledger_path,
            args.by,
            args.mensaje_id,
            args.a,
            args.modo,
            args.resultado,
            args.error,
            args.provider_instance_id,
            args.nota,
        )
        print(msg)
        return rc

    # Unknown subcommand.
    return 2


if __name__ == "__main__":
    sys.exit(main())
