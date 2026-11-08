import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "flight" / "registry_ops.py"


def run_cli(registry, *args, ledger=None):
    command = [sys.executable, str(SCRIPT), *args, "--registry", str(registry)]
    if ledger is not None:
        command += ["--ledger", str(ledger)]
    return subprocess.run(command, capture_output=True, text=True, check=False)


def write_registry(path, sessions=None):
    data = {"sessions": [] if sessions is None else sessions}
    path.write_text(json.dumps(data) + "\n", encoding="utf-8")


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
