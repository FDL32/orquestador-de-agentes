"""Tests de la barrera del recibo DEC (WOT-2026-042x).

MUTATION en las CUATRO direcciones que exige el DoD, cada una con su node-id:

  ficha SIN recibo                  -> ROJO   test_receipt_absent_is_rejected
  recibo con DEC-<id> INEXISTENTE   -> ROJO   test_receipt_with_unknown_dec_is_rejected
  recibo con DEC-<id> existente     -> VERDE  test_receipt_with_known_dec_is_accepted
  `DEC-no-aplica: <motivo>`         -> VERDE  test_dec_no_aplica_with_motive_is_accepted

Las cuatro se ejercen sobre la funcion PURA `receipt_is_valid` y, donde el
veredicto depende del disco (grandfathering, scope no verificable), sobre
`check_file` con ficheros REALES en `tmp_path` -- no mocks: el defecto que este
guard previene vive en la frontera con ficheros de verdad.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "check_dec_receipt.py"
_spec = importlib.util.spec_from_file_location("check_dec_receipt", _MODULE_PATH)
assert _spec and _spec.loader
cdr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cdr)


REGISTRY = {"008B-001", "008B-002", "025H-001", "MOTOR-CHARTER-001"}


# ---------------------------------------------------------------------------
# Las CUATRO direcciones de la mutation
# ---------------------------------------------------------------------------


def test_receipt_absent_is_rejected() -> None:
    """Direccion 1: una ficha sin recibo NO pasa."""
    receipt = "Titulo: algo\nscope: motor\nDoD: binario\n"
    assert cdr.receipt_is_valid(receipt, REGISTRY) is False


def test_receipt_with_unknown_dec_is_rejected() -> None:
    """Direccion 2: citar un DEC que NO existe en el registro declarado -> ROJO.

    Es el corazon del guard: sin esto, un recibo con formato correcto y un id
    inventado pasaria, que es indistinguible de no tener barrera.
    """
    assert cdr.receipt_is_valid("DEC-999Z-001 (motor)", REGISTRY) is False


def test_receipt_with_known_dec_is_accepted() -> None:
    """Direccion 3: un DEC existente en el registro declarado -> VERDE."""
    assert cdr.receipt_is_valid("Recibo: DEC-008B-001 (motor)", REGISTRY) is True


def test_dec_no_aplica_with_motive_is_accepted() -> None:
    """Direccion 4: `DEC-no-aplica: <motivo>` con motivo escrito -> VERDE."""
    receipt = "DEC-no-aplica: el ticket no adjudica nada, solo mide un censo"
    assert cdr.receipt_is_valid(receipt, REGISTRY) is True


# ---------------------------------------------------------------------------
# Bordes de la funcion pura
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("empty_motive", ["", "   ", "n/a", "N/A", "na"])
def test_dec_no_aplica_without_motive_is_rejected(empty_motive: str) -> None:
    """`DEC-no-aplica` sin motivo es una casilla marcada, no una decision."""
    assert cdr.receipt_is_valid(f"DEC-no-aplica: {empty_motive}", REGISTRY) is False


def test_receipt_without_scope_is_rejected() -> None:
    """Un `DEC-<id>` SIN scope no es resoluble: no se sabe contra que registro va."""
    assert cdr.receipt_is_valid("DEC-008B-001", REGISTRY) is False


def test_all_cited_decs_must_exist() -> None:
    """Si el recibo cita varios ids, UNO inexistente basta para rechazar.

    Evita el falso verde de "cita algo valido, ya vale": un override que nombra
    una DEC real y otra inventada sigue siendo irresoluble.
    """
    receipt = "DEC-008B-001 (motor) supersedes: DEC-777X-001 (motor)"
    assert cdr.receipt_is_valid(receipt, REGISTRY) is False


def test_multi_segment_dec_id_is_not_truncated() -> None:
    """Regresion medida (2026-07-29): el id es `<familia>-<numero>`, no un segmento.

    Un patron de un solo segmento colapsaba `DEC-008B-001` y `DEC-008B-002` en
    `008B` -- 6 ficheros del registro real producian 5 ids -- y habria rechazado
    un recibo que cita el id COMPLETO. FAIL sin el fix, PASS con el.
    """
    assert cdr.receipt_is_valid("DEC-008B-002 (motor)", REGISTRY) is True
    assert cdr.receipt_is_valid("DEC-MOTOR-CHARTER-001 (motor)", REGISTRY) is True


# ---------------------------------------------------------------------------
# Registros reales del repo (frontera, no mocks)
# ---------------------------------------------------------------------------


def test_motor_registry_ids_round_trip_against_real_repo() -> None:
    """Todo id del registro REAL del motor valida como recibo con scope (motor).

    Un guard cuyo parser no reconoce los ids que el propio repo escribe seria un
    falso rojo permanente. Se mide contra `docs/decisions/`, no contra fixtures
    (un barrido contra tus propios fixtures mide tus fixtures).
    """
    motor_root = Path(__file__).resolve().parents[2]
    registry = cdr.load_motor_registry(motor_root)
    assert registry, "docs/decisions/ debe contener al menos una DEC"
    for dec_id in registry:
        assert cdr.receipt_is_valid(f"DEC-{dec_id} (motor)", registry) is True, (
            f"el id REAL {dec_id} no round-trip: el parser del recibo y el del "
            "registro han divergido"
        )


# ---------------------------------------------------------------------------
# Grandfathering: el anti-falso-positivo (censo medido 14/14 sin recibo)
# ---------------------------------------------------------------------------


def test_grandfather_cutoff_is_a_declared_constant() -> None:
    """La fecha esta FIJADA en el modulo, no derivada de `today()`.

    Una fecha calculada del reloj haria que el gate cambiara de veredicto solo,
    sin que nadie tocara codigo (caducidad silenciosa, `WOT-2026-024t`).
    """
    assert cdr.GRANDFATHER_CUTOFF == "2026-07-29"
    # Se mide sobre el CODIGO, no sobre el texto crudo: el propio modulo explica
    # en un comentario POR QUE no usa `today()`, y grepear el texto entero
    # convertiria esa explicacion en un falso positivo (medido 2026-07-29).
    code = "\n".join(
        line.split("#", 1)[0]
        for line in _MODULE_PATH.read_text(encoding="utf-8").splitlines()
    )
    assert "today()" not in code and "datetime.now" not in code, (
        "GRANDFATHER_CUTOFF debe ser constante declarada, nunca calculada"
    )


def test_pre_cutoff_ficha_without_receipt_warns_not_errors(tmp_path: Path) -> None:
    """Una ficha ANTERIOR al cutoff sin recibo pasa con WARN.

    Un gate que bloquease las 14 fichas preexistentes seria inservible y se le
    rodearia; ese es el fallo que este test fija.
    """
    ficha = tmp_path / "FP-20260726-041j-algo.tickets.md"
    ficha.write_text("Titulo: sin recibo\n", encoding="utf-8")
    level, _ = cdr.check_file(ficha, REGISTRY, None)
    assert level == "WARN"


def test_post_cutoff_ficha_without_receipt_errors(tmp_path: Path) -> None:
    """Una ficha con fecha IGUAL o POSTERIOR al cutoff sin recibo -> ERROR.

    Sin esta direccion el grandfathering seria una amnistia universal y el
    guard no bloquearia jamas.
    """
    ficha = tmp_path / "FP-20260730-nueva.tickets.md"
    ficha.write_text("Titulo: sin recibo\n", encoding="utf-8")
    level, _ = cdr.check_file(ficha, REGISTRY, None)
    assert level == "ERROR"


def test_ficha_on_cutoff_date_errors(tmp_path: Path) -> None:
    """El borde exacto: la fecha IGUAL al cutoff ya exige recibo (`<`, no `<=`)."""
    ficha = tmp_path / "FP-20260729-borde.tickets.md"
    ficha.write_text("Titulo: sin recibo\n", encoding="utf-8")
    level, _ = cdr.check_file(ficha, REGISTRY, None)
    assert level == "ERROR"


def test_ficha_without_parseable_date_is_not_grandfathered(tmp_path: Path) -> None:
    """Sin fecha parseable NO hay amnistia: ante duda, se exige el recibo."""
    ficha = tmp_path / "NOTE-sin-fecha.tickets.md"
    ficha.write_text("Titulo: sin recibo\n", encoding="utf-8")
    level, _ = cdr.check_file(ficha, REGISTRY, None)
    assert level == "ERROR"


# ---------------------------------------------------------------------------
# Topologia: el guard NO cruza repos
# ---------------------------------------------------------------------------


def test_destino_scope_without_registry_is_not_verifiable(tmp_path: Path) -> None:
    """Scope (destino) sin `--destino-registry` -> ERROR, nunca "valido".

    STOP condition del contrato: el registro del destino se pasa como ARGUMENTO.
    Si no se pasa, el recibo se marca NO VERIFICABLE con motivo; darlo por bueno
    seria exactamente el falso verde que la barrera existe para impedir.
    """
    ficha = tmp_path / "FP-20260730-destino.tickets.md"
    ficha.write_text("Recibo: DEC-010D-001 (destino)\n", encoding="utf-8")
    level, message = cdr.check_file(ficha, REGISTRY, None)
    assert level == "ERROR"
    assert "NO VERIFICABLE" in message


def test_destino_scope_resolves_against_passed_registry(tmp_path: Path) -> None:
    """Con el registro del destino PASADO, el scope (destino) si resuelve."""
    registry_file = tmp_path / "decisions.md"
    registry_file.write_text(
        "# Decisiones\n\n### DEC-010D-001 -- Autoridad de lectura\n\ncuerpo\n",
        encoding="utf-8",
    )
    destino = cdr.load_destino_registry(registry_file)
    assert destino == {"010D-001"}

    ficha = tmp_path / "FP-20260730-destino.tickets.md"
    ficha.write_text("Recibo: DEC-010D-001 (destino)\n", encoding="utf-8")
    level, _ = cdr.check_file(ficha, REGISTRY, destino)
    assert level == "OK"


def test_module_docstring_declares_no_topology_resolution() -> None:
    """El DoD exige que el docstring declare que NO resuelve topologia."""
    assert cdr.receipt_is_valid.__doc__ is not None
    assert "NO resuelve topologia" in cdr.receipt_is_valid.__doc__


def test_empty_inbox_skips_explicitly(capsys: pytest.CaptureFixture[str]) -> None:
    """0 fichas imprime SKIP EXPLICITO: un exit 0 mudo seria "no hice nada"."""
    assert cdr.main(["--motor-root", str(Path(__file__).resolve().parents[2])]) == 0
    assert "SKIP EXPLICITO" in capsys.readouterr().out
