"""Close the start receipt by classifying delivered lens output."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any


class FinishError(ValueError):
    """A fail-closed finish-1 contract failure."""


_DECISION_RE = re.compile(r"\bDECISION:\s*(APPROVE|CHANGES)\b")
_ROUTE_LINE_RE = re.compile(
    r"(?m)(?:^|\s)((?:[A-Za-z]:[\\/]|(?:scripts|tests|docs|\.agent)[\\/])[^\s:]+:\d+)"
)
_READ_WORDS = frozenset({"read", "read_file", "readfile", "cat", "open_file"})
_NOT_JSON = object()


def _required_path(raw: str, *, label: str, file: bool = True) -> Path:
    """Resolve one explicit path and reject absent or unsuitable inputs."""
    if not isinstance(raw, str) or not raw.strip():
        raise FinishError(f"ruta obligatoria ausente: {label}")
    path = Path(raw).expanduser().resolve()
    if file and not path.is_file():
        raise FinishError(f"fichero inexistente: {label}: {raw}")
    if not file and not path.is_dir():
        raise FinishError(f"directorio inexistente: {label}: {raw}")
    return path


def _load_json(path: Path, *, label: str) -> Any:
    """Load one UTF-8 JSON artifact without accepting malformed data."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FinishError(f"{label} ilegible: {exc}") from exc


def _read_event(value: Any) -> bool:
    """Recognize a read/tool event without trusting declarative profile fields."""
    if isinstance(value, dict):
        event_type = str(value.get("type", "")).lower()
        name = str(value.get("name", value.get("tool", ""))).lower()
        if (
            event_type in {"tool_use", "tool_call", "tool_result", "tool"}
            and name in _READ_WORDS
        ):
            return True
        part = value.get("part")
        return isinstance(part, dict) and _read_event(part)
    if isinstance(value, list):
        return any(_read_event(item) for item in value)
    return False


def _route_evidence(text: str) -> list[str]:
    """Return verifiable-looking route:line references from delivered text."""
    return _ROUTE_LINE_RE.findall(text)


def _last_text(raw: str) -> tuple[str, bool, str | None]:
    """Extract last text and effective read evidence from JSONL or plain text."""
    lines = [
        line for line in raw.splitlines() if line.strip() and line.strip() != "[DONE]"
    ]
    if not lines:
        return "", False, None
    records = [_json_record(line) for line in lines]
    if any(record is _NOT_JSON for record in records):
        if isinstance(records[0], dict):
            return "", False, "formato mixto"
        return "\n".join(lines).rstrip(), False, None
    texts: list[str] = []
    has_read_event = any(_read_event(record) for record in records)
    for record in records:
        if not isinstance(record, dict):
            continue
        part = record.get("part")
        if isinstance(part, dict) and part.get("type") == "text":
            text = part.get("text")
            if isinstance(text, str):
                texts.append(text)
        elif record.get("type") == "text" and isinstance(record.get("text"), str):
            texts.append(record["text"])
    text = texts[-1].rstrip().removesuffix("[DONE]").rstrip() if texts else ""
    return text, has_read_event, None


def _json_record(line: str) -> Any:
    """Parse one JSONL line, returning None for a plain-text line."""
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return _NOT_JSON


def _artifact(raw: dict[str, Any]) -> dict[str, Any]:
    """Classify one delivered output artifact and produce a receipt row."""
    key = raw.get("backend_key")
    if not isinstance(key, str) or not key.strip():
        raise FinishError("artefacto sin backend_key")
    out_raw = raw.get("out_path")
    rc = raw.get("rc")
    expected_mode = raw.get("expected_mode")
    if expected_mode is not None and expected_mode not in {"LECTORA", "TEXTO"}:
        raise FinishError(f"expected_mode invalido: {expected_mode}")
    result: dict[str, Any] = {
        "backend_key": key,
        "out_path": out_raw,
        "rc": rc,
        "mode": "TEXTO",
        "vote": "NO-VOTO",
    }
    if expected_mode is not None:
        result["expected_mode"] = expected_mode
    reason = _early_artifact_reason(rc, out_raw)
    if reason is not None:
        result["reason"] = reason
        return result
    result = _read_artifact(result, out_raw)
    if (
        expected_mode is not None
        and result["mode"] != expected_mode
        and "reason" not in result
    ):
        result["vote"] = "NO-VOTO"
        result["reason"] = (
            "sin lectura" if expected_mode == "LECTORA" else "modo discrepante"
        )
    return result


def _early_artifact_reason(rc: Any, out_raw: Any) -> str | None:
    """Return a no-vote reason that needs no filesystem read."""
    if isinstance(rc, bool) or not isinstance(rc, int):
        return "rc ilegible"
    if rc == 3:
        return "stream mudo: rc 3"
    if not isinstance(out_raw, str) or not out_raw.strip():
        return "out ausente"
    return None


def _read_artifact(result: dict[str, Any], out_raw: Any) -> dict[str, Any]:
    """Read one explicit output and apply byte, mode, and decision gates."""
    out = Path(out_raw).expanduser().resolve()
    if not out.is_file():
        result["reason"] = "out ausente"
        return result
    result["out_path"] = str(out)
    try:
        raw_text = out.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        result["reason"] = f"out ilegible: {type(exc).__name__}"
        return result
    text, has_read_event, format_reason = _last_text(raw_text)
    last_text_bytes = len(text.encode("utf-8"))
    result["last_text_bytes"] = last_text_bytes
    if format_reason is not None:
        result["reason"] = format_reason
        return result
    route_evidence = _route_evidence(text)
    if route_evidence and has_read_event:
        result["mode"] = "LECTORA"
        result["read_evidence"] = route_evidence
    if last_text_bytes < 200:
        result["reason"] = "salida menor de 200 bytes"
        return result
    decision = _DECISION_RE.findall(text)
    if not decision:
        result["reason"] = "decision ausente"
        return result
    result["vote"] = decision[-1]
    return result


def _load_finish_inputs(
    ticket: str, start_receipt: str, artifacts: str
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Load and validate the start receipt and unique artifact manifest."""
    start_path = _required_path(start_receipt, label="start_receipt")
    artifacts_path = _required_path(artifacts, label="artifacts")
    start = _load_json(start_path, label="start_receipt")
    manifest = _load_json(artifacts_path, label="artifacts")
    if not isinstance(start, dict) or start.get("ticket") != ticket:
        raise FinishError("start_receipt discrepante: ticket")
    entries = manifest.get("artifacts") if isinstance(manifest, dict) else None
    if not isinstance(entries, list):
        raise FinishError("artifacts invalido: falta artifacts")
    by_key: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("backend_key"), str):
            raise FinishError("artifacts invalido: backend_key")
        if entry["backend_key"] in by_key:
            raise FinishError(f"artifacts duplicado: {entry['backend_key']}")
        by_key[entry["backend_key"]] = entry
    return start, by_key


def _finish_lenses(
    start_lenses: Any, artifacts: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Preserve every start row and append finish-1 evidence."""
    if not isinstance(start_lenses, list):
        raise FinishError("start_receipt invalido: falta lenses")
    result_lenses: list[dict[str, Any]] = []
    for start_lens in start_lenses:
        if not isinstance(start_lens, dict) or not isinstance(
            start_lens.get("backend_key"), str
        ):
            raise FinishError("start_receipt invalido: lente")
        key = start_lens["backend_key"]
        result = dict(start_lens)
        if key not in artifacts:
            result.update({"mode": "TEXTO", "vote": "NO-VOTO", "reason": "out ausente"})
        else:
            result.update(_artifact(artifacts[key]))
        result_lenses.append(result)
    return result_lenses


def finish_ticket(
    *, ticket: str, start_receipt: str, artifacts: str, output_receipt: str
) -> Path:
    """Read start state and explicit .out artifacts, then write finish-1 receipt.

    Before: all paths are explicit; the start receipt and artifact manifest are
        UTF-8 JSON objects for the same ticket.
    During: each output is classified from its delivered bytes and events; no
        scorecard metadata, quorum, or dispatcher behavior is recomputed.
    After: a complete JSON receipt is written at the requested path. Missing,
        short, mute, unreadable, or undecidable output is NO-VOTO; round_status
        remains INCOMPLETA with quorum NO_MEDIDO until finish-2 supplies it.
    """
    if not isinstance(ticket, str) or not ticket.strip():
        raise FinishError("ticket obligatorio ausente")
    output_path = Path(output_receipt).expanduser().resolve()
    if not output_receipt.strip():
        raise FinishError("ruta obligatoria ausente: output_receipt")
    start, by_key = _load_finish_inputs(ticket, start_receipt, artifacts)
    result_lenses = _finish_lenses(start.get("lenses"), by_key)
    planned_keys = {
        row["backend_key"] for row in start.get("lenses", []) if isinstance(row, dict)
    }
    unplanned = sorted(key for key in by_key if key not in planned_keys)
    output = {
        "ticket": ticket,
        "tip": start.get("tip"),
        "lenses": result_lenses,
        "unplanned_artifacts": unplanned,
        "round_status": "INCOMPLETA",
        "quorum": {
            "status": "NO_MEDIDO",
            "reason": "check_loop_execution pendiente en finish-2",
        },
    }
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(output, indent=2), encoding="utf-8", newline="\n"
        )
    except OSError as exc:
        raise FinishError(f"recibo de finish ilegitible: {exc}") from exc
    return output_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticket", required=True)
    parser.add_argument("--start-receipt", required=True)
    parser.add_argument("--artifacts", required=True)
    parser.add_argument("--output-receipt", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        receipt = finish_ticket(**vars(_parser().parse_args(argv)))
    except FinishError as exc:
        print(f"FINISH_FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"FINISH_OK: {receipt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
