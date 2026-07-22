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
    # WOT-2026-039c renombra el reason de aceptacion a 'accepted' (el enum de
    # 4 razones del contrato). Cambio DECLARADO en el CF-audit (O7), no deriva.
    assert reason == "accepted"


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
    """Una afirmacion SIN recibo NI cita no es un probe: no puede verificarse.

    WOT-2026-039c afina la RAZON: prosa sin ningun bloque verificable ya no es
    'fabricated_citation' (no hay cita que fabricar) sino 'no_contribution'
    con el problema 'missing_cite_block'. Es el H10 medido: las lentes
    responden prosa y el diagnostico antiguo confundia "no cumple el schema"
    con "minti sobre una cita".
    """
    accepted, reason, problems = flo.filter_lens_output("Hay un bug, creeme.", repo)

    assert accepted is False
    assert reason == "no_contribution"
    assert any(p.startswith("missing_cite_block") for p in problems), problems


def _cite(path: str, line: int, quote: str, *, verdict: str) -> str:
    """Salida de lente con bloque ```cite (schema lens-answer/v1, 039c)."""
    return f"{verdict}\n\n```cite\npath: {path}\nline: {line}\nquote: {quote}\n```\n"


@pytest.fixture
def cite_repo(tmp_path: Path) -> Path:
    """Arbol con un fichero de contenido conocido para verificar quotes."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "real_module.py").write_text(
        "import os\nDEFAULT_ENCODING = 'utf-8'\ndef run():\n    return 42\n",
        encoding="utf-8",
    )
    return tmp_path


def test_039c_missing_cite_block_is_no_contribution(cite_repo: Path):
    """DoD (b): salida sin bloque cite -> no_contribution/missing_cite_block.

    Es H10 medido: las 6 salidas del bucle de cierre eran prosa sin schema.
    Sin contrato de salida DEFINIDO el filtro no tiene sobre que morder.
    """
    accepted, reason, problems = flo.filter_lens_output(
        "La funcion falla porque no valida el encoding.", cite_repo, cite_only=True
    )

    assert accepted is False
    assert reason == "no_contribution"
    assert any(p.startswith("missing_cite_block") for p in problems), problems


def test_039c_h7_neutral_noise_is_not_an_objection(cite_repo: Path):
    """H7: ruido NEUTRO -> 'neutral' -> no-aportacion.

    Antes el default del clasificador era 'objection', asi que una salida sin
    marcador ninguno se contaba como aportacion: fail-open del clasificador de
    forma (obs-clasificador-de-forma-fail-open-acepta-ruido-neutro).
    """
    assert flo.classify_verdict("El fichero usa utf-8 al abrir.") == "neutral"

    text = _cite(
        "scripts/real_module.py",
        2,
        "DEFAULT_ENCODING",
        verdict="El fichero declara su encoding en una constante.",
    )
    accepted, reason, _ = flo.filter_lens_output(text, cite_repo, cite_only=True)

    assert accepted is False
    assert reason == "no_contribution"


def test_039c_h8_negated_marker_is_not_an_objection(cite_repo: Path):
    """H8: la NEGACION ya no invierte el filtro.

    'Confirmado: no hay bug' matchea el marcador 'bug' y salia como objecion,
    que es lo CONTRARIO de lo que dice. Es el caso peligroso: una confirmacion
    disfrazada de aportacion.
    """
    assert flo.classify_verdict("Confirmado: no hay bug aqui") != "objection"

    text = _cite(
        "scripts/real_module.py",
        4,
        "return 42",
        verdict="Confirmado: no hay bug en el valor de retorno.",
    )
    accepted, reason, _ = flo.filter_lens_output(text, cite_repo, cite_only=True)

    assert accepted is False
    assert reason in ("confirmation_no_objection", "no_contribution")


def test_039c_h8_sin_embargo_is_still_an_objection(cite_repo: Path):
    """Anti-falso-positivo de H8: 'sin embargo' es un MARCADOR, no una
    negacion. El negador 'sin' no debe desactivarlo -- si lo hiciera, el fix
    de H8 descartaria objeciones legitimas (caso borde del CF-audit)."""
    assert flo.classify_verdict("Sin embargo, el valor de retorno es erroneo.") == (
        "objection"
    )


def test_039c_h9_fabricated_execution_receipt_is_not_a_cite(cite_repo: Path):
    """H9: un receipt de EJECUCION emitido por una lente SIN filesystem no
    puede verificarse. En modo cite_only se IGNORA como prosa: la salida se
    descarta por no traer cite, no se acepta por traer un receipt inventado.
    """
    text = _receipt("scripts/real_module.py", verdict="Hay un bug incorrecto aqui.")
    accepted, reason, problems = flo.filter_lens_output(text, cite_repo, cite_only=True)

    assert accepted is False
    assert reason == "no_contribution"
    assert any(p.startswith("missing_cite_block") for p in problems), problems


def test_039c_fabricated_quote_at_real_line_is_discarded(cite_repo: Path):
    """La linea EXISTE pero no dice lo que la lente afirma -> descartada.

    Este es el salto sobre 027o: alli bastaba que el PATH resolviera. Aqui se
    verifica el CONTENIDO de la linea citada, que es lo que convierte la cita
    en evidencia y no en un puntero decorativo.
    """
    text = _cite(
        "scripts/real_module.py",
        2,
        "mock_subprocess",
        verdict="Incorrecto: el modulo parchea subprocess.",
    )
    accepted, reason, problems = flo.filter_lens_output(text, cite_repo, cite_only=True)

    assert accepted is False
    assert reason == "fabricated_citation"
    assert any("quote not found" in p for p in problems), problems


def test_039c_short_quote_is_rejected(cite_repo: Path):
    """Un quote de 1-2 caracteres casaria con cualquier linea: sello de goma."""
    text = _cite(
        "scripts/real_module.py", 2, "=", verdict="Incorrecto: hay un bug aqui."
    )
    accepted, _reason, problems = flo.filter_lens_output(
        text, cite_repo, cite_only=True
    )

    assert accepted is False
    assert any("quote too short" in p for p in problems), problems


def test_039c_objection_with_verified_quote_is_accepted(cite_repo: Path):
    """La UNICA salida que aporta: objecion + cita cuyo quote esta en la linea."""
    text = _cite(
        "scripts/real_module.py",
        4,
        "return 42",
        verdict="Incorrecto: la premisa es falsa, devuelve un literal.",
    )
    accepted, reason, problems = flo.filter_lens_output(text, cite_repo, cite_only=True)

    assert accepted is True, (reason, problems)
    assert reason == "accepted"


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
