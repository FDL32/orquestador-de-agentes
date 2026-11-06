"""Close the start receipt by classifying delivered lens output."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any


class FinishError(ValueError):
    """A fail-closed finish-1 contract failure."""


_DECISION_RE = re.compile(r"\bDECISION:\s*(APPROVE|CHANGES)\b")
_ROUTE_LINE_RE = re.compile(
    r"(?m)(?:^|\s)((?:[A-Za-z]:[\\/]|(?:scripts|tests|docs|\.agent)[\\/])[^\r\n:]*:\d+)"
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
    """Return route:line evidence by shape, without checking filesystem existence."""
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
        plain_lines = [
            line
            for line, record in zip(lines, records, strict=True)
            if record is _NOT_JSON
        ]
        return "\n".join(plain_lines).rstrip(), False, None
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
    """Parse JSONL, returning the private ``_NOT_JSON`` sentinel on plain text."""
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
    for field in ("commit_sha", "family", "model_effective", "substituted"):
        if field in raw:
            result[field] = raw[field]
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
    if rc < 0:
        return "rc negativo"
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


_START_PROTECTED_FIELDS = (
    "backend_key",
    "commit_sha",
    "family",
    "model_effective",
    "expected_mode",
    "substituted",
)


def _merge_start_and_artifact(
    start_lens: dict[str, Any], artifact: dict[str, Any]
) -> dict[str, Any]:
    """Keep start identity and policy authoritative while rejecting contradictions.

    ``_artifact`` emits backend_key, out_path, rc, mode, vote, expected_mode,
    commit_sha, family, model_effective, substituted, last_text_bytes,
    read_evidence, and reason. Start rows may carry backend_key, role, status,
    model_requested, model_effective, family, commit_sha, expected_mode,
    substituted, and rc. The intersection is exactly
    ``_START_PROTECTED_FIELDS``: every intersecting key is protected here;
    ``substituted`` uses the monotone fail-closed rule. The remaining keys are
    artifact-owned evidence and may be supplied by the manifest.
    """
    discrepancy = False
    for field in _START_PROTECTED_FIELDS:
        if field == "substituted":
            continue
        if (
            field in start_lens
            and field in artifact
            and start_lens[field] != artifact[field]
        ):
            discrepancy = True
        if field in start_lens:
            artifact[field] = start_lens[field]
    if "substituted" in _START_PROTECTED_FIELDS and (
        "substituted" in start_lens or "substituted" in artifact
    ):
        artifact["substituted"] = (
            "substituted" in start_lens and start_lens["substituted"] is not False
        ) or ("substituted" in artifact and artifact["substituted"] is not False)
    if discrepancy:
        artifact.update(
            {"vote": "NO-VOTO", "reason": "manifiesto discrepante con start"}
        )
    return artifact


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
        start_rc = start_lens.get("rc")
        if key not in artifacts:
            result.update({"mode": "TEXTO", "vote": "NO-VOTO", "reason": "out ausente"})
        else:
            result.update(
                _merge_start_and_artifact(start_lens, _artifact(artifacts[key]))
            )
        if "rc" in start_lens:
            result["rc"] = start_rc
        result_lenses.append(result)
    return result_lenses


def _validate_guard_receipt(receipt: dict[str, Any], commit_sha: str) -> str | None:
    """Validate one guard receipt's identity and emitted field types."""
    if receipt.get("commit_sha") != commit_sha:
        return "recibo del guard de otro commit"
    if not isinstance(receipt.get("ok"), bool):
        return "veredicto del guard con tipo invalido"
    if "exempt" in receipt and not isinstance(receipt["exempt"], bool):
        return "recibo del guard con tipo invalido"
    if (
        "debt" in receipt
        and receipt["debt"] is not None
        and not isinstance(receipt["debt"], str)
    ):
        return "recibo del guard con tipo invalido"
    return None


def _guard_receipt(
    stdout: str, commit_sha: str
) -> tuple[dict[str, Any] | None, str | None]:
    """Extract and minimally validate the guard receipt from subprocess stdout."""
    receipts: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict) or "loop_exec_receipt" not in value:
            continue
        receipt = value["loop_exec_receipt"]
        if not isinstance(receipt, dict):
            return None, "recibo del guard con tipo invalido"
        receipts.append(receipt)
    if len(receipts) > 1:
        return None, "recibos multiples ambiguos"
    if not receipts:
        return None, "recibo del guard ausente"
    receipt = receipts[0]
    error = _validate_guard_receipt(receipt, commit_sha)
    if error is not None:
        return None, error
    return receipt, None


def _run_loop_guard(
    *, project_root: str, commit_sha: str, loop_id: str | None
) -> tuple[int, dict[str, Any] | None, str | None]:
    """Run check_loop_execution with explicit CLI inputs and capture its receipt."""
    guard = Path(__file__).resolve().parents[1] / "check_loop_execution.py"
    command = [
        sys.executable,
        str(guard),
        "--project-root",
        project_root,
        "--commit-sha",
        commit_sha,
    ]
    if loop_id is not None:
        command.extend(["--loop-id", loop_id])
    try:
        completed = subprocess.run(  # noqa: S603 - fixed executable and explicit arguments
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=900,
        )
    except subprocess.TimeoutExpired:
        return 1, None, "timeout del guard"
    except OSError as exc:
        return 1, None, f"error de ejecucion del guard: {type(exc).__name__}"
    receipt, error = _guard_receipt(completed.stdout, commit_sha)
    if error is not None:
        return completed.returncode, None, error
    return completed.returncode, receipt, None


def _valid_approve_count(result_lenses: list[dict[str, Any]], commit_sha: str) -> int:
    """Count distinct, current, non-substituted APPROVE artifact rows."""
    valid: list[dict[str, Any]] = []
    for row in result_lenses:
        if row.get("vote") != "APPROVE" or row.get("backend_key") in {
            item.get("backend_key") for item in valid
        }:
            continue
        if row.get("commit_sha", commit_sha) != commit_sha:
            continue
        if row.get("substituted") is True:
            continue
        expected_mode = row.get("expected_mode")
        if expected_mode is not None and row.get("mode") != expected_mode:
            continue
        valid.append(row)
    distinct: list[dict[str, Any]] = []
    for row in valid:
        if all(
            row.get(field) != existing.get(field)
            for existing in distinct
            for field in ("family", "model_effective")
            if field in row and field in existing
        ):
            distinct.append(row)
    return len(distinct)


def _guard_non_measurement_reason(receipt: dict[str, Any]) -> str | None:
    """Return the fail-closed reason for an exempt or debt-waived guard."""
    if receipt.get("exempt") is True:
        return "guard OK por exencion"
    if receipt.get("debt") is not None:
        return "guard OK por deuda historica"
    return None


def _quorum_result(
    start: dict[str, Any],
    *,
    result_lenses: list[dict[str, Any]],
    project_root: str | None,
    loop_id: str | None,
    commit_sha: str | None,
) -> tuple[str, dict[str, Any]]:
    """Return round status and a fail-closed quorum result."""
    quorum: dict[str, Any] = {"status": "NO_MEDIDO"}
    if not isinstance(project_root, str) or not project_root.strip():
        quorum["reason"] = "sin project-root"
        return "INCOMPLETA", quorum
    if not isinstance(commit_sha, str) or not commit_sha.strip():
        quorum["reason"] = "sin commit-sha"
        return "INCOMPLETA", quorum
    if isinstance(loop_id, str) and not loop_id.strip():
        quorum["reason"] = "loop-id vacio"
        return "INCOMPLETA", quorum
    start_tip = start.get("tip")
    if start_tip is not None and start_tip != commit_sha:
        quorum.update(
            {"status": "FALLO_RC", "reason": "commit-sha discrepante con start_receipt"}
        )
        return "INCOMPLETA", quorum
    rc, receipt, error = _run_loop_guard(
        project_root=project_root, commit_sha=commit_sha, loop_id=loop_id
    )
    if error is not None:
        quorum.update({"status": "FALLO_RC", "reason": error})
        return "INCOMPLETA", quorum
    quorum["guard_receipt"] = receipt
    if rc != 0:
        quorum.update({"status": "FALLO_RC", "reason": f"guard rc {rc}"})
        return "INCOMPLETA", quorum
    if not receipt["ok"]:
        quorum.update({"status": "FALLO_RC", "reason": "guard veredicto no OK"})
        return "INCOMPLETA", quorum
    override_reason = _guard_non_measurement_reason(receipt)
    if override_reason is not None:
        quorum.update({"status": "NO_MEDIDO", "reason": override_reason})
        return "INCOMPLETA", quorum
    valid_approves = _valid_approve_count(result_lenses, commit_sha)
    if valid_approves < 2:
        quorum.update(
            {
                "status": "NO_MEDIDO",
                "reason": f"menos de 2 APPROVE de lentes distintas: {valid_approves}",
            }
        )
        return "INCOMPLETA", quorum
    quorum["status"] = "OK"
    quorum["reason"] = "guard OK"
    return "COMPLETA", quorum


def _write_receipt(output_path: Path, output: dict[str, Any]) -> Path:
    """Write one finish receipt and convert filesystem failures to FinishError."""
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(output, indent=2), encoding="utf-8", newline="\n"
        )
    except OSError as exc:
        raise FinishError(f"recibo de finish ilegitible: {exc}") from exc
    return output_path


def finish_ticket(
    *,
    ticket: str,
    start_receipt: str,
    artifacts: str,
    output_receipt: str,
    project_root: str | None = None,
    loop_id: str | None = None,
    commit_sha: str | None = None,
) -> Path:
    """Read start state and artifacts, then write the finish receipt.

    Before: all paths are explicit; the start receipt and artifact manifest are
        UTF-8 JSON objects for the same ticket.
    During: each output is classified from its delivered bytes and events. When
        project_root and commit_sha are supplied, the optional loop_id is passed
        to the guard subprocess, which owns quorum evaluation.
    After: a complete JSON receipt is written at the requested path. Missing,
        short, mute, unreadable, or undecidable output is NO-VOTO; round_status
        remains INCOMPLETA with quorum NO_MEDIDO when the guard inputs are absent;
        with both inputs it evaluates lens votes and reflects the guard's rc and
        validated receipt. Execution quorum is delegated to the guard; finish
        does not recompute that execution quorum.
    """
    if not isinstance(ticket, str) or not ticket.strip():
        raise FinishError("ticket obligatorio ausente")
    if not isinstance(output_receipt, str) or not output_receipt.strip():
        raise FinishError("ruta obligatoria ausente: output_receipt")
    output_path = Path(output_receipt).expanduser().resolve()
    try:
        start, by_key = _load_finish_inputs(ticket, start_receipt, artifacts)
        result_lenses = _finish_lenses(start.get("lenses"), by_key)
        planned_keys = {
            row["backend_key"]
            for row in start.get("lenses", [])
            if isinstance(row, dict)
        }
        unplanned = sorted(key for key in by_key if key not in planned_keys)
        round_status, quorum = _quorum_result(
            start,
            result_lenses=result_lenses,
            project_root=project_root,
            loop_id=loop_id,
            commit_sha=commit_sha,
        )
        output = {
            "ticket": ticket,
            "tip": start.get("tip"),
            "lenses": result_lenses,
            "unplanned_artifacts": unplanned,
            "round_status": round_status,
            "quorum": quorum,
        }
    except FinishError as exc:
        _write_receipt(
            output_path,
            {
                "ticket": ticket,
                "round_status": "INCOMPLETA",
                "quorum": {"status": "NO_MEDIDO", "reason": str(exc)},
                "error": str(exc),
            },
        )
        raise
    return _write_receipt(output_path, output)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticket", required=True)
    parser.add_argument("--start-receipt", required=True)
    parser.add_argument("--artifacts", required=True)
    parser.add_argument("--output-receipt", required=True)
    parser.add_argument(
        "--project-root",
        help="repo_destino, NO el repo_motor: con el motor da 0 lentes sin aviso",
    )
    parser.add_argument("--loop-id")
    parser.add_argument("--commit-sha")
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
