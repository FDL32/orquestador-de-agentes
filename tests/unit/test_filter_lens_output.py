"""Tests del filtro de RUIDO sobre la salida de una lente (WOT-2026-027o).

Fija los dos huecos MEDIDOS sobre revisiones REALES de la sesion anterior:
  - FABRICACION: reviews que citan ficheros/commits/variables inexistentes.
  - ANCLAJE: cita REAL + veredicto de CONFIRMACION -> no es aportacion.

El caso de ANCLAJE es el que ningun filtro de "exige fichero:linea" detecta,
porque el puntero SI resuelve. Por eso los dos mecanismos son independientes y
la mutation (DoD (d)) los ataca por separado.

Hermetico: todo corre contra `tmp_path`, sin red y sin tocar el arbol.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


_MOTOR_ROOT = Path(__file__).resolve().parents[2]


def _load_filter():
    path = _MOTOR_ROOT / "scripts" / "filter_lens_output.py"
    spec = importlib.util.spec_from_file_location("filter_lens_output", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["filter_lens_output"] = module
    spec.loader.exec_module(module)
    return module


flo = _load_filter()


def _receipt(path: str, *, verdict: str) -> str:
    """Salida de lente con bloque ```receipt (el schema que valida el reuso)."""
    return (
        f"{verdict}\n\n"
        "```receipt\n"
        "command: python -m pytest tests/unit/test_x.py\n"
        "exit_code: 0\n"
        f"path: {path}\n"
        "```\n"
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Arbol minimo con UN fichero real que las lentes pueden citar."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "real_module.py").write_text("x = 1\n", encoding="utf-8")
    return tmp_path


def test_027o_dod_a_fabricated_citation_is_discarded(repo: Path):
    """DoD (a): cita FABRICADA -> descartada, con reason y exit code.

    Reproduce la fabricacion MEDIDA: la lente cito `tests/test_transport.py`,
    un fichero que no existe en el arbol que decia revisar.
    """
    text = _receipt("tests/test_transport.py", verdict="El transporte falla porque X.")
    accepted, reason, problems = flo.filter_lens_output(text, repo)

    assert accepted is False
    assert reason == "fabricated_citation"
    assert any("does not resolve" in p for p in problems), problems


def test_027o_dod_a_citation_escaping_root_is_discarded(repo: Path):
    """DoD (a): una cita que ESCAPA del root tampoco vale.

    Sin esto, `../../otro_repo/fichero.py` podria existir en la maquina y dar
    un falso verde de wrong-root.
    """
    text = _receipt("../fuera_del_repo.py", verdict="Hay un bug real aqui.")
    accepted, reason, _ = flo.filter_lens_output(text, repo)

    assert accepted is False
    assert reason == "fabricated_citation"


def test_027o_dod_b_real_citation_but_confirmation_is_not_a_contribution(repo: Path):
    """DoD (b): cita REAL + veredicto de CONFIRMACION -> no-aportacion.

    Este es el caso de ANCLAJE medido: qwen y gemma citaron la linea CORRECTA
    y aun asi abrieron con "Confirmado". El puntero resuelve, asi que la
    verificacion de cita (mecanismo 1) lo deja pasar: lo caza la clasificacion
    de forma (mecanismo 2).
    """
    text = _receipt(
        "scripts/real_module.py", verdict="Confirmado, la premisa es correcta."
    )
    accepted, reason, _ = flo.filter_lens_output(text, repo)

    assert accepted is False
    assert reason == "confirmation_no_objection"


def test_027o_dod_c_objection_with_real_citation_passes(repo: Path):
    """DoD (c): objecion + cita real -> PASA. Es la unica salida que aporta."""
    text = _receipt(
        "scripts/real_module.py",
        verdict="Incorrecto: la premisa es falsa, el modulo no hace lo que dices.",
    )
    accepted, reason, problems = flo.filter_lens_output(text, repo)

    assert accepted is True, (reason, problems)
    assert reason == "objection_with_verified_citation"


def test_027o_objection_after_polite_opening_is_still_an_objection(repo: Path):
    """Anti-falso-positivo: la cortesia previa no convierte una objecion en
    confirmacion. Sin esto, el filtro descartaria aportacion legitima -- y un
    filtro que descarta trabajo bueno ensena al operador a apagarlo."""
    text = _receipt(
        "scripts/real_module.py",
        verdict="De acuerdo en el diagnostico general, pero el fix es incorrecto.",
    )
    accepted, _, _ = flo.filter_lens_output(text, repo)

    assert accepted is True


def test_027o_output_without_receipt_is_discarded(repo: Path):
    """Una afirmacion SIN recibo no es un probe: no puede verificarse."""
    accepted, reason, _ = flo.filter_lens_output("Hay un bug, creeme.", repo)

    assert accepted is False
    assert reason == "fabricated_citation"


def test_027o_cli_exit_code_discriminates(repo: Path, capsys):
    """La salida es AUDITABLE por exit code, no solo por texto."""
    good = repo / "good.md"
    good.write_text(
        _receipt("scripts/real_module.py", verdict="Incorrecto: esto falla."),
        encoding="utf-8",
    )
    bad = repo / "bad.md"
    bad.write_text(
        _receipt("no/existe.py", verdict="Incorrecto: esto falla."), encoding="utf-8"
    )

    assert flo.main(["--lens-output", str(good), "--root", str(repo)]) == 0
    assert flo.main(["--lens-output", str(bad), "--root", str(repo)]) == 1
