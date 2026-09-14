"""WOT-2026-069e: los CUATRO lectores naive de `delivery_authority` deben
resolver SOLO desde la seccion `## Metadata`, via un unico modulo compartido
(`scripts/work_plan_authority.py`) que reutiliza el resolvedor canonico de
`scope_gate`.

Contrato: `T-069E-001`, DoD D2 (fixtures del plan real) y D3 (motivo
nombrado cuando el campo falta). El defecto medido: una prosa que contenga el literal
`delivery_authority: repo_destino` anula el campo de Metadata en
`pre_handoff_guard`, `run_pytest_safe`, `delivery_hygiene_check` y
`collect_system_health` (cuatro copias del mismo regex naive; bloque el
cierre de `WOT-2026-069a` tras commiteado -- `CG-WOT-2026-069a.md`).

Los tests importan cada lector por su ruta real de produccion (spec por
fichero, mismo patron que `tests/test_collect_system_health_readonly.py`) y
ejercitan la conducta desde el CONTENIDO del work_plan, no desde el regex.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _ROOT / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    if spec is None or spec.loader is None:
        raise ImportError(f"modulo no cargable: {name}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_pg = _load("pre_handoff_guard")
_rps = _load("run_pytest_safe")
_dhc = _load("delivery_hygiene_check")
_csh = _load("collect_system_health")

TRAP = (
    "y el lector naive deberia ver esto: delivery_authority: repo_destino en la prosa."
)


def _plan(
    authority: str | None = "repo_motor",
    *,
    prose: str = "",
    prelude: str = "",
    section: bool = True,
) -> str:
    metadata_block = "## Metadata\n- **ID:** WOT-2026-TEST\n- **Estado:** APPROVED\n"
    if authority is not None:
        metadata_block += f"- **delivery_authority:** {authority}\n"
    body = "# Plan de Prueba\n\n"
    if prelude:
        body += f"## Contexto previo\n{prelude}\n\n"
    if section:
        body += metadata_block + "\n"
    if prose:
        body += f"## Contexto\n{prose}\n"
    return body


def _write_plan(tmp: Path, content: str) -> Path:
    wp = tmp / ".agent" / "collaboration"
    wp.mkdir(parents=True)
    (wp / "work_plan.md").write_text(content, encoding="utf-8")
    return tmp


def _read_pg(content: str, tmp: Path) -> str:
    return _pg._read_delivery_authority_from_content(content)


def _read_rps(content: str, tmp: Path) -> str:
    _write_plan(tmp, content)
    old = _rps._PROJECT_ROOT
    _rps._PROJECT_ROOT = tmp
    try:
        return _rps._delivery_authority()
    finally:
        _rps._PROJECT_ROOT = old


def _read_dhc(content: str, tmp: Path) -> str:
    _write_plan(tmp, content)
    return _dhc._read_delivery_authority(tmp)


def _read_csh(content: str, tmp: Path) -> str:
    _write_plan(tmp, content)
    return _csh._read_delivery_authority(tmp)


READERS = pytest.mark.parametrize(
    "reader",
    [_read_pg, _read_rps, _read_dhc, _read_csh],
    ids=["pre_handoff_guard", "run_pytest_safe", "delivery_hygiene", "collect_health"],
)


@READERS
def test_metadata_repo_motor_manda_sobre_prosa_posterior(reader, tmp_path):
    """D2(i): Metadata repo_motor + literal repo_destino en prosa -> repo_motor."""
    content = _plan("repo_motor", prose=TRAP)
    assert reader(content, tmp_path) == "repo_motor"


@READERS
def test_metadata_repo_destino_mantiene_eficacia(reader, tmp_path):
    """D2(ii): control anti-sobre-correccion -- Metadata repo_destino gana."""
    content = _plan("repo_destino", prose=TRAP)
    assert reader(content, tmp_path) == "repo_destino"


@READERS
def test_prosa_anterior_a_metadata_no_decide(reader, tmp_path):
    """D2(iv): el literal aparece ANTES de `## Metadata` (agujero del primer-match del canonico)."""
    content = _plan("repo_motor", prose=TRAP, prelude=TRAP)
    assert reader(content, tmp_path) == "repo_motor"


@READERS
def test_sin_campo_en_metadata_resuelve_default(reader, tmp_path):
    """D2(c) del DoD: sin campo, default repo_motor NO importa la prosa."""
    content = _plan(None, prose=TRAP)
    assert reader(content, tmp_path) == "repo_motor"


def test_work_plan_authority_expone_valor_y_motivo_presente(tmp_path):
    """D3: Metadata presente -> (valor, `metadata_field`) via modulo compartido."""
    _wpa = _load("work_plan_authority")
    assert _wpa.resolve_delivery_authority_from_content(
        _plan("repo_motor", prose=TRAP)
    ) == (
        "repo_motor",
        "metadata_field",
    )


def test_work_plan_authority_motivo_nombrado_cuando_falta_campo():
    """D3: campo ausente -> default repo_motor con motivo nombrado, no silencioso."""
    _wpa = _load("work_plan_authority")
    value, reason = _wpa.resolve_delivery_authority_from_content(
        _plan(None, prose=TRAP)
    )
    assert value == "repo_motor"
    assert reason == "no_field_in_metadata"


def test_work_plan_authority_motivo_nombrado_sin_seccion_metadata():
    """D3: plan sin seccion Metadata -> default con motivo nombrado."""
    _wpa = _load("work_plan_authority")
    value, reason = _wpa.resolve_delivery_authority_from_content(
        "# Plan sin metadata\n\ntexto\n"
    )
    assert value == "repo_motor"
    assert reason == "no_metadata_section"
