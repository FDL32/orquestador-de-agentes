"""WOT-2026-070h: forense de muertes de suite sin depender de la siguiente.

Invariant: a killed run leaves ON DISK, at death instant: (a) termination
signal (status=started + dead PID + stale progress), (b) the last nodeid
reached (pytest-progress.json), (c) pytest output (last-run.log written
incrementally per line). Mutation: removing the per-line persistence makes
the incremental-log test red.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = PROJECT_ROOT / "scripts" / "run_pytest_safe.py"

_spec = importlib.util.spec_from_file_location("run_pytest_safe_070h", RUNNER_PATH)
rps = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = rps
_spec.loader.exec_module(rps)


class _FakeStdout:
    def __init__(self, lines: list[str]) -> None:
        self._lines = list(lines)

    def readline(self) -> str:
        return self._lines.pop(0) if self._lines else ""


class _FakeProc:
    def __init__(self, lines: list[str], returncode: int = 0) -> None:
        self.stdout = _FakeStdout(lines)
        self.returncode = returncode
        self.terminated = False
        self.killed = False

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode


class _FakeLazy:
    """Sustituye un _LazyPath: resolve()/str() al target, el resto no-op."""

    def __init__(self, target: Path) -> None:
        self._target = target

    def resolve(self):
        return self._target

    def __str__(self) -> str:
        return str(self._target)

    def unlink(self, *args, **kwargs) -> None:
        pass


class _FakeJsonPath(_FakeLazy):
    """_FakeLazy con exists/read_text/write_text (contrato de read_json)."""

    def exists(self) -> bool:
        return self._target.exists()

    def read_text(self, encoding: str = "utf-8") -> str:
        return self._target.read_text(encoding=encoding)

    def write_text(self, data: str, encoding: str = "utf-8") -> int:
        return self._target.write_text(data, encoding=encoding)


def _load_with_redirects(monkeypatch, tmp_path: Path):
    """Reload the runner with LAST_RUN_LOG / RUNTIME_DIR pointed at tmp."""
    spec = importlib.util.spec_from_file_location(
        f"run_pytest_safe_070h_{tmp_path.name}", RUNNER_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    fake_runtime = types.SimpleNamespace(resolve=lambda: tmp_path)
    monkeypatch.setattr(mod, "RUNTIME_DIR", fake_runtime)
    monkeypatch.setattr(mod, "LAST_RUN_LOG", _FakeLazy(tmp_path / "last-run.log"))
    monkeypatch.setattr(mod, "LAST_RUN_JSON", _FakeJsonPath(tmp_path / "last-run.json"))
    monkeypatch.setattr(
        mod,
        "subprocess",
        types.SimpleNamespace(
            PIPE=-1,
            STDOUT=-2,
            DEVNULL=-3,
            CREATE_NEW_PROCESS_GROUP=0,
            Popen=lambda cmd, **kw: mod._last_fake,  # set per-test
            TimeoutExpired=rps.subprocess.TimeoutExpired,
        ),
    )
    return mod


OUTPUT_LINES = [
    "============================= test session starts =============================",
    "collected 3 items",
    "tests/unit/test_a.py::test_one PASSED",
    "tests/unit/test_a.py::test_two FAILED",
    "FAILED tests/unit/test_a.py::test_two - assert False",
    "=========================== short test summary info ===========================",
]


def test_stream_persiste_linea_a_linea_y_extrae_failed(monkeypatch, tmp_path) -> None:
    mod = _load_with_redirects(monkeypatch, tmp_path)
    mod._last_fake = _FakeProc(list(OUTPUT_LINES))
    rc, failed, errors, timed_out = mod.stream_pytest(["pytest"])
    assert rc == 0
    assert timed_out is False
    assert failed == ["tests/unit/test_a.py::test_two"]
    assert errors == []
    log = (tmp_path / "last-run.log").read_text(encoding="utf-8")
    # (c): TODAS las lineas quedaron en disco, no solo el resumen final.
    for raw in OUTPUT_LINES:
        assert raw in log
    assert "test session starts" in log


def test_progress_json_lleva_ultimo_nodeid_y_timestamp(monkeypatch, tmp_path) -> None:
    mod = _load_with_redirects(monkeypatch, tmp_path)
    mod._last_fake = _FakeProc(list(OUTPUT_LINES))
    mod.stream_pytest(["pytest"])
    progress = json.loads(
        (tmp_path / "pytest-progress.json").read_text(encoding="utf-8")
    )
    assert progress["last_nodeid"] is not None
    assert "::" in progress["last_nodeid"]
    assert "T" in progress["updated_at"] and "-" in progress["updated_at"]


def test_pieza_b_backfilla_fila_aborted_sin_forense(monkeypatch, tmp_path) -> None:
    mod = _load_with_redirects(monkeypatch, tmp_path)
    last_run = tmp_path / "last-run.json"
    last_run.write_text(
        json.dumps({"status": "aborted", "level": "all", "exit_code": None}),
        encoding="utf-8",
    )
    (tmp_path / "pytest-progress.json").write_text(
        json.dumps(
            {
                "last_nodeid": "tests/unit/test_z.py::test_zz",
                "updated_at": "2026-10-25T12:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    mod._reconcile_dead_run()
    data = json.loads(last_run.read_text(encoding="utf-8"))
    assert data["reconciled_reason"] == "backfill_070h_row_predates_forensic_fields"
    assert data["last_nodeid"] == "tests/unit/test_z.py::test_zz"
    assert "reconciled_at" in data


def test_pieza_b_no_toque_fila_aborted_ya_forense(monkeypatch, tmp_path) -> None:
    mod = _load_with_redirects(monkeypatch, tmp_path)
    last_run = tmp_path / "last-run.json"
    original = {
        "status": "aborted",
        "reconciled_reason": "dead_pid",
        "reconciled_at": "2026-10-25T11:00:00+00:00",
        "last_nodeid": "original",
    }
    last_run.write_text(json.dumps(original), encoding="utf-8")
    mod._reconcile_dead_run()
    data = json.loads(last_run.read_text(encoding="utf-8"))
    assert data["reconciled_reason"] == "dead_pid"
    assert data["last_nodeid"] == "original"


def test_mutation_sin_persistencia_incremental_el_test_cae(
    monkeypatch, tmp_path
) -> None:
    """MUTATION: si la persistencia por linea desaparece (solo el write final
    del log al terminar), la muerte de la corrida se lleva la salida y este
    test debe caer."""
    mod = _load_with_redirects(monkeypatch, tmp_path)
    mod._last_fake = _FakeProc(list(OUTPUT_LINES))
    rc, _failed, _errors, timed_out = mod.stream_pytest(["pytest"])
    log = (tmp_path / "last-run.log").read_text(encoding="utf-8")
    if not log.strip():
        raise AssertionError("sin persistencia incremental, la salida se pierde")
    # Control positivo: con la persistencia real, el log NO esta vacio.
    assert rc == 0 and timed_out is False
