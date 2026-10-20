#!/usr/bin/env python3
"""Prepara un bundle reproducible para `claude -p` / `claude --cloud`.

Before: el llamante tiene un repo git y una descripcion de tarea.
During: construye `.agent/cloud_bundle.md` con contexto + tarea + criterios,
    calcula su SHA-256 y escribe `.agent/cloud_manifest.json` con commit,
    rama, modelo, tool policy y hash. No toca el repo ni la red.
After: los dos ficheros quedan escritos; imprime los comandos exactos para
    `claude -p` (local) y `claude --cloud` (manual) / follow-up
    `claude -p --cloud <session_id>`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def _git_value(repo: Path, *args: str) -> str:
    """Lee un valor de git; 'unknown' si no hay repo o falla."""
    git_exe = shutil.which("git")
    if not git_exe:
        return "unknown"
    try:
        result = subprocess.run(  # noqa: S603
            [git_exe, "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    if result.returncode != 0:
        return "unknown"
    return result.stdout.strip()


def build_bundle(
    task: str, commit: str, branch: str, model: str, allowed_tools: str
) -> str:
    """Construye el markdown del bundle (determinista salvo el timestamp)."""
    return (
        "# Cloud bundle\n\n"
        f"- Tarea: {task}\n"
        f"- Commit: {commit}\n"
        f"- Rama: {branch}\n"
        f"- Modelo: {model}\n"
        f"- Tools permitidas: {allowed_tools}\n"
        f"- Generado: {datetime.now(timezone.utc).isoformat()}\n\n"
        "## Instrucciones\n\n"
        "1. Lee este bundle completo antes de actuar.\n"
        "2. Inspecciona el repo en el commit indicado.\n"
        "3. Ejecuta la tarea con las tools permitidas.\n"
        "4. Devuelve un informe con: cambios, evidencia (comandos/exit codes), "
        "riesgos y siguiente paso.\n"
        "5. No commitees ni pushees sin autorizacion explicita.\n\n"
        "## Tarea\n\n"
        f"{task}\n"
    )


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True, help="Descripcion de la tarea")
    parser.add_argument("--repo", default=".", help="Raiz del repo (default: .)")
    parser.add_argument("--output", default=".agent/cloud_bundle.md")
    parser.add_argument("--manifest", default=".agent/cloud_manifest.json")
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--allowed-tools", default="Read,Grep,Glob")
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    commit = _git_value(repo, "rev-parse", "HEAD")
    branch = _git_value(repo, "rev-parse", "--abbrev-ref", "HEAD")
    bundle = build_bundle(args.task, commit, branch, args.model, args.allowed_tools)
    bundle_path = repo / args.output
    manifest_path = repo / args.manifest
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(bundle, encoding="utf-8", newline="\n")
    manifest = {
        "task": args.task,
        "commit": commit,
        "branch": branch,
        "model": args.model,
        "allowed_tools": args.allowed_tools,
        "bundle": str(bundle_path.relative_to(repo)).replace("\\", "/"),
        "bundle_sha256": hashlib.sha256(bundle.encode("utf-8")).hexdigest(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"[OK] bundle: {bundle_path}")
    print(f"[OK] manifest: {manifest_path}")
    print(f"[OK] sha256: {manifest['bundle_sha256']}")
    print()
    print("Local (claude -p):")
    print(
        f'claude -p --output-format json --append-system-prompt-file "{bundle_path}" '
        f'--model {args.model} "Ejecuta la tarea del bundle"'
    )
    print()
    print("Cloud (manual, TTY):")
    print(f'claude --cloud "Lee {bundle_path} y ejecuta la tarea"')
    print()
    print("Cloud follow-up (programatico):")
    print(
        "claude -p --cloud <session_id> --output-format json "
        '"Continua con la tarea del bundle"'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
