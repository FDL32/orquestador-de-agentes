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


def _delivery_authority() -> str:
    """Read delivery_authority from the active work_plan under PROJECT_ROOT.

    Default 'repo_motor' (legacy single-repo behavior) if missing/unreadable.
    """
    work_plan = _PROJECT_ROOT / ".agent" / "collaboration" / "work_plan.md"
    try:
        content = work_plan.read_text(encoding="utf-8")
    except OSError:
        return "repo_motor"
    import re

    if re.search(
        r"delivery_authority\s*:?\**\s*(?:repo_destino|destino)",
        content,
        re.IGNORECASE,
    ):
        return "repo_destino"
    return "repo_motor"


def _delivery_repo_root() -> Path:
    """Repo whose HEAD the suite is delivered against (LEA topology fix).

    A repo_destino code ticket keeps its productive commit in the destination
    (PROJECT_ROOT). Otherwise the delivery repo is the motor where the runner
    lives. The pre-handoff gate resolves the same root by delivery_authority, so
    the stamped tested_commit_sha matches what the gate compares against.
    """
    if _delivery_authority() == "repo_destino":
        return _PROJECT_ROOT
    return _PROJECT_ROOT_BOOTSTRAP


def _venv_python(root: Path) -> Path | None:
    """Return the venv interpreter under ``root`` if present, else None.

    Supports both layouts: ``.venv/Scripts/python.exe`` (Windows) and
    ``.venv/bin/python`` (POSIX).
    """
    candidates = (
        root / ".venv" / "Scripts" / "python.exe",
        root / ".venv" / "bin" / "python",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def resolve_test_interpreter() -> str:
    """Pick the interpreter that has the *delivery repo's* dependencies.

    CTL-2026-007b (Fase 2.4): the canonical-suite gate was non-deterministic
    because the suite ran under ``sys.executable`` (the motor's interpreter),
    whose site-packages may or may not contain the destination's deps (e.g.
    ``loguru``). When the destination has its own ``.venv``, running the suite
    with the motor interpreter produced a spurious collection failure (exit 2),
    leaving a misleading ``last-run.json``.

    Before: PROJECT_ROOT is the active workspace (the destination when running
        its suite); ``sys.executable`` is whatever launched this runner.
    During: if the active workspace differs from the motor AND has a ``.venv``,
        prefer that venv's python so the suite runs with the destination's
        installed dependencies.
    After: returns the interpreter path as a string. Falls back to
        ``sys.executable`` for the single-repo/motor case or when no destination
        venv exists (preserving legacy behavior).
    """
    active = _PROJECT_ROOT.resolve()
    motor = _PROJECT_ROOT_BOOTSTRAP.resolve()
    if active != motor:
        venv_py = _venv_python(active)
        if venv_py is not None:
            return str(venv_py)
    return sys.executable


def _delivery_head_sha() -> str | None:
    """Return the delivery repo HEAD SHA, or None if git is unavailable.

    WOT-2026-010c: recorded in last-run.json so the handoff gate can verify the
    run tested the exact commit being delivered. The delivery repo is resolved
    by delivery_authority: the motor for motor-delivered tickets, the destination
    for repo_destino tickets (so the gate's delivery-HEAD comparison matches).

    Renamed from _motor_head_sha: it no longer always returns the motor HEAD.
    """
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            cwd=_delivery_repo_root(),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    sha = proc.stdout.strip()
    return sha or None


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


def probe_pytest(interpreter: str) -> bool:
    """Return True if *interpreter* can import pytest.

    WOT-2026-014b: runner-detection seam. Runs a fast subprocess against the
    TARGET test interpreter (not the current process), so a destination whose
    .venv has no pytest is detected independently of the motor environment.

    Before: interpreter is the resolved test-interpreter path (string).
    During: spawns <interpreter> -c "import pytest" with a 5-second
        timeout; captures stdout+stderr without printing them.
    After: returns True if returncode == 0; False otherwise (no pytest,
        import error, or timeout). Never raises.
    """
    try:
        result = subprocess.run(  # noqa: S603
            [interpreter, "-c", "import pytest"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def select_test_runner(
    interpreter: str,
    pytest_args: list[str],
    xdist_flags: list[str],
    run_dir: Path,
    *,
    test_dir: str = "tests",
    _probe: bool | None = None,
) -> tuple[list[str], str]:
    """Build the subprocess command for the resolved *interpreter*.

    WOT-2026-014b: testable command-selection seam.  Probes whether the
    target interpreter has pytest; falls back to python -m unittest
    discover when it does not.

    Before: interpreter is the resolved test-interpreter string; pytest_args
        and xdist_flags are the already-normalized pytest argument lists;
        run_dir is the per-run temp directory Path; test_dir is the directory
        to pass to unittest discover -s; _probe overrides the pytest
        probe result (test seam only -- do NOT use in production code).
    During: calls probe_pytest(interpreter) unless _probe is supplied.
        pytest branch: current command construction (byte-identical behavior).
        unittest branch: omits xdist_flags (incompatible) and basetemp;
            passes -s <test_dir> to unittest discover.
    After: returns (command, runner) where runner is "pytest" or "unittest".
        Never raises.  last-run.json callers may record the runner field for
        observability without changing the gate-required fields.
    """
    has_pytest = probe_pytest(interpreter) if _probe is None else _probe

    if has_pytest:
        command = [
            interpreter,
            "-m",
            "pytest",
            *xdist_flags,
            *pytest_args,
            f"--basetemp={run_dir}",
        ]
        return command, "pytest"

    # Fallback: unittest discover (ignores xdist_flags and basetemp --
    # neither is meaningful for unittest).
    command = [
        interpreter,
        "-m",
        "unittest",
        "discover",
        "-s",
        test_dir,
    ]
    return command, "unittest"


def stream_pytest(command: list[str]) -> tuple[int, list[str], list[str]]:  # noqa: C901
    """Run pytest, stream output, and return (returncode, failed_test_ids, error_test_ids).

    WOT-2026-017a: parses lines matching ^FAILED\\s+(\\S+) from the stream to
    capture the node-ids of failing tests (stdlib-only, no plugin required).
    WOT-2026-016k: also parses ^ERROR\\s+(\\S+) to capture teardown-crash
    node-ids in a separate list, keeping FAILED != ERROR semantics.
    Returns the returncode, the list of failed test node-ids, and the list of
    error test node-ids (both empty when returncode == 0 or when no matching
    lines appear in the output).
    """
    import re

    lines: list[str] = []
    _failed_re = re.compile(r"^FAILED\s+(\S+)")
    _error_re = re.compile(r"^ERROR\s+(\S+)")

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

    failed_ids: list[str] = []
    for line in lines:
        m = _failed_re.match(line.rstrip())
        if m:
            failed_ids.append(m.group(1))

    error_ids: list[str] = []
    for line in lines:
        m = _error_re.match(line.rstrip())
        if m:
            error_ids.append(m.group(1))

    return returncode, failed_ids, error_ids


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
        "--select-from-diff",
        action="store_true",
        help=(
            "WOT-2026-010l: ergonomia local. Propone un subset focal de tests "
            "derivado del diff real del working tree. Si no puede resolver un "
            "subset seguro, replega a la suite canonica completa con razon "
            "auditable. NO satisface el handoff de 010q (produce args explicitos)."
        ),
    )
    parser.add_argument(
        "--xdist-workers",
        default=None,
        metavar="N|auto",
        help=(
            "WOT-2026-011e: opt-in local de paralelizacion con pytest-xdist. "
            "Solo se habilita para subset unitario explicito (--level unit + "
            "descubrimiento por defecto). Fuera de ese contrato cae a serial con "
            "razon auditable. NO cambia el camino canonico de cierre (--level all)."
        ),
    )
    parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Argumentos extra para pytest. Usa -- para separarlos.",
    )
    return parser.parse_args()


def resolve_focal_args(raw_args: list[str]) -> tuple[list[str], str | None]:
    """Resolve focal pytest args from the working-tree diff (WOT-2026-010l).

    Before: ``raw_args`` are the user's REMAINDER args (already stripped of the
    leading ``--`` by the caller via :func:`strip_pytest_separator` when needed).
    During: delegates to ``scripts/test_selection.select_focal_tests`` using the
    canonical ``scope_gate`` diff seam (no parallel git parser). After: returns
    ``(extra_args, None)`` with the selected test paths to append when a safe
    subset exists, or ``([], reason)`` when it falls open to the canonical suite.
    The reason is always auditable; selection never pass-opens silently.
    """
    import importlib.util

    selection_path = _PROJECT_ROOT_BOOTSTRAP / "scripts" / "test_selection.py"
    spec = importlib.util.spec_from_file_location("test_selection", selection_path)
    if spec is None or spec.loader is None:
        return (
            [],
            "selector_unavailable: could not load test_selection module; running the canonical full suite.",
        )
    module = importlib.util.module_from_spec(spec)
    # Register before exec so @dataclass can resolve cls.__module__.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    result = module.select_focal_tests(
        project_root=_PROJECT_ROOT_BOOTSTRAP,
        motor_root=_PROJECT_ROOT_BOOTSTRAP,
    )
    if result.is_subset:
        return list(result.tests), None
    return [], result.reason


def apply_focal_selection(
    raw_pytest_args: list[str], *, select_from_diff: bool
) -> tuple[list[str], str | None]:
    """Apply opt-in focal selection (WOT-2026-010l) to the raw pytest args.

    Before: ``raw_pytest_args`` are the user's REMAINDER args. When
    ``select_from_diff`` is false this is a no-op (returns the args unchanged,
    reason ``None``) — full additive backward-compat. During: when true, asks
    :func:`resolve_focal_args` for a safe subset. After: a resolved subset is
    appended as explicit pytest args (so ``args_mode`` becomes ``explicit_args``
    and the 010q handoff gate keeps blocking the run); an unsafe/empty
    resolution falls open to the canonical full suite, returning the original
    args plus the auditable ``reason``.
    """
    if not select_from_diff:
        return raw_pytest_args, None

    focal_extra, focal_reason = resolve_focal_args(raw_pytest_args)
    if focal_extra:
        base = strip_pytest_separator(raw_pytest_args)
        print(
            "[pytest-safe] Focal selection (WOT-2026-010l): "
            f"{len(focal_extra)} test file(s) from diff. This run is focal "
            "and does NOT satisfy the 010q handoff gate."
        )
        return ["--", *base, *focal_extra], None

    print(f"[pytest-safe] Focal selection fell open to full suite: {focal_reason}")
    return raw_pytest_args, focal_reason


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


def resolve_xdist(
    requested: str | None, level: str, args_mode: str
) -> tuple[int | None, dict]:
    """Decide whether xdist runs, with an auditable fallback (WOT-2026-011e).

    Before: ``requested`` is the raw --xdist-workers value (None == not asked).
    During: xdist is enabled ONLY for an explicit unit subset
        (level == "unit" AND args_mode == default discovery). Any other scope
        (integration/all, explicit/focal args, bad value) falls back to serial
        with a stable reason. "auto" maps to min(8, max(2, cpu//2)).
    After: returns (workers or None, metadata dict). workers is None == serial.
        Never silently pass-opens: the metadata always carries why.
    """
    meta = {
        "requested": requested is not None,
        "requested_value": requested,
        "enabled": False,
        "workers": None,
        "fallback_reason": None,
    }
    if requested is None:
        meta["fallback_reason"] = "not_requested"
        return None, meta
    if level != "unit":
        meta["fallback_reason"] = f"xdist only for level=unit (got level={level!r})"
        return None, meta
    if args_mode != DEFAULT_ARGS_MODE:
        meta["fallback_reason"] = (
            f"xdist only for default-discovery subset (got args_mode={args_mode!r})"
        )
        return None, meta

    raw = requested.strip().lower()
    if raw == "auto":
        cpu = os.cpu_count() or 2
        workers = min(8, max(2, cpu // 2))
    else:
        try:
            workers = int(raw)
        except ValueError:
            meta["fallback_reason"] = f"invalid --xdist-workers value {requested!r}"
            return None, meta
        if workers < 2:
            meta["fallback_reason"] = f"xdist needs >=2 workers (got {workers})"
            return None, meta

    meta["enabled"] = True
    meta["workers"] = workers
    return workers, meta


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


def main() -> int:  # noqa: C901
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

    raw_pytest_args, focal_reason = apply_focal_selection(
        list(args.pytest_args), select_from_diff=args.select_from_diff
    )

    args_mode = pytest_args_mode(raw_pytest_args)
    pytest_args = normalize_pytest_args(raw_pytest_args, args.level)
    # WOT-2026-011e: opt-in xdist for an explicit unit subset only; auditable
    # fallback to serial otherwise. Never touches the canonical close path.
    xdist_workers, xdist_meta = resolve_xdist(args.xdist_workers, args.level, args_mode)
    xdist_flags = ["-n", str(xdist_workers)] if xdist_workers else []
    # CTL-2026-007b (Fase 2.4): run the suite with the delivery repo's
    # interpreter so the destination's deps are present. Falls back to
    # sys.executable for the motor/single-repo case.
    # WOT-2026-014b: runner-detection seam. select_test_runner probes whether
    # the resolved interpreter has pytest; falls back to unittest discover when
    # it does not. Behavior is byte-identical for interpreters that DO have pytest.
    command, _runner = select_test_runner(
        resolve_test_interpreter(),
        pytest_args,
        xdist_flags,
        run_dir,
        test_dir=default_test_target().rstrip("/"),
    )

    # WOT-2026-017a: capture the baseline failed_test_ids from the previous
    # last-run.json (if it exists and has the field) BEFORE this run overwrites
    # it. This becomes field B for the subset comparison in pre_handoff_guard.
    #
    # LIMITATION (R3 - carry-forward, not commit-base): baseline_failed_test_ids
    # is the failed_test_ids of the run IMMEDIATELY PRECEDING this one, NOT
    # necessarily the run against the ticket's base commit. If intermediate runs
    # occurred during the ticket (e.g. a run with uncommitted work_plan.md that
    # triggered spurious gate failures), those transient ids become the baseline
    # for the NEXT run. The operational mitigation is to ensure that a clean run
    # (against an unmodified tree, with all collaboration artifacts committed)
    # executes immediately before handoff so that the baseline reflects the true
    # pre-existing failure set, not transient states.
    _baseline_failed: list[str] = []
    if LAST_RUN_JSON.exists():
        try:
            _prev = json.loads(LAST_RUN_JSON.read_text(encoding="utf-8"))
            _baseline_failed = list(_prev.get("failed_test_ids") or [])
        except Exception:
            _baseline_failed = []

    summary = {
        "started_at": iso_now(),
        "lock": lock,
        "level": args.level,
        "args_mode": args_mode,
        "default_discovery_target": default_test_target()
        if args_mode == DEFAULT_ARGS_MODE
        else None,
        "pytest_args": pytest_args,
        # WOT-2026-010l: when focal selection ran, record whether it produced a
        # subset or fell open, with the auditable reason.
        "focal_selection": (
            {"requested": True, "fell_open": bool(focal_reason), "reason": focal_reason}
            if args.select_from_diff
            else None
        ),
        # WOT-2026-011e: xdist request/enablement metadata so review can see
        # whether parallelization ran, with how many workers, or why it fell back.
        "xdist": xdist_meta,
        "command": command,
        "cleanup_before": cleanup,
        "run_dir": str(run_dir),
        # WOT-2026-010c: record the motor HEAD this run tested, so the
        # canonical-suite handoff gate can verify freshness by SHA (not by
        # timestamp). Captured once at run start; the tree must not change.
        "tested_commit_sha": _delivery_head_sha(),
        # WOT-2026-014b: informative field; does not change gate contract.
        "runner": _runner,
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
        exit_code, failed_ids, error_ids = stream_pytest(command)
        summary["status"] = "finished"
        summary["exit_code"] = exit_code
        # WOT-2026-017a: persist node-ids of failed tests so pre_handoff_guard
        # can compare them against the baseline (D2/D3). Always a list; empty
        # when exit_code==0 or when no FAILED lines appeared in the stream.
        summary["failed_test_ids"] = failed_ids
        # WOT-2026-016k: separate field for ERROR teardown crashes.
        summary["error_test_ids"] = error_ids
        # WOT-2026-017a: persist the failed_test_ids that were on disk before
        # this run so the guard can use them as baseline B for subset comparison.
        summary["baseline_failed_test_ids"] = _baseline_failed

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
