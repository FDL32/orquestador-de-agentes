#!/usr/bin/env python3
"""Closeout guard: every canonical-suite SKIP must carry its motive.

WOT-2026-074x (DoD b). Origin (G2/G3, destino Crear_Texto_LLM 2026-09-18): with
its audited surface missing, an audit test SKIPPED silently ("4 passed, 2
skipped" -- indistinguishable from an audit that inspected 0 elements). The
seal (``.agent/runtime/pytest-safe/last-run.json``) recorded ``skipped``
WITHOUT motive, so a consumer could not tell "skipped by platform" from
"skipped because the surface it was going to audit was not there": a silent
deletion turned into a fabricated finding. NON-GOAL: banning ``pytest.skip``
is explicitly out of scope (legit on fresh clones) -- only the REASON is made
mandatory and visible.

Mechanism (the seal set):
- ``pytest.ini`` addopts carries ``-rs`` so the canonical run prints a short
  summary of skipped tests WITH their reasons; ``run_pytest_safe.py`` captures
  that stdout into ``.agent/runtime/pytest-safe/last-run.log``.
- This guard cross-checks the seal (``last-run.json.skipped``), that log and a
  DECLARATION file (``skip-declarations.json``) that classifies every skip of
  the sealed run::

      {
          "seal_started_at": "<last-run.json.started_at>",
          "declared_at": "<iso>",
          "declared_by": "<actor>",
          "classes": {"platform": 0, "surface-missing": 0, "other": 0},
          "notes": "<non-empty when surface-missing > 0>",
      }

- The obligation lives at closeout: ``scripts/prepush_check.py`` runs this
  guard as a blocking closeout check, so a close cannot be pushed with
  unrecorded or undeclared skips (the ticket's "el contrato de cierre obliga a
  declararlos", enforced by a wired check instead of prose).
- The derived annex ``skip-report.json`` (structured reasons per skip) is
  regenerated on every run so the motives travel as data, not only as log
  text.

Docstring-as-spec:
    Before: ``project_root`` resolves the pytest-safe dir; a seal may or may
        not exist (fresh clone / no suite yet).
    During: reads ``last-run.json`` + ``last-run.log`` (read-only on both);
        parses ``SKIPPED [N] path:line: reason`` lines; cross-checks the count
        against the seal and the log's own summary; validates the declaration
        against the sealed run. Writes ONLY the derived ``skip-report.json``.
    After: report dict with verdict ``pass|fail|skip``; CLI exits 0
        (pass/skip), 1 (fail), 2 (usage). A missing seal is SKIP, never a
        failure.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


PYTEST_SAFE_REL = Path(".agent") / "runtime" / "pytest-safe"
SEAL_NAME = "last-run.json"
LOG_NAME = "last-run.log"
DECLARATIONS_NAME = "skip-declarations.json"
REPORT_NAME = "skip-report.json"

SKIP_LINE_RE = re.compile(r"^SKIPPED \[(\d+)\]\s+(.+?):\s(.*)$")
SUMMARY_SKIPPED_RE = re.compile(r"(\d+)\s+skipped\b")
SUMMARY_END_RE = re.compile(r"\bin \d+(?:\.\d+)?s\s*$")
SUMMARY_COUNT_RE = re.compile(r"\d+\s+(?:passed|failed|error|skipped)\b")

ALLOWED_CLASSES = ("platform", "surface-missing", "other")
DEFAULT_SKIP_REASONS = ("", "skipped")


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_skips(log_text: str) -> tuple[list[dict], int]:
    """Before: ``log_text`` is the captured stdout of the canonical run.
    During: parses every ``SKIPPED [N] where: reason`` line (short summary
        emitted because ``-rs`` is in addopts). A default/empty reason
        (``pytest.skip()`` without argument prints ``Skipped``) is flagged as
        missing motive in the entry.
    After: (entries, total) where entries are dicts with ``count``, ``where``,
        ``reason`` and ``motive_present``; total is the summed count."""
    entries: list[dict] = []
    total = 0
    for line in log_text.splitlines():
        match = SKIP_LINE_RE.match(line.strip())
        if not match:
            continue
        count = int(match.group(1))
        where = match.group(2).strip()
        reason = match.group(3).strip()
        total += count
        entries.append(
            {
                "count": count,
                "where": where,
                "reason": reason,
                "motive_present": reason.lower() not in DEFAULT_SKIP_REASONS,
            }
        )
    return entries, total


def parse_log_summary_skipped(log_text: str) -> int | None:
    """Before: ``log_text`` is the captured stdout of the canonical run.
    During: scans lines in reverse for pytest's final summary line (ends with
        ``in <Xs>`` and carries at least one count token) and extracts the
        ``N skipped`` figure.
    After: the skipped count, or None when no parseable summary exists."""
    for line in reversed(log_text.splitlines()):
        stripped = line.strip()
        if not SUMMARY_END_RE.search(stripped):
            continue
        if not SUMMARY_COUNT_RE.search(stripped):
            continue
        match = SUMMARY_SKIPPED_RE.search(stripped)
        return int(match.group(1)) if match else 0
    return None


def _load_json(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _validate_declaration(
    declaration: dict, seal_started_at: str, skipped: int
) -> list[str]:
    """Before: parsed declaration payload, the sealed run timestamp and the
    seal's skipped count. During: validates the closed contract (same sealed
    run; closed class vocabulary; counts sum to the seal; notes mandatory when
    ``surface-missing`` appears). After: list of violation strings."""
    findings: list[str] = []
    declared_for = str(declaration.get("seal_started_at", ""))
    if not declared_for or declared_for != seal_started_at:
        findings.append(
            "declaracion no corresponde a este sello "
            f"(seal_started_at='{declared_for}' vs '{seal_started_at}')"
        )
    classes = declaration.get("classes")
    if not isinstance(classes, dict):
        findings.append("declaracion sin bloque 'classes'")
        return findings
    unknown = [key for key in classes if key not in ALLOWED_CLASSES]
    if unknown:
        findings.append(f"clases fuera del vocabulario cerrado: {sorted(unknown)}")
    total = 0
    invalid_values = [
        key
        for key, value in classes.items()
        if not isinstance(value, int) or isinstance(value, bool) or value < 0
    ]
    if invalid_values:
        findings.append(f"valores no enteros o negativos: {sorted(invalid_values)}")
    else:
        total = sum(classes.values())
    if not invalid_values and total != skipped:
        findings.append(
            f"la declaracion suma {total} skips y el sello registra {skipped}"
        )
    if int(classes.get("surface-missing", 0) or 0) > 0:
        notes = declaration.get("notes")
        if not isinstance(notes, str) or not notes.strip():
            findings.append(
                "hay skips 'surface-missing' y la declaracion no trae 'notes' "
                "con el detalle (superficie ausente que los audita)"
            )
    return findings


def _seal_skipped(seal: dict) -> int:
    """Before: parsed seal payload. During: normalizes ``skipped``.
    After: non-negative int (null/absent/malformed -> 0)."""
    raw = seal.get("skipped")
    if isinstance(raw, bool) or not isinstance(raw, int):
        return 0
    return max(0, raw)


def _cross_check_counts(
    seal_skipped: int,
    log_present: bool,
    entries: list[dict],
    entries_total: int,
    summary_skipped: int | None,
) -> list[str]:
    """Before: normalized counters from the seal and the log. During: applies
    the cross-check contract (count parity, summary parity, explicit motives).
    After: list of violation strings (empty = consistent)."""
    findings: list[str] = []
    if seal_skipped > 0:
        if not log_present:
            findings.append(
                "last-run.log ausente: no hay motivo registrado para los "
                f"{seal_skipped} skips del sello"
            )
            return findings
        if entries_total != seal_skipped:
            findings.append(
                "el log registra "
                f"{entries_total} skips y el sello registra {seal_skipped} "
                "(sin -rs el motivo no llega al log; verifica pytest.ini addopts)"
            )
        if summary_skipped is not None and summary_skipped != seal_skipped:
            findings.append(
                "divergencia log/sello: el resumen del log dice "
                f"{summary_skipped} skipped y el sello dice {seal_skipped}"
            )
        missing_motive = [entry for entry in entries if not entry["motive_present"]]
        if missing_motive:
            detail = ", ".join(
                f"{entry['where']} ({entry['count']})" for entry in missing_motive[:8]
            )
            findings.append(
                f"{len(missing_motive)} skip(s) sin motivo explicito: {detail}"
            )
        return findings
    if entries_total > 0:
        findings.append(
            f"el sello registra {seal_skipped} skips pero el log registra "
            f"{entries_total}: el sello no cuenta la perdida"
        )
    elif summary_skipped not in (None, 0):
        findings.append(
            f"el resumen del log dice {summary_skipped} skipped y el sello "
            f"registra {seal_skipped}"
        )
    return findings


def _declaration_findings(
    safe_dir: Path, seal_skipped: int, seal_started_at: str
) -> tuple[list[str], bool]:
    """Before: pytest-safe dir, seal counters. During: locates and validates
    the declaration (mandatory only when the sealed run has skips).
    After: (violations, declaration_present)."""
    declaration_path = safe_dir / DECLARATIONS_NAME
    declaration_present = declaration_path.is_file()
    if seal_skipped <= 0:
        return [], declaration_present
    if not declaration_present:
        return (
            [
                "falta skip-declarations.json: los skips del cierre deben "
                "declararse (clases: platform|surface-missing|other)"
            ],
            False,
        )
    declaration = _load_json(declaration_path)
    if declaration is None:
        return [f"declaracion ilegible o invalida: {declaration_path}"], True
    return (
        _validate_declaration(declaration, seal_started_at, seal_skipped),
        True,
    )


def run_check(project_root: Path) -> dict:
    """Before: ``project_root`` is the workspace to guard; the pytest-safe dir
        may not exist.
    During: loads the seal, parses the log and the declaration, cross-checks
        all three, and rewrites the derived ``skip-report.json`` annex when a
        seal exists (read-only on the seal and the log).
    After: report dict with ``verdict`` (pass|fail|skip), ``findings``,
        ``skip_reason`` and the parsed accounting (``seal_started_at``,
        ``seal_skipped``, ``entries``, ``declaration_present``)."""
    safe_dir = Path(project_root) / PYTEST_SAFE_REL
    seal_path = safe_dir / SEAL_NAME
    if not seal_path.is_file():
        return {
            "verdict": "skip",
            "findings": [],
            "skip_reason": "sin sello (no hay suite canonica registrada aun)",
            "seal_started_at": "",
            "seal_skipped": None,
            "entries": [],
            "declaration_present": False,
        }

    seal = _load_json(seal_path)
    if seal is None:
        return {
            "verdict": "fail",
            "findings": [f"sello ilegible o invalido: {seal_path}"],
            "skip_reason": "",
            "seal_started_at": "",
            "seal_skipped": None,
            "entries": [],
            "declaration_present": False,
        }

    seal_started_at = str(seal.get("started_at", ""))
    seal_skipped = _seal_skipped(seal)
    log_path = safe_dir / LOG_NAME
    log_present = log_path.is_file()
    log_text = ""
    if log_present:
        try:
            log_text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            log_present = False
    entries, entries_total = parse_skips(log_text) if log_present else ([], 0)
    summary_skipped = parse_log_summary_skipped(log_text) if log_present else None

    findings = _cross_check_counts(
        seal_skipped, log_present, entries, entries_total, summary_skipped
    )
    declaration_findings, declaration_present = _declaration_findings(
        safe_dir, seal_skipped, seal_started_at
    )
    findings.extend(declaration_findings)

    report = {
        "verdict": "fail" if findings else "pass",
        "findings": findings,
        "skip_reason": "",
        "seal_started_at": seal_started_at,
        "seal_skipped": seal_skipped,
        "log_present": log_present,
        "log_skipped": summary_skipped,
        "entries": entries,
        "declaration_present": declaration_present,
    }

    annex = {
        "generated_by": "scripts/check_audit_skips.py",
        "generated_at": _iso_now(),
        "seal_started_at": seal_started_at,
        "seal_skipped": seal_skipped,
        "log_present": log_present,
        "log_skipped": summary_skipped,
        "entries": entries,
        "declaration_present": declaration_present,
        "verdict": report["verdict"],
        "findings": findings,
    }
    try:
        tmp = safe_dir / (REPORT_NAME + ".tmp")
        tmp.write_text(
            json.dumps(annex, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        tmp.replace(safe_dir / REPORT_NAME)
    except OSError:
        pass

    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Guard de cierre: cada skip de la suite canonica debe llevar su "
            "motivo registrado y declarado (WOT-2026-074x)."
        )
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="Raiz del proyecto (por defecto: AGENT_PROJECT_ROOT resuelto).",
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
    root = Path(args.project_root) if args.project_root else _resolve_default_root()
    report = run_check(root)
    payload = {
        "root": str(root.resolve()) if root.exists() else str(root),
        "verdict": report["verdict"],
        "findings": report["findings"],
        "seal_started_at": report["seal_started_at"],
        "seal_skipped": report["seal_skipped"],
        "log_skipped": report.get("log_skipped"),
        "declaration_present": report["declaration_present"],
        "entries": report["entries"],
    }
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"[audit-skips] verdict={report['verdict']}")
        for finding in report["findings"]:
            print(f"  - {finding}")
        if report["verdict"] == "skip":
            print(f"  SKIP: {report.get('skip_reason')}")
    return 1 if report["verdict"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
