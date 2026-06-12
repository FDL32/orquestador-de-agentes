#!/usr/bin/env python3
"""Runner seguro para pytest en agent_system.

Objectives:
- inspeccionar el estado antes de tocar nada
- evitar ejecuciones concurrentes de pytest
- mantener los temporales dentro del proyecto
- limpiar residuos conocidos antes y despues del run
- dejar log del ultimo run para diagnostico

By default this runner executes pytest discovery over ``tests/``.
Pass explicit pytest args (for example ``-- tests/unit``) to narrow the scope.

WP-2026-122: Uses runtime.project_root for dynamic project root resolution.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path


# Bootstrap: project root must be on sys.path before importing runtime.project_root.
_PROJECT_ROOT_BOOTSTRAP = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT_BOOTSTRAP) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT_BOOTSTRAP))

# WP-2026-122 / WP-2026-155: Centralized path resolution via runtime.project_root
from runtime.project_root import get_agent_dir, resolve_project_root  # noqa: E402


_PROJECT_ROOT = resolve_project_root()
_AGENT_DIR = get_agent_dir()


def _project_root() -> Path:
    """Return the resolved project root (cached for performance)."""
    return _PROJECT_ROOT


class _LazyPath:
    def __init__(self, resolver):
        self._resolver = resolver

    def resolve(self) -> Path:
        return self._resolver()

    def __getattr__(self, name: str):
        return getattr(self.resolve(), name)

    def __truediv__(self, other):
        return self.resolve() / other

    def __fspath__(self) -> str:
        return str(self.resolve())

    def __str__(self) -> str:
        return str(self.resolve())


PROJECT_ROOT = _LazyPath(_project_root)
AGENT_DIR = _LazyPath(lambda: _AGENT_DIR)
RUNTIME_DIR = _LazyPath(lambda: AGENT_DIR.resolve() / "runtime" / "pytest-safe")
LOCK_FILE = _LazyPath(lambda: RUNTIME_DIR.resolve() / "pytest.lock")
LAST_RUN_LOG = _LazyPath(lambda: RUNTIME_DIR.resolve() / "last-run.log")
LAST_RUN_JSON = _LazyPath(lambda: RUNTIME_DIR.resolve() / "last-run.json")

DEFAULT_PYTEST_ARGS = [
    "tests",
    "-q",
    "-p",
    "no:cacheprovider",
]

LEVEL_CHOICES = {"unit", "integration", "all"}
DEFAULT_ARGS_MODE = "default_discovery"
EXPLICIT_ARGS_MODE = "explicit_args"


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_runtime_dir() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)


def is_pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def acquire_lock(force_unlock: bool = False) -> dict:
    ensure_runtime_dir()

    if LOCK_FILE.exists():
        stale = True
        lock_data = read_json(LOCK_FILE)
        lock_pid = int(lock_data.get("pid", 0) or 0)
        if is_pid_running(lock_pid):
            stale = False
        if not stale and not force_unlock:
            raise RuntimeError(
                f"Ya hay un pytest activo (pid={lock_pid}). "
                f"Si estas seguro de que es stale, usa --force-unlock."
            )
        LOCK_FILE.unlink(missing_ok=True)

    payload = {
        "pid": os.getpid(),
        "started_at": iso_now(),
        "cwd": str(PROJECT_ROOT),
    }
    fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
    except Exception:
        LOCK_FILE.unlink(missing_ok=True)
        raise
    return payload


def release_lock() -> None:
    LOCK_FILE.unlink(missing_ok=True)


def iter_project_temp_dirs() -> Iterable[Path]:
    for entry in PROJECT_ROOT.iterdir():
        if not entry.is_dir():
            continue
        if entry.name in {".pytest_tmp", "_pytest_tmp"} or entry.name.startswith(
            "_pytest_tmp_"
        ):
            yield entry


def remove_tree(path: Path) -> tuple[bool, str]:
    try:
        shutil.rmtree(path)
        return True, ""
    except FileNotFoundError:
        return True, ""
    except Exception as exc:
        return False, str(exc)


def cleanup_known_temp_dirs() -> dict:
    removed: list[str] = []
    failed: list[dict[str, str]] = []

    for path in iter_project_temp_dirs():
        ok, error = remove_tree(path)
        if ok:
            removed.append(path.name)
        else:
            failed.append({"path": str(path), "error": error})

    return {"removed": removed, "failed": failed}


def path_is_accessible(path: Path) -> bool:
    try:
        with os.scandir(path) as iterator:
            for _ in iterator:
                break
        return True
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return False


def get_lock_status() -> dict:
    if not LOCK_FILE.exists():
        return {"present": False}

    lock_data = read_json(LOCK_FILE)
    lock_pid = int(lock_data.get("pid", 0) or 0)
    return {
        "present": True,
        "pid": lock_pid,
        "active": is_pid_running(lock_pid),
        "data": lock_data,
    }


def get_temp_dir_status() -> list[dict[str, object]]:
    return [
        {
            "path": str(path),
            "name": path.name,
            "accessible": path_is_accessible(path),
        }
        for path in sorted(iter_project_temp_dirs())
    ]


def build_status_payload() -> dict:
    return {
        "project_root": str(PROJECT_ROOT),
        "runtime_dir": str(RUNTIME_DIR),
        "lock": get_lock_status(),
        "temp_dirs": get_temp_dir_status(),
        "last_run": read_json(LAST_RUN_JSON),
    }


def print_status(payload: dict) -> None:
    print("Estado pytest-safe")
    print(f"Proyecto: {payload['project_root']}")
    print(f"Runtime: {payload['runtime_dir']}")

    lock = payload["lock"]
    if lock["present"]:
        state = "activo" if lock["active"] else "stale"
        print(f"Lock: {state} (pid={lock['pid']})")
    else:
        print("Lock: libre")

    temp_dirs = payload["temp_dirs"]
    if temp_dirs:
        print(f"Temporales detectados: {len(temp_dirs)}")
        for item in temp_dirs:
            state = "accesible" if item["accessible"] else "bloqueado"
            print(f"- {item['name']}: {state}")
    else:
        print("Temporales detectados: 0")

    last_run = payload["last_run"]
    if last_run:
        level_info = last_run.get("level", "n/a")
        print(
            "Ultimo run: "
            f"{last_run.get('started_at', 'desconocido')} | "
            f"level={level_info} | "
            f"status={last_run.get('status', 'desconocido')} | "
            f"exit={last_run.get('exit_code', 'n/a')}"
        )
    else:
        print("Ultimo run: sin registro")


def make_run_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return RUNTIME_DIR / f"run-{stamp}-{os.getpid()}"


def stream_pytest(command: list[str]) -> int:
    lines: list[str] = []

    # Ensure .agent is in PYTHONPATH for the subprocess
    env = os.environ.copy()
    agent_path = str(_PROJECT_ROOT_BOOTSTRAP / ".agent")
    if "PYTHONPATH" in env:
        env["PYTHONPATH"] = f"{agent_path}{os.pathsep}{env['PYTHONPATH']}"
    else:
        env["PYTHONPATH"] = agent_path

    process = subprocess.Popen(  # noqa: S603
        command,
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
    )
    try:
        if process.stdout is None:
            raise RuntimeError("pytest subprocess did not expose stdout")
        for line in process.stdout:
            try:
                print(line, end="")
            except UnicodeEncodeError:
                # Fallback to ascii replacing if terminal doesn't support utf-8 (like windows cp1252)
                print(line.encode("ascii", "replace").decode("ascii"), end="")
            lines.append(line)
        returncode = process.wait()
    except KeyboardInterrupt:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        raise
    finally:
        LAST_RUN_LOG.write_text("".join(lines), encoding="utf-8")
    return returncode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Runner seguro para pytest en agent_system."
    )
    parser.add_argument(
        "--cleanup-only",
        action="store_true",
        help="Limpia temporales conocidos y termina sin ejecutar pytest.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Muestra lock, temporales detectados y el ultimo run sin modificar nada.",
    )
    parser.add_argument(
        "--force-unlock",
        action="store_true",
        help="Ignora un lock stale y continua.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Muestra el comando final de pytest sin ejecutarlo.",
    )
    parser.add_argument(
        "--level",
        choices=sorted(LEVEL_CHOICES),
        default="unit",
        help=(
            "Nivel de tests a ejecutar: unit (default, excluye integration), "
            "integration (solo marcados), all (sin filtro)."
        ),
    )
    parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Argumentos extra para pytest. Usa -- para separarlos.",
    )
    return parser.parse_args()


def has_marker_arg(args: list[str]) -> bool:
    return any(
        a == "-m" or a.startswith("-m") or a.startswith("--markers") for a in args
    )


def strip_pytest_separator(raw_args: list[str]) -> list[str]:
    args = list(raw_args)
    if args and args[0] == "--":
        args = args[1:]
    return args


def pytest_args_mode(raw_args: list[str]) -> str:
    return EXPLICIT_ARGS_MODE if strip_pytest_separator(raw_args) else DEFAULT_ARGS_MODE


def default_test_target() -> str:
    return "tests/"


def print_default_discovery_notice(args_mode: str) -> None:
    if args_mode != DEFAULT_ARGS_MODE:
        return
    print(
        "[pytest-safe] Mode: default discovery "
        f"({default_test_target()}, excluding deprecated/debug/sandbox via pytest.ini). "
        "Pass explicit args after -- to narrow scope, e.g. -- tests/unit."
    )


def normalize_pytest_args(raw_args: list[str], level: str) -> list[str]:
    args = strip_pytest_separator(raw_args)
    args = args or list(DEFAULT_PYTEST_ARGS)

    if not has_marker_arg(args):
        if level == "unit":
            args = ["-m", "not integration", *args]
        elif level == "integration":
            args = ["-m", "integration", *args]
        # level == "all" no añade filtro

    return args


def snapshot_canonical_state() -> dict[str, str]:
    """Snapshot canonical collaboration files before the suite runs.

    Barrier (CEM class B - state leak): some historical tests wrote to the
    REAL .agent/collaboration/ of the motor instead of tmp_path. Capturing
    content before and comparing after turns that silent leak into a
    visible failure with the offending delta.
    """
    snapshot: dict[str, str] = {}
    collab = _AGENT_DIR / "collaboration"
    for name in ("STATE.md", "TURN.md", "work_plan.md", "execution_log.md"):
        path = collab / name
        try:
            snapshot[name] = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            snapshot[name] = ""
    return snapshot


def check_canonical_state_leak(snapshot: dict[str, str]) -> list[str]:
    """Compare canonical files against the pre-suite snapshot.

    Returns a list of leaked file names (content changed during the run).
    """
    leaked: list[str] = []
    collab = _AGENT_DIR / "collaboration"
    for name, before in snapshot.items():
        path = collab / name
        try:
            after = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            after = ""
        if after != before:
            leaked.append(name)
    return leaked


def main() -> int:
    args = parse_args()
    ensure_runtime_dir()

    if args.status:
        print_status(build_status_payload())
        return 0

    cleanup = cleanup_known_temp_dirs()

    if args.cleanup_only:
        print("Cleanup terminado.")
        print(f"Eliminados: {len(cleanup['removed'])}")
        if cleanup["failed"]:
            print(f"No eliminados: {len(cleanup['failed'])}")
            for item in cleanup["failed"]:
                print(f"- {item['path']}: {item['error']}")
            print("Consulta el estado con --status antes de relanzar pytest.")
            return 1
        return 0

    lock = acquire_lock(force_unlock=args.force_unlock)
    run_dir = make_run_dir()
    args_mode = pytest_args_mode(args.pytest_args)
    pytest_args = normalize_pytest_args(args.pytest_args, args.level)
    command = [sys.executable, "-m", "pytest", *pytest_args, f"--basetemp={run_dir}"]

    summary = {
        "started_at": iso_now(),
        "lock": lock,
        "level": args.level,
        "args_mode": args_mode,
        "default_discovery_target": default_test_target()
        if args_mode == DEFAULT_ARGS_MODE
        else None,
        "pytest_args": pytest_args,
        "command": command,
        "cleanup_before": cleanup,
        "run_dir": str(run_dir),
        "status": "started",
    }
    write_json(LAST_RUN_JSON, summary)

    try:
        if args.dry_run:
            print_default_discovery_notice(args_mode)
            print("Comando pytest:")
            print(" ".join(command))
            summary["status"] = "dry-run"
            write_json(LAST_RUN_JSON, summary)
            return 0

        print(f"[pytest-safe] Proyecto: {PROJECT_ROOT}")
        print(f"[pytest-safe] Lock: {LOCK_FILE}")
        print(f"[pytest-safe] Temp: {run_dir}")
        print_default_discovery_notice(args_mode)
        print(f"[pytest-safe] Ejecutando: {' '.join(command)}")
        state_snapshot = snapshot_canonical_state()
        exit_code = stream_pytest(command)
        summary["status"] = "finished"
        summary["exit_code"] = exit_code

        # Barrier: fail the run if the suite mutated canonical collaboration
        # state of the motor (state-leak tests writing outside tmp_path).
        leaked = check_canonical_state_leak(state_snapshot)
        if leaked:
            summary["state_leak"] = leaked
            print(
                "[pytest-safe] STATE LEAK: la suite modifico archivos canonicos "
                f"de .agent/collaboration/: {', '.join(leaked)}. "
                "Algun test escribe fuera de tmp_path. Restaura con git checkout "
                "y biseca el test culpable."
            )
            if exit_code == 0:
                exit_code = 1
                summary["exit_code"] = exit_code
        return exit_code
    finally:
        cleanup_after = {"removed": [], "failed": []}
        if run_dir.exists():
            ok, error = remove_tree(run_dir)
            if ok:
                cleanup_after["removed"].append(str(run_dir))
            else:
                cleanup_after["failed"].append({"path": str(run_dir), "error": error})
        summary["finished_at"] = iso_now()
        summary["cleanup_after"] = cleanup_after
        write_json(LAST_RUN_JSON, summary)
        release_lock()


if __name__ == "__main__":
    sys.exit(main())
