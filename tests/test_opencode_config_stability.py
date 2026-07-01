"""WT-2026-248a: Tests para estabilidad de .opencode/opencode.json (BOM drift).

Cobertura:
1. Camino feliz: diff vacio tras restauracion BOM via launcher finally-block
2. Camino de fallo/abort: --pre-handoff bloquea cambio semantico real
3. Prueba negativa: cambio semantico en opencode.json -> --pre-handoff NO autocorrige
4. Mensaje de stderr de autocorreccion BOM

WOT-2026-016h: los tests que ejercen `--pre-handoff` corren AHORA in-process contra
un MOTOR TEMPORAL (tmp_path) con `_MOTOR_ROOT`/`PROJECT_ROOT`/`WORK_PLAN`/`EXEC_LOG`
monkeypatcheados. Antes lanzaban `agent_controller.py --pre-handoff` como SUBPROCESO
contra el motor REAL (`_MOTOR_ROOT` derivado de __file__), lo que escribia en el
`events.jsonl` real del motor y disparaba el guard de aislamiento
(`_isolate_controller_event_bus`, tests/conftest.py) en TEARDOWN (5 ERRORS). El bus
del subproceso se resuelve desde el motor-root derivado de __file__ y NO es
redirigible por `--project-root`; la unica forma de aislarlo es que el motor-root
apunte a un repo temporal (patron canonico de tests/test_pre_handoff_multirepo.py).
"""

import base64
import json
import subprocess
from pathlib import Path

import pytest

from tests.test_pre_handoff_guard import init_git_repo


# Motor root REAL (donde vive .opencode/opencode.json de referencia)
_MOTOR_ROOT = Path(__file__).resolve().parent.parent
_OPENCODE_PATH = _MOTOR_ROOT / ".opencode" / "opencode.json"
_BOM = b"\xef\xbb\xbf"


# ============================================================================
# Helpers
# ============================================================================


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=30,
    )


def _real_head_opencode_bytes() -> bytes:
    """Return the exact bytes of the REAL motor .opencode/opencode.json at HEAD.

    Used only as realistic seed content for the temp motor; the tests never
    mutate the real file.
    """
    result = subprocess.run(
        ["git", "show", "HEAD:.opencode/opencode.json"],
        capture_output=True,
        cwd=_MOTOR_ROOT,
        timeout=10,
    )
    assert result.returncode == 0, f"git show failed: {result.stderr.decode()}"
    return result.stdout


class _TempMotor:
    """A temporary motor repo with a committed .opencode/opencode.json + work_plan.

    Running ``agent_controller._handle_pre_handoff`` in-process with
    ``_MOTOR_ROOT`` pointed here resolves the event bus to this temp dir, so the
    real motor bus is never touched (WOT-2026-016h).
    """

    def __init__(self, motor: Path, dest: Path, work_plan: Path, exec_log: Path):
        self.motor = motor
        self.dest = dest
        self.work_plan = work_plan
        self.exec_log = exec_log
        self.opencode_path = motor / ".opencode" / "opencode.json"

    def head_opencode_bytes(self) -> bytes:
        # capture_output without text=True -> exact bytes (BOM-sensitive).
        raw = subprocess.run(
            ["git", "show", "HEAD:.opencode/opencode.json"],
            capture_output=True,
            cwd=self.motor,
            timeout=10,
        )
        assert raw.returncode == 0, f"git show failed: {raw.stderr.decode()}"
        return raw.stdout

    def diff_opencode(self) -> str:
        return _git(
            ["diff", "HEAD", "--", ".opencode/opencode.json"], cwd=self.motor
        ).stdout


@pytest.fixture
def temp_motor(tmp_path: Path, monkeypatch) -> _TempMotor:
    """Build a temp motor+dest, seed .opencode/opencode.json, monkeypatch roots.

    Mirrors the canonical isolation pattern of tests/test_pre_handoff_multirepo.py:
    a real git repo in tmp_path with ``_MOTOR_ROOT`` monkeypatched, so the
    controller's bus resolves to the temp dir and the real motor bus is untouched.
    """
    import os as _os

    import agent_controller

    # Clear Builder session env vars so the test is independent of the runtime.
    _os.environ.pop("AGENT_BUILDER_TICKET", None)
    _os.environ.pop("AGENT_BUILDER_ROUND", None)

    motor = tmp_path / "motor"
    dest = tmp_path / "dest"
    init_git_repo(motor)
    init_git_repo(dest)

    # Seed the temp motor's .opencode/opencode.json with realistic content and
    # commit it, so `git show HEAD:.opencode/opencode.json` works in the temp repo.
    opencode = motor / ".opencode" / "opencode.json"
    opencode.parent.mkdir(parents=True, exist_ok=True)
    opencode.write_bytes(_real_head_opencode_bytes())
    _git(["add", ".opencode/opencode.json"], cwd=motor)
    _git(["commit", "-m", "seed opencode.json"], cwd=motor)

    # work_plan + exec_log live in dest (the delivery/collaboration repo).
    collab = dest / ".agent" / "collaboration"
    collab.mkdir(parents=True, exist_ok=True)
    wp = collab / "work_plan.md"
    wp.write_text(
        "# Work Plan\n\n"
        "## Metadata\n"
        "- **ID:** WOT-2026-016h\n"
        "- **Estado:** APPROVED\n"
        "- **deliverable_type:** code\n\n"
        "## Files Likely Touched\n- `tests/test_opencode_config_stability.py`\n"
    )
    exec_log = collab / "execution_log.md"
    exec_log.write_text("# Execution Log\n\n**Estado:** IN_PROGRESS\n\n")
    (dest / ".agent" / "runtime").mkdir(parents=True, exist_ok=True)
    _git(["add", "."], cwd=dest)
    _git(["commit", "-m", "add work_plan"], cwd=dest)

    monkeypatch.setattr(agent_controller, "_MOTOR_ROOT", motor)
    monkeypatch.setattr(agent_controller, "PROJECT_ROOT", dest)
    monkeypatch.setattr(agent_controller, "WORK_PLAN", wp)
    monkeypatch.setattr(agent_controller, "EXEC_LOG", exec_log)

    return _TempMotor(motor, dest, wp, exec_log)


def _pre_handoff_inprocess(capsys) -> tuple[int, str, str]:
    """Run agent_controller._handle_pre_handoff in-process; return (rc, out, err).

    Resets the module-level event_bus singleton first (the autouse conftest
    fixture also does this, but be explicit) so the temp _MOTOR_ROOT governs.
    """
    import agent_controller

    agent_controller.event_bus = None
    rc = agent_controller._handle_pre_handoff(json_output=True)
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


# ============================================================================
# Test 1: Camino feliz - diff vacio tras restauracion BOM
# ============================================================================


class TestBomHappyPath:
    """Camino feliz: diff HEAD -- .opencode/opencode.json debe ser vacio."""

    def test_feliz_diff_vacio_tras_pre_handoff(self, temp_motor, capsys):
        """Despues de --pre-handoff, git diff HEAD debe ser vacio."""
        head = temp_motor.head_opencode_bytes()
        # Asegurar que el archivo en disco es identico a HEAD
        temp_motor.opencode_path.write_bytes(head)

        _pre_handoff_inprocess(capsys)

        # pre-handoff puede fallar si no hay ticket activo, pero el diff debe ser cero
        assert temp_motor.diff_opencode() == "", (
            f"Expected empty diff after pre-handoff, got:\n{temp_motor.diff_opencode()}"
        )


# ============================================================================
# Test 2: Launcher finally-block sin BOM drift (no toca el bus; sin cambios)
# ============================================================================


class TestLauncherNoBomDrift:
    """El finally-block del launcher usa [IO.File]::WriteAllBytes (no BOM).

    Este test NO ejecuta --pre-handoff: valida solo el comportamiento de escritura
    de bytes contra el .opencode/opencode.json del motor REAL (read-only + backup/
    restore local), por lo que no toca el bus. Se mantiene tal cual.
    """

    @pytest.fixture(autouse=True)
    def _backup_and_restore(self):
        self._head_backup = _real_head_opencode_bytes()
        yield
        _OPENCODE_PATH.write_bytes(self._head_backup)

    def test_launcher_restore_is_bom_free(self):
        """Simular el finally-block del launcher: WriteAllBytes no introduce BOM."""
        b64 = base64.b64encode(self._head_backup).decode("ascii")
        decoded = base64.b64decode(b64)

        _OPENCODE_PATH.write_bytes(decoded)

        actual = _OPENCODE_PATH.read_bytes()
        assert not actual.startswith(_BOM), "File should NOT start with BOM"
        assert actual == self._head_backup, "File must be byte-identical to HEAD"

        diff = subprocess.run(
            ["git", "diff", "HEAD", "--", ".opencode/opencode.json"],
            capture_output=True,
            text=True,
            cwd=_MOTOR_ROOT,
            timeout=10,
        ).stdout
        assert diff == "", f"Launcher restore introduced diff:\n{diff}"


# ============================================================================
# Test 3: Pre-handoff autocorreccion BOM exacto
# ============================================================================


class TestPreHandoffBomAutocorrect:
    """--pre-handoff autocorrige solo el residuo BOM exacto permitido."""

    def test_autocorrect_bom_exacto(self, temp_motor, capsys):
        """Si bytes_actuales == BOM + bytes_head, autocorrige y emite stderr."""
        head = temp_motor.head_opencode_bytes()
        # Simular BOM drift: escribir BOM + HEAD
        temp_motor.opencode_path.write_bytes(_BOM + head)

        _rc, _out, stderr = _pre_handoff_inprocess(capsys)

        assert "[OK] Pre-handoff BOM autocorrected" in stderr, (
            f"Expected BOM autocorrect message in stderr, got:\n{stderr}"
        )

        # Archivo debe estar restaurado a HEAD
        assert temp_motor.opencode_path.read_bytes() == head, (
            "File should be restored to HEAD after BOM autocorrect"
        )
        assert temp_motor.diff_opencode() == "", (
            f"Expected empty diff after BOM autocorrect, got:\n{temp_motor.diff_opencode()}"
        )


# ============================================================================
# Test 4: Prueba negativa - cambio semantico NO se autocorrige
# ============================================================================


class TestNegativeSemanticChange:
    """Cambio semantico real en opencode.json -> --pre-handoff NO autocorrige."""

    def test_no_autocorrect_semantic_change(self, temp_motor, capsys):
        """Si el archivo tiene un cambio semantico REAL (no solo BOM), no lo revierte."""
        head = temp_motor.head_opencode_bytes()
        head_json = json.loads(head.decode("utf-8"))
        head_json["model"] = "opencode-go/modified-model-for-test"
        modified_bytes = json.dumps(head_json, indent=2).encode("utf-8")

        temp_motor.opencode_path.write_bytes(modified_bytes)

        _rc, _out, stderr = _pre_handoff_inprocess(capsys)

        assert "[OK] Pre-handoff BOM autocorrected" not in stderr, (
            "Should NOT autocorrect semantic changes"
        )
        assert temp_motor.opencode_path.read_bytes() != head, (
            "Semantic change should NOT be reverted by pre-handoff"
        )
        assert "modified-model-for-test" in temp_motor.diff_opencode(), (
            f"Expected semantic diff to be visible, got:\n{temp_motor.diff_opencode()}"
        )


# ============================================================================
# Test 5: Mensaje de stderr de autocorreccion BOM
# ============================================================================


class TestBomAutocorrectStderrMessage:
    """Verificar que el mensaje de autocorreccion BOM es visible en stderr."""

    def test_stderr_message_visible(self, temp_motor, capsys):
        """El mensaje de autocorreccion debe aparecer en stderr, no en stdout."""
        head = temp_motor.head_opencode_bytes()
        temp_motor.opencode_path.write_bytes(_BOM + head)

        _rc, stdout, stderr = _pre_handoff_inprocess(capsys)

        assert "[OK] Pre-handoff BOM autocorrected" in stderr
        assert ".opencode/opencode.json restored to HEAD" in stderr
        assert "(removed BOM drift)" in stderr
        assert "[OK] Pre-handoff BOM autocorrected" not in stdout


# ============================================================================
# Test 6: Camino de fallo/abort del launcher
# ============================================================================


class TestLauncherFailurePath:
    """Reproduccion documental del camino de fallo del launcher."""

    def test_launcher_finally_block_no_bom(self, temp_motor, capsys):
        """El finally-block del launcher NO introduce BOM (doc del camino de fallo).

        Camino de fallo anterior (antes de WT-2026-248a):
        - Set-Content -Encoding UTF8 -> escribe BOM + contenido -> git diff muestra diff
        Camino corregido (despues de WT-2026-248a):
        - [IO.File]::WriteAllBytes -> bytes exactos sin BOM -> git diff vacio
        """
        head = temp_motor.head_opencode_bytes()

        # Simular el finally-block corregido (WriteAllBytes, sin BOM) -> diff vacio.
        b64 = base64.b64encode(head).decode("ascii")
        temp_motor.opencode_path.write_bytes(base64.b64decode(b64))
        assert not temp_motor.opencode_path.read_bytes().startswith(_BOM)
        assert temp_motor.diff_opencode() == ""

        # Simular el camino de fallo ANTES del fix (Set-Content -Encoding UTF8 -> BOM).
        temp_motor.opencode_path.write_bytes(_BOM + head)
        diff_before_fix = temp_motor.diff_opencode()
        assert len(diff_before_fix) > 0, (
            "Before fix: diff should NOT be empty (BOM drift present)"
        )

        # El pre-handoff autocorrige el BOM.
        _rc, _out, stderr = _pre_handoff_inprocess(capsys)
        assert "[OK] Pre-handoff BOM autocorrected" in stderr

        # Despues de autocorreccion, diff es vacio.
        assert temp_motor.diff_opencode() == "", (
            f"After autocorrect: diff should be empty, got:\n{temp_motor.diff_opencode()}"
        )
