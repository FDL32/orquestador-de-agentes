#!/usr/bin/env python
"""Tests para scripts/check_builder_cli_privacy_preflight.py.

Via de invocacion: subprocess (llama al script como proceso real), porque el
guard corre como proceso independiente en la practica; testear la tuberia
completa de argparse -> import lazy -> privacy_preflight REAL es mas fiel.

PROHIBIDO mockear la deteccion de contenido sensible: se ejerce
privacy_preflight REAL importada de ensemble_dispatch.py, no un mock.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile


SCRIPT_DIR = Path(__file__).resolve().parents[2] / "scripts"
SCRIPT_PATH = SCRIPT_DIR / "check_builder_cli_privacy_preflight.py"


def _run(
    preflight_args: list[str], expect_rc: int | None = None
) -> subprocess.CompletedProcess:
    """Invocar el script y verificar RC si se pasa expect_rc."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *preflight_args],
        capture_output=True,
        text=True,
        cwd=str(SCRIPT_DIR),
    )
    if expect_rc is not None:
        assert result.returncode == expect_rc, (
            f"Expected rc={expect_rc}, got {result.returncode}. "
            f"stdout: {result.stdout!r}. stderr: {result.stderr!r}"
        )
    return result


def _make_prompt(content: str) -> Path:
    """Crea un fichero temporal con el contenido dado. El caller debe borrarlo."""
    f = NamedTemporaryFile(
        suffix=".md", mode="w", encoding="utf-8", delete=False, dir=str(SCRIPT_DIR)
    )
    try:
        f.write(content)
    finally:
        f.close()
    return Path(f.name)


def _cleanup(p: Path) -> None:
    """Borra un fichero temporal creado por _make_prompt."""
    p.unlink(missing_ok=True)


class TestPrivacyPreflightReal:
    """Tests que ejercitan privacy_preflight REAL, sin mockear la deteccion."""

    # Un token de alta entropia (>=32 chars, base64, 3+ classes, >=4.0 bits/char)
    # que _OPAQUE_TOKEN detecta como fuga por entropia.
    # Patrn usado en tests_ensemble_dispatch.py:68-70 (test_059e_*).
    _SENSITIVE_PAYLOAD = "kJ8vQz3XpR7mNw2LtY6bHc4FdA9sG1eU5iO0"

    def test_046k_mutation_sensible_sin_exencion_bloquea(self):
        """MUTATION (DoD 2): payload sensible sin --trusted-reason -> BLOQUEADO.

        El payload es el MISMO patron de alta entropia que _OPAQUE_TOKEN
        detecta en ensemble_dispatch.py (_ENTROPY_MIN_TOKEN_LEN=32,
        _ENTROPY_BITS_THRESHOLD=4.0, 3+ clases de caracter).
        Se usa --data-sensitivity public para que la unica razon posible de
        bloqueo sea el CONTENIDO (detectado por _content_leak), no la
        sensibilidad.
        """
        path = _make_prompt(f"revision del informe. payload: {self._SENSITIVE_PAYLOAD}")
        try:
            result = _run(
                [str(path), "--data-sensitivity", "public"],
                expect_rc=1,
            )
            assert "BLOQUEA" in result.stderr, (
                f"Expected BLOQUEA in stderr, got: {result.stderr!r}"
            )
            assert "contenido sensible" in result.stderr, (
                f"Expected 'contenido sensible' in stderr (content-leak reason, "
                f"not sensitivity), got: {result.stderr!r}"
            )
        finally:
            _cleanup(path)

    def test_046k_control_negativo_trusted_reason_permite(self):
        """CONTROL NEGATIVO (DoD 3): mismo payload sensible con --trusted-reason -> permitido.

        Se usa --data-sensitivity public para que el guard pase la rama de
        deteccion de contenido y la unica decision sea por backend_cfg
        (trusted:true). El motivo declarado debe aparecer en la salida.
        """
        path = _make_prompt(f"revision del informe. payload: {self._SENSITIVE_PAYLOAD}")
        try:
            result = _run(
                [
                    str(path),
                    "--data-sensitivity",
                    "public",
                    "--trusted-reason",
                    "auditoria autorizada WOT-2026-046k",
                ],
                expect_rc=0,
            )
            assert "OK" in result.stdout or "exencion" in result.stdout.lower(), (
                f"Expected OK/exencion in stdout, got stdout: {result.stdout!r}"
            )
            assert "auditoria autorizada WOT-2026-046k" in result.stdout, (
                f"Expected reason in stdout, got: {result.stdout!r}"
            )
        finally:
            _cleanup(path)

    def test_046k_publico_sin_sensible_permite(self):
        """Caso base: prompt publico sin contenido sensible -> exit 0."""
        path = _make_prompt(
            "revision manual del informe trimestral. sin datos sensibles."
        )
        try:
            result = _run([str(path), "--data-sensitivity", "public"], expect_rc=0)
            assert "OK" in result.stdout, (
                f"Expected OK in stdout, got: {result.stdout!r}"
            )
        finally:
            _cleanup(path)

    def test_046k_fichero_inexistente_exit_2(self):
        """Fichero de prompt inexistente -> exit 2."""
        result = _run(["/tmp/no_existe_prompt_046k.md"], expect_rc=2)
        assert "no encontrado" in result.stderr.lower() or ("ERROR" in result.stderr), (
            f"Expected ERROR/no encontrado in stderr, got: {result.stderr!r}"
        )


class TestDefaultSensitivity:
    """Caso: --data-sensitivity ausente se trata como 'private' (fail-closed)."""

    _SENSITIVE_PAYLOAD = "kJ8vQz3XpR7mNw2LtY6bHc4FdA9sG1eU5iO0"

    def test_046k_default_private_bloquea_sensible(self):
        """Sin --data-sensitivity, un payload sensible debe bloquear (default private)."""
        path = _make_prompt(f"contenido: {self._SENSITIVE_PAYLOAD}")
        try:
            result = _run([str(path)], expect_rc=1)
            assert "BLOQUEA" in result.stderr, (
                f"Expected BLOQUEA (default private), got: {result.stderr!r}"
            )
        finally:
            _cleanup(path)


class TestCredentialLiteral:
    """Credenciales con patrn conocido (sk-..., ghp_...) bloquean tambien.

    NOTA: todos estos tests usan --data-sensitivity public para que el bloqueo
    sea por la deteccion de contenido literal (_content_leaf), no por
    sensibilidad. La sensibilidad se prueba separada en
    TestDefaultSensitivity::test_046k_default_private_bloquea_sensible.
    """

    def test_046k_sk_like_bloquea(self):
        """Un token tipo sk-... con >=16 chars alfanumericos es credencial literal."""
        path = _make_prompt("clave: sk-ABCDEFGHIJKLMNOPQRSTUVWX")
        try:
            result = _run(
                [str(path), "--data-sensitivity", "public"],
                expect_rc=1,
            )
            assert "BLOQUEA" in result.stderr, (
                f"Expected BLOQUEA for sk- token, got: {result.stderr!r}"
            )
            assert "literal de credencial" in result.stderr, (
                f"Expected 'literal de credencial' in stderr for sk- token "
                f"(content-leak reason, not sensitivity), got: {result.stderr!r}"
            )
        finally:
            _cleanup(path)

    def test_046k_sk_like_con_trusted_reason_permite(self):
        """Mismo token sk-... con --trusted-reason permitido."""
        path = _make_prompt("clave: sk-ABCDEFGHIJKLMNOPQRSTUVWX")
        try:
            result = _run(
                [
                    str(path),
                    "--data-sensitivity",
                    "public",
                    "--trusted-reason",
                    "clave de prueba documentada",
                ],
                expect_rc=0,
            )
            assert "OK" in result.stdout or "exencion" in result.stderr.lower(), (
                f"Expected OK/exencion, got: stdout={result.stdout!r}, stderr={result.stderr!r}"
            )
        finally:
            _cleanup(path)


class TestTrustedReasonEmpty:
    """--trusted-reason con motivo vacio no cuenta como exencion.

    NOTA: estos tests usan --data-sensitivity public para que el bloqueo sea
    por deteccion de contenido, no por sensibilidad.
    """

    _SENSITIVE_PAYLOAD = "kJ8vQz3XpR7mNw2LtY6bHc4FdA9sG1eU5iO0"

    def test_046k_trusted_reason_vacio_no_exime(self):
        """--trusted-reason '' no activa trusted:true -> sigue bloqueando."""
        path = _make_prompt(f"contenido: {self._SENSITIVE_PAYLOAD}")
        try:
            result = _run(
                [str(path), "--data-sensitivity", "public", "--trusted-reason", ""],
                expect_rc=1,
            )
            assert "BLOQUEA" in result.stderr, (
                f"Expected BLOQUEA with empty reason, got: {result.stderr!r}"
            )
            assert "payload contiene contenido sensible:" in result.stderr, (
                f"Expected 'payload contiene contenido sensible:' in stderr "
                f"(content-leak reason), got: {result.stderr!r}"
            )
        finally:
            _cleanup(path)

    def test_046k_trusted_reason_solo_espacios_no_exime(self):
        """--trusted-reason '   ' (solo espacios) no activa trusted:true."""
        path = _make_prompt(f"contenido: {self._SENSITIVE_PAYLOAD}")
        try:
            result = _run(
                [
                    str(path),
                    "--data-sensitivity",
                    "public",
                    "--trusted-reason",
                    "   ",
                ],
                expect_rc=1,
            )
            assert "BLOQUEA" in result.stderr, (
                f"Expected BLOQUEA with whitespace-only reason, got: {result.stderr!r}"
            )
            assert "payload contiene contenido sensible:" in result.stderr, (
                f"Expected 'payload contiene contenido sensible:' in stderr "
                f"(content-leak reason), got: {result.stderr!r}"
            )
        finally:
            _cleanup(path)
