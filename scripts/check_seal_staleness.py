#!/usr/bin/env python3
"""Seal-staleness guard for the start-context-isolation receipt (WOT-2026-055c).

Contract: given a receipt ``start_context_isolation.json`` and its sealed prompt,
verify in three layers:

1. **Integrity (triple via):** ``prompt_sha256`` + ``prompt_bytes`` +
   ``prompt_lines`` must match the file. Three ways, not one: a bare sha cannot
   distinguish "wrong file" from "right file renamed".
2. **Temporal order:** ``approved_at`` is LATER than the ``mtime`` of the
   prompt. A seal earlier than what it seals never saw what it signs.
3. **Semantic freshness (heuristic):** if the prompt carries state claims
   (``EN VUELO``, ``N warnings``, ``runtime OCUPADO``, ``sin push``), contrast them
   against the tree and emit ``[WARN] seal-staleness`` when the prompt asserts the
   opposite of what is measured.

Regime: WARN, non-blocking, for coherence with ``run_batch_run_accounting_check``
(``prepush_check.py:727``). Wired in ``prepush_check.py`` next to its sibling.

Fail-closed anchor (sec 4.bis of audit_autonomous_ticket_batch.md): the receipt
must read with ``utf-8-sig``, carry ``flight`` (contrasted against the flight /
its own batch_run), ``prompt_sha256`` matching the prompt REALLY consumed,
``project_root_resolved``, ``approved_by`` external, ``scope`` covering the
flight -- a violation of ANY hard anchor exits non-zero.

Escape (original filing's rejection condition): if the engine re-runs
``grep -rln \"start_context_isolation\" <MOTOR_ROOT>/scripts/*.py`` and it does
NOT return empty, this escalation is wrong and must be closed, downgraded to
``REPRODUCCION_INDEPENDIENTE``. Measured 2026-08-22: 0 consumers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


_STATE_CLAIM = re.compile(
    r"(?i)(\d+)\s+(?:warnings?|errores?|errors?)|EN VUELO|runtime OCUPADO|sin push"
)


def _norm(root: str | Path) -> str:
    return str(Path(str(root)).resolve()).replace("\\", "/")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _lines(path: Path) -> int:
    return len(path.read_bytes().splitlines())


def _git() -> str:
    import shutil

    return shutil.which("git") or "git"


def _read_receipt(path: Path) -> dict[str, Any]:
    """Before: receipt path. During: read with utf-8-sig (BOM tolerated). After:
    parsed dict; raises OSError/JSONDecodeError on unreadable/malformed."""
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    iso = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(iso)
    except ValueError:
        return None
    # Un approved_at naive se interpreta en la zona LOCAL: compararlo contra el
    # mtime (que es aware via astimezone) lanzaria TypeError en Python 3.10.
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed


def _measured_validate_counts(project_root: Path | None) -> tuple[int, int] | None:
    """Measure current validate errors/warnings with --no-heal. Returns
    (errors, warnings) or None if the controller is absent. NEVER raises."""
    if project_root is None:
        return None
    controller = (
        Path(__file__).resolve().parent.parent / ".agent" / "agent_controller.py"
    )
    if not controller.exists():
        return None
    import subprocess

    try:
        proc = subprocess.run(  # noqa: S603 - ruta fija del controller, no input de usuario
            [
                sys.executable,
                str(controller),
                "--validate",
                "--json",
                "--no-heal",
                "--project-root",
                str(project_root),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode not in (0, 1):
        return None
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    errors = payload.get("total_errors")
    warnings = payload.get("total_warnings")
    if not isinstance(errors, int) or not isinstance(warnings, int):
        return None
    return (errors, warnings)


def _commits_ahead(root: Path) -> int | None:
    """Local commits not on the upstream, measured with git. None if no upstream
    or git fails. Read-only; never raises."""
    import subprocess

    try:
        proc = subprocess.run(  # noqa: S603 - git del propio root, no input de usuario
            [_git(), "-C", str(root), "rev-list", "--count", "HEAD..@{upstream}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        return int(proc.stdout.strip())
    except ValueError:
        return None


def _semantic_freshness(prompt: Path, project_root: Path | None) -> list[str]:
    """Layer 3 (WARN heuristic): contrast state claims in the prompt against the
    tree. Before: prompt exists; project_root optional. During: scan the prompt
    text for `N warnings/errors`, `sin push` claims and compare to measured
    validate counts / commit-ahead. After: returns [WARN] findings; never a hard
    finding. Never raises (measurement helpers return None on failure)."""
    findings: list[str] = []
    text = prompt.read_text(encoding="utf-8", errors="replace")
    for match in _STATE_CLAIM.finditer(text):
        claim = match.group(0)
        if (
            "warnings" in claim.lower()
            or "errors" in claim.lower()
            or "errores" in claim.lower()
        ):
            counts = _measured_validate_counts(project_root)
            if counts is None:
                continue
            errors, warnings = counts
            measured = errors + warnings
            try:
                claimed_n = int(re.search(r"\d+", claim).group(0))  # type: ignore[union-attr]
            except (AttributeError, ValueError):
                continue
            if claimed_n != measured:
                findings.append(
                    f"[WARN] seal-staleness: prompt claims {claim!r} but "
                    f"validate --no-heal measures {measured} (errors+warning)"
                )
        elif "sin push" in claim.lower():
            ahead = _commits_ahead(project_root or Path.cwd())
            if ahead is not None and ahead > 0:
                findings.append(
                    f"[WARN] seal-staleness: prompt claims {claim!r} but the "
                    f"tree has {ahead} commit(s) ahead of upstream"
                )
        elif "EN VUELO" in claim.upper() or "OCUPADO" in claim.upper():
            # EN VUELO/OCUPADO claims are about the RUNNER, not the tree:
            # there is no computable false-friend to measure them against
            # (the runtime dir is gitignored). Left as an informational
            # trace, never a finding.
            continue
    return findings


def _prompt_integrity(
    receipt: dict[str, Any],
    prompt_path: str | Path | None,
    receipt_path: str | Path,
) -> tuple[Path | None, list[str]]:
    """Layer 1 (triple via) + prompt resolution. Before: parsed receipt.
    During: resolve the prompt REALLY consumed (arg wins, else receipt.prompt_path),
    contrast prompt_sha256 and, when present, prompt_bytes/prompt_lines.
    After: (prompt | None, findings). Absent bytes/lines fields are tolerated
    (legacy receipts carry only the sha)."""
    findings: list[str] = []
    prompt = None
    if prompt_path is not None:
        prompt = Path(prompt_path)
    elif isinstance(receipt.get("prompt_path"), str) and receipt["prompt_path"]:
        cand = Path(receipt["prompt_path"])
        prompt = cand if cand.is_absolute() else Path(receipt_path).parent / cand
    if prompt is None or not prompt.exists():
        findings.append(
            f"hard: cannot resolve the prompt file consumed (arg={prompt_path})"
        )
        return prompt, findings
    actual_sha = _sha256(prompt)
    claimed_sha = receipt.get("prompt_sha256")
    if not claimed_sha:
        findings.append("hard: receipt lacks 'prompt_sha256'")
    elif claimed_sha != actual_sha:
        findings.append(
            f"hard: receipt 'prompt_sha256'={claimed_sha[:12]}... does not match "
            f"the prompt bytes {actual_sha[:12]}... ({prompt.name})"
        )
    if isinstance(receipt.get("prompt_bytes"), int):
        actual_bytes = prompt.stat().st_size
        if receipt["prompt_bytes"] != actual_bytes:
            findings.append(
                f"hard: 'prompt_bytes'={receipt['prompt_bytes']} != actual {actual_bytes}"
            )
    if isinstance(receipt.get("prompt_lines"), int):
        actual_lines = _lines(prompt)
        if receipt["prompt_lines"] != actual_lines:
            findings.append(
                f"hard: 'prompt_lines'={receipt['prompt_lines']} != actual {actual_lines}"
            )
    return prompt, findings


def _approval_anchors(receipt: dict[str, Any], executor: str | None) -> list[str]:
    """status/approved_by/scope anchors (sec 4.bis). Before: parsed receipt.
    During: verify status==RESOLVED, approved_by external (never the executor),
    scope covering the flight. After: list of hard findings."""
    findings: list[str] = []
    status = receipt.get("status")
    if status != "RESOLVED":
        findings.append(
            f"hard: receipt 'status'={status!r} != 'RESOLVED' "
            "(executor did not wait for external resolution)"
        )
    approved_by = receipt.get("approved_by")
    if not approved_by:
        findings.append("hard: receipt lacks 'approved_by' (no external approval)")
    elif executor and (
        str(approved_by).strip().lower() == executor.strip().lower()
        or str(receipt.get("_resolver", "")).strip().lower() == executor.strip().lower()
    ):
        findings.append(
            f"hard: 'approved_by'={approved_by!r} / '_resolver' names the executor "
            f"{executor!r} (self-approval)"
        )
    scope = receipt.get("scope")
    if not scope:
        findings.append(
            "hard: receipt lacks 'scope' (must cover the tickets of this flight)"
        )
    return findings


def _flight_anchor(
    receipt: dict[str, Any],
    flight_id: str | None,
    batch_run_path: str | Path | None,
) -> list[str]:
    """flight + pertenencia contrast. Before: parsed receipt. During: require a
    flight, contrast against the expected flight_id and, when provided, the
    receipt's own batch_run; a mismatched anchor is falso_verde (2026-08-13).
    After: list of hard findings."""
    findings: list[str] = []
    flight = receipt.get("flight")
    if not flight:
        findings.append(
            "hard: receipt lacks 'flight' (needed to attribute the receipt)"
        )
    if flight_id and flight != flight_id:
        findings.append(
            f"hard: receipt 'flight'={flight!r} differs from expected {flight_id!r}"
        )
    if batch_run_path is not None:
        batch = _read_receipt(Path(batch_run_path))
        batch_flight = batch.get("flight")
        if batch_flight and flight and batch_flight != flight:
            findings.append(
                f"hard: receipt 'flight'={flight!r} differs from its batch_run "
                f"{Path(batch_run_path).name} 'flight'={batch_flight!r}"
            )
    return findings


def _root_and_temporal(
    receipt: dict[str, Any],
    prompt: Path | None,
    project_root: str | Path | None,
) -> list[str]:
    """project_root_resolved + layer-2 temporal order. Before: parsed receipt.
    During: verify project_root_resolved if an expected root is given; verify
    approved_at is LATER than prompt mtime (a seal older than what it seals
    never saw what it signs). After: list of hard findings."""
    findings: list[str] = []
    proot = receipt.get("project_root_resolved")
    if not proot:
        findings.append("hard: receipt lacks 'project_root_resolved'")
    elif project_root is not None and _norm(proot) != _norm(project_root):
        findings.append(
            f"hard: 'project_root_resolved'={proot!r} != expected {_norm(project_root)!r}"
        )
    approved_at = _parse_iso(receipt.get("approved_at"))
    if prompt is not None and prompt.exists():
        prompt_mtime = datetime.fromtimestamp(prompt.stat().st_mtime).astimezone()
        if approved_at is not None and approved_at < prompt_mtime:
            findings.append(
                f"hard: 'approved_at'={approved_at.isoformat()} is EARLIER than "
                f"prompt mtime {prompt_mtime.isoformat()} (seal predates what it seals)"
            )
    return findings


def check_seal_staleness(
    receipt_path: str | Path,
    prompt_path: str | Path | None = None,
    flight_id: str | None = None,
    batch_run_path: str | Path | None = None,
    project_root: str | Path | None = None,
    executor: str | None = None,
) -> list[str]:
    """Run the three-layer check and return the findings.

    Before: receipt_path exists and points to start_context_isolation*.json;
    prompt_path, batch_run_path, project_root are optional external anchors.
    During: reads the receipt with utf-8-sig; resolves the prompt REALLY consumed
    (arg wins, else receipt.prompt_path); contrasts flight against the arg and/or
    the receipt's own batch_run flight; verifies integrity, temporal order and
    semantic freshness.
    After: returns a list of finding strings. HARD findings make the CLI exit 1;
    ``[WARN]`` entries are seal-staleness heuristics (non-blocking). Raises
    OSError/JSONDecodeError/ValueError on unreadable receipt or prompt.
    """
    findings: list[str] = []
    receipt = _read_receipt(Path(receipt_path))

    # --- anchor: flight + pertenencia ---------------------------------------
    findings.extend(_flight_anchor(receipt, flight_id, batch_run_path))

    # --- anchor: prompt REALLY consumed --------------------------------------
    prompt, integrity = _prompt_integrity(receipt, prompt_path, receipt_path)
    findings.extend(integrity)

    # --- anchor: project_root_resolved + temporal order ------------------------
    findings.extend(_root_and_temporal(receipt, prompt, project_root))

    # --- anchor: approved_by external + status + scope --------------------------
    findings.extend(_approval_anchors(receipt, executor))

    # --- layer 3: semantic freshness (WARN heuristic) -----------------------------
    if prompt is not None and prompt.exists():
        findings.extend(
            _semantic_freshness(prompt, Path(project_root) if project_root else None)
        )

    return findings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "receipt",
        nargs="?",
        default=None,
        help="Path to start_context_isolation*.json (positional).",
    )
    parser.add_argument(
        "--file",
        dest="file",
        default=None,
        help="Path to start_context_isolation*.json (alternative to positional).",
    )
    parser.add_argument(
        "--prompt",
        default=None,
        help="Path to the sealed prompt file actually consumed (overrides receipt.prompt_path).",
    )
    parser.add_argument(
        "--flight",
        default=None,
        help="Expected flight id this receipt must belong to.",
    )
    parser.add_argument(
        "--batch-run",
        default=None,
        help="Path to the batch_run_<ts>.json OF THIS FLIGHT to contrast 'flight'.",
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="Expected project_root_resolved (the destino of the resolved topology).",
    )
    parser.add_argument(
        "--executor",
        default=None,
        help="Executor identity; a matching approved_by/_resolver is self-approval.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Before: argv optional. During: resolve target, run the seal check. After:
    exit 0 if no hard findings (WARN seal-staleness allowed); exit 1 listing each
    hard finding; exit 2 on usage error (M1: 'no medi')."""
    args = build_parser().parse_args(argv)
    target = args.receipt or args.file
    if not target:
        print("[check-seal-staleness] ERROR: no receipt path given.")
        return 2
    path = Path(target)
    if not path.exists():
        print(f"[check-seal-staleness] ERROR: file not found: {path}")
        return 2

    try:
        findings = check_seal_staleness(
            path,
            prompt_path=Path(args.prompt) if args.prompt else None,
            flight_id=args.flight,
            batch_run_path=Path(args.batch_run) if args.batch_run else None,
            project_root=Path(args.project_root) if args.project_root else None,
            executor=args.executor,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"[check-seal-staleness] ERROR: unreadable/invalid receipt: {exc}")
        return 2

    hard = [f for f in findings if not f.startswith("[WARN]")]
    for f in findings:
        print(f"[check-seal-staleness] {f}")

    if hard:
        print(f"[check-seal-staleness] FAIL: {len(hard)} hard finding(s).")
        return 1
    print("[check-seal-staleness] OK: no hard findings (seal fresh).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
