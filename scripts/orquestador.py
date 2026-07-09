# ruff: noqa: S603
"""
Orquestador de skills v3.0

Lanzador de skills locales del sistema multi-agente. Descubre las skills
disponibles (via discover_skills.py) y ejecuta la seleccionada mostrando su
seccion Workflow.

Patron:
    Claude Code (supervisor) -> orquestador.py --skill <trigger>

Historico: las versiones previas (v2.x) incluian motores externos Goose/Claw
(retirados en WOT-2026-020n por ser codigo muerto). Claude Code es el backend
IA principal; la ejecucion de skills es la unica ruta soportada.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def read_file_safe(path: str) -> str:
    p = Path(path)
    if p.exists():
        try:
            return p.read_text(encoding="utf-8")
        except Exception:  # noqa: S110
            pass
    return ""


# ---------------------------------------------------------------------------
# Skills Discovery
# ---------------------------------------------------------------------------


def discover_available_skills() -> dict:
    """
    Ejecuta discover_skills.py y retorna el trigger_map.
    Si discover_skills falla o no existe, retorna dict vacio.
    """
    try:
        discover_script = Path(__file__).parent / "discover_skills.py"
        if not discover_script.exists():
            print(
                f"DEBUG: discover_skills.py not found at {discover_script}",
                file=sys.stderr,
            )
            return {}

        result = subprocess.run(
            [sys.executable, str(discover_script), "--json"],
            capture_output=True,
            text=True,
            timeout=10,
            shell=False,
        )
        if result.returncode != 0:
            print(
                f"DEBUG: discover_skills.py failed with return code {result.returncode}",
                file=sys.stderr,
            )
            print(f"DEBUG: stderr: {result.stderr}", file=sys.stderr)
            return {}

        data = json.loads(result.stdout)
        trigger_map = data.get("trigger_map", {})
        print(
            f"DEBUG: trigger_map received: {len(trigger_map)} triggers", file=sys.stderr
        )
        return trigger_map
    except Exception as e:
        print(f"DEBUG: Exception in discover_available_skills: {e}", file=sys.stderr)
        return {}


# ---------------------------------------------------------------------------
# Skill execution
# ---------------------------------------------------------------------------


def execute_skill(skill_trigger: str, instruction: str) -> int:
    """
    Ejecuta una skill directamente sin pasar por agente externo.
    Flujo: trigger_map -> SKILL.md -> [Workflow] -> Output
    """
    try:
        trigger_map = discover_available_skills()
        if skill_trigger not in trigger_map:
            print(f"ERROR: Trigger '{skill_trigger}' no encontrado.")
            print(f"Triggers disponibles: {', '.join(sorted(trigger_map.keys()))}")
            return 1

        skill_path_str = trigger_map[skill_trigger]
        script_dir = Path(__file__).parent
        agent_system_dir = script_dir.parent
        skill_path = agent_system_dir / skill_path_str

        if not skill_path.exists():
            print(f"ERROR: Archivo skill no encontrado: {skill_path}")
            return 1

        skill_content = skill_path.read_text(encoding="utf-8")

        skill_name = skill_path.parent.name
        print(f">> Ejecutando skill: {skill_name}")
        print(f">> Archivo: {skill_path}")
        print(f">> Instruccion: {instruction}")
        print("=" * 60)

        # Extraer seccion Workflow
        lines = skill_content.split("\n")
        workflow_start = None
        workflow_end = None

        for i, line in enumerate(lines):
            if line.strip().startswith("## Workflow"):
                workflow_start = i
            elif (
                workflow_start is not None
                and line.startswith("##")
                and "Workflow" not in line
            ):
                workflow_end = i
                break

        if workflow_start is None:
            print("ERROR: Skill no tiene seccion 'Workflow'")
            return 1

        if workflow_end is None:
            workflow_end = len(lines)

        # Mostrar Workflow
        workflow_lines = lines[workflow_start:workflow_end]
        for line in workflow_lines:
            print(line)

        print("\n" + "=" * 60)
        print(">> Skill ejecutada correctamente. Implementacion manual requerida.")
        # Intentional exit: skill mode exposes workflow without full execution (return 0 = salida informativa).
        return 0

    except Exception as e:
        print(f"ERROR ejecutando skill: {e}")
        return 1


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="Orquestador de skills v3.0. Ejecuta una skill local por su "
        "trigger. Claude Code es el backend principal."
    )
    parser.add_argument(
        "--skill",
        type=str,
        help="Trigger de skill a ejecutar directamente (ej: /implement, /review)",
    )
    parser.add_argument("--query", type=str, help="Instruccion de texto directa")
    parser.add_argument("--file", type=str, help="Archivo .md/.txt con la instruccion")
    args = parser.parse_args()

    instruction = args.query
    if args.file:
        instruction = read_file_safe(args.file)

    if not instruction:
        print("Error: proporciona --query o --file.")
        sys.exit(1)

    if not args.skill:
        print("Error: proporciona --skill.")
        sys.exit(1)

    print("=" * 60)
    print(f"  ORQUESTADOR v3.0  ->  skill: {args.skill}")
    print("=" * 60)

    exit_code = execute_skill(args.skill, instruction)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
