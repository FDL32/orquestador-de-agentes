"""Minimal tests for agent_controller.py canonical functions.

Only tests functions that exist in the canonical controller:
- read_file
- write_file
- validate_state_files
- determine_next_action
- should_overwrite_turn
- update_log_status
- run_quality_gates

Full test suite for removed functions (normalize_*, mark_*, perform_*,
request_*, get_rejection_*, publish_*) can be restored when those
functions are implemented.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# Add .agent to path for imports
PROJECT_ROOT = Path(__file__).parent.parent
agent_dir = PROJECT_ROOT / ".agent"
if str(agent_dir) not in sys.path:
    sys.path.insert(0, str(agent_dir))

import agent_controller  # noqa: E402
import motor_checkpoint  # noqa: E402
from agent_controller import (  # noqa: E402
    determine_next_action,
    read_file,
    run_quality_gates,
    should_overwrite_turn,
    update_log_status,
    validate_state_files,
    write_file,
)


def test_agent_controller_help_lists_critical_flags() -> None:
    controller = PROJECT_ROOT / ".agent" / "agent_controller.py"
    result = subprocess.run(
        [sys.executable, str(controller), "--help"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    for flag in (
        "--mark-ready",
        "--validate",
        "--manager-approve <ticket>",
        "--request-changes <ticket>",
        # WOT-2026-013u: reopen consumes a ticket, so the help must show <ticket>.
        "--reopen-terminal-ticket <ticket>",
        "--resume-human-gate",
        "--bootstrap-ticket",
        "--escalate-human-gate",
        "--pre-handoff",
    ):
        assert flag in result.stdout
    # WOT-2026-013u: help must document BOTH the positional and the --ticket form
    # for ticket actions, so neither is silently the only supported one.
    assert "--ticket <id>" in result.stdout
    assert "positional" in result.stdout
    assert "Traceback" not in result.stderr
    assert "error:" not in result.stderr.lower()


# WOT-2026-013u: shared helper that exercises the REAL CLI dispatch (subprocess),
# not the internal handlers, so the barriers cover the actual --ticket parser.
#
# Hermetic: the helper builds its OWN throwaway project-root with a placeholder
# work_plan (no active ticket), so the barrier does NOT depend on the live
# dogfooding workspace state. The marker is "No ticket_id provided": it appears
# ONLY when the parser fails to capture the ticket (the pre-fix inverted-condition
# symptom, emitted BEFORE any work_plan lookup). When the parser captures the
# ticket, the flow proceeds to the ticket lookup and emits a DIFFERENT error
# (e.g. "No active ticket found in work_plan.md"), so the absence of
# "No ticket_id provided" is a robust, state-independent signal that the ticket
# was parsed. asserting on downstream errors like "does not match active ticket"
# is FRAGILE because it depends on what ticket the work_plan holds.
_NOT_PARSED_MARKER = "No ticket_id provided"
_FAKE_TICKET = "WOT-TEST-013U-001"


def _run_controller_hermetic(*args: str) -> subprocess.CompletedProcess:
    controller = PROJECT_ROOT / ".agent" / "agent_controller.py"
    with tempfile.TemporaryDirectory() as tmp:
        collab = Path(tmp) / ".agent" / "collaboration"
        collab.mkdir(parents=True, exist_ok=True)
        # Placeholder work_plan with NO active ticket -> deterministic downstream
        # error, independent of the live workspace.
        (collab / "work_plan.md").write_text(
            "# Plan de Trabajo\n\nNo active ticket here.\n", encoding="utf-8"
        )
        return subprocess.run(
            [
                sys.executable,
                str(controller),
                *args,
                "--json",
                "--force",
                "--project-root",
                tmp,
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )


def _assert_ticket_parsed(result: subprocess.CompletedProcess) -> None:
    """The parser captured the ticket iff "No ticket_id provided" is absent."""
    combined = result.stdout + result.stderr
    assert _NOT_PARSED_MARKER not in combined, combined


def _assert_ticket_not_parsed(result: subprocess.CompletedProcess) -> None:
    combined = result.stdout + result.stderr
    assert _NOT_PARSED_MARKER in combined, combined


def test_ticket_parser_reads_control_flag_before_positional_fallback() -> None:
    """--manager-approve --ticket <id> must capture the id via the --ticket parser.

    Mutation barrier: reintroducing the inverted condition
    `idx + 1 >= len(sys.argv)` makes ticket_id stay None, so "No ticket_id
    provided" reappears and this test FAILS. Hermetic: own tmp project-root.
    """
    _assert_ticket_parsed(
        _run_controller_hermetic("--manager-approve", "--ticket", _FAKE_TICKET)
    )


def test_ticket_parser_omitted_reports_no_ticket() -> None:
    """Negative control: with NO ticket at all, the parser reports it (proves the
    marker is real and not vacuously absent)."""
    _assert_ticket_not_parsed(_run_controller_hermetic("--manager-approve"))


def test_reopen_terminal_ticket_accepts_ticket_flag() -> None:
    """--reopen-terminal-ticket --ticket <id> must capture the id (parser path)."""
    _assert_ticket_parsed(
        _run_controller_hermetic("--reopen-terminal-ticket", "--ticket", _FAKE_TICKET)
    )


def test_reopen_terminal_ticket_positional_still_supported() -> None:
    """Backward-compat: the positional form must keep working (not deprecated)."""
    _assert_ticket_parsed(
        _run_controller_hermetic("--reopen-terminal-ticket", _FAKE_TICKET)
    )


class TestReadFile:
    """Test read_file handles filesystem correctly."""

    def test_read_file_existing_path(self, tmp_path):
        """read_file returns content from existing file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        result = read_file(test_file)
        assert result == "test content"

    def test_read_file_missing_path(self, tmp_path):
        """read_file returns empty string for missing file."""
        missing_file = tmp_path / "missing.txt"

        result = read_file(missing_file)
        assert result == ""


class TestWriteFile:
    """Test write_file creates and updates files."""

    def test_write_file_creates_new(self, tmp_path):
        """write_file creates new file with content."""
        test_file = tmp_path / "new.txt"
        write_file(test_file, "new content")

        assert test_file.exists()
        assert test_file.read_text() == "new content"

    def test_write_file_overwrites_existing(self, tmp_path):
        """write_file overwrites existing file."""
        test_file = tmp_path / "existing.txt"
        test_file.write_text("old content")

        write_file(test_file, "new content")

        assert test_file.read_text() == "new content"

    def test_write_file_creates_parent_dirs(self, tmp_path):
        """write_file creates parent directories if needed."""
        test_file = tmp_path / "subdir" / "nested" / "file.txt"
        write_file(test_file, "nested content")

        assert test_file.exists()
        assert test_file.read_text() == "nested content"


class TestValidateStateFiles:
    """Test validate_state_files checks state consistency."""

    def test_validate_returns_dict_with_keys(self):
        """validate_state_files returns proper error dict structure."""
        with patch("agent_controller.read_file", return_value=""):
            errors = validate_state_files()

        # Should have these keys
        assert "work_plan.md" in errors
        assert "execution_log.md" in errors
        assert "TURN.md" in errors
        assert "consistency" in errors

    def test_validate_detects_missing_section(self):
        """validate_state_files detects missing required sections."""
        with (
            patch("agent_controller.read_file", return_value="# Empty file\n"),
            patch(
                "agent_controller.TURN_FILE",
                MagicMock(exists=MagicMock(return_value=True)),
            ),
        ):
            errors = validate_state_files()

        # Should detect missing sections
        assert len(errors["TURN.md"]) > 0 or len(errors["consistency"]) > 0

    def test_validate_accepts_seed_neutral_motor_state(self, monkeypatch):
        """The portable motor seed with no active ticket must validate cleanly."""
        seed_plan = (
            "# Work Plan - Seed\n\n"
            "## Metadata\n"
            "- **ID:** none\n"
            "- **Estado:** READY_TO_START\n"
            "- **deliverable_type:** code\n"
            "- **Titulo:** Seed neutral del motor\n"
            "- **Asignado a:** Manager\n"
        )
        seed_log = "# Execution Log - Seed\n\n**Estado:** READY_TO_START\n"
        seed_turn = (
            "# TURNO ACTUAL\n\n"
            "## Agente Activo\n\n"
            "| Campo | Valor |\n"
            "|-------|-------|\n"
            "| **ROL** | **MANAGER** |\n"
            "| **Plan ID** | none |\n"
            "| **Tipo** | SEED |\n"
            "| **Accion** | WAIT |\n"
        )
        seed_state = "ACTIVE_TICKET: none\nSTATUS: READY_TO_START\n"

        def fake_read(path):
            name = str(path)
            if name.endswith("work_plan.md"):
                return seed_plan
            if name.endswith("execution_log.md"):
                return seed_log
            if name.endswith("TURN.md"):
                return seed_turn
            if name.endswith("STATE.md"):
                return seed_state
            return ""

        monkeypatch.setattr(agent_controller, "read_file", fake_read)

        errors = validate_state_files()

        assert all(not items for items in errors.values()), errors


class TestDetermineNextAction:
    """Test determine_next_action analyzes state and returns action."""

    def test_determine_next_action_returns_dict(self):
        """determine_next_action returns proper action dict."""
        with (
            patch("agent_controller.read_file", return_value=""),
            patch("agent_controller.HOOKS_AVAILABLE", False),
        ):
            action = determine_next_action(skip_gates=True)

        # Should return dict with role and action_type
        assert isinstance(action, dict)
        assert "role" in action


class TestShouldOverwriteTurn:
    """Test should_overwrite_turn determines if TURN.md needs reset."""

    def test_should_overwrite_turn_returns_bool(self):
        """should_overwrite_turn returns boolean."""
        with patch.object(Path, "exists", return_value=False):
            result = should_overwrite_turn(Path("/fake/TURN.md"))

        assert isinstance(result, bool)


class TestUpdateLogStatus:
    """Test update_log_status modifies execution log."""

    def test_update_log_status_returns_bool(self):
        """update_log_status returns success boolean."""
        with (
            patch("agent_controller.read_file", return_value="# Execution Log\n"),
            patch("agent_controller.write_file"),
        ):
            result = update_log_status("IN_PROGRESS", "test note")

        assert isinstance(result, bool)


class TestRunQualityGates:
    """Test run_quality_gates executes validation checks."""

    def test_run_quality_gates_returns_dict(self):
        """run_quality_gates returns result dict with expected keys."""
        with (
            patch("agent_controller.read_file", return_value=""),
            patch("agent_controller.subprocess"),
        ):
            result = run_quality_gates()

        assert isinstance(result, dict)
        # Should have standard result keys: errors, passed, summary, warnings
        assert "passed" in result
        assert "summary" in result

    def test_run_quality_gates_does_not_rerun_pytest_with_timeout(self):
        """WOT-2026-016c (iterado): el gate NO re-corre pytest con timeout=120.
        Delega en el stamp de run_pytest_safe. Un subprocess de pytest con
        timeout=120 sobre la suite canonica (>120s) volveria a los bugs
        (AUTO-REJECT espurio o no-op/falso-verde). Verifica que el gate no invoca
        pytest via subprocess.run."""
        mock_run = MagicMock(
            return_value=MagicMock(returncode=0, stdout=b"", stderr=b"")
        )
        with (
            patch("agent_controller.read_file", return_value=""),
            patch("agent_controller.subprocess.run", mock_run),
            patch(
                "agent_controller._read_pytest_safe_verdict",
                return_value={"verdict": "green", "detail": "x"},
            ),
        ):
            run_quality_gates()

        pytest_calls = [
            call
            for call in mock_run.call_args_list
            if call.args and "pytest" in call.args[0]
        ]
        assert pytest_calls == [], (
            f"El gate NO debe re-correr pytest via subprocess; se encontro: {pytest_calls}"
        )

    def test_run_quality_gates_pytest_green_from_stamp(self):
        """WOT-2026-016c: stamp verde (run_pytest_safe) -> passed=True, [OK]."""
        with (
            patch("agent_controller.read_file", return_value=""),
            patch(
                "agent_controller.subprocess.run",
                MagicMock(return_value=MagicMock(returncode=0, stdout=b"", stderr=b"")),
            ),
            patch(
                "agent_controller._read_pytest_safe_verdict",
                return_value={"verdict": "green", "detail": "suite verde"},
            ),
        ):
            result = run_quality_gates()
        assert result["passed"] is True
        assert any("[OK] Pytest" in msg for msg in result["summary"])

    def test_run_quality_gates_real_failure_is_not_masked(self):
        """WOT-2026-016c (el fix de fondo, contra Review 2): un fallo REAL de la
        suite NO se enmascara como pass. verdict=red -> passed=False. Esto cierra
        la ventana de falso-verde donde un test que falla en una suite lenta
        quedaba oculto como 'timeout benigno'."""
        with (
            patch("agent_controller.read_file", return_value=""),
            patch(
                "agent_controller.subprocess.run",
                MagicMock(return_value=MagicMock(returncode=0, stdout=b"", stderr=b"")),
            ),
            patch(
                "agent_controller._read_pytest_safe_verdict",
                return_value={
                    "verdict": "red",
                    "detail": "1 test(s) fallando: ['tests/x.py::test_a']",
                },
            ),
        ):
            result = run_quality_gates()
        assert result["passed"] is False
        assert any("[FAIL] Pytest" in msg for msg in result["summary"])

    def test_run_quality_gates_inconclusive_stamp_does_not_fake_pass(self):
        """WOT-2026-016c: stamp ausente/desalineado -> WARN visible, NO fuerza
        pass silencioso ni fail. El pre-handoff canonico exige stamp fresco por
        separado; aqui es senal suave, no no-op."""
        with (
            patch("agent_controller.read_file", return_value=""),
            patch(
                "agent_controller.subprocess.run",
                MagicMock(return_value=MagicMock(returncode=0, stdout=b"", stderr=b"")),
            ),
            patch(
                "agent_controller._read_pytest_safe_verdict",
                return_value={"verdict": "inconclusive", "detail": "sin last-run.json"},
            ),
        ):
            result = run_quality_gates()
        # No [OK] Pytest ni [FAIL] Pytest en summary; si un WARN accionable.
        assert not any("Pytest" in msg for msg in result["summary"])
        assert any(
            "no concluyente" in msg.lower() or "run_pytest_safe" in msg
            for msg in result["warnings"]
        )

    def test_run_quality_gates_inconclusive_stamp_prints_warning_to_operator(
        self, capsys
    ):
        """WOT-2026-016x: el WARN de stamp inconclusive debe llegar al operador
        como salida VISIBLE (stdout), no solo acumularse en result["warnings"].
        El veredicto NO cambia (passed sigue True); esto es puramente
        visibilidad diagnostica."""
        with (
            patch("agent_controller.read_file", return_value=""),
            patch(
                "agent_controller.subprocess.run",
                MagicMock(return_value=MagicMock(returncode=0, stdout=b"", stderr=b"")),
            ),
            patch(
                "agent_controller._read_pytest_safe_verdict",
                return_value={"verdict": "inconclusive", "detail": "sin last-run.json"},
            ),
        ):
            result = run_quality_gates()
        captured = capsys.readouterr()
        assert result["passed"] is True
        assert result["warnings"][0] in captured.out
        assert "no concluyente" in captured.out.lower()

    def test_read_pytest_safe_verdict_partial_coverage_is_inconclusive(
        self, tmp_path, monkeypatch
    ):
        """WOT-2026-016c (Rev2 nit): un stamp de cobertura PARCIAL (--level unit
        o paths explicitos) NO debe dar green, aunque exit_code sea 0 y el sha
        coincida con HEAD -- seria un falso verde con solo una fraccion de la
        suite. Debe degradar a inconclusive (mismo criterio que
        assert_canonical_suite_green: level==all + default_discovery)."""
        import agent_controller as ac

        # Repo git real con un commit, para que HEAD resuelva.
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.email=t@t",
                "-c",
                "user.name=t",
                "commit",
                "--allow-empty",
                "-q",
                "-m",
                "base",
            ],
            cwd=tmp_path,
            check=True,
        )
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True
        ).stdout.strip()
        stamp_dir = tmp_path / ".agent" / "runtime" / "pytest-safe"
        stamp_dir.mkdir(parents=True)
        monkeypatch.setattr(ac, "PROJECT_ROOT", tmp_path)

        def write_stamp(**over):
            base = {
                "tested_commit_sha": head,
                "status": "finished",
                "exit_code": 0,
                "level": "all",
                "args_mode": "default_discovery",
            }
            base.update(over)
            (stamp_dir / "last-run.json").write_text(json.dumps(base), encoding="utf-8")

        # level=all + discovery + exit 0 -> green (control).
        write_stamp()
        assert ac._read_pytest_safe_verdict()["verdict"] == "green"
        # level=unit -> inconclusive aunque exit 0.
        write_stamp(level="unit")
        assert ac._read_pytest_safe_verdict()["verdict"] == "inconclusive"
        # paths explicitos -> inconclusive aunque exit 0.
        write_stamp(args_mode="explicit_paths")
        assert ac._read_pytest_safe_verdict()["verdict"] == "inconclusive"

    def test_read_pytest_safe_verdict_oserror_detail_has_no_absolute_path(
        self, tmp_path, monkeypatch
    ):
        """WOT-2026-019b: un OSError al leer el stamp NO debe filtrar la ruta
        absoluta local (username incluido) en el detail devuelto. El except de
        OSError debe componer el detail via
        scope_gate._relativize_scope_path(exc.filename, PROJECT_ROOT), nunca
        str(exc) crudo ni exc.filename sin relativizar."""
        import agent_controller as ac

        monkeypatch.setattr(ac, "PROJECT_ROOT", tmp_path)
        stamp_dir = tmp_path / ".agent" / "runtime" / "pytest-safe"
        stamp_dir.mkdir(parents=True)
        stamp_path = stamp_dir / "last-run.json"
        # stamp_path.exists() debe ser True para llegar al try/except (linea
        # 2034-2035 corta antes con un detail distinto si no existe).
        stamp_path.write_text("{}", encoding="utf-8")

        absolute_path_str = str(stamp_path)
        real_read_text = Path.read_text

        def fake_read_text(self, *args, **kwargs):
            if self == stamp_path:
                raise OSError(13, "Permission denied", absolute_path_str)
            return real_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", fake_read_text)

        result = ac._read_pytest_safe_verdict()

        assert result["verdict"] == "inconclusive"
        detail = result["detail"]
        # La ruta absoluta simulada (que vive bajo tmp_path, con o sin
        # segmento de usuario real de esta maquina) no debe aparecer entera.
        assert absolute_path_str not in detail
        assert str(tmp_path) not in detail
        # El username real de quien ejecuta el test tampoco debe colarse.
        assert str(Path.home()) not in detail
        # Debe relativizar a <REPO_ROOT> (stamp_path esta dentro de PROJECT_ROOT).
        assert "<REPO_ROOT>" in detail
        assert "last-run.json" in detail
        # Informacion de diagnostico util (strerror/errno) se conserva.
        assert "Permission denied" in detail
        assert "13" in detail

    def test_read_pytest_safe_verdict_oserror_without_filename_is_safe(
        self, tmp_path, monkeypatch
    ):
        """WOT-2026-019b: si exc.filename es None (algunos OSError no lo
        traen), el except NO debe llamar a scope_gate._relativize_scope_path
        con None; debe caer al detail sin ruta (solo strerror/errno)."""
        import agent_controller as ac

        monkeypatch.setattr(ac, "PROJECT_ROOT", tmp_path)
        stamp_dir = tmp_path / ".agent" / "runtime" / "pytest-safe"
        stamp_dir.mkdir(parents=True)
        stamp_path = stamp_dir / "last-run.json"
        stamp_path.write_text("{}", encoding="utf-8")

        real_read_text = Path.read_text

        def fake_read_text(self, *args, **kwargs):
            if self == stamp_path:
                raise OSError("boom sin filename")
            return real_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", fake_read_text)

        result = ac._read_pytest_safe_verdict()

        assert result["verdict"] == "inconclusive"
        assert str(tmp_path) not in result["detail"]

    def test_read_pytest_safe_verdict_jsondecodeerror_detail_unchanged(
        self, tmp_path, monkeypatch
    ):
        """WOT-2026-019b (paridad): json.JSONDecodeError sigue cayendo en su
        propia rama, con str(exc) intacto (describe linea/columna del JSON
        invalido, no una ruta de filesystem; no tiene el problema de PII que
        si tiene OSError, y no debe perder informacion de diagnostico)."""
        import agent_controller as ac

        monkeypatch.setattr(ac, "PROJECT_ROOT", tmp_path)
        stamp_dir = tmp_path / ".agent" / "runtime" / "pytest-safe"
        stamp_dir.mkdir(parents=True)
        (stamp_dir / "last-run.json").write_text(
            "{ esto no es json valido", encoding="utf-8"
        )

        result = ac._read_pytest_safe_verdict()

        assert result["verdict"] == "inconclusive"
        assert result["detail"].startswith("stamp ilegible: ")
        # str(exc) de JSONDecodeError describe posicion (linea/columna), no
        # una ruta de filesystem: no debe contener el path absoluto local.
        assert str(tmp_path) not in result["detail"]


class TestHumanGateThreshold:
    """WP-2026-106 B-fix: HUMAN_GATE threshold is a single source of truth."""

    def test_threshold_reads_from_agents_config(self, tmp_path, monkeypatch):
        """get_human_gate_threshold reads manager_review.max_attempts."""
        import json

        cfg = tmp_path / "agents.json"
        cfg.write_text(
            json.dumps({"manager_review": {"max_attempts": 5}}), encoding="utf-8"
        )
        monkeypatch.setattr(agent_controller, "AGENTS_CONFIG_PATH", cfg)
        assert agent_controller.get_human_gate_threshold() == 5

    def test_threshold_falls_back_when_config_missing(self, tmp_path, monkeypatch):
        """Missing config -> safe fallback, never the legacy hardcoded 3."""
        monkeypatch.setattr(
            agent_controller, "AGENTS_CONFIG_PATH", tmp_path / "absent.json"
        )
        result = agent_controller.get_human_gate_threshold()
        assert result == agent_controller.HUMAN_GATE_REJECTION_FALLBACK
        assert result != 3

    def test_threshold_falls_back_on_malformed_config(self, tmp_path, monkeypatch):
        """Malformed JSON -> fallback, no exception."""
        bad = tmp_path / "agents.json"
        bad.write_text("{not valid json", encoding="utf-8")
        monkeypatch.setattr(agent_controller, "AGENTS_CONFIG_PATH", bad)
        assert (
            agent_controller.get_human_gate_threshold()
            == agent_controller.HUMAN_GATE_REJECTION_FALLBACK
        )


class TestTicketProseIntegration:
    """WP-2026-162: Ticket prose validation integration in _handle_validate."""

    def test_validate_includes_ticket_prose_warnings(self, tmp_path, monkeypatch):
        """_handle_validate includes ticket_prose warnings when validator available."""
        # Mock validate_ticket_prose to return warnings
        mock_result = {
            "warnings": [
                {
                    "rule_id": "TP-PROSE-01",
                    "rule_name": "throat-clearing",
                    "evidence": "test",
                    "suggestion": "fix",
                }
            ],
            "warning_count": 1,
        }

        def mock_validate(work_plan_path, collab_dir):
            return mock_result

        # Patch WORK_PLAN and get_collab_dir
        fake_work_plan = tmp_path / "work_plan.md"
        fake_work_plan.write_text("# Plan\n", encoding="utf-8")
        fake_collab = tmp_path / "collab"
        fake_collab.mkdir()

        monkeypatch.setattr(agent_controller, "WORK_PLAN", fake_work_plan)
        monkeypatch.setattr(agent_controller, "get_collab_dir", lambda: fake_collab)

        # Mock the validate_state_files and other dependencies to return empty
        monkeypatch.setattr(agent_controller, "validate_state_files", lambda: {})
        monkeypatch.setattr(
            agent_controller, "_collect_deliverable_type_warnings", lambda x: {}
        )
        monkeypatch.setattr(agent_controller, "read_file", lambda x: "")
        monkeypatch.setattr(agent_controller, "get_status", lambda x, y: "APPROVED")
        monkeypatch.setattr(
            agent_controller, "_check_scope_for_validate", lambda x, y: ([], [])
        )
        monkeypatch.setattr(agent_controller, "_check_bus_drift", lambda x, y: [])
        monkeypatch.setattr(
            agent_controller,
            "_check_invariants",
            lambda x, y, z: {"errors": [], "warnings": []},
        )

        # Patch the import
        import sys

        mock_module = type(
            "MockModule",
            (),
            {"validate_ticket_prose": staticmethod(mock_validate)},
        )()
        monkeypatch.setitem(sys.modules, "scripts.validate_ticket_prose", mock_module)

        # Capture stdout
        from io import StringIO

        captured = StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured

        try:
            exit_code = agent_controller._handle_validate(json_output=True)
        finally:
            sys.stdout = old_stdout

        # Exit code should be 0 (warnings don't block)
        assert exit_code == 0
        output = captured.getvalue()
        assert "ticket_prose" in output or "TP-PROSE" in output

    def test_validate_seed_neutral_skips_ticket_specific_advisories(self, monkeypatch):
        """Seed neutral validation must stay green without prose/scope/bus checks."""
        seed_plan = (
            "# Work Plan - Seed\n\n"
            "## Metadata\n"
            "- **ID:** none\n"
            "- **Estado:** READY_TO_START\n"
            "- **deliverable_type:** code\n"
            "- **Titulo:** Seed neutral del motor\n"
            "- **Asignado a:** Manager\n"
        )
        seed_log = "# Execution Log - Seed\n\n**Estado:** READY_TO_START\n"
        seed_turn = (
            "# TURNO ACTUAL\n\n"
            "## Agente Activo\n\n"
            "| Campo | Valor |\n"
            "|-------|-------|\n"
            "| **ROL** | **MANAGER** |\n"
            "| **Plan ID** | none |\n"
            "| **Tipo** | SEED |\n"
            "| **Accion** | WAIT |\n"
        )
        seed_state = "ACTIVE_TICKET: none\nSTATUS: READY_TO_START\n"

        def fake_read(path):
            name = str(path)
            if name.endswith("work_plan.md"):
                return seed_plan
            if name.endswith("execution_log.md"):
                return seed_log
            if name.endswith("TURN.md"):
                return seed_turn
            if name.endswith("STATE.md"):
                return seed_state
            return ""

        monkeypatch.setattr(agent_controller, "read_file", fake_read)
        monkeypatch.setattr(
            agent_controller, "_collect_deliverable_type_warnings", lambda _content: {}
        )
        monkeypatch.setattr(
            agent_controller,
            "_check_scope_for_validate",
            lambda *_args: (_ for _ in ()).throw(
                AssertionError("scope check should be skipped for seed")
            ),
        )
        monkeypatch.setattr(
            agent_controller,
            "_check_bus_drift",
            lambda *_args: (_ for _ in ()).throw(
                AssertionError("bus drift check should be skipped for seed")
            ),
        )
        monkeypatch.setattr(
            agent_controller,
            "_check_invariants",
            lambda *_args: (_ for _ in ()).throw(
                AssertionError("invariant check should be skipped for seed")
            ),
        )

        def fail_validate_ticket_prose(*_args, **_kwargs):
            raise AssertionError("ticket prose validator should be skipped for seed")

        mock_module = type(
            "MockModule",
            (),
            {"validate_ticket_prose": staticmethod(fail_validate_ticket_prose)},
        )()
        monkeypatch.setitem(sys.modules, "scripts.validate_ticket_prose", mock_module)

        from io import StringIO

        captured = StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            exit_code = agent_controller._handle_validate(json_output=True)
        finally:
            sys.stdout = old_stdout

        assert exit_code == 0
        output = captured.getvalue()
        assert '"warnings": {}' in output

    def test_validate_graceful_degrade_without_validator(self, tmp_path, monkeypatch):
        """_handle_validate works even if validator not available."""
        # Mock the validate_ticket_prose import to raise ImportError
        import sys
        from types import ModuleType

        # Create a mock module that raises ImportError when validate_ticket_prose is accessed
        def mock_validate(*args, **kwargs):
            raise ImportError("Validator not available")

        mock_module = ModuleType("scripts.validate_ticket_prose")
        mock_module.validate_ticket_prose = mock_validate
        monkeypatch.setitem(sys.modules, "scripts.validate_ticket_prose", mock_module)

        # Mock file reads
        monkeypatch.setattr(
            agent_controller,
            "read_file",
            lambda x: "# Plan\n\n## Metadata\n- **ID:** TEST\n- **Estado:** APPROVED\n",
        )
        monkeypatch.setattr(agent_controller, "validate_state_files", lambda: {})
        monkeypatch.setattr(
            agent_controller, "_collect_deliverable_type_warnings", lambda x: {}
        )
        monkeypatch.setattr(agent_controller, "get_status", lambda x, y: "APPROVED")
        monkeypatch.setattr(
            agent_controller, "_check_scope_for_validate", lambda x, y: ([], [])
        )
        monkeypatch.setattr(agent_controller, "_check_bus_drift", lambda x, y: [])
        monkeypatch.setattr(
            agent_controller,
            "_check_invariants",
            lambda x, y, z: {"errors": [], "warnings": []},
        )

        from io import StringIO

        captured = StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured

        try:
            exit_code = agent_controller._handle_validate(json_output=True)
        finally:
            sys.stdout = old_stdout

        # Should still work and return 0
        assert exit_code == 0


class TestSessionClose:
    """WP-2026-169: Test --session-close handler delegation and idempotency."""

    def test_session_close_already_completed(self, monkeypatch):
        """When STATE.md already COMPLETED and no --force, exit 0 silently."""

        def mock_read(path):
            return "Estado actual: COMPLETED\n"

        monkeypatch.setattr(agent_controller, "read_file", mock_read)

        code = agent_controller._handle_session_close(
            dry_run=False,
            skip_slow=False,
            ticket=None,
            tickets=None,
            force_mode=False,
            json_output=False,
        )
        assert code == 0

    def test_session_close_dry_run(self, monkeypatch, tmp_path):
        """--dry-run delegates and returns exit code without syncing state."""
        # Create mock scripts/session_closeout.py in temp dir
        script_dir = tmp_path / "scripts"
        script_dir.mkdir()
        (script_dir / "session_closeout.py").write_text("")
        monkeypatch.setattr(agent_controller, "PROJECT_ROOT", tmp_path)

        mock_run = MagicMock(
            return_value=MagicMock(returncode=0, stdout="[DRY-RUN] ok\n", stderr="")
        )
        monkeypatch.setattr(agent_controller.subprocess, "run", mock_run)

        def mock_read(path):
            return "Estado actual: IN_PROGRESS\n"

        monkeypatch.setattr(agent_controller, "read_file", mock_read)

        code = agent_controller._handle_session_close(
            dry_run=True,
            skip_slow=False,
            ticket=None,
            tickets=None,
            force_mode=False,
            json_output=False,
        )
        assert code == 0
        # Verify subprocess received --dry-run flag
        assert mock_run.called
        args = mock_run.call_args[0][0]
        assert "--dry-run" in args

    def test_session_close_uses_motor_script_for_external_motor_topology(
        self, monkeypatch, tmp_path
    ):
        """External-motor topology executes the motor-owned script with destination cwd."""
        motor_root = tmp_path / "motor"
        destination_root = tmp_path / "destination"
        script_dir = motor_root / "scripts"
        script_dir.mkdir(parents=True)
        destination_root.mkdir()
        script_path = script_dir / "session_closeout.py"
        script_path.write_text("", encoding="utf-8")

        monkeypatch.setattr(agent_controller, "_MOTOR_ROOT", motor_root)
        monkeypatch.setattr(agent_controller, "PROJECT_ROOT", destination_root)
        monkeypatch.setattr(
            agent_controller,
            "read_file",
            lambda path: "Estado actual: IN_PROGRESS\n",
        )
        mock_run = MagicMock(
            return_value=MagicMock(returncode=0, stdout="[DRY-RUN] ok\n", stderr="")
        )
        monkeypatch.setattr(agent_controller.subprocess, "run", mock_run)

        code = agent_controller._handle_session_close(
            dry_run=True,
            skip_slow=False,
            ticket=None,
            tickets=None,
            force_mode=True,
            json_output=False,
        )

        assert code == 0
        assert mock_run.call_args[0][0][1] == str(script_path)
        assert mock_run.call_args.kwargs["cwd"] == destination_root

    def test_session_close_dry_run_passes_ticket(self, monkeypatch, tmp_path):
        """--session-close --dry-run --ticket WP-2026-168 passes the flag."""
        # Create mock scripts/session_closeout.py in temp dir
        script_dir = tmp_path / "scripts"
        script_dir.mkdir()
        (script_dir / "session_closeout.py").write_text("")
        monkeypatch.setattr(agent_controller, "PROJECT_ROOT", tmp_path)

        mock_run = MagicMock(
            return_value=MagicMock(returncode=0, stdout="[DRY-RUN] ok\n", stderr="")
        )
        monkeypatch.setattr(agent_controller.subprocess, "run", mock_run)

        def mock_read(path):
            return "Estado actual: IN_PROGRESS\n"

        monkeypatch.setattr(agent_controller, "read_file", mock_read)

        code = agent_controller._handle_session_close(
            dry_run=True,
            skip_slow=False,
            ticket="WP-2026-168",
            tickets=None,
            force_mode=False,
            json_output=False,
        )
        assert code == 0
        args = mock_run.call_args[0][0]
        assert "--ticket" in args
        assert "WP-2026-168" in args

    def test_session_close_real_syncs_state(self, monkeypatch, tmp_path):
        """Real close delegates and syncs STATE.md to COMPLETED."""
        # Create mock scripts/session_closeout.py in temp dir
        script_dir = tmp_path / "scripts"
        script_dir.mkdir()
        (script_dir / "session_closeout.py").write_text("")
        monkeypatch.setattr(agent_controller, "PROJECT_ROOT", tmp_path)

        written = {}

        def mock_write(path, content):
            written[str(path)] = content

        def mock_read(path):
            return "# State\nEstado actual: IN_PROGRESS\n"

        monkeypatch.setattr(agent_controller, "write_file", mock_write)
        monkeypatch.setattr(agent_controller, "read_file", mock_read)

        mock_run = MagicMock(
            return_value=MagicMock(
                returncode=0, stdout="[OK] Session close completed\n", stderr=""
            )
        )
        monkeypatch.setattr(agent_controller.subprocess, "run", mock_run)

        code = agent_controller._handle_session_close(
            dry_run=False,
            skip_slow=False,
            ticket=None,
            tickets=None,
            force_mode=False,
            json_output=False,
        )
        assert code == 0
        # Verify STATE.md was synced to COMPLETED
        assert any("COMPLETED" in v for v in written.values())

    def test_session_close_force_overrides_idempotency(self, monkeypatch, tmp_path):
        """--force overrides already-completed guard and runs session close."""
        # Create mock scripts/session_closeout.py in temp dir
        script_dir = tmp_path / "scripts"
        script_dir.mkdir()
        (script_dir / "session_closeout.py").write_text("")
        monkeypatch.setattr(agent_controller, "PROJECT_ROOT", tmp_path)

        written = {}

        def mock_write(path, content):
            written[str(path)] = content

        def mock_read(path):
            return "Estado actual: COMPLETED\n"

        monkeypatch.setattr(agent_controller, "write_file", mock_write)
        monkeypatch.setattr(agent_controller, "read_file", mock_read)

        mock_run = MagicMock(
            return_value=MagicMock(
                returncode=0, stdout="[OK] Session close completed\n", stderr=""
            )
        )
        monkeypatch.setattr(agent_controller.subprocess, "run", mock_run)

        code = agent_controller._handle_session_close(
            dry_run=False,
            skip_slow=False,
            ticket=None,
            tickets=None,
            force_mode=True,
            json_output=False,
        )
        assert code == 0
        assert mock_run.called

    def test_session_close_script_not_found(self, monkeypatch):
        """When session_closeout.py is missing, exit with error."""
        nonexistent_root = Path("/nonexistent")
        monkeypatch.setattr(
            agent_controller,
            "PROJECT_ROOT",
            nonexistent_root,
        )
        monkeypatch.setattr(agent_controller, "_MOTOR_ROOT", nonexistent_root)

        def mock_read(path):
            return "Estado actual: IN_PROGRESS\n"

        monkeypatch.setattr(agent_controller, "read_file", mock_read)

        code = agent_controller._handle_session_close(
            dry_run=False,
            skip_slow=False,
            ticket=None,
            tickets=None,
            force_mode=False,
            json_output=False,
        )
        assert code == 1


class TestPreHandoff:
    """WP-2026-173: --pre-handoff helper to stage commit and checkpoint.

    Test suite covers at least five cases:
    - happy path: commit + tag + clean tree
    - idempotent: no changes + tag already aligned
    - tag-only: no changes but tag missing → create tag without commit
    - hook failure: pre-commit hook fails → stderr propagated
    - dirty tree: tree still dirty after ops → error
    """

    _PLAN_ID = "WP-2026-173"
    _PLAN_CONTENT = f"""# Work Plan

## Metadata
- **ID:** {_PLAN_ID}
- **Estado:** APPROVED

## Files Likely Touched
- src/file1.py
- src/file2.py
"""

    @staticmethod
    def _make_git_mock(overrides=None):
        """Create a subprocess.run mock for git commands.

        Args:
            overrides: dict of pattern -> (returncode, stdout, stderr)
                       to override specific command responses.
        """
        default_overrides = {
            "git show HEAD:.opencode/opencode.json": (1, b"", b""),
            **(overrides or {}),
        }

        def mock_run(cmd, *args, **kwargs):
            cmd_str = " ".join(cmd)

            # Check overrides first
            for pattern, result in default_overrides.items():
                if pattern in cmd_str:
                    rc, out, err = result
                    return MagicMock(returncode=rc, stdout=out, stderr=err)

            # Default handlers
            if "rev-parse" in cmd_str and "checkpoint" in cmd_str and "^{}" in cmd_str:
                return MagicMock(returncode=1, stdout="", stderr="")
            if "rev-parse HEAD" in cmd_str:
                return MagicMock(returncode=0, stdout="abc123\n", stderr="")
            if len(cmd) >= 2 and cmd[:2] == ["git", "add"]:
                return MagicMock(returncode=0, stdout="", stderr="")
            if len(cmd) >= 2 and cmd[:2] == ["git", "commit"]:
                return MagicMock(
                    returncode=0, stdout="[main abc123] commit\n", stderr=""
                )
            if len(cmd) >= 3 and cmd[1] == "tag" and cmd[2] in ("-a", "-d"):
                return MagicMock(returncode=0, stdout="", stderr="")
            if len(cmd) >= 2 and cmd[:2] == ["git", "status"]:
                return MagicMock(returncode=0, stdout="", stderr="")

            return MagicMock(returncode=0, stdout="", stderr="")

        return mock_run

    def _setup_basic_mocks(self, monkeypatch, changed_files, whitelist_files):
        """Set up common mocks for pre_handoff tests.

        Args:
            monkeypatch: pytest monkeypatch fixture.
            changed_files: set of absolute paths for get_changed_files.
            whitelist_files: set of absolute paths for parse_files_likely_touched.
        """
        monkeypatch.setattr(
            agent_controller,
            "read_file",
            lambda x: self._PLAN_CONTENT if "work_plan" in str(x).lower() else "",
        )
        monkeypatch.setattr(
            agent_controller,
            "parse_files_likely_touched",
            lambda x: whitelist_files,
        )
        monkeypatch.setattr(
            agent_controller,
            "get_changed_files",
            lambda: changed_files,
        )
        # motor_checkpoint.assert_work_plan_committed calls
        # scope_gate.get_changed_files directly (not agent_controller's
        # wrapper), and scope_gate.get_changed_files's run_fn=subprocess.run
        # default is bound at import time, so patching agent_controller.subprocess
        # or agent_controller.get_changed_files above does not reach it. Patch
        # the module-level seam directly so pre-handoff never shells out to
        # real git for the work_plan.md commit check (see
        # tests/unit/test_motor_checkpoint.py::test_delegates_to_scope_gate_not_new_git_parser
        # for the canonical precedent of this pattern).
        monkeypatch.setattr(
            motor_checkpoint.scope_gate,
            "get_changed_files",
            lambda *, project_root, motor_root, run_fn=None: changed_files,
        )
        # Ensure .git exists for pre_handoff git directory check
        project_root = agent_controller.PROJECT_ROOT.resolve()
        git_path = project_root / ".git"
        original_exists = Path.exists

        def _patched_exists(self_path):
            if str(self_path) == str(git_path):
                return True
            return original_exists(self_path)

        monkeypatch.setattr(Path, "exists", _patched_exists)

    def _capture_output(self, func):
        """Run func capturing stdout+stderr, return (exit_code, combined_text)."""
        from io import StringIO

        captured_out = StringIO()
        captured_err = StringIO()
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = captured_out
        sys.stderr = captured_err
        try:
            code = func()
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
        combined = captured_out.getvalue() + captured_err.getvalue()
        return code, combined

    def test_happy_path_commit_tag_clean(self, monkeypatch):
        """Happy path: commit + tag + clean tree → exit 0."""
        project_root = agent_controller.PROJECT_ROOT.resolve()
        file1 = str(project_root / "src" / "file1.py")
        file2 = str(project_root / "src" / "file2.py")
        whitelist = {file1, file2}

        self._setup_basic_mocks(monkeypatch, whitelist, whitelist)

        git_mock = self._make_git_mock()
        monkeypatch.setattr(agent_controller.subprocess, "run", git_mock)

        code, output = self._capture_output(
            lambda: agent_controller._handle_pre_handoff(json_output=False)
        )

        assert code == 0, f"Expected 0, got {code}. Output: {output}"
        assert "Pre-handoff complete" in output

    def test_happy_path_resets_circuit_breaker(self, monkeypatch, tmp_path):
        """Successful pre-handoff should clear an OPEN circuit breaker."""
        project_root = agent_controller.PROJECT_ROOT.resolve()
        file1 = str(project_root / "src" / "file1.py")
        file2 = str(project_root / "src" / "file2.py")
        whitelist = {file1, file2}

        self._setup_basic_mocks(monkeypatch, whitelist, whitelist)

        git_mock = self._make_git_mock()
        monkeypatch.setattr(agent_controller.subprocess, "run", git_mock)

        breaker_path = tmp_path / "runtime" / "circuit_breaker.json"
        breaker_path.parent.mkdir(parents=True, exist_ok=True)
        breaker_path.write_text(
            json.dumps(
                {
                    "state": "OPEN",
                    "failures": 4,
                    "no_progress_count": 2,
                    "reason": "previous handoff block",
                }
            ),
            encoding="utf-8",
        )

        monkeypatch.setattr(agent_controller, "CIRCUIT_BREAKER_PATH", breaker_path)

        code, output = self._capture_output(
            lambda: agent_controller._handle_pre_handoff(json_output=False)
        )

        assert code == 0, f"Expected 0, got {code}. Output: {output}"
        breaker = agent_controller._read_circuit_breaker()
        assert breaker["state"] == "CLOSED"
        assert breaker["failures"] == 0
        assert breaker["no_progress_count"] == 0

    def test_idempotent_no_changes_tag_aligned(self, monkeypatch):
        """No changes + tag aligned → idempotent exit 0."""
        self._setup_basic_mocks(monkeypatch, set(), set())

        # Override: tag exists and aligns with HEAD
        def git_mock(cmd, *args, **kwargs):
            cmd_str = " ".join(cmd)
            if "git show HEAD:.opencode/opencode.json" in cmd_str:
                return MagicMock(returncode=1, stdout=b"", stderr=b"")
            if "rev-parse" in cmd_str and "checkpoint" in cmd_str and "^{}" in cmd_str:
                return MagicMock(returncode=0, stdout="abc123\n", stderr="")
            if "rev-parse HEAD" in cmd_str:
                return MagicMock(returncode=0, stdout="abc123\n", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(agent_controller.subprocess, "run", git_mock)

        code, output = self._capture_output(
            lambda: agent_controller._handle_pre_handoff(json_output=False)
        )

        assert code == 0, f"Expected 0, got {code}. Output: {output}"
        assert "already aligned" in output

    def test_no_changes_tag_missing_create_only(self, monkeypatch):
        """No changes + tag missing → create tag without commit."""
        self._setup_basic_mocks(monkeypatch, set(), set())

        tag_created = [False]

        def git_mock(cmd, *args, **kwargs):
            cmd_str = " ".join(cmd)
            if "git show HEAD:.opencode/opencode.json" in cmd_str:
                return MagicMock(returncode=1, stdout=b"", stderr=b"")
            if "rev-parse" in cmd_str and "checkpoint" in cmd_str and "^{}" in cmd_str:
                return MagicMock(returncode=1, stdout="", stderr="")
            if len(cmd) >= 2 and cmd[1] == "tag" and cmd[2] == "-a":
                tag_created[0] = True
                return MagicMock(returncode=0, stdout="", stderr="")
            if len(cmd) >= 2 and cmd[:2] == ["git", "status"]:
                return MagicMock(returncode=0, stdout="", stderr="")
            if "rev-parse HEAD" in cmd_str:
                return MagicMock(returncode=0, stdout="abc123\n", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(agent_controller.subprocess, "run", git_mock)

        code, output = self._capture_output(
            lambda: agent_controller._handle_pre_handoff(json_output=False)
        )

        assert code == 0, f"Expected 0, got {code}. Output: {output}"
        assert tag_created[0], "Tag was not created"
        assert "Created/refreshed tag" in output

    def test_no_changes_tag_misaligned_delete_then_recreate(self, monkeypatch):
        """No changes + existing misaligned tag → delete then recreate."""
        self._setup_basic_mocks(monkeypatch, set(), set())

        calls = []

        def git_mock(cmd, *args, **kwargs):
            cmd_str = " ".join(cmd)
            calls.append(cmd_str)
            if "git show HEAD:.opencode/opencode.json" in cmd_str:
                return MagicMock(returncode=1, stdout=b"", stderr=b"")
            if "rev-parse" in cmd_str and "checkpoint" in cmd_str and "^{}" in cmd_str:
                return MagicMock(returncode=0, stdout="oldsha\n", stderr="")
            if "rev-parse HEAD" in cmd_str:
                return MagicMock(returncode=0, stdout="newsha\n", stderr="")
            if len(cmd) >= 3 and cmd[:3] == ["git", "tag", "-d"]:
                return MagicMock(returncode=0, stdout="Deleted tag\n", stderr="")
            if len(cmd) >= 3 and cmd[:3] == ["git", "tag", "-a"]:
                return MagicMock(returncode=0, stdout="", stderr="")
            if len(cmd) >= 2 and cmd[:2] == ["git", "status"]:
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(agent_controller.subprocess, "run", git_mock)

        code, output = self._capture_output(
            lambda: agent_controller._handle_pre_handoff(json_output=False)
        )

        assert code == 0, f"Expected 0, got {code}. Output: {output}"
        assert any("git tag -d checkpoint/review-WP-2026-173" in c for c in calls), (
            output
        )
        assert any("git tag -a checkpoint/review-WP-2026-173" in c for c in calls), (
            output
        )
        assert next(i for i, c in enumerate(calls) if "git tag -d" in c) < next(
            i for i, c in enumerate(calls) if "git tag -a" in c
        ), output
        assert "Created/refreshed tag" in output

    def test_hook_failure_propagates_stderr(self, monkeypatch):
        """Pre-commit hook failure → stderr propagated, exit != 0."""
        project_root = agent_controller.PROJECT_ROOT.resolve()
        file1 = str(project_root / "src" / "file1.py")
        whitelist = {file1}
        fake_stderr = (
            "pre-commit hook failed\nAborting commit due to pre-commit hook.\n"
        )

        self._setup_basic_mocks(monkeypatch, whitelist, whitelist)

        def git_mock(cmd, *args, **kwargs):
            cmd_str = " ".join(cmd)
            if "git show HEAD:.opencode/opencode.json" in cmd_str:
                return MagicMock(returncode=1, stdout=b"", stderr=b"")
            if "rev-parse" in cmd_str and "checkpoint" in cmd_str and "^{}" in cmd_str:
                return MagicMock(returncode=1, stdout="", stderr="")
            if len(cmd) >= 2 and cmd[:2] == ["git", "add"]:
                return MagicMock(returncode=0, stdout="", stderr="")
            if len(cmd) >= 2 and cmd[:2] == ["git", "commit"]:
                return MagicMock(returncode=1, stdout="", stderr=fake_stderr)
            return MagicMock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(agent_controller.subprocess, "run", git_mock)

        code, output = self._capture_output(
            lambda: agent_controller._handle_pre_handoff(json_output=False)
        )

        assert code != 0, f"Expected non-zero, got {code}. Output: {output}"
        assert "pre-commit hook failed" in output, f"Missing error in output: {output}"

    def test_dirty_tree_after_ops(self, monkeypatch):
        """Dirty tree after commit + tag → error exit 1."""
        project_root = agent_controller.PROJECT_ROOT.resolve()
        file1 = str(project_root / "src" / "file1.py")
        whitelist = {file1}

        self._setup_basic_mocks(monkeypatch, whitelist, whitelist)

        # Override status to report a dirty file
        def git_mock(cmd, *args, **kwargs):
            cmd_str = " ".join(cmd)
            if "git show HEAD:.opencode/opencode.json" in cmd_str:
                return MagicMock(returncode=1, stdout=b"", stderr=b"")
            if "rev-parse" in cmd_str and "checkpoint" in cmd_str and "^{}" in cmd_str:
                return MagicMock(returncode=1, stdout="", stderr="")
            if len(cmd) >= 2 and cmd[:2] == ["git", "add"]:
                return MagicMock(returncode=0, stdout="", stderr="")
            if len(cmd) >= 2 and cmd[:2] == ["git", "commit"]:
                return MagicMock(
                    returncode=0, stdout="[main abc123] commit\n", stderr=""
                )
            if len(cmd) >= 3 and cmd[1] == "tag" and cmd[2] == "-a":
                return MagicMock(returncode=0, stdout="", stderr="")
            if len(cmd) >= 2 and cmd[:2] == ["git", "status"]:
                # Simulate an untracked non-live file
                return MagicMock(
                    returncode=0,
                    stdout="?? untracked_output.txt\n",
                    stderr="",
                )
            return MagicMock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(agent_controller.subprocess, "run", git_mock)

        code, output = self._capture_output(
            lambda: agent_controller._handle_pre_handoff(json_output=False)
        )

        assert code != 0, f"Expected non-zero, got {code}. Output: {output}"
        assert "Tree still dirty" in output

    def test_pre_handoff_blocks_stale_builder_round(self, monkeypatch):
        """A stale Builder shell must not create checkpoint or commit new work."""
        monkeypatch.setattr(
            agent_controller,
            "read_file",
            lambda x: self._PLAN_CONTENT if "work_plan" in str(x).lower() else "",
        )
        monkeypatch.setattr(
            agent_controller,
            "_ensure_active_builder_round",
            lambda plan_id: (False, 3, "stale Builder round 3; active round is 4"),
        )
        monkeypatch.setattr(agent_controller, "BUS_AVAILABLE", True)
        emit_mock = MagicMock()
        monkeypatch.setattr(agent_controller, "event_bus", MagicMock(emit=emit_mock))

        code, output = self._capture_output(
            lambda: agent_controller._handle_pre_handoff(json_output=False)
        )

        assert code == 1, f"Expected 1, got {code}. Output: {output}"
        assert "stale Builder shell" in output
        assert emit_mock.call_count == 1
        assert emit_mock.call_args.kwargs["event_type"] == "HANDOFF_BLOCKED"

    @pytest.mark.parametrize(
        ("event_dict", "active_round"),
        [
            (
                {
                    "event_type": "STATE_CHANGED",
                    "payload": {"to_state": "READY_FOR_REVIEW"},
                },
                4,
            ),
            (
                {
                    "event_type": "STATE_CHANGED",
                    "payload": {"to_state": "READY_TO_CLOSE"},
                },
                5,
            ),
            (
                {
                    "event_type": "REVIEW_DECISION",
                    "payload": {"decision": "inspect"},
                },
                3,
            ),
            (
                {
                    "event_type": "STATE_CHANGED",
                    "payload": {"to_state": "COMPLETED"},
                },
                2,
            ),
        ],
    )
    def test_pre_handoff_orphan_for_post_success_states(
        self, monkeypatch, event_dict, active_round
    ):
        """Stale Builder shell on post-success states must emit STALE_BUILDER_ORPHAN and exit 0."""
        monkeypatch.setattr(
            agent_controller,
            "read_file",
            lambda x: self._PLAN_CONTENT if "work_plan" in str(x).lower() else "",
        )
        monkeypatch.setattr(
            agent_controller,
            "_ensure_active_builder_round",
            lambda plan_id: (
                False,
                active_round - 1,
                f"stale Builder round {active_round - 1}; active round is {active_round}",
            ),
        )
        monkeypatch.setattr(agent_controller, "BUS_AVAILABLE", True)
        emit_mock = MagicMock()
        monkeypatch.setattr(agent_controller, "event_bus", MagicMock(emit=emit_mock))

        mock_event = MagicMock()
        mock_event.to_dict.return_value = event_dict
        agent_controller.event_bus.read_events.return_value = [mock_event]

        code, output = self._capture_output(
            lambda: agent_controller._handle_pre_handoff(json_output=False)
        )

        assert code == 0, f"Expected 0, got {code}. Output: {output}"
        orphan_events = [
            call
            for call in emit_mock.call_args_list
            if call.kwargs.get("event_type") == "STALE_BUILDER_ORPHAN"
        ]
        assert orphan_events, "post-success stale must emit STALE_BUILDER_ORPHAN"
        handoff_events = [
            call
            for call in emit_mock.call_args_list
            if call.kwargs.get("event_type") == "HANDOFF_BLOCKED"
        ]
        assert not handoff_events, "must NOT emit HANDOFF_BLOCKED for orphan"

    def test_pre_handoff_stays_blocking_when_bus_state_unknown(self, monkeypatch):
        """Unknown bus state must keep the original stale Builder block."""
        monkeypatch.setattr(
            agent_controller,
            "read_file",
            lambda x: self._PLAN_CONTENT if "work_plan" in str(x).lower() else "",
        )
        monkeypatch.setattr(
            agent_controller,
            "_ensure_active_builder_round",
            lambda plan_id: (False, 1, "stale Builder round 1; active round is 2"),
        )
        monkeypatch.setattr(agent_controller, "BUS_AVAILABLE", True)
        emit_mock = MagicMock()
        monkeypatch.setattr(agent_controller, "event_bus", MagicMock(emit=emit_mock))
        agent_controller.event_bus.read_events.return_value = []

        code, output = self._capture_output(
            lambda: agent_controller._handle_pre_handoff(json_output=False)
        )

        assert code == 1, f"Expected 1, got {code}. Output: {output}"
        handoff_events = [
            call
            for call in emit_mock.call_args_list
            if call.kwargs.get("event_type") == "HANDOFF_BLOCKED"
        ]
        assert handoff_events, "unknown bus state must keep HANDOFF_BLOCKED"
        orphan_events = [
            call
            for call in emit_mock.call_args_list
            if call.kwargs.get("event_type") == "STALE_BUILDER_ORPHAN"
        ]
        assert not orphan_events


# =============================================================================
# Tests WP-2026-176: Motor code-only guard
# =============================================================================


class TestMotorCodeOnlyGuard:
    """Tests for motor code-only guard blocking write operations."""

    def test_is_motor_code_only_true(self, monkeypatch):
        """is_motor_code_only returns True when no AGENT_PROJECT_ROOT and marker exists."""
        monkeypatch.delenv("AGENT_PROJECT_ROOT", raising=False)

        from runtime.project_root import is_motor_code_only

        # The actual motor repo has agent_controller.py, so this should be True
        # when run from the motor repo and AGENT_PROJECT_ROOT is not set
        result = is_motor_code_only()
        # Note: In test context, this may be False if tests run with AGENT_PROJECT_ROOT
        # or if the test filesystem differs. The marker check is reliable.
        from runtime.project_root import resolve_project_root

        marker = resolve_project_root() / ".agent" / "agent_controller.py"
        expected = marker.exists()
        assert result == expected

    def test_is_motor_code_only_false_with_env(self, monkeypatch, tmp_path):
        """is_motor_code_only returns False when AGENT_PROJECT_ROOT points to an external workspace.

        Uses a real existing external path (tmp_path) because the guard is
        fail-closed for non-existent paths: a non-existent AGENT_PROJECT_ROOT
        returns True, not False.
        """
        monkeypatch.setenv("AGENT_PROJECT_ROOT", str(tmp_path))

        from runtime.project_root import is_motor_code_only

        result = is_motor_code_only()
        assert result is False

    def test_is_motor_code_only_true_when_env_points_to_motor(self, monkeypatch):
        """is_motor_code_only returns True when AGENT_PROJECT_ROOT points to the motor itself.

        Regression guard for the --project-root . from-motor contamination
        bug (WOT-2026-020d): before the fix, any non-empty AGENT_PROJECT_ROOT
        returned False, so --bootstrap-ticket/--mark-ready could write into
        the motor's own .agent/collaboration/ and commit per-ticket artifacts.
        """
        import runtime.project_root as project_root_module

        motor_root = Path(project_root_module.__file__).resolve().parent.parent
        monkeypatch.setenv("AGENT_PROJECT_ROOT", str(motor_root))

        from runtime.project_root import is_motor_code_only

        result = is_motor_code_only()
        assert result is True

    def test_is_motor_code_only_true_when_env_path_nonexistent(self, monkeypatch):
        """is_motor_code_only returns True (fail-closed) for a non-existent env path."""
        monkeypatch.setenv(
            "AGENT_PROJECT_ROOT",
            str(Path("/tmp/definitely_not_a_real_workspace_zzz").resolve()),
        )

        from runtime.project_root import is_motor_code_only

        result = is_motor_code_only()
        assert result is True

    def test_main_blocks_mutating_flags(self, monkeypatch):
        """Motor code-only guard blocks --mark-ready when no AGENT_PROJECT_ROOT."""
        monkeypatch.delenv("AGENT_PROJECT_ROOT", raising=False)
        monkeypatch.setattr(agent_controller, "is_motor_code_only", lambda: True)

        # Simulate argv with --mark-ready
        test_argv = ["agent_controller.py", "--mark-ready", "--json"]
        monkeypatch.setattr(sys, "argv", test_argv)

        ensure_mock = MagicMock(
            side_effect=AssertionError("_ensure_runtime_dirs called")
        )
        bus_mock = MagicMock(side_effect=AssertionError("_get_event_bus called"))
        monkeypatch.setattr(agent_controller, "_ensure_runtime_dirs", ensure_mock)
        monkeypatch.setattr(agent_controller, "_get_event_bus", bus_mock)

        exit_code = agent_controller.main()
        assert exit_code == 1
        ensure_mock.assert_not_called()
        bus_mock.assert_not_called()

    def test_main_allows_non_mutating_flags(self, monkeypatch):
        """Motor code-only guard allows --validate even without AGENT_PROJECT_ROOT."""
        monkeypatch.delenv("AGENT_PROJECT_ROOT", raising=False)
        monkeypatch.setattr(agent_controller, "is_motor_code_only", lambda: True)

        # Simulate argv with --validate (should not be blocked)
        test_argv = ["agent_controller.py", "--validate", "--json"]
        monkeypatch.setattr(sys, "argv", test_argv)

        # Patch _ensure_runtime_dirs and _get_event_bus to be safe
        monkeypatch.setattr(agent_controller, "_ensure_runtime_dirs", lambda: None)
        monkeypatch.setattr(agent_controller, "_get_event_bus", lambda: None)

        # We need to also patch the validate handler to return 0, since it reads
        # files from the real filesystem and will fail.
        monkeypatch.setattr(agent_controller, "_handle_validate", lambda json_output: 0)

        exit_code = agent_controller.main()
        assert exit_code == 0

    def test_main_blocks_pre_handoff(self, monkeypatch):
        """Motor code-only guard blocks --pre-handoff without AGENT_PROJECT_ROOT."""
        monkeypatch.delenv("AGENT_PROJECT_ROOT", raising=False)
        monkeypatch.setattr(agent_controller, "is_motor_code_only", lambda: True)

        test_argv = ["agent_controller.py", "--pre-handoff"]
        monkeypatch.setattr(sys, "argv", test_argv)
        monkeypatch.setattr(agent_controller, "_ensure_runtime_dirs", lambda: None)
        monkeypatch.setattr(agent_controller, "_get_event_bus", lambda: None)

        exit_code = agent_controller.main()
        assert exit_code == 1

    def test_main_blocks_session_close(self, monkeypatch):
        """Motor code-only guard blocks --session-close without AGENT_PROJECT_ROOT."""
        monkeypatch.delenv("AGENT_PROJECT_ROOT", raising=False)
        monkeypatch.setattr(agent_controller, "is_motor_code_only", lambda: True)

        test_argv = ["agent_controller.py", "--session-close"]
        monkeypatch.setattr(sys, "argv", test_argv)
        monkeypatch.setattr(agent_controller, "_ensure_runtime_dirs", lambda: None)
        monkeypatch.setattr(agent_controller, "_get_event_bus", lambda: None)

        exit_code = agent_controller.main()
        assert exit_code == 1


# ======================================================================
# WT-2026-181: Dual WP-/WT- prefix regression tests
# ======================================================================


class TestDualPrefixParsing:
    """Verify parsers accept both WP- and WT- prefixes identically."""

    def test_get_plan_id_extracts_wp(self):
        """get_plan_id() extracts WP-2026-XXX correctly."""
        content = "# Work Plan\n- **ID:** WP-2026-100\n- **Estado:** APPROVED\n"
        assert agent_controller.get_plan_id(content) == "WP-2026-100"

    def test_get_plan_id_extracts_wt(self):
        """get_plan_id() extracts WT-2026-XXX correctly."""
        content = "# Work Plan\n- **ID:** WT-2026-100\n- **Estado:** APPROVED\n"
        assert agent_controller.get_plan_id(content) == "WT-2026-100"

    def test_get_plan_id_extracts_wp_from_plan_id_label(self):
        """get_plan_id() handles **Plan ID:** label with WP- prefix."""
        content = "# Work Plan\n- **Plan ID:** WP-2026-100\n"
        assert agent_controller.get_plan_id(content) == "WP-2026-100"

    def test_get_plan_id_extracts_wt_from_plan_id_label(self):
        """get_plan_id() handles **Plan ID:** label with WT- prefix."""
        content = "# Work Plan\n- **Plan ID:** WT-2026-100\n"
        assert agent_controller.get_plan_id(content) == "WT-2026-100"

    def test_get_plan_id_returns_na_for_missing(self):
        """get_plan_id() returns N/A when no ID is present."""
        content = "# Work Plan\n- **Estado:** PENDING\n"
        assert agent_controller.get_plan_id(content) == "N/A"

    def test_validation_accepts_wp_ticket_in_work_plan(self, monkeypatch):
        """get_plan_id() extracts WP- from work_plan content and returns dict result."""
        wp_content = "# Work Plan\n- **ID:** WP-2026-100\n- **Estado:** APPROVED\n- **deliverable_type:** code\n"
        plan_id = agent_controller.get_plan_id(wp_content)
        assert plan_id == "WP-2026-100"

    def test_validation_accepts_wt_ticket_in_work_plan(self, monkeypatch):
        """get_plan_id() extracts WT- from work_plan content."""
        wp_content = "# Work Plan\n- **ID:** WT-2026-100\n- **Estado:** APPROVED\n- **deliverable_type:** code\n"
        plan_id = agent_controller.get_plan_id(wp_content)
        assert plan_id == "WT-2026-100"


# ======================================================================
# WT-2026-188: Closeout commit validation and state cleanup tests
# ======================================================================


class TestCloseoutCommitValidation:
    """WT-2026-188: Validate closeout commit message.

    Tests the pure _validate_closeout_commit_message() helper.
    """

    _ACTIVE_ID = "WT-2026-188"

    def test_manager_approve_rejects_generic_checkpoint_commit_message(self):
        """Checkpoint with correct ID is rejected (generic pre-handoff)."""
        valid, reason = agent_controller._validate_closeout_commit_message(
            "chore(WT-2026-188): pre-handoff checkpoint", self._ACTIVE_ID
        )
        assert not valid
        # The commit contains both "pre-handoff" and "checkpoint"; either may
        # be reported first depending on iteration order
        assert any(kw in reason.lower() for kw in ("checkpoint", "pre-handoff"))

    def test_manager_approve_rejects_commit_message_with_wrong_ticket_id(self):
        """Message referencing a valid but different ticket ID is rejected."""
        valid, reason = agent_controller._validate_closeout_commit_message(
            "feat(WT-2026-187): improve closeout validation", self._ACTIVE_ID
        )
        assert not valid, f"Expected invalid, got reason: {reason}"
        # Must detect that WT-2026-187 != WT-2026-188
        assert "WT-2026-187" in reason

    def test_manager_approve_rejects_commit_message_without_ticket_id(self):
        """Message without any ticket ID is rejected."""
        valid, _reason = agent_controller._validate_closeout_commit_message(
            "fix: minor cleanup", self._ACTIVE_ID
        )
        assert not valid

    def test_manager_approve_accepts_commit_message_with_active_ticket_id(self):
        """Message with correct ID and descriptive content is accepted."""
        valid, reason = agent_controller._validate_closeout_commit_message(
            "feat(WT-2026-188): validate canonical closeout commit hygiene",
            self._ACTIVE_ID,
        )
        assert valid, f"Expected valid, got: {reason}"

    def test_manager_approve_accepts_canonical_closeout_message_with_active_ticket_id(
        self,
    ):
        """Canonical format 'TICKET-ID: msg' (no Conventional Commits) is accepted."""
        valid, reason = agent_controller._validate_closeout_commit_message(
            "WT-2026-188: canonical closeout", self._ACTIVE_ID
        )
        assert valid, f"Expected valid, got: {reason}"

    def test_manager_approve_accepts_commit_message_with_alphanumeric_suffix(self):
        """Canonical parser must preserve ticket suffixes like WT-2026-248a."""
        active_id = "WT-2026-248a"
        valid, reason = agent_controller._validate_closeout_commit_message(
            "fix(WT-2026-248a): preserve canonical suffix in manager approve",
            active_id,
        )
        assert valid, f"Expected valid suffix-preserving match, got: {reason}"


class TestManagerApproveStateCleanup:
    """WT-2026-188: --manager-approve clears auxiliary state files."""

    def test_manager_approve_clears_manager_bridge_state(self, tmp_path, monkeypatch):
        """manager_bridge_state.json is removed after closeout."""
        state_file = tmp_path / "manager_bridge_state.json"
        state_file.write_text('{"last_processed_sequence": 42}', encoding="utf-8")
        monkeypatch.setattr(agent_controller, "_MANAGER_BRIDGE_STATE_PATH", state_file)
        monkeypatch.setattr(
            agent_controller,
            "_SUPERVISOR_STATE_PATH",
            tmp_path / "supervisor_state.json",
        )
        assert state_file.exists()
        agent_controller._clear_auxiliary_states("WT-2026-188")
        assert not state_file.exists()

    def test_manager_approve_clears_supervisor_state(self, tmp_path, monkeypatch):
        """supervisor_state.json is removed after closeout."""
        state_file = tmp_path / "supervisor_state.json"
        state_file.write_text('{"active_ticket": "WT-2026-188"}', encoding="utf-8")
        monkeypatch.setattr(agent_controller, "_SUPERVISOR_STATE_PATH", state_file)
        monkeypatch.setattr(
            agent_controller,
            "_MANAGER_BRIDGE_STATE_PATH",
            tmp_path / "manager_bridge_state.json",
        )
        assert state_file.exists()
        agent_controller._clear_auxiliary_states("WT-2026-188")
        assert not state_file.exists()

    def test_clear_does_not_fail_on_missing(self, tmp_path, monkeypatch):
        """Clearing non-existent state files is a no-op (no exception)."""
        monkeypatch.setattr(
            agent_controller,
            "_MANAGER_BRIDGE_STATE_PATH",
            tmp_path / "nonexistent_mgr.json",
        )
        monkeypatch.setattr(
            agent_controller,
            "_SUPERVISOR_STATE_PATH",
            tmp_path / "nonexistent_sup.json",
        )
        # Should not raise even if files don't exist
        agent_controller._clear_auxiliary_states("WT-2026-188")

    def test_clear_removes_both_files(self, tmp_path, monkeypatch):
        """Both auxiliary state files are removed by a single call."""
        mgr = tmp_path / "manager_bridge_state.json"
        sup = tmp_path / "supervisor_state.json"
        mgr.write_text("{}", encoding="utf-8")
        sup.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(agent_controller, "_MANAGER_BRIDGE_STATE_PATH", mgr)
        monkeypatch.setattr(agent_controller, "_SUPERVISOR_STATE_PATH", sup)

        agent_controller._clear_auxiliary_states("WT-2026-188")

        assert not mgr.exists()
        assert not sup.exists()

    def test_closeout_updates_compact_state_projection(self, monkeypatch):
        """Compact ACTIVE_TICKET/STATUS projections close to COMPLETED."""
        written = {}

        def fake_read(path):
            if str(path).endswith("STATE.md"):
                return "ACTIVE_TICKET: WT-2026-208\nSTATUS: READY_FOR_REVIEW\n"
            return ""

        monkeypatch.setattr(agent_controller, "read_file", fake_read)
        monkeypatch.setattr(
            agent_controller,
            "write_file",
            lambda path, content: written.__setitem__(str(path), content),
        )
        monkeypatch.setattr(agent_controller, "update_log_status", lambda *_args: True)
        monkeypatch.setattr(agent_controller, "update_turn_file", lambda *_args: None)

        agent_controller._sync_markdowns_to_completed("WT-2026-208")

        state_content = next(
            content for path, content in written.items() if path.endswith("STATE.md")
        )
        assert "ACTIVE_TICKET: WT-2026-208" in state_content
        assert "STATUS: COMPLETED" in state_content


# ======================================================================
# WT-2026-188: _handle_manager_approve integration tests
# These tests call _handle_manager_approve directly to prove the full flow,
# not just the isolated helpers.
# ======================================================================


class TestHandleManagerApproveIntegration:
    """WT-2026-188: _handle_manager_approve exercises full closeout flow.

    Proves that the handler:
    - Blocks on generic checkpoint commits
    - Blocks on wrong ticket ID in commit
    - Blocks on missing ticket ID in commit
    - Calls _clear_auxiliary_states on successful approve
    """

    _TICKET = "WT-2026-188"

    _WORK_PLAN = (
        "# Work Ticket - WT-2026-188\n"
        "## Metadata\n"
        "- **ID:** WT-2026-188\n"
        "- **Estado:** APPROVED\n"
        "- **deliverable_type:** code\n"
    )

    _EXEC_LOG_READY = "# Execution Log WT-2026-188\n\n**Estado:** READY_FOR_REVIEW\n"

    def _setup(self, monkeypatch, tmp_path, commit_msg: str):
        """Patch minimal scaffolding so _handle_manager_approve can run."""
        monkeypatch.setattr(
            agent_controller,
            "read_file",
            lambda p: (
                self._WORK_PLAN if "work_plan" in str(p) else self._EXEC_LOG_READY
            ),
        )
        monkeypatch.setattr(agent_controller, "BUS_AVAILABLE", False)
        monkeypatch.setattr(agent_controller, "event_bus", None)
        monkeypatch.setattr(
            agent_controller, "_sync_markdowns_to_completed", lambda tid: None
        )
        monkeypatch.setattr(
            agent_controller, "_reset_circuit_breaker", lambda tid: None
        )
        monkeypatch.setattr(agent_controller, "_release_builder_lock", lambda tid: None)
        monkeypatch.setattr(
            agent_controller, "_emit_manager_approve_cascade", lambda bus, tid: None
        )
        # Patch commit check to return the supplied message
        monkeypatch.setattr(
            agent_controller,
            "_check_last_commit",
            lambda root, tid: agent_controller._validate_closeout_commit_message(
                commit_msg, tid
            ),
        )
        # Wire real state files into tmp_path
        mgr = tmp_path / "manager_bridge_state.json"
        sup = tmp_path / "supervisor_state.json"
        mgr.write_text('{"seq": 1}', encoding="utf-8")
        sup.write_text('{"active_ticket": "WT-2026-188"}', encoding="utf-8")
        monkeypatch.setattr(agent_controller, "_MANAGER_BRIDGE_STATE_PATH", mgr)
        monkeypatch.setattr(agent_controller, "_SUPERVISOR_STATE_PATH", sup)
        return mgr, sup

    def test_blocks_on_generic_checkpoint_commit(self, monkeypatch, tmp_path):
        """_handle_manager_approve returns 1 for a checkpoint commit with correct ID."""
        self._setup(monkeypatch, tmp_path, "chore(WT-2026-188): pre-handoff checkpoint")
        rc = agent_controller._handle_manager_approve(self._TICKET, False, False)
        assert rc == 1, "Expected block on generic checkpoint commit"

    def test_blocks_on_wrong_ticket_id_in_commit(self, monkeypatch, tmp_path):
        """_handle_manager_approve returns 1 when commit references a different ticket."""
        self._setup(
            monkeypatch, tmp_path, "feat(WT-2026-187): improve closeout validation"
        )
        rc = agent_controller._handle_manager_approve(self._TICKET, False, False)
        assert rc == 1, "Expected block on wrong ticket ID in commit"

    def test_blocks_on_missing_ticket_id_in_commit(self, monkeypatch, tmp_path):
        """_handle_manager_approve returns 1 when commit has no ticket ID."""
        self._setup(monkeypatch, tmp_path, "fix: minor cleanup")
        rc = agent_controller._handle_manager_approve(self._TICKET, False, False)
        assert rc == 1, "Expected block on commit without ticket ID"

    def test_clears_auxiliary_states_on_approve(self, monkeypatch, tmp_path):
        """_handle_manager_approve deletes both state files on successful close."""
        mgr, sup = self._setup(
            monkeypatch,
            tmp_path,
            "feat(WT-2026-188): validate canonical closeout commit hygiene",
        )
        assert mgr.exists() and sup.exists()
        rc = agent_controller._handle_manager_approve(self._TICKET, False, False)
        assert rc == 0, f"Expected success, got rc={rc}"
        assert not mgr.exists(), "manager_bridge_state.json must be deleted on approve"
        assert not sup.exists(), "supervisor_state.json must be deleted on approve"

    def test_historical_close_does_not_block_approval_after_reopen(
        self, monkeypatch, tmp_path
    ):
        """A reopened READY_FOR_REVIEW ticket must not return already_completed."""
        from bus.event_bus import EventBus

        self._setup(
            monkeypatch,
            tmp_path,
            "feat(WT-2026-188): validate canonical closeout commit hygiene",
        )
        bus = EventBus(runtime_dir=tmp_path / "events")
        bus.emit(
            "STATE_CHANGED",
            ticket_id=self._TICKET,
            actor="SUPERVISOR",
            payload={"from_state": "READY_TO_CLOSE", "to_state": "COMPLETED"},
        )
        bus.emit(
            "SUPERVISOR_CLOSED",
            ticket_id=self._TICKET,
            actor="SUPERVISOR",
            payload={"reason": "historical close"},
        )
        bus.emit(
            "STATE_CHANGED",
            ticket_id=self._TICKET,
            actor="SUPERVISOR",
            payload={"from_state": "COMPLETED", "to_state": "IN_PROGRESS"},
            allow_reentry=True,
        )
        bus.emit(
            "STATE_CHANGED",
            ticket_id=self._TICKET,
            actor="SUPERVISOR",
            payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
        )

        cascade_calls = []
        monkeypatch.setattr(agent_controller, "BUS_AVAILABLE", True)
        monkeypatch.setattr(agent_controller, "event_bus", bus)
        monkeypatch.setattr(
            agent_controller,
            "_emit_manager_approve_cascade",
            lambda active_bus, ticket_id: cascade_calls.append((active_bus, ticket_id)),
        )

        rc = agent_controller._handle_manager_approve(self._TICKET, False, True)

        assert rc == 0
        assert cascade_calls == [(bus, self._TICKET)]


class TestHandleManagerApproveDryRun:
    """WOT-2026-020h: --manager-approve --dry-run must be a no-op on state.

    Dry-run must NOT sync markdowns to COMPLETED, clear auxiliary states, nor
    emit the closeout cascade. It only reports what it would do.
    """

    _TICKET = "WT-2026-020h"

    _WORK_PLAN = (
        "# Work Ticket - WT-2026-020h\n"
        "## Metadata\n"
        "- **ID:** WT-2026-020h\n"
        "- **Estado:** APPROVED\n"
        "- **deliverable_type:** code\n"
    )

    _EXEC_LOG_READY = "# Execution Log WT-2026-020h\n\n**Estado:** READY_FOR_REVIEW\n"

    def _setup(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            agent_controller,
            "read_file",
            lambda p: (
                self._WORK_PLAN if "work_plan" in str(p) else self._EXEC_LOG_READY
            ),
        )
        monkeypatch.setattr(agent_controller, "BUS_AVAILABLE", False)
        monkeypatch.setattr(agent_controller, "event_bus", None)
        calls = []
        monkeypatch.setattr(
            agent_controller,
            "_sync_markdowns_to_completed",
            lambda tid: calls.append("sync"),
        )
        monkeypatch.setattr(
            agent_controller,
            "_clear_auxiliary_states",
            lambda tid: calls.append("clear"),
        )
        monkeypatch.setattr(
            agent_controller,
            "_reset_circuit_breaker",
            lambda tid: calls.append("reset"),
        )
        monkeypatch.setattr(
            agent_controller,
            "_release_builder_lock",
            lambda tid: calls.append("release"),
        )
        monkeypatch.setattr(
            agent_controller,
            "_emit_manager_approve_cascade",
            lambda bus, tid: calls.append("cascade"),
        )
        monkeypatch.setattr(
            agent_controller, "_check_last_commit", lambda root, tid: (True, "ok")
        )
        mgr = tmp_path / "manager_bridge_state.json"
        sup = tmp_path / "supervisor_state.json"
        mgr.write_text('{"seq": 1}', encoding="utf-8")
        sup.write_text('{"active_ticket": "WT-2026-020h"}', encoding="utf-8")
        monkeypatch.setattr(agent_controller, "_MANAGER_BRIDGE_STATE_PATH", mgr)
        monkeypatch.setattr(agent_controller, "_SUPERVISOR_STATE_PATH", sup)
        return calls, mgr, sup

    def test_dry_run_does_not_mutate_state(self, monkeypatch, tmp_path, capsys):
        """--dry-run leaves state unchanged: no sync, no clear, state files intact."""
        calls, mgr, sup = self._setup(monkeypatch, tmp_path)
        rc = agent_controller._handle_manager_approve(
            self._TICKET, False, False, dry_run=True
        )
        assert rc == 0
        assert calls == [], f"dry-run must not mutate state, got calls={calls}"
        assert mgr.exists() and sup.exists(), "dry-run must not delete state files"
        assert "DRY-RUN" in capsys.readouterr().out

    def test_real_run_still_applies_transition(self, monkeypatch, tmp_path):
        """Without --dry-run, the closeout still applies (regression guard)."""
        calls, _mgr, _sup = self._setup(monkeypatch, tmp_path)
        rc = agent_controller._handle_manager_approve(
            self._TICKET, False, False, dry_run=False
        )
        assert rc == 0
        assert "sync" in calls, "real run must sync markdowns to COMPLETED"
        assert "clear" in calls, "real run must clear auxiliary states"
        assert "reset" in calls, "real run must reset circuit breaker"
        assert "release" in calls, "real run must release builder lock"


class TestHandleReopenTerminalTicket:
    """WT-2026-233a: explicit reopen path for terminal tickets."""

    _TICKET = "WT-2026-208"
    _WORK_PLAN = (
        "# Work Ticket - WT-2026-208\n"
        "## Metadata\n"
        "- **ID:** WT-2026-208\n"
        "- **Estado:** APPROVED\n"
        "- **deliverable_type:** code\n"
    )
    _EXEC_LOG_COMPLETED = "# Execution Log WT-2026-208\n\n**Estado:** COMPLETED\n"

    class FakeEvent:
        def __init__(self, to_state):
            self.payload = {"from_state": "IN_PROGRESS", "to_state": to_state}

        def to_dict(self):
            return {
                "event_type": "STATE_CHANGED",
                "payload": self.payload,
            }

    class FakeBus:
        def __init__(self, to_state="COMPLETED"):
            self.emits = []
            self.to_state = to_state

        def read_events(self, ticket_id=None, event_type=None):
            return [TestHandleReopenTerminalTicket.FakeEvent(self.to_state)]

        def emit(self, *args, **kwargs):
            self.emits.append((args, kwargs))
            return object()

    def _setup(self, monkeypatch, *, active_ticket=None, bus_state="COMPLETED"):
        active_ticket = active_ticket or self._TICKET
        work_plan = self._WORK_PLAN.replace(self._TICKET, active_ticket)
        fake_bus = self.FakeBus(bus_state)
        monkeypatch.setattr(
            agent_controller,
            "read_file",
            lambda p: work_plan if "work_plan" in str(p) else self._EXEC_LOG_COMPLETED,
        )
        monkeypatch.setattr(agent_controller, "BUS_AVAILABLE", True)
        monkeypatch.setattr(agent_controller, "event_bus", fake_bus)
        monkeypatch.setattr(agent_controller, "update_log_status", lambda *_args: True)
        return fake_bus

    def test_reopens_completed_ticket_to_in_progress(self, monkeypatch):
        """The explicit reopen flag bypasses the terminal reentry guard intentionally."""
        fake_bus = self._setup(monkeypatch)
        sync_calls = []
        monkeypatch.setattr(
            "scripts.state_projection_sync.sync_state_projection",
            lambda **kwargs: sync_calls.append(kwargs) or True,
        )
        monkeypatch.setattr(
            agent_controller,
            "get_runtime_dir",
            lambda: Path("destination/.agent/runtime"),
        )
        monkeypatch.setattr(
            agent_controller,
            "get_collab_dir",
            lambda: Path("destination/.agent/collaboration"),
        )

        rc = agent_controller._handle_reopen_terminal_ticket(self._TICKET, False)

        assert rc == 0
        assert fake_bus.emits, "Expected reopen command to emit a state transition"
        _args, kwargs = fake_bus.emits[0]
        assert kwargs["ticket_id"] == self._TICKET
        assert kwargs["payload"]["to_state"] == "IN_PROGRESS"
        assert kwargs["allow_reentry"] is True
        assert sync_calls == [
            {
                "runtime_dir": Path("destination/.agent/runtime/events"),
                "collaboration_dir": Path("destination/.agent/collaboration"),
                "ticket_id": self._TICKET,
            }
        ]

    def test_rejects_ticket_mismatch(self, monkeypatch):
        """A terminal ticket cannot be reopened unless it is the active work plan."""
        fake_bus = self._setup(monkeypatch, active_ticket="WT-2026-999")

        rc = agent_controller._handle_reopen_terminal_ticket(self._TICKET, False)

        assert rc == 1
        assert fake_bus.emits == []

    def test_rejects_non_terminal_bus_state(self, monkeypatch):
        """The recovery command only accepts a bus-derived COMPLETED state."""
        fake_bus = self._setup(monkeypatch, bus_state="READY_FOR_REVIEW")

        rc = agent_controller._handle_reopen_terminal_ticket(self._TICKET, False)

        assert rc == 1
        assert fake_bus.emits == []


# ======================================================================
# WT-2026-188 Phase 4: Builder ready evidence gate tests
# ======================================================================


class TestImplementationEvidenceGate:
    """WP-2026-188 Phase 4: _check_implementation_evidence pure function tests.

    Tests the four required scenarios:
    - Rejects when only .agent/collaboration/ files changed
    - Rejects when execution_log.md has only boilerplate
    - Rejects when Files Likely Touched not in diff (best-effort)
    - Accepts when real file changed and log has evidence
    """

    _PLAN_ID = "WT-2026-188"
    # Minimal plan content with Files Likely Touched
    _PLAN_WITH_FILES = """# Work Plan

## Metadata
- **ID:** WT-2026-188
- **Estado:** APPROVED
- **deliverable_type:** code

## Files Likely Touched
- `src/module.py`
- `tests/test_module.py`
"""

    _PLAN_WITHOUT_FILES = """# Work Plan

## Metadata
- **ID:** WT-2026-188
- **Estado:** APPROVED
"""

    # Non-boilerplate execution log content (includes quality gate evidence for WT-2026-203)
    _LOG_WITH_EVIDENCE = """# Execution Log

**Estado:** IN_PROGRESS

- Implemented closeout commit validation
- Added `_check_implementation_evidence` function
- Ran quality gates: ruff, pytest
- All checks passed
"""

    # Boilerplate-only log
    _LOG_BOILERPLATE = """# Execution Log

**Estado:** IN_PROGRESS

Marked ready by Builder

Marked ready by Builder
"""

    @staticmethod
    def _make_git_mock(changed_files: list[str], plan_in_log: bool = True) -> MagicMock:
        """Create a subprocess.run mock that returns specific git diff output.

        Args:
            changed_files: list of file paths to return from git diff --name-only
            plan_in_log: if True, git log --oneline includes the plan_id
        """
        mock_stdout = "\n".join(changed_files)

        def mock_run(cmd, *args, **kwargs):
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            if "diff --name-only" in cmd_str and "--cached" not in cmd_str:
                return MagicMock(returncode=0, stdout=mock_stdout, stderr="")
            if "diff --cached --name-only" in cmd_str:
                return MagicMock(returncode=0, stdout="", stderr="")
            if "log -1 --name-only" in cmd_str:
                return MagicMock(returncode=0, stdout="", stderr="")
            if "log --oneline" in cmd_str:
                if plan_in_log:
                    return MagicMock(
                        returncode=0,
                        stdout="7a3c596 WT-2026-188: some change\n",
                        stderr="",
                    )
                return MagicMock(
                    returncode=0, stdout="abc1234 other ticket\n", stderr=""
                )
            if "check-ignore" in cmd_str:
                return MagicMock(returncode=1, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        return MagicMock(side_effect=mock_run)

    def test_rejects_when_only_collaboration_files_changed(self, monkeypatch):
        """Evidence gate rejects when only .agent/collaboration/ files changed."""
        # Simulate git diff showing only collaboration files
        git_mock = self._make_git_mock(
            [
                ".agent/collaboration/execution_log.md",
                ".agent/collaboration/notifications.md",
            ]
        )
        monkeypatch.setattr(agent_controller.subprocess, "run", git_mock)

        # Mock work_plan and execution_log reads
        monkeypatch.setattr(
            agent_controller,
            "read_file",
            lambda x: (
                self._LOG_WITH_EVIDENCE
                if "execution_log.md" in str(x)
                else self._PLAN_WITHOUT_FILES
            ),
        )

        errors = agent_controller._check_implementation_evidence(self._PLAN_ID)
        # Should reject: no implementation files outside collaboration
        assert any(
            "Collaboration-only" in err or "No implementation evidence" in err
            for err in errors
        ), f"Expected no-implementation-evidence error, got: {errors}"

    def test_rejects_when_execution_log_has_only_boilerplate(self, monkeypatch):
        """Evidence gate rejects when execution_log.md has only boilerplate."""
        # Simulate git diff showing a real file change
        git_mock = self._make_git_mock(
            [
                "src/module.py",
            ]
        )
        monkeypatch.setattr(agent_controller.subprocess, "run", git_mock)

        # Mock work_plan and execution_log reads - boilerplate log
        monkeypatch.setattr(
            agent_controller,
            "read_file",
            lambda x: (
                self._LOG_BOILERPLATE
                if "execution_log.md" in str(x)
                else self._PLAN_WITHOUT_FILES
            ),
        )

        errors = agent_controller._check_implementation_evidence(self._PLAN_ID)
        # Should reject: log has only boilerplate
        assert any("boilerplate" in err.lower() for err in errors), (
            f"Expected boilerplate error, got: {errors}"
        )

    def test_rejects_when_files_likely_touched_not_in_diff(self, monkeypatch):
        """Evidence gate rejects (best-effort) when Files Likely Touched not in diff."""
        # Simulate git diff showing files NOT in Files Likely Touched
        git_mock = self._make_git_mock(
            [
                "unrelated/other.py",
            ]
        )
        monkeypatch.setattr(agent_controller.subprocess, "run", git_mock)

        # Mock reads: work_plan has Files Likely Touched section, log has evidence

        def mock_read(path):
            name = str(path).replace("\\", "/")
            if "execution_log.md" in name:
                return self._LOG_WITH_EVIDENCE
            if "work_plan.md" in name:
                return self._PLAN_WITH_FILES
            return ""

        monkeypatch.setattr(agent_controller, "read_file", mock_read)
        monkeypatch.setattr(
            agent_controller,
            "parse_files_likely_touched",
            lambda x: {
                "src/module.py",
                "tests/test_module.py",
            },
        )

        errors = agent_controller._check_implementation_evidence(self._PLAN_ID)
        # Should produce Files Likely Touched mismatch error (best-effort)
        assert any("Files Likely Touched" in err for err in errors), (
            f"Expected Files Likely Touched error, got: {errors}"
        )

    def test_accepts_when_real_file_changed_and_log_has_evidence(self, monkeypatch):
        """Evidence gate accepts when real file changed and log has evidence."""
        # Simulate git diff showing a real implementation file
        git_mock = self._make_git_mock(
            [
                "src/module.py",
            ]
        )
        monkeypatch.setattr(agent_controller.subprocess, "run", git_mock)

        # Mock reads: work_plan with files, log with evidence
        def mock_read(path):
            name = str(path).replace("\\", "/")
            if "execution_log.md" in name:
                return self._LOG_WITH_EVIDENCE
            if "work_plan.md" in name:
                return self._PLAN_WITH_FILES
            return ""

        monkeypatch.setattr(agent_controller, "read_file", mock_read)
        monkeypatch.setattr(
            agent_controller,
            "parse_files_likely_touched",
            lambda x: {
                "src/module.py",
                "tests/test_module.py",
            },
        )

        errors = agent_controller._check_implementation_evidence(self._PLAN_ID)
        # All checks should pass
        assert errors == [], f"Expected no errors, got: {errors}"

    def test_gate_is_unconditional(self, monkeypatch):
        """Evidence gate is never bypassed: rejects even when no diff exists."""
        monkeypatch.setattr(agent_controller, "_collect_git_diff_files", lambda: [])
        monkeypatch.setattr(
            agent_controller, "_check_git_log_has_plan_id", lambda pid: False
        )
        monkeypatch.setattr(
            agent_controller,
            "_check_log_has_quality_gate_evidence",
            lambda *_args, **_kwargs: False,
        )
        monkeypatch.setattr(agent_controller, "read_file", lambda name: "")
        errors = agent_controller._check_implementation_evidence(self._PLAN_ID)
        assert errors, "Evidence gate must reject when there is no real implementation"

    # ===== WT-2026-203: New evidence gate tests =====

    def test_rejects_when_git_log_misses_plan_id(self, monkeypatch):
        """TP-01: --mark-ready blocks if git log --oneline -20 lacks plan_id."""
        # Simulate git diff showing real file change
        git_mock = self._make_git_mock(["src/module.py"], plan_in_log=False)
        monkeypatch.setattr(agent_controller.subprocess, "run", git_mock)

        # Mock reads: log has quality gate evidence, plan exists
        monkeypatch.setattr(
            agent_controller,
            "read_file",
            lambda x: (
                self._LOG_WITH_EVIDENCE
                if "execution_log.md" in str(x)
                else self._PLAN_WITH_FILES
            ),
        )

        errors = agent_controller._check_implementation_evidence(self._PLAN_ID)
        assert any("commit evidence" in err.lower() for err in errors), (
            f"Expected commit evidence error, got: {errors}"
        )

    def test_rejects_when_log_lacks_quality_gate_evidence(self, monkeypatch):
        """TP-02: --mark-ready blocks if execution_log.md lacks pytest/ruff/passed."""
        git_mock = self._make_git_mock(["src/module.py"], plan_in_log=True)
        monkeypatch.setattr(agent_controller.subprocess, "run", git_mock)

        # Log without quality gate keywords but with non-boilerplate content
        # (passes the non-boilerplate check but fails the stricter quality gate check)
        log_no_qg = """# Execution Log

**Estado:** IN_PROGRESS

- Implemented the feature
- All tests were run manually
- Ready for review
"""

        monkeypatch.setattr(
            agent_controller,
            "read_file",
            lambda x: (
                log_no_qg if "execution_log.md" in str(x) else self._PLAN_WITH_FILES
            ),
        )

        errors = agent_controller._check_implementation_evidence(self._PLAN_ID)
        assert any("quality gate" in err.lower() for err in errors), (
            f"Expected quality gate evidence error, got: {errors}"
        )

    def test_accepts_when_all_new_checks_pass(self, monkeypatch):
        """All WT-2026-203 checks pass when git log has plan_id and log has QG evidence."""
        git_mock = self._make_git_mock(["src/module.py"], plan_in_log=True)
        monkeypatch.setattr(agent_controller.subprocess, "run", git_mock)

        def mock_read(path):
            name = str(path).replace("\\", "/")
            if "execution_log.md" in name:
                return self._LOG_WITH_EVIDENCE
            if "work_plan.md" in name:
                return self._PLAN_WITH_FILES
            return ""

        monkeypatch.setattr(agent_controller, "read_file", mock_read)
        monkeypatch.setattr(
            agent_controller,
            "parse_files_likely_touched",
            lambda x: {"src/module.py"},
        )

        errors = agent_controller._check_implementation_evidence(self._PLAN_ID)
        assert errors == [], f"Expected no errors, got: {errors}"

    def test_flt_all_gitignored_true_when_all_gitignored(self, monkeypatch):
        """WOT-2026-019g: _flt_all_gitignored returns True when all FLT gitignored."""
        monkeypatch.setattr(
            agent_controller,
            "parse_files_likely_touched",
            lambda x, **kw: {"data/cache.json"},
        )

        def mock_run(cmd, *args, **kwargs):
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            if "check-ignore" in cmd_str:
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(agent_controller.subprocess, "run", mock_run)
        assert agent_controller._flt_all_gitignored("plan") is True

    def test_flt_all_gitignored_false_when_tracked(self, monkeypatch):
        """WOT-2026-019g: _flt_all_gitignored returns False when FLT is tracked."""
        monkeypatch.setattr(
            agent_controller,
            "parse_files_likely_touched",
            lambda x, **kw: {"src/module.py"},
        )

        def mock_run(cmd, *args, **kwargs):
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            if "check-ignore" in cmd_str:
                return MagicMock(returncode=1, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(agent_controller.subprocess, "run", mock_run)
        assert agent_controller._flt_all_gitignored("plan") is False

    def test_code_ticket_gitignored_flt_skips_evidence_check(self, monkeypatch):
        """WOT-2026-019g: code ticket with gitignored FLT skips evidence checks."""
        git_mock = self._make_git_mock(
            [".agent/collaboration/execution_log.md"],
            plan_in_log=True,
        )
        original_side = git_mock.side_effect

        def extended_mock(cmd, *args, **kwargs):
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            if "check-ignore" in cmd_str:
                return MagicMock(returncode=0, stdout="", stderr="")
            return original_side(cmd, *args, **kwargs)

        monkeypatch.setattr(
            agent_controller.subprocess, "run", MagicMock(side_effect=extended_mock)
        )

        def mock_read(path):
            name = str(path).replace("\\", "/")
            if "execution_log.md" in name:
                return self._LOG_WITH_EVIDENCE
            if "work_plan.md" in name:
                return self._PLAN_WITH_FILES
            return ""

        monkeypatch.setattr(agent_controller, "read_file", mock_read)
        monkeypatch.setattr(
            agent_controller,
            "parse_files_likely_touched",
            lambda x, **kw: {"src/module.py", "tests/test_module.py"},
        )

        errors = agent_controller._check_implementation_evidence(self._PLAN_ID)
        assert not any("No implementation evidence" in err for err in errors), (
            f"Should skip for gitignored FLT, got: {errors}"
        )
        assert not any("Collaboration-only" in err for err in errors), (
            f"Should skip collab-only for gitignored FLT, got: {errors}"
        )
        assert not any("Files Likely Touched match" in err for err in errors), (
            f"Should skip FLT-match for gitignored FLT, got: {errors}"
        )


# =============================================================================
# Tests WT-2026-204: helpers de validacion de blockers y AUTO-REJECT
# =============================================================================


class TestValidateTurnBlockersContent:
    """WT-2026-204: _validate_turn_blockers_content helper."""

    def test_valid_non_empty_blockers(self):
        """Valid non-empty blockers return True."""
        assert (
            agent_controller._validate_turn_blockers_content(
                "- bus/parser.py: fix edge case"
            )
            is True
        )

    def test_empty_blockers_return_false(self):
        """Empty or whitespace-only blockers return False."""
        assert agent_controller._validate_turn_blockers_content("") is False
        assert agent_controller._validate_turn_blockers_content("   ") is False

    def test_oversized_blockers_return_false(self):
        """Blockers exceeding 15 KB return False."""
        big_blockers = "- file.py: " + "x" * (16 * 1024)
        assert agent_controller._validate_turn_blockers_content(big_blockers) is False

    def test_jsonl_crudo_blockers_return_false(self):
        """Blockers containing raw JSONL markers return False."""
        assert (
            agent_controller._validate_turn_blockers_content(
                '{"type":"text","part":{...}}'
            )
            is False
        )
        assert (
            agent_controller._validate_turn_blockers_content(
                "some text sessionID=abc123"
            )
            is False
        )


class TestAutoRejectQualityGates:
    """WT-2026-204: _check_quality_gates AUTO-REJECT path."""

    def test_auto_reject_has_distinct_instruction(self):
        """AUTO-REJECT produces distinct instruction without builder_rules refs."""
        with (
            patch(
                "agent_controller.run_quality_gates",
                return_value={
                    "passed": False,
                    "errors": [],
                    "summary": [],
                    "warnings": [],
                },
            ),
            patch("agent_controller.update_log_status"),
        ):
            result = agent_controller._check_quality_gates(
                plan_id="WT-2026-204",
                plan_type="IMPLEMENTATION",
                plan_status="APPROVED",
                skip_gates=False,
            )

        assert result is not None
        assert result["role"] == "BUILDER"
        # Must not reference old files
        assert result["context_file"] != ".builder_rules"
        assert result["workflow_file"] != ".agent/workflows/builder_workflow.md"
        # Must have distinct instruction
        assert "AUTO-REJECTED" in result["instruction"]
        assert result["instruction"] != (
            "RECHAZADO. Quality Gates fallaron. Corrige errores."
        )
        assert result["action_type"] == "FIX_QUALITY_ISSUES"

    def test_auto_reject_logs_auto_rejected_status(self):
        """AUTO-REJECT updates log status to AUTO-REJECTED."""
        logged_status = {}

        def fake_update_log_status(status, note):
            logged_status["status"] = status
            logged_status["note"] = note

        with (
            patch(
                "agent_controller.run_quality_gates",
                return_value={
                    "passed": False,
                    "errors": [],
                    "summary": [],
                    "warnings": [],
                },
            ),
            patch("agent_controller.update_log_status", fake_update_log_status),
        ):
            agent_controller._check_quality_gates(
                plan_id="WT-2026-204",
                plan_type="IMPLEMENTATION",
                plan_status="APPROVED",
                skip_gates=False,
            )

        assert logged_status.get("status") == "IN_PROGRESS"
        assert "AUTO-REJECTED" in logged_status.get("note", "")


class TestAgentControllerEvidence:
    """WT-2026-226a: Ensure agent_controller delegates correctly to bus.evidence."""

    def test_negative_no_commit_no_diff(self, tmp_path, monkeypatch):
        import agent_controller

        from tests.test_pre_handoff_guard import init_git_repo

        motor = tmp_path / "motor"
        dest = tmp_path / "dest"
        init_git_repo(motor)
        init_git_repo(dest)

        monkeypatch.setattr(agent_controller, "_MOTOR_ROOT", motor)
        monkeypatch.setattr(agent_controller, "PROJECT_ROOT", dest)
        # WOT-2026-018b: aislar del work_plan.md REAL. Sin este mock, el test lee el
        # deliverable_type del work_plan del repo; si es documentation/analysis/research,
        # _check_implementation_evidence retorna antes de emitir "No commit evidence"
        # (non_code_ticket -> early return) y el assert falla. El test hermano
        # test_semantic_parity_positive ya usa este mismo patron.
        monkeypatch.setattr(agent_controller, "read_file", lambda x: "")

        errors = agent_controller._check_implementation_evidence("WT-2026-999")

        assert any("No commit evidence" in err for err in errors)
        assert any("No implementation evidence" in err for err in errors)

    def test_semantic_parity_positive(self, tmp_path, monkeypatch):
        """agent_controller passes evidence gate when ticket commit exists."""
        import subprocess

        import agent_controller

        from tests.test_pre_handoff_guard import init_git_repo

        motor = tmp_path / "motor"
        init_git_repo(motor)

        (motor / "src").mkdir()
        (motor / "src" / "productive.py").write_text("print('test')")
        subprocess.run(["git", "add", "."], cwd=motor, check=True)
        subprocess.run(
            ["git", "commit", "-m", "WT-2026-999: add code"], cwd=motor, check=True
        )

        monkeypatch.setattr(agent_controller, "_MOTOR_ROOT", motor)
        monkeypatch.setattr(agent_controller, "PROJECT_ROOT", motor)

        # Mock out log checks
        monkeypatch.setattr(agent_controller, "_check_log_has_evidence", lambda: True)
        monkeypatch.setattr(
            agent_controller,
            "_check_log_has_quality_gate_evidence",
            lambda *_args, **_kwargs: True,
        )
        monkeypatch.setattr(agent_controller, "read_file", lambda x: "")

        errors = agent_controller._check_implementation_evidence("WT-2026-999")

        # None of the errors should be about missing implementation evidence or commits
        assert not any("No commit evidence" in err for err in errors)
        assert not any("No implementation evidence" in err for err in errors)
        assert not any("Collaboration-only" in err for err in errors)
        assert not any("Docs-only" in err for err in errors)

    def test_documentation_ticket_accepts_declared_deliverable_without_commit(
        self, tmp_path, monkeypatch
    ):
        """Documentation/research tickets should not require code commits."""
        import agent_controller

        report_path = tmp_path / ".agent" / "runtime" / "compare"
        report_path.mkdir(parents=True)
        report_file = report_path / "stablyai-orca-HEAD-2026-06-07.md"
        report_file.write_text("# report\n", encoding="utf-8")

        plan_content = f"""# Work Plan

- **deliverable_type:** research

## Deliverables
- `{report_file}`
"""
        log_content = """
# Execution Log

**Estado:** IN_PROGRESS

- Validate final tras reporte: exit code 0, 0 errores, 0 warnings
- Report persisted to runtime/compare
"""

        monkeypatch.setattr(
            agent_controller,
            "read_file",
            lambda path: (
                log_content if "execution_log.md" in str(path) else plan_content
            ),
        )
        monkeypatch.setattr(
            agent_controller,
            "_check_log_has_evidence",
            lambda: True,
        )

        def fake_resolve_evidence(*_args, **_kwargs):
            return {
                "all_files": {str(report_file)},
                "has_ticket_commit": False,
                "is_collaboration_only": True,
                "is_docs_only": True,
                "has_productive_evidence": False,
            }

        from types import SimpleNamespace

        monkeypatch.setitem(
            sys.modules,
            "bus.evidence",
            SimpleNamespace(resolve_evidence=fake_resolve_evidence),
        )

        errors = agent_controller._check_implementation_evidence("WT-2026-236a")
        assert errors == [], (
            f"Expected no errors for research deliverable, got: {errors}"
        )

    def test_documentation_ticket_rejects_missing_declared_deliverable(
        self, tmp_path, monkeypatch
    ):
        """Documentation/research tickets still require declared artifacts."""
        import agent_controller

        report_file = (
            tmp_path
            / ".agent"
            / "runtime"
            / "compare"
            / "stablyai-orca-HEAD-2026-06-07.md"
        )
        plan_content = f"""# Work Plan

- **deliverable_type:** documentation

## Deliverables
- `{report_file}`
"""
        log_content = """
# Execution Log

**Estado:** IN_PROGRESS

- Validate final: exit code 0, 0 errors, 0 warnings
"""

        monkeypatch.setattr(
            agent_controller,
            "read_file",
            lambda path: (
                log_content if "execution_log.md" in str(path) else plan_content
            ),
        )
        monkeypatch.setattr(agent_controller, "_check_log_has_evidence", lambda: True)

        def fake_resolve_evidence(*_args, **_kwargs):
            return {
                "all_files": set(),
                "has_ticket_commit": False,
                "is_collaboration_only": False,
                "is_docs_only": False,
                "has_productive_evidence": False,
            }

        from types import SimpleNamespace

        monkeypatch.setitem(
            sys.modules,
            "bus.evidence",
            SimpleNamespace(resolve_evidence=fake_resolve_evidence),
        )

        errors = agent_controller._check_implementation_evidence("WT-2026-236a")
        assert any("Missing declared deliverables" in err for err in errors)

    def test_documentation_ticket_detects_missing_deliverable_under_subheader(
        self, tmp_path, monkeypatch
    ):
        """Files Likely Touched sub-sections must still declare artifacts."""
        import agent_controller

        report_file = (
            tmp_path
            / ".agent"
            / "runtime"
            / "compare"
            / "stablyai-orca-HEAD-2026-06-07.md"
        )
        plan_content = f"""# Work Plan

- **deliverable_type:** research

## Files Likely Touched

### repo_destino - Builder
- `{report_file}`
"""
        log_content = """
# Execution Log

**Estado:** IN_PROGRESS

- Validate final tras reporte: exit code 0, 0 errors, 0 warnings
"""

        monkeypatch.setattr(
            agent_controller,
            "read_file",
            lambda path: (
                log_content if "execution_log.md" in str(path) else plan_content
            ),
        )
        monkeypatch.setattr(agent_controller, "_check_log_has_evidence", lambda: True)

        from types import SimpleNamespace

        monkeypatch.setitem(
            sys.modules,
            "bus.evidence",
            SimpleNamespace(
                resolve_evidence=lambda *_args, **_kwargs: {
                    "all_files": set(),
                    "has_ticket_commit": False,
                    "is_collaboration_only": False,
                    "is_docs_only": False,
                    "has_productive_evidence": False,
                }
            ),
        )

        errors = agent_controller._check_implementation_evidence("WT-2026-236a")
        assert any("Missing declared deliverables" in err for err in errors)

    def test_documentation_deliverables_ignore_read_only_subheaders(
        self, tmp_path, monkeypatch
    ):
        """Read/inspect and Manager-only FLT paths are not required artifacts."""
        import agent_controller

        report_dir = tmp_path / ".agent" / "runtime" / "compare"
        report_dir.mkdir(parents=True)
        report_file = report_dir / "stablyai-orca-HEAD-2026-06-07.md"
        report_file.write_text("# report\n", encoding="utf-8")
        missing_read_only = tmp_path / "skills" / "repo-compare" / "SKILL.md"
        missing_manager_only = tmp_path / ".agent" / "collaboration" / "PLAN.md"

        plan_content = f"""# Work Plan

- **deliverable_type:** research

## Files Likely Touched

### repo_destino - Builder
- `{report_file}`

### repo_destino - Read/inspect only
- `{missing_read_only}`

### repo_destino - Manager only
- `{missing_manager_only}`
"""
        log_content = """
# Execution Log

**Estado:** IN_PROGRESS

- Reporte `.agent/runtime/compare/stablyai-orca-HEAD-2026-06-07.md` creado. Validate: exit code 0, 0 errors, 0 warnings.
"""

        monkeypatch.setattr(
            agent_controller,
            "read_file",
            lambda path: (
                log_content if "execution_log.md" in str(path) else plan_content
            ),
        )
        monkeypatch.setattr(agent_controller, "_check_log_has_evidence", lambda: True)

        from types import SimpleNamespace

        monkeypatch.setitem(
            sys.modules,
            "bus.evidence",
            SimpleNamespace(
                resolve_evidence=lambda *_args, **_kwargs: {
                    "all_files": {str(report_file)},
                    "has_ticket_commit": False,
                    "is_collaboration_only": True,
                    "is_docs_only": True,
                    "has_productive_evidence": False,
                }
            ),
        )

        errors = agent_controller._check_implementation_evidence("WT-2026-236a")
        assert errors == [], f"Read-only paths should not be required: {errors}"

    def test_documentation_quality_gate_ignores_planning_validate_entries(
        self, monkeypatch
    ):
        """Planning validate lines should not satisfy Builder deliverable evidence."""
        import agent_controller

        log_content = """
# Execution Log

**Estado:** IN_PROGRESS

- Validate final tras sustitucion de placeholders: exit code 0, 0 errors, 0 warnings.
- Fase 3: pendiente reporte `.agent/runtime/compare/stablyai-orca-HEAD-2026-06-07.md`.
"""

        monkeypatch.setattr(agent_controller, "read_file", lambda _path: log_content)

        assert (
            agent_controller._check_log_has_quality_gate_evidence("documentation")
            is False
        )

    def test_documentation_quality_gate_accepts_report_validate_entry(
        self, monkeypatch
    ):
        """Builder report evidence and validate result can close non-code tickets."""
        import agent_controller

        log_content = """
# Execution Log

**Estado:** IN_PROGRESS

- Validate final tras reporte `.agent/runtime/compare/stablyai-orca-HEAD-2026-06-07.md`: exit code 0, 0 errors, 0 warnings.
"""

        monkeypatch.setattr(agent_controller, "read_file", lambda _path: log_content)

        assert agent_controller._check_log_has_quality_gate_evidence("research") is True


# =============================================================================
# WT-2026-245b: external-motor checkpoint topology regression tests
# =============================================================================


class TestExternalMotorCheckpointTopology:
    """WT-2026-245b: Regression tests for checkpoint M3 in external-motor topology.

    In external-motor topology, the motor repo and workspace are separate directories.
    The checkpoint tag (checkpoint/review-<ticket>) must live in repo_motor,
    not in the workspace. These tests use real git repos in tmp_path to
    reproduce the bug: --pre-handoff creating the tag in the wrong root
    and --mark-ready failing to find it.

    [NON-REVERSE-CLASSICAL: regression test for identified bug — the fix
    was implemented first, then the test was written to prove it works.]
    """

    _PLAN_ID = "WT-2026-245b"
    _PLAN_CONTENT = f"""# Work Plan

## Metadata
- **ID:** {_PLAN_ID}
- **Estado:** APPROVED
- **deliverable_type:** code

## Files Likely Touched
- `.agent/agent_controller.py`
- `tests/test_agent_controller.py`
"""
    _DESTINO_PLAN_CONTENT = f"""# Work Plan

## Metadata
- **ID:** {_PLAN_ID}
- **Estado:** APPROVED
- **deliverable_type:** code
- **delivery_authority:** repo_destino

## Files Likely Touched
- `app.py`
"""

    @staticmethod
    def _init_git_repo(repo_path: Path) -> None:
        """Initialize a git repository with initial commit."""
        repo_path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )
        (repo_path / "README.md").write_text("# Test Repo")
        subprocess.run(
            ["git", "add", "."], cwd=repo_path, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )

    @staticmethod
    def _create_work_plan(workspace: Path) -> None:
        """Create work_plan.md in the workspace."""
        collab_dir = workspace / ".agent" / "collaboration"
        collab_dir.mkdir(parents=True, exist_ok=True)
        (collab_dir / "work_plan.md").write_text(
            TestExternalMotorCheckpointTopology._PLAN_CONTENT
        )

    @staticmethod
    def _create_execution_log(workspace: Path) -> None:
        """Create execution_log.md in the workspace."""
        collab_dir = workspace / ".agent" / "collaboration"
        collab_dir.mkdir(parents=True, exist_ok=True)
        (collab_dir / "execution_log.md").write_text(
            "# Execution Log\n\n**Estado:** IN_PROGRESS\n"
        )

    def test_pre_handoff_creates_tag_in_motor_not_workspace(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """--pre-handoff in external-motor topology must create the tag in repo_motor, not workspace.

        Regression: if the workspace has its own .git, the old code would
        create the tag in the workspace (git_root = project_root). The fix
        delegates to _try_motor_tag() when motor_root != project_root.
        """
        # Setup: motor repo and workspace as separate directories
        motor_repo = tmp_path / "motor"
        workspace = tmp_path / "workspace"
        self._init_git_repo(motor_repo)
        self._init_git_repo(workspace)  # workspace also has .git in this topology
        self._create_work_plan(workspace)
        self._create_execution_log(workspace)
        # WOT-2026-009g: work_plan.md must be committed before handoff
        subprocess.run(
            [
                "git",
                "add",
                str(workspace / ".agent" / "collaboration" / "work_plan.md"),
            ],
            cwd=workspace,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "add work_plan"],
            cwd=workspace,
            check=True,
            capture_output=True,
        )

        # Create a productive file in motor repo (simulating code changes)
        (motor_repo / "src").mkdir(parents=True, exist_ok=True)
        (motor_repo / "src" / "module.py").write_text("# productive change")
        subprocess.run(
            ["git", "add", "."], cwd=motor_repo, check=True, capture_output=True
        )

        # Monkey-patch the controller to use our temp repos
        monkeypatch.setattr(agent_controller, "_MOTOR_ROOT", motor_repo)
        monkeypatch.setattr(agent_controller, "PROJECT_ROOT", workspace)

        # Patch read_file to return our plan content
        monkeypatch.setattr(
            agent_controller,
            "read_file",
            lambda path: (
                self._PLAN_CONTENT
                if "work_plan" in str(path).lower()
                else (
                    "# Execution Log\n\n**Estado:** IN_PROGRESS\n"
                    if "execution_log" in str(path).lower()
                    else ""
                )
            ),
        )

        # Patch _ensure_active_builder_round to pass
        monkeypatch.setattr(
            agent_controller,
            "_ensure_active_builder_round",
            lambda plan_id: (True, 1, None),
        )

        # Patch BUS_AVAILABLE to False to avoid bus dependency
        monkeypatch.setattr(agent_controller, "BUS_AVAILABLE", False)

        # Patch motor_uncommitted_productive (imported from bus.evidence inside
        # _handle_pre_handoff) to return our file as an uncommitted motor change
        import bus.evidence

        monkeypatch.setattr(
            bus.evidence,
            "motor_uncommitted_productive",
            lambda root: {"src/module.py"},
        )

        # Patch parse_files_likely_touched to return our FLT paths
        monkeypatch.setattr(
            agent_controller,
            "parse_files_likely_touched",
            lambda content: {
                str((motor_repo / ".agent" / "agent_controller.py").resolve()),
                str((motor_repo / "tests" / "test_agent_controller.py").resolve()),
            },
        )

        # Patch _parse_raw_flt_paths to return our FLT paths
        monkeypatch.setattr(
            agent_controller,
            "_parse_raw_flt_paths",
            lambda content, **kwargs: {
                ".agent/agent_controller.py",
                "tests/test_agent_controller.py",
                "src/module.py",
            },
        )

        # Run pre-handoff
        code, output = self._capture_output(
            lambda: agent_controller._handle_pre_handoff(json_output=False)
        )

        assert code == 0, f"pre-handoff failed: {output}"

        # Verify: tag exists in motor_repo, NOT in workspace
        tag_result = subprocess.run(
            ["git", "rev-parse", f"checkpoint/review-{self._PLAN_ID}^{{}}"],
            capture_output=True,
            text=True,
            cwd=motor_repo,
        )
        assert tag_result.returncode == 0, (
            f"Tag should exist in motor_repo: {tag_result.stderr}"
        )

        tag_in_ws = subprocess.run(
            ["git", "rev-parse", f"checkpoint/review-{self._PLAN_ID}^{{}}"],
            capture_output=True,
            text=True,
            cwd=workspace,
        )
        assert tag_in_ws.returncode != 0, "Tag should NOT exist in workspace"

    def test_mark_ready_finds_checkpoint_in_motor(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """--mark-ready in external-motor topology must find the checkpoint tag in repo_motor.

        Regression: after --pre-handoff creates the tag in motor_repo,
        --mark-ready must validate it via _resolve_motor_checkpoint_files.
        """
        # Setup: motor repo and workspace as separate directories
        motor_repo = tmp_path / "motor"
        workspace = tmp_path / "workspace"
        self._init_git_repo(motor_repo)
        self._init_git_repo(workspace)
        self._create_work_plan(workspace)
        self._create_execution_log(workspace)

        # Create a productive commit in motor repo with the ticket ID
        (motor_repo / "src").mkdir(parents=True, exist_ok=True)
        (motor_repo / "src" / "module.py").write_text("# productive change")
        subprocess.run(
            ["git", "add", "."], cwd=motor_repo, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", f"feat({self._PLAN_ID}): implement fix"],
            cwd=motor_repo,
            check=True,
            capture_output=True,
        )

        # Create the checkpoint tag in motor_repo (as pre-handoff would)
        subprocess.run(
            [
                "git",
                "tag",
                "-a",
                f"checkpoint/review-{self._PLAN_ID}",
                "-m",
                f"Checkpoint M3 for {self._PLAN_ID}",
            ],
            cwd=motor_repo,
            check=True,
            capture_output=True,
        )

        # Monkey-patch the controller to use our temp repos
        self._seed_archival_detector(motor_repo)
        monkeypatch.setattr(agent_controller, "_MOTOR_ROOT", motor_repo)
        monkeypatch.setattr(agent_controller, "PROJECT_ROOT", workspace)

        # Patch read_file
        monkeypatch.setattr(
            agent_controller,
            "read_file",
            lambda path: (
                self._PLAN_CONTENT
                if "work_plan" in str(path).lower()
                else (
                    "# Execution Log\n\n**Estado:** IN_PROGRESS\n"
                    if "execution_log" in str(path).lower()
                    else ""
                )
            ),
        )

        # Patch _ensure_active_builder_round to pass
        monkeypatch.setattr(
            agent_controller,
            "_ensure_active_builder_round",
            lambda plan_id: (True, 1, None),
        )

        # Patch BUS_AVAILABLE to False to avoid bus dependency
        monkeypatch.setattr(agent_controller, "BUS_AVAILABLE", False)

        # Patch _check_implementation_evidence to pass
        monkeypatch.setattr(
            agent_controller, "_check_implementation_evidence", lambda plan_id: []
        )

        # Patch _run_pre_handoff_guard to pass (we already have the tag)
        monkeypatch.setattr(
            agent_controller,
            "_run_pre_handoff_guard",
            lambda plan_id, json_output: {"valid": True},
        )

        # Patch _emit_builder_exit to no-op
        monkeypatch.setattr(
            agent_controller, "_emit_builder_exit", lambda *a, **kw: None
        )

        # Patch _sync_mark_ready_targets to no-op
        monkeypatch.setattr(
            agent_controller, "_sync_mark_ready_targets", lambda *a, **kw: None
        )

        # Patch _reset_circuit_breaker to no-op
        monkeypatch.setattr(
            agent_controller, "_reset_circuit_breaker", lambda plan_id: None
        )

        # Patch _release_builder_lock to no-op
        monkeypatch.setattr(
            agent_controller, "_release_builder_lock", lambda *a, **kw: None
        )

        # Patch _auto_archive_closed_artifacts to no-op
        monkeypatch.setattr(
            agent_controller, "_auto_archive_closed_artifacts", lambda: None
        )

        # Patch _read_deliverable_type to return "code"
        monkeypatch.setattr(
            agent_controller,
            "_read_deliverable_type",
            lambda content, default="code": "code",
        )

        # Patch _parse_raw_flt_paths to return our FLT paths
        monkeypatch.setattr(
            agent_controller,
            "_parse_raw_flt_paths",
            lambda content, **kwargs: {
                ".agent/agent_controller.py",
                "tests/test_agent_controller.py",
                "src/module.py",
            },
        )

        # Run mark-ready
        code, output = self._capture_output(
            lambda: agent_controller._handle_mark_ready(
                scope_override=None, json_output=False, force_mode=False
            )
        )

        assert code == 0, f"mark-ready failed: {output}"
        assert "marked as ready" in output.lower() or "Motor scope" in output, (
            f"Unexpected output: {output}"
        )

    def _setup_mark_ready_motor_topology(
        self, tmp_path: Path, monkeypatch
    ) -> tuple[Path, Path]:
        """Wire a real motor+workspace topology for a passing --mark-ready run.

        WOT-2026-011h helper: reproduces the green path of
        test_mark_ready_finds_checkpoint_in_motor (productive motor commit, M3 tag,
        all collaborators patched to no-op) and returns (motor_repo, workspace).
        Callers override _auto_archive_closed_artifacts to inject (or not) the
        archival limbo, exercising the REAL mark-ready path, not a helper in isolation.
        """
        motor_repo = tmp_path / "motor"
        workspace = tmp_path / "workspace"
        self._init_git_repo(motor_repo)
        self._init_git_repo(workspace)
        self._create_work_plan(workspace)
        self._create_execution_log(workspace)

        (motor_repo / "src").mkdir(parents=True, exist_ok=True)
        (motor_repo / "src" / "module.py").write_text("# productive change")
        subprocess.run(
            ["git", "add", "."], cwd=motor_repo, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", f"feat({self._PLAN_ID}): implement fix"],
            cwd=motor_repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "git",
                "tag",
                "-a",
                f"checkpoint/review-{self._PLAN_ID}",
                "-m",
                f"Checkpoint M3 for {self._PLAN_ID}",
            ],
            cwd=motor_repo,
            check=True,
            capture_output=True,
        )

        self._seed_archival_detector(motor_repo)

        monkeypatch.setattr(agent_controller, "_MOTOR_ROOT", motor_repo)
        monkeypatch.setattr(agent_controller, "PROJECT_ROOT", workspace)
        monkeypatch.setattr(
            agent_controller,
            "read_file",
            lambda path: (
                self._PLAN_CONTENT
                if "work_plan" in str(path).lower()
                else (
                    "# Execution Log\n\n**Estado:** IN_PROGRESS\n"
                    if "execution_log" in str(path).lower()
                    else ""
                )
            ),
        )
        monkeypatch.setattr(
            agent_controller,
            "_ensure_active_builder_round",
            lambda plan_id: (True, 1, None),
        )
        monkeypatch.setattr(agent_controller, "BUS_AVAILABLE", False)
        monkeypatch.setattr(
            agent_controller, "_check_implementation_evidence", lambda plan_id: []
        )
        monkeypatch.setattr(
            agent_controller,
            "_run_pre_handoff_guard",
            lambda plan_id, json_output: {"valid": True},
        )
        monkeypatch.setattr(
            agent_controller, "_emit_builder_exit", lambda *a, **kw: None
        )
        monkeypatch.setattr(
            agent_controller, "_sync_mark_ready_targets", lambda *a, **kw: None
        )
        monkeypatch.setattr(
            agent_controller, "_reset_circuit_breaker", lambda plan_id: None
        )
        monkeypatch.setattr(
            agent_controller, "_release_builder_lock", lambda *a, **kw: None
        )
        monkeypatch.setattr(
            agent_controller,
            "_read_deliverable_type",
            lambda content, default="code": "code",
        )
        monkeypatch.setattr(
            agent_controller,
            "_parse_raw_flt_paths",
            lambda content, **kwargs: {
                ".agent/agent_controller.py",
                "tests/test_agent_controller.py",
                "src/module.py",
            },
        )
        return motor_repo, workspace

    @staticmethod
    def _seed_archival_detector(motor_repo: Path) -> None:
        """Copy the real delivery_hygiene_check into a patched motor_repo.

        WOT-2026-011h: --mark-ready now resolves check_archive_rename_complete from
        _MOTOR_ROOT/scripts. Tests that patch _MOTOR_ROOT to a temp dir must seed the
        detector there, otherwise the new fail-closed guard (correctly) blocks.
        """
        import shutil as _shutil

        real_motor_root = Path(agent_controller.__file__).resolve().parent.parent
        (motor_repo / "scripts").mkdir(parents=True, exist_ok=True)
        _shutil.copy2(
            real_motor_root / "scripts" / "delivery_hygiene_check.py",
            motor_repo / "scripts" / "delivery_hygiene_check.py",
        )

    @staticmethod
    def _inject_archival_limbo(workspace: Path) -> None:
        """Create the real `D old + ?? new` archival limbo in the workspace git.

        Commits a closed STRATEGY_ artifact, then moves it into _archive/plan_audit/
        with shutil.move WITHOUT committing -- exactly what _auto_archive_closed_artifacts
        does. Git then shows the original as deleted and the archived copy as untracked.
        """
        import shutil

        collab = workspace / ".agent" / "collaboration"
        collab.mkdir(parents=True, exist_ok=True)
        artifact = collab / "STRATEGY_WT-2026-245b.md"
        artifact.write_text("# closed strategy\n")
        subprocess.run(
            ["git", "add", str(artifact)],
            cwd=workspace,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "add closed STRATEGY artifact"],
            cwd=workspace,
            check=True,
            capture_output=True,
        )
        archive_dir = collab / "_archive" / "plan_audit"
        archive_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(artifact), str(archive_dir / artifact.name))

    def test_mark_ready_blocks_when_archive_leaves_uncommitted_rename(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """WOT-2026-011h FAIL-without: if mark-ready's auto-archive leaves the
        `D old + ?? new` limbo, mark-ready must fail closed with the stable reason
        archive_rename_uncommitted, BEFORE reaching READY_FOR_REVIEW."""
        _motor, workspace = self._setup_mark_ready_motor_topology(tmp_path, monkeypatch)

        # The auto-archive step is what creates the limbo in the real path.
        monkeypatch.setattr(
            agent_controller,
            "_auto_archive_closed_artifacts",
            lambda: self._inject_archival_limbo(workspace),
        )

        code, output = self._capture_output(
            lambda: agent_controller._handle_mark_ready(
                scope_override=None, json_output=False, force_mode=False
            )
        )

        assert code == 1, f"mark-ready should block on archival limbo: {output}"
        assert "archive_rename_uncommitted" in output, (
            f"diagnostic must carry the stable reason: {output}"
        )
        # Remediation must name origin, destino and the exact reconcile command.
        assert "STRATEGY_WT-2026-245b.md" in output
        assert "_archive/plan_audit/" in output
        assert "git add" in output and "git commit" in output, (
            f"diagnostic must surface the reconcile command, not auto-commit: {output}"
        )
        # And it must NOT have auto-committed the rename (no auto-commit invariant):
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=workspace,
            capture_output=True,
            text=True,
        )
        assert "STRATEGY_WT-2026-245b.md" in status.stdout, (
            "the rename must remain uncommitted (the guard never auto-commits)"
        )

    def test_mark_ready_clean_archive_reaches_ready_for_review(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """WOT-2026-011h PASS-with: a clean auto-archive (no limbo) must still reach
        READY_FOR_REVIEW. No false positive from the new barrier."""
        _motor, _workspace = self._setup_mark_ready_motor_topology(
            tmp_path, monkeypatch
        )
        # Clean archive: no-op (nothing to archive) -> no limbo.
        monkeypatch.setattr(
            agent_controller, "_auto_archive_closed_artifacts", lambda: None
        )

        code, output = self._capture_output(
            lambda: agent_controller._handle_mark_ready(
                scope_override=None, json_output=False, force_mode=False
            )
        )

        assert code == 0, f"clean mark-ready must pass: {output}"
        assert "archive_rename_uncommitted" not in output

    def test_mark_ready_archive_guard_fails_closed_on_detector_error(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """WOT-2026-011h: the new guard must fail closed if the detector cannot run
        (guard parity with pre_handoff_guard), never silently pass."""
        _motor, _workspace = self._setup_mark_ready_motor_topology(
            tmp_path, monkeypatch
        )
        monkeypatch.setattr(
            agent_controller, "_auto_archive_closed_artifacts", lambda: None
        )

        # Force the guard's internal detector load to raise; the guard must block.
        import importlib

        real_spec_from_file = importlib.util.spec_from_file_location

        def _fake_spec(name, location, *a, **kw):
            if "delivery_hygiene_check" in str(location):
                raise RuntimeError("simulated detector load failure")
            return real_spec_from_file(name, location, *a, **kw)

        monkeypatch.setattr(importlib.util, "spec_from_file_location", _fake_spec)

        code, output = self._capture_output(
            lambda: agent_controller._handle_mark_ready(
                scope_override=None, json_output=False, force_mode=False
            )
        )

        assert code == 1, f"guard must fail closed on detector error: {output}"
        assert "archive_rename_guard_error" in output

    def test_check_mark_ready_archive_rename_blocks_on_dirty_detector(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """WOT-2026-011h robust barrier: `_check_mark_ready_archive_rename` itself
        must return a block dict (stable reason archive_rename_uncommitted) when the
        detector reports an uncommitted rename, and None when clean.

        This tests the guard helper DIRECTLY with an injected detector, so it is
        FAIL-without/PASS-with by construction: it does not depend on git seeding,
        the full mark-ready flow, or _MOTOR_ROOT resolution. If the 011h helper is
        removed (controller reverted), this test errors at attribute access; if the
        helper stops mapping a failed detector to the stable reason, it fails.
        """
        # The helper must exist (controller carries the 011h fix). With the
        # controller reverted (no 011h), this attribute is gone and the test errors.
        assert hasattr(agent_controller, "_check_mark_ready_archive_rename"), (
            "011h helper _check_mark_ready_archive_rename is missing"
        )

        # Use the REAL detector (delivery_hygiene_check) over a temp git repo.
        # _MOTOR_ROOT must carry the real script so the helper resolves it; PROJECT_ROOT
        # is the temp repo whose tree we make dirty/clean.
        real_motor_root = Path(agent_controller.__file__).resolve().parent.parent
        repo = tmp_path / "repo"
        self._init_git_repo(repo)
        monkeypatch.setattr(agent_controller, "_MOTOR_ROOT", real_motor_root)
        monkeypatch.setattr(agent_controller, "PROJECT_ROOT", repo)

        # CLEAN tree first -> helper must return None (no false positive).
        assert agent_controller._check_mark_ready_archive_rename() is None, (
            "clean tree must not trigger the archival-rename guard"
        )

        # Now create the REAL `D old + ?? new` limbo and re-check -> must block.
        self._inject_archival_limbo(repo)
        block = agent_controller._check_mark_ready_archive_rename()
        assert block is not None, (
            "guard must block when the archival rename is uncommitted"
        )
        assert block["reason"] == "archive_rename_uncommitted", block
        assert any(
            "origen:" in d or "STRATEGY_WT-2026-245b.md" in d for d in block["details"]
        ), f"diagnostic must name the renamed artifact: {block}"

    def test_pre_handoff_repo_destino_authority_tags_workspace(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """repo_destino-authority tickets must create M3 in the destination repo."""
        motor_repo = tmp_path / "motor"
        workspace = tmp_path / "workspace"
        self._init_git_repo(motor_repo)
        self._init_git_repo(workspace)
        self._create_execution_log(workspace)

        (workspace / ".agent" / "collaboration" / "work_plan.md").write_text(
            self._DESTINO_PLAN_CONTENT
        )
        subprocess.run(
            ["git", "add", ".agent"],
            cwd=workspace,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "Add operational state"],
            cwd=workspace,
            check=True,
            capture_output=True,
        )
        (workspace / "app.py").write_text("print('destino')\n")

        monkeypatch.setattr(agent_controller, "_MOTOR_ROOT", motor_repo)
        monkeypatch.setattr(agent_controller, "PROJECT_ROOT", workspace)
        monkeypatch.setattr(
            agent_controller,
            "read_file",
            lambda path: (
                self._DESTINO_PLAN_CONTENT
                if "work_plan" in str(path).lower()
                else (
                    "# Execution Log\n\n**Estado:** IN_PROGRESS\n"
                    if "execution_log" in str(path).lower()
                    else ""
                )
            ),
        )
        monkeypatch.setattr(
            agent_controller,
            "_ensure_active_builder_round",
            lambda plan_id: (True, 1, None),
        )
        monkeypatch.setattr(agent_controller, "BUS_AVAILABLE", False)
        monkeypatch.setattr(agent_controller, "_reset_circuit_breaker", lambda _: None)
        monkeypatch.setattr(
            agent_controller, "_capture_builder_session", lambda *a, **kw: None
        )
        monkeypatch.setattr(
            agent_controller,
            "get_changed_files",
            lambda: {str((workspace / "app.py").resolve())},
        )

        import bus.evidence

        monkeypatch.setattr(
            bus.evidence,
            "motor_uncommitted_productive",
            lambda root: set(),
        )

        code, output = self._capture_output(
            lambda: agent_controller._handle_pre_handoff(json_output=False)
        )

        assert code == 0, f"pre-handoff failed: {output}"

        tag_in_ws = subprocess.run(
            ["git", "rev-parse", f"checkpoint/review-{self._PLAN_ID}^{{}}"],
            capture_output=True,
            text=True,
            cwd=workspace,
        )
        assert tag_in_ws.returncode == 0, (
            f"Tag should exist in workspace: {tag_in_ws.stderr}"
        )

        tag_in_motor = subprocess.run(
            ["git", "rev-parse", f"checkpoint/review-{self._PLAN_ID}^{{}}"],
            capture_output=True,
            text=True,
            cwd=motor_repo,
        )
        assert tag_in_motor.returncode != 0, "Tag should NOT exist in motor repo"

    def test_mark_ready_repo_destino_authority_uses_workspace_checkpoint(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """repo_destino-authority mark-ready must not require a motor commit."""
        motor_repo = tmp_path / "motor"
        workspace = tmp_path / "workspace"
        self._init_git_repo(motor_repo)
        self._init_git_repo(workspace)
        self._create_execution_log(workspace)

        (workspace / ".agent" / "collaboration" / "work_plan.md").write_text(
            self._DESTINO_PLAN_CONTENT
        )
        subprocess.run(
            ["git", "add", ".agent"],
            cwd=workspace,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "Add operational state"],
            cwd=workspace,
            check=True,
            capture_output=True,
        )
        (workspace / "app.py").write_text("print('destino')\n")
        subprocess.run(
            ["git", "add", "app.py"], cwd=workspace, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", f"feat({self._PLAN_ID}): destination delivery"],
            cwd=workspace,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "git",
                "tag",
                "-a",
                f"checkpoint/review-{self._PLAN_ID}",
                "-m",
                f"Checkpoint M3 for {self._PLAN_ID}",
            ],
            cwd=workspace,
            check=True,
            capture_output=True,
        )

        self._seed_archival_detector(motor_repo)
        monkeypatch.setattr(agent_controller, "_MOTOR_ROOT", motor_repo)
        monkeypatch.setattr(agent_controller, "PROJECT_ROOT", workspace)
        monkeypatch.setattr(
            agent_controller,
            "read_file",
            lambda path: (
                self._DESTINO_PLAN_CONTENT
                if "work_plan" in str(path).lower()
                else (
                    "# Execution Log\n\n**Estado:** IN_PROGRESS\n"
                    if "execution_log" in str(path).lower()
                    else ""
                )
            ),
        )
        monkeypatch.setattr(
            agent_controller,
            "_ensure_active_builder_round",
            lambda plan_id: (True, 1, None),
        )
        monkeypatch.setattr(agent_controller, "BUS_AVAILABLE", False)
        monkeypatch.setattr(
            agent_controller, "_check_implementation_evidence", lambda plan_id: []
        )
        monkeypatch.setattr(
            agent_controller,
            "_run_pre_handoff_guard",
            lambda plan_id, json_output: {"valid": True},
        )
        monkeypatch.setattr(
            agent_controller, "_emit_builder_exit", lambda *a, **kw: None
        )
        monkeypatch.setattr(
            agent_controller, "_sync_mark_ready_targets", lambda *a, **kw: None
        )
        monkeypatch.setattr(agent_controller, "_reset_circuit_breaker", lambda _: None)
        monkeypatch.setattr(
            agent_controller, "_release_builder_lock", lambda *a, **kw: None
        )
        monkeypatch.setattr(
            agent_controller, "_auto_archive_closed_artifacts", lambda: None
        )

        code, output = self._capture_output(
            lambda: agent_controller._handle_mark_ready(
                scope_override=None, json_output=False, force_mode=False
            )
        )

        assert code == 0, f"mark-ready failed: {output}"
        assert "Destination scope" in output

    def test_mark_ready_blocks_when_checkpoint_missing_in_motor(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """--mark-ready must block when checkpoint tag is missing from repo_motor.

        Negative test: even if the workspace has a .git, the tag must be in
        motor_repo. Without the tag, mark-ready must fail.
        """
        # Setup: motor repo and workspace as separate directories
        motor_repo = tmp_path / "motor"
        workspace = tmp_path / "workspace"
        self._init_git_repo(motor_repo)
        self._init_git_repo(workspace)
        self._create_work_plan(workspace)
        self._create_execution_log(workspace)

        # Create a productive commit in motor repo (WITHOUT checkpoint tag)
        (motor_repo / "src").mkdir(parents=True, exist_ok=True)
        (motor_repo / "src" / "module.py").write_text("# productive change")
        subprocess.run(
            ["git", "add", "."], cwd=motor_repo, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", f"feat({self._PLAN_ID}): implement fix"],
            cwd=motor_repo,
            check=True,
            capture_output=True,
        )

        # Monkey-patch the controller to use our temp repos
        monkeypatch.setattr(agent_controller, "_MOTOR_ROOT", motor_repo)
        monkeypatch.setattr(agent_controller, "PROJECT_ROOT", workspace)

        # Patch read_file
        monkeypatch.setattr(
            agent_controller,
            "read_file",
            lambda path: (
                self._PLAN_CONTENT
                if "work_plan" in str(path).lower()
                else (
                    "# Execution Log\n\n**Estado:** IN_PROGRESS\n"
                    if "execution_log" in str(path).lower()
                    else ""
                )
            ),
        )

        # Patch _ensure_active_builder_round to pass
        monkeypatch.setattr(
            agent_controller,
            "_ensure_active_builder_round",
            lambda plan_id: (True, 1, None),
        )

        # Patch BUS_AVAILABLE to False
        monkeypatch.setattr(agent_controller, "BUS_AVAILABLE", False)

        # Patch _check_implementation_evidence to pass
        monkeypatch.setattr(
            agent_controller, "_check_implementation_evidence", lambda plan_id: []
        )

        # Patch _run_pre_handoff_guard to pass (guard doesn't check motor)
        monkeypatch.setattr(
            agent_controller,
            "_run_pre_handoff_guard",
            lambda plan_id, json_output: {"valid": True},
        )

        # Patch _read_deliverable_type to return "code"
        monkeypatch.setattr(
            agent_controller,
            "_read_deliverable_type",
            lambda content, default="code": "code",
        )

        # Run mark-ready — should fail because checkpoint tag is missing
        code, output = self._capture_output(
            lambda: agent_controller._handle_mark_ready(
                scope_override=None, json_output=False, force_mode=False
            )
        )

        assert code != 0, f"mark-ready should have blocked without checkpoint: {output}"
        assert (
            "No valid motor checkpoint" in output
            or "motor_checkpoint_missing" in output
        ), f"Expected motor checkpoint error: {output}"

    def test_non_code_ticket_not_blocked_by_motor_checkpoint_guard(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Non-code tickets must NOT be blocked by the external-motor checkpoint guard.

        Regression: the new _MOTOR_ROOT verification in _run_pre_handoff_guard()
        must skip documentation/research/analysis tickets, otherwise mark-ready
        would block them before reaching the non-code bypass in the motor scope gate.
        """
        # Setup: motor repo and workspace as separate directories
        motor_repo = tmp_path / "motor"
        workspace = tmp_path / "workspace"
        self._init_git_repo(motor_repo)
        self._init_git_repo(workspace)
        self._create_work_plan(workspace)
        self._create_execution_log(workspace)

        # Monkey-patch the controller to use our temp repos
        self._seed_archival_detector(motor_repo)
        monkeypatch.setattr(agent_controller, "_MOTOR_ROOT", motor_repo)
        monkeypatch.setattr(agent_controller, "PROJECT_ROOT", workspace)

        # Commit .agent in workspace so the guard doesn't report dirty tree
        subprocess.run(
            ["git", "add", ".agent"],
            cwd=workspace,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "Add .agent directory"],
            cwd=workspace,
            check=True,
            capture_output=True,
        )

        # Patch read_file to return a DOCUMENTATION plan
        _doc_plan = self._PLAN_CONTENT.replace(
            "deliverable_type:** code", "deliverable_type:** documentation"
        )
        monkeypatch.setattr(
            agent_controller,
            "read_file",
            lambda path: (
                _doc_plan
                if "work_plan" in str(path).lower()
                else (
                    "# Execution Log\n\n**Estado:** IN_PROGRESS\n"
                    if "execution_log" in str(path).lower()
                    else ""
                )
            ),
        )

        # Patch _ensure_active_builder_round to pass
        monkeypatch.setattr(
            agent_controller,
            "_ensure_active_builder_round",
            lambda plan_id: (True, 1, None),
        )

        # Patch BUS_AVAILABLE to False
        monkeypatch.setattr(agent_controller, "BUS_AVAILABLE", False)

        # Patch _check_implementation_evidence to pass
        monkeypatch.setattr(
            agent_controller, "_check_implementation_evidence", lambda plan_id: []
        )

        # Patch _emit_builder_exit to no-op
        monkeypatch.setattr(
            agent_controller, "_emit_builder_exit", lambda *a, **kw: None
        )

        # Patch _sync_mark_ready_targets to no-op
        monkeypatch.setattr(
            agent_controller, "_sync_mark_ready_targets", lambda *a, **kw: None
        )

        # Patch _reset_circuit_breaker to no-op
        monkeypatch.setattr(
            agent_controller, "_reset_circuit_breaker", lambda plan_id: None
        )

        # Patch _release_builder_lock to no-op
        monkeypatch.setattr(
            agent_controller, "_release_builder_lock", lambda *a, **kw: None
        )

        # Patch _auto_archive_closed_artifacts to no-op
        monkeypatch.setattr(
            agent_controller, "_auto_archive_closed_artifacts", lambda: None
        )

        # Patch _check_log_has_evidence to pass
        monkeypatch.setattr(agent_controller, "_check_log_has_evidence", lambda: True)

        # Patch _check_log_has_quality_gate_evidence to pass
        monkeypatch.setattr(
            agent_controller,
            "_check_log_has_quality_gate_evidence",
            lambda dt="code": True,
        )

        # Run mark-ready — must NOT block even though no checkpoint tag exists
        code, output = self._capture_output(
            lambda: agent_controller._handle_mark_ready(
                scope_override=None, json_output=False, force_mode=False
            )
        )

        assert code == 0, (
            f"Non-code mark-ready should pass without checkpoint: {output}"
        )

    @staticmethod
    def _capture_output(func):
        """Run func capturing stdout+stderr, return (exit_code, combined_text)."""
        from io import StringIO

        captured_out = StringIO()
        captured_err = StringIO()
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = captured_out
        sys.stderr = captured_err
        try:
            code = func()
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
        combined = captured_out.getvalue() + captured_err.getvalue()
        return code, combined

    @staticmethod
    def _capture_streams(func):
        """Run func capturing stdout+stderr separately, return (exit_code, out_text, err_text)."""
        from io import StringIO

        captured_out = StringIO()
        captured_err = StringIO()
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = captured_out
        sys.stderr = captured_err
        try:
            code = func()
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
        return code, captured_out.getvalue(), captured_err.getvalue()


# =============================================================================
# WT-2026-249a: CLI contract hardening — stderr vs returncode
# =============================================================================


class TestCliContractStaleOrphan:
    """WT-2026-249a: stale_builder_orphan must not write to stderr when exit 0."""

    _PLAN_ID = "WT-2026-249a"
    _PLAN_CONTENT = f"""# Work Plan

## Metadata
- **ID:** {_PLAN_ID}
- **Estado:** APPROVED

## Files Likely Touched
- .agent/agent_controller.py
"""

    def _setup(self, monkeypatch):
        """Minimal mocks: post-success bus state, active round mismatch."""
        monkeypatch.setattr(
            agent_controller,
            "read_file",
            lambda x: self._PLAN_CONTENT if "work_plan" in str(x).lower() else "",
        )
        monkeypatch.setattr(
            agent_controller,
            "_ensure_active_builder_round",
            lambda plan_id: (
                False,
                1,
                "stale Builder round 1; active round is 2",
            ),
        )
        monkeypatch.setattr(agent_controller, "BUS_AVAILABLE", True)
        emit_mock = MagicMock()
        monkeypatch.setattr(agent_controller, "event_bus", MagicMock(emit=emit_mock))
        # Simulate a post-success bus state (ticket already READY_FOR_REVIEW)
        mock_event = MagicMock()
        mock_event.to_dict.return_value = {
            "event_type": "STATE_CHANGED",
            "payload": {"to_state": "READY_FOR_REVIEW"},
        }
        agent_controller.event_bus.read_events.return_value = [mock_event]
        return emit_mock

    def test_stale_orphan_exit_0_stderr_empty(self, monkeypatch):
        """stale_builder_orphan exits 0 with empty stderr (WT-2026-249a)."""
        emit_mock = self._setup(monkeypatch)

        code, out_text, err_text = TestExternalMotorCheckpointTopology._capture_streams(
            lambda: agent_controller._handle_pre_handoff(json_output=False)
        )

        assert code == 0, f"Expected 0, got {code}"
        assert err_text == "", f"stderr must be empty, got: {err_text!r}"
        # Warning should be on stdout instead
        assert "[WARN]" in out_text, f"Warning must appear on stdout, got: {out_text!r}"
        # STALE_BUILDER_ORPHAN event must still be emitted
        orphan_events = [
            call
            for call in emit_mock.call_args_list
            if call.kwargs.get("event_type") == "STALE_BUILDER_ORPHAN"
        ]
        assert orphan_events, "Must emit STALE_BUILDER_ORPHAN event"

    def test_stale_orphan_no_handoff_blocked_event(self, monkeypatch):
        """stale_builder_orphan must NOT emit HANDOFF_BLOCKED when returning 0."""
        emit_mock = self._setup(monkeypatch)

        code, _out_text, _err_text = (
            TestExternalMotorCheckpointTopology._capture_streams(
                lambda: agent_controller._handle_pre_handoff(json_output=False)
            )
        )

        assert code == 0, f"Expected 0, got {code}"
        handoff_events = [
            call
            for call in emit_mock.call_args_list
            if call.kwargs.get("event_type") == "HANDOFF_BLOCKED"
        ]
        assert not handoff_events, "Must NOT emit HANDOFF_BLOCKED for orphan"


class TestCliContractSessionClose:
    """WT-2026-249a: session close wrapper must classify stderr by returncode."""

    _TICKET = "WT-2026-249a"

    def _setup(self, monkeypatch, tmp_path, subprocess_result):
        """Set up mocks for _handle_session_close with a controlled subprocess result."""
        monkeypatch.setattr(
            agent_controller,
            "read_file",
            lambda path: (
                "# State\nEstado actual: IN_PROGRESS\n"
                if path == agent_controller.STATE_FILE.resolve()
                else ""
            ),
        )
        monkeypatch.setattr(agent_controller, "write_file", lambda p, c: None)
        # Create scripts/session_closeout.py
        script_dir = tmp_path / "scripts"
        script_dir.mkdir()
        (script_dir / "session_closeout.py").write_text("")
        monkeypatch.setattr(agent_controller, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(
            agent_controller.subprocess,
            "run",
            MagicMock(return_value=subprocess_result),
        )

    def test_session_close_success_no_stderr_propagation(self, monkeypatch, tmp_path):
        """Session close with returncode 0 must NOT propagate stderr."""
        mock_result = MagicMock(
            returncode=0,
            stdout="[OK] Session close completed\n",
            stderr="[WARN] Non-fatal orphan file detected\n",
        )
        self._setup(monkeypatch, tmp_path, mock_result)

        code, out_text, err_text = TestExternalMotorCheckpointTopology._capture_streams(
            lambda: agent_controller._handle_session_close(
                dry_run=False,
                skip_slow=False,
                ticket=None,
                tickets=None,
                force_mode=False,
                json_output=False,
            )
        )

        assert code == 0, f"Expected 0, got {code}"
        # stdout should contain the subprocess output
        assert "[OK] Session close completed" in out_text
        # stderr must be empty despite subprocess having stderr warnings
        assert err_text == "", (
            f"stderr must be empty for returncode==0, got: {err_text!r}"
        )

    def test_session_close_failure_propagates_stderr(self, monkeypatch, tmp_path):
        """Session close with returncode != 0 must propagate stderr."""
        mock_result = MagicMock(
            returncode=1,
            stdout="",
            stderr="[ERROR] Closeout script failed: timeout\n",
        )
        self._setup(monkeypatch, tmp_path, mock_result)

        code, _out_text, err_text = (
            TestExternalMotorCheckpointTopology._capture_streams(
                lambda: agent_controller._handle_session_close(
                    dry_run=False,
                    skip_slow=False,
                    ticket=None,
                    tickets=None,
                    force_mode=False,
                    json_output=False,
                )
            )
        )

        assert code == 1, f"Expected 1, got {code}"
        # stderr must contain the subprocess error
        assert "[ERROR] Closeout script failed: timeout" in err_text, (
            f"stderr must contain subprocess error, got: {err_text!r}"
        )


# =============================================================================
# WT-2026-249b: BUILDER_BRIEF_ exclusion from workspace live-surface guard
# =============================================================================


class TestBuilderBriefExclusion:
    """WT-2026-249b: BUILDER_BRIEF_ must be treated as live surface (non-blocking)
    while UPSTREAM_LEARNINGS.md must remain outside exclusions.

    [NON-REVERSE-CLASSICAL: test of guard prefix logic — the fix is a
    one-line constant addition, behavioural coverage matters.]
    """

    def test_is_live_surface_accepts_builder_brief(self, tmp_path):
        """_is_live_surface() returns True for BUILDER_BRIEF_WT-*.md paths."""
        brief_path = str(
            tmp_path / ".agent" / "collaboration" / "BUILDER_BRIEF_WT-2026-249b.md"
        )
        result = agent_controller._is_live_surface(
            brief_path,
            tmp_path,
            live_files=set(),
            live_dirs=set(),
        )
        assert result is True, "BUILDER_BRIEF_ path should be a live surface, got False"

    def test_is_live_surface_rejects_upstream_learnings(self, tmp_path):
        """_is_live_surface() returns False for UPSTREAM_LEARNINGS.md paths."""
        learnings_path = str(
            tmp_path / ".agent" / "runtime" / "memory" / "UPSTREAM_LEARNINGS.md"
        )
        result = agent_controller._is_live_surface(
            learnings_path,
            tmp_path,
            live_files=set(),
            live_dirs=set(),
        )
        assert result is False, (
            "UPSTREAM_LEARNINGS.md must NOT be a live surface, got True"
        )

    @staticmethod
    def _make_pre_handoff_git_mock():
        """Standard git mock for pre-handoff that succeeds on all operations."""

        def git_mock(cmd, *args, **kwargs):
            cmd_str = " ".join(cmd)
            if "git show HEAD:.opencode/opencode.json" in cmd_str:
                return MagicMock(returncode=1, stdout=b"", stderr=b"")
            if "rev-parse" in cmd_str and "checkpoint" in cmd_str and "^{}" in cmd_str:
                return MagicMock(returncode=1, stdout="", stderr="")
            if "rev-parse HEAD" in cmd_str:
                return MagicMock(returncode=0, stdout="abc123\n", stderr="")
            if len(cmd) >= 2 and cmd[:2] == ["git", "add"]:
                return MagicMock(returncode=0, stdout="", stderr="")
            if len(cmd) >= 2 and cmd[:2] == ["git", "commit"]:
                return MagicMock(
                    returncode=0, stdout="[main abc123] commit\n", stderr=""
                )
            if len(cmd) >= 3 and cmd[1] == "tag" and cmd[2] in ("-a", "-d"):
                return MagicMock(returncode=0, stdout="", stderr="")
            if len(cmd) >= 2 and cmd[:2] == ["git", "status"]:
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        return git_mock

    @staticmethod
    def _patch_git_exists(monkeypatch):
        """Patch Path.exists to simulate .git directory."""
        project_root = agent_controller.PROJECT_ROOT.resolve()
        git_path = project_root / ".git"
        original_exists = Path.exists

        def _patched_exists(self_path):
            if str(self_path) == str(git_path):
                return True
            return original_exists(self_path)

        monkeypatch.setattr(Path, "exists", _patched_exists)

    def test_builder_brief_does_not_block_pre_handoff(self, monkeypatch, tmp_path):
        """--pre-handoff must NOT block when the only untracked file is a BUILDER_BRIEF_."""
        from agent_controller import _handle_pre_handoff

        project_root = agent_controller.PROJECT_ROOT.resolve()
        brief_file = str(
            project_root / ".agent" / "collaboration" / "BUILDER_BRIEF_WT-2026-249b.md"
        )

        # The brief file is excluded via _WORKSPACE_EXCLUDED_PREFIXES,
        # so it is removed from the "changed" set before the scope check.
        monkeypatch.setattr(
            agent_controller,
            "read_file",
            lambda x: (
                TestPreHandoff._PLAN_CONTENT if "work_plan" in str(x).lower() else ""
            ),
        )
        monkeypatch.setattr(
            agent_controller,
            "parse_files_likely_touched",
            lambda x: {brief_file},
        )
        monkeypatch.setattr(
            agent_controller,
            "get_changed_files",
            lambda: {brief_file},
        )
        # Same mock-escape closure as TestPreHandoff._setup_basic_mocks: patch
        # the scope_gate seam that assert_work_plan_committed actually calls.
        monkeypatch.setattr(
            motor_checkpoint.scope_gate,
            "get_changed_files",
            lambda *, project_root, motor_root, run_fn=None: {brief_file},
        )
        self._patch_git_exists(monkeypatch)

        # Patch pre-handoff guard and round check to pass
        monkeypatch.setattr(
            agent_controller,
            "_run_pre_handoff_guard",
            lambda plan_id, json_output: {"valid": True},
        )
        monkeypatch.setattr(
            agent_controller,
            "_ensure_active_builder_round",
            lambda plan_id: (True, 1, None),
        )
        monkeypatch.setattr(agent_controller, "BUS_AVAILABLE", False)

        # Patch git operations
        monkeypatch.setattr(
            agent_controller.subprocess, "run", self._make_pre_handoff_git_mock()
        )

        code, output = TestExternalMotorCheckpointTopology._capture_output(
            lambda: _handle_pre_handoff(json_output=False)
        )

        assert code == 0, (
            f"pre-handoff should pass when only BUILDER_BRIEF_ is untracked: "
            f"exit={code}, output={output}"
        )
        assert "Pre-handoff complete" in output, (
            f"Expected success message in output: {output}"
        )

    def test_upstream_learnings_not_in_excluded_prefixes(self):
        """UPSTREAM_LEARNINGS.md must NOT appear in _WORKSPACE_EXCLUDED_PREFIXES."""
        excluded = agent_controller._WORKSPACE_EXCLUDED_PREFIXES
        for prefix in excluded:
            assert "UPSTREAM_LEARNINGS" not in prefix, (
                f"UPSTREAM_LEARNINGS must not be in excluded prefixes, found: {prefix}"
            )


class TestDeliverableTypeFileCongruence:
    """H-009: warn when a doc-type ticket lists a code file as a deliverable.

    Single-direction, informational (never blocking) check. The false-positive
    guard is critical: a .py listed only under '## Read/inspect only' is a source
    to read, NOT a deliverable, and must NOT warn.
    """

    def test_doc_type_with_code_deliverable_warns(self):
        import agent_controller

        plan = (
            "# WP\n"
            "- **deliverable_type:** documentation\n"
            "## Files Likely Touched\n"
            "- docs/GUIDE.md\n"
            "- scripts/thing.py\n"
        )
        warnings = agent_controller._check_deliverable_type(plan)
        assert warnings, "doc-type ticket with a .py deliverable must warn"
        assert "scripts/thing.py" in warnings[0]
        assert "code deliverable" in warnings[0].lower()

    def test_doc_type_code_only_under_read_only_does_not_warn(self):
        """The .py is a source to read, not produced -> no false positive."""
        import agent_controller

        plan = (
            "# WP\n"
            "- **deliverable_type:** documentation\n"
            "## Builder\n"
            "- docs/REPORT.md\n"
            "## Read/inspect only\n"
            "- scripts/source.py\n"
        )
        assert agent_controller._check_deliverable_type(plan) == []

    def test_code_type_with_py_does_not_warn(self):
        """Single-direction: code/mixed are never flagged for listing .py."""
        import agent_controller

        plan = (
            "# WP\n"
            "- **deliverable_type:** code\n"
            "## Files Likely Touched\n"
            "- scripts/feature.py\n"
        )
        assert agent_controller._check_deliverable_type(plan) == []

    def test_research_type_with_only_docs_does_not_warn(self):
        import agent_controller

        plan = (
            "# WP\n"
            "- **deliverable_type:** research\n"
            "## Files Likely Touched\n"
            "- .agent/runtime/compare/report.md\n"
        )
        assert agent_controller._check_deliverable_type(plan) == []


class TestValidateJsonTotals:
    """WOT-2026-014q: _handle_validate JSON must expose total_errors and total_warnings as ints."""

    def test_total_keys_expose_zero_not_category_count(self, tmp_path, monkeypatch):
        """total_errors and total_warnings must be 0 when all categories are empty lists.

        Anti-floor: with 7 empty categories, a naive len(errors) would return 7,
        not 0. The fix exposes total_errors = sum(len(v) for v in errors.values()) = 0.
        Without the fix, data["total_errors"] raises KeyError.
        """
        import agent_controller

        # validate_state_files returns 7 categories all with empty lists
        # A broken consumer counting len(errors) would get 7, not 0.
        seven_empty_categories = {
            "cat_a": [],
            "cat_b": [],
            "cat_c": [],
            "cat_d": [],
            "cat_e": [],
            "cat_f": [],
            "cat_g": [],
        }
        monkeypatch.setattr(
            agent_controller, "validate_state_files", lambda: seven_empty_categories
        )

        # All other collaborators return neutral/empty results
        # (same technique as TestTicketProseIntegration)
        fake_work_plan = tmp_path / "work_plan.md"
        fake_work_plan.write_text("# Plan\n", encoding="utf-8")
        fake_collab = tmp_path / "collab"
        fake_collab.mkdir()
        monkeypatch.setattr(agent_controller, "WORK_PLAN", fake_work_plan)
        monkeypatch.setattr(agent_controller, "get_collab_dir", lambda: fake_collab)

        monkeypatch.setattr(
            agent_controller, "_collect_deliverable_type_warnings", lambda x: {}
        )
        monkeypatch.setattr(agent_controller, "read_file", lambda x: "")
        monkeypatch.setattr(agent_controller, "get_status", lambda x, y: "APPROVED")
        monkeypatch.setattr(
            agent_controller, "_check_scope_for_validate", lambda x, y: ([], [])
        )
        monkeypatch.setattr(agent_controller, "_check_bus_drift", lambda x, y: [])
        monkeypatch.setattr(
            agent_controller,
            "_check_invariants",
            lambda x, y, z: {"errors": [], "warnings": []},
        )
        monkeypatch.setattr(
            agent_controller,
            "_validate_contract_gap_coherence",
            lambda x: [],
        )

        # Mock scripts.validate_ticket_prose (imported dynamically inside _handle_validate)
        # Same technique as TestTicketProseIntegration: inject into sys.modules
        mock_prose_module = type(
            "MockProseModule",
            (),
            {
                "validate_ticket_prose": staticmethod(
                    lambda work_plan_path, collab_dir: {
                        "warnings": [],
                        "warning_count": 0,
                    }
                )
            },
        )()
        monkeypatch.setitem(
            sys.modules, "scripts.validate_ticket_prose", mock_prose_module
        )

        # Capture stdout and invoke _handle_validate
        from io import StringIO

        captured = StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            exit_code = agent_controller._handle_validate(json_output=True)
        finally:
            sys.stdout = old_stdout

        assert exit_code == 0
        data = json.loads(captured.getvalue())
        # Strict equality: 7 empty categories -> total 0, not 7
        assert data["total_errors"] == 0
        assert data["total_warnings"] == 0


# ======================================================================
# WOT-2026-019d: PII regression tests for the 12 str(exc)/{exc} sites
# corrected to compose their detail via scope_gate._relativize_scope_path
# instead of exposing exc.filename/str(exc) raw. Follow-up of WOT-2026-019b.
# ======================================================================


class TestPiiSafeExceptionSites:
    """WOT-2026-019d: one regression test per PII-risk site (12 total).

    Each test forces a real OSError at the concrete I/O point of a site, with
    exc.filename set to an absolute path under tmp_path, then asserts the
    resulting message/detail:
    - Does NOT contain the simulated absolute path in full.
    - Does NOT contain str(Path.home()) (the real local username).
    - DOES preserve strerror/errno diagnostic information.

    Mutation-safety note: on Windows, ``str(OSError(errno, strerror,
    filename))`` renders the filename with DOUBLE backslashes
    (``C:\\\\Users\\\\...``), while the test builds ``absolute_path_str`` with
    single backslashes (``str(path)``). A naive
    ``assert absolute_path_str not in captured.out`` is a FALSE-GREEN: it
    passes both with and without the fix, because the separators never match
    even when the raw path leaked. ``_assert_no_pii_leak`` below normalizes
    both sides (collapsing doubled backslashes) AND independently checks a
    bare marker string with no path separators (e.g. a unique tmp_path
    component, standing in for the real local username), which is immune to
    the separator-escaping problem and is the real barrier that must bite the
    mutation.
    """

    @staticmethod
    def _assert_no_pii_leak(output: str, absolute_path_str: str, marker: str) -> None:
        """Assert `output` leaks neither the simulated absolute path nor the
        bare sensitive marker (e.g. username/tmp dir name), immune to
        Windows' doubled-backslash str(OSError) rendering (WOT-2026-019d
        mutation-safety fix)."""
        normalized = output.replace("\\\\", "\\")
        assert absolute_path_str not in output
        assert absolute_path_str not in normalized
        assert marker not in output
        assert marker not in normalized

    def test_capture_builder_session_oserror_detail_has_no_absolute_path(
        self, tmp_path, monkeypatch, capsys
    ):
        """Site 900 (_capture_builder_session): session_path.write_text can
        raise OSError; the except must compose the detail via
        scope_gate._relativize_scope_path, never str(exc) raw."""
        import sqlite3

        import agent_controller as ac

        monkeypatch.setattr(ac, "PROJECT_ROOT", tmp_path)

        home_stub = tmp_path / "home_stub"
        home_stub.mkdir()
        monkeypatch.setattr(Path, "home", lambda: home_stub)
        monkeypatch.setattr(ac.os.environ, "get", lambda *a: "")

        # This is the FIRST candidate _capture_builder_session checks
        # (home_path / ".local" / "share" / "opencode" / "opencode.db").
        db_path = home_stub / ".local" / "share" / "opencode" / "opencode.db"
        db_path.parent.mkdir(parents=True)
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE session (id TEXT, title TEXT, time_updated TEXT)")
        conn.execute(
            "INSERT INTO session VALUES (?, ?, ?)",
            ("sess-1", "WOT-2026-019d-R1", "2026-07-05T00:00:00"),
        )
        conn.commit()
        conn.close()

        session_path = tmp_path / "runtime" / "builder_session.json"
        monkeypatch.setattr(ac, "_BUILDER_SESSION_PATH", session_path)

        absolute_path_str = str(session_path)
        real_write_text = Path.write_text

        def fake_write_text(self, *args, **kwargs):
            if self == session_path:
                raise OSError(13, "Permission denied", absolute_path_str)
            return real_write_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "write_text", fake_write_text)

        result = ac._capture_builder_session("WOT-2026-019d", 1)

        assert result is None
        captured = capsys.readouterr()
        self._assert_no_pii_leak(captured.out, absolute_path_str, tmp_path.name)
        assert "<REPO_ROOT>" in captured.out or "builder_session.json" in captured.out
        assert "Permission denied" in captured.out
        assert "13" in captured.out

    def test_create_human_gate_approval_request_oserror_detail_has_no_absolute_path(
        self, tmp_path, monkeypatch, capsys
    ):
        """Site 1007 (_create_human_gate_approval_request):
        store.create_request persists to a file; OSError must be composed
        safely."""
        import agent_controller as ac

        monkeypatch.setattr(ac, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(ac, "APPROVAL_SYSTEM_AVAILABLE", True)

        store_path = tmp_path / "runtime" / "approvals" / "store.json"
        absolute_path_str = str(store_path)

        class FakeStore:
            def create_request(self, **kwargs):
                raise OSError(13, "Permission denied", absolute_path_str)

        monkeypatch.setattr(ac, "_get_approval_store", lambda: FakeStore())
        monkeypatch.setattr(ac, "get_human_gate_timeout", lambda: 3600)

        result = ac._create_human_gate_approval_request("WOT-2026-019d")

        assert result is False
        captured = capsys.readouterr()
        self._assert_no_pii_leak(captured.err, absolute_path_str, tmp_path.name)
        assert "<REPO_ROOT>" in captured.err or "store.json" in captured.err
        assert "Permission denied" in captured.err
        assert "13" in captured.err

    def test_auto_archive_closed_artifacts_oserror_detail_has_no_absolute_path(
        self, tmp_path, monkeypatch, capsys
    ):
        """Site 1041 (_auto_archive_closed_artifacts):
        archive_collaboration_artifacts moves files under COLLAB_DIR; OSError
        must be composed safely."""
        import importlib.util

        import agent_controller as ac

        monkeypatch.setattr(ac, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(ac, "_MOTOR_ROOT", tmp_path)
        monkeypatch.setattr(ac, "COLLAB_DIR", tmp_path / "collaboration")

        script_path = tmp_path / "collaboration" / "some_archived_file.md"
        absolute_path_str = str(script_path)

        real_spec_from_file = importlib.util.spec_from_file_location

        def fake_spec(name, location, *a, **kw):
            if name == "archive_collaboration_artifacts":
                raise OSError(13, "Permission denied", absolute_path_str)
            return real_spec_from_file(name, location, *a, **kw)

        monkeypatch.setattr(importlib.util, "spec_from_file_location", fake_spec)

        ac._auto_archive_closed_artifacts()

        captured = capsys.readouterr()
        self._assert_no_pii_leak(captured.out, absolute_path_str, tmp_path.name)
        assert "<REPO_ROOT>" in captured.out or "some_archived_file.md" in captured.out
        assert "Permission denied" in captured.out
        assert "13" in captured.out

    def test_check_mark_ready_archive_rename_oserror_detail_has_no_absolute_path(
        self, tmp_path, monkeypatch
    ):
        """Site 1085 (_check_mark_ready_archive_rename):
        check_archive_rename_complete inspects the file tree; OSError must be
        composed safely in the returned block dict."""
        import importlib.util

        import agent_controller as ac

        project_root = tmp_path / "repo"
        (project_root / ".git").mkdir(parents=True)
        monkeypatch.setattr(ac, "PROJECT_ROOT", project_root)
        monkeypatch.setattr(ac, "_MOTOR_ROOT", project_root)

        script_path = project_root / "some_dir" / "some_file.md"
        absolute_path_str = str(script_path)

        real_spec_from_file = importlib.util.spec_from_file_location

        def fake_spec(name, location, *a, **kw):
            if name == "delivery_hygiene_check":
                raise OSError(13, "Permission denied", absolute_path_str)
            return real_spec_from_file(name, location, *a, **kw)

        monkeypatch.setattr(importlib.util, "spec_from_file_location", fake_spec)

        block = ac._check_mark_ready_archive_rename()

        assert block is not None
        assert block["reason"] == "archive_rename_guard_error"
        details = " ".join(block["details"])
        self._assert_no_pii_leak(details, absolute_path_str, tmp_path.name)
        assert "<REPO_ROOT>" in details or "some_file.md" in details
        assert "Permission denied" in details
        assert "13" in details

    def test_validate_contract_gap_coherence_bus_read_oserror_detail_has_no_absolute_path(
        self, tmp_path, monkeypatch
    ):
        """Site 1888 (_validate_contract_gap_coherence, first except):
        bus.read_events -> _read_raw_events does events_path.read_text;
        OSError must be composed safely."""
        import agent_controller as ac

        monkeypatch.setattr(ac, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(ac, "BUS_AVAILABLE", True)

        events_path = tmp_path / "runtime" / "events" / "events.jsonl"
        absolute_path_str = str(events_path)

        class FakeBus:
            def read_events(self, ticket_id=None, event_type=None):
                raise OSError(13, "Permission denied", absolute_path_str)

        monkeypatch.setattr(ac, "_get_event_bus", lambda: FakeBus())

        plan_content = (
            "# Work Plan\n## Metadata\n- **ID:** WOT-2026-019d\n"
            "- **Estado:** APPROVED\n"
        )
        errors = ac._validate_contract_gap_coherence(plan_content)

        assert errors, "expected a CONTRACT_GAP coherence error"
        joined = " ".join(errors)
        self._assert_no_pii_leak(joined, absolute_path_str, tmp_path.name)
        assert "<REPO_ROOT>" in joined or "events.jsonl" in joined
        assert "Permission denied" in joined
        assert "13" in joined

    def test_validate_contract_gap_coherence_cg_scan_oserror_detail_has_no_absolute_path(
        self, tmp_path, monkeypatch
    ):
        """Site 1910 (_validate_contract_gap_coherence, second except):
        (contract_gaps_dir / cg_pattern).exists() can re-raise OSError (e.g.
        EACCES); OSError must be composed safely."""
        import agent_controller as ac

        monkeypatch.setattr(ac, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(ac, "BUS_AVAILABLE", True)

        class EmptyBus:
            def read_events(self, ticket_id=None, event_type=None):
                return []

        monkeypatch.setattr(ac, "_get_event_bus", lambda: EmptyBus())
        monkeypatch.setattr(ac, "get_agent_dir", lambda: tmp_path / ".agent")

        cg_path = (
            tmp_path / ".agent" / "planning" / "contract_gaps" / "CG-WOT-2026-019d.md"
        )
        absolute_path_str = str(cg_path)
        real_exists = Path.exists

        def fake_exists(self):
            if self == cg_path:
                raise OSError(13, "Permission denied", absolute_path_str)
            return real_exists(self)

        monkeypatch.setattr(Path, "exists", fake_exists)

        plan_content = (
            "# Work Plan\n## Metadata\n- **ID:** WOT-2026-019d\n"
            "- **Estado:** APPROVED\n"
        )
        errors = ac._validate_contract_gap_coherence(plan_content)

        assert errors, "expected a CONTRACT_GAP coherence error"
        joined = " ".join(errors)
        self._assert_no_pii_leak(joined, absolute_path_str, tmp_path.name)
        assert "<REPO_ROOT>" in joined or "CG-WOT-2026-019d.md" in joined
        assert "Permission denied" in joined
        assert "13" in joined

    def test_create_findings_file_oserror_detail_has_no_absolute_path(
        self, tmp_path, monkeypatch, capsys
    ):
        """Site 2219 (create_findings_file): write_file does open(path, 'w');
        OSError must be composed safely."""
        import agent_controller as ac

        monkeypatch.setattr(ac, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(ac, "COLLAB_DIR", tmp_path / "collaboration")
        monkeypatch.setattr(ac, "AGENT_DIR", tmp_path / ".agent")

        findings_path = tmp_path / "collaboration" / "findings.md"
        absolute_path_str = str(findings_path)

        def fake_write_file(path, content):
            if path == findings_path:
                raise OSError(13, "Permission denied", absolute_path_str)

        monkeypatch.setattr(ac, "write_file", fake_write_file)

        result = ac.create_findings_file("WOT-2026-019d")

        assert result == findings_path
        captured = capsys.readouterr()
        self._assert_no_pii_leak(captured.out, absolute_path_str, tmp_path.name)
        assert "<REPO_ROOT>" in captured.out or "findings.md" in captured.out
        assert "Permission denied" in captured.out
        assert "13" in captured.out

    def test_run_pre_handoff_guard_oserror_detail_has_no_absolute_path(
        self, tmp_path, monkeypatch, capsys
    ):
        """Sites 2890/2891 (_run_pre_handoff_guard, single except block):
        read_file(WORK_PLAN) can raise OSError; a single fix must cover BOTH
        uses of exc (the print and the returned warnings list)."""
        import agent_controller as ac

        monkeypatch.setattr(ac, "PROJECT_ROOT", tmp_path)

        work_plan_path = tmp_path / "work_plan.md"
        absolute_path_str = str(work_plan_path)

        def fake_read_file(path):
            raise OSError(13, "Permission denied", absolute_path_str)

        monkeypatch.setattr(ac, "read_file", fake_read_file)
        monkeypatch.setattr(ac, "WORK_PLAN", work_plan_path)

        result = ac._run_pre_handoff_guard("WOT-2026-019d", json_output=False)

        assert result == {
            "valid": True,
            "warnings": [w for w in result["warnings"] if "Guard execution error" in w],
        }
        captured = capsys.readouterr()
        warnings_joined = " ".join(result["warnings"])
        self._assert_no_pii_leak(captured.out, absolute_path_str, tmp_path.name)
        self._assert_no_pii_leak(warnings_joined, absolute_path_str, tmp_path.name)
        assert "<REPO_ROOT>" in captured.out or "work_plan.md" in captured.out
        assert "Permission denied" in captured.out
        assert "13" in captured.out

    def test_handle_reopen_terminal_ticket_projection_sync_oserror_detail_has_no_absolute_path(
        self, tmp_path, monkeypatch, capsys
    ):
        """Site 5342 (_handle_reopen_terminal_ticket): sync_state_projection
        does state_md_path.write_text; OSError must be composed safely."""
        import agent_controller as ac

        ticket_id = "WT-2026-208"
        work_plan_content = (
            "# Work Ticket\n## Metadata\n- **ID:** WT-2026-208\n"
            "- **Estado:** APPROVED\n"
        )

        class FakeEvent:
            def __init__(self):
                self.payload = {"from_state": "IN_PROGRESS", "to_state": "COMPLETED"}

            def to_dict(self):
                return {"event_type": "STATE_CHANGED", "payload": self.payload}

        class FakeBus:
            def __init__(self):
                self.emits = []

            def read_events(self, ticket_id=None, event_type=None):
                return [FakeEvent()]

            def emit(self, *args, **kwargs):
                self.emits.append((args, kwargs))
                return object()

        monkeypatch.setattr(ac, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(
            ac,
            "read_file",
            lambda p: work_plan_content if "work_plan" in str(p) else "",
        )
        monkeypatch.setattr(ac, "BUS_AVAILABLE", True)
        monkeypatch.setattr(ac, "event_bus", FakeBus())
        monkeypatch.setattr(ac, "update_log_status", lambda *_args: True)
        monkeypatch.setattr(ac, "get_runtime_dir", lambda: tmp_path / "runtime")
        monkeypatch.setattr(ac, "get_collab_dir", lambda: tmp_path / "collaboration")

        state_md_path = tmp_path / "collaboration" / "STATE.md"
        absolute_path_str = str(state_md_path)

        def fake_sync_state_projection(**kwargs):
            raise OSError(13, "Permission denied", absolute_path_str)

        monkeypatch.setitem(
            sys.modules,
            "scripts.state_projection_sync",
            type(
                "MockSyncModule",
                (),
                {"sync_state_projection": staticmethod(fake_sync_state_projection)},
            )(),
        )

        rc = ac._handle_reopen_terminal_ticket(ticket_id, False)

        assert rc == 0
        captured = capsys.readouterr()
        self._assert_no_pii_leak(captured.err, absolute_path_str, tmp_path.name)
        assert "<REPO_ROOT>" in captured.err or "STATE.md" in captured.err
        assert "Permission denied" in captured.err
        assert "13" in captured.err

    def test_handle_session_close_subprocess_oserror_detail_has_no_absolute_path(
        self, tmp_path, monkeypatch, capsys
    ):
        """Site 5895 (_handle_session_close): subprocess.run raises
        FileNotFoundError (an OSError subclass) with .filename absolute when
        the script/interpreter is missing; OSError must be composed safely."""
        import agent_controller as ac

        monkeypatch.setattr(ac, "PROJECT_ROOT", tmp_path)

        script_path = tmp_path / "scripts" / "session_closeout.py"
        absolute_path_str = str(script_path)

        def fake_run(cmd, **kwargs):
            raise FileNotFoundError(2, "No such file or directory", absolute_path_str)

        monkeypatch.setattr(ac.subprocess, "run", fake_run)
        monkeypatch.setattr(
            ac, "read_file", lambda path: "Estado actual: IN_PROGRESS\n"
        )

        code = ac._handle_session_close(
            dry_run=False,
            skip_slow=False,
            ticket=None,
            tickets=None,
            force_mode=False,
            json_output=False,
        )

        assert code == 1
        captured = capsys.readouterr()
        self._assert_no_pii_leak(captured.err, absolute_path_str, tmp_path.name)
        assert "<REPO_ROOT>" in captured.err or "session_closeout.py" in captured.err
        assert "No such file or directory" in captured.err
        assert "2" in captured.err

    def test_handle_main_action_scanner_oserror_detail_has_no_absolute_path(
        self, tmp_path, monkeypatch, capsys
    ):
        """Site 5925 (_handle_main_action): context_dir.mkdir/
        output_path.write_text can raise OSError; OSError must be composed
        safely."""
        import agent_controller as ac

        monkeypatch.setattr(ac, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(ac, "SESSION_TRACKER_AVAILABLE", False)
        monkeypatch.setattr(ac, "SCANNER_AVAILABLE", True)

        context_dir = tmp_path / "context"
        absolute_path_str = str(context_dir)

        def fake_scan_project(*args, **kwargs):
            return {}

        monkeypatch.setattr(ac, "scan_project", fake_scan_project)
        monkeypatch.setattr(ac, "get_context_dir", lambda: context_dir)

        def fake_mkdir(self, **kwargs):
            if self == context_dir:
                raise OSError(13, "Permission denied", absolute_path_str)

        monkeypatch.setattr(Path, "mkdir", fake_mkdir)

        # Neutralize downstream best-effort collaborators so the test focuses
        # on the scanner except branch only.
        monkeypatch.setattr(
            ac, "validate_state_files", lambda: {"notifications.md": []}
        )
        monkeypatch.setattr(ac, "archive_old_notifications", lambda: None)
        monkeypatch.setattr(
            ac, "determine_next_action", lambda **kw: {"action": "NONE"}
        )
        monkeypatch.setattr(ac, "should_overwrite_turn", lambda *a, **kw: False)

        code = ac._handle_main_action(
            skip_gates=False,
            strict_mode=False,
            json_output=True,
            reset_turn_mode=False,
        )

        assert code == 0
        captured = capsys.readouterr()
        self._assert_no_pii_leak(captured.out, absolute_path_str, tmp_path.name)
        assert "<REPO_ROOT>" in captured.out or "context" in captured.out
        assert "Permission denied" in captured.out
        assert "13" in captured.out
