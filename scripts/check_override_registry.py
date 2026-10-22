#!/usr/bin/env python3
"""CLI del registro de overrides YAML (WOT-2026-119a).

Ver `scripts/override_registry.py` para el diseno completo, la busqueda de
protocolo previo y la justificacion de las 4 salvaguardas (a)-(d). Este
fichero solo orquesta la libreria en dos fases de `.pre-commit-config.yaml`:

  pre-commit  WARN (nunca bloquea, exit 0 siempre que el propio registro sea
              legible): avisa de overrides activos cuyo `expiry` ya paso y
              que siguen sin archivar en `.agent/overrides/_archive/`.
  commit-msg  BLOCK (exit 1) autoritativo:
                - self-approval (salvaguarda a): el override Y un fichero de
                  su propio `scope` estan staged en el MISMO commit.
                - expiry sin archivar (salvaguarda b): un override activo ya
                  expirado sigue sin archivar -- el pre-commit solo avisa de
                  esto, aqui se bloquea de verdad.

Fail-CLOSED (salvaguarda d): si CUALQUIER YAML dentro de `.agent/overrides/`
(incluido uno nuevo que este commit anade) es ilegible o le falta un campo,
`load_overrides` lanza `OverrideRegistryError` y AMBAS fases salen con exit 1,
en vez de degradar a exit 0. Diverge deliberadamente del precedente
`check_commit_message_encoding.py:158-165` (fail-open ante error propio): ese
precedente es correcto para un guard de FORMA de mensaje, donde bloquear cada
commit por un fallo propio del guard es peor que el gap que cubre. Aqui el
mecanismo ES la superficie de seguridad -- degradar a exit 0 ante un YAML
corrupto seria exactamente el bypass silencioso que las salvaguardas (a)-(c)
existen para impedir, asi que el calculo de riesgo se invierte.

Before: se invoca como hook de `.pre-commit-config.yaml` con `--phase`; la
    fase `commit-msg` recibe la ruta de `COMMIT_EDITMSG` como argv posicional
    (igual que los hooks hermanos de cuspide), pero este guard no necesita el
    contenido del mensaje -- solo los ficheros staged.
During: no escribe nada; solo lee `.agent/overrides/*.yaml` y
    `git diff --cached --name-only`.
After: exit 0 en el camino silencioso (sin overrides, o con overrides sanos y
    sin violaciones); exit 1 en commit-msg con self-approval o expiry sin
    archivar; exit 1 en CUALQUIER fase si el registro esta malformado
    (fail-closed, salvaguarda d).
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

from override_registry import (
    MOTOR_ROOT,
    OVERRIDES_DIR,
    Override,
    OverrideRegistryError,
    is_expired,
    load_overrides,
    normalize_relpath,
    self_approval_violation,
    staged_files,
)


MARKER = "[override-registry]"


def _today() -> date:
    return datetime.now().date()


def _override_relpath(override: Override, repo_root) -> str:
    try:
        return normalize_relpath(
            str(override.source_path.resolve().relative_to(repo_root))
        )
    except ValueError:
        return normalize_relpath(str(override.source_path))


def run(phase: str, repo_root=None) -> int:
    root = repo_root or MOTOR_ROOT
    overrides_dir = root / ".agent" / "overrides" if repo_root else OVERRIDES_DIR
    archive_dir = overrides_dir / "_archive"
    try:
        overrides = load_overrides(overrides_dir)
    except OverrideRegistryError as exc:
        print(
            f"{MARKER} FAIL-CLOSED: registro de overrides malformado: {exc}",
            file=sys.stderr,
        )
        return 1

    if not overrides:
        return 0

    today = _today()
    changed = staged_files(cwd=root)
    expired = [o for o in overrides if is_expired(o, today)]
    violations = [
        o
        for o in overrides
        if self_approval_violation(o, _override_relpath(o, root), changed)
    ]

    if phase == "pre-commit":
        for o in expired:
            print(
                f"{MARKER} WARN: override {o.id} ({o.source_path.name}) "
                f"expiro {o.expiry.isoformat()} y sigue activo sin archivar "
                f"en {archive_dir}. commit-msg lo bloqueara.",
                file=sys.stderr,
            )
        return 0

    if phase == "commit-msg":
        failed = False
        for o in violations:
            print(
                f"{MARKER} BLOCK: self-approval -- override {o.id} "
                f"({o.source_path.name}) y un fichero de su propio scope "
                "estan staged en el MISMO commit. Aterriza el override en "
                "un commit PREVIO, revisado antes de que exista el cambio "
                "que excepciona.",
                file=sys.stderr,
            )
            failed = True
        for o in expired:
            print(
                f"{MARKER} BLOCK: override {o.id} ({o.source_path.name}) "
                f"expiro {o.expiry.isoformat()} y sigue activo. Archivalo en "
                f"{archive_dir} o renuevalo (nuevo expiry) antes de commitear.",
                file=sys.stderr,
            )
            failed = True
        return 1 if failed else 0

    print(f"{MARKER} fase desconocida: {phase!r}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["pre-commit", "commit-msg"], required=True)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Raiz del repo a auditar (default: MOTOR_ROOT). Solo para tests hermeticos.",
    )
    parser.add_argument("message_path", nargs="?", default=None)
    args = parser.parse_args(argv)
    return run(args.phase, repo_root=args.repo_root)


if __name__ == "__main__":
    sys.exit(main())
