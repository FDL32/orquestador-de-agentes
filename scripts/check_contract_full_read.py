#!/usr/bin/env python3
r"""Check contract full read (WOT-2026-042z).

Dado un artefacto (prompt, work\_plan, informe) que CITA un prompt/contrato
canonico por ruta, cruza esa cita contra el registro de Read de la sesion
(eventos emitidos por `.agent/hooks/native_post_tool_hook.py`) y verifica
`line_count observado >= wc -l real` del fichero citado (o que la union de
lecturas parciales cubre el fichero completo). Si no cubre: FALLA listando el
fichero y las lineas ausentes.

Distincion critica: LEER != GREPEAR
------------------------------------
Un evento `Read` real del hook es el UNICO que cuenta como lectura. Una
invocacion de `grep`/`diff`/`cat`/`git show`/`Get-ChildItem`/`wc` sobre el
fichero NO cuenta como lectura -- ese fue exactamente el nucleo del fallo
WOT-2026-042z (2026-07-29: se redacto un prompt contra un fichero de 571
lineas por GREP DIRIGIDO + DIFF, sin abrirlo entero).

Muestreo declarado (anti-falso-positivo)
-----------------------------------------
Una DECLARACION EXPLICITA de muestreo inmediatamente ANTES de la cita pasa
con WARN, no ERROR. El patrón buscado es: una linea (o bloque adyacente) que
contenga `:` (rango de lineas como `:100-200` o `lines 100-200`) junto con
palabras como `muestreo`, `solo`, `leer` (o `read`, `sample`) y `riesgo`
(o `risk`). La norma prohibe el muestreo SILENCIOSO; permite el muestreo
DECLARADO siempre que se anteceda explicitamente.

Ejecucion
---------
python scripts/check_contract_full_read.py <artefacto> [telemetry_dir]

  <artefacto>    ruta al fichero artefacto que puede contener citas de otros
                 ficheros (prompt, work\_plan, informe).
  <telemetry_dir> ruta al directorio .agent/runtime/telemetry/ donde vive
                  tool\_usage.jsonl. Por defecto: <motor_root>/.agent/runtime/
                  telemetry/, resuelto desde la raiz del motor.

Exit codes:
  0 -- todos los ficheros citados leidos enteros (WARN de muestreo OK).
  1 -- algun fichero citado NO leido enteramente (ERROR) o muestreo sin
       declaracion valida (WARN -> ERROR).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


# ------------------------------------------------------------------ constants
# Citas canonicas de ficheros: rutas relativas al motor que terminan en .md
# o .py (los tipos normativos mas comunes). Se aceptan barras, backslash o
# backticks.
_CITATION_RE = re.compile(
    r"(?:"
    r"(?P<backtick>`)(?P<path1>[^\s`]+)`|"
    r"(?P<quoted>[" + '"' + r"'])(?P<path2>[^\s" + '"' + r"]+)"
    r"(?:[" + '"' + r"])|"
    r"(?P<path3>\S+\.(?:md|py))"
    r")",
    re.IGNORECASE,
)

# Muestreo declarado: busca patrones con :X-Y y palabras clave (muestreo, sample,
# riesgo, risk). La linea debe anteceder a la cita (verificacion contextual en el parser).
_DASH_RE = r"[-\u2013]"
_SAMPLING_RE = re.compile(
    r"(?:muestreo|sample(?:d|ing)?|solo\s+(?:leo|leer|reading)|"
    r":\s*(\d+)\s*"
    + _DASH_RE
    + r"\s*(\d+)|lines?\s+(?:\d+\s*"
    + _DASH_RE
    + r"\s*)*\d+.*?"
    r"(?:muestreo|sample|riesgo|risk))",
    re.IGNORECASE,
)

# Rango de lineas explicito (:X-Y o lines X-Y)
_LINE_RANGE_RE = re.compile(
    r":\s*(\d+)\s*" + _DASH_RE + r"\s*(\d+)|"
    r"lines?\s+(\d+)\s*" + _DASH_RE + r"\s*(\d+)",
    re.IGNORECASE,
)


def resolve_motor_root() -> Path:
    """Resolve the motor root from this script's location."""
    return Path(__file__).resolve().parent.parent


def resolve_telemetry_dir(motor_root: Path, explicit: Path | None) -> Path:
    """Return the telemetry directory."""
    if explicit and explicit.is_dir():
        return explicit
    candidate = motor_root / ".agent" / "runtime" / "telemetry"
    if candidate.is_dir():
        return candidate
    # Try from CWD (workspace active)
    cwd_telemetry = Path(".agent").absolute() / "runtime" / "telemetry"
    if cwd_telemetry.is_dir():
        return cwd_telemetry
    # Default fallback -- will likely fail on reads, which is acceptable
    return candidate


def load_read_events(
    telemetry_dir: Path,
    session_id: str | None = None,
) -> list[dict[str, Any]]:
    """Load Read events from the telemetry file, optionally filtered by session.

    Args:
        telemetry_dir: Path to .agent/runtime/telemetry/
        session_id: If provided, only return events from this session.
    """
    events: list[dict[str, Any]] = []
    telemetry_file = telemetry_dir / "tool_usage.jsonl"
    if not telemetry_file.is_file():
        return events
    with telemetry_file.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Read events have context like "Read file <path>, <n> lines"
            context = record.get("context", "")
            if not context.startswith("Read file "):
                continue
            if session_id is not None and record.get("session_id") != session_id:
                continue
            inner = context[len("Read file ") :]
            try:
                parts = inner.rsplit(", ", 1)
                if len(parts) == 2:
                    file_path = parts[0].strip()
                    line_count_str = parts[1].strip()
                    line_count = int(line_count_str.replace(" lines", ""))
                    events.append(
                        {
                            "file_path": file_path,
                            "line_count": line_count,
                        }
                    )
            except (ValueError, IndexError):
                continue
    return events


def _normalize_path(p: str, motor_root: Path) -> Path | None:
    """Try to resolve a citation path to a real file under motor_root."""
    # Try exact relative path
    candidate = motor_root / p
    if candidate.is_file():
        return candidate
    # Try with forward slashes normalized
    candidate = motor_root / p.replace("\\", "/")
    if candidate.is_file():
        return candidate
    # Try as-is (might be absolute)
    if Path(p).is_file():
        return Path(p)
    return None


def _count_lines(file_path: Path) -> int:
    """Count lines in a file (wc -l equivalent)."""
    raw = file_path.read_bytes()
    # Count \n-terminated lines (wc -l convention)
    return raw.count(b"\n") + (1 if raw and not raw.endswith(b"\n") else 0)


def _find_citations_in_artifact(  # noqa: C901
    artifact_path: Path,
    motor_root: Path,
) -> list[dict[str, Any]]:
    """Extract citation information from the artifact.

    Returns a list of dicts with:
      - path: the cited file path (raw)
      - resolved: Path or None
      - wc_lines: int or None
      - sampling_declared: bool
      - line_range: (start, end) tuple or None (for sampling)
    """
    artifact_text = artifact_path.read_text(encoding="utf-8")
    lines = artifact_text.splitlines()
    citations: list[dict[str, Any]] = []

    for i, line in enumerate(lines):
        # Find all citation-like patterns in this line
        for match in _CITATION_RE.finditer(line):
            # Determine the path from whichever group matched
            if match.group("path1"):
                raw_path = match.group("path1")
            elif match.group("path2"):
                raw_path = match.group("path2").strip("'\"")
            elif match.group("path3"):
                raw_path = match.group("path3").strip("'\"")
            else:
                continue

            # Check for sampling declaration in nearby lines (previous line)
            sampling_declared = False
            line_range: tuple[int, int] | None = None
            for j in range(max(0, i - 2), i):
                prev_line = lines[j]
                # Look for sampling patterns
                if _SAMPLING_RE.search(prev_line) and _LINE_RANGE_RE.search(prev_line):
                    range_match = _LINE_RANGE_RE.search(prev_line)
                    if range_match:
                        start = int(range_match.group(1) or range_match.group(3))
                        end = int(range_match.group(2) or range_match.group(4))
                        line_range = (start, end)
                    sampling_declared = True
                # Also check the same line for sampling + range
                if (
                    not sampling_declared
                    and _SAMPLING_RE.search(line)
                    and _LINE_RANGE_RE.search(line)
                ):
                    range_match = _LINE_RANGE_RE.search(line)
                    if range_match:
                        start = int(range_match.group(1) or range_match.group(3))
                        end = int(range_match.group(2) or range_match.group(4))
                        line_range = (start, end)
                    sampling_declared = True

            # Resolve the path against the provided motor_root
            if raw_path.startswith("/"):
                resolved = Path(raw_path)
            else:
                resolved = _normalize_path(raw_path, motor_root)

            wc_lines = None
            if resolved and resolved.is_file():
                wc_lines = _count_lines(resolved)

            citations.append(
                {
                    "path": raw_path,
                    "resolved": resolved,
                    "wc_lines": wc_lines,
                    "sampling_declared": sampling_declared,
                    "line_range": line_range,
                    "line_num": i + 1,  # 1-indexed for reporting
                }
            )

    return citations


def check_read_coverage(  # noqa: C901
    citations: list[dict[str, Any]],
    read_events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Check read coverage for each citation.

    Returns dict with:
      - ok: bool (overall pass/fail)
      - errors: list[str] -- failure descriptions
      - warnings: list[str] -- sampling warnings
      - details: list of per-citation results
    """
    # Build coverage map: for each file, track which lines were read
    # line_count in the event means the file was read with at least that many
    # lines. A single read event with line_count >= wc_lines covers the file.
    coverage: dict[str, int] = {}  # file_path -> max line_count seen
    for ev in read_events:
        fp = ev["file_path"]
        lc = ev["line_count"]
        if fp not in coverage or lc > coverage[fp]:
            coverage[fp] = lc

    result: dict[str, Any] = {
        "ok": True,
        "errors": [],
        "warnings": [],
        "details": [],
    }

    for cit in citations:
        path_raw = cit["path"]
        resolved = cit["resolved"]
        wc_lines = cit["wc_lines"]
        sampling_declared = cit["sampling_declared"]
        line_range = cit["line_range"]

        detail: dict[str, Any] = {
            "path": path_raw,
            "covered": False,
        }

        if not resolved or not resolved.is_file():
            # Cannot check: file not found under motor root
            detail["status"] = "unresolved"
            result["warnings"].append(
                f"{path_raw}: no se resolvio bajo el motor root (saltado)"
            )
            continue

        if wc_lines is None:
            wc_lines = _count_lines(resolved)
            detail["wc_lines"] = wc_lines

        # Check if this file was read
        # Try to match against telemetry events
        # B3: use full normalized path (not suffix matching) to avoid cross-session
        # false-positives where a homonym file read in another session seals PASS.
        matched_line_count: int | None = None

        for fp, max_lc in coverage.items():
            # Exact match on the raw file_path from telemetry
            if fp == path_raw:
                matched_line_count = max_lc
                break
            # Full normalized path match (B3 fix)
            try:
                if Path(fp).resolve() == resolved.resolve():
                    matched_line_count = max_lc
                    break
            except (OSError, ValueError):
                continue

        if matched_line_count is not None and matched_line_count >= wc_lines:
            # Full coverage: read with >= wc_lines
            detail["status"] = "covered"
            detail["read_lines"] = matched_line_count
            detail["wc_lines"] = wc_lines
            detail["covered"] = True
            continue

        # Check if line-range sampling covers the file
        if sampling_declared and line_range:
            range_start, range_end = line_range
            # Sampling is valid if it covers the full file
            if range_start <= 1 and range_end >= wc_lines:
                detail["status"] = "covered_by_sampling"
                detail["read_lines"] = wc_lines
                detail["wc_lines"] = wc_lines
                detail["covered"] = True
                result["warnings"].append(
                    f"{path_raw}: muestreo declarado :{range_start}-{range_end} "
                    f"cubre el fichero entero ({wc_lines} lin)"
                )
                continue
            elif range_end >= wc_lines:
                # Partial coverage with declaration -> WARN not ERROR
                detail["status"] = "partial_sampling"
                detail["read_lines"] = line_range[1] - line_range[0] + 1
                detail["wc_lines"] = wc_lines
                detail["covered"] = False
                # Not an error if declared, but list as warning
                result["warnings"].append(
                    f"{path_raw}: muestreo declarado :{range_start}-{range_end} "
                    f"({wc_lines} lin total) -> linea(s) ausente(s) {range_end + 1}-{wc_lines}"
                )
                continue

        # FAILED: file not read or partial read without declaration
        if sampling_declared and not (line_range and line_range[1] >= wc_lines):
            # Declared but insufficient -> WARN (not ERROR)
            read_lines = matched_line_count or 0
            absent_lines = list(
                range(read_lines + 1, wc_lines + 1) if read_lines < wc_lines else []
            )
            detail["status"] = "partial_declared"
            detail["read_lines"] = read_lines
            detail["wc_lines"] = wc_lines
            detail["covered"] = False
            detail["absent_lines"] = absent_lines[:20]  # cap at 20
            result["warnings"].append(
                f"{path_raw}: muestreo declarado, pero {read_lines}/{wc_lines} lin "
                f"(ausentes: {absent_lines[:5] if absent_lines else 'N/A'})"
            )
        else:
            read_lines = matched_line_count or 0
            absent_lines = list(
                range(read_lines + 1, wc_lines + 1) if read_lines < wc_lines else []
            )
            detail["status"] = "not_read"
            detail["read_lines"] = read_lines
            detail["wc_lines"] = wc_lines
            detail["covered"] = False
            detail["absent_lines"] = absent_lines[:20]
            result["errors"].append(
                f"{path_raw}: {read_lines}/{wc_lines} lin leidas "
                f"(ausentes: {absent_lines[:5] if absent_lines else 'N/A'})"
            )
            result["ok"] = False

        result["details"].append(detail)

    return result


def main() -> int:  # noqa: C901
    parser = argparse.ArgumentParser(
        description="WOT-2026-042z: check that cited prompts/contracts were fully read."
    )
    parser.add_argument(
        "artifact",
        nargs="?",
        default=None,
        help=r"Path to the artifact (prompt/work\_plan/report) that cites files.",
    )
    parser.add_argument(
        "telemetry_dir",
        nargs="?",
        default=None,
        help="Path to .agent/runtime/telemetry/. Default: auto-resolve.",
    )
    parser.add_argument(
        "--motor-root",
        default=None,
        help="Path to motor root. Default: auto-resolve from script location.",
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help="Filter telemetry to a single session (default: all sessions).",
    )
    args = parser.parse_args()

    artifact_path = None
    if args.artifact:
        artifact_path = Path(args.artifact)
        if not artifact_path.is_file():
            print(
                f"ERROR: artefacto no encontrado: {artifact_path}",
                file=sys.stderr,
            )
            return 2
    else:
        # No artifact provided: scan .agent/planning/ for citation-rich files
        motor_root = Path(args.motor_root) if args.motor_root else resolve_motor_root()
        planning_dir = motor_root / ".agent" / "planning"
        if planning_dir.is_dir():
            # Find .md files with citations (heuristic: contain backtick-quoted paths)
            import glob

            for pattern in (
                "**/*.md",
                "**/*.txt",
                "vuelo7/**/*.md",
                "**/WOT-*/**/*.md",
            ):
                for md_file in glob.glob(str(planning_dir / pattern), recursive=True):
                    fp = Path(md_file)
                    if (
                        fp.is_file()
                        and _CITATION_RE.search(fp.read_text(encoding="utf-8"))
                        and (
                            artifact_path is None
                            or artifact_path.stat().st_mtime < fp.stat().st_mtime
                        )
                    ):
                        artifact_path = fp
        if artifact_path is None:
            print(
                "INFO: no artifacts with citations found, nothing to verify.",
                file=sys.stderr,
            )
            print("PASS: no citations found (nothing to verify).")
            return 0

    motor_root = Path(args.motor_root) if args.motor_root else resolve_motor_root()
    telemetry_dir = resolve_telemetry_dir(
        motor_root, Path(args.telemetry_dir) if args.telemetry_dir else None
    )

    # Load read events from telemetry
    read_events = load_read_events(telemetry_dir, session_id=args.session_id)

    # Extract citations from the artifact
    citations = _find_citations_in_artifact(artifact_path, motor_root)

    if not citations:
        print(
            "INFO: no se encontraron citas de ficheros en el artefacto.",
            file=sys.stderr,
        )
        print("PASS: 0 citations found (nothing to verify).")
        return 0

    # Check coverage
    result = check_read_coverage(citations, read_events)

    # Report
    if result["errors"]:
        print(f"FAIL: {len(result['errors'])} fichero(s) no leidos enteramente:")
        for err in result["errors"]:
            print(f"  ERROR: {err}")

    if result["warnings"]:
        print(f"WARN: {len(result['warnings'])} aviso(s):")
        for warn in result["warnings"]:
            print(f"  WARN: {warn}")

    # Per-citation detail
    for detail in result.get("details", []):
        status = detail.get("status", "unknown")
        path = detail["path"]
        covered = detail.get("covered", False)
        print(
            f"  {path}: {status} "
            f"(covered={covered}, read={detail.get('read_lines', '?')}, "
            f"wc={detail.get('wc_lines', '?')})"
        )

    if result["ok"]:
        print("PASS: todos los ficheros citados leidos enteramente.")
        return 0
    else:
        print("FAIL: hay ficheros citados sin lectura completa.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
