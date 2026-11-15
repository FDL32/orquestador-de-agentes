#!/usr/bin/env python3
"""Guard staged or ranged changes against script and prompt counters.

Before: receive a Git checkout and optionally a revision range.
During: classify the staged/ranged diff, count first-level ``scripts/*.py``
    from the relevant Git state, read ``SCRIPTS_COUNT`` from the matching blob,
    and reuse the canonical prompt-budget auditor for normative prompts.
After: return zero for a valid measurement or an explicit no-matter skip, and
    return one with self-service diagnostics for every measured failure.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path


TEST_COUNTER_PATH = "tests/unit/test_152b2_link_readers_bom.py"
SCRIPT_RE = re.compile(r"^scripts/[^/]+\.py$")
COUNTER_RE = re.compile(r"^SCRIPTS_COUNT\s*=\s*(\d+)\s*$", re.MULTILINE)


def _run_git(root: Path, *args: str) -> str:
    """Run Git and fail closed with a reproducible diagnostic."""
    try:
        result = subprocess.run(  # noqa: S603
            ["git", "-c", "core.quotePath=false", *args],  # noqa: S607
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise RuntimeError(f"git no se puede leer ({exc}); revalida en {root}") from exc
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(
            f"git fallo rc={result.returncode}: {detail}; reproduce: git {' '.join(args)}"
        )
    return result.stdout


def _diff(root: Path, revision_range: str | None) -> list[tuple[str, list[str]]]:
    """Return Git name-status entries for the index or a revision range."""
    args = ["diff", "--cached", "--name-status", "-M"]
    if revision_range:
        args = ["diff", "--name-status", "-M", revision_range]
    rows = []
    for line in _run_git(root, *args).splitlines():
        fields = line.split("\t")
        if len(fields) >= 2:
            rows.append((fields[0], fields[1:]))
    return rows


def _script_count(root: Path, revision_range: str | None) -> int:
    """Count first-level scripts in the index or range tip."""
    if revision_range:
        names = _run_git(
            root, "ls-tree", "-r", "--name-only", revision_range.split("..", 1)[1]
        )
    else:
        names = _run_git(root, "ls-files", "--cached")
    return sum(
        bool(SCRIPT_RE.fullmatch(name.replace("\\", "/")))
        for name in names.splitlines()
    )


def _counter_text(root: Path, revision_range: str | None) -> str:
    """Read the counter from the staged blob or range-tip blob."""
    ref = revision_range.split("..", 1)[1] if revision_range else ":"
    spec = f":{TEST_COUNTER_PATH}" if ref == ":" else f"{ref}:{TEST_COUNTER_PATH}"
    text = _run_git(root, "show", spec)
    match = COUNTER_RE.search(text)
    if match is None:
        raise RuntimeError(
            f"SCRIPTS_COUNT no es parseable en {TEST_COUNTER_PATH}; "
            "actualiza el contador en el blob medido y revalida"
        )
    return match.group(1)


def _is_script_surface(path: str) -> bool:
    return bool(SCRIPT_RE.fullmatch(path.replace("\\", "/")))


def _is_entering_or_leaving_script(status: str, paths: list[str]) -> bool:
    if not status.startswith("R") or len(paths) < 2:
        return True
    old, new = paths[0].replace("\\", "/"), paths[1].replace("\\", "/")
    return _is_script_surface(old) != _is_script_surface(new)


def _audit_prompts(
    root: Path,
    paths: set[str],
    revision_range: str | None,
    normative_prompts: tuple[str, ...],
) -> bool:
    """Audit changed normative prompts using the canonical implementation."""
    sys.path.insert(0, str(root / "scripts"))
    from check_prompt_line_budget import audit

    ok = True
    for relative in sorted(paths & set(normative_prompts)):
        if revision_range:
            revision = revision_range.split("..", 1)[1]
            try:
                content = _run_git(root, "show", f"{revision}:{relative}")
            except RuntimeError as exc:
                raise RuntimeError(
                    f"no se puede extraer el prompt {relative}: {exc}"
                ) from exc
            with tempfile.TemporaryDirectory(prefix="counter-budget-") as temp:
                candidate = Path(temp) / Path(relative).name
                candidate.write_text(content, encoding="utf-8")
                result = audit(candidate)
        else:
            content = _run_git(root, "show", f":{relative}")
            with tempfile.TemporaryDirectory(prefix="counter-budget-") as temp:
                candidate = Path(temp) / Path(relative).name
                candidate.write_text(content, encoding="utf-8")
                result = audit(candidate)
        budget = result.line_budget
        print(
            f"Superficie medida: prompt {relative}; elementos=1; {result.actual_lines} lineas / presupuesto {budget}"
        )
        if not result.within_budget:
            print(
                f"FAIL: {relative}: presupuesto={budget}, lineas={result.actual_lines}; "
                "corrige el prompt y revalida con python scripts/check_counter_budget_gate.py"
            )
            ok = False
    return ok


def main(argv: list[str] | None = None) -> int:
    """Measure the selected Git state and report every applicable denominator."""
    parser = argparse.ArgumentParser(description="Guard de contadores y presupuestos")
    parser.add_argument(
        "--motor-root", "--repo-root", dest="root", type=Path, default=Path.cwd()
    )
    parser.add_argument("--range", dest="revision_range", metavar="A..B")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.revision_range and "..." in args.revision_range:
        print(
            "FAIL: --range no admite A...B; usa la forma A..B y revalida",
            file=sys.stderr,
        )
        return 1
    if args.revision_range and ".." not in args.revision_range:
        print(
            "FAIL: --range debe tener la forma A..B; revalida el rango", file=sys.stderr
        )
        return 1
    try:
        entries = _diff(root, args.revision_range)
        script_change = any(
            (_is_script_surface(paths[0]) if paths else False)
            or (
                status.startswith("R") and _is_entering_or_leaving_script(status, paths)
            )
            for status, paths in entries
            if status[0] in "ADR"
        )
        changed_paths = {
            path.replace("\\", "/") for _status, paths in entries for path in paths
        }
        normative_prompts: tuple[str, ...] = ()
        prompt_change = False
        if any(path.startswith("prompts/") for path in changed_paths):
            sys.path.insert(0, str(root / "scripts"))
            try:
                from check_prompt_line_budget import NORMATIVE_PROMPTS
            except (ImportError, OSError) as exc:
                raise RuntimeError(
                    "no se puede importar check_prompt_line_budget para auditar "
                    "materia bajo prompts/; restaura scripts/check_prompt_line_budget.py"
                ) from exc
            normative_prompts = NORMATIVE_PROMPTS
            prompt_change = bool(changed_paths & set(normative_prompts))
        if not script_change and not prompt_change:
            print("Superficie medida: diff aplicable; elementos=0")
            print(
                "SKIP EXPLICITO: no hay scripts/*.py de primer nivel ni prompt normativo tocado. No es un PASS."
            )
            return 0
        ok = True
        if script_change:
            found = _script_count(root, args.revision_range)
            expected = int(_counter_text(root, args.revision_range))
            print(f"Superficie medida: scripts/*.py de primer nivel; elementos={found}")
            if found != expected:
                print(
                    f"FAIL: {TEST_COUNTER_PATH}::test_no_strict_utf8_read_of_the_link_remains_in_scripts ; "
                    f"esperado SCRIPTS_COUNT={expected} (censo={expected + 1}), encontrado "
                    f"scripts/*.py={found} (censo={found + 1}); "
                    "reproduce con python scripts/check_counter_budget_gate.py y revalida"
                )
                ok = False
        if prompt_change:
            ok = (
                _audit_prompts(
                    root, changed_paths, args.revision_range, normative_prompts
                )
                and ok
            )
        return 0 if ok else 1
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"FAIL-CLOSED: {exc}; corrige la materia y revalida.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
