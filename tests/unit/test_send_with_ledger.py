#!/usr/bin/env python3
"""Tests for scripts/flight/send_with_ledger.py (WOT-2026-136h).

Tests the shared function, the helper CLI (check and record subcommands),
the attempt rule, degenerate cases, AST barriers, and the censo of mcp:.
"""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
_SEND_WITH_LEDGER = _SCRIPTS_DIR / "flight" / "send_with_ledger.py"

# The fixed schema keys (N3).
FIXED_KEYS = {
    "ts",
    "by",
    "a",
    "modo",
    "resultado",
    "error",
    "providerInstanceId",
    "mensaje_id",
    "nota",
}

# Valid modes (N4).
VALID_MODES = {"auto", "queue", "steer", "restart"}

# Valid resultado values (P-N3b).
VALID_RESULTADOS = {"enviado", "parent_not_active", "thread_not_found", "error"}


def _run_helper(args: list[str], tmp_path: Path) -> subprocess.CompletedProcess:
    """Run the helper CLI and return the result."""
    env = dict(__import__("os").environ)
    # Clean FLIGHT_ROSTER_PATH to avoid interfering.
    env.pop("FLIGHT_ROSTER_PATH", None)
    return subprocess.run(
        [sys.executable, str(_SEND_WITH_LEDGER), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        cwd=str(tmp_path),
    )


class TestSharedFunction:
    """Tests for the shared has_mcp_prefix function in thread_id.py."""

    def test_shared_function_returns_true_for_valid_prefix(self):
        """The shared function returns True for mcp: prefixed strings."""
        import importlib.util

        thread_id_path = _SCRIPTS_DIR / "flight" / "thread_id.py"
        spec = importlib.util.spec_from_file_location("thread_id_test", thread_id_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        assert module.has_mcp_prefix("mcp:orq-001") is True
        assert module.has_mcp_prefix("mcp:") is True

    def test_shared_function_returns_false_for_non_mcp_prefix(self):
        """The shared function returns False for non-mcp: strings."""
        import importlib.util

        thread_id_path = _SCRIPTS_DIR / "flight" / "thread_id.py"
        spec = importlib.util.spec_from_file_location("thread_id_test", thread_id_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        assert module.has_mcp_prefix("other-001") is False
        assert module.has_mcp_prefix("") is False
        assert module.has_mcp_prefix("mcp") is False
        assert module.has_mcp_prefix("MCP:foo") is False


class TestHelperCheckAuthorized:
    """Tests for check subcommand: authorized cases."""

    def test_check_no_ledger_authorizes(self, tmp_path):
        """check on nonexistent ledger -> rc 0 (advisory)."""
        proc = _run_helper(
            [
                "check",
                "--ledger",
                str(tmp_path / "nonexistent.jsonl"),
                "--by",
                "test",
                "--mensaje-id",
                "msg-1",
                "--a",
                "mcp:x",
                "--modo",
                "auto",
            ],
            tmp_path,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "autorizado" in proc.stdout

    def test_check_empty_ledger_authorizes(self, tmp_path):
        """check on empty ledger -> rc 0 (no prior attempts)."""
        ledger = tmp_path / "comms.jsonl"
        ledger.write_text("", encoding="utf-8")
        proc = _run_helper(
            [
                "check",
                "--ledger",
                str(ledger),
                "--by",
                "test",
                "--mensaje-id",
                "msg-1",
                "--a",
                "mcp:x",
                "--modo",
                "auto",
            ],
            tmp_path,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "sin intentos previos" in proc.stdout

    def test_check_first_attempt_authorizes(self, tmp_path):
        """check with one prior failed attempt -> rc 0 (allows retry)."""
        ledger = tmp_path / "comms.jsonl"
        ledger.write_text(
            json.dumps(
                {"mensaje_id": "msg-1", "resultado": "error"}, ensure_ascii=False
            )
            + "\n",
            encoding="utf-8",
        )
        proc = _run_helper(
            [
                "check",
                "--ledger",
                str(ledger),
                "--by",
                "test",
                "--mensaje-id",
                "msg-1",
                "--a",
                "mcp:x",
                "--modo",
                "auto",
            ],
            tmp_path,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "autorizado" in proc.stdout

    def test_check_enviado_not_terminal(self, tmp_path):
        """A prior enviado record is NOT terminal (ledger is a register, not FSM)."""
        ledger = tmp_path / "comms.jsonl"
        ledger.write_text(
            json.dumps(
                {"mensaje_id": "msg-1", "resultado": "enviado"}, ensure_ascii=False
            )
            + "\n",
            encoding="utf-8",
        )
        proc = _run_helper(
            [
                "check",
                "--ledger",
                str(ledger),
                "--by",
                "test",
                "--mensaje-id",
                "msg-1",
                "--a",
                "mcp:x",
                "--modo",
                "auto",
            ],
            tmp_path,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "ya se envio" in proc.stdout


class TestHelperCheckRefused:
    """Tests for check subcommand: refused cases."""

    def test_check_parent_not_active_refuses(self, tmp_path):
        """check after parent_not_active -> rc 1 (zero retries)."""
        ledger = tmp_path / "comms.jsonl"
        ledger.write_text(
            json.dumps(
                {"mensaje_id": "msg-1", "resultado": "parent_not_active"},
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        proc = _run_helper(
            [
                "check",
                "--ledger",
                str(ledger),
                "--by",
                "test",
                "--mensaje-id",
                "msg-1",
                "--a",
                "mcp:x",
                "--modo",
                "auto",
            ],
            tmp_path,
        )
        assert proc.returncode == 1, proc.stdout + proc.stderr
        assert "parent_not_active" in proc.stdout

    def test_check_two_failures_refuses(self, tmp_path):
        """check after two failed attempts -> rc 1 (tope de 2)."""
        ledger = tmp_path / "comms.jsonl"
        ledger.write_text(
            json.dumps(
                {"mensaje_id": "msg-1", "resultado": "error"}, ensure_ascii=False
            )
            + "\n",
            encoding="utf-8",
        )
        # Use append mode so both records are kept.
        with open(ledger, "a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {"mensaje_id": "msg-1", "resultado": "thread_not_found"},
                    ensure_ascii=False,
                )
                + "\n"
            )
        proc = _run_helper(
            [
                "check",
                "--ledger",
                str(ledger),
                "--by",
                "test",
                "--mensaje-id",
                "msg-1",
                "--a",
                "mcp:x",
                "--modo",
                "auto",
            ],
            tmp_path,
        )
        assert proc.returncode == 1, proc.stdout + proc.stderr
        assert "tope de 2 intentos" in proc.stdout

    def test_check_ignores_non_matching_mensaje_id(self, tmp_path):
        """Records with different mensaje_id are ignored."""
        ledger = tmp_path / "comms.jsonl"
        ledger.write_text(
            json.dumps(
                {"mensaje_id": "msg-2", "resultado": "parent_not_active"},
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        proc = _run_helper(
            [
                "check",
                "--ledger",
                str(ledger),
                "--by",
                "test",
                "--mensaje-id",
                "msg-1",
                "--a",
                "mcp:x",
                "--modo",
                "auto",
            ],
            tmp_path,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr

    def test_check_refused_bad_prefix(self, tmp_path):
        """check with destination without mcp: prefix -> rc 1."""
        ledger = tmp_path / "comms.jsonl"
        proc = _run_helper(
            [
                "check",
                "--ledger",
                str(ledger),
                "--by",
                "test",
                "--mensaje-id",
                "msg-1",
                "--a",
                "bad-prefix",
                "--modo",
                "auto",
            ],
            tmp_path,
        )
        assert proc.returncode == 1, proc.stdout + proc.stderr
        assert "prefijo mcp:" in proc.stdout

    def test_check_refused_bad_modo(self, tmp_path):
        """check with unknown mode -> rc 1."""
        ledger = tmp_path / "comms.jsonl"
        proc = _run_helper(
            [
                "check",
                "--ledger",
                str(ledger),
                "--by",
                "test",
                "--mensaje-id",
                "msg-1",
                "--a",
                "mcp:x",
                "--modo",
                "invalid_mode",
            ],
            tmp_path,
        )
        assert proc.returncode == 1, proc.stdout + proc.stderr
        assert "modo desconocido" in proc.stdout


class TestHelperRecord:
    """Tests for record subcommand."""

    def test_record_success(self, tmp_path):
        """record with valid args -> rc 0, line appended."""
        ledger = tmp_path / "comms.jsonl"
        proc = _run_helper(
            [
                "record",
                "--ledger",
                str(ledger),
                "--by",
                "test",
                "--mensaje-id",
                "msg-1",
                "--a",
                "mcp:orq-001",
                "--modo",
                "auto",
                "--resultado",
                "enviado",
            ],
            tmp_path,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        lines = ledger.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        obj = json.loads(lines[0])
        assert obj["by"] == "test"
        assert obj["mensaje_id"] == "msg-1"
        assert obj["a"] == "mcp:orq-001"
        assert obj["modo"] == "auto"
        assert obj["resultado"] == "enviado"
        assert "ts" in obj

    def test_record_refuses_no_prefix(self, tmp_path):
        """record with destination lacking mcp: prefix -> rc 1."""
        ledger = tmp_path / "comms.jsonl"
        proc = _run_helper(
            [
                "record",
                "--ledger",
                str(ledger),
                "--by",
                "test",
                "--mensaje-id",
                "msg-1",
                "--a",
                "other-001",
                "--modo",
                "auto",
                "--resultado",
                "enviado",
            ],
            tmp_path,
        )
        assert proc.returncode == 1, proc.stdout + proc.stderr
        assert "prefijo mcp:" in proc.stdout

    def test_record_refuses_invalid_mode(self, tmp_path):
        """record with unknown mode -> rc 1."""
        ledger = tmp_path / "comms.jsonl"
        proc = _run_helper(
            [
                "record",
                "--ledger",
                str(ledger),
                "--by",
                "test",
                "--mensaje-id",
                "msg-1",
                "--a",
                "mcp:orq-001",
                "--modo",
                "invalid_mode",
                "--resultado",
                "enviado",
            ],
            tmp_path,
        )
        assert proc.returncode == 1, proc.stdout + proc.stderr
        assert "modo desconocido" in proc.stdout

    def test_record_refuses_invalid_resultado(self, tmp_path):
        """record with unknown resultado -> rc 1."""
        ledger = tmp_path / "comms.jsonl"
        proc = _run_helper(
            [
                "record",
                "--ledger",
                str(ledger),
                "--by",
                "test",
                "--mensaje-id",
                "msg-1",
                "--a",
                "mcp:orq-001",
                "--modo",
                "auto",
                "--resultado",
                "unknown_result",
            ],
            tmp_path,
        )
        assert proc.returncode == 1, proc.stdout + proc.stderr
        assert "resultado desconocido" in proc.stdout

    def test_record_refuses_missing_by(self, tmp_path):
        """record without --by -> rc 1."""
        ledger = tmp_path / "comms.jsonl"
        proc = _run_helper(
            [
                "record",
                "--ledger",
                str(ledger),
                "--by",
                "",
                "--mensaje-id",
                "msg-1",
                "--a",
                "mcp:orq-001",
                "--modo",
                "auto",
                "--resultado",
                "enviado",
            ],
            tmp_path,
        )
        assert proc.returncode == 1, proc.stdout + proc.stderr
        assert "--by es obligatorio" in proc.stdout

    def test_record_refuses_missing_mensaje_id(self, tmp_path):
        """record without --mensaje-id -> rc 1."""
        ledger = tmp_path / "comms.jsonl"
        proc = _run_helper(
            [
                "record",
                "--ledger",
                str(ledger),
                "--by",
                "test",
                "--mensaje-id",
                "",
                "--a",
                "mcp:orq-001",
                "--modo",
                "auto",
                "--resultado",
                "enviado",
            ],
            tmp_path,
        )
        assert proc.returncode == 1, proc.stdout + proc.stderr
        assert "--mensaje_id es obligatorio" in proc.stdout

    def test_record_rc2_on_readonly_ledger(self, tmp_path):
        """record on a read-only ledger file -> rc 2 (environment error, no write)."""
        ledger = tmp_path / "readonly.jsonl"
        ledger.write_text("", encoding="utf-8")
        ledger.chmod(0o444)  # read-only
        proc = _run_helper(
            [
                "record",
                "--ledger",
                str(ledger),
                "--by",
                "test",
                "--mensaje-id",
                "msg-1",
                "--a",
                "mcp:orq-001",
                "--modo",
                "auto",
                "--resultado",
                "enviado",
            ],
            tmp_path,
        )
        assert proc.returncode == 2, proc.stdout + proc.stderr
        assert "no se puede anexar" in proc.stdout
        assert ledger.read_text(encoding="utf-8") == ""  # No write

    def test_record_rc2_on_directory_ledger(self, tmp_path):
        """record with ledger path pointing to a directory -> rc 2."""
        dir_path = tmp_path / "ledger_dir"
        dir_path.mkdir()
        proc = _run_helper(
            [
                "record",
                "--ledger",
                str(dir_path),
                "--by",
                "test",
                "--mensaje-id",
                "msg-1",
                "--a",
                "mcp:orq-001",
                "--modo",
                "auto",
                "--resultado",
                "enviado",
            ],
            tmp_path,
        )
        assert proc.returncode == 2, proc.stdout + proc.stderr


class TestHelperNoSend:
    """AST barrier: the helper must NOT import subprocess, socket, http, etc."""

    def test_helper_no_network_or_send_imports(self):
        """The helper source must not import subprocess, socket, urllib, http, requests."""
        src = _SEND_WITH_LEDGER.read_text(encoding="utf-8")
        tree = ast.parse(src)

        forbidden = {"subprocess", "socket", "urllib", "http", "requests"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    assert top not in forbidden, (
                        f"helper imports forbidden module: {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                top = node.module.split(".")[0]
                assert top not in forbidden, (
                    f"helper from-imports forbidden module: {node.module}"
                )


class TestHelperCallSharedFunction:
    """AST aserto: the helper IMPORTS AND CALLS the shared function."""

    def test_helper_calls_shared_function(self):
        """The helper accesses has_mcp_prefix from thread_id via _get_has_mcp_prefix()."""
        src = _SEND_WITH_LEDGER.read_text(encoding="utf-8")
        tree = ast.parse(src)

        found = False
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_get_has_mcp_prefix"
            ):
                found = True

        assert found, (
            "send_with_ledger.py must access has_mcp_prefix from the shared module"
        )


class TestHelperExitCodes:
    """Test exit codes: 0, 1, 2 only; never 3."""

    def test_check_valid_args_rc0(self, tmp_path):
        """check on valid args with no prior -> rc 0."""
        proc = _run_helper(
            [
                "check",
                "--ledger",
                str(tmp_path / "x.jsonl"),
                "--by",
                "test",
                "--mensaje-id",
                "msg-1",
                "--a",
                "mcp:x",
                "--modo",
                "auto",
            ],
            tmp_path,
        )
        assert proc.returncode == 0

    def test_check_refused_rc1(self, tmp_path):
        """check with parent_not_active -> rc 1, with reason text."""
        ledger = tmp_path / "comms.jsonl"
        ledger.write_text(
            json.dumps(
                {"mensaje_id": "msg-1", "resultado": "parent_not_active"},
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        proc = _run_helper(
            [
                "check",
                "--ledger",
                str(ledger),
                "--by",
                "test",
                "--mensaje-id",
                "msg-1",
                "--a",
                "mcp:x",
                "--modo",
                "auto",
            ],
            tmp_path,
        )
        assert proc.returncode == 1
        assert "parent_not_active" in proc.stdout
        assert "cero reintentos" in proc.stdout

    def test_record_valid_rc0(self, tmp_path):
        """record with valid args -> rc 0."""
        proc = _run_helper(
            [
                "record",
                "--ledger",
                str(tmp_path / "c.jsonl"),
                "--by",
                "test",
                "--mensaje-id",
                "m1",
                "--a",
                "mcp:x",
                "--modo",
                "auto",
                "--resultado",
                "enviado",
            ],
            tmp_path,
        )
        assert proc.returncode == 0

    def test_record_no_subcommand_rc2(self):
        """No subcommand -> rc 2 (usage)."""
        proc = _run_helper([], Path("."))
        assert proc.returncode == 2


class TestHelperDegenerateCases:
    """Six degenerate cases from P-datos."""

    def test_d1_nonexistent_ledger_authorizes(self, tmp_path):
        """Ledger inexistente: check AUTORIZA."""
        proc = _run_helper(
            [
                "check",
                "--ledger",
                str(tmp_path / "no.jsonl"),
                "--by",
                "test",
                "--mensaje-id",
                "m1",
                "--a",
                "mcp:x",
                "--modo",
                "auto",
            ],
            tmp_path,
        )
        assert proc.returncode == 0

    def test_d2_empty_ledger_authorizes(self, tmp_path):
        """Ledger vacio: check autoriza."""
        ledger = tmp_path / "empty.jsonl"
        ledger.write_text("", encoding="utf-8")
        proc = _run_helper(
            [
                "check",
                "--ledger",
                str(ledger),
                "--by",
                "test",
                "--mensaje-id",
                "m1",
                "--a",
                "mcp:x",
                "--modo",
                "auto",
            ],
            tmp_path,
        )
        assert proc.returncode == 0

    def test_d3_invalid_json_ignored(self, tmp_path):
        """Linea con JSON invalido: check la IGNORA al contar intentos."""
        ledger = tmp_path / "mixed.jsonl"
        ledger.write_text(
            "not valid json\n"
            + json.dumps({"mensaje_id": "m1", "resultado": "error"})
            + "\n",
            encoding="utf-8",
        )
        proc = _run_helper(
            [
                "check",
                "--ledger",
                str(ledger),
                "--by",
                "test",
                "--mensaje-id",
                "m1",
                "--a",
                "mcp:x",
                "--modo",
                "auto",
            ],
            tmp_path,
        )
        assert (
            proc.returncode == 0
        )  # The invalid line is ignored, one valid error record -> allows retry

    def test_d4_last_line_no_newline(self, tmp_path):
        """Ultima linea sin \n: check la lee bien; record la completa con salto."""
        ledger = tmp_path / "no_newline.jsonl"
        # Write ONE record WITHOUT trailing newline
        ledger.write_text(
            json.dumps({"mensaje_id": "m1", "resultado": "error"}, ensure_ascii=False),
            encoding="utf-8",
        )
        # No trailing newline
        proc = _run_helper(
            [
                "check",
                "--ledger",
                str(ledger),
                "--by",
                "test",
                "--mensaje-id",
                "m1",
                "--a",
                "mcp:x",
                "--modo",
                "auto",
            ],
            tmp_path,
        )
        assert proc.returncode == 0  # The record is read correctly

    def test_d4_record_completes_last_line_without_newline(self, tmp_path):
        """record on ledger without trailing \n: adds \n before new line."""
        ledger = tmp_path / "no_newline_record.jsonl"
        # Write ONE record WITHOUT trailing newline
        ledger.write_text(
            json.dumps({"mensaje_id": "m1", "resultado": "error"}, ensure_ascii=False),
            encoding="utf-8",
        )
        # record should add \n before the new line
        proc = _run_helper(
            [
                "record",
                "--ledger",
                str(ledger),
                "--by",
                "test",
                "--mensaje-id",
                "m2",
                "--a",
                "mcp:y",
                "--modo",
                "auto",
                "--resultado",
                "enviado",
            ],
            tmp_path,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        # The ledger must have exactly 2 lines, both valid JSON
        lines = ledger.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2, f"Expected 2 lines, got {len(lines)}: {lines}"
        json.loads(lines[0])  # Should parse
        json.loads(lines[1])  # Should parse

    def test_d5_repeated_mensaje_id_respects_rule(self, tmp_path):
        """mensaje_id repetido: the P-N2 rule applies.

        Writes TWO lines to the SAME file (not overwriting) to test
        that the ledger sees both records and applies the rule correctly.
        """
        ledger = tmp_path / "repeat.jsonl"
        line1 = json.dumps(
            {"mensaje_id": "m1", "resultado": "enviado"}, ensure_ascii=False
        )
        line2 = json.dumps(
            {"mensaje_id": "m1", "resultado": "error"}, ensure_ascii=False
        )
        # Write both lines to the same file in append mode
        with open(ledger, "w", encoding="utf-8") as f:
            f.write(line1 + "\n")
            f.write(line2 + "\n")
        proc = _run_helper(
            [
                "check",
                "--ledger",
                str(ledger),
                "--by",
                "test",
                "--mensaje-id",
                "m1",
                "--a",
                "mcp:x",
                "--modo",
                "auto",
            ],
            tmp_path,
        )
        assert proc.returncode == 0  # enviado is NOT terminal

    def test_d6_ts_and_by(self, tmp_path):
        """ts lo pone el reloj del helper, by es argumento: verificado por estructura."""
        ledger = tmp_path / "verify.jsonl"
        proc = _run_helper(
            [
                "record",
                "--ledger",
                str(ledger),
                "--by",
                "test_actor",
                "--mensaje-id",
                "m1",
                "--a",
                "mcp:x",
                "--modo",
                "queue",
                "--resultado",
                "enviado",
            ],
            tmp_path,
        )
        assert proc.returncode == 0
        lines = ledger.read_text(encoding="utf-8").splitlines()
        obj = json.loads(lines[0])
        assert set(obj.keys()) == FIXED_KEYS
        assert obj["by"] == "test_actor"
        assert "ts" in obj
        # Verify ts parses as ISO 8601 and is within 120s of current time
        from datetime import datetime, timezone

        ts_dt = datetime.fromisoformat(obj["ts"])
        now = datetime.now(timezone.utc)
        assert abs((now - ts_dt).total_seconds()) < 120


class TestCensoMcpPrefix:
    """Censo AST: only thread_id.py should have the literal mcp: as a constant."""

    def test_censo_mcp_prefix_in_scripts_py(self):
        """Censo AST de constantes cadena iguales a mcp: en scripts/**/*.py debe ser 1."""
        root = _SCRIPTS_DIR
        count = 0
        found_files = []

        for py in sorted(root.rglob("*.py")):
            if "__pycache__" in py.parts:
                continue
            src = py.read_text(encoding="utf-8")
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and node.value == "mcp:":
                    count += 1
                    found_files.append(str(py.relative_to(_SCRIPTS_DIR.parent)))

        assert count == 1, (
            f"Expected exactly 1 file with mcp: constant, found {count} in: {found_files}"
        )
        assert any("thread_id.py" in f and "flight" in f for f in found_files)


# --- Phase 2: Tests for writer and guard isolation (D4) ---


# Classes of failure when loading scripts/flight/thread_id.py (cold table, WOT-2026-136h):
# the file is absent, is not valid UTF-8, loads but lacks has_mcp_prefix, or raises
# when executed. None = the file does not exist in the isolated tree.
_LOAD_FAILURE_MODES: dict[str, bytes | None] = {
    "ausente": None,
    "no_utf8": b"\xff\xfe\x00 not utf8 \x80\x81\n",
    "sin_has_mcp_prefix": b"MCP_PREFIX = 'mcp:'\n",
    "exec_lanza": b"raise RuntimeError('boom en exec_module')\n",
}


def _isolated_tree(tmp_path: Path, mode: str | None) -> Path:
    """Copy the flight scripts into an isolated tree with a chosen thread_id.py.

    Before: tmp_path is empty; mode is a key of _LOAD_FAILURE_MODES, or None for
        the positive control (the REAL thread_id.py is copied).
    During: copies the writer, the guard and the helper to tmp_path/iso/scripts and
        writes (or omits) flight/thread_id.py according to mode.
    After: returns the isolated scripts directory; nothing outside tmp_path changes.
    """
    scripts = tmp_path / "iso" / "scripts"
    (scripts / "flight").mkdir(parents=True)
    for name in (
        "flight_roster_writer.py",
        "check_roster_matches_acting_thread.py",
    ):
        shutil.copy(_SCRIPTS_DIR / name, scripts / name)
    shutil.copy(_SEND_WITH_LEDGER, scripts / "flight" / "send_with_ledger.py")
    if mode is None:
        shutil.copy(
            _SCRIPTS_DIR / "flight" / "thread_id.py",
            scripts / "flight" / "thread_id.py",
        )
    elif _LOAD_FAILURE_MODES[mode] is not None:
        (scripts / "flight" / "thread_id.py").write_bytes(_LOAD_FAILURE_MODES[mode])
    return scripts


class TestWriterLoadFailureSubprocess:
    """The writer fails closed (rc 3, roster intact, no Traceback) on EVERY load failure.

    Runs a REAL rotation, so the prefix validation is actually reached (a `--help`
    run never touches the shared module and would pass with the defect present).
    """

    @staticmethod
    def _rotate(scripts: Path, tmp_path: Path):
        """Run a real supervisor rotation with the isolated writer.

        Before: scripts is an isolated tree from _isolated_tree.
        During: writes the rotation roster and runs the writer CLI as a subprocess.
        After: returns (proc, roster_path, changes_path, roster_bytes, changes_bytes).
        """
        from tests.unit.test_flight_roster_writer import (
            _rotation_roster,
            _write_rotation_files,
        )

        roster_p, changes_p = _write_rotation_files(tmp_path, _rotation_roster())
        roster_before = roster_p.read_bytes()
        changes_before = changes_p.read_bytes()
        proc = subprocess.run(
            [
                sys.executable,
                str(scripts / "flight_roster_writer.py"),
                "--roster",
                str(roster_p),
                "--changes-log",
                str(changes_p),
                "--actor",
                "test",
                "--reason",
                "load-failure",
                "--supervisor-thread",
                "mcp:sup-previo",
                "--supervisor-code",
                "sp",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(tmp_path),
        )
        return proc, roster_p, changes_p, roster_before, changes_before

    @pytest.mark.parametrize("mode", list(_LOAD_FAILURE_MODES))
    def test_load_failure_rc3_clean_roster_intact(self, tmp_path, mode):
        """Every load-failure class => rc 3, no Traceback, roster and log untouched."""
        scripts = _isolated_tree(tmp_path, mode)
        proc, roster_p, changes_p, roster_before, changes_before = self._rotate(
            scripts, tmp_path
        )
        assert proc.returncode == 3, proc.stdout + proc.stderr
        assert "Traceback" not in proc.stderr, proc.stderr
        assert roster_p.read_bytes() == roster_before
        assert changes_p.read_bytes() == changes_before
        assert "thread_id" in proc.stdout + proc.stderr

    def test_positive_control_rotates_with_the_module(self, tmp_path):
        """Same rotation WITH the real module => rc 0 and the roster changes."""
        scripts = _isolated_tree(tmp_path, None)
        proc, roster_p, _changes_p, roster_before, _ = self._rotate(scripts, tmp_path)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert roster_p.read_bytes() != roster_before
        data = json.loads(roster_p.read_text(encoding="utf-8"))
        assert data["active_roles"]["supervisor"]["threadId"] == "mcp:sup-previo"


class TestGuardLoadFailureSubprocess:
    """The guard, WITH a roster to check, fails with rc 1 naming the cause on EVERY
    load failure; WITHOUT a roster it stays N/A (rc 3), never a Traceback."""

    @staticmethod
    def _run_guard(scripts: Path, tmp_path: Path, with_roster: bool):
        """Run the isolated guard; with_roster decides whether a roster path is given.

        Before: scripts is an isolated tree from _isolated_tree.
        During: writes the rotation roster when with_roster and runs the guard CLI.
        After: returns the CompletedProcess.
        """
        from tests.unit.test_flight_roster_writer import (
            _rotation_roster,
            _write_rotation_files,
        )

        args = [
            sys.executable,
            str(scripts / "check_roster_matches_acting_thread.py"),
            "--acting-thread",
            "mcp:orq-actual",
        ]
        if with_roster:
            roster_p, _ = _write_rotation_files(tmp_path, _rotation_roster())
            args += ["--roster-path", str(roster_p)]
        env = dict(__import__("os").environ)
        env.pop("FLIGHT_ROSTER_PATH", None)
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
            cwd=str(tmp_path),
        )

    @pytest.mark.parametrize("mode", list(_LOAD_FAILURE_MODES))
    def test_with_roster_rc1_names_the_cause(self, tmp_path, mode):
        """With a roster: rc 1 (never 3 and never 'indeterminado'), cause on stdout."""
        scripts = _isolated_tree(tmp_path, mode)
        proc = self._run_guard(scripts, tmp_path, with_roster=True)
        assert proc.returncode == 1, proc.stdout + proc.stderr
        assert "Traceback" not in proc.stderr, proc.stderr
        assert "scripts/flight/thread_id.py" in proc.stdout, proc.stdout

    @pytest.mark.parametrize("mode", list(_LOAD_FAILURE_MODES))
    def test_without_roster_stays_na_rc3(self, tmp_path, mode):
        """Without a roster the guard is N/A (rc 3) whatever the module state."""
        scripts = _isolated_tree(tmp_path, mode)
        proc = self._run_guard(scripts, tmp_path, with_roster=False)
        assert proc.returncode == 3, proc.stdout + proc.stderr
        assert "Traceback" not in proc.stderr, proc.stderr

    def test_positive_control_does_not_blame_the_module(self, tmp_path):
        """With the real module the load-failure line is absent (the cause is specific)."""
        scripts = _isolated_tree(tmp_path, None)
        proc = self._run_guard(scripts, tmp_path, with_roster=True)
        assert "Traceback" not in proc.stderr, proc.stderr
        assert "scripts/flight/thread_id.py" not in proc.stdout, proc.stdout


class TestHelperLoadFailureSubprocess:
    """The helper (check and record) exits rc 2 with the cause on stdout and writes
    NOTHING when the shared module cannot be loaded (supuesto del Manager: the plan
    fixes no code for it; rc 2 is the environment-error code, never 3)."""

    @staticmethod
    def _args(sub: str, ledger: Path) -> list[str]:
        common = [
            "--ledger",
            str(ledger),
            "--by",
            "x",
            "--mensaje-id",
            "m1",
            "--a",
            "mcp:x",
            "--modo",
            "queue",
        ]
        if sub == "record":
            common += ["--resultado", "enviado"]
        return [sub, *common]

    def _run(self, scripts: Path, tmp_path: Path, sub: str, ledger: Path):
        return subprocess.run(
            [
                sys.executable,
                str(scripts / "flight" / "send_with_ledger.py"),
                *self._args(sub, ledger),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(tmp_path),
        )

    @pytest.mark.parametrize("sub", ["check", "record"])
    @pytest.mark.parametrize("mode", list(_LOAD_FAILURE_MODES))
    def test_load_failure_rc2_cause_and_nothing_written(self, tmp_path, mode, sub):
        """Every load-failure class => rc 2, cause on stdout, no Traceback, no ledger."""
        scripts = _isolated_tree(tmp_path, mode)
        ledger = tmp_path / "ledger.jsonl"
        proc = self._run(scripts, tmp_path, sub, ledger)
        assert proc.returncode == 2, proc.stdout + proc.stderr
        assert "Traceback" not in proc.stderr, proc.stderr
        assert "scripts/flight/thread_id.py" in proc.stdout, proc.stdout
        assert not ledger.exists()

    @pytest.mark.parametrize("sub", ["check", "record"])
    def test_positive_control_with_the_module(self, tmp_path, sub):
        """The same arguments with the real module => rc 0 (and record writes a line)."""
        scripts = _isolated_tree(tmp_path, None)
        ledger = tmp_path / "ledger.jsonl"
        proc = self._run(scripts, tmp_path, sub, ledger)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert ledger.exists() == (sub == "record")


class TestGuardWithoutModuleSubprocess:
    """Test check_roster_matches_acting_thread without thread_id.py -> rc 1, cause named."""

    def _run_isolated(
        self, guard_path: Path, tmp_path: Path, roster_path: Path | None = None
    ) -> subprocess.CompletedProcess:
        """Copy guard to isolated dir WITHOUT thread_id.py and run it."""
        iso = tmp_path / "iso"
        iso.mkdir(parents=True)
        import shutil

        shutil.copy2(guard_path, iso / "check_roster_matches_acting_thread.py")
        # Create minimal flight dir without thread_id.py
        (iso / "flight").mkdir()
        # Create a minimal roster if not provided
        if roster_path is None:
            roster_data = {
                "active_roles": {
                    "orquestador": {"threadId": "mcp:orq-001", "version": 1}
                }
            }
            roster_path = iso / "roster.json"
            roster_path.write_text(
                json.dumps(roster_data, indent=2) + "\n", encoding="utf-8"
            )
        env = dict(__import__("os").environ)
        env.pop("FLIGHT_ROSTER_PATH", None)
        args = [
            sys.executable,
            str(iso / "check_roster_matches_acting_thread.py"),
            "--roster-path",
            str(roster_path),
            "--acting-thread",
            "mcp:orq-001",
        ]
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            cwd=str(iso),
        )

    def test_guard_with_roster_no_module_rc1_cause_named(self, tmp_path):
        """Guard with roster but no thread_id.py -> rc 1, cause named, no Traceback."""
        guard_path = _SCRIPTS_DIR / "check_roster_matches_acting_thread.py"
        proc = self._run_isolated(guard_path, tmp_path)
        assert proc.returncode == 1, (
            f"Expected rc 1 (violation), got {proc.returncode}: {proc.stdout}"
        )
        # Should name the cause (thread_id.py missing)
        assert "thread_id.py" in proc.stdout or "thread_id" in proc.stdout, (
            f"Guard should name the cause (missing thread_id.py): {proc.stdout}"
        )
        # Should NOT contain Traceback
        assert "Traceback" not in proc.stderr, (
            f"Guard should NOT print Traceback: {proc.stderr}"
        )

    def test_guard_without_roster_rc3(self, tmp_path):
        """Guard without roster path -> rc 3 (N/A)."""
        guard_path = _SCRIPTS_DIR / "check_roster_matches_acting_thread.py"
        iso = tmp_path / "iso"
        iso.mkdir(parents=True)
        import shutil

        shutil.copy2(guard_path, iso / "check_roster_matches_acting_thread.py")
        (iso / "flight").mkdir()
        env = dict(__import__("os").environ)
        env.pop("FLIGHT_ROSTER_PATH", None)
        # No --roster-path and no FLIGHT_ROSTER_PATH
        args = [
            sys.executable,
            str(iso / "check_roster_matches_acting_thread.py"),
            "--acting-thread",
            "mcp:orq-001",
        ]
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            cwd=str(iso),
        )
        assert proc.returncode == 3, f"Expected rc 3 (N/A), got {proc.returncode}"


class TestGuardAndWriterCallSharedFunction:
    """AST aserto: writer, guard, and helper CALL the shared has_mcp_prefix."""

    def _check_calls_shared_function(self, py_path: Path):
        """Verify the file really CALLS has_mcp_prefix from the shared module.

        Before: py_path is a Python source file.
        During: parses it with ast; collects the local names bound to the shared
            function (an assignment whose value is `<x>.has_mcp_prefix` or a
            `_get_has_mcp_prefix()` call) and looks for an ast.Call whose func is
            the attribute `.has_mcp_prefix` or one of those names.
        After: asserts there is at least one such call. A mere attribute read, an
            assignment of the function or a call to the factory that returns it does
            NOT count (importing or holding the function is not calling it).
        """
        tree = ast.parse(py_path.read_text(encoding="utf-8"))
        aliases = {"has_mcp_prefix"}
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
            ):
                value = node.value
                binds_function = (
                    isinstance(value, ast.Attribute) and value.attr == "has_mcp_prefix"
                ) or (
                    isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Name)
                    and value.func.id == "_get_has_mcp_prefix"
                )
                if binds_function:
                    aliases.add(node.targets[0].id)
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and (
                (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "has_mcp_prefix"
                )
                or (isinstance(node.func, ast.Name) and node.func.id in aliases)
            )
        ]
        assert calls, f"{py_path.name} must CALL has_mcp_prefix from the shared module"

    def test_checker_distinguishes_call_from_access(self, tmp_path):
        """Control positivo/negativo de la barrera: una lectura NO es una llamada."""
        casos = {
            "lectura_de_atributo": "x = mod.has_mcp_prefix\n",
            "asignacion_sin_llamada": "f = mod.has_mcp_prefix\nif f is None:\n    pass\n",
            "fabrica_sin_llamar_a_la_funcion": "g = _get_has_mcp_prefix()\nif g:\n    pass\n",
            "llamada_directa": "mod.has_mcp_prefix(a)\n",
            "llamada_por_alias": "f = mod.has_mcp_prefix\nf(a)\n",
            "llamada_por_fabrica": "g = _get_has_mcp_prefix()\ng(a)\n",
        }
        for nombre, fuente in casos.items():
            ruta = tmp_path / f"{nombre}.py"
            ruta.write_text(fuente, encoding="utf-8")
            if nombre.startswith("llamada"):
                self._check_calls_shared_function(ruta)
            else:
                with pytest.raises(AssertionError):
                    self._check_calls_shared_function(ruta)

    def test_writer_calls_shared_function(self):
        """flight_roster_writer.py calls has_mcp_prefix from thread_id."""
        writer_path = _SCRIPTS_DIR / "flight_roster_writer.py"
        self._check_calls_shared_function(writer_path)

    def test_guard_calls_shared_function(self):
        """check_roster_matches_acting_thread.py calls has_mcp_prefix from thread_id."""
        guard_path = _SCRIPTS_DIR / "check_roster_matches_acting_thread.py"
        self._check_calls_shared_function(guard_path)

    def test_helper_calls_shared_function(self):
        """send_with_ledger.py calls has_mcp_prefix from thread_id."""
        self._check_calls_shared_function(_SEND_WITH_LEDGER)
