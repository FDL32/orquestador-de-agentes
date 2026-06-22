"""Gate de publicacion pre-push para repo_destino.

Before:
    Se invoca desde el repo_destino con --project-root apuntando al workspace activo
    y --motor-root apuntando al repo_motor. Si --motor-root se omite, el script
    intenta resolverlo desde motor_destination_link.json o el entorno.

During:
    1. Corre agent_controller.py --validate --json --project-root <destino>.
    2. Si hay errors > 0: imprime diagnostico con comando de reproduccion y sale con exit 1.
    3. Si errors = 0 pero STATE.md muestra STATUS = APPROVED: imprime aviso de estado
       pre-Builder no publicable y sale con exit 2.
    4. Si errors = 0 y estado publicable (READY_FOR_REVIEW, COMPLETED, IDLE, etc.): exit 0.

After:
    exit 0 = publicable.
    exit 1 = drift detectado; publicacion bloqueada.
    exit 2 = APPROVED pre-Builder; publicacion no recomendada (aviso, no error duro).
    exit 3 = error de configuracion (motor no encontrado, validate no ejecutable).

Uso:
    python <MOTOR_ROOT>/scripts/check_destino_publish_ready.py \\
        --project-root <repo_destino> \\
        --motor-root <repo_motor>

Integracion CI (GitHub Actions):
    - name: Gate pre-push destino
      run: |
        python _motor/scripts/check_destino_publish_ready.py \\
          --project-root . \\
          --motor-root _motor
      # exit 1 falla el job; exit 2 produce advertencia (considera || true si quieres solo avisar)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


_NOT_PUBLISHABLE_STATUSES = {"APPROVED"}
# WOT-2026-013n: honest non-success terminals (SUPERSEDED, BLOCKED_FINAL) are
# publishable like COMPLETED — a ticket closed honestly does not block publish.
_PUBLISHABLE_STATUSES = {
    "COMPLETED",
    "SUPERSEDED",
    "BLOCKED_FINAL",
    "READY_FOR_REVIEW",
    "IDLE",
    "BLOCKED",
}


def _resolve_motor_root(project_root: Path, motor_root_arg: str | None) -> Path | None:
    if motor_root_arg:
        p = Path(motor_root_arg)
        return p if p.exists() else None
    link = project_root / ".agent" / "config" / "motor_destination_link.json"
    if link.exists():
        try:
            data = json.loads(link.read_text(encoding="utf-8"))
            candidate = Path(data.get("motor_root", ""))
            if candidate.exists():
                return candidate
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _run_validate(motor_root: Path, project_root: Path) -> tuple[int, dict]:
    controller = motor_root / ".agent" / "agent_controller.py"
    if not controller.exists():
        return 3, {"error": f"agent_controller.py not found at {controller}"}
    try:
        result = subprocess.run(  # noqa: S603
            [
                sys.executable,
                str(controller),
                "--validate",
                "--json",
                "--project-root",
                str(project_root),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        raw = result.stdout.strip()
        if not raw:
            return 3, {"error": "validate produced no output", "stderr": result.stderr}
        return result.returncode, json.loads(raw)
    except subprocess.TimeoutExpired:
        return 3, {"error": "validate timed out after 60s"}
    except json.JSONDecodeError as exc:
        return 3, {"error": f"validate output not JSON: {exc}"}
    except FileNotFoundError:
        return 3, {"error": "Python interpreter not found"}


def _read_status(project_root: Path) -> str:
    state_file = project_root / ".agent" / "collaboration" / "STATE.md"
    if not state_file.exists():
        return "UNKNOWN"
    for line in state_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("STATUS:"):
            return line.split(":", 1)[1].strip()
    return "UNKNOWN"


def _count_errors(validate_data: dict) -> int:
    errors = validate_data.get("errors", {})
    return sum(len(v) for v in errors.values())


def _format_errors(validate_data: dict) -> list[str]:
    lines = []
    lines.extend(
        f"  [{category}] {item}"
        for category, items in validate_data.get("errors", {}).items()
        for item in items
    )
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Gate de publicacion pre-push para repo_destino.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--project-root",
        required=True,
        help="Ruta al repo_destino (workspace activo).",
    )
    parser.add_argument(
        "--motor-root",
        default=None,
        help="Ruta al repo_motor. Si se omite, se resuelve desde motor_destination_link.json.",
    )
    args = parser.parse_args(argv)

    project_root = Path(args.project_root).resolve()
    if not project_root.exists():
        print(f"[ERROR] --project-root no existe: {project_root}", file=sys.stderr)
        return 3

    motor_root = _resolve_motor_root(project_root, args.motor_root)
    if motor_root is None:
        print(
            "[ERROR] No se pudo resolver --motor-root. "
            "Pasa --motor-root <ruta> o configura motor_destination_link.json.",
            file=sys.stderr,
        )
        return 3

    _rc, validate_data = _run_validate(motor_root, project_root)

    if "error" in validate_data:
        print(f"[ERROR] validate fallo: {validate_data['error']}", file=sys.stderr)
        if "stderr" in validate_data:
            print(validate_data["stderr"], file=sys.stderr)
        return 3

    error_count = _count_errors(validate_data)

    if error_count > 0:
        print(
            f"[BLOQUEADO] validate --json devuelve {error_count} error(s). "
            "El repo_destino no esta en estado publicable.\n"
        )
        for line in _format_errors(validate_data):
            print(line)
        print(
            "\nPara reproducir:\n"
            f"  python {motor_root / '.agent' / 'agent_controller.py'} "
            f"--validate --json --project-root {project_root}\n"
            "\nResuelve los errores antes de publicar a main."
        )
        return 1

    status = _read_status(project_root)
    if status in _NOT_PUBLISHABLE_STATUSES:
        print(
            f"[AVISO] validate 0/0 pero STATUS={status} (ticket activo pre-Builder). "
            "Un APPROVED aislado no es publicable a main.\n"
            "\nEspera a que el Builder implemente y el ticket alcance "
            "READY_FOR_REVIEW o COMPLETED antes de publicar.\n"
            "\nSi es checkpoint intencional, usa rama separada o documenta "
            "el motivo antes de publicar."
        )
        return 2

    print(
        f"[OK] validate 0/0 y STATUS={status}. El repo_destino esta en estado publicable."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
