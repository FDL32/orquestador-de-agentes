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

Nota (Manager review WOT-2026-047i, 2026-09-19): (a) y (c) se reescribieron
para ejecutar `uv run`/`ruff` REAL en vez de mockear el resultado -- las
versiones originales fabricaban el efecto esperado con un mock en vez de
demostrarlo, y (a) en particular pasaba igual con o sin el fix real
(mutation-verify del Manager: worktree en el commit pre-fix, mismo test,
exit_code=0 -- falso verde). Verificado tras la correccion: mutation-verify
sin_fix exit_code=1, con_fix exit_code=0.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import prepush_check as pc_module  # noqa: E402
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

    Ejecuta `uv run` REAL (sin mock de subprocess) reproduciendo literalmente
    el cmd PRE-fix (`uv run ruff format --check .`, sin `--isolated`), para
    demostrar la premisa del ticket con evidencia real, no fabricada.

    MUTACION QUE LO VERIFICA (Manager review WOT-2026-047i, revision del test
    original que mockeaba run_subprocess_check y pasaba con o sin el fix):
    corrido contra el codigo pre-fix (worktree en 6684d1d) -> este test PASA
    (los artefactos SI aparecen, confirmando la premisa); corrido contra el
    codigo con fix -> vease test_no_venv_or_lock_with_isolation, que es el que
    prueba la AUSENCIA con el cmd real ya parcheado.
    """
    _make_minimal_project(tmp_path)

    # cmd PRE-fix literal (antes de anadir --isolated), ejecutado tal cual
    # ejecutaria uv en la maquina real: sin mocks.
    subprocess.run(
        ["uv", "run", "ruff", "format", "--check", "."],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    file_names = {f.name for f in tmp_path.iterdir()}
    assert ".venv" in file_names, (
        f"sin --isolated, uv run DEBE materializar .venv en el arbol auditado: {file_names}"
    )
    assert "uv.lock" in file_names, (
        f"sin --isolated, uv run DEBE materializar uv.lock en el arbol auditado: {file_names}"
    )


# ---------------------------------------------------------- (c) CONTROL NEGATIVO
def test_unformatted_code_still_blocks(tmp_path):
    """(c) DoD-3 (control negativo): codigo mal formateado sigue dando passed=False.

    El check sigue siendo BLOQUEANTE: un project_root con codigo no formateado
    devuelve passed=False, incluso con --isolated (de uv).

    CAUSA RAIZ REAL investigada (Manager review WOT-2026-047i, 2026-09-19; el
    test original mockeaba subprocess.run completo alegando que "ruff no
    encuentra archivos en tmp_path" sin diagnosticar por que): el `tmp_path`
    de ESTA suite vive bajo `tests/sandbox/test_runtime/...`
    (ProjectTmpPathFactory, ver tests/conftest.py), y `pyproject.toml:35`
    excluye `tests/sandbox/` de ruff. Cuando `ruff` corre SIN su propio
    `--isolated` (config), hereda esa exclusion ascendente del
    `pyproject.toml` REAL del motor por mas que `cwd` sea el tmp_path
    sintetico, y no ve ningun fichero -- artefacto del ENTORNO DE TEST, no
    del comportamiento de produccion (donde `project_root` nunca vive bajo
    `tests/sandbox/`). Verificado con `uv run --isolated ... --verbose`: uv
    SI resuelve tmp_path como proyecto correcto; el hueco es la herencia de
    config de ruff.

    Mock LEGITIMO (envuelve la funcion real, no fabrica el resultado): se
    intercepta `run_subprocess_check` solo para inyectar el `--isolated` de
    RUFF (neutraliza el artefacto de entorno) y delega en la implementacion
    REAL, que ejecuta `subprocess.run` de verdad. El resultado que llega al
    assert es la salida genuina de ruff sobre codigo sin formatear, no un
    valor inventado.
    """
    _make_unformatted_project(tmp_path)

    real_run_subprocess_check = pc_module.run_subprocess_check

    def _inject_ruff_isolated(cmd, name, project_root, capture_output=True):
        patched_cmd = list(cmd)
        if "ruff" in patched_cmd:
            idx = patched_cmd.index("ruff")
            patched_cmd.insert(idx + 1, "--isolated")
        return real_run_subprocess_check(
            patched_cmd, name, project_root, capture_output
        )

    with patch.object(
        pc_module, "run_subprocess_check", side_effect=_inject_ruff_isolated
    ):
        result = run_ruff_format_check(tmp_path)

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

    Mock LEGITIMO: solo intercepta run_subprocess_check para CAPTURAR el cmd
    que run_ruff_format_check construye, sin fabricar ningun resultado ni
    artefacto -- no ejecuta el subproceso real (por velocidad), pero tampoco
    simula su efecto. La verificacion es sobre el ARGUMENTO construido, no
    sobre el comportamiento del proceso.

    Mutation: si se retira --isolated del cmd, este test cae.
    """
    from prepush_check import CheckResult

    _make_minimal_project(tmp_path)

    captured_cmd: list[str] = []

    def _capture_run(cmd, name, project_root, capture_output=True):  # type: ignore[no-untyped-def]
        captured_cmd.extend(cmd)
        return CheckResult(name=name, passed=True, output="", is_blocking=True)

    with patch.object(pc_module, "run_subprocess_check", side_effect=_capture_run):
        run_ruff_format_check(tmp_path)

    assert "--isolated" in captured_cmd, (
        f"--isolated debe estar en el cmd, salio: {captured_cmd}"
    )
    assert "uv" in captured_cmd
    assert "ruff" in captured_cmd
    assert "format" in captured_cmd
    assert "--check" in captured_cmd
