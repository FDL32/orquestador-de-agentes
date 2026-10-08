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

import hashlib
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import prepush_check as pc_module  # noqa: E402
from prepush_check import run_ruff_check, run_ruff_format_check  # noqa: E402


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


# ============================================================================
# WOT-2026-047i: mismo aislamiento para `run_ruff_check` (residuo del preflight).
#
# `run_ruff_format_check` ya fue aislado (bloque de arriba). `run_ruff_check`
# seguia invocando `uv run ruff check .` con cwd=project_root, materializando
# .venv/ y uv.lock en el arbol que el preflight audita justo antes de que
# `run_pytest_safe` prefiera ese venv vacio -> falsos rojos de import. Ademas se
# demuestra (D3) que el gate de higiene sigue siendo valido frente a los dos
# gates `uv run` del preflight, por igualdad de snapshot sobre los gates 1-3.
# ============================================================================


def _snapshot_tree(root: Path) -> dict[str, str]:
    """Snapshot determinista del arbol, EXCLUYENDO `.git/`.

    Se excluye `.git/` a proposito: `run_delivery_hygiene_check` ejecuta
    `git status --porcelain`, que puede tocar el index del repo del fixture y
    volveria `A != B` de forma flaky sin que ningun gate haya escrito en el
    arbol auditado (WOT-2026-047i, correccion MI2). Para cada ruta relativa se
    guarda `<dir>` si es directorio o el sha256 de sus bytes si es fichero.
    """
    snapshot: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if ".git" in rel.parts:
            continue
        key = rel.as_posix()
        if path.is_dir():
            snapshot[key] = "<dir>"
        elif path.is_file():
            snapshot[key] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    """Ejecuta git en `root` con identidad INLINE (nunca la global/del motor)."""
    return subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def _make_d3_fixture(root: Path) -> Path:
    """Fixture de D3: proyecto minimo + `.git` propio + config de pre-commit.

    `.pre-commit-config.yaml` MINIMO PERO PARSEABLE: `repos: []` haria que
    `load_pre_commit_config` devuelva None y la higiene retornase 1 SIN medir
    nada (falso verde). `smoke` queda FUERA de `MUTATING_HOOKS` y de
    `formatting_hooks`, asi que la higiene mide de verdad y pasa.
    """
    _make_formatted_project(root)
    (root / ".pre-commit-config.yaml").write_text(
        "repos:\n  - repo: local\n    hooks:\n      - id: smoke\n",
        encoding="utf-8",
    )
    _git(root, "init")
    _git(
        root,
        "-c",
        "user.email=fixture@test",
        "-c",
        "user.name=fixture",
        "add",
        "-A",
    )
    _git(
        root,
        "-c",
        "user.email=fixture@test",
        "-c",
        "user.name=fixture",
        "commit",
        "-m",
        "fixture",
    )
    return root


# ------------------------------------------------- D2a REGRESION POSITIVA ruff check
def test_ruff_check_no_venv_or_lock_with_isolation(tmp_path):
    """(D2a) Con `--isolated`, `run_ruff_check` NO crea .venv/ ni uv.lock.

    Criterio principal del ticket: el preflight no materializa esos artefactos
    en el project_root que audita. MUTACION que lo mata: retirar `--isolated`
    del cmd de `run_ruff_check` -> aparecen .venv/ y uv.lock en tmp_path.
    """
    _make_formatted_project(tmp_path)

    run_ruff_check(tmp_path)

    file_names = {f.name for f in tmp_path.iterdir()}
    assert ".venv" not in file_names, (
        f".venv fue creado en el arbol auditado: {file_names}"
    )
    assert "uv.lock" not in file_names, (
        f"uv.lock fue creado en el arbol auditado: {file_names}"
    )


# --------------------------------------------- D2b MUTATION (cmd PRE-fix real)
def test_ruff_check_creates_venv_and_lock_without_isolation(tmp_path):
    """(D2b, MUTACION real) sin `--isolated` -> .venv/ y uv.lock SI se crean.

    Ejecuta `uv run ruff check .` REAL (sin mocks), reproduciendo literalmente
    el cmd PRE-fix, para demostrar la premisa del ticket con evidencia real:
    el cmd sin `--isolated` materializa los artefactos en el arbol auditado.
    """
    _make_formatted_project(tmp_path)

    subprocess.run(
        ["uv", "run", "ruff", "check", "."],
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


# ------------------------------------------------------- D2c CMD VERIFICATION
def test_ruff_check_cmd_contains_isolated_after_run(tmp_path):
    """(D2c) El cmd de `run_ruff_check` lleva `--isolated` justo tras `run`.

    Mock LEGITIMO: solo intercepta `run_subprocess_check` para CAPTURAR el cmd
    construido, sin fabricar resultado ni artefacto. Asevera la posicion exacta
    del flag (inmediatamente despues de `run`) y que se conservan el target `.`
    y `_ruff_exclude_args()`. MUTACION: retirar `--isolated` -> cae.
    """
    from prepush_check import CheckResult

    _make_formatted_project(tmp_path)

    captured_cmd: list[str] = []

    def _capture_run(cmd, name, project_root, capture_output=True):  # type: ignore[no-untyped-def]
        captured_cmd.extend(cmd)
        return CheckResult(name=name, passed=True, output="", is_blocking=True)

    with patch.object(pc_module, "run_subprocess_check", side_effect=_capture_run):
        run_ruff_check(tmp_path)

    assert "--isolated" in captured_cmd, (
        f"--isolated debe estar en el cmd, salio: {captured_cmd}"
    )
    assert captured_cmd.index("--isolated") == captured_cmd.index("run") + 1, (
        f"--isolated debe ir inmediatamente tras 'run', salio: {captured_cmd}"
    )
    assert "." in captured_cmd, f"el target '.' debe conservarse: {captured_cmd}"
    assert "--extend-exclude" in captured_cmd, (
        f"_ruff_exclude_args() debe conservarse: {captured_cmd}"
    )


# ------------------------------------------------------ D2d CONTROL NEGATIVO
def test_ruff_check_behavior_preserved(tmp_path):
    """(D2d) Control negativo: un rc!=0 sigue dando passed=False y bloqueante.

    El aislamiento no cambia el comportamiento observable del check. Se usa el
    mismo patron de mock que `TestRuffCheck` (Read/inspect only).
    """
    _make_formatted_project(tmp_path)

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
    assert result.is_blocking is True
    assert "E501" in result.output


# ------------------------------------------ D3 HIGIENE VALIDA PARA EL ARBOL FINAL
def test_delivery_hygiene_holds_for_final_tree_after_ruff_checks(tmp_path):
    """(D3, alcance acotado a gates 1-3) La higiene sigue valida tras los `uv run`.

    `Delivery Hygiene Check` corre en posicion 1; con el fix, los DOS unicos
    invocadores de `uv` del preflight (gates 2-3) pasan a ser read-only, asi que
    el arbol que la higiene midio no cambia. Se demuestra por IGUALDAD DE
    SNAPSHOT (excluyendo `.git/`) antes y despues de invocar ambos gates.

    NO se extiende al gate 4 (`run_agent_controller_validate`), escritor
    condicional CONOCIDO fuera de alcance (TT-4).

    Artefacto de entorno NEUTRALIZADO (hallazgo 2026-10-08): el fixture cuelga
    de `tests/sandbox/` (bajo el arbol del motor), asi que `uv` DESCUBRE el
    `uv.toml` del motor por walk-up del parent, cuyo `cache-dir` es RELATIVO
    (`cache-dir = '.agent/runtime/uv-cache'`). uv lo resuelve contra `cwd`, de
    modo que AMBOS gates `uv run` (incluso el ya aislado `run_ruff_format_check`)
    escriben `.agent/runtime/uv-cache/` DENTRO del fixture con o sin el fix --
    una cache gitignored y fuera del alcance operativo (ver
    `prepush_check._ruff_exclude_args` y `encoding_guard.py`), no la
    contaminacion productiva (`.venv`/`uv.lock`) que el ticket persigue. Se
    redirige `UV_CACHE_DIR` a un directorio FUERA del snapshot durante las dos
    invocaciones (misma clase de neutralizacion de entorno que
    `test_unformatted_code_still_blocks`), para que el snapshot pueda seguir
    excluyendo EXACTAMENTE `.git/` como fija el contrato.

    MUTACION: retirar `--isolated` del cmd de `run_ruff_check` -> .venv/uv.lock
    aparecen DESPUES de que la higiene midio -> snapshot_b != snapshot_a -> cae.
    """
    _make_d3_fixture(tmp_path)

    assert pc_module.run_delivery_hygiene_check(tmp_path).passed is True, (
        "la higiene debe MEDIR y pasar; sin este assert el test podria quedar "
        "verde sin que la higiene hubiera medido nada (falso verde)"
    )

    ultima_cache = tmp_path.parent / f"{tmp_path.name}-uvcache"

    snapshot_a = _snapshot_tree(tmp_path)
    with patch.dict(os.environ, {"UV_CACHE_DIR": str(ultima_cache)}):
        pc_module.run_ruff_check(tmp_path)
        pc_module.run_ruff_format_check(tmp_path)
    snapshot_b = _snapshot_tree(tmp_path)

    assert snapshot_a == snapshot_b, (
        "los gates 2-3 (uv run) no deben mutar el arbol que la higiene (gate 1) "
        f"midio. Diff: {sorted(set(snapshot_b) ^ set(snapshot_a))}"
    )
