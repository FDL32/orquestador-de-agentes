"""Static guard: every literal ruff invocation in a target file carries --no-fix.

WOT-2026-047v. The system-health collector (scripts/collect_system_health.py) is
documented as read-only, but the repo sets `fix = true` in [tool.ruff], so a bare
`ruff check` invocation MUTATES the tree it audits and then reports GREEN
precisely because it fixed the findings (measured: rc=0 + file changed without
--no-fix; rc=1 + file untouched with --no-fix). This guard scans a Python target
and fails for EVERY literal command list that contains "ruff" without "--no-fix"
in that exact list. The check is per invocation, never by substring presence in
the whole file: a missing flag in the SECOND invocation is a violation even when
a first one carries the flag.

Before:
    - A readable UTF-8 Python source file. Default target:
      scripts/collect_system_health.py of this repo.

During:
    - Parses the target with `ast` and walks every literal sequence (ast.List /
      ast.Tuple). A sequence whose string elements include "ruff" but NOT
      "--no-fix" is a ruff invocation that can auto-fix under `fix = true`.
    - Declared scope limit (NON-GOAL of WOT-2026-047v): only LITERAL sequences
      are covered. An invocation assembled at runtime (variables, f-strings,
      subprocess.run with one string) is not detected.

After:
    - Exit 0: every literal ruff list in the target carries --no-fix.
    - Exit 1: at least one literal ruff list lacks --no-fix (line numbers are
      printed to stderr), or the target cannot be parsed.
    - Exit 2: argparse usage error (raised by argparse).
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TARGET = PROJECT_ROOT / "scripts" / "collect_system_health.py"


def _string_elements(node: ast.List | ast.Tuple) -> list[str]:
    """Return literal string elements of a sequence node, in order."""
    return [
        el.value
        for el in node.elts
        if isinstance(el, ast.Constant) and isinstance(el.value, str)
    ]


def ruff_invocations_without_no_fix(source: str) -> list[int]:
    """Return line numbers of literal ruff lists that lack `--no-fix`.

    Per invocation: each literal sequence containing "ruff" as an element must
    also contain "--no-fix" in the SAME sequence. Raises SyntaxError when the
    source is not valid Python.
    """
    tree = ast.parse(source)
    violations: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.List, ast.Tuple)):
            continue
        elements = _string_elements(node)
        if "ruff" in elements and "--no-fix" not in elements:
            violations.append(node.lineno)
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail if a Python target invokes ruff without --no-fix."
    )
    parser.add_argument(
        "--target",
        default=str(DEFAULT_TARGET),
        help=f"Python file to scan (default: {DEFAULT_TARGET})",
    )
    args = parser.parse_args(argv)

    target = Path(args.target)
    try:
        source = target.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"[ruff-nofix-guard] cannot read {target}: {exc}", file=sys.stderr)
        return 1
    try:
        violations = ruff_invocations_without_no_fix(source)
    except SyntaxError as exc:
        print(f"[ruff-nofix-guard] cannot parse {target}: {exc}", file=sys.stderr)
        return 1
    if violations:
        print(
            f"[ruff-nofix-guard] GUARD FAIL: ruff invocation(s) without --no-fix "
            f"in {target}: lines {violations}",
            file=sys.stderr,
        )
        return 1
    print(
        f"[ruff-nofix-guard] GUARD PASS: every literal ruff invocation in "
        f"{target} carries --no-fix"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
