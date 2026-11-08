import importlib.util
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


_REAL_OS_FSYNC = os.fsync
ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "flight" / "registry_ops.py"

_REGISTRY_OPS_SPEC = importlib.util.spec_from_file_location("registry_ops", SCRIPT)
_REGISTRY_OPS_MODULE = importlib.util.module_from_spec(_REGISTRY_OPS_SPEC)
_REGISTRY_OPS_SPEC.loader.exec_module(_REGISTRY_OPS_MODULE)
RECONCILE_FIELDS = _REGISTRY_OPS_MODULE.RECONCILE_FIELDS


def test_registry_ops_docstring_describes_durability_limits():
    docstring = _REGISTRY_OPS_MODULE.__doc__
    assert "registry via temporal con fsync del fichero antes del replace" in docstring
    assert "ledger con flush pero sin fsync" in docstring
    assert "Ningun fsync cubre el directorio contenedor" in docstring


def run_cli(
    registry,
    *args,
    ledger=None,
    roster=None,
    snapshot=None,
    auto_roster=True,
    cwd=None,
):
    if "--apply" in args and roster is None and auto_roster:
        roster = registry.parent / "roster.json"
        write_roster(roster)
    command = [sys.executable, str(SCRIPT), *args, "--registry", str(registry)]
    if ledger is not None:
        command += ["--ledger", str(ledger)]
    if roster is not None:
        command += ["--roster", str(roster)]
    if snapshot is not None:
        command += ["--snapshot", str(snapshot)]
    return subprocess.run(command, capture_output=True, text=True, check=False, cwd=cwd)


def write_registry(path, sessions=None):
    data = {"sessions": [] if sessions is None else sessions}
    path.write_text(json.dumps(data) + "\n", encoding="utf-8")


def write_roster(path, state="ACTIVO", entry=None):
    active_entry = {"estado": state} if entry is None else entry
    path.write_text(
        json.dumps({"active_roles": {"orquestador": active_entry}}) + "\n",
        encoding="utf-8",
    )


def session(code="IM-1"):
    return {
        "code": code,
        "role": "builder",
        "slot": "builder-1",
        "threadId": "thread-1",
        "started": "2026-11-08T10:00:00+01:00",
        "status": "ACTIVE",
        "brief": "preserve me",
        "worktree": "tree-1",
    }


def snapshot_entry(thread_id="thread-1", **overrides):
    entry = {
        "threadId": thread_id,
        "settled": True,
        "status": "SETTLED",
        "updatedAt": "2026-11-08T11:00:00+01:00",
        "modelo": "codex",
        "cuenta": "plana",
    }
    entry.update(overrides)
    return entry


def _collision_command(command, apply=False):
    args = [command]
    if command == "alta":
        args += [
            "--code",
            "IM-2",
            "--role",
            "builder",
            "--slot",
            "slot-2",
            "--thread-id",
            "thread-2",
            "--started",
            "now",
            "--status",
            "ACTIVE",
        ]
    elif command == "asiento":
        args += ["--code", "IM-1", "--status", "SETTLED"]
    elif command == "nota":
        args += ["--code", "IM-1", "--nota", "note"]
    else:
        args += ["--snapshot", "SNAPSHOT_PLACEHOLDER"]
    if command == "reconcile" or command in {"alta", "asiento", "nota"}:
        args += ["--by", "collision-test", "--reason", "collision-test"]
    if apply:
        args += ["--apply"]
    return args


@pytest.mark.parametrize("apply", [False, True])
def test_dod_a_registry_ledger_collision_rejected_without_write(tmp_path, apply):
    registry = tmp_path / "registry.json"
    write_registry(registry)
    before = registry.read_bytes()
    result = run_cli(
        registry,
        *_collision_command("alta", apply),
        ledger=registry,
        auto_roster=apply,
    )
    assert result.returncode == 2
    assert registry.read_bytes() == before
    assert "--registry=" in result.stderr and "--ledger=" in result.stderr


def test_dod_a_registry_roster_collision_rejected_without_write(tmp_path):
    registry = tmp_path / "registry.json"
    write_registry(registry)
    before = registry.read_bytes()
    result = run_cli(
        registry,
        *_collision_command("alta", True),
        ledger=tmp_path / "ledger.jsonl",
        roster=registry,
        auto_roster=False,
    )
    assert result.returncode == 2
    assert registry.read_bytes() == before
    assert "--registry=" in result.stderr and "--roster=" in result.stderr


def test_dod_a_ledger_roster_collision_rejected_before_corruption(tmp_path):
    registry = tmp_path / "registry.json"
    ledger = tmp_path / "shared.jsonl"
    write_registry(registry)
    ledger.write_bytes(b"roster-before\n")
    registry_before = registry.read_bytes()
    before = ledger.read_bytes()
    result = run_cli(
        registry,
        *_collision_command("alta", True),
        ledger=ledger,
        roster=ledger,
        auto_roster=False,
    )
    assert result.returncode == 2
    assert ledger.read_bytes() == before
    assert registry.read_bytes() == registry_before
    assert "--ledger=" in result.stderr and "--roster=" in result.stderr


@pytest.mark.parametrize("apply", [False, True])
def test_dod_a_registry_snapshot_collision_rejected(tmp_path, apply):
    registry = tmp_path / "registry.json"
    write_registry(registry)
    before = registry.read_bytes()
    args = _collision_command("reconcile", apply)
    args[args.index("SNAPSHOT_PLACEHOLDER")] = str(registry)
    result = run_cli(
        registry,
        *args,
        ledger=tmp_path / "ledger.jsonl",
        snapshot=registry,
        auto_roster=apply,
    )
    assert result.returncode == 2
    assert registry.read_bytes() == before
    assert "--registry=" in result.stderr and "--snapshot=" in result.stderr


def test_dod_a_ledger_snapshot_collision_rejected_before_corruption(tmp_path):
    registry = tmp_path / "registry.json"
    ledger = tmp_path / "shared.jsonl"
    snapshot = ledger
    write_registry(registry)
    snapshot.write_bytes(b"snapshot-before\n")
    registry_before = registry.read_bytes()
    before = snapshot.read_bytes()
    result = run_cli(
        registry,
        *_collision_command("reconcile", True),
        ledger=ledger,
        roster=tmp_path / "roster.json",
        snapshot=snapshot,
    )
    assert result.returncode == 2
    assert snapshot.read_bytes() == before
    assert registry.read_bytes() == registry_before
    assert "--ledger=" in result.stderr and "--snapshot=" in result.stderr


def test_dod_a_roster_snapshot_collision_rejected(tmp_path):
    registry = tmp_path / "registry.json"
    shared = tmp_path / "shared.json"
    write_registry(registry)
    shared.write_bytes(b"shared-before\n")
    registry_before = registry.read_bytes()
    shared_before = shared.read_bytes()
    result = run_cli(
        registry,
        *_collision_command("reconcile", True),
        ledger=tmp_path / "ledger.jsonl",
        roster=shared,
        snapshot=shared,
        auto_roster=False,
    )
    assert result.returncode == 2
    assert "--roster=" in result.stderr and "--snapshot=" in result.stderr
    assert registry.read_bytes() == registry_before
    assert shared.read_bytes() == shared_before


@pytest.mark.parametrize(
    "path_style",
    [
        lambda path: str(path).upper(),
        lambda path: str(path).replace("\\", "/"),
        lambda path: str(path.parent / "nested" / ".." / path.name),
        lambda path: path.name,
    ],
)
def test_dod_a_equivalent_ledger_roster_paths_rejected(tmp_path, path_style):
    registry = tmp_path / "registry.json"
    roster = tmp_path / "roster.json"
    write_registry(registry)
    write_roster(roster)
    ledger = path_style(roster)
    result = run_cli(
        registry,
        *_collision_command("alta", True),
        ledger=ledger,
        roster=roster,
        auto_roster=False,
        cwd=tmp_path,
    )
    assert result.returncode == 2
    assert "--ledger=" in result.stderr and "--roster=" in result.stderr


def test_dod_a_nonexistent_case_variant_ledger_roster_rejected(tmp_path):
    registry = tmp_path / "registry.json"
    ledger = tmp_path / "shared.jsonl"
    roster = tmp_path / "SHARED.JSONL"
    write_registry(registry)
    assert not ledger.exists()
    assert not roster.exists()
    result = run_cli(
        registry,
        *_collision_command("alta", True),
        ledger=ledger,
        roster=roster,
        auto_roster=False,
    )
    assert result.returncode == 2
    assert "--ledger=" in result.stderr and "--roster=" in result.stderr


def test_dod_a_registry_hardlink_ledger_collision_rejected(tmp_path):
    registry = tmp_path / "registry.json"
    ledger = tmp_path / "ledger-hardlink.jsonl"
    roster = tmp_path / "roster.json"
    write_registry(registry, [session()])
    write_roster(roster)
    try:
        os.link(registry, ledger)
    except (OSError, NotImplementedError):
        pytest.skip("hardlinks no soportados en este filesystem")
    before = registry.read_bytes()
    result = run_cli(
        registry,
        "asiento",
        "--code",
        "IM-1",
        "--status",
        "SETTLED",
        "--by",
        "hardlink-test",
        "--reason",
        "hardlink-registry",
        "--apply",
        ledger=ledger,
        roster=roster,
        auto_roster=False,
    )
    assert result.returncode == 2
    assert "--registry=" in result.stderr and "--ledger=" in result.stderr
    assert registry.read_bytes() == before


def test_dod_a_roster_hardlink_ledger_collision_rejected(tmp_path):
    registry = tmp_path / "registry.json"
    ledger = tmp_path / "ledger-hardlink.jsonl"
    roster = tmp_path / "roster.json"
    write_registry(registry, [session()])
    write_roster(roster)
    try:
        os.link(roster, ledger)
    except (OSError, NotImplementedError):
        pytest.skip("hardlinks no soportados en este filesystem")
    before = roster.read_bytes()
    result = run_cli(
        registry,
        "asiento",
        "--code",
        "IM-1",
        "--status",
        "SETTLED",
        "--by",
        "hardlink-test",
        "--reason",
        "hardlink-roster",
        "--apply",
        ledger=ledger,
        roster=roster,
        auto_roster=False,
    )
    assert result.returncode == 2
    assert "--ledger=" in result.stderr and "--roster=" in result.stderr
    assert roster.read_bytes() == before


def test_dod_a_distinct_paths_remain_valid(tmp_path):
    registry = tmp_path / "registry.json"
    write_registry(registry)
    result = run_cli(
        registry,
        *_collision_command("alta", False),
        ledger=tmp_path / "ledger.jsonl",
    )
    assert result.returncode == 0


@pytest.mark.parametrize(
    "extra,kwargs",
    [
        (["--ledger", ""], {}),
        ([], {"roster": Path(".")}),
        (["--ledger", r"\\localhost\missing\ledger.jsonl"], {}),
    ],
)
def test_dod_a_pathological_inputs_have_controlled_result(tmp_path, extra, kwargs):
    registry = tmp_path / "registry.json"
    write_registry(registry)
    result = run_cli(
        registry,
        *_collision_command("alta", True),
        *extra,
        ledger=tmp_path / "ledger.jsonl",
        auto_roster=not kwargs,
        **kwargs,
    )
    assert result.returncode in {0, 2, 3, 4, 5, 6}
    assert "Traceback" not in result.stderr


def test_dod_a_path_with_spaces_has_controlled_result(tmp_path):
    registry = tmp_path / "mi registro.json"
    write_registry(registry)
    result = run_cli(
        registry, *_collision_command("alta", False), ledger=tmp_path / "ledger.jsonl"
    )
    assert result.returncode == 0
    assert "Traceback" not in result.stderr


def write_driver(tmp_path, mode):
    body = {
        "slow": """
import os
original_apply = mod._apply_change
def slow_apply(*args, **kwargs):
    real_mutate = args[-1]
    def delayed(data):
        witness_path = os.environ.get("REGISTRY_OPS_TEST_WITNESS")
        if witness_path:
            Path(witness_path).write_text("ready", encoding="utf-8")
        real_mutate(data)
        second_started = os.environ.get("REGISTRY_OPS_TEST_SECOND_STARTED")
        if second_started:
            deadline = time.monotonic() + 10
            while not Path(second_started).exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            if not Path(second_started).exists():
                raise RuntimeError(
                    "el segundo escritor nunca intento el lock "
                    "(_lock_try) en 10s"
                )
        time.sleep(0.05)
    return original_apply(*args[:-1], delayed, **kwargs)
mod._apply_change = slow_apply
""",
        "signal_lock_attempt": """
import os
signal_path = os.environ.get("REGISTRY_OPS_TEST_SECOND_STARTED")
real_lock_try = mod._lock_try
signaled = False
def spy_lock_try(handle):
    global signaled
    if signal_path and not signaled:
        Path(signal_path).write_text("attempted", encoding="utf-8")
        signaled = True
    return real_lock_try(handle)
mod._lock_try = spy_lock_try
""",
        "ledger_fail": 'mod._append_ledger_handle = lambda *args, **kwargs: (_ for _ in ()).throw(OSError("ledger failure"))',
        "registry_fail": 'mod._write_registry = lambda *args, **kwargs: (_ for _ in ()).throw(OSError("registry failure"))',
        "rotate_fail": 'mod._rotate_backups = lambda *args, **kwargs: (_ for _ in ()).throw(OSError("rotate failure"))',
        "lock_open_fail": """
real_open = Path.open
def spy_open(self, *args, **kwargs):
    if str(self).endswith(".lock"):
        raise OSError(13, "simulado: permiso denegado al abrir el lock")
    return real_open(self, *args, **kwargs)
Path.open = spy_open
""",
        "lock_release_fail": """
import msvcrt
real_locking = msvcrt.locking
def spy_locking(fd, mode, nbytes):
    if mode == msvcrt.LK_UNLCK:
        raise OSError(0, "simulado: fallo al liberar el lock")
    return real_locking(fd, mode, nbytes)
msvcrt.locking = spy_locking
""",
        "write_and_lock_release_fail": """
import msvcrt
def fail_write(*args, **kwargs):
    raise OSError("simulado: fallo de escritura del registry")
mod._write_registry = fail_write
real_locking = msvcrt.locking
def spy_locking(fd, mode, nbytes):
    if mode == msvcrt.LK_UNLCK:
        raise OSError(0, "simulado: fallo al liberar el lock")
    return real_locking(fd, mode, nbytes)
msvcrt.locking = spy_locking
""",
    }[mode]
    driver = tmp_path / f"driver_{mode}.py"
    driver.write_text(
        f"""import importlib.util
import sys
import time
from pathlib import Path

source = Path({str(SCRIPT)!r})
spec = importlib.util.spec_from_file_location("registry_ops_driver", source)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
{body}
raise SystemExit(mod.main(sys.argv[1:]))
""",
        encoding="utf-8",
    )
    return driver


def test_alta_dry_run_prints_session_without_writing(tmp_path):
    registry = tmp_path / "registry.json"
    write_registry(registry)
    result = run_cli(
        registry,
        "alta",
        "--code",
        "IM-2",
        "--role",
        "builder",
        "--slot",
        "slot-2",
        "--thread-id",
        "thread-2",
        "--started",
        "now",
        "--status",
        "ACTIVE",
        "--nota",
        "hello",
        "--by",
        "tester",
        "--reason",
        "test",
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["code"] == "IM-2"
    assert json.loads(registry.read_text(encoding="utf-8"))["sessions"] == []


def test_alta_apply_writes_optional_fields_backup_and_ledger(tmp_path):
    registry = tmp_path / "registry.json"
    ledger = tmp_path / "changes.jsonl"
    write_registry(registry)
    result = run_cli(
        registry,
        "alta",
        "--code",
        "IM-2",
        "--role",
        "builder",
        "--slot",
        "slot-2",
        "--thread-id",
        "thread-2",
        "--started",
        "now",
        "--status",
        "ACTIVE",
        "--generation",
        "2",
        "--by",
        "tester",
        "--reason",
        "test",
        "--apply",
        ledger=ledger,
    )
    assert result.returncode == 0
    data = json.loads(registry.read_text(encoding="utf-8"))
    assert data["sessions"][0]["generation"] == "2"
    assert "nota" not in data["sessions"][0]
    assert (
        json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])["detail"]
        == "code=IM-2"
    )
    assert json.loads(
        registry.with_name("registry.json.bak1").read_text(encoding="utf-8")
    ) == {"sessions": []}


def test_alta_rejects_duplicate_code(tmp_path):
    registry = tmp_path / "registry.json"
    write_registry(registry, [session()])
    result = run_cli(
        registry,
        "alta",
        "--code",
        "IM-1",
        "--role",
        "builder",
        "--slot",
        "s",
        "--thread-id",
        "t",
        "--started",
        "s",
        "--status",
        "ACTIVE",
        "--by",
        "b",
        "--reason",
        "r",
    )
    assert result.returncode == 4
    assert "sesion duplicada" in result.stderr


def test_asiento_dry_run_changes_only_transition_fields(tmp_path):
    registry = tmp_path / "registry.json"
    write_registry(registry, [session()])
    result = run_cli(
        registry,
        "asiento",
        "--code",
        "IM-1",
        "--status",
        "SETTLED",
        "--by",
        "b",
        "--reason",
        "r",
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["cambios"] == {"status": ["ACTIVE", "SETTLED"]}


def test_asiento_apply_preserves_brief_and_updates_fields(tmp_path):
    registry = tmp_path / "registry.json"
    write_registry(registry, [session()])
    result = run_cli(
        registry,
        "asiento",
        "--code",
        "IM-1",
        "--status",
        "SETTLED",
        "--worktree",
        "tree-2",
        "--by",
        "b",
        "--reason",
        "r",
        "--apply",
    )
    assert result.returncode == 0
    updated = json.loads(registry.read_text(encoding="utf-8"))["sessions"][0]
    assert updated["status"] == "SETTLED"
    assert updated["worktree"] == "tree-2"
    assert updated["brief"] == "preserve me"


@pytest.mark.parametrize("command", ["asiento", "nota"])
def test_existing_code_is_required(command, tmp_path):
    registry = tmp_path / "registry.json"
    write_registry(registry)
    args = [command, "--code", "MISSING", "--by", "b", "--reason", "r"]
    if command == "asiento":
        args += ["--status", "ACTIVE"]
    else:
        args += ["--nota", "x"]
    result = run_cli(registry, *args)
    assert result.returncode == 4
    assert "sesion no encontrada" in result.stderr


def test_asiento_requires_a_mutable_field(tmp_path):
    registry = tmp_path / "registry.json"
    write_registry(registry, [session()])
    result = run_cli(
        registry, "asiento", "--code", "IM-1", "--by", "b", "--reason", "r"
    )
    assert result.returncode == 2
    assert "sin campos" in result.stderr


@pytest.mark.parametrize(
    "nota_args", [("--nota", "new"), ("--started-nota", "started")]
)
def test_nota_replace_and_append_preserve_unrelated_fields(tmp_path, nota_args):
    registry = tmp_path / "registry.json"
    write_registry(registry, [session()])
    result = run_cli(
        registry,
        "nota",
        "--code",
        "IM-1",
        *nota_args,
        "--by",
        "b",
        "--reason",
        "r",
        "--apply",
    )
    assert result.returncode == 0
    updated = json.loads(registry.read_text(encoding="utf-8"))["sessions"][0]
    assert updated["brief"] == "preserve me"
    assert (
        updated["nota" if nota_args[0] == "--nota" else "started_nota"] == nota_args[1]
    )


def test_nota_append_uses_literal_separator(tmp_path):
    registry = tmp_path / "registry.json"
    item = session()
    item["nota"] = "old"
    write_registry(registry, [item])
    result = run_cli(
        registry,
        "nota",
        "--code",
        "IM-1",
        "--nota",
        "new",
        "--append",
        "--by",
        "b",
        "--reason",
        "r",
        "--apply",
    )
    assert result.returncode == 0
    assert (
        json.loads(registry.read_text(encoding="utf-8"))["sessions"][0]["nota"]
        == "old | new"
    )


def test_started_nota_append_uses_literal_separator(tmp_path):
    registry = tmp_path / "registry.json"
    item = session()
    item["started_nota"] = "old"
    write_registry(registry, [item])
    result = run_cli(
        registry,
        "nota",
        "--code",
        "IM-1",
        "--started-nota",
        "new",
        "--append",
        "--by",
        "b",
        "--reason",
        "r",
        "--apply",
    )
    assert result.returncode == 0
    assert (
        json.loads(registry.read_text(encoding="utf-8"))["sessions"][0]["started_nota"]
        == "old | new"
    )


def test_nota_dry_run_existing_code_prints_plan_without_writing(tmp_path):
    registry = tmp_path / "registry.json"
    item = session()
    item["nota"] = "old"
    write_registry(registry, [item])
    before = registry.read_bytes()
    result = run_cli(
        registry,
        "nota",
        "--code",
        "IM-1",
        "--nota",
        "new",
        "--by",
        "b",
        "--reason",
        "r",
    )
    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "code": "IM-1",
        "campo": "nota",
        "valor_viejo": "old",
        "valor_nuevo": "new",
    }
    assert registry.read_bytes() == before


@pytest.mark.parametrize(
    "extra",
    [[], ["--nota", "x", "--started-nota", "y"]],
)
def test_nota_requires_exactly_one_note_field(tmp_path, extra):
    registry = tmp_path / "registry.json"
    write_registry(registry, [session()])
    result = run_cli(
        registry, "nota", "--code", "IM-1", *extra, "--by", "b", "--reason", "r"
    )
    assert result.returncode == 2


@pytest.mark.parametrize(
    "contents",
    [
        {},
        {"sessions": {}},
        {"sessions": [{"role": "builder"}]},
        {"sessions": [123]},
        b"{truncated",
    ],
)
def test_invalid_registry_forms_return_schema_error(tmp_path, contents):
    registry = tmp_path / "registry.json"
    if isinstance(contents, bytes):
        registry.write_bytes(contents)
    else:
        registry.write_text(json.dumps(contents), encoding="utf-8")
    result = run_cli(
        registry,
        "alta",
        "--code",
        "IM-2",
        "--role",
        "builder",
        "--slot",
        "s",
        "--thread-id",
        "t",
        "--started",
        "s",
        "--status",
        "ACTIVE",
        "--by",
        "b",
        "--reason",
        "r",
    )
    assert result.returncode == 2


def test_backup_rotation_and_ledger_newline_guard(tmp_path):
    registry = tmp_path / "registry.json"
    ledger = tmp_path / "ledger.jsonl"
    write_registry(registry, [session()])
    ledger.write_text('{"prior": true}', encoding="utf-8")
    for status in ("ONE", "TWO", "THREE"):
        result = run_cli(
            registry,
            "asiento",
            "--code",
            "IM-1",
            "--status",
            status,
            "--by",
            "b",
            "--reason",
            "r",
            "--apply",
            ledger=ledger,
        )
        assert result.returncode == 0
    assert (
        json.loads(registry.with_name("registry.json.bak1").read_text())["sessions"][0][
            "status"
        ]
        == "TWO"
    )
    assert (
        json.loads(registry.with_name("registry.json.bak2").read_text())["sessions"][0][
            "status"
        ]
        == "ONE"
    )
    assert (
        json.loads(registry.with_name("registry.json.bak3").read_text())["sessions"][0][
            "status"
        ]
        == "ACTIVE"
    )
    lines = ledger.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4
    assert all(json.loads(line) for line in lines)


def test_apply_returns_lock_error_when_lock_is_held(tmp_path):
    registry = tmp_path / "registry.json"
    write_registry(registry, [session()])
    module = __import__("importlib.util").util.spec_from_file_location(
        "registry_ops", SCRIPT
    )
    loaded = __import__("importlib.util").util.module_from_spec(module)
    module.loader.exec_module(loaded)
    lock = loaded._RegistryLock(registry.with_name("registry.json.lock"))
    with lock:
        result = run_cli(
            registry,
            "asiento",
            "--code",
            "IM-1",
            "--status",
            "SETTLED",
            "--by",
            "b",
            "--reason",
            "r",
            "--apply",
        )
    assert result.returncode == 5
    assert "bloqueo" in result.stderr


def test_dod_c_two_real_registry_ops_writers_keep_both_updates(tmp_path):
    for iteration in range(5):
        work = tmp_path / f"concurrent_{iteration}"
        work.mkdir()
        registry = work / "registry.json"
        ledger = work / "ledger.jsonl"
        roster = work / "roster.json"
        first = session("IM-1")
        second = session("IM-2")
        second["threadId"] = "thread-2"
        write_registry(registry, [first, second])
        write_roster(roster)
        slow = write_driver(work, "slow")
        normal = write_driver(work, "signal_lock_attempt")
        witness = work / "slow.ready"
        second_started = work / "second.started"
        common = [
            "asiento",
            "--status",
            "SETTLED",
            "--registry",
            str(registry),
            "--ledger",
            str(ledger),
            "--roster",
            str(roster),
            "--apply",
        ]
        slow_env = os.environ.copy()
        slow_env["REGISTRY_OPS_TEST_WITNESS"] = str(witness)
        slow_env["REGISTRY_OPS_TEST_SECOND_STARTED"] = str(second_started)
        slow_process = subprocess.Popen(
            [
                sys.executable,
                str(slow),
                *common[:1],
                "--code",
                "IM-1",
                *common[1:],
                "--by",
                "slow",
                "--reason",
                f"slow-{iteration}",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=slow_env,
        )
        deadline = time.monotonic() + 5
        while not witness.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        if not witness.exists():
            slow_process.terminate()
            slow_result = slow_process.communicate()
            pytest.fail(
                f"slow writer did not create witness within 5 seconds: {slow_result}"
            )
        normal_process = subprocess.Popen(
            [
                sys.executable,
                str(normal),
                *common[:1],
                "--code",
                "IM-2",
                *common[1:],
                "--by",
                "normal",
                "--reason",
                f"normal-{iteration}",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={
                **os.environ,
                "REGISTRY_OPS_TEST_SECOND_STARTED": str(second_started),
            },
        )
        try:
            slow_result = slow_process.communicate(timeout=30)
            normal_result = normal_process.communicate(timeout=30)
        except subprocess.TimeoutExpired as exc:
            slow_process.terminate()
            normal_process.terminate()
            slow_process.communicate()
            normal_process.communicate()
            pytest.fail(f"escritores concurrentes excedieron 30s: {exc}")
        assert slow_process.returncode == 0, slow_result
        assert normal_process.returncode == 0, normal_result
        final = json.loads(registry.read_text(encoding="utf-8"))
        assert {item["status"] for item in final["sessions"]} == {"SETTLED"}
        rows = [
            json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()
        ]
        assert len(rows) == 2
        assert {
            (row["change"], row["by"], row["reason"], row["detail"]) for row in rows
        } == {
            ("asiento", "slow", f"slow-{iteration}", "code=IM-1 campos=['status']"),
            ("asiento", "normal", f"normal-{iteration}", "code=IM-2 campos=['status']"),
        }


def test_write_ahead_ledger_failure_leaves_registry_unchanged(tmp_path):
    registry = tmp_path / "registry.json"
    write_registry(registry, [session()])
    roster = tmp_path / "roster.json"
    write_roster(roster)
    before = registry.read_bytes()
    driver = write_driver(tmp_path, "ledger_fail")
    result = subprocess.run(
        [
            sys.executable,
            str(driver),
            "nota",
            "--code",
            "IM-1",
            "--nota",
            "fail",
            "--by",
            "write-ahead",
            "--reason",
            "ledger-error",
            "--registry",
            str(registry),
            "--roster",
            str(roster),
            "--apply",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert registry.read_bytes() == before
    assert not registry.with_name("registry.json.bak1").exists()


def test_write_registry_fsync_precedes_replace(tmp_path, monkeypatch):
    registry = tmp_path / "registry.json"
    ledger = tmp_path / "ledger.jsonl"
    roster = tmp_path / "roster.json"
    write_registry(registry, [session()])
    write_roster(roster)
    before = registry.read_bytes()
    spec = importlib.util.spec_from_file_location("registry_ops_fsync", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    captured = []
    real_fsync = module.os.fsync

    def spy_fsync(fd):
        captured.append(registry.read_bytes())
        return real_fsync(fd)

    monkeypatch.setattr(module.os, "fsync", spy_fsync)
    result = module.main(
        [
            "alta",
            "--code",
            "IM-2",
            "--role",
            "builder",
            "--slot",
            "slot-2",
            "--thread-id",
            "thread-2",
            "--started",
            "now",
            "--status",
            "ACTIVE",
            "--by",
            "fsync-test",
            "--reason",
            "fsync-test",
            "--registry",
            str(registry),
            "--ledger",
            str(ledger),
            "--roster",
            str(roster),
            "--apply",
        ]
    )
    assert result == 0
    assert captured == [before]
    assert registry.read_bytes() != before


def test_write_registry_fsync_failure_cleans_tmp(tmp_path, monkeypatch):
    registry = tmp_path / "registry.json"
    ledger = tmp_path / "ledger.jsonl"
    roster = tmp_path / "roster.json"
    write_registry(registry, [session()])
    write_roster(roster)
    before = registry.read_bytes()
    spec = importlib.util.spec_from_file_location("registry_ops_fsync_failure", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def failing_fsync(fd):
        raise OSError("fsync simulado: fallo tras escribir el tmp")

    monkeypatch.setattr(module.os, "fsync", failing_fsync)
    result = module.main(
        [
            "asiento",
            "--code",
            "IM-1",
            "--status",
            "SETTLED",
            "--by",
            "fsync-failure-test",
            "--reason",
            "fsync-failure-test",
            "--registry",
            str(registry),
            "--ledger",
            str(ledger),
            "--roster",
            str(roster),
            "--apply",
        ]
    )
    assert result == 2
    assert registry.read_bytes() == before
    assert not registry.with_name("registry.json.tmp").exists()


def test_os_fsync_is_restored_after_fsync_tests():
    assert os.fsync is _REAL_OS_FSYNC


def test_write_ahead_registry_failure_leaves_audit_row(tmp_path):
    registry = tmp_path / "registry.json"
    ledger = tmp_path / "ledger.jsonl"
    write_registry(registry, [session()])
    before = registry.read_bytes()
    roster = tmp_path / "roster.json"
    write_roster(roster)
    driver = write_driver(tmp_path, "registry_fail")
    result = subprocess.run(
        [
            sys.executable,
            str(driver),
            "nota",
            "--code",
            "IM-1",
            "--nota",
            "fail",
            "--by",
            "write-ahead",
            "--reason",
            "registry-error",
            "--registry",
            str(registry),
            "--ledger",
            str(ledger),
            "--roster",
            str(roster),
            "--apply",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    row = json.loads(ledger.read_text(encoding="utf-8").splitlines()[-1])
    assert row["change"] == "nota"
    assert row["by"] == "write-ahead"
    assert row["reason"] == "registry-error"
    assert row["detail"] == "code=IM-1 campo=nota modo=replace"
    assert registry.with_name("registry.json.bak1").read_bytes() == before


def test_rotate_failure_leaves_write_ahead_row_and_old_registry(tmp_path):
    registry = tmp_path / "registry.json"
    ledger = tmp_path / "ledger.jsonl"
    roster = tmp_path / "roster.json"
    write_registry(registry, [session()])
    write_roster(roster)
    roster_before = roster.read_bytes()
    ledger.write_bytes(b"")
    backup = registry.with_name("registry.json.bak1")
    backup.write_bytes(b"previous-backup")
    before = registry.read_bytes()
    driver = write_driver(tmp_path, "rotate_fail")
    result = subprocess.run(
        [
            sys.executable,
            str(driver),
            "asiento",
            "--code",
            "IM-1",
            "--status",
            "SETTLED",
            "--by",
            "rotate-test",
            "--reason",
            "rotate-error",
            "--registry",
            str(registry),
            "--ledger",
            str(ledger),
            "--roster",
            str(roster),
            "--apply",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "rotate failure" in result.stderr
    assert registry.read_bytes() == before
    assert roster.read_bytes() == roster_before
    assert backup.read_bytes() == b"previous-backup"
    assert sorted(p.name for p in tmp_path.glob("registry.json.bak*")) == [
        "registry.json.bak1"
    ]
    rows = [
        json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 1
    row = rows[0]
    assert set(row) == {"ts", "by", "change", "detail", "reason"}
    assert row["reason"] == "rotate-error"
    assert row["detail"] == "code=IM-1 campos=['status']"
    datetime.fromisoformat(row["ts"])
    assert row["change"] == "asiento"
    assert row["by"] == "rotate-test"


def test_lock_open_failure_leaves_inputs_untouched(tmp_path):
    registry = tmp_path / "registry.json"
    ledger = tmp_path / "ledger.jsonl"
    roster = tmp_path / "roster.json"
    write_registry(registry, [session()])
    write_roster(roster)
    ledger.write_bytes(b"ledger-before\n")
    paths = (registry, ledger, roster)
    before = {path: path.read_bytes() for path in paths}
    driver = write_driver(tmp_path, "lock_open_fail")
    result = subprocess.run(
        [
            sys.executable,
            str(driver),
            "asiento",
            "--code",
            "IM-1",
            "--status",
            "SETTLED",
            "--by",
            "lock-test",
            "--reason",
            "lock-open-error",
            "--registry",
            str(registry),
            "--ledger",
            str(ledger),
            "--roster",
            str(roster),
            "--apply",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 5
    assert "bloqueo no disponible" in result.stderr
    assert {path: path.read_bytes() for path in paths} == before
    assert list(tmp_path.glob("registry.json.bak*")) == []


def test_lock_release_failure_reports_error_after_successful_mutation(tmp_path):
    registry = tmp_path / "registry.json"
    ledger = tmp_path / "ledger.jsonl"
    roster = tmp_path / "roster.json"
    write_registry(registry, [session()])
    write_roster(roster)
    roster_before = roster.read_bytes()
    ledger.write_bytes(b"")
    before = registry.read_bytes()
    backup = registry.with_name("registry.json.bak1")
    driver = write_driver(tmp_path, "lock_release_fail")
    result = subprocess.run(
        [
            sys.executable,
            str(driver),
            "asiento",
            "--code",
            "IM-1",
            "--status",
            "SETTLED",
            "--by",
            "lock-test",
            "--reason",
            "lock-release-error",
            "--registry",
            str(registry),
            "--ledger",
            str(ledger),
            "--roster",
            str(roster),
            "--apply",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 6
    assert "simulado: fallo al liberar el lock" in result.stderr
    assert "SE APLICO" in result.stderr
    assert "fallo la liberacion del lock" in result.stderr
    assert registry.read_bytes() != before
    assert roster.read_bytes() == roster_before
    expected = json.loads(before)
    expected["sessions"][0]["status"] = "SETTLED"
    final = json.loads(registry.read_text(encoding="utf-8"))
    actualizado = final.pop("actualizado")
    datetime.fromisoformat(actualizado)
    assert final == expected
    assert backup.read_bytes() == before
    assert sorted(p.name for p in tmp_path.glob("registry.json.bak*")) == [
        "registry.json.bak1"
    ]
    rows = [
        json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 1
    row = rows[0]
    assert set(row) == {"ts", "by", "change", "detail", "reason"}
    assert row["reason"] == "lock-release-error"
    assert row["detail"] == "code=IM-1 campos=['status']"
    datetime.fromisoformat(row["ts"])
    assert row["change"] == "asiento"
    assert row["by"] == "lock-test"


def test_release_failure_before_mutation_keeps_current_rc(tmp_path):
    registry = tmp_path / "registry.json"
    ledger = tmp_path / "ledger.jsonl"
    roster = tmp_path / "roster.json"
    write_registry(registry, [session()])
    write_roster(roster)
    roster_before = roster.read_bytes()
    ledger.write_bytes(b"")
    before = registry.read_bytes()
    driver = write_driver(tmp_path, "write_and_lock_release_fail")
    result = subprocess.run(
        [
            sys.executable,
            str(driver),
            "asiento",
            "--code",
            "IM-1",
            "--status",
            "SETTLED",
            "--by",
            "lock-test",
            "--reason",
            "write-then-release-fail",
            "--registry",
            str(registry),
            "--ledger",
            str(ledger),
            "--roster",
            str(roster),
            "--apply",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "simulado: fallo de escritura del registry" in result.stderr
    assert "simulado: fallo al liberar el lock" not in result.stderr
    assert "SE APLICO" not in result.stderr
    assert registry.read_bytes() == before
    assert roster.read_bytes() == roster_before


@pytest.mark.parametrize(
    "command_args",
    [
        [
            "alta",
            "--code",
            "IM-2",
            "--role",
            "builder",
            "--slot",
            "slot-2",
            "--thread-id",
            "thread-2",
            "--started",
            "now",
            "--status",
            "ACTIVE",
        ],
        ["asiento", "--code", "IM-1", "--status", "SETTLED"],
        ["nota", "--code", "IM-1", "--nota", "blocked"],
        ["reconcile", "--snapshot", "snapshot.json"],
    ],
)
def test_apply_gate_blocks_all_subcommands(tmp_path, command_args):
    registry = tmp_path / "registry.json"
    write_registry(registry, [session()])
    roster = tmp_path / "roster.json"
    write_roster(roster, "PENDIENTE_ACK")
    if "snapshot.json" in command_args:
        snapshot = tmp_path / "snapshot.json"
        snapshot.write_text("[]", encoding="utf-8")
        command_args = [
            str(snapshot) if value == "snapshot.json" else value
            for value in command_args
        ]
    result = run_cli(
        registry,
        *command_args,
        "--by",
        "b",
        "--reason",
        "r",
        "--apply",
        roster=roster,
    )
    assert result.returncode == 3
    assert "PENDIENTE_ACK" in result.stderr


def test_gate_blocks_saliente_muerto_and_roster_invalid(tmp_path):
    registry = tmp_path / "registry.json"
    write_registry(registry, [session()])
    roster = tmp_path / "roster.json"
    write_roster(roster, "SALIENTE_MUERTO")
    result = run_cli(
        registry,
        "asiento",
        "--code",
        "IM-1",
        "--status",
        "SETTLED",
        "--by",
        "b",
        "--reason",
        "r",
        "--apply",
        roster=roster,
    )
    assert result.returncode == 3
    roster.write_text("{truncated", encoding="utf-8")
    result = run_cli(
        registry,
        "asiento",
        "--code",
        "IM-1",
        "--status",
        "SETTLED",
        "--by",
        "b",
        "--reason",
        "r",
        "--apply",
        roster=roster,
    )
    assert result.returncode == 2
    assert "roster ilegible" in result.stderr


def test_roster_missing_estado_uses_activo_fallback(tmp_path):
    registry = tmp_path / "registry.json"
    write_registry(registry, [session()])
    roster = tmp_path / "roster.json"
    write_roster(roster, entry={"status": "PENDIENTE_ACK"})
    result = run_cli(
        registry,
        "asiento",
        "--code",
        "IM-1",
        "--status",
        "SETTLED",
        "--by",
        "b",
        "--reason",
        "r",
        "--apply",
        roster=roster,
    )
    assert result.returncode == 0


@pytest.mark.parametrize(
    "entry, expected",
    [
        ({"estado": "ACTIVO", "status": "PENDIENTE_ACK"}, 0),
        ({"estado": "PENDIENTE_ACK", "status": "ACTIVO"}, 3),
    ],
)
def test_gate_reads_estado_not_legacy_status(tmp_path, entry, expected):
    registry = tmp_path / "registry.json"
    write_registry(registry, [session()])
    roster = tmp_path / "roster.json"
    write_roster(roster, entry=entry)
    result = run_cli(
        registry,
        "asiento",
        "--code",
        "IM-1",
        "--status",
        "SETTLED",
        "--by",
        "b",
        "--reason",
        "r",
        "--apply",
        roster=roster,
    )
    assert result.returncode == expected


def test_gate_failure_leaves_registry_backups_and_ledger_untouched(tmp_path):
    registry = tmp_path / "registry.json"
    write_registry(registry, [session()])
    bak1 = registry.with_name("registry.json.bak1")
    bak1.write_bytes(b"old backup")
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_bytes(b"old ledger\n")
    before_registry = registry.read_bytes()
    before_bak = bak1.read_bytes()
    before_ledger = ledger.read_bytes()
    roster = tmp_path / "roster.json"
    write_roster(roster, "PENDIENTE_ACK")
    result = run_cli(
        registry,
        "nota",
        "--code",
        "IM-1",
        "--nota",
        "blocked",
        "--by",
        "b",
        "--reason",
        "r",
        "--apply",
        ledger=ledger,
        roster=roster,
    )
    assert result.returncode == 3
    assert registry.read_bytes() == before_registry
    assert bak1.read_bytes() == before_bak
    assert ledger.read_bytes() == before_ledger


def test_apply_requires_roster(tmp_path):
    registry = tmp_path / "registry.json"
    write_registry(registry, [session()])
    result = run_cli(
        registry,
        "nota",
        "--code",
        "IM-1",
        "--nota",
        "x",
        "--by",
        "b",
        "--reason",
        "r",
        "--apply",
        auto_roster=False,
    )
    assert result.returncode == 2
    assert result.stderr.strip() == "registry_ops: --apply requiere --roster"


def test_ledger_directory_fails_before_registry_or_backup(tmp_path):
    registry = tmp_path / "registry.json"
    write_registry(registry, [session()])
    before = registry.read_bytes()
    ledger_dir = tmp_path / "ledger-dir"
    ledger_dir.mkdir()
    result = run_cli(
        registry,
        "asiento",
        "--code",
        "IM-1",
        "--status",
        "SETTLED",
        "--by",
        "b",
        "--reason",
        "r",
        "--apply",
        ledger=ledger_dir,
    )
    assert result.returncode == 2
    assert registry.read_bytes() == before
    assert not registry.with_name("registry.json.bak1").exists()


def test_reconcile_empty_snapshot_has_no_changes(tmp_path):
    registry = tmp_path / "registry.json"
    write_registry(registry, [session()])
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text("[]", encoding="utf-8")
    result = run_cli(
        registry, "reconcile", "--snapshot", snapshot, "--by", "b", "--reason", "r"
    )
    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "actualizaciones": [],
        "snapshot_sin_match": [],
        "registry_sin_actualizar": ["IM-1"],
    }


@pytest.mark.parametrize(
    "snapshot_data",
    [
        [{"threadId": "thread-1"}],
        {"threadId": "thread-1"},
        {},
        [snapshot_entry(), snapshot_entry()],
        b"{truncated",
    ],
)
def test_reconcile_rejects_invalid_snapshot_forms(tmp_path, snapshot_data):
    registry = tmp_path / "registry.json"
    write_registry(registry, [session()])
    snapshot = tmp_path / "snapshot.json"
    if isinstance(snapshot_data, bytes):
        snapshot.write_bytes(snapshot_data)
    else:
        snapshot.write_text(json.dumps(snapshot_data), encoding="utf-8")
    result = run_cli(
        registry, "reconcile", "--snapshot", snapshot, "--by", "b", "--reason", "r"
    )
    assert result.returncode == 2


@pytest.mark.parametrize(
    "missing_field", ("threadId", "settled", "status", "updatedAt", "modelo", "cuenta")
)
def test_reconcile_rejects_each_missing_required_snapshot_field(
    tmp_path, missing_field
):
    registry = tmp_path / "registry.json"
    write_registry(registry, [session()])
    snapshot = tmp_path / "snapshot.json"
    entry = snapshot_entry()
    del entry[missing_field]
    snapshot.write_text(json.dumps([entry]), encoding="utf-8")
    result = run_cli(
        registry, "reconcile", "--snapshot", snapshot, "--by", "b", "--reason", "r"
    )
    assert result.returncode == 2


def test_reconcile_lists_unmatched_entries_without_creating_sessions(tmp_path):
    registry = tmp_path / "registry.json"
    write_registry(registry, [session()])
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps([snapshot_entry("unknown")]), encoding="utf-8")
    result = run_cli(
        registry, "reconcile", "--snapshot", snapshot, "--by", "b", "--reason", "r"
    )
    assert result.returncode == 0
    plan = json.loads(result.stdout)
    assert plan["snapshot_sin_match"] == ["unknown"]
    assert plan["registry_sin_actualizar"] == ["IM-1"]
    assert json.loads(registry.read_text(encoding="utf-8"))["sessions"] == [session()]


def test_reconcile_apply_updates_only_five_fields_and_preserves_unknowns(tmp_path):
    registry = tmp_path / "registry.json"
    item = session()
    item.update(
        {
            "slot": "slot-real",
            "nota": "nota-real",
            "started_nota": "started-nota-real",
            "supersedes": "IM-0",
            "reporta_a": "OR-1",
            "brief": "brief-real",
            "generation": 7,
            "launched_by": "launcher-real",
            "worktree": "worktree-real",
            "campo_no_documentado": "keep",
        }
    )
    original_keys = set(item)
    registry.write_text(
        json.dumps(
            {
                "cadena_consulta": "cadena-real",
                "protocolo": "protocolo-real",
                "autoridad": "autoridad-real",
                "sessions": [item],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps([snapshot_entry(extra="ignored")]), encoding="utf-8")
    result = run_cli(
        registry,
        "reconcile",
        "--snapshot",
        snapshot,
        "--by",
        "b",
        "--reason",
        "r",
        "--apply",
    )
    assert result.returncode == 0
    updated_data = json.loads(registry.read_text(encoding="utf-8"))
    updated = updated_data["sessions"][0]
    assert {field: updated[field] for field in RECONCILE_FIELDS} == {
        "settled": True,
        "status": "SETTLED",
        "updatedAt": "2026-11-08T11:00:00+01:00",
        "modelo": "codex",
        "cuenta": "plana",
    }
    assert updated["campo_no_documentado"] == "keep"
    assert {
        field: updated[field]
        for field in (
            "slot",
            "nota",
            "started_nota",
            "supersedes",
            "reporta_a",
            "brief",
            "generation",
            "launched_by",
            "worktree",
        )
    } == {
        "slot": "slot-real",
        "nota": "nota-real",
        "started_nota": "started-nota-real",
        "supersedes": "IM-0",
        "reporta_a": "OR-1",
        "brief": "brief-real",
        "generation": 7,
        "launched_by": "launcher-real",
        "worktree": "worktree-real",
    }
    assert updated_data["cadena_consulta"] == "cadena-real"
    assert updated_data["protocolo"] == "protocolo-real"
    assert updated_data["autoridad"] == "autoridad-real"
    assert "extra" not in updated
    assert set(updated) == original_keys | set(RECONCILE_FIELDS)


def test_g4_roster_private_string_is_ignored_on_apply(tmp_path):
    registry = tmp_path / "registry.json"
    write_registry(registry, [session()])
    roster = tmp_path / "roster.json"
    roster.write_text(
        json.dumps(
            {
                "active_roles": {
                    "_schema_note": "texto",
                    "orquestador": {"estado": "ACTIVO"},
                }
            }
        ),
        encoding="utf-8",
    )
    result = run_cli(
        registry,
        "asiento",
        "--code",
        "IM-1",
        "--status",
        "SETTLED",
        "--by",
        "g4",
        "--reason",
        "private-active",
        "--apply",
        roster=roster,
    )
    assert result.returncode == 0


def test_g4_roster_private_string_does_not_bypass_gate(tmp_path):
    registry = tmp_path / "registry.json"
    write_registry(registry, [session()])
    roster = tmp_path / "roster.json"
    roster.write_text(
        json.dumps(
            {
                "active_roles": {
                    "_algo": "texto",
                    "orquestador": {"estado": "PENDIENTE_ACK"},
                }
            }
        ),
        encoding="utf-8",
    )
    result = run_cli(
        registry,
        "asiento",
        "--code",
        "IM-1",
        "--status",
        "SETTLED",
        "--by",
        "g4",
        "--reason",
        "private-pending",
        "--apply",
        roster=roster,
    )
    assert result.returncode == 3


def test_l3_ledger_alta_contains_exact_audit_fields(tmp_path):
    registry = tmp_path / "registry.json"
    ledger = tmp_path / "ledger.jsonl"
    write_registry(registry)
    result = run_cli(
        registry,
        "alta",
        "--code",
        "IM-2",
        "--role",
        "builder",
        "--slot",
        "slot-2",
        "--thread-id",
        "thread-2",
        "--started",
        "now",
        "--status",
        "ACTIVE",
        "--by",
        "ledger-alta",
        "--reason",
        "audit-alta",
        "--apply",
        ledger=ledger,
    )
    assert result.returncode == 0
    row = json.loads(ledger.read_text(encoding="utf-8").splitlines()[-1])
    assert set(row) == {"ts", "by", "change", "detail", "reason"}
    assert row["change"] == "alta"
    assert row["by"] == "ledger-alta"
    assert row["reason"] == "audit-alta"
    assert row["detail"] == "code=IM-2"


def test_l3_ledger_asiento_contains_exact_audit_fields(tmp_path):
    registry = tmp_path / "registry.json"
    ledger = tmp_path / "ledger.jsonl"
    write_registry(registry, [session()])
    result = run_cli(
        registry,
        "asiento",
        "--code",
        "IM-1",
        "--status",
        "SETTLED",
        "--by",
        "ledger-asiento",
        "--reason",
        "audit-asiento",
        "--apply",
        ledger=ledger,
    )
    assert result.returncode == 0
    row = json.loads(ledger.read_text(encoding="utf-8").splitlines()[-1])
    assert set(row) == {"ts", "by", "change", "detail", "reason"}
    assert row["change"] == "asiento"
    assert row["by"] == "ledger-asiento"
    assert row["reason"] == "audit-asiento"
    assert row["detail"] == "code=IM-1 campos=['status']"


def test_l3_ledger_nota_contains_exact_audit_fields(tmp_path):
    registry = tmp_path / "registry.json"
    ledger = tmp_path / "ledger.jsonl"
    write_registry(registry, [session()])
    result = run_cli(
        registry,
        "nota",
        "--code",
        "IM-1",
        "--nota",
        "note",
        "--by",
        "ledger-nota",
        "--reason",
        "audit-nota",
        "--apply",
        ledger=ledger,
    )
    assert result.returncode == 0
    row = json.loads(ledger.read_text(encoding="utf-8").splitlines()[-1])
    assert set(row) == {"ts", "by", "change", "detail", "reason"}
    assert row["change"] == "nota"
    assert row["by"] == "ledger-nota"
    assert row["reason"] == "audit-nota"
    assert row["detail"] == "code=IM-1 campo=nota modo=replace"


def test_l3_ledger_reconcile_contains_exact_audit_fields(tmp_path):
    registry = tmp_path / "registry.json"
    ledger = tmp_path / "ledger.jsonl"
    snapshot = tmp_path / "snapshot.json"
    write_registry(registry, [session()])
    snapshot.write_text(json.dumps([snapshot_entry()]), encoding="utf-8")
    result = run_cli(
        registry,
        "reconcile",
        "--snapshot",
        snapshot,
        "--by",
        "ledger-reconcile",
        "--reason",
        "audit-reconcile",
        "--apply",
        ledger=ledger,
    )
    assert result.returncode == 0
    row = json.loads(ledger.read_text(encoding="utf-8").splitlines()[-1])
    assert set(row) == {"ts", "by", "change", "detail", "reason"}
    assert row["change"] == "reconcile"
    assert row["by"] == "ledger-reconcile"
    assert row["reason"] == "audit-reconcile"
    assert row["detail"] == (
        f"actualizadas=1 snapshot={snapshot} sin_match=0 sin_actualizar=0"
    )


def test_r1_r2_d1_d6_reconcile_preserves_unmatched_sessions_and_detail(tmp_path):
    registry = tmp_path / "registry.json"
    ledger = tmp_path / "ledger.jsonl"
    snapshot = tmp_path / "snapshot.json"
    first = session("IM-1")
    second = session("IM-2")
    second["threadId"] = "thread-2"
    second["campo_no_documentado"] = "unchanged"
    write_registry(registry, [first, second])
    before_second = dict(second)
    snapshot.write_text(
        json.dumps([snapshot_entry("thread-1"), snapshot_entry("thread-huerfano")]),
        encoding="utf-8",
    )
    result = run_cli(
        registry,
        "reconcile",
        "--snapshot",
        snapshot,
        "--by",
        "r1r2",
        "--reason",
        "d1d6",
        "--apply",
        ledger=ledger,
    )
    assert result.returncode == 0
    updated = json.loads(registry.read_text(encoding="utf-8"))
    assert len(updated["sessions"]) == 2
    assert all(
        item.get("threadId") != "thread-huerfano" for item in updated["sessions"]
    )
    assert (
        next(item for item in updated["sessions"] if item["code"] == "IM-2")
        == before_second
    )
    row = json.loads(ledger.read_text(encoding="utf-8").splitlines()[-1])
    assert (
        row["detail"]
        == f"actualizadas=1 snapshot={snapshot} sin_match=1 sin_actualizar=1"
    )


def test_e2_default_ledger_is_next_to_registry(tmp_path):
    registry = tmp_path / "registry.json"
    write_registry(registry, [session()])
    cwd_ledger = ROOT / "registry_changes.jsonl"
    before_cwd_ledger = cwd_ledger.read_bytes() if cwd_ledger.exists() else None
    result = run_cli(
        registry,
        "nota",
        "--code",
        "IM-1",
        "--nota",
        "default-ledger",
        "--by",
        "e2",
        "--reason",
        "default",
        "--apply",
    )
    assert result.returncode == 0
    ledger = registry.parent / "registry_changes.jsonl"
    assert ledger.exists()
    assert (
        json.loads(ledger.read_text(encoding="utf-8").splitlines()[-1])["change"]
        == "nota"
    )
    if cwd_ledger != ledger:
        assert (
            cwd_ledger.read_bytes() if cwd_ledger.exists() else None
        ) == before_cwd_ledger


def test_a1_apply_updates_actualizado(tmp_path):
    registry = tmp_path / "registry.json"
    before_dt = datetime.now(timezone.utc) - timedelta(minutes=1)
    registry.write_text(
        json.dumps({"actualizado": before_dt.isoformat(), "sessions": [session()]})
        + "\n",
        encoding="utf-8",
    )
    result = run_cli(
        registry,
        "asiento",
        "--code",
        "IM-1",
        "--status",
        "SETTLED",
        "--by",
        "a1",
        "--reason",
        "timestamp",
        "--apply",
    )
    assert result.returncode == 0
    after = json.loads(registry.read_text(encoding="utf-8"))["actualizado"]
    after_dt = datetime.fromisoformat(after)
    assert after_dt > before_dt


def test_d4_reconcile_dry_run_lists_only_changed_overlay_fields(tmp_path):
    registry = tmp_path / "registry.json"
    item = session()
    item.update(
        {
            "settled": True,
            "modelo": "codex",
            "cuenta": "plana",
            "status": "ACTIVE",
            "updatedAt": "old",
        }
    )
    write_registry(registry, [item])
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps([snapshot_entry()]), encoding="utf-8")
    result = run_cli(
        registry,
        "reconcile",
        "--snapshot",
        snapshot,
        "--by",
        "d4",
        "--reason",
        "partial",
    )
    assert result.returncode == 0
    plan = json.loads(result.stdout)
    assert set(plan["actualizaciones"][0]["cambios"]) == {"status", "updatedAt"}


def test_4a_missing_snapshot_file_returns_schema_error(tmp_path):
    registry = tmp_path / "registry.json"
    write_registry(registry, [session()])
    result = run_cli(
        registry,
        "reconcile",
        "--snapshot",
        tmp_path / "does-not-exist.json",
        "--by",
        "4a",
        "--reason",
        "missing",
    )
    assert result.returncode == 2


def test_4b_missing_registry_file_apply_returns_schema_error(tmp_path):
    registry = tmp_path / "does-not-exist.json"
    roster = tmp_path / "roster.json"
    write_roster(roster)
    result = run_cli(
        registry,
        "nota",
        "--code",
        "IM-1",
        "--nota",
        "x",
        "--by",
        "4b",
        "--reason",
        "missing",
        "--apply",
        roster=roster,
    )
    assert result.returncode == 2
    ledger = registry.parent / "registry_changes.jsonl"
    assert ledger.exists()
    assert ledger.read_bytes() == b""


def test_4c_non_private_non_dict_role_returns_schema_error(tmp_path):
    registry = tmp_path / "registry.json"
    write_registry(registry, [session()])
    roster = tmp_path / "roster.json"
    roster.write_text(
        json.dumps({"active_roles": {"orquestador": ["not-a-dict"]}}),
        encoding="utf-8",
    )
    result = run_cli(
        registry,
        "asiento",
        "--code",
        "IM-1",
        "--status",
        "SETTLED",
        "--by",
        "4c",
        "--reason",
        "invalid-role",
        "--apply",
        roster=roster,
    )
    assert result.returncode == 2


def test_4d_invalid_snapshot_precedes_blocked_roster(tmp_path):
    registry = tmp_path / "registry.json"
    write_registry(registry, [session()])
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text("{invalid", encoding="utf-8")
    roster = tmp_path / "roster.json"
    write_roster(roster, "PENDIENTE_ACK")
    result = run_cli(
        registry,
        "reconcile",
        "--snapshot",
        snapshot,
        "--by",
        "4d",
        "--reason",
        "precedence",
        "--apply",
        roster=roster,
    )
    assert result.returncode == 2


def test_4e_asiento_missing_code_and_fields_returns_rc2(tmp_path):
    registry = tmp_path / "registry.json"
    write_registry(registry, [session()])
    result = run_cli(
        registry,
        "asiento",
        "--code",
        "MISSING",
        "--by",
        "4e",
        "--reason",
        "precedence",
    )
    assert result.returncode == 2
    assert "asiento sin campos a cambiar" in result.stderr


def test_4f_reconcile_rejects_duplicate_registry_thread_ids(tmp_path):
    registry = tmp_path / "registry.json"
    first = session("IM-1")
    second = session("IM-2")
    second["brief"] = "second"
    write_registry(registry, [first, second])
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps([snapshot_entry()]), encoding="utf-8")
    for extra in ([], ["--apply"]):
        result = run_cli(
            registry,
            "reconcile",
            "--snapshot",
            snapshot,
            "--by",
            "4f",
            "--reason",
            "duplicate",
            *extra,
        )
        assert result.returncode == 2
        assert "threadId duplicado=thread-1" in result.stderr


def test_4h_actualizado_is_strictly_later_iso8601(tmp_path):
    registry = tmp_path / "registry.json"
    before_dt = datetime.now(timezone.utc) - timedelta(minutes=1)
    registry.write_text(
        json.dumps({"actualizado": before_dt.isoformat(), "sessions": [session()]})
        + "\n",
        encoding="utf-8",
    )
    result = run_cli(
        registry,
        "asiento",
        "--code",
        "IM-1",
        "--status",
        "SETTLED",
        "--by",
        "4h",
        "--reason",
        "timestamp",
        "--apply",
    )
    assert result.returncode == 0
    after_value = json.loads(registry.read_text(encoding="utf-8"))["actualizado"]
    after_dt = datetime.fromisoformat(after_value)
    assert datetime.fromisoformat(before_dt.isoformat()) < after_dt


def test_reconcile_rejects_duplicate_codes_dry_run_and_apply(tmp_path):
    registry = tmp_path / "registry.json"
    first = session("IM-1")
    first["threadId"] = "t1"
    second = session("IM-1")
    second["threadId"] = "t2"
    write_registry(registry, [first, second])
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(
        json.dumps([snapshot_entry("t1"), snapshot_entry("t2")]), encoding="utf-8"
    )
    before = registry.read_bytes()
    for extra in ([], ["--apply"]):
        result = run_cli(
            registry,
            "reconcile",
            "--snapshot",
            snapshot,
            "--by",
            "duplicate-code",
            "--reason",
            "closed",
            *extra,
        )
        assert result.returncode == 2
        assert "code duplicado=IM-1" in result.stderr
        assert registry.read_bytes() == before


@pytest.mark.parametrize("command", ["alta", "asiento", "nota", "reconcile"])
def test_all_subcommands_reject_duplicate_registry_codes(tmp_path, command):
    registry = tmp_path / "registry.json"
    first = session("IM-1")
    second = session("IM-1")
    second["threadId"] = "thread-2"
    write_registry(registry, [first, second])
    args = [command, "--by", "universal-code", "--reason", "duplicate"]
    if command == "alta":
        args += [
            "--code",
            "IM-2",
            "--role",
            "builder",
            "--slot",
            "slot-2",
            "--thread-id",
            "thread-3",
            "--started",
            "now",
            "--status",
            "ACTIVE",
        ]
    elif command == "asiento":
        args += ["--code", "IM-1", "--status", "SETTLED"]
    elif command == "nota":
        args += ["--code", "IM-1", "--nota", "note"]
    else:
        snapshot = tmp_path / "snapshot.json"
        snapshot.write_text("[]", encoding="utf-8")
        args += ["--snapshot", str(snapshot)]
    result = run_cli(registry, *args)
    assert result.returncode == 2
    assert "code duplicado=IM-1" in result.stderr


@pytest.mark.parametrize("thread_id", [None, ""])
def test_reconcile_rejects_null_or_empty_snapshot_thread_id(tmp_path, thread_id):
    registry = tmp_path / "registry.json"
    write_registry(registry, [session()])
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps([snapshot_entry(thread_id)]), encoding="utf-8")
    result = run_cli(
        registry, "reconcile", "--snapshot", snapshot, "--by", "b", "--reason", "r"
    )
    assert result.returncode == 2
    assert "threadId nulo o vacio" in result.stderr


@pytest.mark.parametrize("command", ["alta", "asiento", "nota", "reconcile"])
def test_4i_missing_registry_dry_run_returns_schema_error(tmp_path, command):
    registry = tmp_path / "missing-registry.json"
    args = [command, "--by", "4i", "--reason", "missing"]
    if command == "alta":
        args += [
            "--code",
            "IM-1",
            "--role",
            "builder",
            "--slot",
            "s",
            "--thread-id",
            "t",
            "--started",
            "now",
            "--status",
            "ACTIVE",
        ]
    elif command == "asiento":
        args += ["--code", "IM-1", "--status", "SETTLED"]
    elif command == "nota":
        args += ["--code", "IM-1", "--nota", "x"]
    else:
        snapshot = tmp_path / "snapshot.json"
        snapshot.write_text("[]", encoding="utf-8")
        args += ["--snapshot", str(snapshot)]
    result = run_cli(registry, *args)
    assert result.returncode == 2


def test_4ii_alta_duplicate_apply_returns_conflict_without_change(tmp_path):
    registry = tmp_path / "registry.json"
    write_registry(registry, [session()])
    before = registry.read_bytes()
    result = run_cli(
        registry,
        "alta",
        "--code",
        "IM-1",
        "--role",
        "builder",
        "--slot",
        "s",
        "--thread-id",
        "t",
        "--started",
        "now",
        "--status",
        "ACTIVE",
        "--by",
        "4ii",
        "--reason",
        "duplicate",
        "--apply",
    )
    assert result.returncode == 4
    assert registry.read_bytes() == before
    assert len(json.loads(registry.read_text(encoding="utf-8"))["sessions"]) == 1


def test_4iii_reconcile_default_ledger_is_next_to_registry(tmp_path):
    registry = tmp_path / "registry.json"
    snapshot = tmp_path / "snapshot.json"
    write_registry(registry, [session()])
    snapshot.write_text(json.dumps([snapshot_entry()]), encoding="utf-8")
    result = run_cli(
        registry,
        "reconcile",
        "--snapshot",
        snapshot,
        "--by",
        "4iii",
        "--reason",
        "default",
        "--apply",
    )
    assert result.returncode == 0
    ledger = registry.parent / "registry_changes.jsonl"
    row = json.loads(ledger.read_text(encoding="utf-8").splitlines()[-1])
    assert row["change"] == "reconcile"
    assert row["by"] == "4iii"
    assert row["reason"] == "default"


def test_real_rotator_roster_shape_blocks_pending_ack(tmp_path):
    registry = tmp_path / "registry.json"
    write_registry(registry, [session()])
    roster = tmp_path / "roster.json"
    roster.write_text(
        json.dumps(
            {
                "active_roles": {
                    "orquestador": {
                        "threadId": "thread-orquestador",
                        "session_code": "OR-1",
                        "since": "2026-11-08T10:00:00+01:00",
                        "set_by": "SUPERVISOR-1",
                        "predecessor_threadId": None,
                        "version": 3,
                        "status": "active",
                        "approved_by": "SUPERVISOR-1",
                        "nota": "pending",
                        "estado": "PENDIENTE_ACK",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    result = run_cli(
        registry,
        "asiento",
        "--code",
        "IM-1",
        "--status",
        "SETTLED",
        "--by",
        "rotator-shape",
        "--reason",
        "pending",
        "--apply",
        roster=roster,
    )
    assert result.returncode == 3
