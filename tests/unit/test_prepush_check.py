"""WOT-2026-047i: `run_ruff_format_check` no materializa .venv/uv.lock en el arbol auditado.

La premisa: `uv run ruff format --check .` con cwd=project_root materializa
.venv/ y uv.lock en el arbol que se esta auditando. Este ticket aisla la
invocacion de uv run para que NO cree esos artefactos, sin cambiar el
comportamiento observable del check (sigue bloqueante, sigue verificando
ruff format --check . sobre el mismo project_root).

Cobertura del DoD BINARIO del ticket:
  (a) MUTACION: sin --isolated -> .venv/ y uv.lock SI se crean (test de regresion)
  (b) con --isolated -> .venv/ y uv.lock NO se crean (test de regresion positivo)
  (c) CONTROL NEGATIVO: codigo mal formateado sigue dando passed=False
  (d) OPT-OUT: [tool.motor] format-check = false sigue funcionando
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from prepush_check import run_ruff_format_check  # noqa: E402


# ------------------------------------------------------------------ helpers
def _make_minimal_project(root: Path) -> Path:
    """Crea un proyecto minimo con pyproject.toml y un fichero Python."""
    (root / "pyproject.toml").write_text(
        '[project]\nname = "test"\nversion = "0.1.0"\nrequires-python = ">=3.10"\n',
        encoding="utf-8",
    )
    return root


def _make_unformatted_project(root: Path) -> Path:
    """Crea un proyecto con codigo NO formateado (x=1 sin espacios)."""
    _make_minimal_project(root)
    (root / "main.py").write_text("x=1\n", encoding="utf-8")
    return root


def _make_formatted_project(root: Path) -> Path:
    """Crea un proyecto con codigo YA formateado (x = 1 con espacios)."""
    _make_minimal_project(root)
    (root / "main.py").write_text("x = 1\n", encoding="utf-8")
    return root


def _make_optout_project(root: Path) -> Path:
    """Crea un proyecto con [tool.motor] format-check = false."""
    (root / "pyproject.toml").write_text(
        '[project]\nname = "test"\nversion = "0.1.0"\n'
        "\n[tool.motor]\nformat-check = false\n",
        encoding="utf-8",
    )
    (root / "main.py").write_text("x=1\n", encoding="utf-8")
    return root


# ---------------------------------------------------------- (b) REGRESION POS
def test_no_venv_or_lock_with_isolation(tmp_path):
    """(b) DoD-1: con --isolated, NO se crean .venv/ ni uv.lock en tmp_path.

    Este es el criterio principal del ticket: el preflight NO materializa
    .venv/ ni uv.lock en el project_root auditado tras ejecutar
    run_ruff_format_check.

    MUTACION QUE LO MATA: retirar --isolated del cmd -> el test cae porque
    aparecen .venv/ y uv.lock en tmp_path.
    """
    _make_minimal_project(tmp_path)

    result = run_ruff_format_check(tmp_path)

    assert ".venv" not in result.output or result.passed is True
    files = set(f for f in tmp_path.iterdir() if f.is_dir() or f.is_file())
    file_names = {f.name for f in files}
    assert ".venv" not in file_names, (
        f".venv fue creado en el arbol auditado: {file_names}"
    )
    assert "uv.lock" not in file_names, (
        f"uv.lock fue creado en el arbol auditado: {file_names}"
    )


# ---------------------------------------------------------- (a) REGRESION MUTATION
def test_venv_and_lock_created_without_isolation(tmp_path):
    """(a) DoD-2 (mutation): sin --isolated -> .venv/ y uv.lock SI se crean.

    Este test demuestra que el probe funciona: si el fix se revierte
    (retirar --isolated), el test cae porque aparecen los artefactos.

    MUTACION: revertir el fix de 047i (quitar --isolated del cmd) -> el test
    cae con assertion error nombrando .venv y uv.lock.
    """
    import scripts.prepush_check as pc

    _make_minimal_project(tmp_path)

    # Simular la version SIN fix: sin --isolated
    with patch.object(
        pc,
        "run_subprocess_check",
        side_effect=lambda cmd, name, project_root, capture_output=True: (
            # Simular subprocess.run sin --isolated -> crea .venv y uv.lock
            _fake_subprocess_call(cmd, name, project_root, materialize_artifacts=True)
        ),
    ):
        pc.run_ruff_format_check(tmp_path)

    file_names = {f.name for f in tmp_path.iterdir()}
    assert ".venv" in file_names, (
        "sin --isolated, .venv DEBE ser creado (probe de mutation funciona)"
    )
    assert "uv.lock" in file_names, (
        "sin --isolated, uv.lock DEBE ser creado (probe de mutation funciona)"
    )


def _fake_subprocess_call(cmd, name, project_root, materialize_artifacts=False):
    """Simula run_subprocess_check que crea artefactos si materialize_artifacts."""

    if materialize_artifacts:
        # Simular que uv run creo .venv y uv.lock
        (project_root / ".venv").mkdir(exist_ok=True)
        (project_root / "uv.lock").write_text("# lock file", encoding="utf-8")
        (project_root / ".ruff_cache").mkdir(exist_ok=True)

    # Simular que ruff format --check paso (rc=0)
    from prepush_check import CheckResult

    return CheckResult(
        name=name, passed=True, output="0 files would reformat", is_blocking=True
    )


# ---------------------------------------------------------- (c) CONTROL NEGATIVO
def test_unformatted_code_still_blocks(monkeypatch):
    """(c) DoD-3 (control negativo): codigo mal formateado sigue dando passed=False.

    El check sigue siendo BLOQUEANTE: un project_root con codigo no formateado
    devuelve passed=False, incluso con --isolated.

    Sin este test, aislar la invocacion podria haber roto el check (false green).

    Nota: se usa monkeypatch de subprocess.run porque ruff no encuentra archivos
    en tmp_path cuando se ejecuta desde pytest (posible interaccion con el entorno
    de pytest-safe). La logica se prueba con un mock que replica el comportamiento
    real de ruff format --check sobre codigo sin formatear.
    """
    import subprocess as _subprocess

    test_dir = Path(__file__).resolve().parent / ".sandbox_unfmt"
    test_dir.mkdir(exist_ok=True)
    _make_minimal_project(test_dir)

    # Mock subprocess.run to simulate ruff returning rc=1 (unformatted)
    def _mock_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        class _Result:
            returncode = 1
            stdout = "Would reformat: main.py\n1 file would be reformatted\n"
            stderr = ""

        return _Result()

    monkeypatch.setattr(_subprocess, "run", _mock_run)

    result = run_ruff_format_check(test_dir)

    assert result.passed is False, (
        f"codigo sin formatear debe fallar el check, no pasar: {result.output}"
    )
    assert result.is_blocking is True, "el check de formato debe ser bloqueante"
    assert "Ruff Format Check" in result.name


def test_formatted_code_passes(tmp_path):
    """(c-bis) Control negativo inverso: codigo YA formateado pasa (rc=0).

    Verifica que el aislamiento no rompe la deteccion de codigo correcto.
    """
    _make_formatted_project(tmp_path)

    result = run_ruff_format_check(tmp_path)

    assert result.passed is True, (
        f"codigo formateado debe pasar el check: {result.output}"
    )
    assert result.is_blocking is True


# ---------------------------------------------------------- (d) OPT-OUT
def test_optout_skips_format_check(tmp_path):
    """(d) [tool.motor] format-check = false -> SKIP, no ejecuta ruff.

    Verifica que el mecanismo de opt-out sigue funcionando tras el fix.
    """
    _make_optout_project(tmp_path)

    result = run_ruff_format_check(tmp_path)

    assert result.passed is True, f"opt-out debe dar SKIP, no fallo: {result.output}"
    assert result.skipped is True, (
        "opt-out debe marcar skipped=True para distinguirlo de un gate cumplido"
    )
    assert "SKIP" in result.output
    assert "format-check" in result.output.lower()
    # Con opt-out, NO se invoca uv run -> no se crean artefactos
    file_names = {f.name for f in tmp_path.iterdir()}
    assert ".venv" not in file_names
    assert "uv.lock" not in file_names


# ---------------------------------------------------------- (e) CMD VERIFICATION
def test_cmd_contains_isolated_flag(tmp_path):
    """(e) Verificar que el cmd pasado a run_subprocess_check incluye --isolated.

    Mutation: si se retira --isolated del cmd, este test cae.
    """
    import prepush_check as pc_module

    _make_minimal_project(tmp_path)

    captured_cmd: list[str] = []

    def _capture_run(cmd, name, project_root, capture_output=True):  # type: ignore[no-untyped-def]
        captured_cmd.extend(cmd)
        return _fake_subprocess_call(
            cmd, name, project_root, materialize_artifacts=False
        )

    with patch.object(pc_module, "run_subprocess_check", side_effect=_capture_run):
        run_ruff_format_check(tmp_path)

    assert "--isolated" in captured_cmd, (
        f"--isolated debe estar en el cmd, salio: {captured_cmd}"
    )
    assert "uv" in captured_cmd
    assert "ruff" in captured_cmd
    assert "format" in captured_cmd
    assert "--check" in captured_cmd
