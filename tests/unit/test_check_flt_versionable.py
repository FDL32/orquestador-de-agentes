"""WOT-2026-069a: tests del gate de versionabilidad del FLT.

El gate (``scripts/check_flt_versionable.py``) mide cada ruta del
``Files Likely Touched`` del plan activo con ``git check-ignore`` corriendo
EN el repo que resuelve ``delivery_authority``. Estos tests ejercitan:

- MUTATION en ambas direcciones (D4): ruta ignorada -> FAIL nombrando la
  regla ``.gitignore:<linea>:<patron>`` y el repo medido; ruta versionable
  -> silencio verde (sin errores).
- CONTROL DE RAIZ (D4): DOS repos git DISTINTOS en el fixture. Un fixture
  de un solo repo es ciego a que se lea la raiz equivocada; aqui la MISMA
  ruta relativa cambia de veredicto segun el repo de entrega.
- SKIP nombrado (D3): plan terminal, plan ausente, seed-neutral y plan sin
  seccion FLT nunca son verde mudo; publican su motivo.
- ROJO (D3): ``inspeccionadas == 0`` sin motivo declarado (seccion FLT
  presente pero 0 rutas resolubles) y fallo de medicion git (fail-closed).
- DENOMINADOR (D1): ``rutas / inspeccionadas / ignoradas / saltadas`` +
  lista de saltadas con motivo.

La medicion es git real contra repos ``git init`` temporales (mismo patron
que ``tests/unit/test_gitignore_wot_artifacts.py``): ``git check-ignore`` es
la MEDIDA, no una heuristica que un stub podria falsificar.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.check_flt_versionable import (  # noqa: E402
    flt_paths_not_versionable,
    format_summary,
    gate_errors,
)


def _git_init(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-q"],
        cwd=path,
        check=True,
        capture_output=True,
    )


@pytest.fixture()
def two_repos(tmp_path: Path) -> tuple[Path, Path]:
    """Dos repos git DISTINTOS: motor (ignora ``reports/*``) y destino.

    Un fixture de un solo repo no puede detectar que se mida la raiz
    equivocada: con dos repos, la MISMA ruta relativa cambia de veredicto
    segun el repo de entrega, y el test lo verifica en ambas direcciones.
    """
    motor = tmp_path / "motor_repo"
    destino = tmp_path / "destino_repo"
    _git_init(motor)
    _git_init(destino)
    (motor / ".gitignore").write_text("reports/*\n", encoding="utf-8")
    return motor, destino


def _plan(
    flt_body: str,
    *,
    estado: str = "APPROVED",
    authority: str = "repo_motor",
    ticket: str = "WOT-2026-069a",
) -> str:
    """Plan minimo parseable por el extractor FLT y los lectores de metadata."""
    return (
        "# Plan\n\n## Metadata\n"
        f"- **ID:** {ticket}\n"
        f"- **Estado:** {estado}\n"
        "- **deliverable_type:** code\n"
        f"- **delivery_authority:** {authority}\n\n"
        f"## Files Likely Touched\n\n{flt_body}"
    )


class TestMutationDirections:
    """D4: el gate FALLA nombrando la regla, o queda en silencio verde."""

    def test_ignored_route_fails_naming_rule_and_repo(self, two_repos):
        motor, destino = two_repos
        plan = _plan("- reports/informe.md")
        result = flt_paths_not_versionable(plan, motor_root=motor, project_root=destino)
        assert result["status"] == "FAIL"
        assert result["ignoradas"] == 1
        violation = result["violaciones"][0]
        assert violation["ruta"] == "reports/informe.md"
        assert violation["repo"] == str(motor)
        assert violation["repo_role"] == "repo_motor"
        assert violation["regla"] == ".gitignore:1:reports/*"
        errors = gate_errors(result)
        assert errors, "un FAIL debe renderizar al menos un error"
        assert ".gitignore:1:reports/*" in errors[0]
        assert str(motor) in errors[0]

    def test_versionable_route_is_silent_green(self, two_repos):
        motor, destino = two_repos
        plan = _plan("- scripts/ok.py")
        result = flt_paths_not_versionable(plan, motor_root=motor, project_root=destino)
        assert result["status"] == "OK"
        assert (
            result["rutas"],
            result["inspeccionadas"],
            result["ignoradas"],
            result["saltadas"],
        ) == (1, 1, 0, 0)
        assert result["violaciones"] == []
        assert gate_errors(result) == []


class TestRootControl:
    """D4: DOS repos distintos; el repo medido es el que resuelve la ruta."""

    def test_same_route_is_green_when_authority_is_destino(self, two_repos):
        """La ruta que el motor IGNORA es versionable cuando el FLT resuelve
        contra el destino: la medida corre en el repo correcto, no en motor."""
        motor, destino = two_repos
        plan = _plan("- reports/informe.md", authority="repo_destino")
        result = flt_paths_not_versionable(plan, motor_root=motor, project_root=destino)
        assert result["status"] == "OK"
        assert result["inspeccionadas"] == 1
        assert result["repo_destino"] == str(destino)
        assert result["violaciones"] == []

    def test_namespaced_destino_route_fails_naming_destino(self, two_repos):
        """Subheading ``### repo_destino`` manda sobre delivery_authority:
        la ruta se mide en el repo DESTINO y el FAIL lo nombra."""
        motor, destino = two_repos
        (destino / ".gitignore").write_text("reports/*\n", encoding="utf-8")
        plan = _plan("### repo_destino\n\n- reports/informe.md\n")
        result = flt_paths_not_versionable(plan, motor_root=motor, project_root=destino)
        assert result["status"] == "FAIL"
        violation = result["violaciones"][0]
        assert violation["repo"] == str(destino)
        assert violation["repo_role"] == "repo_destino"
        assert violation["regla"] == ".gitignore:1:reports/*"


class TestSkipNamed:
    """D3: SKIP nombrado (no verde mudo) para planes fuera del universo."""

    def test_terminal_plan_skips_named_without_measuring(self, two_repos):
        motor, destino = two_repos
        plan = _plan("- reports/informe.md", estado="COMPLETED")
        result = flt_paths_not_versionable(plan, motor_root=motor, project_root=destino)
        assert result["status"] == "SKIP"
        assert result["reason"] and "terminal" in result["reason"]
        assert result["rutas"] == 0
        assert result["violaciones"] == []
        assert gate_errors(result) == []

    def test_empty_plan_skips_named(self, two_repos):
        motor, destino = two_repos
        result = flt_paths_not_versionable("", motor_root=motor, project_root=destino)
        assert result["status"] == "SKIP"
        assert result["reason"] and "sin plan activo" in result["reason"]

    def test_seed_neutral_plan_skips_named(self, two_repos):
        motor, destino = two_repos
        plan = "# Plan\n\n## Metadata\n- **ID:** none\n- **Estado:** READY_TO_START\n"
        result = flt_paths_not_versionable(plan, motor_root=motor, project_root=destino)
        assert result["status"] == "SKIP"
        assert result["reason"] and "seed" in result["reason"]

    def test_missing_flt_section_skips_named(self, two_repos):
        """Un plan no terminal SIN seccion FLT declara 0 rutas por si mismo:
        motivo declarado -> SKIP nombrado, no ROJO."""
        motor, destino = two_repos
        plan = (
            "# Plan\n\n## Metadata\n- **ID:** WOT-2026-001a\n- **Estado:** APPROVED\n"
        )
        result = flt_paths_not_versionable(plan, motor_root=motor, project_root=destino)
        assert result["status"] == "SKIP"
        assert result["reason"] and "Files Likely Touched" in result["reason"]


class TestRedCases:
    """D3: inspeccionadas == 0 sin motivo declarado -> ROJO, nunca verde mudo."""

    def test_flt_section_without_parseable_routes_is_red(self, two_repos):
        motor, destino = two_repos
        plan = _plan("- ver notas de la sesion para el detalle")
        result = flt_paths_not_versionable(plan, motor_root=motor, project_root=destino)
        assert result["status"] == "FAIL"
        assert result["reason"] and "inspeccionadas == 0" in result["reason"]
        assert gate_errors(result), "el ROJO debe renderizar error"

    def test_git_measurement_failure_is_fail_closed(self, two_repos):
        """Un git roto (rc>=2) es ROJO: no medir no puede ser un verde."""

        def broken_runner(repo_root: Path, rel_routes: list[str]):
            return subprocess.CompletedProcess(
                args=[], returncode=128, stdout="", stderr="fatal: not a git repository"
            )

        motor, destino = two_repos
        plan = _plan("- scripts/ok.py")
        result = flt_paths_not_versionable(
            plan,
            motor_root=motor,
            project_root=destino,
            check_ignore=broken_runner,
        )
        assert result["status"] == "FAIL"
        assert result["reason"] and "no se pudo medir" in result["reason"]
        assert result["inspeccionadas"] == 0
        assert gate_errors(result)


class TestDenominator:
    """D1: el gate publica su denominador y la lista de saltadas."""

    def test_denominator_published_mixed_routes(self, two_repos):
        motor, destino = two_repos
        plan = _plan("- reports/informe.md\n- scripts/ok.py")
        result = flt_paths_not_versionable(plan, motor_root=motor, project_root=destino)
        assert result["rutas"] == 2
        assert result["inspeccionadas"] == 2
        assert result["ignoradas"] == 1
        assert result["saltadas"] == 0
        assert len(result["violaciones"]) == 1

    def test_route_outside_both_repos_is_skipped_with_motive(self, two_repos, tmp_path):
        motor, destino = two_repos
        outside = tmp_path / "afuera"
        outside.mkdir()
        plan = _plan(f"- {(outside / 'x.md').as_posix()}")
        result = flt_paths_not_versionable(plan, motor_root=motor, project_root=destino)
        assert result["status"] == "SKIP"
        assert result["saltadas"] == 1
        assert result["inspeccionadas"] == 0
        assert result["saltadas_detalle"], "la lista de saltadas debe venir NOMBRADA"
        assert "fuera de los dos repos" in result["saltadas_detalle"][0]["motivo"]

    def test_format_summary_publishes_denominator(self, two_repos):
        motor, destino = two_repos
        plan = _plan("- reports/informe.md")
        result = flt_paths_not_versionable(plan, motor_root=motor, project_root=destino)
        summary = format_summary(result)
        assert "rutas=1" in summary
        assert "inspeccionadas=1" in summary
        assert "ignoradas=1" in summary
        assert "saltadas=0" in summary
