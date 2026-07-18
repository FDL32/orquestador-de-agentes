"""CLI de conformidad estructural HTML contra templates del destino.

CTL-2026-012i (Check 2; cross-repo). Recibe el root del destino via
``--project-root`` (DEC-012i-01: sin hardcodear rutas del destino) y resuelve
``content_roles/templates/`` desde el. Importa la logica reutilizable del
modulo ``encoding_guard`` (separacion de concerns: modulo = logica, CLI =
invocacion; DEC-2026-012i-05). No se mezcla con ``check_encoding_guard.py`` (el
pre-commit hook del motor).

Exit codes:
- ``0``: el output es conforme (0 issues).
- ``1``: issues de conformidad (output no publication-ready).
- ``2`` (o != 0): error de uso/pathing/lectura, con diagnostico accionable
  (fail-closed, nunca silent skip).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.encoding_guard import (  # noqa: E402
    build_template_registry,
    find_template_conformity_issues,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Check HTML output conformity against destino templates (CTL-2026-012i)."
        ),
    )
    parser.add_argument(
        "--project-root",
        required=True,
        help="destino repo root (must contain content_roles/templates/).",
    )
    parser.add_argument(
        "--html",
        required=True,
        help="HTML output file to check.",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()

    project_root = Path(args.project_root).resolve()
    templates_dir = project_root / "content_roles" / "templates"
    html_path = Path(args.html).resolve()

    try:
        registry = build_template_registry(templates_dir)
    except (FileNotFoundError, ValueError) as exc:
        print(
            f"error: cannot build template registry from {templates_dir}: {exc}",
            file=sys.stderr,
        )
        return 2

    if not html_path.is_file():
        print(f"error: HTML file not found: {html_path}", file=sys.stderr)
        return 2

    try:
        html_text = html_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(
            f"error: cannot read HTML file {html_path}: {exc}",
            file=sys.stderr,
        )
        return 2

    issues = find_template_conformity_issues(html_text, registry)
    if not issues:
        return 0
    print(f"template conformity issues in {html_path}:", file=sys.stderr)
    for issue in issues:
        print(f"- {issue}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
