#!/usr/bin/env python3
"""WOT-2026-040z: autoridad de sesion cableada en el camino de push.

El incidente (2026-07-25): una sesion de DISENO pusheo ac984f5..22fae69 a
origin/main porque nada en el codigo conoce el tipo de sesion -- la accion
menos reversible del sistema era la unica sin control de autoridad. Este guard
es la BARRERA: hook propio `stages: [pre-push]` en .pre-commit-config.yaml
(un raw `git push` lo ejecuta; el gate de closeout NO habria parado el
incidente), que BLOQUEA el push a main cuando la sesion esta DECLARADA como
`diseno` y no se ha dejado rastro de escape.

Declaracion (decision (b) de la orquestadora): el comando de bootstrap recibe
`--session-type diseno|desarrollo|orquestacion` EXPLICITO y escribe
`.agent/runtime/session/session_type.json` {"tipo", "declared_at",
"declared_by"}. Sin el flag NO se escribe fichero y este guard da WARN
(sesiones legacy) -- nunca adivina el tipo.

Escape (decision (a)): NO hay flag (git push no transporta flags al hook y un
agente lo anadiria sin coste). El escape es la variable de entorno
DESIGN_PUSH_REASON con motivo NO vacio: el guard registra la linea en
.agent/runtime/session/design_push_log.jsonl (auditable: timestamp, motivo,
refs) y deja pasar el push. La via alternativa es REDECLARAR el tipo con el
comando de declaracion (reescribe session_type.json con declared_at/by
nuevos). Ambas dejan rastro.

Limitaciones declaradas (decision (b)):
- El fichero es POR CHECKOUT (.agent/runtime/ es per-worktree): dos sesiones
  compartiendo checkout comparten tipo.
- Un session_type.json VIEJO en una worktree reutilizada puede bloquear a una
  sesion de desarrollo nueva -- el mensaje de bloqueo dice exactamente como
  redeclarar.

Before: cwd o --project-root apunta a la raiz del repo empujado; stdin trae
las lineas `<local_ref> <local_sha> <remote_ref> <remote_sha>` de pre-commit
(fase pre-push) o el fallback por entorno. During: determina si el destino es
main; lee la declaracion; evalua autoridad; en escape escribe el log. After:
0 = autorizado/legacy/no-main; 1 = bloqueado (declarada diseno -> main sin
escape, con instrucciones exactas de redeclaracion); 2 = error de
infraestructura. Nunca determina el tipo por si solo.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


SESSION_TYPE_RELPATH = Path(".agent") / "runtime" / "session" / "session_type.json"
PUSH_LOG_RELPATH = Path(".agent") / "runtime" / "session" / "design_push_log.jsonl"
VALID_TYPES = ("diseno", "desarrollo", "orquestacion")


def _remote_refs_from_stdin() -> list[str]:
    """Refs REMOTAS de las lineas stdin de pre-commit (fase pre-push).

    Before: stdin puede traer lineas `<local_ref> <local_sha> <remote_ref>
        <remote_sha>` (una por ref empujada) o estar vacio (invocacion manual
        / hook --all-run-mode). During: parsea el tercer campo de cada linea
        no vacia. After: lista de remote refs (posiblemente vacia).
    """
    refs: list[str] = []
    try:
        raw = sys.stdin.read()
    except (OSError, ValueError):
        return refs
    for line in raw.splitlines():
        parts = line.strip().split()
        if len(parts) >= 3:
            refs.append(parts[2])
    return refs


def _is_main_target(remote_refs: list[str], env: dict[str, str]) -> bool:
    """True si alguna ref remota del push es main.

    Before: remote_refs del stdin y el entorno de pre-commit. During: refs
        `refs/heads/main` o que terminan en `/main`; fallback
        PRE_COMMIT_REMOTE_BRANCH cuando el stdin no trae nada. After: bool.
    """
    for ref in remote_refs:
        if ref == "refs/heads/main" or ref.endswith("/main"):
            return True
    branch = env.get("PRE_COMMIT_REMOTE_BRANCH", "")
    return branch in ("main", "refs/heads/main", "origin/main")


def _read_declaration(project_root: Path) -> dict | None:
    """Lee session_type.json; None si no existe o es ilegible (legacy/WARN)."""
    path = project_root / SESSION_TYPE_RELPATH
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _append_escape_log(project_root: Path, reason: str, remote_refs: list[str]) -> None:
    """Deja rastro auditable del escape (decision (a) de la orquestadora)."""
    log_path = project_root / PUSH_LOG_RELPATH
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "remote_refs": remote_refs,
        "mechanism": "DESIGN_PUSH_REASON",
    }
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=True) + "\n")


def run(
    project_root: Path,
    stdin_remote_refs: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> int:
    """Logica pura del guard (testeable sin stdin real).

    Before: project_root raiz del repo empujado; stdin_remote_refs None =
        leer stdin real (produccion), lista = inyectada (tests); env None =
        os.environ. During: deteccion de destino, lectura de declaracion,
        evaluacion, escape con log. After: 0/1/2 segun docstring del modulo.
    """
    if stdin_remote_refs is None:
        remote_refs = _remote_refs_from_stdin()
    else:
        remote_refs = stdin_remote_refs
    environment = env if env is not None else dict(os.environ)

    try:
        if not _is_main_target(remote_refs, environment):
            print(
                "[push-authority] PASS: el push no va a main "
                f"(refs: {', '.join(remote_refs) or 'desconocidas'})"
            )
            return 0

        declaration = _read_declaration(project_root)
        if declaration is None:
            # Decision (b): sesion legacy sin declaracion -> WARN, no bloquea.
            print(
                "[push-authority] WARN: push a main SIN declaracion de tipo de "
                "sesion (legacy). Declara con: python scripts/destination_context.py "
                "--bootstrap --project-root <raiz> --session-type desarrollo|orquestacion|diseno"
            )
            return 0

        tipo = str(declaration.get("tipo", ""))
        if tipo != "diseno":
            print(
                f"[push-authority] PASS: sesion declarada '{tipo}' pusha a main "
                "(autoridad de desarrollo/orquestacion)"
            )
            return 0

        reason = environment.get("DESIGN_PUSH_REASON", "").strip()
        if reason:
            _append_escape_log(project_root, reason, remote_refs)
            print(
                "[push-authority] ESCAPE registrado: sesion 'diseno' pusha a "
                f"main con DESIGN_PUSH_REASON='{reason}' "
                "(linea anadida a design_push_log.jsonl, auditable)"
            )
            return 0

        declared_at = declaration.get("declared_at", "?")
        print(
            "[push-authority] FAIL: sesion declarada 'diseno' (declared_at="
            f"{declared_at}) NO puede empujar a main. Opciones exactas:\n"
            "  1. Reddeclarar el tipo (reescribe session_type.json con rastro):\n"
            "     python scripts/destination_context.py --bootstrap "
            "--project-root <raiz> --session-type desarrollo\n"
            "  2. Escape puntual con motivo no vacio (queda en "
            "design_push_log.jsonl):\n"
            '     DESIGN_PUSH_REASON="<motivo>" git push ...',
            file=sys.stderr,
        )
        return 1
    except OSError as exc:
        print(f"[push-authority] ERROR: {exc}", file=sys.stderr)
        return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Raiz del repo empujado (default: cwd, que en pre-push es la raiz).",
    )
    args = parser.parse_args(argv)
    return run(args.project_root.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
