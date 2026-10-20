"""Generate run_manifest.json for repo audit reproducibility (OPT-05).

Ejecuta todas las herramientas de Fase 1 del prompt repo_audit_multiagent,
registra versiones, estados y salidas, y genera el hash del entorno.

Uso:
    python scripts/audit_manifest.py --repo <ruta> --ticket <id>
    python scripts/audit_manifest.py --repo . --ticket TEST-001

Salida:
    .agent/runtime/audit/repo_audit/_meta/run_manifest.json
"""

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_TOOLS = [
    "ruff",
    "gitleaks",
    "pytest",
    "vulture",
    "pip-audit",
    "semgrep",
    "mypy",
    "bandit",
]

META_DIR = Path(".agent/runtime/audit/repo_audit/_meta")


def run_cmd(cmd: list[str], cwd: Path, timeout: int = 60) -> tuple[int, str, str]:
    """Ejecuta un comando y retorna (exit_code, stdout, stderr)."""
    try:
        result = subprocess.run(  # noqa: S603
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError:
        return -1, "", "comando no encontrado"
    except subprocess.TimeoutExpired:
        return -2, "", "timeout excedido"


def get_version(tool: str, cwd: Path) -> str | None:
    """Intenta obtener la version de una herramienta."""
    version_flags = {
        "ruff": ["ruff", "--version"],
        "gitleaks": ["gitleaks", "version"],
        "pytest": ["pytest", "--version"],
        "vulture": ["vulture", "--version"],
        "pip-audit": ["pip-audit", "--version"],
        "semgrep": ["semgrep", "--version"],
        "mypy": ["mypy", "--version"],
        "bandit": ["bandit", "--version"],
    }

    flags = version_flags.get(tool, [tool, "--version"])
    rc, stdout, _ = run_cmd(flags, cwd)

    if rc == 0 and stdout.strip():
        # Extraer solo la version del output
        lines = stdout.strip().splitlines()
        first_line = lines[0]
        # Patrones comunes: "ruff 0.17.1", "pytest 8.x", etc.
        parts = first_line.split()
        for part in parts:
            if part[0].isdigit() or part.startswith("v"):
                return part
        return first_line[:80]  # fallback: primer pedazo
    return None


def compute_env_hash(repo_path: Path) -> str:
    """Genera hash unico del entorno para reproducibilidad."""
    components = [
        platform.system(),
        platform.release(),
        platform.machine(),
        platform.python_version(),
        str(repo_path.resolve()),
        datetime.now(timezone.utc).isoformat(),
    ]
    raw = "|".join(components)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def check_pyproject_repo(repo_path: Path) -> list[str]:
    """Detecta herramientas listadas en pyproject.toml."""
    tools_found = []

    pyproject = repo_path / "pyproject.toml"
    if pyproject.exists():
        content = pyproject.read_text()
        tool_sections = [
            ("semgrep", "semgrep"),
            ("ruff", "ruff"),
        ]
        for label, search in tool_sections:
            if search in content.lower():
                tools_found.append(label)

    return tools_found


def run_tool(tool: str, repo_path: Path) -> dict[str, Any]:
    """Ejecuta una herramienta y retorna su estado."""
    result: dict[str, Any] = {"status": "unknown", "version": None, "output": ""}

    version = get_version(tool, repo_path)
    if version is None:
        result["status"] = "skipped"
        result["reason"] = "herramienta no instalada"
        return result

    result["version"] = version

    # Comandos por herramienta
    commands = {
        "ruff": [
            ["ruff", "check", "."],
            ["ruff", "format", "--check", "."],
        ],
        "gitleaks": [
            ["gitleaks", "detect", "--source", str(repo_path), "--no-banner"],
        ],
        "pytest": [
            ["pytest", "-q", "--tb=short"],
        ],
        "vulture": [
            ["vulture", ".", "--min-confidence=80"],
        ],
        "pip-audit": [
            ["pip-audit"],
        ],
        "semgrep": [
            ["semgrep", "--config=auto", "."],
        ],
        "mypy": [
            ["mypy", "."],
        ],
        "bandit": [
            ["bandit", "-r", "."],
        ],
    }

    cmds = commands.get(tool, [[tool, "--help"]])

    for cmd in cmds:
        rc, stdout, stderr = run_cmd(cmd, repo_path)

        if rc == 0:
            result["status"] = "executed"
            result["output"] = (stdout or stderr)[:2000]
            result["exit_code"] = rc
            return result
        elif rc == -1:
            result["status"] = "skipped"
            result["reason"] = "herramienta no instalada"
            break
        else:
            # Herramienta existe pero fallo (warnings, errors, etc.)
            if "No security" not in (stdout or ""):
                result["status"] = "executed"
                result["output"] = (stdout or stderr)[:2000]
                result["exit_code"] = rc
                return result

    return result


def build_manifest(
    repo_path: Path,
    ticket: str,
    tools: list[str] | None = None,
) -> dict[str, Any]:
    """Construye el manifest completo."""
    if tools is None:
        tools = list(DEFAULT_TOOLS)

    # Detectar herramientas adicionales via pyproject.toml
    pyproject_tools = check_pyproject_repo(repo_path)
    for t in pyproject_tools:
        if t not in tools:
            tools.append(t)

    commit_sha = ""
    if (repo_path / ".git").exists():
        rc, stdout, _ = run_cmd(["git", "rev-parse", "HEAD"], repo_path)
        if rc == 0:
            commit_sha = stdout.strip()[:12]

    tool_results: dict[str, Any] = {}
    executed_count = 0
    skipped_count = 0

    for tool in tools:
        tool_result = run_tool(tool, repo_path)
        tool_results[tool] = tool_result

        if tool_result["status"] == "executed":
            executed_count += 1
        elif tool_result["status"] == "skipped":
            skipped_count += 1

    manifest = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "commit_sha": commit_sha,
        "repo": str(repo_path.resolve()),
        "ticket": ticket,
        "env_hash": compute_env_hash(repo_path),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.system(),
            "platform_release": platform.release(),
            "machine": platform.machine(),
        },
        "tools": tool_results,
        "summary": {
            "tools_executed": executed_count,
            "tools_skipped": skipped_count,
            "total_configured": len(tools),
        },
    }

    return manifest


def save_manifest(manifest: dict[str, Any], output_dir: Path) -> Path:
    """Guarda el manifest en el filesystem."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "run_manifest.json"
    output_file.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    return output_file


def main():
    parser = argparse.ArgumentParser(
        description="Genera manifest de herramientas para reproducibilidad de auditoria."
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path("."),
        help="Ruta al repo a auditar (default: cwd)",
    )
    parser.add_argument(
        "--ticket",
        type=str,
        default="UNSPECIFIED",
        help="ID del ticket/auditoria",
    )
    parser.add_argument(
        "--tools",
        nargs="+",
        default=None,
        help="Herramientas especificas (default: todas las conocidas)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=META_DIR,
        help="Directorio de salida (default: .agent/runtime/audit/repo_audit/_meta)",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Imprimir manifest a stdout ademas de guardar",
    )

    args = parser.parse_args()

    if not args.repo.exists():
        print(f"ERROR: repo no existe: {args.repo}", file=sys.stderr)
        sys.exit(1)

    print(f"[audit_manifest] Escaneando {args.repo}...")

    manifest = build_manifest(args.repo, args.ticket, args.tools)

    output_file = save_manifest(manifest, args.output_dir)

    if args.stdout:
        print(json.dumps(manifest, indent=2, ensure_ascii=False))

    print(f"[audit_manifest] Manifest guardado: {output_file}")
    print(
        f"[audit_manifest] Resumen: {manifest['summary']['tools_executed']} "
        f"ejecutadas, {manifest['summary']['tools_skipped']} omitidas, "
        f"{manifest['summary']['total_configured']} configuradas"
    )
    print(f"[audit_manifest] env_hash: {manifest['env_hash']}")


if __name__ == "__main__":
    main()
