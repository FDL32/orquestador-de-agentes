# ruff: noqa
"""
DEPRECATED: Use install_agent_system.py --sync instead.

This script is no longer the recommended sync method.
Use: python orquestacion_agentes/scripts/install_agent_system.py --sync

This file is kept for backward compatibility only.
New projects MUST use install_agent_system.py.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path


def detect_target_version(dest: Path) -> dict:
    """
    DEPRECATED: Use install_agent_system.py --sync instead.

    This script is no longer the recommended sync method.
    Use: python orquestacion_agentes/scripts/install_agent_system.py --sync

    This file is kept for backward compatibility only.
    New projects MUST use install_agent_system.py.
    """
    try:
        from detect_agent_system_version import AgentSystemDetector

        detector = AgentSystemDetector(str(dest))
        result = detector.detect_version()
        # AÃƒÂ±adir agent_exists basado en detecciÃƒÂ³n o existence check
        agent_exists = result.get("detected", False) or (dest / ".agent").exists()
        return {
            "detected": result.get("detected", False),
            "version": result.get("version", "unknown"),
            "agent_exists": agent_exists,
            "confidence": result.get("confidence", "unknown"),
        }
    except Exception as e:
        print(f"[WARN] No se pudo detectar versiÃƒÂ³n: {e}")
        return {
            "detected": False,
            "agent_exists": (dest / ".agent").exists(),
            "version": "unknown",
        }


def find_template_from_dest(dest: Path) -> tuple[Path, str] | None:
    """
    DEPRECATED: Use install_agent_system.py --sync instead.

    This script is no longer the recommended sync method.
    Use: python orquestacion_agentes/scripts/install_agent_system.py --sync

    This file is kept for backward compatibility only.
    New projects MUST use install_agent_system.py.
    """
    search_paths = [
        ("dest-local", dest / "orquestacion_agentes"),
        ("dest-tools", dest / "tools" / "orquestacion_agentes"),
        ("dest-parent", dest.parent / "orquestacion_agentes"),
        ("dest-parent-z_scripts", dest.parent / "z_scripts" / "orquestacion_agentes"),
    ]

    for method_name, path in search_paths:
        if path.exists() and (path / ".agent" / "agent_controller.py").exists():
            return path, method_name

    return None


def find_orquestacion_template(start_path: Path | None = None) -> tuple[Path, str]:
    """
    DEPRECATED: Use install_agent_system.py --sync instead.

    This script is no longer the recommended sync method.
    Use: python orquestacion_agentes/scripts/install_agent_system.py --sync

    This file is kept for backward compatibility only.
    New projects MUST use install_agent_system.py.
    """
    if start_path:
        if (start_path / ".agent" / "agent_controller.py").exists():
            return start_path, "user-provided"
        else:
            print(
                f"[WARN] --source provided but missing .agent/agent_controller.py: {start_path}"
            )

    # Strategy 1: Relative to this script Ã¢â‚¬â€ BUSCAR plantilla en tools/orquestacion_agentes
    # Script location: <proyecto>/tools/scripts/sync_agent_core.py
    # Plantilla esperada: <proyecto>/tools/orquestacion_agentes/
    script_path = Path(__file__).resolve()
    project_root = (
        script_path.parent.parent.parent
    )  # tools/scripts -> tools -> <proyecto>
    candidate = project_root / "tools" / "orquestacion_agentes"
    if candidate.exists() and (candidate / ".agent" / "agent_controller.py").exists():
        return candidate, "script-relative"
    # No fallback aquÃƒÂ­ Ã¢â‚¬â€ si no encuentra plantilla local, pasa a Strategy 2

    # Strategy 2: Sibling directories (buscar orquestacion_agentes junto al proyecto actual)
    # project_root es el directorio que contiene el script (Crear_Texto_LLM/)
    # Buscamos en directorios hermanos de project_root
    sibling_search_root = project_root.parent  # Directorio padre de Crear_Texto_LLM/
    if sibling_search_root.exists():
        siblings = [p for p in sibling_search_root.iterdir() if p.is_dir()]
        for sibling in siblings:
            # Priorizar directorio llamado 'orquestacion_agentes' o 'z_scripts'
            if sibling.name in ("orquestacion_agentes", "z_scripts"):
                candidate_sibling = (
                    sibling / "orquestacion_agentes"
                    if sibling.name == "z_scripts"
                    else sibling
                )
                if (candidate_sibling / ".agent" / "agent_controller.py").exists():
                    return candidate_sibling, "sibling-search"

    # Strategy 3: Common paths (PROJECTS_PATHS)
    common_paths = [
        Path.home() / "Proyectos_Python" / "orquestacion_agentes",
        Path.home() / "projects" / "orquestacion_agentes",
        Path("C:/Users/fdl/Proyectos_Python/z_scripts/orquestacion_agentes"),
    ]
    for p in common_paths:
        if p.exists() and (p / ".agent" / "agent_controller.py").exists():
            return p, "common-path"

    # Strategy 4: BÃƒÂºsqueda inversa desde destino (solo si no se especificÃƒÂ³ --source)
    if start_path is None:
        # Usar Path.cwd() como destino; args.dest serÃƒÂ¡ disponible en main(), pero aquÃƒÂ­ podemos usar cwd
        inverse_result = find_template_from_dest(Path.cwd())
        if inverse_result:
            return inverse_result

    raise FileNotFoundError(
        "No se pudo detectar plantilla orquestacion_agentes.\n"
        "Buscada en:\n"
        "  - --source argumento\n"
        "  - Relativo al script (tools/orquestacion_agentes)\n"
        "  - Directorios hermanos\n"
        "  - Rutas comunes\n"
        "  - BÃƒÂºsqueda inversa desde destino\n\n"
        "Especifica --source <ruta> manualmente."
    )


def sync_with_robocopy(
    source: Path, dest: Path, dry_run: bool = False
) -> tuple[bool, str]:
    """
    DEPRECATED: Use install_agent_system.py --sync instead.

    This script is no longer the recommended sync method.
    Use: python orquestacion_agentes/scripts/install_agent_system.py --sync

    This file is kept for backward compatibility only.
    New projects MUST use install_agent_system.py.
    """
    # Ensure destinations exist
    dest.mkdir(parents=True, exist_ok=True)

    # Robocopy flags:
    # /E Ã¢â‚¬â€ Copy subdirectories, including empty ones
    # /XD Ã¢â‚¬â€ Exclude directories
    # /NFL Ã¢â‚¬â€ No file list
    # /NDL Ã¢â‚¬â€ No directory list
    # /NJH Ã¢â‚¬â€ No job header
    # /NJS Ã¢â‚¬â€ No job summary
    # /NP Ã¢â‚¬â€ No progress (% copied)
    cmd = [
        "robocopy",
        str(source),
        str(dest),
        "/E",
        "/XD",
        "collaboration",
        "__pycache__",
        "/NFL",
        "/NDL",
        "/NJH",
        "/NJS",
        "/NP",
    ]

    if dry_run:
        cmd.append("/L")  # List only, don't copy

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300, shell=False
        )
        # Robocopy returns 0-7 for success (files copied), 8+ for errors
        success = result.returncode < 8
        output = result.stdout + result.stderr
        return success, output
    except subprocess.TimeoutExpired:
        return False, "Robocopy timeout after 300 seconds"
    except FileNotFoundError:
        return False, "Robocopy not found (Windows only)"


def sync_with_shutil(
    source: Path, dest: Path, dry_run: bool = False
) -> tuple[bool, str]:
    """
    DEPRECATED: Use install_agent_system.py --sync instead.

    This script is no longer the recommended sync method.
    Use: python orquestacion_agentes/scripts/install_agent_system.py --sync

    This file is kept for backward compatibility only.
    New projects MUST use install_agent_system.py.
    """
    import shutil

    log_lines = []
    copied = 0
    skipped = 0

    try:
        for src_file in source.rglob("*"):
            if src_file.is_dir():
                continue  # Directories created on demand

            # Check exclusions
            rel = src_file.relative_to(source)
            parts = rel.parts
            if "collaboration" in parts or "__pycache__" in parts:
                skipped += 1
                continue

            dst_file = dest / rel
            if dry_run:
                log_lines.append(f"[DRY] Would copy: {rel}")
            else:
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_file, dst_file)
                log_lines.append(f"Copied: {rel}")
            copied += 1

        summary = (
            f"Sync complete: {copied} files copied, {skipped} skipped\n"
            + "\n".join(log_lines)
        )
        return True, summary
    except Exception as e:
        return False, f"shutil sync failed: {e}"


def validate_sync(dest: Path) -> dict:
    """
    DEPRECATED: Use install_agent_system.py --sync instead.

    This script is no longer the recommended sync method.
    Use: python orquestacion_agentes/scripts/install_agent_system.py --sync

    This file is kept for backward compatibility only.
    New projects MUST use install_agent_system.py.
    """
    REQUIRED_DIRS = [
        "collaboration",  # Must exist (preserved, not copied)
        "config",
        "context",
        "decisions",
        "hooks",
        "legacy",
        "logs",
        "protocols",
        "rules",
        "runtime",
        "runtime/memory",
        "templates",
        "workflows",
    ]

    CRITICAL_FILES = [
        "agent_controller.py",
        "session_tracker.py",
        "completion_checker.py",
        "hooks/guard_paths.py",
        "hooks/native_post_tool_hook.py",
        "hooks/pre_compact_hook.py",
        "hooks/native_stop_hook.py",
        "hooks/subagent_stop_hook.py",
        "runtime/memory/memory_helpers.py",
        "runtime/memory/observations.jsonl",
        "runtime/memory/MEMORY.md",
    ]

    report = {
        "total_dirs_expected": len(REQUIRED_DIRS),
        "dirs_present": 0,
        "missing_dirs": [],
        "critical_files_ok": True,
        "hook_count": 0,
        "rule_count": 0,
    }

    # Check directories
    for d in REQUIRED_DIRS:
        dir_path = dest / d
        if dir_path.exists():
            report["dirs_present"] += 1
        else:
            report["missing_dirs"].append(d)
            if d != "__pycache__":  # __pycache__ is optional
                print(f"[WARN] Missing critical dir: {d}")

    # Check critical files
    for f in CRITICAL_FILES:
        if not (dest / f).exists():
            report["critical_files_ok"] = False
            print(f"[ERROR] Missing critical file: {f}")

    # Count hooks
    hooks_dir = dest / "hooks"
    if hooks_dir.exists():
        hook_files = list(hooks_dir.glob("*.py"))
        report["hook_count"] = len(
            [f for f in hook_files if not f.name.startswith("__")]
        )

    # Count rules
    rules_dir = dest / "rules"
    if rules_dir.exists():
        for subdir in ["common", "builder", "manager"]:
            sub_path = rules_dir / subdir
            if sub_path.exists():
                report["rule_count"] += len(list(sub_path.glob("*.md")))

    return report


def print_report(
    source: Path,
    dest: Path,
    dry_run: bool,
    sync_ok: bool,
    validation: dict,
    previous_version: dict | None = None,
):
    """
    DEPRECATED: Use install_agent_system.py --sync instead.

    This script is no longer the recommended sync method.
    Use: python orquestacion_agentes/scripts/install_agent_system.py --sync

    This file is kept for backward compatibility only.
    New projects MUST use install_agent_system.py.
    """
    print("\n" + "=" * 70)
    print("  SYNC AGENT CORE Ã¢â‚¬â€ Reporte de SincronizaciÃƒÂ³n")
    print("=" * 70)
    print(f"\nOrigen:    {source}")
    print(f"Destino:   {dest}")
    print(
        f"Modo:      {'DRY-RUN (simulaciÃƒÂ³n)' if dry_run else 'EJECUCIÃƒâ€œN REAL'}"
    )
    print(f"Resultado: {'Ã¢Å“â€¦ Ãƒâ€°XITO' if sync_ok else 'Ã¢ÂÅ’ FALLÃƒâ€œ'}")

    # Comparativa de versiÃƒÂ³n (si hay versiÃƒÂ³n anterior)
    if previous_version:
        old_ver = previous_version.get("version", "?")
        print(f"\nðŸ“Š ACTUALIZACIÃ“N: {old_ver} -> v9.5")

    print("\nDirectorios sincronizados:")
    print(
        f"  Ã¢Å“â€¦ Presentes: {validation['dirs_present']}/{validation['total_dirs_expected']}"
    )
    if validation["missing_dirs"]:
        print(f"  Ã¢ÂÅ’ Faltantes: {', '.join(validation['missing_dirs'])}")

    print(f"\nHooks funcionales: {validation['hook_count']}/5")
    print(f"Reglas modulares: {validation['rule_count']} (common+builder+manager)")

    if validation["critical_files_ok"]:
        print("  Ã¢Å“â€¦ Archivos crÃƒÂ­ticos: presente")
    else:
        print("  Ã¢ÂÅ’ Archivos crÃƒÂ­ticos: faltantes")

    is_valid = (
        validation["critical_files_ok"]
        and validation["dirs_present"] >= validation["total_dirs_expected"] - 1
    )
    print(f"\nValidaciÃƒÂ³n: {'Ã¢Å“â€¦ PASS' if is_valid else 'Ã¢ÂÅ’ FAIL'}")
    print("=" * 70 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Sync Agent Core Ã¢â‚¬â€ Sincroniza nÃƒÂºcleo .agent/ desde plantilla orquestacion_agentes"
    )
    parser.add_argument(
        "--source",
        type=Path,
        help="Ruta a plantilla orquestacion_agentes (auto-detectada si no se proporciona)",
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=Path.cwd(),
        help="Ruta del proyecto destino (default: directorio actual)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simular sincronizaciÃƒÂ³n sin copiar archivos",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Forzar sincronizaciÃƒÂ³n ignorando advertencias",
    )

    args = parser.parse_args()

    # Resolve paths
    dest = args.dest.resolve()
    if not (dest / ".agent").exists():
        print(f"[ERROR] No existe .agent/ en destino: {dest}")
        print("Ejecuta desde proyecto raÃƒÂ­z o especifica --dest correcta.")
        return 1

    # === PRE-CHECK: Detectar versiÃƒÂ³n actual del destino ===
    print("[PRE-CHECK] Analizando proyecto destino...")
    current_version = detect_target_version(dest)

    agent_exists = current_version.get("agent_exists", False)
    if agent_exists:
        detected_version = current_version.get("version", "desconocida")
        print(f"[INFO] VersiÃƒÂ³n actual: {detected_version}")

        if detected_version == "v9.5":
            print("[OK] Ya estas en v9.5 (ultima version)")
            if not args.force:
                print("[INFO] Usa --force para forzar re-sincronizacion")
                return 0
        else:
            print(f"\n[INFO] Necesitas actualizacion: {detected_version} -> v9.5")
            print("\nMejor opcion?")
            print("  [1] Sincronizacion completa (robocopy, sobrescribe cambios)")
            print(
                "  [2] Upgrade inteligente (3-way merge, preserva cambios) [RECOMENDADO]"
            )
            print("  [3] Cancelar")

            if not args.force and not os.environ.get("HEADLESS"):
                try:
                    choice = input("\nSelecciona [1-3]: ").strip()
                    if choice == "2":
                        print("\n[INFO] Para upgrade con 3-way merge, usa:")
                        print("  python scripts/upgrade_agent_system.py --dry-run")
                        print("  python scripts/upgrade_agent_system.py --confirm")
                        return 0
                    elif choice == "3":
                        print("[INFO] Cancelado.")
                        return 0
                except (EOFError, KeyboardInterrupt):
                    pass  # Modo headless, continuar con sync
    else:
        print(
            "[INFO] No hay .agent/ existente Ã¢â‚¬â€ procediendo con sync (instalaciÃƒÂ³n limpia)"
        )

    try:
        source, method = find_orquestacion_template(args.source)
        print(f"[INFO] Plantilla detectada ({method}): {source}")
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
        return 1

    source_agent = source / ".agent"
    dest_agent = dest / ".agent"

    print(f"\n[SYNC] {source_agent} -> {dest_agent}")

    # Perform sync
    if sys.platform == "win32":
        sync_ok, output = sync_with_robocopy(source_agent, dest_agent, args.dry_run)
    else:
        sync_ok, output = sync_with_shutil(source_agent, dest_agent, args.dry_run)

    print(output)

    # Validate (only on real runs)
    if not args.dry_run and sync_ok:
        print("\n[VALIDATE] Ejecutando validaciÃƒÂ³n post-sync...")
        validation = validate_sync(dest_agent)

        # Print report (with version comparison)
        print_report(
            source,
            dest,
            args.dry_run,
            sync_ok,
            validation,
            current_version if agent_exists else None,
        )

        if (
            not validation["critical_files_ok"]
            or validation["dirs_present"] < validation["total_dirs_expected"]
        ):
            print("[ERROR] ValidaciÃƒÂ³n fallÃƒÂ³ Ã¢â‚¬â€ revisa los warnings above.")
            return 1
    elif args.dry_run:
        print("\n[DRY-RUN] ValidaciÃƒÂ³n omitida (simulaciÃƒÂ³n)")
    else:
        print("\n[ERROR] SincronizaciÃƒÂ³n fallÃƒÂ³ Ã¢â‚¬â€ revisa errores arriba.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
