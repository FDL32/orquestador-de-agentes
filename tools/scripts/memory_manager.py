#!/usr/bin/env python3
"""
Memory Manager - Herramienta CLI para gestionar memoria persistente del proyecto.

UbicaciÃ³n: tools/scripts/memory_manager.py
PropÃ³sito: Proporcionar interfaz de lÃ­nea de comandos para append, regenerate index y read memory.

Uso:
    python tools/scripts/memory_manager.py append --topic "arquitectura" --signal "Nueva observaciÃ³n" --source "agent"
    python tools/scripts/memory_manager.py regenerate
    python tools/scripts/memory_manager.py read
"""

import argparse
import pathlib
import sys
from datetime import datetime, timezone


def find_project_root() -> pathlib.Path:
    """Encuentra la raÃ­z del proyecto buscando hacia arriba hasta encontrar .agent/"""
    current = pathlib.Path(__file__).resolve()
    for parent in [current, *current.parents]:
        if (parent / ".agent").exists():
            return parent
    raise RuntimeError(
        "No se pudo encontrar la raÃ­z del proyecto (.agent/ no encontrado)"
    )


def _setup_argument_parser() -> argparse.ArgumentParser:
    """Setup the argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        description="Gestor de memoria persistente del proyecto",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos de uso:

# Registrar una observaciÃ³n
python tools/scripts/memory_manager.py append --topic "arquitectura" --signal "Implementada nueva funcionalidad" --source "builder"

# Regenerar el Ã­ndice de memoria
python tools/scripts/memory_manager.py regenerate

# Leer todas las observaciones
python tools/scripts/memory_manager.py read

# Mostrar ayuda
python tools/scripts/memory_manager.py --help
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Comandos disponibles")

    # Append command
    append_parser = subparsers.add_parser(
        "append", help="Registrar una nueva observaciÃ³n"
    )
    append_parser.add_argument(
        "--topic",
        required=True,
        help="CategorÃ­a de la observaciÃ³n (e.g., arquitectura, bug, aprendizaje)",
    )
    append_parser.add_argument(
        "--signal", required=True, help="DescripciÃ³n breve de la observaciÃ³n"
    )
    append_parser.add_argument(
        "--source",
        required=True,
        help="Origen de la observaciÃ³n (e.g., agent, usuario, test)",
    )

    # Regenerate command
    subparsers.add_parser(
        "regenerate", help="Regenerar el Ã­ndice MEMORY.md desde observations.jsonl"
    )

    # Read command
    subparsers.add_parser("read", help="Leer todas las observaciones")

    return parser


def _initialize_memory_helpers():
    """Initialize and import memory helpers."""
    project_root = find_project_root()
    memory_helpers_path = (
        project_root / ".agent" / "runtime" / "memory" / "memory_helpers.py"
    )
    if not memory_helpers_path.exists():
        raise FileNotFoundError(
            f"No se encontrÃ³ memory_helpers.py en {memory_helpers_path}"
        )

    sys.path.insert(0, str(memory_helpers_path.parent))
    import memory_helpers

    return memory_helpers


def _handle_append_command(memory_helpers, args) -> int:
    """Handle the append command."""
    observation = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "topic": args.topic,
        "signal": args.signal,
        "source": args.source,
    }

    if memory_helpers.append_observation(observation):
        print("Observacion registrada exitosamente")
        return 0
    else:
        print("Error al registrar observacion")
        return 1


def _handle_regenerate_command(memory_helpers) -> int:
    """Handle the regenerate command."""
    if memory_helpers.create_memory_index():
        print("Indice de memoria regenerado exitosamente")
        return 0
    else:
        print("Error al regenerar indice de memoria")
        return 1


def _handle_read_command(memory_helpers) -> int:
    """Handle the read command."""
    observations = memory_helpers.read_observations()
    if observations:
        print(f"Memoria del proyecto ({len(observations)} observaciones):\n")
        for obs in observations:
            print(
                f"[{obs['timestamp']}] {obs['topic'].upper()}: {obs['signal']} (fuente: {obs['source']})"
            )
        print(
            "\nPara regenerar el indice legible, ejecuta: python tools/scripts/memory_manager.py regenerate"
        )
    else:
        print("No hay observaciones registradas aun.")
    return 0


def main():
    parser = _setup_argument_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    try:
        memory_helpers = _initialize_memory_helpers()
    except Exception as e:
        print(f"Error al inicializar: {e}")
        return 1

    try:
        command_handlers = {
            "append": _handle_append_command,
            "regenerate": _handle_regenerate_command,
            "read": _handle_read_command,
        }

        handler = command_handlers.get(args.command)
        if handler:
            return (
                handler(memory_helpers, args)
                if args.command == "append"
                else handler(memory_helpers)
            )
        else:
            print(f"Comando desconocido: {args.command}")
            return 1

    except Exception as e:
        print(f"Error ejecutando comando '{args.command}': {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
