# ruff: noqa: S603, S607
# ruff: noqa: S603,S607
"""
Orquestador multi-agente v2.2

[DEPRECATED - WT-2026-254a] Goose y Claw estan deprecados como motores de
orquestacion. Claude Code es el backend IA principal. Este script se conserva
solo por compatibilidad historica; NO usar en proyectos nuevos.

Patron legacy (historico, no recomendado):
    Claude Code (supervisor) -> orquestador.py -> goose | claw

Engines legacy (DEPRECATED, no usar):
    goose  - legacy/deprecated (antes "estable")
    claw   - legacy/deprecated (antes "experimental")

Engine excluido:
    claude - Claude Code no puede invocarse a si mismo desde una sesion activa
             (recursion / TTY hang). Si necesitas invocar claude desde terminal
             externa, usa un script separado con flag --experimental-claude.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from abc import ABC, abstractmethod
from contextlib import suppress
from datetime import datetime
from pathlib import Path


TIMEOUT_SECONDS = 300
LOG_DIR = Path(".agent/logs")
ALLOWLIST_PATH = Path(".agent_allowlist.json")
DENYLIST_PATH = Path(".agent_denylist.json")
CREDENTIAL_PATTERN = re.compile(
    r"(password|token|secret|api_key|api-key|auth|bearer|sk-ant|sk-[a-z])\s*[:=]",
    re.IGNORECASE,
)


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


def read_json_file(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def sanitize_context(text: str) -> str:
    """Elimina lineas con patrones de credenciales antes de pasar a agentes externos."""
    lines = text.splitlines()
    clean = [ln for ln in lines if not CREDENTIAL_PATTERN.search(ln)]
    removed = len(lines) - len(clean)
    if removed:
        clean.append(
            f"\n[SANITIZER: {removed} linea(s) omitida(s) por politica de seguridad]"
        )
    return "\n".join(clean)


def git_changed_files() -> list[str]:
    """Devuelve lista de archivos modificados respecto a HEAD (o todos si no hay HEAD)."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            shell=False,
        )
        if result.returncode == 0:
            return [f for f in result.stdout.splitlines() if f.strip()]
        # Repo sin commits aun
        result2 = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
            shell=False,
        )
        return [ln[3:].strip() for ln in result2.stdout.splitlines() if ln.strip()]
    except Exception:
        return []


def write_log(
    engine: str,
    mode: str,
    exit_code: int,
    stdout: str,
    stderr: str,
    duration: float,
    files_before: list[str],
    files_after: list[str],
) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"orquestador_{ts}_{engine}_{mode}.json"
    files_touched = sorted(set(files_after) - set(files_before))
    entry = {
        "timestamp": ts,
        "engine": engine,
        "mode": mode,
        "exit_code": exit_code,
        "duration_s": round(duration, 2),
        "files_touched": files_touched,
        "stdout": stdout[:4000],
        "stderr": stderr[:2000],
    }
    log_path.write_text(
        json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f">> Log guardado: {log_path}")
    if files_touched:
        print(f">> Archivos tocados por el agente ({len(files_touched)}):")
        for f in files_touched:
            print(f"     {f}")


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------


class AdapterBase(ABC):
    experimental: bool = False

    @abstractmethod
    def build_cmd(self, prompt_ref: str) -> list[str]:
        """Devuelve la lista de argumentos para subprocess."""

    def run(self, prompt_ref: str, env: dict) -> subprocess.CompletedProcess:
        cmd = self.build_cmd(prompt_ref)
        print(f">> CMD: {' '.join(cmd)}")
        return subprocess.run(
            cmd,
            env=env,
            timeout=TIMEOUT_SECONDS,
            capture_output=True,
            text=True,
            encoding="utf-8",
            shell=False,
        )

    @property
    def install_hint(self) -> str:
        return "Asegurate de que el binario este en el PATH del sistema."


class GooseAdapter(AdapterBase):
    def build_cmd(self, prompt_ref: str) -> list[str]:
        return [
            "goose",
            "run",
            "--text",
            prompt_ref,
            "--no-session",
            "-q",
            "--output-format",
            "text",
        ]

    @property
    def install_hint(self) -> str:
        # [DEPRECATED - WT-2026-254a] Goose es un motor legacy retirado. No se
        # dan instrucciones de instalacion: Claude Code es el backend principal.
        return (
            "[DEPRECATED - WT-2026-254a] El motor Goose esta deprecado y no se "
            "soporta su instalacion. Usa Claude Code como backend principal."
        )


class ClawAdapter(AdapterBase):
    experimental = True

    def build_cmd(self, prompt_ref: str) -> list[str]:
        return ["claw", "prompt", "--output-format", "text", prompt_ref]

    @property
    def install_hint(self) -> str:
        # [DEPRECATED - WT-2026-254a] Claw es un motor legacy retirado. No se
        # dan instrucciones de compilacion: Claude Code es el backend principal.
        return (
            "[DEPRECATED - WT-2026-254a] El motor Claw esta deprecado y no se "
            "soporta su compilacion. Usa Claude Code como backend principal."
        )


ADAPTERS: dict[str, AdapterBase] = {
    "goose": GooseAdapter(),
    "claw": ClawAdapter(),
}


# ---------------------------------------------------------------------------
# Skills Discovery
# ---------------------------------------------------------------------------


def discover_available_skills() -> dict:
    """
    Ejecuta discover_skills.py y retorna el trigger_map.
    Si discover_skills falla o no existe, retorna dict vacío.
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
# Payload
# ---------------------------------------------------------------------------


def build_payload(instruction: str, mode: str) -> str:
    raw_plan = read_file_safe(".agent/collaboration/work_plan.md")
    plan_section = sanitize_context(raw_plan) if raw_plan else "(sin plan activo)"
    allowlist = read_json_file(ALLOWLIST_PATH)
    denylist = read_json_file(DENYLIST_PATH)

    policy_section = (
        "[POLITICA LOCAL]\n"
        f"- mode: {mode}\n"
        f"- allowlist: {json.dumps(allowlist, ensure_ascii=False)}\n"
        f"- denylist: {json.dumps(denylist, ensure_ascii=False)}\n"
    )

    if mode == "research":
        mode_rules = (
            "[RESTRICCIONES DE MODO]\n"
            "- MODO RESEARCH: solo lectura.\n"
            "- No modifiques archivos.\n"
            "- No ejecutes instalaciones.\n"
            "- No hagas git push, reset, clean, commit ni cambios persistentes.\n"
            "- Devuelve hallazgos, plan o diff propuesto en texto.\n"
        )
    else:
        mode_rules = (
            "[RESTRICCIONES DE MODO]\n"
            "- MODO WRITE: puedes editar solo dentro del workspace actual.\n"
            "- No toques secretos, .env, privada/, .ssh ni archivos protegidos.\n"
            "- No uses comandos destructivos ni git push/reset/clean.\n"
        )

    # NUEVO: Cargar trigger_map
    trigger_map = discover_available_skills()
    skills_section = ""
    if trigger_map:
        skills_section = "\n---\n[SKILLS DISPONIBLES POR TRIGGER]\n"
        for trigger, info in trigger_map.items():
            skills_section += f"- {trigger:<20} -> {info}\n"

    return (
        "INSTRUCCIONES PARA EL AGENTE\n"
        "---\n"
        "[CONTEXTO: WORK PLAN ACTIVO]\n"
        f"{plan_section}\n\n"
        "---\n"
        f"{policy_section}\n"
        "---\n"
        f"{mode_rules}"
        f"{skills_section}\n"
        "---\n"
        "[TAREA PRINCIPAL]\n"
        f"{instruction}\n"
    )


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------


def print_dry_run(engine_name: str, instruction: str, mode: str) -> None:
    adapter = ADAPTERS[engine_name]
    payload = build_payload(instruction, mode)
    allowlist = read_json_file(ALLOWLIST_PATH)
    denylist = read_json_file(DENYLIST_PATH)

    dummy_ref = f"<tempfile>.md  [{len(payload)} chars]"
    cmd = adapter.build_cmd(dummy_ref)

    print("\n" + "=" * 60)
    print("  DRY-RUN — nada sera ejecutado")
    print("=" * 60)
    print(
        f"\nENGINE   : {engine_name} {'(experimental)' if adapter.experimental else '(estable)'}"
    )
    print(f"MODE     : {mode}")
    print(f"\nCMD      : {' '.join(cmd)}")
    print("\nPOLITICA :")
    print(f"  allowlist = {json.dumps(allowlist, ensure_ascii=False)}")
    print(f"  denylist  = {json.dumps(denylist, ensure_ascii=False)}")
    print(f"\nPAYLOAD  : {len(payload)} chars")
    print("-" * 40)
    preview = payload[:800]
    print(preview)
    if len(payload) > 800:
        print(f"... [{len(payload) - 800} chars mas]")
    print("-" * 40)
    print("\n[DRY-RUN completado. Usa sin --dry-run para ejecutar.]\n")


# ---------------------------------------------------------------------------
# Supervisor
# ---------------------------------------------------------------------------


def run_supervisor(engine_name: str, instruction: str, mode: str) -> int:
    adapter = ADAPTERS[engine_name]

    if adapter.experimental:
        print(f"AVISO: '{engine_name}' es experimental. El contrato CLI puede cambiar.")

    payload = build_payload(instruction, mode)
    files_before = git_changed_files()

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write(payload)
            tmp_path = f.name
        print(f">> Payload ({len(payload)} chars) escrito en: {tmp_path}")

        prompt_ref = (
            f"Lee y ejecuta con precision el archivo de instrucciones: {tmp_path}"
        )

        t0 = datetime.now()
        try:
            result = adapter.run(prompt_ref, env=os.environ.copy())
        except FileNotFoundError:
            print(f"\nERROR: Binario '{engine_name}' no encontrado en PATH.")
            print(f"-> {adapter.install_hint}")
            return 127
        except subprocess.TimeoutExpired:
            print(
                f"\nERROR: Timeout ({TIMEOUT_SECONDS}s) superado para '{engine_name}'."
            )
            return 124

        duration = (datetime.now() - t0).total_seconds()
        files_after = git_changed_files()

        if result.stdout:
            print("\n--- SALIDA DEL AGENTE ---")
            print(result.stdout)
        if result.stderr:
            print("\n--- STDERR ---")
            print(result.stderr)

        write_log(
            engine_name,
            mode,
            result.returncode,
            result.stdout or "",
            result.stderr or "",
            duration,
            files_before,
            files_after,
        )

        if result.returncode != 0:
            print(f"\nERROR: {engine_name} termino con codigo {result.returncode}.")
        else:
            print(f"\n>> Ejecucion completada en {duration:.1f}s (exit 0).")

        return result.returncode  # return 0 = real execution success

    finally:
        if tmp_path and Path(tmp_path).exists():
            with suppress(Exception):
                Path(tmp_path).unlink()


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
        print(f">> Instrucción: {instruction}")
        print("=" * 60)

        # Extraer sección Workflow
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
            print("ERROR: Skill no tiene sección 'Workflow'")
            return 1

        if workflow_end is None:
            workflow_end = len(lines)

        # Mostrar Workflow
        workflow_lines = lines[workflow_start:workflow_end]
        for line in workflow_lines:
            print(line)

        print("\n" + "=" * 60)
        print(">> Skill ejecutada correctamente. Implementación manual requerida.")
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
        description="[DEPRECATED - WT-2026-254a] Orquestador multi-agente v2.2 "
        "(motores Goose/Claw, legacy). Claude Code es el backend principal."
    )
    parser.add_argument(
        "--engine",
        choices=list(ADAPTERS.keys()),
        help="[DEPRECATED - WT-2026-254a] Engine legacy a invocar: goose | claw. "
        "Deprecados; Claude Code es el backend principal. No usar en proyectos nuevos.",
    )
    parser.add_argument(
        "--skill",
        type=str,
        help="Trigger de skill a ejecutar directamente (ej: /implement, /review)",
    )
    parser.add_argument("--query", type=str, help="Instruccion de texto directa")
    parser.add_argument("--file", type=str, help="Archivo .md/.txt con la instruccion")
    parser.add_argument(
        "--mode",
        choices=["research", "write"],
        default="research",
        help="research = solo lectura (default); write = edicion acotada al workspace",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Muestra engine, payload, politica y comando sin ejecutar nada",
    )
    args = parser.parse_args()

    instruction = args.query
    if args.file:
        instruction = read_file_safe(args.file)

    if not instruction:
        print("Error: proporciona --query o --file.")
        sys.exit(1)

    # Validar argumentos mutuamente excluyentes
    if args.skill and args.engine:
        print("Error: --skill y --engine son mutuamente excluyentes.")
        sys.exit(1)
    elif not args.skill and not args.engine:
        print("Error: proporciona --skill o --engine.")
        sys.exit(1)

    if args.skill:
        print("=" * 60)
        print(f"  ORQUESTADOR v2.2  ->  skill: {args.skill}")
        print("=" * 60)

        exit_code = execute_skill(args.skill, instruction)
        sys.exit(exit_code)
    else:
        print("=" * 60)
        print(
            f"  ORQUESTADOR v2.2  ->  engine: {args.engine.upper()}  ->  mode: {args.mode.upper()}"
        )
        print("=" * 60)

        if args.dry_run:
            print_dry_run(args.engine, instruction, args.mode)
            # Intentional exit: dry-run shows payload without executing agents (return 0 = previsualizacion satisfactoria).
            sys.exit(0)

        exit_code = run_supervisor(args.engine, instruction, args.mode)
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
