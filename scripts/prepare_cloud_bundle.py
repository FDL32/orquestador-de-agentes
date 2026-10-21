#!/usr/bin/env python3
"""Prepara un bundle reproducible y el runbook de una sesion cloud.

Before: el llamante tiene un repo git y una descripcion de tarea.
During: construye `.agent/cloud_bundle.md` con contexto + tarea + criterios,
    calcula su SHA-256 y escribe `.agent/cloud_manifest.json` con task_id,
    commit, rama de trabajo, modelo, tool policy y hash. No toca el repo ni la
    red.
After: los dos ficheros quedan escritos; imprime un runbook de una accion por
    linea para crear la rama, lanzar `claude --cloud` (creacion manual, TTY) y
    el comando de follow-up programatico `claude -p --cloud <session_id>`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
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


def _slug(value: str) -> str:
    """Slug estable para task_id/branch (minusculas, guiones)."""
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:48] or "cloud-task"


def build_bundle(
    task: str,
    task_id: str,
    commit: str,
    branch: str,
    model: str,
    allowed_tools: str,
) -> str:
    """Construye el markdown del bundle (determinista salvo el timestamp)."""
    return (
        "# Cloud bundle\n\n"
        f"- task_id: {task_id}\n"
        f"- Tarea: {task}\n"
        f"- Commit base: {commit}\n"
        f"- Rama de trabajo: {branch}\n"
        f"- Modelo: {model}\n"
        f"- Tools permitidas: {allowed_tools}\n"
        f"- Generado: {datetime.now(timezone.utc).isoformat()}\n\n"
        "## Instrucciones\n\n"
        "1. Lee este bundle completo antes de actuar.\n"
        f"2. Trabaja SOLO en la rama `{branch}`. No toques `main`.\n"
        "3. Inspecciona el repo en el commit base indicado.\n"
        "4. Ejecuta la tarea con las tools permitidas.\n"
        "5. Devuelve un informe con: cambios, evidencia (comandos/exit codes), "
        "riesgos y siguiente paso.\n"
        "6. No commitees ni pushees sin autorizacion explicita.\n\n"
        "## Tarea\n\n"
        f"{task}\n"
    )


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True, help="Descripcion de la tarea")
    parser.add_argument("--task-id", help="ID estable (default: slug de --task)")
    parser.add_argument("--repo", default=".", help="Raiz del repo (default: .)")
    parser.add_argument("--output", default=".agent/cloud_bundle.md")
    parser.add_argument("--manifest", default=".agent/cloud_manifest.json")
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--allowed-tools", default="Read,Grep,Glob")
    parser.add_argument(
        "--branch",
        help="Rama de trabajo (default: cloud/<task-id>)",
    )
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    task_id = args.task_id or _slug(args.task)
    branch = args.branch or f"cloud/{task_id}"
    commit = _git_value(repo, "rev-parse", "HEAD")
    base_branch = _git_value(repo, "rev-parse", "--abbrev-ref", "HEAD")
    bundle = build_bundle(
        args.task, task_id, commit, branch, args.model, args.allowed_tools
    )
    bundle_path = repo / args.output
    manifest_path = repo / args.manifest
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(bundle, encoding="utf-8", newline="\n")
    manifest = {
        "task_id": task_id,
        "task": args.task,
        "commit": commit,
        "base_branch": base_branch,
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
    short_sha = manifest["bundle_sha256"][:8]
    print(f"[OK] bundle: {bundle_path}")
    print(f"[OK] manifest: {manifest_path}")
    print(f"[OK] task_id: {task_id}")
    print(f"[OK] branch: {branch}")
    print(f"[OK] sha256: {manifest['bundle_sha256']}")
    print()
    print("Runbook (una accion por linea):")
    print(f"1. cd {repo}")
    print(f"2. git switch -c {branch}  # o git switch {branch} si ya existe")
    print(f"3. git push -u origin {branch}")
    print("4. Remove-Item Env:ANTHROPIC_API_KEY -ErrorAction SilentlyContinue")
    print(
        f'5. claude --cloud "Lee {bundle_path.relative_to(repo)} '
        f'(sha256 {short_sha}), trabaja en {branch}, no toques main"'
    )
    print("6. Copia la URL de la sesion que muestra y pegala al agente.")
    print()
    print("Follow-up programatico (cuando el agente tenga el session_id):")
    print(
        f"claude -p --cloud <session_id> --output-format json "
        f'"Continua la tarea {task_id} del bundle (sha256 {short_sha})"'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
