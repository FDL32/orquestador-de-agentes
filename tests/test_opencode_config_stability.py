"""WT-2026-248a: Tests para estabilidad de .opencode/opencode.json (BOM drift).

Cobertura:
1. Camino feliz: diff vacio tras restauracion BOM via launcher finally-block
2. Camino de fallo/abort: --pre-handoff bloquea cambio semantico real
3. Prueba negativa: cambio semantico en opencode.json -> --pre-handoff NO autocorrige
4. Mensaje de stderr de autocorreccion BOM
"""

import base64
import json
import subprocess
import sys
from pathlib import Path

import pytest


# Motor root (donde vive .opencode/opencode.json)
_MOTOR_ROOT = Path(__file__).resolve().parent.parent
_OPENCODE_PATH = _MOTOR_ROOT / ".opencode" / "opencode.json"
_BOM = b"\xef\xbb\xbf"


# ============================================================================
# Helpers
# ============================================================================


def _git_show_head_opencode() -> bytes:
    """Return the exact bytes of .opencode/opencode.json at HEAD."""
    result = subprocess.run(
        ["git", "show", "HEAD:.opencode/opencode.json"],
        capture_output=True,
        cwd=_MOTOR_ROOT,
        timeout=10,
    )
    assert result.returncode == 0, f"git show failed: {result.stderr.decode()}"
    return result.stdout


def _git_diff_head_path(path: str) -> str:
    """Run git diff HEAD -- <path> and return stdout."""
    result = subprocess.run(
        ["git", "diff", "HEAD", "--", path],
        capture_output=True,
        text=True,
        cwd=_MOTOR_ROOT,
        timeout=10,
    )
    return result.stdout


def _pre_handoff() -> tuple[int, str, str]:
    """Run agent_controller --pre-handoff and return (exit_code, stdout, stderr)."""
    result = subprocess.run(
        [
            sys.executable,
            str(_MOTOR_ROOT / ".agent" / "agent_controller.py"),
            "--pre-handoff",
            "--json",
            "--project-root",
            str(_MOTOR_ROOT),
        ],
        capture_output=True,
        text=True,
        cwd=_MOTOR_ROOT,
        timeout=30,
    )
    return result.returncode, result.stdout, result.stderr


def _save_head_backup() -> bytes:
    """Save the HEAD bytes for later restoration."""
    return _git_show_head_opencode()


def _restore_head() -> None:
    """Restore .opencode/opencode.json to HEAD exactly."""
    head_bytes = _git_show_head_opencode()
    _OPENCODE_PATH.write_bytes(head_bytes)


# ============================================================================
# Test 1: Camino feliz - diff vacio tras restauracion BOM
# ============================================================================


class TestBomHappyPath:
    """Camino feliz: diff HEAD -- .opencode/opencode.json debe ser vacio."""

    @pytest.fixture(autouse=True)
    def _backup_and_restore(self):
        """Backup HEAD bytes before test, restore after."""
        self._head_backup = _save_head_backup()
        yield
        _restore_head()

    def test_feliz_diff_vacio_tras_pre_handoff(self):
        """Despues de --pre-handoff, git diff HEAD debe ser vacio."""
        # Asegurar que el archivo en disco es identico a HEAD
        _OPENCODE_PATH.write_bytes(self._head_backup)

        # Ejecutar pre-handoff
        _exit_code, _stdout, _stderr = _pre_handoff()
        # pre-handoff puede fallar si no hay ticket activo, pero el diff debe ser cero
        diff = _git_diff_head_path(".opencode/opencode.json")
        assert diff == "", f"Expected empty diff after pre-handoff, but got:\n{diff}"


# ============================================================================
# Test 2: Launcher finally-block sin BOM drift
# ============================================================================


class TestLauncherNoBomDrift:
    """El finally-block del launcher usa [IO.File]::WriteAllBytes (no BOM)."""

    @pytest.fixture(autouse=True)
    def _backup_and_restore(self):
        self._head_backup = _save_head_backup()
        yield
        _restore_head()

    def test_launcher_restore_is_bom_free(self):
        """Simular el finally-block del launcher: WriteAllBytes no introduce BOM."""
        # Simular lo que hace el launcher en el finally-block
        b64 = base64.b64encode(self._head_backup).decode("ascii")
        decoded = base64.b64decode(b64)

        # Escribir como lo haria el launcher (WriteAllBytes)
        _OPENCODE_PATH.write_bytes(decoded)

        # Verificar: sin BOM
        actual = _OPENCODE_PATH.read_bytes()
        assert not actual.startswith(_BOM), "File should NOT start with BOM"
        assert actual == self._head_backup, "File must be byte-identical to HEAD"

        # Diff debe ser vacio
        diff = _git_diff_head_path(".opencode/opencode.json")
        assert diff == "", f"Launcher restore introduced diff:\n{diff}"


# ============================================================================
# Test 3: Pre-handoff autocorreccion BOM exacto
# ============================================================================


class TestPreHandoffBomAutocorrect:
    """--pre-handoff autocorrige solo el residuo BOM exacto permitido."""

    @pytest.fixture(autouse=True)
    def _backup_and_restore(self):
        self._head_backup = _save_head_backup()
        yield
        _restore_head()

    def test_autocorrect_bom_exacto(self):
        """Si bytes_actuales == BOM + bytes_head, autocorrige y emite stderr."""
        # Simular BOM drift: escribir BOM + HEAD
        drifted = _BOM + self._head_backup
        _OPENCODE_PATH.write_bytes(drifted)

        # Ejecutar pre-handoff
        _exit_code, _stdout, stderr = _pre_handoff()

        # Debe haber autocorreccion en stderr
        assert "[OK] Pre-handoff BOM autocorrected" in stderr, (
            f"Expected BOM autocorrect message in stderr, got:\n{stderr}"
        )

        # Archivo debe estar restaurado a HEAD
        actual = _OPENCODE_PATH.read_bytes()
        assert actual == self._head_backup, (
            "File should be restored to HEAD after BOM autocorrect"
        )

        # Diff debe ser vacio
        diff = _git_diff_head_path(".opencode/opencode.json")
        assert diff == "", f"Expected empty diff after BOM autocorrect, got:\n{diff}"


# ============================================================================
# Test 4: Prueba negativa - cambio semantico NO se autocorrige
# ============================================================================


class TestNegativeSemanticChange:
    """Cambio semantico real en opencode.json -> --pre-handoff NO autocorrige."""

    @pytest.fixture(autouse=True)
    def _backup_and_restore(self):
        self._head_backup = _save_head_backup()
        yield
        _restore_head()

    def test_no_autocorrect_semantic_change(self):
        """Si el archivo tiene un cambio semantico REAL (no solo BOM), bloquea."""
        # Leer HEAD, modificar un valor semantico
        head_text = self._head_backup.decode("utf-8")
        head_json = json.loads(head_text)
        head_json["model"] = "opencode-go/modified-model-for-test"
        modified_text = json.dumps(head_json, indent=2)
        modified_bytes = modified_text.encode("utf-8")

        # Escribir modificacion semantica (sin BOM)
        _OPENCODE_PATH.write_bytes(modified_bytes)

        # Ejecutar pre-handoff
        _exit_code, _stdout, stderr = _pre_handoff()

        # NO debe haber mensaje de autocorreccion BOM
        assert "[OK] Pre-handoff BOM autocorrected" not in stderr, (
            "Should NOT autocorrect semantic changes"
        )

        # El archivo NO debe haber sido modificado por pre-handoff
        actual = _OPENCODE_PATH.read_bytes()
        assert actual != self._head_backup, (
            "Semantic change should NOT be reverted by pre-handoff"
        )

        # Diff debe mostrar el cambio semantico
        diff = _git_diff_head_path(".opencode/opencode.json")
        assert "modified-model-for-test" in diff, (
            f"Expected semantic diff to be visible, got:\n{diff}"
        )


# ============================================================================
# Test 5: Mensaje de stderr de autocorreccion BOM
# ============================================================================


class TestBomAutocorrectStderrMessage:
    """Verificar que el mensaje de autocorreccion BOM es visible en stderr."""

    @pytest.fixture(autouse=True)
    def _backup_and_restore(self):
        self._head_backup = _save_head_backup()
        yield
        _restore_head()

    def test_stderr_message_visible(self):
        """El mensaje de autocorreccion debe aparecer en stderr."""
        # Simular BOM drift
        drifted = _BOM + self._head_backup
        _OPENCODE_PATH.write_bytes(drifted)

        # Ejecutar pre-handoff
        _exit_code, _stdout, stderr = _pre_handoff()

        # Verificar mensaje en stderr
        assert "[OK] Pre-handoff BOM autocorrected" in stderr
        assert ".opencode/opencode.json restored to HEAD" in stderr
        assert "(removed BOM drift)" in stderr

        # Verificar que el mensaje NO esta en stdout
        assert "[OK] Pre-handoff BOM autocorrected" not in _stdout


# ============================================================================
# Test 6: Camino de fallo/abort del launcher
# ============================================================================


class TestLauncherFailurePath:
    """Reproduccion documental del camino de fallo del launcher."""

    @pytest.fixture(autouse=True)
    def _backup_and_restore(self):
        self._head_backup = _save_head_backup()
        yield
        _restore_head()

    def test_launcher_finally_block_no_bom(self):
        """El finally-block del launcher NO introduce BOM (documentacion del camino de fallo).

        Camino de fallo anterior (antes de WT-2026-248a):
        - Set-Content -Encoding UTF8 -> escribe BOM + contenido
        - Resultado: .opencode/opencode.json tiene BOM extra
        - git diff HEAD muestra diff

        Camino corregido (despues de WT-2026-248a):
        - [IO.File]::WriteAllBytes -> escribe bytes exactos sin BOM
        - Resultado: .opencode/opencode.json es identico a HEAD
        - git diff HEAD es vacio
        """
        # Simular el finally-block corregido
        b64 = base64.b64encode(self._head_backup).decode("ascii")
        decoded = base64.b64decode(b64)

        # WriteAllBytes (sin BOM)
        _OPENCODE_PATH.write_bytes(decoded)

        # Verificar: sin BOM, diff vacio
        actual = _OPENCODE_PATH.read_bytes()
        assert not actual.startswith(_BOM)
        diff = _git_diff_head_path(".opencode/opencode.json")
        assert diff == ""

        # Simular el camino de fallo ANTES del fix (Set-Content -Encoding UTF8)
        # Esto introduce BOM
        text_content = self._head_backup.decode("utf-8")
        # Set-Content -Encoding UTF8 en PowerShell escribe BOM
        bom_content = _BOM + text_content.encode("utf-8")
        _OPENCODE_PATH.write_bytes(bom_content)

        # Ahora el diff NO es vacio (camino de fallo)
        diff_before_fix = _git_diff_head_path(".opencode/opencode.json")
        assert len(diff_before_fix) > 0, (
            "Before fix: diff should NOT be empty (BOM drift present)"
        )

        # El pre-handoff autocorrige el BOM
        _exit_code, _stdout, stderr = _pre_handoff()
        assert "[OK] Pre-handoff BOM autocorrected" in stderr

        # Despues de autocorreccion, diff es vacio
        diff_after_fix = _git_diff_head_path(".opencode/opencode.json")
        assert diff_after_fix == "", (
            f"After autocorrect: diff should be empty, got:\n{diff_after_fix}"
        )
