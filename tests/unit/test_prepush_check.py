"""WOT-2026-047i: `run_ruff_format_check` no materializa .venv/uv.lock en el arbol auditado.

WOT-2026-070m: `run_agent_controller_validate` anade `--no-heal` a la
invocacion de `agent_controller --validate` para que el preflight sea
READ-ONLY (evita que --validate sane el STATE.md del workspace auditado).

Cobertura del DoD BINARIO del ticket (047i):
  (a) MUTACION: sin --isolated -> .venv/ y uv.lock SI se crean (test de regresion)
  (b) con --isolated -> .venv/ y uv.lock NO se crean (test de regresion positivo)
  (c) CONTROL NEGATIVO: codigo mal formateado sigue dando passed=False
  (d) OPT-OUT: [tool.motor] format-check = false sigue funcionando

Cobertura del DoD BINARIO del ticket (070m):
  (a) REAL PATH: --no-heal -> STATE.md NO se reescribe bajo drift real (prepush)
  (b) CONTROL NEGATIVO: sin --no-heal, STATE.md SI se reescribe (anti-vacuidad)
  (c) CMD: el cmd de run_agent_controller_validate lleva --no-heal (mutacion muerde)

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
import json
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
from prepush_check import (  # noqa: E402
    run_agent_controller_validate,
    run_ruff_check,
    run_ruff_format_check,
)


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


# ============================================================================
# WOT-2026-056d: paridad de commits hermanos (par atomico motor+destino).
#
# DoD binario cubierto:
#   (a) declaracion legible por maquina -> `Sibling-Commit: <sha> [motor|destino]`
#   (b) closeout verifica paridad y FALLA si falta el hermano -> FAIL bloqueante
#   (c) MUTATION: publicar solo la mitad del motor -> ROJO citando el hermano
#   (d) CONTROL NEGATIVO: ticket de un repo NO dispara el check -> SKIP nombrado
# ============================================================================


def _make_repo_with_origin(root: Path) -> str:
    """Repo git propio con su origin BARE local y el commit base YA publicado.

    Hermetico: el remote es un bare dentro de tmp_path (nada de red). Devuelve
    el full sha de HEAD publicado. La barrera de vector git (CEM): el fixture
    tiene SU PROPIO `.git`, asi que `git -C root` jamas hace walk-up al repo
    real de la maquina.
    """
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-b", "main")
    (root / "base.txt").write_text("base\n", encoding="utf-8")
    _git(root, "-c", "user.email=fixture@test", "-c", "user.name=fixture", "add", "-A")
    _git(
        root,
        "-c",
        "user.email=fixture@test",
        "-c",
        "user.name=fixture",
        "commit",
        "-m",
        "base",
    )
    remote = root.parent / f"{root.name}-origin.git"
    _git(root, "clone", "--bare", str(root), str(remote))
    _git(root, "remote", "add", "origin", str(remote))
    _git(
        root,
        "-c",
        "user.email=fixture@test",
        "-c",
        "user.name=fixture",
        "push",
        "-u",
        "origin",
        "main",
    )
    return _git(root, "rev-parse", "HEAD").stdout.strip()


def _commit_sibling(
    root: Path, subject: str, trailer: str | None = None, push: bool = False
) -> str:
    """Commit nuevo en `root`; con `trailer` literal como parrafo del mensaje."""
    n = len(list(root.glob("work*.txt")))
    (root / f"work{n}.txt").write_text(f"{subject}\n", encoding="utf-8")
    _git(root, "-c", "user.email=fixture@test", "-c", "user.name=fixture", "add", "-A")
    msgs = ["-m", subject]
    if trailer:
        msgs += ["-m", trailer]
    _git(
        root,
        "-c",
        "user.email=fixture@test",
        "-c",
        "user.name=fixture",
        "commit",
        *msgs,
    )
    sha = _git(root, "rev-parse", "HEAD").stdout.strip()
    if push:
        _git(root, "push", "origin", "main")
    return sha


# ------------------------------------------------- (c) MUTATION: mitad publicada
def test_sibling_parity_half_published_fails(tmp_path):
    """(c) Publicar solo la mitad del motor -> el gate FALLA citando el hermano.

    El par: commit M en motor (PUBLISHED, base empujado) y commit D en destino
    que declara `Sibling-Commit: <M> motor` sin empujar (UNPUBLISHED). Es la
    simulacion exacta del fallo medido en WOT-2026-054p (f953519/9a0db6a),
    declarado ahora por contenido.

    MUTACION que lo mata: retirar la rama `pub_decl != pub_sib` del check ->
    el veredicto pasa a verde y este test cae.
    """
    motor_sha = _make_repo_with_origin(tmp_path / "motor")
    _make_repo_with_origin(tmp_path / "destino")
    dest_sha = _commit_sibling(
        tmp_path / "destino",
        "WOT-2026-001x: parte DESTINO",
        trailer=f"Sibling-Commit: {motor_sha[:9]} motor",
    )

    result = pc_module.run_sibling_commit_parity_check(
        tmp_path / "destino", motor_root=tmp_path / "motor"
    )

    assert result.passed is False, f"par medio publicado debe FALLAR: {result.output}"
    assert result.is_blocking is True, "la paridad de hermanos es BLOQUEANTE"
    assert motor_sha[:9] in result.output, "debe citar la mitad publicada"
    assert dest_sha[:9] in result.output, "debe citar el hermano AUSENTE (DoD c)"
    assert "PUBLISHED" in result.output and "UNPUBLISHED" in result.output


# ------------------------------------------------------ (b) par simetrico verde
def test_sibling_parity_both_published_passes(tmp_path):
    """(b) Ambas mitades publicadas -> PASS EJECUTADO (no SKIP).

    `skipped` debe ser False: la barrera corrio y verdicto paridad. Un verde
    por saltarse el check seria el `exit 0 = no hice nada` que CEM prohibe.
    """
    motor_sha = _make_repo_with_origin(tmp_path / "motor")
    _make_repo_with_origin(tmp_path / "destino")
    _commit_sibling(
        tmp_path / "destino",
        "WOT-2026-001x: parte DESTINO",
        trailer=f"Sibling-Commit: {motor_sha} motor",
        push=True,
    )

    result = pc_module.run_sibling_commit_parity_check(
        tmp_path / "destino", motor_root=tmp_path / "motor"
    )

    assert result.passed is True, f"par completo publicado debe pasar: {result.output}"
    assert result.skipped is False, "debe ser un PASS ejecutado, no un SKIP"
    assert "1 par" in result.output


def test_sibling_parity_neither_published_passes(tmp_path):
    """Ni mitad publicada (el cierre corre ANTES de empujar) -> paridad OK.

    Ambos sin publicar es simetrico: el gate castiga la PUBLICACION PARCIAL,
    no el trabajo aun sin publicar. Sin este caso el cierre de cualquier
    ticket de dos repos seria perpetuamente rojo antes de su propio push.
    """
    _make_repo_with_origin(tmp_path / "motor")
    _make_repo_with_origin(tmp_path / "destino")
    motor_sha = _commit_sibling(tmp_path / "motor", "WOT-2026-001x: parte MOTOR")
    _commit_sibling(
        tmp_path / "destino",
        "WOT-2026-001x: parte DESTINO",
        trailer=f"Sibling-Commit: {motor_sha[:9]}",
    )

    result = pc_module.run_sibling_commit_parity_check(
        tmp_path / "destino", motor_root=tmp_path / "motor"
    )

    assert result.passed is True, (
        f"ninguna mitad publicada es simetrico: {result.output}"
    )
    assert result.skipped is False


# ------------------------------------------------ (d) CONTROL NEGATIVO (SKIP)
def test_sibling_parity_single_repo_ticket_skips(tmp_path):
    """(d) Ticket de UN solo repo (ningun trailer) -> SKIP nombrado, no dispara.

    El DoD exige que el control negativo NO fabrique un verde silencioso:
    `skipped=True` y el motivo impreso (contrato de `CheckResult`).
    """
    _make_repo_with_origin(tmp_path / "motor")
    _make_repo_with_origin(tmp_path / "destino")
    _commit_sibling(tmp_path / "motor", "ticket de un solo repo", push=True)

    result = pc_module.run_sibling_commit_parity_check(
        tmp_path / "destino", motor_root=tmp_path / "motor"
    )

    assert result.passed is True
    assert result.skipped is True, "sin declaraciones el gate no corrio: SKIP"
    assert "SKIP" in result.output
    assert result.is_blocking is False


# ----------------------------------------------------- fail-closed: colgante
def test_sibling_parity_dangling_declaration_fails_with_two_roots(tmp_path):
    """Declaracion cuyo sha no resuelve en NINGUNA raiz (2 visibles) -> ROJO.

    Fail-closed, mismo precedente de `run_loop_execution_check`: una
    declaracion rota no puede verificar paridad. Y con UNA sola raiz visible
    la misma declaracion es no-comprobable -> SKIP nombrado (doctrina "None
    es desconocido, no invalido"; jamas falso-rojo por falta de topologia).
    """
    _make_repo_with_origin(tmp_path / "motor")
    _make_repo_with_origin(tmp_path / "destino")
    _commit_sibling(
        tmp_path / "motor",
        "parte MOTOR con hermano roto",
        trailer="Sibling-Commit: deadbeefdeadbeefdeadbeefdeadbeefdeadbeef motor",
    )

    two_roots = pc_module.run_sibling_commit_parity_check(
        tmp_path / "destino", motor_root=tmp_path / "motor"
    )
    assert two_roots.passed is False, (
        f"colgante con 2 raices debe FALLAR: {two_roots.output}"
    )
    assert two_roots.is_blocking is True
    assert "COLGANTE" in two_roots.output

    one_root = pc_module.run_sibling_commit_parity_check(
        tmp_path / "motor", motor_root=tmp_path / "motor"
    )
    assert one_root.passed is True, (
        f"con 1 sola raiz es no-comprobable, no invalido: {one_root.output}"
    )
    assert one_root.skipped is True


def test_sibling_parity_malformed_trailer_fails(tmp_path):
    """Trailer malformado -> ROJO citando la linea: la convencion se audita.

    `Sibling-Commit: nope motor` viola `_SIBLING_SHA_RE`. Un trailer que no
    se puede parsear NO es "sin declaracion": es una declaracion rota, y
    dejarla pasar reabriria justo el hoyo de legibilidad por maquina que el
    ticket cierra.
    """
    _make_repo_with_origin(tmp_path / "motor")
    _make_repo_with_origin(tmp_path / "destino")
    _commit_sibling(
        tmp_path / "motor",
        "parte MOTOR",
        trailer="Sibling-Commit: nope motor",
    )

    result = pc_module.run_sibling_commit_parity_check(
        tmp_path / "destino", motor_root=tmp_path / "motor"
    )

    assert result.passed is False, f"trailer malformado debe FALLAR: {result.output}"
    assert result.is_blocking is True
    assert "MALFORMADO" in result.output


# ----------------------------------------------------------- parser puro (a)
def test_parse_sibling_trailers_forma_de_la_convencion():
    """(a) La convencion `Sibling-Commit: <sha> [motor|destino]` parseada exacto.

    Acepta: sha solo; sha + etiqueta (case-insensitive); indentacion. Rechaza:
    linea sin token, token no-hex, etiqueta desconocida, 3+ tokens. Y una
    mencion en mitad de frase NO es trailer (no empieza la linea).
    """
    ok, bad = pc_module._parse_sibling_trailers(
        "subject\n\nSibling-Commit: abc1234 motor\nSibling-Commit: DEF5678\n"
        "  Sibling-Commit: 1234567 destino\n"
    )
    assert ok == ["abc1234", "DEF5678", "1234567"]
    assert bad == []

    ok, bad = pc_module._parse_sibling_trailers("Sibling-Commit: nope motor\n")
    assert ok == [] and bad == ["Sibling-Commit: nope motor"]

    ok, bad = pc_module._parse_sibling_trailers("Sibling-Commit:\n")
    assert ok == [] and len(bad) == 1

    ok, bad = pc_module._parse_sibling_trailers("Sibling-Commit: abc1234 luna\n")
    assert ok == [] and len(bad) == 1

    ok, bad = pc_module._parse_sibling_trailers("Sibling-Commit: abc1234 motor x\n")
    assert ok == [] and len(bad) == 1

    ok, bad = pc_module._parse_sibling_trailers(
        "ver Sibling-Commit: abc1234 dentro de una frase\n"
    )
    assert ok == [] and bad == []


# ------------------------------------------------------------ barrera cableada
def test_sibling_parity_is_wired_into_closeout(tmp_path, monkeypatch):
    """CABLEADO: `run_preflight_check` invoca el check SOLO en closeout_mode.

    Es la asercion que separa barrera de norma (mismo patron que
    `test_check_is_wired_into_closeout` de WOT-2026-048l). Mutation: retirar
    el `results.append(run_sibling_commit_parity_check(...))` deja el spy sin
    llamar. Tambien fija que el preflight BASE (sin closeout) NO lo paga.
    """
    from prepush_check import CheckResult

    called = {"closeout": 0, "base": 0}

    def _spy(root, *args, **kwargs):
        called["closeout"] += 1
        return CheckResult(name="spy", passed=True, output="", is_blocking=False)

    ok = CheckResult(name="stub", passed=True, output="", is_blocking=True)
    for fn in (
        "run_delivery_hygiene_check",
        "run_portable_memory_archive_check",
        "run_ruff_check",
        "run_ruff_format_check",
        "run_agent_controller_validate",
        "run_git_status_check",
        "run_validate_all",
        "run_backlog_contract_check",
        "run_ghost_ticket_ids_check",
        "run_contract_reconcile_check",
        "run_handoff_state_sha_check",
        "run_handoff_committed_check",
        "run_destination_pii_check",
        "run_closeout_reconciliation_check",
        "run_landed_evidence_shape_check",
        "run_backlog_live_landed_check",
        "run_motor_destination_integration_check",
        "run_contract_formation_check",
        "run_workspace_contract_formation_check",
        "run_batch_run_accounting_check",
        "run_seal_staleness_check",
        "run_distributable_planning_check",
        "run_guard_wiring_orphan_check",
        "run_prompt_wired_invocations_check",
        "run_loop_execution_check",
        "run_principal_freshness_check",
        "run_agent_write_enforced_check",
        "run_flight_plan_collision_check",
        "run_launch_prompt_paths_check",
        "run_builder_prompt_obligations_check",
        "run_arranques_index_check",
        "run_dec_receipt_check",
        "run_dec_receipt_ticket_contracts_check",
        "run_inbox_drainage_check",
        "run_backlog_admission_check",
        "run_sibling_commit_parity_check",
    ):
        monkeypatch.setattr(pc_module, fn, lambda *a, **k: ok)
    monkeypatch.setattr(pc_module, "run_sibling_commit_parity_check", _spy)

    pc_module.run_preflight_check(tmp_path, closeout_mode=True)
    assert called["closeout"] == 1, (
        "el check existe pero el closeout no lo invoca -> es una NORMA, no "
        "una barrera (WOT-2026-056d)"
    )

    monkeypatch.setattr(
        pc_module,
        "run_sibling_commit_parity_check",
        lambda *a, **k: (
            called.__setitem__("base", called["base"] + 1)
            or CheckResult(name="spy", passed=True, output="", is_blocking=False)
        ),
    )
    pc_module.run_preflight_check(tmp_path, closeout_mode=False)
    assert called["base"] == 0, "el preflight base no paga el gate de closeout"


# ============================================================================
# WOT-2026-040o: recibo de auditoria-hermana ANTES del push (barrera, no norma).
#
# DoD binario cubierto:
#   (a) MUTATION 040b: vuelo TERMINADO sin recibo hermana -> FAIL bloqueante
#       (el escape de SECUENCIA: se pusheo/archivo antes de auditarse).
#   (b) MUTATION 040c: recibo verde/fresh-context pero medido contra FIXTURE
#       (topologia que no resuelve) -> FAIL (la autocertificacion).
#   (c) CONTROL NEGATIVO: recibo verde + fresh-context + datos REALES -> PASS.
#   (d) SKIP nombrado cuando no hay vuelo TERMINADO del cierre.
# ============================================================================


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _real_repo_with_head(root: Path) -> tuple[str, str]:
    """Repo git propio y HERMETICO con su HEAD: `(path, full_sha)`.

    Vector git (CEM): tiene su propio `.git`, asi que `git -C root` jamas hace
    walk-up al repo real de la maquina.
    """
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-b", "main")
    (root / "f.txt").write_text("x\n", encoding="utf-8")
    _git(root, "-c", "user.email=f@t", "-c", "user.name=f", "add", "-A")
    _git(root, "-c", "user.email=f@t", "-c", "user.name=f", "commit", "-m", "base")
    return str(root), _git(root, "rev-parse", "HEAD").stdout.strip()


def _write_done_batch_run(reports: Path, name: str, report_json: str | None) -> Path:
    payload: dict = {
        "schema": "batch_run/v1",
        "generated_at": "2026-07-24T00:00:00Z",
        "verdict": "DONE",
    }
    if report_json is not None:
        payload["sibling_audit"] = {"report_json": report_json, "verdict": "APROBADO"}
    path = reports / name
    _write_json(path, payload)
    return path


def _write_audit_receipt(
    reports: Path, name: str, *, verdict: str, topology: dict
) -> Path:
    path = reports / name
    _write_json(
        path,
        {
            "verdict": verdict,
            "isolation": {"b1": "b:fresh-context", "b3_read_only": True},
            "topology": topology,
        },
    )
    return path


def test_sibling_audit_missing_receipt_blocks(tmp_path):
    """(a) 040b: vuelo DONE sin `sibling_audit` -> FAIL bloqueante.

    MUTATION que lo mata: retirar la rama que exige `sibling_audit` -> el
    vuelo atraviesa el cierre sin auditoria (el escape de secuencia medido).
    """
    reports = tmp_path / "orchestrator_pipeline" / "reports"
    reports.mkdir(parents=True)
    _write_done_batch_run(reports, "batch_run_20260724-0000.json", report_json=None)

    result = pc_module.run_sibling_audit_check(tmp_path)

    assert result.passed is False, f"debe FALLAR sin recibo: {result.output}"
    assert result.is_blocking is True, "el gate de auditoria-hermana es BLOQUEANTE"
    assert "sibling_audit" in result.output


def test_sibling_audit_fixture_topology_blocks(tmp_path):
    """(b) 040c: recibo verde/fresh-context pero medido contra FIXTURE -> FAIL.

    El recibo declara fresh-context y APROBADO, pero su `topology` cita un sha
    que NO resuelve en el repo real (un fixture): midio otra cosa. MUTATION que
    lo mata: retirar la verificacion de `topology.repos` -> el fixture pasa.
    """
    reports = tmp_path / "orchestrator_pipeline" / "reports"
    reports.mkdir(parents=True)
    receipt_rel = (
        "orchestrator_pipeline/reports/audit_autonomous_batch_20260724-0100.json"
    )
    _write_done_batch_run(
        reports, "batch_run_20260724-0000.json", report_json=receipt_rel
    )
    # Sha con forma valida (40 hex) pero INEXISTENTE en cualquier repo real.
    _write_audit_receipt(
        reports,
        "audit_autonomous_batch_20260724-0100.json",
        verdict="APROBADO",
        topology={
            "repos": [
                {
                    "role": "motor",
                    "path": str(tmp_path / "repo_inexistente"),
                    "sha": "deadbeef" * 5,
                }
            ]
        },
    )

    result = pc_module.run_sibling_audit_check(tmp_path)

    assert result.passed is False, f"fixture debe FALLAR: {result.output}"
    assert result.is_blocking is True
    assert "REALES" in result.output or "resuelve" in result.output


def test_sibling_audit_valid_receipt_passes(tmp_path):
    """(c) CONTROL NEGATIVO: recibo verde + fresh-context + datos REALES -> PASS.

    `skipped` debe ser False: la barrera corrio y verdicto, no se salto.
    """
    reports = tmp_path / "orchestrator_pipeline" / "reports"
    reports.mkdir(parents=True)
    repo_path, sha = _real_repo_with_head(tmp_path / "realrepo")
    receipt_rel = (
        "orchestrator_pipeline/reports/audit_autonomous_batch_20260724-0100.json"
    )
    _write_done_batch_run(
        reports, "batch_run_20260724-0000.json", report_json=receipt_rel
    )
    _write_audit_receipt(
        reports,
        "audit_autonomous_batch_20260724-0100.json",
        verdict="APROBADO_CON_NITS",
        topology={"repos": [{"role": "motor", "path": repo_path, "sha": sha}]},
    )

    result = pc_module.run_sibling_audit_check(tmp_path)

    assert result.passed is True, f"recibo valido debe PASAR: {result.output}"
    assert result.skipped is False, "debe ser un PASS ejecutado, no un SKIP"


def test_sibling_audit_non_authorizing_verdict_blocks(tmp_path):
    """Un veredicto rojo (`CAMBIOS NECESARIOS`) NO autoriza el push."""
    reports = tmp_path / "orchestrator_pipeline" / "reports"
    reports.mkdir(parents=True)
    repo_path, sha = _real_repo_with_head(tmp_path / "realrepo")
    receipt_rel = (
        "orchestrator_pipeline/reports/audit_autonomous_batch_20260724-0100.json"
    )
    _write_done_batch_run(
        reports, "batch_run_20260724-0000.json", report_json=receipt_rel
    )
    _write_audit_receipt(
        reports,
        "audit_autonomous_batch_20260724-0100.json",
        verdict="CAMBIOS_NECESARIOS",
        topology={"repos": [{"role": "motor", "path": repo_path, "sha": sha}]},
    )

    result = pc_module.run_sibling_audit_check(tmp_path)

    assert result.passed is False
    assert "NO autorizador" in result.output


def test_sibling_audit_no_done_flight_skips(tmp_path):
    """(d) Sin reports dir y sin vuelo TERMINADO -> SKIP nombrado, no dispara."""
    result = pc_module.run_sibling_audit_check(tmp_path)
    assert result.passed is True
    assert result.skipped is True
    assert "SKIP" in result.output

    reports = tmp_path / "orchestrator_pipeline" / "reports"
    reports.mkdir(parents=True)
    _write_json(reports / "batch_run_20260724-0000.json", {"verdict": "RUNNING"})
    result = pc_module.run_sibling_audit_check(tmp_path)
    assert result.passed is True
    assert result.skipped is True


def test_sibling_audit_is_wired_into_closeout(tmp_path, monkeypatch):
    """CABLEADO: `run_preflight_check` invoca el gate SOLO en closeout_mode.

    Mutation: retirar el `results.append(run_sibling_audit_check(...))` deja el
    spy sin llamar (norma, no barrera). Fija ademas que el preflight BASE no lo
    paga.
    """
    from prepush_check import CheckResult

    called = {"closeout": 0, "base": 0}

    def _spy(root, *args, **kwargs):
        called["closeout"] += 1
        return CheckResult(name="spy", passed=True, output="", is_blocking=False)

    ok = CheckResult(name="stub", passed=True, output="", is_blocking=True)
    for fn in (
        "run_delivery_hygiene_check",
        "run_portable_memory_archive_check",
        "run_ruff_check",
        "run_ruff_format_check",
        "run_agent_controller_validate",
        "run_git_status_check",
        "run_validate_all",
        "run_backlog_contract_check",
        "run_ghost_ticket_ids_check",
        "run_contract_reconcile_check",
        "run_handoff_state_sha_check",
        "run_handoff_committed_check",
        "run_destination_pii_check",
        "run_closeout_reconciliation_check",
        "run_landed_evidence_shape_check",
        "run_backlog_live_landed_check",
        "run_motor_destination_integration_check",
        "run_contract_formation_check",
        "run_workspace_contract_formation_check",
        "run_batch_run_accounting_check",
        "run_seal_staleness_check",
        "run_distributable_planning_check",
        "run_guard_wiring_orphan_check",
        "run_prompt_wired_invocations_check",
        "run_loop_execution_check",
        "run_principal_freshness_check",
        "run_agent_write_enforced_check",
        "run_flight_plan_collision_check",
        "run_launch_prompt_paths_check",
        "run_builder_prompt_obligations_check",
        "run_arranques_index_check",
        "run_dec_receipt_check",
        "run_dec_receipt_ticket_contracts_check",
        "run_inbox_drainage_check",
        "run_backlog_admission_check",
        "run_sibling_commit_parity_check",
    ):
        monkeypatch.setattr(pc_module, fn, lambda *a, **k: ok)
    monkeypatch.setattr(pc_module, "run_sibling_audit_check", _spy)

    pc_module.run_preflight_check(tmp_path, closeout_mode=True)
    assert called["closeout"] == 1, (
        "el check existe pero el closeout no lo invoca -> es una NORMA, no "
        "una barrera (WOT-2026-040o)"
    )

    monkeypatch.setattr(
        pc_module,
        "run_sibling_audit_check",
        lambda *a, **k: (
            called.__setitem__("base", called["base"] + 1)
            or CheckResult(name="spy", passed=True, output="", is_blocking=False)
        ),
    )
    pc_module.run_preflight_check(tmp_path, closeout_mode=False)
    assert called["base"] == 0, "el preflight base no paga el gate de closeout"


# ============================================================================
# WOT-2026-070m: --validate --no-heal keeps the preflight read-only --------
#
# The Manager review mutated the premise: the root cause is the OMISION of
# --no-heal in run_agent_controller_validate (prepush_check.py:420-422),
# NOT --force. --force is inert (--no-heal alone controls the heal branch).
#
# DoD binario cubierto:
#   (a) REAL PATH: --no-heal -> STATE.md NOT healed under real bus drift.
#   (b) CONTROL NEGATIVO: sin --no-heal -> STATE.md SI se reescribe (el
#       fixture gunita drift real).
#   (c) CMD: el cmd de run_agent_controller_validate lleva --no-heal.
# ============================================================================


def _make_validate_fixture(root: Path) -> Path:
    """Crea un fixture de proyecto con bus drift para testear --validate.

    States: STATE.md says IN_PROGRESS, events say READY_FOR_REVIEW -> DRIFT.
    """
    collab = root / ".agent" / "collaboration"
    events = root / ".agent" / "runtime" / "events"
    collab.mkdir(parents=True)
    events.mkdir(parents=True)
    (collab / "work_plan.md").write_text(
        "# Plan\n\n- **ID:** WOT-TEST-001\n- **Estado:** IN_PROGRESS\n",
        encoding="utf-8",
    )
    (collab / "execution_log.md").write_text(
        "# Log\n\n- **Estado:** IN_PROGRESS\n", encoding="utf-8"
    )
    state = collab / "STATE.md"
    state.write_text(
        "ACTIVE_TICKET: WOT-TEST-001\nSTATUS: IN_PROGRESS\n",
        encoding="utf-8",
    )
    (events / "events.jsonl").write_text(
        '{"event_type": "STATE_CHANGED", "ticket_id": "WOT-TEST-001", '
        '"payload": {"to_state": "READY_FOR_REVIEW"}}\n',
        encoding="utf-8",
    )
    _git(root, "init", "-q")
    _git(root, "-c", "user.email=f@t", "-c", "user.name=f", "add", "-A")
    _git(root, "-c", "user.email=f@t", "-c", "user.name=f", "commit", "-m", "fixture")
    return root


def test_prepush_validate_passes_no_heal(tmp_path):
    """(a) DoD-1: `run_agent_controller_validate` pasa --no-heal -> STATE.md NO se reescribe.

    REAL PATH: subprocess real al controller (no mock de _run), ejercuta el path
    de sync_state_projection que los tests mockeados de collect_system_health no
    alcanzan -- un mock de _run pasaba VERDE con el defecto vivo.

    MUTACION QUE LO MATA: la mutacion real es (c) — quitar --no-heal del cmd
    en run_agent_controller_validate -> el test_cmd cae (AssertionError:
    --no-heal no esta en captured_cmd). El test (a) declara su propia cmd
    de subproceso y no muerde bajo esa mutacion (permitido por el plan 2.2:
    "la cmd de run_agent_controller_validate, o el subproceso equivalente
    que el test declare").
    """
    import subprocess

    controller = Path(__file__).resolve().parents[2] / ".agent" / "agent_controller.py"
    fx = tmp_path / "fx"
    _make_validate_fixture(fx)

    original_state = (fx / ".agent" / "collaboration" / "STATE.md").read_text(
        encoding="utf-8"
    )

    subprocess.run(
        [
            sys.executable,
            str(controller),
            "--validate",
            "--json",
            "--force",
            "--no-heal",
            "--project-root",
            str(fx),
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )

    assert (fx / ".agent" / "collaboration" / "STATE.md").read_text(
        encoding="utf-8"
    ) == original_state, (
        "STATE.md fue reescrito bajo --no-heal (contrato read-only violado)"
    )


def test_prepush_validate_does_not_rewrite_terminal_state_md(tmp_path):
    """(b) CONTROL NEGATIVO: sin --no-heal, el fixture drift -> STATE.md SI se reescribe.

    Sanity: demuestra que el fixture gunita drift real y el path de heal se
    dispara sin el flag — la asercion de arriba es significativa, no vacua.
    """
    import subprocess

    controller = Path(__file__).resolve().parents[2] / ".agent" / "agent_controller.py"
    fx = tmp_path / "fx"
    _make_validate_fixture(fx)

    original_state = (fx / ".agent" / "collaboration" / "STATE.md").read_text(
        encoding="utf-8"
    )

    subprocess.run(
        [
            sys.executable,
            str(controller),
            "--validate",
            "--json",
            "--force",
            "--project-root",
            str(fx),
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )

    healed = (fx / ".agent" / "collaboration" / "STATE.md").read_text(encoding="utf-8")
    assert healed != original_state and "READY_FOR_REVIEW" in healed, (
        "fixture no drift/heal sin --no-heal; la prueba de --no-heal seria vacua"
    )


def test_prepush_validate_cmd_contains_no_heal(tmp_path, monkeypatch):
    """(c) CMD: el cmd de run_agent_controller_validate lleva --no-heal.

    MUTACION: quitar --no-heal del cmd -> este test cae (AssertionError).
    Este es el unico test que muerde la mutacion de retirar --no-heal del
    codigo real (el test (a) declara su propia cmd de subproceso).
    """
    from prepush_check import CheckResult

    captured_cmd: list[str] = []

    def _spy(cmd, name, project_root, capture_output=True):  # type: ignore[no-untyped-def]
        captured_cmd.extend(cmd)
        return CheckResult(name=name, passed=True, output="", is_blocking=True)

    monkeypatch.setattr(pc_module, "run_subprocess_check", _spy)
    run_agent_controller_validate(tmp_path)

    assert "--no-heal" in captured_cmd, (
        f"--no-heal debe estar en el cmd, salio: {captured_cmd}"
    )
    assert "--validate" in captured_cmd
    assert "--force" in captured_cmd
