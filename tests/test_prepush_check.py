#!/usr/bin/env python3
"""Tests for prepush_check.py - delivery preflight wrapper.

Tests cover three main scenarios:
(a) Clean path - all five checks pass, exit 0, tree unchanged
(b) Dirty tree path - git status --short returns output, exit 1
(c) Mutating hook in pre-push detected by delivery_hygiene_check, exit 1

Uses monkeypatch and tmp_path to isolate subprocess calls and git operations.
No test mutates the real filesystem.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from scripts.prepush_check import (
    CheckResult,
    _format_check_optout,
    _print_preflight_report,
    run_agent_controller_validate,
    run_delivery_hygiene_check,
    run_git_status_check,
    run_portable_memory_archive_check,
    run_preflight_check,
    run_ruff_check,
    run_ruff_format_check,
    run_validate_all,
)


class TestDeliveryHygieneCheck:
    """Tests for delivery_hygiene_check integration."""

    def test_destination_root_does_not_shadow_motor_scripts(
        self, tmp_path: Path
    ) -> None:
        """The canonical motor module is imported without mutating sys.path."""
        original_path = list(sys.path)
        with patch(
            "scripts.delivery_hygiene_check.run_delivery_hygiene_check",
            return_value=0,
        ):
            result = run_delivery_hygiene_check(tmp_path)

        assert result.passed is True
        assert sys.path == original_path

    def test_delivery_hygiene_import_error(self, tmp_path: Path) -> None:
        """Test when delivery_hygiene_check module cannot be imported."""
        # Simulate ImportError by patching the import to fail
        with patch.dict("sys.modules", {"scripts.delivery_hygiene_check": None}):
            result = run_delivery_hygiene_check(tmp_path)

        assert result.name == "Delivery Hygiene Check"
        assert result.passed is False
        assert "Error importando" in result.output
        assert result.is_blocking is True


class TestRuffCheck:
    """Tests for ruff check integration."""

    def test_ruff_check_passes(self, tmp_path: Path) -> None:
        """Test when ruff check passes."""
        mock_result = subprocess.CompletedProcess(
            args=["ruff", "check", "."],
            returncode=0,
            stdout="",
            stderr="",
        )

        with patch("subprocess.run", return_value=mock_result):
            result = run_ruff_check(tmp_path)

        assert result.name == "Ruff Check"
        assert result.passed is True
        assert result.is_blocking is True

    def test_ruff_check_fails(self, tmp_path: Path) -> None:
        """Test when ruff check fails."""
        mock_result = subprocess.CompletedProcess(
            args=["ruff", "check", "."],
            returncode=1,
            stdout="E501 Line too long\n",
            stderr="",
        )

        with patch("subprocess.run", return_value=mock_result):
            result = run_ruff_check(tmp_path)

        assert result.name == "Ruff Check"
        assert result.passed is False
        assert "E501" in result.output
        assert result.is_blocking is True

    def test_ruff_check_not_found(self, tmp_path: Path) -> None:
        """Test when ruff command is not found."""
        with patch("subprocess.run", side_effect=FileNotFoundError("ruff")):
            result = run_ruff_check(tmp_path)

        assert result.name == "Ruff Check"
        assert result.passed is False
        assert "no encontrado" in result.output
        assert result.is_blocking is True


class TestRuffFormatCheck:
    """Tests for ruff format --check integration."""

    def test_ruff_format_passes(self, tmp_path: Path) -> None:
        """Test when ruff format --check passes."""
        mock_result = subprocess.CompletedProcess(
            args=["ruff", "format", "--check", "."],
            returncode=0,
            stdout="",
            stderr="",
        )

        with patch("subprocess.run", return_value=mock_result):
            result = run_ruff_format_check(tmp_path)

        assert result.name == "Ruff Format Check"
        assert result.passed is True
        assert result.is_blocking is True

    def test_ruff_format_fails(self, tmp_path: Path) -> None:
        """Test when ruff format --check fails."""
        mock_result = subprocess.CompletedProcess(
            args=["ruff", "format", "--check", "."],
            returncode=1,
            stdout="Would reformat: file.py\n",
            stderr="",
        )

        with patch("subprocess.run", return_value=mock_result):
            result = run_ruff_format_check(tmp_path)

        assert result.name == "Ruff Format Check"
        assert result.passed is False
        assert "Would reformat" in result.output
        assert result.is_blocking is True


class TestRuffFormatOptOut:
    """Un destino puede DECLINAR `ruff format` y el gate debe reconocerlo.

    Contexto (LEA-2026-002k / WOT-2026-047e): `run_ruff_format_check` corria
    `ruff format --check .` sin excepcion posible, asi que un proyecto que
    decide por diseno no adoptar el formateador quedaba con el cierre
    bloqueado por un rojo CORRECTO. La decision estaba declarada y anclada en
    su propia suite, pero el motor no tenia forma de leerla.

    El discriminante es EXPLICITO (`format-check = false` bajo
    `[tool.motor]`), no inferido de la presencia de `[format]`: un `ruff.toml`
    puede traer `[format]` configurado justamente para el caso contrario --
    dejar preparada la activacion futura -- y confundir ambas cosas volveria
    a apagar el gate donde nadie lo pidio.
    """

    def _write_unformatted(self, root: Path) -> None:
        """Deja un fichero que `ruff format --check` rechaza con seguridad.

        Control positivo obligatorio, y no es ceremonia: `tmp_path` en esta
        suite NO es el de pytest, es un factory re-enraizado DENTRO del arbol
        del motor (`conftest.py::tmp_path` / `SESSION_RUNTIME_ROOT`), que
        cuelga de `tests/sandbox`. Y el `pyproject.toml` del motor lista
        `tests/sandbox` en `extend-exclude`, asi que ruff descubre esa
        configuracion "via parent" y DESCARTA el fixture entero antes de
        mirarlo: contesta rc=0 con "No Python files found".

        Medido con `ruff -v` desde el propio fixture:
            Using configuration file (via parent) at: <motor>/pyproject.toml
            Ignored path via `extend-exclude`: <motor>/tests/sandbox
        Ese rc=0 es indistinguible de un opt-out que funciona, de modo que
        sin este control positivo los tests de abajo pasarian sin ejercitar
        nada.

        LIMITE DECLARADO (cazado por la lente Codex del bucle L700): este
        probe usa `--isolated` y el gate real NO -- corre `uv run ruff format
        --check .`, sin aislar. NO son la misma ruta. Lo que el control
        positivo prueba es que el fixture esta REALMENTE sucio, o sea que un
        rc=0 posterior no puede atribuirse a un arbol limpio; no prueba que el
        gate mida igual. Esa segunda mitad la cubre el assert de
        "Would reformat" del test negativo, que exige que ruff HAYA LEIDO el
        fichero. Una version anterior de este docstring afirmaba que el gate
        usaba `--isolated`: era falso.
        """
        (root / "sample.py").write_text(
            "x = {'a':1,   'b':2}\ndef f( a ,b ):\n  return a+b\n",
            encoding="utf-8",
        )
        probe = subprocess.run(
            ["ruff", "format", "--check", "--isolated", "."],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
        assert probe.returncode != 0, (
            "control positivo fallido: el fixture deberia estar sin formatear, "
            f"pero ruff lo acepta.\nstdout={probe.stdout}\nstderr={probe.stderr}"
        )

    def test_optout_declarado_convierte_el_fallo_en_skip(self, tmp_path: Path) -> None:
        """Con el opt-out declarado, un arbol sin formatear NO bloquea.

        La declaracion va en `pyproject.toml`, el UNICO sitio soportado; ver
        `test_ruff_toml_no_es_sitio_valido_para_el_optout` para por que
        `ruff.toml` no puede alojarla.
        """
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "fixture"\nversion = "0"\n'
            'requires-python = ">=3.10"\n\n[tool.motor]\nformat-check = false\n',
            encoding="utf-8",
        )
        (tmp_path / "ruff.toml").write_text("line-length = 88\n", encoding="utf-8")
        self._write_unformatted(tmp_path)

        result = run_ruff_format_check(tmp_path)

        assert result.passed is True
        assert result.is_blocking is True, "el gate sigue siendo bloqueante"
        assert "SKIP" in result.output.upper()
        assert "pyproject.toml" in result.output, (
            "el SKIP debe CITAR el fichero que lo autoriza; un skip sin "
            "procedencia es indistinguible de un gate roto"
        )

    def test_sin_optout_un_arbol_sin_formatear_sigue_bloqueando(
        self, tmp_path: Path
    ) -> None:
        """Mutacion inversa: sin la declaracion, el gate muerde igual que antes."""
        self._write_unformatted(tmp_path)
        (tmp_path / "ruff.toml").write_text("line-length = 88\n", encoding="utf-8")

        result = run_ruff_format_check(tmp_path)

        assert result.passed is False, (
            "sin opt-out declarado el gate NO puede aflojarse"
        )
        # Sin esto el test es un FALSO VERDE, cazado por el bucle L700 (BA10 y
        # BA11, 2026-08-02): `passed is False` tambien se cumple cuando ruff
        # aborta sin mirar nada -- p.ej. el `unknown field` de un ruff.toml
        # invalido, o el fixture excluido por `extend-exclude`. Exigir la
        # frase de reformateo obliga a que ruff HAYA LEIDO el fichero sucio,
        # que es lo unico que prueba que el gate mordio por la razon correcta.
        assert "Would reformat" in result.output, (
            "el gate debe fallar PORQUE ruff vio el fichero sin formatear, no "
            f"porque ruff abortase sin mirarlo. Salida real: {result.output!r}"
        )

    def test_format_configurado_no_es_optout(self, tmp_path: Path) -> None:
        """`[format]` presente NO significa declinar: puede ser preparacion.

        Este es el falso-positivo que el diseno evita a proposito. El
        `ruff.toml` real de LEA trae `quote-style = "preserve"` bajo
        `[format]` con el comentario "por si alguien lo activa algun dia":
        leerlo como opt-out apagaria el gate en todo destino que haya dejado
        el formateador preconfigurado.
        """
        self._write_unformatted(tmp_path)
        (tmp_path / "ruff.toml").write_text(
            '[format]\nquote-style = "preserve"\n', encoding="utf-8"
        )

        result = run_ruff_format_check(tmp_path)

        assert result.passed is False

    def test_optout_en_pyproject_tambien_vale(self, tmp_path: Path) -> None:
        """No todo destino tiene `ruff.toml`; el contrato tambien se declara ahi."""
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "fixture"\nversion = "0"\n'
            'requires-python = ">=3.10"\n\n[tool.motor]\nformat-check = false\n',
            encoding="utf-8",
        )
        self._write_unformatted(tmp_path)

        result = run_ruff_format_check(tmp_path)

        assert result.passed is True
        assert "pyproject.toml" in result.output

    def test_el_skip_es_visible_en_el_informe_de_cierre(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """La procedencia del SKIP debe llegar al INFORME, no solo al objeto.

        Cazado por la lente Codex del bucle L700 (2026-08-02) y confirmado en
        el codigo: el reporter imprime `result.output` bajo la condicion
        `if not result.passed and result.output`. Como el SKIP sale con
        `passed=True`, su procedencia MUERE ahi y un lector del cierre ve

            [OK] Ruff Format Check

        indistinguible de "ruff format corrio y paso". Es el mismo defecto que
        `test_optout_declarado_convierte_el_fallo_en_skip` creia estar
        pineando: aquel afirma sobre el `CheckResult`, no sobre el artefacto
        que lee un humano. Verificar el objeto y creer haber verificado el
        informe es la version de "medir tu parser y creer haber medido la ruta
        productiva".
        """
        results = [
            CheckResult(
                name="Ruff Format Check",
                passed=True,
                output=(
                    "SKIP: el proyecto declina `ruff format` en pyproject.toml "
                    "([tool.motor] format-check = false)."
                ),
                is_blocking=True,
            )
        ]
        _print_preflight_report(results)
        printed = capsys.readouterr().out

        assert "Ruff Format Check" in printed
        assert "SKIP" in printed, (
            "un gate que NO se ejecuto no puede presentarse como [OK] a secas: "
            f"el informe fue {printed!r}"
        )
        assert "pyproject.toml" in printed, (
            "la procedencia debe llegar al informe; sin ella el lector no "
            "puede distinguir un gate saltado de un gate que corrio y paso"
        )

    def test_un_salto_sin_la_palabra_skip_tambien_es_visible(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """El salto se marca en el DATO, no se adivina del texto.

        Cazado por la lente GLM-5.2 del bucle L700 (2026-08-02), que refuto la
        correccion anterior: detectar el salto con
        `output.startswith("SKIP")` cierra UNA INSTANCIA y deja viva la CLASE.
        Medido en el propio fichero, hay al menos dos gates BLOQUEANTES que
        pasan sin ejecutarse y cuyo texto NO empieza por "SKIP":

            :461  "No backlog.md at <ruta> (skipped)"
            :545  "motor CF triple not materialized (skipped)"

        Un cierre en un destino sin `backlog.md` imprimia
        `[OK] Backlog Contract Check`, indistinguible de "corrio y valido".
        Ademas el criterio por prefijo es fragil por naturaleza: sensible a
        mayusculas y al idioma del mensaje.

        Por eso `CheckResult` lleva ahora un campo `skipped` explicito y el
        reporter lo lee a el. El texto puede decir lo que quiera.
        """
        results = [
            CheckResult(
                name="Backlog Contract Check",
                passed=True,
                output="No backlog.md at /x (skipped)",
                is_blocking=True,
                skipped=True,
            )
        ]
        _print_preflight_report(results)
        printed = capsys.readouterr().out

        assert "No backlog.md" in printed, (
            "un gate que no se ejecuto debe mostrar su motivo aunque su texto "
            f"no empiece por SKIP. Informe: {printed!r}"
        )
        assert "[OK]" not in printed.split("\n")[0] or "SKIP" in printed, (
            "un salto no puede presentarse como un [OK] pelado"
        )

    def test_un_check_que_paso_de_verdad_no_se_marca_como_salto(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Mutacion inversa: un check ejecutado y verde NO debe verse saltado."""
        results = [
            CheckResult(
                name="Ruff Check",
                passed=True,
                output="All checks passed!",
                is_blocking=True,
            )
        ]
        _print_preflight_report(results)
        printed = capsys.readouterr().out

        assert "[OK] Ruff Check" in printed
        assert "SKIP" not in printed, (
            "marcar como salto un check que SI corrio invierte el defecto"
        )

    def test_el_discriminante_es_contrato_publico_y_no_puede_renombrarse(
        self, tmp_path: Path
    ) -> None:
        """El nombre exacto de la clave es CONTRATO con los destinos.

        Un destino declina `ruff format` escribiendo, en SU propio
        `pyproject.toml`, exactamente estas tres cosas: la tabla `tool.motor`,
        la clave `format-check` y el booleano `false`. El motor no puede
        renombrar ninguna sin romper a todo destino que ya lo haya declarado
        -- y el destino no se entera: su fichero sigue ahi, su suite sigue
        verde, y lo unico que cambia es que el gate del motor deja de
        reconocerlo y su cierre vuelve a bloquearse. Es un fallo SILENCIOSO y
        a distancia.

        El resto de la suite usa el literal en fixtures y docstrings, pero eso
        NO lo ancla: un renombrado que actualice fixtures y codigo en el mismo
        commit los deja a todos verdes y rompe el contrato igual. Este test
        existe para que ese commit tenga que TOCAR una barrera que dice, con
        todas las letras, que el nombre es publico.

        Destino real que depende de esto (2026-08-03): el `pyproject.toml` de
        LEA, escrito en su commit `2730d1b` citando `LEA-2026-002k`.

        Si de verdad hay que renombrar la clave, este test es el sitio donde
        se decide: hay que cambiarlo A PROPOSITO y, en el mismo movimiento,
        migrar los destinos o aceptar un alias de transicion.
        """
        # El contrato, escrito como lo escribe un destino -- no importado de
        # una constante del motor, que se renombraria sola con el codigo.
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "fixture"\nversion = "0"\n'
            'requires-python = ">=3.10"\n\n[tool.motor]\nformat-check = false\n',
            encoding="utf-8",
        )

        assert _format_check_optout(tmp_path) == "pyproject.toml", (
            "el motor ha dejado de reconocer `[tool.motor] format-check = "
            "false`. Si el renombrado es deliberado, migra los destinos que "
            "ya lo declaran (LEA: commit 2730d1b) o acepta un alias; si no, "
            "es una regresion que rompe su cierre en silencio"
        )

    def test_solo_el_booleano_false_concede_el_optout(self, tmp_path: Path) -> None:
        """Ni `true`, ni la cadena "false", ni la clave ausente conceden nada.

        Complemento del contrato de arriba: fija el VALOR, no solo el nombre.
        `motor.get("format-check") is False` es estricto al booleano TOML, y
        eso debe seguir siendo cierto -- aflojarlo a un `not motor.get(...)`
        haria que la clave AUSENTE concediese el opt-out, apagando el gate en
        todo destino que declare `[tool.motor]` para cualquier otra cosa.
        """
        head = (
            '[project]\nname = "fixture"\nversion = "0"\n'
            'requires-python = ">=3.10"\n\n[tool.motor]\n'
        )
        for body, esperado in (
            ("format-check = false\n", "pyproject.toml"),
            ("format-check = true\n", None),
            ('format-check = "false"\n', None),
            ("otra-clave = true\n", None),
            # `0` es el caso que DISCRIMINA entre `is False` y un `not`
            # falsy-permisivo: sin el, aflojar la condicion a
            # `not motor.get("format-check", True)` sobrevive a la mutacion
            # (medido 2026-08-03: los 37 tests seguian verdes). Un `0` en un
            # campo booleano es dato mal escrito, no un permiso.
            ("format-check = 0\n", None),
            ('format-check = ""\n', None),
        ):
            (tmp_path / "pyproject.toml").write_text(head + body, encoding="utf-8")
            assert _format_check_optout(tmp_path) == esperado, (
                f"con `{body.strip()}` el opt-out deberia ser {esperado!r}"
            )

    def test_ruff_toml_no_es_sitio_valido_para_el_optout(self, tmp_path: Path) -> None:
        """`ruff.toml` NO puede alojar la declaracion: ruff rechaza el fichero.

        `ruff.toml` es config PLANA con esquema CERRADO -- sus claves van en la
        raiz y ruff valida el fichero entero. `[tool.motor]` (el convenio de
        `pyproject.toml`) lo hace irrecuperable, y una clave suelta en la raiz
        tampoco pasa: ambas dan `unknown field`, ruff aborta y `ruff check`
        sube de rc=0 a rc=2. Medido 2026-08-02 sobre ruff real:

            ruff failed
              Cause: TOML parse error at line 1, column 1
            unknown field `tool`

        Consecuencia doble, y por eso el offering original era una TRAMPA:
        escribirlo en `ruff.toml` rompe el gate de lint que el destino SI
        adopta, y ademas NO concede el opt-out -- el TOML deja de parsear,
        `_format_check_optout` es fail-closed y devuelve None. Se rompe el
        lint y se sigue bloqueado.

        Por eso `pyproject.toml` es el UNICO sitio soportado. Este test pinea
        que nadie vuelva a ofrecer `ruff.toml` como candidato.
        """
        source = _format_check_optout.__doc__ or ""
        assert "ruff.toml" not in source.split("Sitio soportado")[0], (
            "el docstring no puede ofrecer ruff.toml como sitio de la "
            "declaracion: ruff rechaza el fichero entero"
        )

        # Un ruff.toml con la declaracion NO concede opt-out (fail-closed).
        (tmp_path / "ruff.toml").write_text(
            "line-length = 88\n\n[tool.motor]\nformat-check = false\n",
            encoding="utf-8",
        )
        assert _format_check_optout(tmp_path) is None, (
            "ruff.toml con [tool.motor] no parsea como config de ruff; "
            "aceptarlo aqui daria un opt-out que rompe el lint del destino"
        )

    def test_optout_malformado_no_apaga_el_gate(self, tmp_path: Path) -> None:
        """Un TOML corrupto es fail-closed: ante duda, el gate muerde."""
        self._write_unformatted(tmp_path)
        (tmp_path / "ruff.toml").write_text(
            "[tool.motor\nformat-check = false\n", encoding="utf-8"
        )

        result = run_ruff_format_check(tmp_path)

        assert result.passed is False


class TestAgentControllerValidate:
    """Tests for agent_controller --validate integration."""

    def test_controller_validate_passes(self, tmp_path: Path) -> None:
        """Test when agent_controller --validate passes."""
        mock_result = subprocess.CompletedProcess(
            args=[
                "python",
                ".agent/agent_controller.py",
                "--validate",
                "--json",
                "--force",
            ],
            returncode=0,
            stdout='{"status": "valid"}\n',
            stderr="",
        )

        with patch("subprocess.run", return_value=mock_result):
            result = run_agent_controller_validate(tmp_path)

        assert result.name == "Agent Controller Validate"
        assert result.passed is True
        assert result.is_blocking is True

    def test_controller_validate_fails(self, tmp_path: Path) -> None:
        """Test when agent_controller --validate fails."""
        mock_result = subprocess.CompletedProcess(
            args=[
                "python",
                ".agent/agent_controller.py",
                "--validate",
                "--json",
                "--force",
            ],
            returncode=1,
            stdout="",
            stderr="Validation error: work_plan.md missing\n",
        )

        with patch("subprocess.run", return_value=mock_result):
            result = run_agent_controller_validate(tmp_path)

        assert result.name == "Agent Controller Validate"
        assert result.passed is False
        assert "Validation error" in result.output
        assert result.is_blocking is True


class TestGitStatusCheck:
    """Tests for git status --short integration."""

    def test_git_status_clean(self, tmp_path: Path) -> None:
        """Test when git status shows clean tree."""
        mock_result = subprocess.CompletedProcess(
            args=["git", "status", "--short"],
            returncode=0,
            stdout="",
            stderr="",
        )

        with (
            patch("runtime.motor_link.resolve_motor_root", return_value=tmp_path),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = run_git_status_check(tmp_path)

        assert result.name == "Git Status Check"
        assert result.passed is True
        assert "limpio" in result.output
        assert result.is_blocking is True

    def test_git_status_dirty(self, tmp_path: Path) -> None:
        """Test when git status shows dirty tree."""
        mock_result = subprocess.CompletedProcess(
            args=["git", "status", "--short"],
            returncode=0,
            stdout="M scripts/prepush_check.py\n?? tests/test_prepush_check.py\n",
            stderr="",
        )

        with (
            patch("runtime.motor_link.resolve_motor_root", return_value=tmp_path),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = run_git_status_check(tmp_path)

        assert result.name == "Git Status Check"
        assert result.passed is False
        assert "sucio" in result.output
        assert "scripts/prepush_check.py" in result.output
        assert result.is_blocking is True

    def test_git_status_command_not_found(self, tmp_path: Path) -> None:
        """Test when git command is not found."""
        with (
            patch("runtime.motor_link.resolve_motor_root", return_value=tmp_path),
            patch("subprocess.run", side_effect=FileNotFoundError("git")),
        ):
            result = run_git_status_check(tmp_path)

        assert result.name == "Git Status Check"
        assert result.passed is True  # Tolerated as non-blocking WARN
        assert "no encontrado" in result.output
        assert result.is_blocking is False  # Workspace no-repo is tolerated

    def test_git_status_command_error(self, tmp_path: Path) -> None:
        """Test when git status returns non-zero exit code."""
        mock_result = subprocess.CompletedProcess(
            args=["git", "status", "--short"],
            returncode=128,
            stdout="",
            stderr="fatal: not a git repository",
        )

        with (
            patch("runtime.motor_link.resolve_motor_root", return_value=tmp_path),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = run_git_status_check(tmp_path)

        assert result.name == "Git Status Check"
        assert result.passed is True  # Tolerated as non-blocking WARN
        assert "Workspace no-repo" in result.output
        assert "exit 128" in result.output
        assert result.is_blocking is False  # Workspace no-repo is tolerated


class TestValidateAll:
    """Tests for skills/validate_all.py integration."""

    def test_validate_all_passes(self, tmp_path: Path) -> None:
        """Test when validate_all passes."""
        mock_result = subprocess.CompletedProcess(
            args=["python", "skills/validate_all.py"],
            returncode=0,
            stdout="All validations passed\n",
            stderr="",
        )

        with patch("subprocess.run", return_value=mock_result):
            result = run_validate_all(tmp_path)

        assert result.name == "Validate All (informacional)"
        assert result.passed is True
        assert result.is_blocking is False  # Non-blocking

    def test_validate_all_fails(self, tmp_path: Path) -> None:
        """Test when validate_all fails - still non-blocking."""
        mock_result = subprocess.CompletedProcess(
            args=["python", "skills/validate_all.py"],
            returncode=1,
            stdout="",
            stderr="Validation failed\n",
        )

        with patch("subprocess.run", return_value=mock_result):
            result = run_validate_all(tmp_path)

        assert result.name == "Validate All (informacional)"
        assert result.passed is False
        assert result.is_blocking is False  # Still non-blocking

    def test_validate_all_uses_motor_path_when_running_in_destino(
        self, tmp_path: Path
    ) -> None:
        """Destination preflight must execute the motor-owned validate_all script."""
        mock_result = subprocess.CompletedProcess(
            args=["python", "validate_all.py"],
            returncode=0,
            stdout="All validations passed\n",
            stderr="",
        )
        motor_root = tmp_path / "motor"
        validate_all = motor_root / "skills" / "validate_all.py"
        validate_all.parent.mkdir(parents=True, exist_ok=True)
        validate_all.write_text("# stub\n", encoding="utf-8")

        with (
            patch("runtime.motor_link.resolve_motor_root", return_value=motor_root),
            patch("subprocess.run", return_value=mock_result) as mock_run,
        ):
            result = run_validate_all(tmp_path)

        assert result.passed is True
        called_cmd = mock_run.call_args.args[0]
        assert called_cmd[1] == str(validate_all)
        assert mock_run.call_args.kwargs["cwd"] == tmp_path


class TestPreflightCheckIntegration:
    """Integration tests for the full preflight check."""

    def test_clean_path_all_checks_pass(self, tmp_path: Path) -> None:
        """Test clean path: all five blocking checks pass, exit 0."""
        # Mock all the individual check functions to return passing CheckResults
        mock_result = CheckResult(name="Mock", passed=True, output="OK")

        with (
            patch(
                "scripts.prepush_check.run_delivery_hygiene_check",
                return_value=mock_result,
            ),
            patch("scripts.prepush_check.run_ruff_check", return_value=mock_result),
            patch(
                "scripts.prepush_check.run_ruff_format_check", return_value=mock_result
            ),
            patch(
                "scripts.prepush_check.run_agent_controller_validate",
                return_value=mock_result,
            ),
            patch(
                "scripts.prepush_check.run_git_status_check", return_value=mock_result
            ),
            patch(
                "scripts.prepush_check.run_portable_memory_archive_check",
                return_value=mock_result,
            ),
            patch("scripts.prepush_check.run_validate_all", return_value=mock_result),
        ):
            exit_code = run_preflight_check(tmp_path)

        assert exit_code == 0

    def test_dirty_tree_path(self, tmp_path: Path) -> None:
        """Test dirty tree path: git status returns output, exit 1."""
        mock_pass = CheckResult(name="Mock", passed=True, output="OK")
        mock_fail = CheckResult(
            name="Git Status", passed=False, output="Dirty", is_blocking=True
        )

        with (
            patch(
                "scripts.prepush_check.run_delivery_hygiene_check",
                return_value=mock_pass,
            ),
            patch("scripts.prepush_check.run_ruff_check", return_value=mock_pass),
            patch(
                "scripts.prepush_check.run_ruff_format_check", return_value=mock_pass
            ),
            patch(
                "scripts.prepush_check.run_agent_controller_validate",
                return_value=mock_pass,
            ),
            patch("scripts.prepush_check.run_git_status_check", return_value=mock_fail),
            patch("scripts.prepush_check.run_validate_all", return_value=mock_pass),
        ):
            exit_code = run_preflight_check(tmp_path)

        assert exit_code == 1

    def test_mutating_hook_in_prepush(self, tmp_path: Path) -> None:
        """Test mutating hook in pre-push detected by delivery_hygiene_check, exit 1."""
        mock_pass = CheckResult(name="Mock", passed=True, output="OK")
        mock_fail = CheckResult(
            name="Delivery Hygiene",
            passed=False,
            output="Mutator detected",
            is_blocking=True,
        )

        with (
            patch(
                "scripts.prepush_check.run_delivery_hygiene_check",
                return_value=mock_fail,
            ),
            patch("scripts.prepush_check.run_ruff_check", return_value=mock_pass),
            patch(
                "scripts.prepush_check.run_ruff_format_check", return_value=mock_pass
            ),
            patch(
                "scripts.prepush_check.run_agent_controller_validate",
                return_value=mock_pass,
            ),
            patch("scripts.prepush_check.run_git_status_check", return_value=mock_pass),
            patch("scripts.prepush_check.run_validate_all", return_value=mock_pass),
        ):
            exit_code = run_preflight_check(tmp_path)

        assert exit_code == 1

    def test_ruff_check_failure_blocks(self, tmp_path: Path) -> None:
        """Test that ruff check failure blocks the preflight."""
        mock_pass = CheckResult(name="Mock", passed=True, output="OK")
        mock_fail = CheckResult(
            name="Ruff", passed=False, output="E501", is_blocking=True
        )

        with (
            patch(
                "scripts.prepush_check.run_delivery_hygiene_check",
                return_value=mock_pass,
            ),
            patch("scripts.prepush_check.run_ruff_check", return_value=mock_fail),
            patch(
                "scripts.prepush_check.run_ruff_format_check", return_value=mock_pass
            ),
            patch(
                "scripts.prepush_check.run_agent_controller_validate",
                return_value=mock_pass,
            ),
            patch("scripts.prepush_check.run_git_status_check", return_value=mock_pass),
            patch("scripts.prepush_check.run_validate_all", return_value=mock_pass),
        ):
            exit_code = run_preflight_check(tmp_path)

        assert exit_code == 1

    def test_validate_all_failure_does_not_block(self, tmp_path: Path) -> None:
        """Test that validate_all failure does not block the preflight."""
        mock_pass = CheckResult(name="Mock", passed=True, output="OK")
        mock_fail_nonblocking = CheckResult(
            name="Validate All", passed=False, output="Failed", is_blocking=False
        )

        with (
            patch(
                "scripts.prepush_check.run_delivery_hygiene_check",
                return_value=mock_pass,
            ),
            patch("scripts.prepush_check.run_ruff_check", return_value=mock_pass),
            patch(
                "scripts.prepush_check.run_ruff_format_check", return_value=mock_pass
            ),
            patch(
                "scripts.prepush_check.run_agent_controller_validate",
                return_value=mock_pass,
            ),
            patch("scripts.prepush_check.run_git_status_check", return_value=mock_pass),
            patch(
                "scripts.prepush_check.run_portable_memory_archive_check",
                return_value=mock_pass,
            ),
            patch(
                "scripts.prepush_check.run_validate_all",
                return_value=mock_fail_nonblocking,
            ),
        ):
            exit_code = run_preflight_check(tmp_path)

        assert exit_code == 0  # validate_all is non-blocking

    def test_skip_gates_degrades_blocking_failure_to_exit_zero(
        self, tmp_path: Path
    ) -> None:
        """WOT-2026-020i: with skip_gates=True, a BLOCKING failure still runs and
        prints, but no longer forces exit 1 (operator closes over known debt).

        Mutation: drop the `if skip_gates: return 0` short-circuit in
        run_preflight_check and this test goes RED (the blocking failure would
        force exit 1 again).
        """
        mock_pass = CheckResult(name="Mock", passed=True, output="OK")
        mock_fail = CheckResult(
            name="Ruff", passed=False, output="E501", is_blocking=True
        )

        with (
            patch(
                "scripts.prepush_check.run_delivery_hygiene_check",
                return_value=mock_pass,
            ),
            patch("scripts.prepush_check.run_ruff_check", return_value=mock_fail),
            patch(
                "scripts.prepush_check.run_ruff_format_check", return_value=mock_pass
            ),
            patch(
                "scripts.prepush_check.run_agent_controller_validate",
                return_value=mock_pass,
            ),
            patch("scripts.prepush_check.run_git_status_check", return_value=mock_pass),
            patch("scripts.prepush_check.run_validate_all", return_value=mock_pass),
        ):
            blocked = run_preflight_check(tmp_path)
            skipped = run_preflight_check(tmp_path, skip_gates=True)

        assert blocked == 1, "without skip_gates a blocking ruff failure blocks"
        assert skipped == 0, "with skip_gates the same failure no longer blocks"


class TestCheckResult:
    """Tests for CheckResult named tuple."""

    def test_check_result_creation(self) -> None:
        """Test CheckResult can be created with default values."""
        result = CheckResult(
            name="Test Check",
            passed=True,
            output="All good",
        )

        assert result.name == "Test Check"
        assert result.passed is True
        assert result.output == "All good"
        assert result.is_blocking is True

    def test_check_result_non_blocking(self) -> None:
        """Test CheckResult can be created as non-blocking."""
        result = CheckResult(
            name="Informacional",
            passed=False,
            output="Failed but ok",
            is_blocking=False,
        )

        assert result.is_blocking is False


class TestPortableMemoryArchiveCheck:
    """WOT-2026-038j: the guard must resolve its script against the MOTOR.

    The gate lives ONLY in the motor (`scripts/check_portable_memory_archive_schema.py`).
    Building its path from `project_root` makes the gate self-destruct whenever
    motor != destino -- the real topology of this repo -- with a FALSE RED
    ("can't open file ... under the destino's scripts/"), blocking the closeout
    for a file that was never supposed to be there.
    """

    def test_script_path_resolves_to_motor_not_destination(
        self, tmp_path: Path
    ) -> None:
        """The command must point at the motor's copy of the guard.

        `tmp_path` stands for a repo_destino that has no `scripts/` at all.
        Mutation: rebuild the path from `project_root` and this goes red,
        because the destination path does not exist.
        """
        captured: dict = {}

        def _fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return CheckResult(name="x", passed=True, output="", is_blocking=False)

        with patch("scripts.prepush_check.run_subprocess_check", _fake_run):
            run_portable_memory_archive_check(tmp_path)

        script_arg = Path(captured["cmd"][1])
        assert script_arg.is_file(), (
            f"the guard script must resolve to an EXISTING file; got {script_arg}. "
            "Building it from project_root self-destructs when motor != destino."
        )
        assert tmp_path not in script_arg.parents, (
            f"the guard script must NOT be resolved under the destino ({tmp_path}); "
            f"got {script_arg}"
        )

    def test_motor_root_argument_is_the_motor(self, tmp_path: Path) -> None:
        """`--motor-root` must carry the motor, not the destino.

        Passing the destino makes the guard audit the WRONG archive (or none),
        which is a false green rather than a false red -- the worse failure.
        """
        captured: dict = {}

        def _fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return CheckResult(name="x", passed=True, output="", is_blocking=False)

        with patch("scripts.prepush_check.run_subprocess_check", _fake_run):
            run_portable_memory_archive_check(tmp_path)

        cmd = captured["cmd"]
        motor_root_value = Path(cmd[cmd.index("--motor-root") + 1])
        assert motor_root_value != tmp_path, (
            "--motor-root must not be the destino: the guard would audit the wrong "
            "archive (false green)."
        )
        assert (motor_root_value / "scripts").is_dir(), (
            f"--motor-root must point at a real motor checkout; got {motor_root_value}"
        )
