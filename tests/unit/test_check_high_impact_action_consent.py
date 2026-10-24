import sys
from pathlib import Path


_MOTOR_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _MOTOR_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import check_high_impact_action_consent as hiac  # noqa: E402


def _write(tmp_path: Path, rel: str, text: str) -> Path:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# WOT-2026-043n DoD (b): mutation en las dos direcciones, caso real 042q.
_DISPATCH_TEXT_NO_CONSENT = (
    "# Arranque del vuelo\n\n"
    "Haz fan-out a 5 backends externos con el bundle completo del ticket.\n"
)

_DISPATCH_TEXT_WITH_CONSENT = (
    "# Arranque del vuelo\n\n"
    "Autorizacion: usuario, en la sesion que redacto este prompt.\n\n"
    "Haz fan-out a 5 backends externos con el bundle completo del ticket.\n"
)


def test_dispatch_externo_sin_autorizacion_falla_nombrando_la_accion():
    errors = hiac.check_action_consent(_DISPATCH_TEXT_NO_CONSENT)

    assert len(errors) == 1
    assert "dispatch_externo" in errors[0]


def test_dispatch_externo_con_autorizacion_pasa():
    errors = hiac.check_action_consent(_DISPATCH_TEXT_WITH_CONSENT)

    assert errors == []


def test_mutation_both_directions():
    """DoD (b): ordenar sin clausula -> ROJO; con clausula -> VERDE."""
    red = hiac.check_action_consent(_DISPATCH_TEXT_NO_CONSENT)
    assert any("dispatch_externo" in e for e in red)

    green = hiac.check_action_consent(_DISPATCH_TEXT_WITH_CONSENT)
    assert green == []


def test_vague_sin_autorizacion_does_not_mask_as_consent():
    """'sin autorizacion' no debe leerse como una clausula POSITIVA."""
    text = "Haz fan-out a 5 backends externos, sin autorizacion explicita de nadie.\n"

    errors = hiac.check_action_consent(text)

    assert any("dispatch_externo" in e for e in errors)


def test_push_sin_autorizacion_falla():
    text = "Cuando termines, haz git push a origin de la rama del vuelo.\n"

    errors = hiac.check_action_consent(text)

    assert any("push" in e for e in errors)


def test_borrado_irreversible_sin_autorizacion_falla():
    text = "Antes de reintentar, ejecuta rm -rf sobre el directorio de cache.\n"

    errors = hiac.check_action_consent(text)

    assert any("borrado_irreversible" in e for e in errors)


def test_gasto_desproporcionado_sin_autorizacion_falla():
    text = "Lee 1070 lineas de contratos antes de la re-medicion read-only.\n"

    errors = hiac.check_action_consent(text)

    assert any("gasto_desproporcionado" in e for e in errors)


def test_local_readonly_artifact_is_never_blocked():
    """DoD (c): anti-falso-positivo, un artefacto solo local/read-only no se marca."""
    text = (
        "# Triaje local\n\n"
        "Lee el backlog.md y el STATE.md del destino, clasifica cada ticket y "
        "escribe el informe en orchestrator_pipeline/reports/. No toca git, no "
        "publica nada fuera de la maquina.\n"
    )

    errors = hiac.check_action_consent(text)

    assert errors == []


def test_main_cli_exits_1_naming_the_category(tmp_path, capsys):
    artifact = _write(tmp_path, "flight_start.md", _DISPATCH_TEXT_NO_CONSENT)

    rc = hiac.main(["--artifact", str(artifact)])

    assert rc == 1
    err = capsys.readouterr().err
    assert "dispatch_externo" in err


def test_main_cli_exits_0_when_consent_declared(tmp_path, capsys):
    artifact = _write(tmp_path, "flight_start.md", _DISPATCH_TEXT_WITH_CONSENT)

    rc = hiac.main(["--artifact", str(artifact)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "OK" in out


def test_main_cli_errors_on_missing_artifact(tmp_path, capsys):
    missing = tmp_path / "does_not_exist.md"

    rc = hiac.main(["--artifact", str(missing)])

    assert rc == 2
    err = capsys.readouterr().err
    assert "no encontrado" in err
