"""Pruebas de concurrencia del ledger de autorizacion de push.

Before: cada caso prepara reservas reales y fuerza una ventana entre la
lectura y el reemplazo del JSONL.
During: las pruebas ejercitan hilos, procesos, append legacy, reserva de
intentos, lectores Windows y agotamiento del plazo de serializacion.
After: los invariantes de WOT-2026-239k quedan comprobados contra bytes,
estados efectivos, locks y causas de infraestructura nombradas.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from scripts.flight import verify_user_authorization as vua


_CANDIDATE_CREATED = "2026-01-01T00:00:01.000Z"
_ANCHOR = "anchor-message"
_MODULE_PATH = Path(vua.__file__).resolve()


def _record(message_id: str, *, full_sha: str, remote_sha: str = "b" * 40) -> dict:
    """Construye un registro de intento completo y determinista."""
    return {
        "messageId": message_id,
        "createdAt": _CANDIDATE_CREATED,
        "textSha256": "0" * 64,
        "fullSha": full_sha,
        "anchorMessageId": _ANCHOR,
        "repo": "demo_repo",
        "ref": "refs/heads/main",
        "remoteSha": remote_sha,
    }


def _rows(path: Path) -> list[dict]:
    """Lee sólo filas JSON y deja intactos los bytes no JSON para el llamador."""
    result = []
    for raw in path.read_bytes().splitlines():
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            result.append(value)
    return result


def _run_thread_reconciliations(
    ledger: vua.PushAuthorityLedger,
    records: list[dict],
    patch,
    *,
    barrier_timeout: float = 0.08,
) -> tuple[list[object], list[tuple[str, int]], list[BaseException]]:
    """Ejecuta reconciliaciones con un gancho observable tras cada lectura.

    Before: los registros ya están reservados en el ledger y patch es un
        contexto monkeypatch activo para esta corrida.
    During: intercepta sólo la lectura del ledger y os.replace, registrando
        la ruptura de la barrera como evidencia de serializacion.
    After: devuelve resultados, eventos ordenados y excepciones de los hilos.
    """
    read_barrier = threading.Barrier(len(records))
    events: list[tuple[str, int]] = []
    errors: list[BaseException] = []
    event_lock = threading.Lock()
    ledger_path = ledger.path.resolve()
    original_read_bytes = Path.read_bytes
    original_replace = vua.os.replace

    def instrumented_read(path: Path, *args, **kwargs):
        value = original_read_bytes(path, *args, **kwargs)
        if path.resolve() == ledger_path:
            with event_lock:
                events.append(("read", threading.get_ident()))
                events.append(("barrier-called", threading.get_ident()))
            try:
                read_barrier.wait(timeout=barrier_timeout)
            except threading.BrokenBarrierError:
                with event_lock:
                    events.append(("barrier-broken", threading.get_ident()))
        return value

    def instrumented_replace(source, target, *args, **kwargs):
        if Path(target).resolve() == ledger_path:
            with event_lock:
                events.append(("replace", threading.get_ident()))
        return original_replace(source, target, *args, **kwargs)

    patch.setattr(Path, "read_bytes", instrumented_read)
    patch.setattr(vua.os, "replace", instrumented_replace)
    results: list[object] = [None] * len(records)

    def worker(index: int, record: dict) -> None:
        try:
            results[index] = vua.reconcile_push_attempt(
                ledger, record, record["fullSha"]
            )
        except BaseException as exc:  # pragma: no cover - asserted by caller
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=(index, record))
        for index, record in enumerate(records)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert all(not thread.is_alive() for thread in threads)
    return results, events, errors


def _hold_os_lock(path: Path):
    """Retiene el lock de fichero elegido por el contrato durante un bloque."""

    @contextlib.contextmanager
    def holder():
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a+b")
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            with contextlib.suppress(OSError):
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    return holder()


def test_m01_distinct_concurrent_reconciliations_are_not_lost(
    tmp_path: Path, monkeypatch
):
    """m-01: dos messageId distintos conservan ambos CONSUMIDO."""
    ledger = vua.PushAuthorityLedger(tmp_path / "ledger.jsonl")
    records = [
        _record("message-a", full_sha="a" * 40),
        _record("message-b", full_sha="c" * 40),
    ]
    assert all(ledger.consume(record) for record in records)

    with monkeypatch.context() as patch:
        results, _events, errors = _run_thread_reconciliations(ledger, records, patch)

    assert errors == []
    assert results == [True, True]
    states = {row["messageId"]: row["state"] for row in _rows(ledger.path)}
    assert states == {"message-a": "CONSUMIDO", "message-b": "CONSUMIDO"}


def test_m02_barrier_proves_serialized_second_read(tmp_path: Path, monkeypatch):
    """m-02: el gancho no puede desaparecer sin que la prueba falle."""
    ledger = vua.PushAuthorityLedger(tmp_path / "ledger.jsonl")
    records = [
        _record("message-a", full_sha="a" * 40),
        _record("message-b", full_sha="c" * 40),
    ]
    assert all(ledger.consume(record) for record in records)

    with monkeypatch.context() as patch:
        results, events, errors = _run_thread_reconciliations(ledger, records, patch)

    assert errors == []
    assert results == [True, True]
    barrier_events = [event for event in events if event[0] == "barrier-broken"]
    read_positions = [index for index, event in enumerate(events) if event[0] == "read"]
    replace_positions = [
        index for index, event in enumerate(events) if event[0] == "replace"
    ]
    assert len(read_positions) == 2
    assert len(replace_positions) == 2
    barrier_calls = [event for event in events if event[0] == "barrier-called"]
    assert len(barrier_calls) == 2
    assert len(barrier_events) >= 1
    assert min(replace_positions) < read_positions[1]


def test_m03_processes_share_the_ledger_serialization(tmp_path: Path):
    """m-03: una barrera de fichero comprueba exclusion entre procesos reales."""
    ledger_path = tmp_path / "ledger.jsonl"
    ledger = vua.PushAuthorityLedger(ledger_path)
    records = [
        _record("process-a", full_sha="a" * 40),
        _record("process-b", full_sha="c" * 40),
    ]
    assert all(ledger.consume(record) for record in records)
    barrier_dir = tmp_path / "process-barrier"
    barrier_dir.mkdir()
    child = r"""
import importlib.util
import json
import sys
import time
from pathlib import Path

module_path, ledger_path, barrier_dir, index, record_json = sys.argv[1:]
spec = importlib.util.spec_from_file_location("vua_direct", module_path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
ledger_path = Path(ledger_path).resolve()
barrier_dir = Path(barrier_dir)
original_read_bytes = module.Path.read_bytes

def synchronized_read(path, *args, **kwargs):
    value = original_read_bytes(path, *args, **kwargs)
    if path.resolve() == ledger_path:
        (barrier_dir / ("ready-" + index)).write_text("ready", encoding="ascii")
        deadline = time.monotonic() + 5
        while not (barrier_dir / "go").exists() and time.monotonic() < deadline:
            time.sleep(0.005)
        (barrier_dir / ("arrived-" + index)).write_text("arrived", encoding="ascii")
        deadline = time.monotonic() + 1
        while len(list(barrier_dir.glob("arrived-*"))) < 2 and time.monotonic() < deadline:
            time.sleep(0.005)
    return value

module.Path.read_bytes = synchronized_read
ledger = module.PushAuthorityLedger(ledger_path)
record = json.loads(record_json)
if not module.reconcile_push_attempt(ledger, record, record["fullSha"]):
    raise SystemExit("reconcile returned false")
print("OK", flush=True)
"""
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-c",
                child,
                str(_MODULE_PATH),
                str(ledger_path),
                str(barrier_dir),
                str(index),
                json.dumps(record),
            ],
            cwd=str(tmp_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        for index, record in enumerate(records)
    ]
    outputs = []
    try:
        deadline = time.monotonic() + 5
        while len(list(barrier_dir.glob("ready-*"))) < 1:
            if time.monotonic() >= deadline:
                diagnostics = []
                for process in processes:
                    stdout, stderr = process.communicate(timeout=5)
                    diagnostics.append((stdout, stderr, process.returncode))
                raise AssertionError(
                    f"los procesos no alcanzaron la barrera: {diagnostics}"
                )
            time.sleep(0.01)
        (barrier_dir / "go").write_text("go", encoding="ascii")
        outputs = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=10)
            outputs.append((stdout, stderr, process.returncode))
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait()

    assert all(returncode == 0 for _stdout, _stderr, returncode in outputs), outputs
    assert all(stdout.strip() == "OK" for stdout, _stderr, _returncode in outputs), (
        outputs
    )
    states = {row["messageId"]: row["state"] for row in _rows(ledger_path)}
    assert states == {"process-a": "CONSUMIDO", "process-b": "CONSUMIDO"}


@pytest.mark.parametrize("legacy", [False, True], ids=["reserve", "legacy"])
def test_m04_append_during_rewrite_is_retained(
    tmp_path: Path, monkeypatch, legacy: bool
):
    """m-04: ambos caminos de append quedan dentro de la misma serializacion."""
    ledger = vua.PushAuthorityLedger(tmp_path / f"ledger-{legacy}.jsonl")
    primary = _record("primary", full_sha="a" * 40)
    appended = _record("appended", full_sha="c" * 40)
    if legacy:
        appended = {
            key: value
            for key, value in appended.items()
            if key not in {"repo", "ref", "remoteSha"}
        }
    assert ledger.consume(primary)
    append_started = threading.Event()
    append_errors: list[BaseException] = []
    original_read_bytes = Path.read_bytes
    armed = True
    append_thread: threading.Thread | None = None

    def append_worker() -> None:
        append_started.set()
        try:
            assert ledger.consume(appended)
        except BaseException as exc:  # pragma: no cover - asserted by caller
            append_errors.append(exc)

    def hooked_read(path: Path, *args, **kwargs):
        nonlocal append_thread, armed
        value = original_read_bytes(path, *args, **kwargs)
        if path.resolve() == ledger.path.resolve() and armed:
            armed = False
            append_thread = threading.Thread(target=append_worker)
            append_thread.start()
            assert append_started.wait(timeout=1)
            time.sleep(0.05)
        return value

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_bytes", hooked_read)
        assert vua.reconcile_push_attempt(ledger, primary, primary["fullSha"])

    assert append_thread is not None
    append_thread.join(timeout=5)
    assert not append_thread.is_alive()
    assert append_errors == []
    appended_rows = [
        row for row in _rows(ledger.path) if row.get("messageId") == "appended"
    ]
    assert len(appended_rows) == 1
    if legacy:
        assert ledger._lock_path("appended").exists()
    else:
        assert ledger._attempt_lock_path("appended").exists()


def test_m05_repeated_reconciliations_have_no_static_temp_collision(
    tmp_path: Path, monkeypatch
):
    """m-05: veinte carreras no pierden filas ni producen ledger-append-failed."""
    for iteration in range(20):
        ledger = vua.PushAuthorityLedger(tmp_path / f"ledger-{iteration}.jsonl")
        records = [
            _record(f"a-{iteration}", full_sha="a" * 40),
            _record(f"b-{iteration}", full_sha="c" * 40),
        ]
        assert all(ledger.consume(record) for record in records)
        with monkeypatch.context() as patch:
            results, _events, errors = _run_thread_reconciliations(
                ledger, records, patch, barrier_timeout=0.03
            )
        assert errors == []
        assert results == [True, True]
        states = {row["messageId"]: row["state"] for row in _rows(ledger.path)}
        assert states == {
            f"a-{iteration}": "CONSUMIDO",
            f"b-{iteration}": "CONSUMIDO",
        }


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="m-06 verifica el reemplazo con un lector abierto en Windows",
)
def test_m06_open_reader_does_not_create_unnamed_ledger_failure(tmp_path: Path):
    """m-06: el reemplazo Windows reintenta y conserva una causa nombrada."""
    ledger = vua.PushAuthorityLedger(tmp_path / "ledger.jsonl")
    record = _record("windows-reader", full_sha="a" * 40)
    assert ledger.consume(record)
    before = ledger.path.read_bytes()
    outcome: dict[str, object] = {}
    reader = ledger.path.open("r", encoding="utf-8")

    def reconcile() -> None:
        try:
            outcome["result"] = vua.reconcile_push_attempt(
                ledger, record, record["fullSha"]
            )
        except BaseException as exc:  # pragma: no cover - platform-specific
            outcome["error"] = exc

    thread = threading.Thread(target=reconcile)
    thread.start()
    time.sleep(0.05)
    reader.close()
    thread.join(timeout=5)
    assert not thread.is_alive()
    if "error" in outcome:
        error = outcome["error"]
        assert isinstance(error, vua.InfraError)
        assert error.cause == "ledger-replace-timeout"
        assert ledger.path.read_bytes() == before
        assert ledger._attempt_lock_path(record["messageId"]).exists()
    else:
        assert outcome["result"] is True
        assert ledger.is_consumed(record["messageId"])


def test_m07_unreconciled_lines_are_byte_identical(tmp_path: Path):
    """m-07: sólo cambia la fila reconciliada, incluso con bytes no JSON."""
    ledger = vua.PushAuthorityLedger(tmp_path / "ledger.jsonl")
    record = _record("target", full_sha="a" * 40)
    assert ledger.consume(record)
    target = _rows(ledger.path)[0]
    compact_target = json.dumps(
        target, ensure_ascii=False, separators=(",", ":")
    ).encode()
    foreign = b'{"producer":"other","messageId":"foreign"}\n'
    raw = compact_target + b"\r\n" + b"not-json\r\n" + foreign
    ledger.path.write_bytes(raw)
    before_parts = ledger.path.read_bytes().splitlines(keepends=True)
    target_index = 0
    assert vua.reconcile_push_attempt(ledger, record, record["fullSha"])
    after_parts = ledger.path.read_bytes().splitlines(keepends=True)
    assert len(after_parts) == len(before_parts)
    assert after_parts[1:] == before_parts[1:]
    assert after_parts[target_index] != before_parts[target_index]
    assert json.loads(after_parts[target_index])["state"] == "CONSUMIDO"


def test_m08_lock_timeout_is_fail_closed_and_named(tmp_path: Path):
    """m-08: sin lock en plazo no hay escritura ni cambio de estado."""
    ledger = vua.PushAuthorityLedger(tmp_path / "ledger.jsonl")
    record = _record("timeout", full_sha="a" * 40)
    assert ledger.consume(record)
    before = ledger.path.read_bytes()
    lock_path = ledger.path.with_name(ledger.path.name + ".lock")
    with _hold_os_lock(lock_path):
        ledger.lock_timeout = 0.05
        with pytest.raises(vua.InfraError) as caught:
            vua.reconcile_push_attempt(ledger, record, record["fullSha"])
    assert caught.value.cause == "ledger-lock-timeout"
    assert ledger.path.read_bytes() == before
    assert ledger._attempt_lock_path(record["messageId"]).exists()
    assert _rows(ledger.path)[0]["state"] == "INTENTO"


def test_m09_same_record_concurrent_reconciliation_has_one_effective_state(
    tmp_path: Path, monkeypatch
):
    """m-09: dos reconciliaciones del mismo intento convergen a CONSUMIDO."""
    ledger = vua.PushAuthorityLedger(tmp_path / "ledger.jsonl")
    record = _record("same-record", full_sha="a" * 40)
    assert ledger.consume(record)
    with monkeypatch.context() as patch:
        results, _events, errors = _run_thread_reconciliations(
            ledger, [record, record], patch
        )

    assert errors == []
    assert results == [True, True]
    assert ledger.is_consumed(record["messageId"]) is True
    context = vua.PushContext(
        project_root=tmp_path,
        remote="origin",
        branch="main",
        repo="demo_repo",
        full_sha=record["fullSha"],
        sha12=record["fullSha"][:12],
        commit_count=1,
        remote_sha=record["remoteSha"],
        expected=vua.ExpectedAuthorization.from_git_parts(
            repo="demo_repo",
            remote="origin",
            branch="main",
            sha12=record["fullSha"][:12],
            commit_count=1,
            full_sha=record["fullSha"],
        ),
    )
    assert ledger.has_retryable_attempt(context) is False
    rows = _rows(ledger.path)
    assert len(rows) == 1
    assert rows[0]["state"] == "CONSUMIDO"
