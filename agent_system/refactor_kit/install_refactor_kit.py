#!/usr/bin/env python3
"""
Instalador del Refactor-Kit.
Copia el kit a un proyecto externo manteniendo la independencia.
"""

import argparse
import json
import shutil
import sys
from pathlib import Path


def install(project_path: str):
    dst_root = Path(project_path).resolve()
    if not dst_root.exists():
        print(f"ERROR: El directorio {dst_root} no existe.")
        return False

    # El origen es el directorio donde reside este script
    src_kit = Path(__file__).parent
    dst_kit = dst_root / ".refactor" / "kit"

    try:
        if dst_kit.exists():
            shutil.rmtree(dst_kit)

        # Copiar recursivamente ignorando caches y .refactor propio si existe
        shutil.copytree(
            src_kit,
            dst_kit,
            ignore=shutil.ignore_patterns("__pycache__", ".refactor", "*.pyc"),
        )

        # Crear config base
        config = {
            "version": "1.0.0",
            "project_name": dst_root.name,
            "default_agent": "goose",
        }
        (dst_root / ".refactor" / "config.json").write_text(
            json.dumps(config, indent=2)
        )

        print(f"[OK] Refactor-Kit instalado en: {dst_kit}")
        print(
            f"Para empezar: python {dst_kit.relative_to(dst_root)}/refactor_manager.py --target src/main.py"
        )
        return True
    except Exception as e:
        print(f"[ERROR] Error durante la instalacion: {e}")
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("project_path", help="Ruta del proyecto destino")
    args = parser.parse_args()
    sys.exit(0 if install(args.project_path) else 1)
