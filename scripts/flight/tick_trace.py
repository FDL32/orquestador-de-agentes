"""Append one structured record for each coordinator heartbeat.

Before: the caller supplies an existing absolute ``--ops-dir`` and explicit
measurements; no live flight files are read.
During: validate the arguments, build schema version 2, and append one UTF-8
JSON line to the fixed ``tick_trace.jsonl`` path with one binary write;
``quota_summary`` is bounded to 200 characters and ``quota_accounts`` to 4096
characters with bounded per-account schema. A v1 record has no queue fields;
the reader represents that as ``cola_despachable`` not declared.
After: return 0 for a fully measured record, 1 for a record containing null
measurements, or 2 for usage/I/O errors, with a named stdout message except
for argparse ``--help``. Limit: one writer; simultaneous calls can
interleave, and the heartbeat is sequential.

Threat model: confia en el ops-dir; no defiende frente a un enlace simbolico
plantado por quien ya puede escribir ahi.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
import sys
from pathlib import Path
from typing import Any


TRACE_NAME = "tick_trace.jsonl"
TRACE_SCHEMA = 2
QUEUE_MOTIVES = (
    "NO_DECLARADO",
    "CADUCADO",
    "CERO",
    "SIN_BRIEF",
    "FLT_NO_DISJUNTO",
    "TOPE_ALCANZADO",
    "SIN_GO",
    "BUILDER_O_LENTE_VIVO",
    "CUPO",
    "OTRO",
)
FIELDS = (
    "coordinator",
    "roster_sha12",
    "guard_rc",
    "quota_rc",
    "quota_summary",
    "cola_despachable",
    "cola_motivo",
    "gate_rc",
    "quota_accounts",
    "destino",
)
OPTIONAL_FIELDS = FIELDS[5:]
_SHA12 = re.compile(r"[0-9a-fA-F]{12}")
_TS_WITH_OFFSET = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"
    r"(?:\.\d+)?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])"
)


class UsageError(ValueError):
    """Raised when a command-line value violates the trace contract."""


def _safe_error_text(exc: BaseException) -> str:
    """Escape line breaks before an expected error reaches stdout.

    Before: ``exc`` is an expected usage or I/O exception.
    During: convert carriage returns and line feeds to visible escape text.
    After: return one physical-line-safe error description.
    """
    return str(exc).replace("\r", r"\r").replace("\n", r"\n")


def _parser() -> argparse.ArgumentParser:
    """Build the CLI parser without defaults that could write implicitly.

    Before: no state is required.
    During: declare the mandatory output directory and explicit measurements.
    After: return a parser whose values can be validated before any I/O.
    """
    parser = argparse.ArgumentParser(
        description="Append one coordinator heartbeat trace record",
    )
    parser.add_argument("--ops-dir", required=True)
    parser.add_argument("--coordinator")
    parser.add_argument("--roster-sha12")
    parser.add_argument("--guard-rc")
    parser.add_argument("--quota-rc")
    parser.add_argument("--quota-summary")
    parser.add_argument("--cola-despachable")
    parser.add_argument("--cola-motivo")
    parser.add_argument("--gate-rc")
    parser.add_argument("--quota-accounts")
    parser.add_argument("--destino")
    parser.add_argument("--ts")
    parser.add_argument("--unmeasured", action="append", default=[])
    return parser


def _parse_rc(raw: str | None, field: str) -> int | None:
    """Parse an optional integer measurement.

    Before: ``raw`` is either absent or the literal argument value.
    During: convert only base-10 integer text.
    After: return an integer or null; raise ``UsageError`` for invalid text.
    """
    if raw is None:
        return None
    try:
        return int(raw, 10)
    except (TypeError, ValueError) as exc:
        raise UsageError(f"{field} must be an integer") from exc


def _parse_unmeasured(values: list[str]) -> dict[str, str]:
    """Parse repeatable field-reason declarations.

    Before: each value has the form ``FIELD=REASON``.
    During: validate the field against the fixed schema and preserve the
    reason verbatim after the separator.
    After: return one reason per field or raise ``UsageError``.
    """
    reasons: dict[str, str] = {}
    for value in values:
        field, separator, reason = value.partition("=")
        if not separator or field not in FIELDS or not reason:
            raise UsageError(f"--unmeasured invalido: {value}")
        reasons[field] = reason
    return reasons


def _parse_queue(args: argparse.Namespace) -> dict[str, Any]:  # noqa: C901
    """Validate optional schema-v2 queue fields.

    Before: parser values and explicit ``--unmeasured`` reasons exist.
    During: validate queue bounds, the closed motive enum and bounded JSON summary.
    After: return the five optional values, with absent fields represented as null.
    """
    queue = _parse_rc(args.cola_despachable, "cola-despachable")
    if queue is not None and queue < 0:
        raise UsageError("cola-despachable must be >= 0")
    motive = args.cola_motivo
    if motive is not None and motive not in QUEUE_MOTIVES:
        raise UsageError("cola-motivo invalido")
    gate_rc = _parse_rc(args.gate_rc, "gate-rc")
    summary = None
    if args.quota_accounts is not None:
        try:
            summary = json.loads(args.quota_accounts)
        except json.JSONDecodeError as exc:
            raise UsageError("quota-accounts must be JSON") from exc
        if (
            len(args.quota_accounts) > 4096
            or not isinstance(summary, list)
            or len(summary) > 32
        ):
            raise UsageError("quota-accounts exceeds 4096 characters or 32 accounts")
        for item in summary:
            if not isinstance(item, dict) or set(item) != {
                "cuenta",
                "calidad_medida",
                "block_pct",
                "estado_operativo",
            }:
                raise UsageError("quota-accounts entry has invalid schema")
            if not isinstance(item["cuenta"], str) or not item["cuenta"]:
                raise UsageError("quota-accounts cuenta must be a string")
            if item["calidad_medida"] not in {"OK", "STALE", "NO_MEDIDO", "RESERVA"}:
                raise UsageError("quota-accounts calidad_medida invalida")
            pct = item["block_pct"]
            if pct is not None and (
                isinstance(pct, bool)
                or not isinstance(pct, (int, float))
                or not math.isfinite(pct)
            ):
                raise UsageError("quota-accounts block_pct invalido")
            if item["estado_operativo"] not in {
                None,
                "NORMAL",
                "VIGILANCIA",
                "PREPARACION",
                "CAMBIO",
            }:
                raise UsageError("quota-accounts estado_operativo invalido")
    return {
        "cola_despachable": queue,
        "cola_motivo": motive,
        "gate_rc": gate_rc,
        "quota_accounts": summary,
        "destino": args.destino,
    }


def _parse_ts(raw: str | None) -> str:
    """Return an offset-bearing ISO-8601 timestamp with seconds.

    Before: ``raw`` is absent or a caller-supplied timestamp.
    During: use the local aware clock for omission, otherwise parse and verify
    timezone information and preserve the supplied representation.
    After: return a valid timestamp string or raise ``UsageError``.
    """
    if raw is None:
        return dt.datetime.now().astimezone().isoformat(timespec="seconds")
    if not _TS_WITH_OFFSET.fullmatch(raw):
        raise UsageError("ts must be ISO8601 with an offset and seconds")
    try:
        dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise UsageError("ts must be ISO8601 with an offset and seconds") from exc
    return raw


def _record(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    """Validate explicit inputs and build a JSON-serializable record.

    Before: parser values exist but no output path has been opened.
    During: validate directory, hashes, return codes, timestamp and reasons;
    assign null plus a reason to every omitted measurement. An empty
    ``quota_summary`` is treated as measured and therefore returns rc 0.
    After: return the record and its semantic rc (0 measured or 1 degraded).
    """
    raw_ops = str(args.ops_dir)
    ops_dir = Path(raw_ops)
    if not ops_dir.is_absolute() or not ops_dir.is_dir():
        raise UsageError("ops-dir must be an existing absolute directory")
    if args.roster_sha12 is not None and not _SHA12.fullmatch(args.roster_sha12):
        raise UsageError("roster-sha12 must be exactly 12 hexadecimal characters")
    guard_rc = _parse_rc(args.guard_rc, "guard-rc")
    quota_rc = _parse_rc(args.quota_rc, "quota-rc")
    reasons = _parse_unmeasured(args.unmeasured)
    timestamp = _parse_ts(args.ts)
    queue = _parse_queue(args)
    record: dict[str, Any] = {
        "v": TRACE_SCHEMA,
        "ts": timestamp,
        "coordinator": args.coordinator,
        "roster_sha12": args.roster_sha12,
        "guard_rc": guard_rc,
        "quota_rc": quota_rc,
        "quota_summary": (
            args.quota_summary[:200] if args.quota_summary is not None else None
        ),
        "unmeasured": {},
        **queue,
    }
    for field in FIELDS[:5]:
        if record[field] is None:
            record["unmeasured"][field] = reasons.get(field, "not_provided")
    for field in OPTIONAL_FIELDS:
        if record[field] is None and field in reasons:
            record["unmeasured"][field] = reasons[field]
    return record, int(bool(record["unmeasured"]))


def read_records(ops_dir: Path) -> list[dict[str, Any]]:
    """Read bounded trace records while preserving v1 records unchanged.

    Before: ``ops_dir`` is an existing operation directory.
    During: parse at most 256 physical records and tolerate legacy v1 omissions.
    After: return parsed records; a missing v2 queue field reads as not declared.
    """
    target = ops_dir / TRACE_NAME
    if not target.is_file():
        return []
    records = []
    for line in target.read_text(encoding="utf-8").splitlines()[-256:]:
        try:
            value = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def _append(ops_dir: Path, record: dict[str, Any]) -> None:
    """Append one complete JSONL payload to the fixed trace file.

    Before: ``ops_dir`` is an existing directory and ``record`` is validated.
    During: inspect the existing final byte, prepend LF when needed, and issue
    one ``write`` call in binary append mode to the fixed child path.
    After: the new JSON object ends in LF; ``OSError`` propagates to ``main``.
    """
    target = ops_dir / TRACE_NAME
    prefix = b""
    if target.exists():
        if not target.is_file():
            raise OSError(f"trace path is not a file: {target}")
        previous = target.read_bytes()
        if previous and previous[-1:] != b"\n":
            prefix = b"\n"
    payload = prefix + (
        json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    with target.open("ab") as handle:
        handle.write(payload)


def main(argv: list[str] | None = None) -> int:
    """Run the trace command and convert expected failures to named rc output.

    Before: ``argv`` is absent or a command-line argument list.
    During: parse and validate without opening or writing the trace file, append only after validation, and
    catch usage/I/O errors so heartbeat callers never receive a traceback.
    After: print exactly one ``TICK_TRACE`` status line and return 0, 1 or 2;
    argparse ``--help`` intentionally exits with SystemExit(0) without a
    ``TICK_TRACE`` status line.
    """
    parser = _parser()
    try:
        args = parser.parse_args(argv)
        record, rc = _record(args)
        _append(Path(args.ops_dir), record)
    except (argparse.ArgumentError, OSError, UsageError, ValueError) as exc:
        print(f"TICK_TRACE error {_safe_error_text(exc)}")
        return 2
    except SystemExit as exc:
        if exc.code == 0:
            return 0
        print("TICK_TRACE error invalid arguments")
        return 2
    status = "degraded" if rc else "ok"
    print(f"TICK_TRACE {status} {TRACE_NAME}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
