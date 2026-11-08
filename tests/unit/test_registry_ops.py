import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "flight" / "registry_ops.py"

_REGISTRY_OPS_SPEC = importlib.util.spec_from_file_location("registry_ops", SCRIPT)
_REGISTRY_OPS_MODULE = importlib.util.module_from_spec(_REGISTRY_OPS_SPEC)
_REGISTRY_OPS_SPEC.loader.exec_module(_REGISTRY_OPS_MODULE)
RECONCILE_FIELDS = _REGISTRY_OPS_MODULE.RECONCILE_FIELDS


def run_cli(registry, *args, ledger=None, roster=None, auto_roster=True):
    if "--apply" in args and roster is None and auto_roster:
        roster = registry.parent / "roster.json"
        write_roster(roster)
    command = [sys.executable, str(SCRIPT), *args, "--registry", str(registry)]
    if ledger is not None:
        command += ["--ledger", str(ledger)]
    if roster is not None:
        command += ["--roster", str(roster)]
    return subprocess.run(command, capture_output=True, text=True, check=False)


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


def write_driver(tmp_path, mode):
    body = {
        "slow": """
original_apply = mod._apply_change
def slow_apply(*args, **kwargs):
    real_mutate = args[-1]
    def delayed(data):
        real_mutate(data)
        time.sleep(0.3)
    return original_apply(*args[:-1], delayed, **kwargs)
mod._apply_change = slow_apply
""",
        "ledger_fail": 'mod._append_ledger_handle = lambda *args, **kwargs: (_ for _ in ()).throw(OSError("ledger failure"))',
        "registry_fail": 'mod._write_registry = lambda *args, **kwargs: (_ for _ in ()).throw(OSError("registry failure"))',
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
        )
        normal_process = subprocess.Popen(
            [
                sys.executable,
                str(SCRIPT),
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
        )
        slow_result = slow_process.communicate()
        normal_result = normal_process.communicate()
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
