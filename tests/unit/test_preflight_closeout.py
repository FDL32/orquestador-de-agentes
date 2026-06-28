# WOT-2026-016a: tests del pre-flight agregado de cierre.
#
# HERMETICOS (el propio AP-D05 en accion): ningun test lee el
# .agent/collaboration/ del workspace vivo ni el .agent/runtime real del repo.
# Cada test construye su propio tmp_path (work_plan + repos git) o monkeypatchea
# los seams reales de pre_handoff_guard.
#
# Dos capas:
#  1. Orquestacion: monkeypatch de las funciones REALES que el script llama
#     (run_guard, assert_canonical_suite_green, resolve_delivery_root, los
#     lectores del plan). Prueba que el script AGREGA, no reimplementa, y que
#     resuelve el delivery_root correcto. Mock apuntado a la API real (sin
#     mock-drift): el script invoca exactamente esos atributos del modulo.
#  2. Integracion: ejecuta run_preflight contra un tmp git repo real (sin
#     mocks de git) para evitar floor-assertion: prueba el cableado end-to-end.

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


# scripts/ no es paquete: insertarlo en sys.path como hace el propio script.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import pre_handoff_guard  # noqa: E402
import preflight_closeout  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers hermeticos
# ---------------------------------------------------------------------------


def _init_git_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "README.md").write_text("# Test Repo", encoding="utf-8")
    # Igual que los repos reales: el runtime es gitignored, asi que escribir
    # last-run.json no debe ensuciar el arbol. Sin esto, el dirty_tree real
    # enmascararia el check que el test aisla.
    (repo / ".gitignore").write_text(".agent/runtime/\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True
    )


def _git_out(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def _write_work_plan(
    project_root: Path, ticket_id: str, *, authority: str, dtype: str = "mixed"
) -> Path:
    collab = project_root / ".agent" / "collaboration"
    collab.mkdir(parents=True, exist_ok=True)
    wp = collab / "work_plan.md"
    wp.write_text(
        "# Work Plan\n\n"
        "## Metadata\n"
        f"- **ID:** {ticket_id}\n"
        f"- **deliverable_type:** {dtype}\n"
        f"- **delivery_authority:** {authority}\n"
        "- **Estado:** APPROVED\n",
        encoding="utf-8",
    )
    return wp


def _write_fresh_green_last_run(delivery_root: Path) -> None:
    """Escribir un last-run.json fresh-green para el HEAD del delivery_root."""
    import json

    head = _git_out(["rev-parse", "HEAD"], delivery_root)
    runtime = delivery_root / ".agent" / "runtime" / "pytest-safe"
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "last-run.json").write_text(
        json.dumps(
            {
                "status": "finished",
                "exit_code": 0,
                "tested_commit_sha": head,
                "level": "all",
                "args_mode": "default_discovery",
            }
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Capa 1 - ORQUESTACION (monkeypatch de seams reales)
# ---------------------------------------------------------------------------


def _patch_clean_guard(monkeypatch, *, dirty=False, missing_ckpt=False):
    """Stub de run_guard que devuelve un dict con los keys que el script lee."""
    calls = {}

    def fake_run_guard(project_root, ticket_id, motor_root=None):
        calls["run_guard_root"] = project_root
        calls["run_guard_ticket"] = ticket_id
        return {
            "valid": not (dirty or missing_ckpt),
            "dirty_tree": dirty,
            "missing_checkpoint": missing_ckpt,
            "checkpoint_misaligned": False,
            "dirty_files": ["scripts/x.py"] if dirty else [],
        }

    monkeypatch.setattr(pre_handoff_guard, "run_guard", fake_run_guard)
    return calls


def _patch_green_suite(monkeypatch, *, ok=True, reason="fresh_green"):
    calls = {}

    def fake_suite(motor_root, deliverable_type):
        calls["suite_root"] = motor_root
        if ok:
            return True, {"canonical_suite_required": True, "reason": reason}
        return False, {
            "canonical_suite_required": True,
            "reason": reason,
            "canonical_suite_error": "boom",
            "remediation": "python scripts/run_pytest_safe.py --level all",
        }

    monkeypatch.setattr(pre_handoff_guard, "assert_canonical_suite_green", fake_suite)
    return calls


def test_all_pass(monkeypatch, tmp_path):
    """Arbol limpio + checkpoint presente + suite green -> all_pass, exit 0."""
    _write_work_plan(tmp_path, "WOT-2026-016a", authority="repo_motor")
    _patch_clean_guard(monkeypatch)
    _patch_green_suite(monkeypatch)

    motor = tmp_path / "motor"
    motor.mkdir()
    report = preflight_closeout.run_preflight(
        project_root=tmp_path, ticket_id="WOT-2026-016a", motor_root=motor
    )

    assert report["all_pass"] is True
    assert all(c["pass"] for c in report["checks"].values())
    # exit 0 via main()
    rc = preflight_closeout.main(
        [
            "--project-root",
            str(tmp_path),
            "--ticket-id",
            "WOT-2026-016a",
            "--motor-root",
            str(motor),
        ]
    )
    assert rc == 0


def test_dirty_tree_fails(monkeypatch, tmp_path):
    """run_guard reporta dirty_tree -> check dirty_tree FALLA, all_pass False."""
    _write_work_plan(tmp_path, "WOT-2026-016a", authority="repo_motor")
    _patch_clean_guard(monkeypatch, dirty=True)
    _patch_green_suite(monkeypatch)
    motor = tmp_path / "motor"
    motor.mkdir()

    report = preflight_closeout.run_preflight(
        project_root=tmp_path, ticket_id="WOT-2026-016a", motor_root=motor
    )
    assert report["checks"]["dirty_tree"]["pass"] is False
    assert "scripts/x.py" in report["checks"]["dirty_tree"]["detail"]
    assert report["all_pass"] is False


def test_missing_checkpoint_fix_cites_delivery_root(monkeypatch, tmp_path):
    """checkpoint_m3 FALLA y su fix cita --project-root <delivery_root> (motor).

    Este es el check NUEVO: con authority=repo_motor el comando de fix debe
    apuntar al MOTOR, no al destino (el gap real de la sesion).
    """
    _write_work_plan(tmp_path, "WOT-2026-016a", authority="repo_motor")
    _patch_clean_guard(monkeypatch, missing_ckpt=True)
    _patch_green_suite(monkeypatch)
    motor = tmp_path / "motor"
    motor.mkdir()

    report = preflight_closeout.run_preflight(
        project_root=tmp_path, ticket_id="WOT-2026-016a", motor_root=motor
    )
    ckpt = report["checks"]["checkpoint_m3"]
    assert ckpt["pass"] is False
    assert "create_checkpoint.py" in ckpt["fix"]
    assert "--milestone M3" in ckpt["fix"]
    # El fix cita el MOTOR como --project-root, y termina exactamente ahi
    # (no en el destino). El delivery_root es el motor (authority=repo_motor).
    assert ckpt["fix"].endswith(f"--project-root {motor}")
    assert report["delivery_root"] == str(motor)
    assert report["all_pass"] is False


def test_stale_suite_fails(monkeypatch, tmp_path):
    """assert_canonical_suite_green reporta stale_run -> canonical_suite FALLA."""
    _write_work_plan(tmp_path, "WOT-2026-016a", authority="repo_motor")
    _patch_clean_guard(monkeypatch)
    _patch_green_suite(monkeypatch, ok=False, reason="stale_run")
    motor = tmp_path / "motor"
    motor.mkdir()

    report = preflight_closeout.run_preflight(
        project_root=tmp_path, ticket_id="WOT-2026-016a", motor_root=motor
    )
    suite = report["checks"]["canonical_suite"]
    assert suite["pass"] is False
    assert "stale_run" in suite["detail"]
    assert "run_pytest_safe" in suite["fix"]
    assert report["all_pass"] is False


def test_delivery_root_resolution_motor_vs_destino(monkeypatch, tmp_path):
    """delivery_root = motor cuando authority=repo_motor; = destino si repo_destino.

    Verifica que el script PASA el delivery_root correcto a run_guard y a
    assert_canonical_suite_green (prueba de orquestacion, no de duplicacion).
    """
    motor = tmp_path / "motor"
    motor.mkdir()

    # Caso repo_motor: ambas funciones reciben el MOTOR.
    dest_a = tmp_path / "dest_a"
    _write_work_plan(dest_a, "WOT-2026-016a", authority="repo_motor")
    guard_calls = _patch_clean_guard(monkeypatch)
    suite_calls = _patch_green_suite(monkeypatch)
    report = preflight_closeout.run_preflight(
        project_root=dest_a, ticket_id="WOT-2026-016a", motor_root=motor
    )
    assert report["delivery_authority"] == "repo_motor"
    assert report["delivery_root"] == str(motor)
    assert guard_calls["run_guard_root"] == motor
    assert suite_calls["suite_root"] == motor

    # Caso repo_destino: ambas funciones reciben el DESTINO (project_root).
    dest_b = tmp_path / "dest_b"
    _write_work_plan(dest_b, "WOT-2026-016a", authority="repo_destino")
    guard_calls = _patch_clean_guard(monkeypatch)
    suite_calls = _patch_green_suite(monkeypatch)
    report = preflight_closeout.run_preflight(
        project_root=dest_b, ticket_id="WOT-2026-016a", motor_root=motor
    )
    assert report["delivery_authority"] == "repo_destino"
    assert report["delivery_root"] == str(dest_b)
    assert guard_calls["run_guard_root"] == dest_b
    assert suite_calls["suite_root"] == dest_b


def test_ci_local_warning_always_present(monkeypatch, tmp_path):
    """La advertencia CI/local (AP-D05) esta en el reporte aunque all_pass."""
    _write_work_plan(tmp_path, "WOT-2026-016a", authority="repo_motor")
    _patch_clean_guard(monkeypatch)
    _patch_green_suite(monkeypatch)
    motor = tmp_path / "motor"
    motor.mkdir()
    report = preflight_closeout.run_preflight(
        project_root=tmp_path, ticket_id="WOT-2026-016a", motor_root=motor
    )
    assert "AP-D05" in report["ci_local_warning"]


def test_orchestrates_does_not_reimplement(monkeypatch, tmp_path):
    """Si run_guard del modulo importado es reemplazado, el reporte cambia.

    Prueba mecanica de que el script DELEGA en pre_handoff_guard.run_guard (no
    tiene su propia copia de la logica): un stub que devuelve missing_checkpoint
    debe hacer FALLAR checkpoint_m3. Si el script reimplementara el check,
    ignoraria el stub y el test fallaria.
    """
    _write_work_plan(tmp_path, "WOT-2026-016a", authority="repo_motor")
    _patch_clean_guard(monkeypatch, missing_ckpt=True)
    _patch_green_suite(monkeypatch)
    motor = tmp_path / "motor"
    motor.mkdir()
    report = preflight_closeout.run_preflight(
        project_root=tmp_path, ticket_id="WOT-2026-016a", motor_root=motor
    )
    assert report["checks"]["checkpoint_m3"]["pass"] is False


# ---------------------------------------------------------------------------
# Capa 2 - INTEGRACION (run_guard real contra tmp git repo, sin mocks de git)
# ---------------------------------------------------------------------------


def test_integration_missing_checkpoint_real_git(tmp_path):
    """End-to-end real: motor git sin tag M3 -> checkpoint_m3 FALLA, exit 1.

    No mockea nada: ejercita el run_guard real (que corre git) sobre repos
    tmp_path propios. Prueba el cableado real y evita floor-assertion. La suite
    se neutraliza con deliverable_type=documentation (skip auditable), de modo
    que el unico fallo observado sea el checkpoint, aislado.
    """
    motor = tmp_path / "motor"
    dest = tmp_path / "dest"
    _init_git_repo(motor)
    _init_git_repo(dest)
    # Plan documentation => assert_canonical_suite_green hace skip auditable.
    _write_work_plan(
        dest, "WOT-2026-016a", authority="repo_motor", dtype="documentation"
    )

    report = preflight_closeout.run_preflight(
        project_root=dest, ticket_id="WOT-2026-016a", motor_root=motor
    )
    # El motor no tiene checkpoint/review-WOT-2026-016a => FALLA.
    assert report["checks"]["checkpoint_m3"]["pass"] is False
    assert report["delivery_root"] == str(motor)
    # La suite documentation hace skip => no bloquea por suite.
    assert report["checks"]["canonical_suite"]["pass"] is True
    assert report["all_pass"] is False


def test_integration_all_pass_real_git(tmp_path):
    """End-to-end real green: tag M3 alineado + last-run fresh-green -> exit 0.

    deliverable_type=code para EJERCITAR la rama de suite real (no skip):
    escribimos un last-run.json valido para el HEAD del motor.
    """
    motor = tmp_path / "motor"
    dest = tmp_path / "dest"
    _init_git_repo(motor)
    _init_git_repo(dest)
    _write_work_plan(dest, "WOT-2026-016a", authority="repo_motor", dtype="code")

    # Crear el checkpoint M3 real en el MOTOR (delivery_root) alineado con HEAD.
    head = _git_out(["rev-parse", "HEAD"], motor)
    subprocess.run(
        ["git", "tag", "checkpoint/review-WOT-2026-016a", head],
        cwd=motor,
        check=True,
        capture_output=True,
    )
    _write_fresh_green_last_run(motor)

    rc = preflight_closeout.main(
        [
            "--project-root",
            str(dest),
            "--ticket-id",
            "WOT-2026-016a",
            "--motor-root",
            str(motor),
            "--json",
        ]
    )
    assert rc == 0


def test_main_fail_closed_on_error(tmp_path):
    """Si no hay work_plan ni motor, el script NO crashea: fail-closed exit 1.

    Hermetico: tmp_path vacio, sin .agent. Las lecturas del plan caen a default,
    run_guard real corre git en un dir sin repo -> el reporte agrega FAIL sin
    excepcion no controlada, o main captura y devuelve 1.
    """
    empty = tmp_path / "empty"
    empty.mkdir()
    rc = preflight_closeout.main(
        [
            "--project-root",
            str(empty),
            "--ticket-id",
            "WOT-2026-016a",
        ]
    )
    assert rc == 1


def test_no_dependency_on_live_workspace(tmp_path, monkeypatch):
    """Prueba de hermeticidad explicita (B6): mover el cwd a tmp no afecta.

    El reporte se construye solo desde los argumentos, no desde el
    .agent/collaboration/ del repo vivo. Cambiamos el cwd a un tmp vacio y el
    resultado debe ser identico al de pasar las mismas rutas.
    """
    monkeypatch.chdir(tmp_path)
    _write_work_plan(tmp_path, "WOT-2026-016a", authority="repo_destino")
    _patch_clean_guard(monkeypatch)
    _patch_green_suite(monkeypatch)
    report = preflight_closeout.run_preflight(
        project_root=tmp_path, ticket_id="WOT-2026-016a", motor_root=None
    )
    # authority repo_destino + motor None -> delivery_root = project_root.
    assert report["delivery_root"] == str(tmp_path)
    assert report["all_pass"] is True
