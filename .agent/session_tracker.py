"""Session Tracker Lite para proyectos pequenos (<30 archivos).

Version simplificada de Session Recovery optimizada para uso local
con proyectos pequenos. No usa hashes MD5 complejos.

WP-2026-122: Uses runtime.project_root for dynamic project root resolution.

Uso:
    from .session_tracker import save_session, detect_stale_session, recover_session

    # Al finalizar
    save_session()

    # Al iniciar (detectar sesion antigua)
    if detect_stale_session():
        recover_session()
"""

from __future__ import annotations

import json
from contextlib import suppress
from datetime import datetime, timedelta
from pathlib import Path


# WP-2026-122: Deferred path resolution via runtime.project_root
try:
    from runtime.project_root import get_collab_dir
except ImportError:
    # Fallback if runtime.project_root not available
    get_collab_dir = None


class _LazyPath:
    def __init__(self, resolver):
        self._resolver = resolver

    def resolve(self) -> Path:
        return self._resolver()

    def __truediv__(self, other):
        return self.resolve() / other

    def __getattr__(self, name: str):
        return getattr(self.resolve(), name)

    def __fspath__(self) -> str:
        return str(self.resolve())

    def __str__(self) -> str:
        return str(self.resolve())


def _collab_dir() -> Path:
    if get_collab_dir is not None:
        return get_collab_dir()
    return Path(__file__).parent / "collaboration"


COLLAB_DIR = _LazyPath(_collab_dir)
SESSION_FILE = _LazyPath(lambda: _collab_dir() / ".session_state.json")

STALE_THRESHOLD_HOURS = 2
MAX_FILES_TO_LIST = 10


def save_session() -> None:
    """Guarda estado simple de la sesion actual."""
    with suppress(OSError, TypeError, ValueError):
        COLLAB_DIR.mkdir(parents=True, exist_ok=True)

        session = {
            "last_activity": datetime.now().isoformat(),
            "active_plan": _get_current_plan_id(),
            "files_count": _count_project_files(),
            "version": "1.0-lite",
        }

        SESSION_FILE.write_text(
            json.dumps(session, indent=2, ensure_ascii=False), encoding="utf-8"
        )


def detect_stale_session() -> bool:
    """Detecta si han pasado mas de 2 horas desde la ultima actividad."""
    if not SESSION_FILE.exists():
        return False

    try:
        session = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        last_activity = datetime.fromisoformat(session["last_activity"])
        return datetime.now() - last_activity > timedelta(hours=STALE_THRESHOLD_HOURS)
    except (json.JSONDecodeError, KeyError, ValueError):
        return False


def recover_session() -> dict | None:
    """Recupera informacion de la sesion anterior."""
    if not SESSION_FILE.exists():
        return None

    with suppress(Exception):
        session = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        last = datetime.fromisoformat(session["last_activity"])
        elapsed = datetime.now() - last
        hours_ago = elapsed.total_seconds() / 3600

        print("\n" + "=" * 60)
        print("[INFO] SESION ANTERIOR DETECTADA")
        print("=" * 60)
        print(f"[INFO] Ultima actividad: hace {hours_ago:.1f} horas")
        print(f"[INFO] Plan activo: {session.get('active_plan', 'N/A')}")
        print(f"[INFO] Archivos en proyecto: {session.get('files_count', 'N/A')}")

        modified = _get_recently_modified_files(hours=int(hours_ago) + 1)
        if modified:
            print("\n[INFO] Archivos modificados:")
            for filepath in modified[:MAX_FILES_TO_LIST]:
                print(f"   - {filepath}")
            if len(modified) > MAX_FILES_TO_LIST:
                print(f"   ... y {len(modified) - MAX_FILES_TO_LIST} mas")

        print("=" * 60 + "\n")
        return session
    return None


def show_recovery_hint() -> None:
    """Muestra hint suave si hay sesion antigua."""
    if detect_stale_session():
        print("[INFO] Hay una sesion anterior (>2h). Usa --recover para ver detalles.")


def _get_current_plan_id() -> str:
    """Obtiene el ID del plan actual desde work_plan.md."""
    work_plan = COLLAB_DIR / "work_plan.md"
    if not work_plan.exists():
        return "N/A"

    with suppress(Exception):
        content = work_plan.read_text(encoding="utf-8")
        for line in content.split("\n"):
            if "**ID:**" in line:
                return line.split(":**")[1].strip()

    return "N/A"


def _count_project_files() -> int:
    """Cuenta archivos relevantes en el proyecto."""
    project_root = COLLAB_DIR.parent.parent
    ignore_dirs = {".git", ".venv", "__pycache__", ".pytest_cache"}
    extensions = {".py", ".md", ".json", ".yaml", ".yml", ".toml"}

    count = 0
    with suppress(Exception):
        for filepath in project_root.rglob("*"):
            if any(part in ignore_dirs for part in filepath.parts):
                continue
            if filepath.is_file() and filepath.suffix in extensions:
                count += 1
                if count > 50:
                    break

    return count


def _get_recently_modified_files(hours: int = 2) -> list[str]:
    """Obtiene archivos modificados en las ultimas N horas."""
    project_root = COLLAB_DIR.parent.parent
    cutoff = datetime.now() - timedelta(hours=hours)

    ignore_dirs = {".git", ".venv", "__pycache__", ".pytest_cache"}
    extensions = {".py", ".md", ".json", ".yaml", ".yml", ".toml"}

    modified = []
    with suppress(Exception):
        for filepath in project_root.rglob("*"):
            if any(part in ignore_dirs for part in filepath.parts):
                continue

            if filepath.is_file() and filepath.suffix in extensions:
                try:
                    mtime = datetime.fromtimestamp(filepath.stat().st_mtime)
                    if mtime > cutoff:
                        rel_path = filepath.relative_to(project_root)
                        modified.append(str(rel_path))
                except (OSError, ValueError):
                    continue

    return sorted(modified)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == "save":
            save_session()
            print("[OK] Sesion guardada")
        elif command == "check":
            if detect_stale_session():
                print("[WARN] Sesion antigua detectada (>2h)")
            else:
                print("[INFO] Sesion reciente o no hay sesion")
        elif command == "recover":
            result = recover_session()
            if not result:
                print("[INFO] No hay sesion previa para recuperar")
        else:
            print(f"Comando desconocido: {command}")
            print("Usa: save | check | recover")
    else:
        recover_session()
