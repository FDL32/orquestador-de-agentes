"""Barrera textual del contrato de arranque del Builder (WOT-2026-058f).

Before: los prompts canonicos viven en `prompts/` del repo_motor.
During: lee `orchestrator_launch_builder.md` y `orchestrator_session_bootstrap.md`
    y comprueba, sin analisis semantico (solo regex/marcadores textuales):
    (a) que existe el guard de placeholders y que TODO token `{{...}}` presente
        pertenece al conjunto DECLARADO (un placeholder nuevo sin declarar cae);
    (b) que la contradiccion de `validate` se resolvio en UNA direccion (el
        Builder SI ejecuta `validate`): NO reaparece la prohibicion
        "no lo ejecutes desde el Builder" junto al criterio binario;
    (c) que la seccion `## Comportamiento esperado` no se duplica: exactamente
        una en el bootstrap (ergonomia M4: movida, no copiada) y ninguna en el
        launch_builder (nunca existio ahi).
After: verde si el contrato se mantiene; rojo si alguien reintroduce la
    contradiccion de `validate`, un placeholder no declarado o una seccion
    duplicada. No muta nada.
"""

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPTS = REPO_ROOT / "prompts"
LAUNCH_BUILDER = PROMPTS / "orchestrator_launch_builder.md"
SESSION_BOOTSTRAP = PROMPTS / "orchestrator_session_bootstrap.md"

# Universo cerrado declarado en la tabla "Placeholders de plantilla" del prompt.
DECLARED_PLACEHOLDERS = {
    "{{TICKET_ID}}",
    "{{NON_GOALS_UNA_LINEA}}",
    "{{DESCRIPCION_DEL_OBJETIVO_Y_ROOT_CAUSE}}",
    "{{SEAMS_Y_ARCHIVOS_A_CONFIRMAR}}",
    "{{DESCRIPCION_MINIMA_DEL_CAMBIO}}",
    "{{TEST_FILES}}",
    "{{PYTHON_FILES_TOUCHED}}",
    "{{CRITERIOS_ESPECIFICOS_DEL_TICKET}}",
}

# Un token de plantilla es `{{...}}` en UNA sola linea. El `[^}\n]` impide que
# una llave suelta del guard ("`{{` sin sustituir") case con el `}}` de un
# placeholder posterior en otra linea.
_PLACEHOLDER_RE = re.compile(r"\{\{[^}\n]+?\}\}")
_COMPORTAMIENTO_RE = re.compile(r"^## Comportamiento esperado$", re.MULTILINE)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_placeholder_guard_is_present() -> None:
    """El prompt declara el guard textual contra placeholders crudos."""
    text = _text(LAUNCH_BUILDER)
    assert "DETENTE" in text, "falta la palabra-guard DETENTE"
    assert "sin sustituir" in text, "falta 'sin sustituir' en el guard"
    assert "GUARD (textual, sin analisis semantico)" in text, (
        "falta el marcador del guard de placeholders"
    )
    assert "Orquestador" in text, "el guard no declara quien rellena la plantilla"


def test_all_placeholders_are_declared() -> None:
    """Todo token `{{...}}` presente debe estar en el conjunto declarado."""
    found = set(_PLACEHOLDER_RE.findall(_text(LAUNCH_BUILDER)))
    undeclared = found - DECLARED_PLACEHOLDERS
    assert not undeclared, (
        f"placeholders sin declarar en el prompt: {sorted(undeclared)}"
    )
    # El universo declarado debe estar cubierto: no declarar huecos inexistentes.
    missing_in_body = DECLARED_PLACEHOLDERS - found
    assert not missing_in_body, (
        f"placeholders declarados que no aparecen en el prompt: {sorted(missing_in_body)}"
    )


def test_validate_direction_is_declared_and_prohibition_absent() -> None:
    """La direccion de `validate` queda declarada en una sola direccion."""
    text = _text(LAUNCH_BUILDER)
    assert "no lo ejecutes desde el Builder" not in text, (
        "reaparecio la prohibicion que contradecia el criterio binario de salida"
    )
    assert "direccion unica" in text and "Builder SI ejecuta" in text, (
        "falta la declaracion de direccion canonica de `validate`"
    )


def test_validate_contradiction_cannot_coexist() -> None:
    """La prohibicion y el criterio binario no pueden coexistir (mutation)."""
    text = _text(LAUNCH_BUILDER)
    prohibits = "no lo ejecutes desde el Builder" in text
    requires = re.search(r"`validate --json` devuelve 0 errores", text) is not None
    assert not (prohibits and requires), (
        "contradiccion de `validate` reintroducida: prohibido al Builder y a la "
        "vez exigido como criterio binario de su salida"
    )


def test_comportamiento_esperado_not_duplicated() -> None:
    """`## Comportamiento esperado` no se copia: una en bootstrap, 0 en builder."""
    bootstrap_count = len(_COMPORTAMIENTO_RE.findall(_text(SESSION_BOOTSTRAP)))
    builder_count = len(_COMPORTAMIENTO_RE.findall(_text(LAUNCH_BUILDER)))
    assert bootstrap_count == 1, (
        f"orchestrator_session_bootstrap.md debe tener exactamente 1 "
        f"`## Comportamiento esperado` (movida, no duplicada); tiene {bootstrap_count}"
    )
    assert builder_count == 0, (
        f"orchestrator_launch_builder.md nunca tuvo `## Comportamiento esperado`; "
        f"una copia ahi es la corrupcion que WOT-2026-058f corrige; tiene {builder_count}"
    )
