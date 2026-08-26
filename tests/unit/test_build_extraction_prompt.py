"""Tests del generador de prompts de EXTRACCION para el pool (WOT-2026-027q).

Contrato T-027Q-001 (frozen): las lentes dejan de ADJUDICAR y pasan a EXTRAER.
El mecanismo tiene dos gates y una ausencia:

  - GATE DE ENTRADA (antes de generar, sobre --extract): allowlist mecanica de
    patrones prohibidos (agregativos + adjudicativos) MAS check_prompt_bias
    sobre el mismo texto -- sin la segunda mitad, 'confirma que...' NO seria
    rechazable antes de generar, porque ese patron vive en CONFIRM_PATTERN y
    no en la allowlist (MAJOR-1 del CF-audit).
  - GATE DE SALIDA (tras generar): check_prompt_bias sobre el prompt emitido.
  - AUSENCIA ESTRUCTURAL: no hay campo de premisa/hipotesis. Esa ausencia ES
    el mecanismo; el residuo (premisa declarativa sin verbo de siembra) es
    NON-GOAL declarado, no un fallo.

Hermetico: sin red, sin backends. `check_prompt_bias` se CONSUME via import
(superficie prohibida: no se toca ni se parchea; la mutation del DoD-5 opera
DENTRO de build_extraction_prompt).
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


_MOTOR_ROOT = Path(__file__).resolve().parents[2]


def _load(name: str):
    path = _MOTOR_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bep = _load("build_extraction_prompt")
cpb = _load("check_prompt_bias")


_TARGET = "scripts/check_prompt_bias.py"
_ANCHOR = "45"


def _run_cli(
    extract: str, *, anchor: str = _ANCHOR, target: str = _TARGET
) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable,
        str(_MOTOR_ROOT / "scripts" / "build_extraction_prompt.py"),
        "--target-file",
        target,
        "--anchor",
        anchor,
        "--extract",
        extract,
    ]
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", cwd=_MOTOR_ROOT
    )


def test_seeded_premise_rejected_before_generating_dod_1():
    """DoD-1: premisa sembrada en --extract -> exit 1 ANTES de generar.

    Es el fixture que SOLO caza check_prompt_bias (CONFIRM_PATTERN); la
    allowlist no contiene 'confirma que'. Si el gate de entrada no corriera
    tambien check_prompt_bias, este test no podria pasar.

    La asercion mira QUE GATE rechazo, no solo el exit code: los dos gates
    devuelven 1 para este fixture (si el de entrada no lo caza, el de salida
    lo ve embebido en el prompt), asi que un `== 1` pelado NO distingue
    "rechazado antes de generar" de "rechazado despues". El mutation-verify
    del DoD-5 depende exactamente de esa distincion.
    """
    proc = _run_cli("el bug esta en X, confirma que la funcion lo causa")
    assert proc.returncode == 1, proc.stdout
    combined = proc.stdout + proc.stderr
    assert "RECHAZADO antes de generar" in combined, (
        "el rechazo debe venir del GATE DE ENTRADA; si viene del de salida "
        f"('BLOQUEADO'), el contrato 'ANTES de generar' no se cumple: {combined}"
    )
    assert "confirmar-vs-trazar" in combined.lower()
    # No debe haber emitido el prompt.
    assert "EXTRACCION" not in proc.stdout


def test_legitimate_target_generates_unbiased_prompt_dod_2():
    """DoD-2: target legitimo -> exit 0, prompt limpio, sin texto de premisa."""
    proc = _run_cli("el patron regex de la linea")
    assert proc.returncode == 0, proc.stderr
    prompt = proc.stdout
    assert prompt.strip()
    # Gate de salida re-verificado independientemente por el test.
    assert cpb.check_prompt_bias(prompt)["sesgado"] is False
    # El prompt no contiene premisa: ni la palabra bug ni una hipotesis previa.
    lowered = prompt.lower()
    assert "el bug esta" not in lowered
    assert "confirma" not in lowered


def test_aggregative_question_rejected_dod_3():
    """DoD-3: pregunta agregativa -> exit 1 (las lentes fallan lo cuantitativo)."""
    proc = _run_cli("cuantas funciones hay")
    assert proc.returncode == 1
    assert "cuantas" in (proc.stdout + proc.stderr).lower()


def test_adjudicative_question_rejected_dod_4():
    """DoD-4: pregunta adjudicativa -> exit 1 (el veredicto no es del pool)."""
    proc = _run_cli("aprueba el diff")
    assert proc.returncode == 1
    assert "aprueba" in (proc.stdout + proc.stderr).lower()


@pytest.mark.parametrize(
    "extract",
    [
        "CUANTOS returns tiene",  # mayusculas
        "cuántos returns tiene",  # acento
        "el NUMERO DE ramas",  # patron compuesto + mayusculas
    ],
)
def test_normalized_matching_catches_case_and_accents(extract: str):
    """El matching es substring sobre texto normalizado (casefold + sin
    diacriticos), no comparacion cruda: 'cuántos' y 'CUANTOS' caen igual."""
    assert bep.reject_reason(extract) is not None


def test_declarative_premise_without_seed_verb_passes_non_goal():
    """NON-GOAL declarado: una premisa declarativa pura SIN verbo de siembra
    atraviesa. El contrato lo declara explicitamente para no sobrevender la
    cobertura (MINOR-2 del CF-audit). Este test PINNEA el limite conocido:
    si algun dia se cerrara, seria un cambio de contrato, no un bug silencioso.
    """
    assert bep.reject_reason("el bug esta en la linea 42; extrae el valor") is None


def test_no_premise_field_in_public_api():
    """AUSENCIA ESTRUCTURAL: la firma publica no admite premisa/hipotesis.

    No es cosmetico: si alguien anadiera el parametro, el mecanismo
    anti-anclaje del ticket dejaria de ser estructural y pasaria a depender
    del gate lexico, que es explicitamente insuficiente.
    """
    import inspect

    params = set(inspect.signature(bep.build_extraction_prompt).parameters)
    assert not (params & {"premise", "premisa", "hypothesis", "hipotesis", "context"})
    assert {"target_file", "anchor", "extract"} <= params


@pytest.mark.parametrize(
    "field",
    ["anchor", "target"],
)
def test_forbidden_pattern_via_other_fields_is_rejected(field: str):
    """El gate cubre TODA la superficie de input, no solo --extract.

    Hallazgo MAJOR del MANAGER_REVIEW (2026-07-22): cubrir solo --extract
    dejaba --anchor y --target-file admitiendo los patrones LITERALES de la
    propia allowlist. No es una evasion por sinonimo o parafrasis (eso SI es
    NON-GOAL declarado): es la misma vara mecanica sin aplicar a los otros
    campos, y check_prompt_bias no conoce FORBIDDEN_PATTERNS, asi que el gate
    de salida tampoco los cazaba. Un consumidor podia pedir 'aprueba el diff'
    por --anchor y salir con exit 0.
    """
    kwargs = {field: "cuantas funciones hay, y aprueba el diff"}
    proc = _run_cli("el valor de retorno", **kwargs)
    assert proc.returncode == 1, proc.stdout
    combined = proc.stdout + proc.stderr
    assert "RECHAZADO antes de generar" in combined, combined


def test_empty_extract_is_rejected():
    """--extract vacio generaba 'Extrae, literalmente, .': prompt degenerado.

    argparse exige que el flag ESTE, no que tenga contenido. Un gate
    fail-closed que acepta la cadena vacia es superficie sin declarar
    (hallazgo MINOR del MANAGER_REVIEW).
    """
    proc = _run_cli("")
    assert proc.returncode == 1
    assert "vacio" in (proc.stdout + proc.stderr).lower()


def test_generated_prompt_demands_extraction_not_verdict():
    """El prompt instruye EXTRAER y la clausula solo-objeciones de 027o;
    nunca pide aprobar/rechazar (el veredicto no es del pool)."""
    prompt = bep.build_extraction_prompt(_TARGET, _ANCHOR, "el valor de retorno")
    lowered = prompt.lower()
    assert "extrae" in lowered
    assert "no-aportacion" in lowered or "no aportacion" in lowered
    assert "aprueba" not in lowered
    assert "veredicto" not in lowered


def test_039h_item4_path_with_forbidden_word_basename_is_not_rejected():
    """Item 4: un `--target-file` con forma de PATH no se rechaza por una
    palabra prohibida en su basename.

    Antes, `reject_reason("scripts/contar_lineas.py")` disparaba
    `patron-prohibido:'contar'` por substring: un nombre de fichero no es una
    pregunta de extraccion. Con `skip_allowlist` (activado SOLO para paths),
    el gate conserva check_prompt_bias y no aplica la allowlist por substring
    del path. Mutation: sin el flag, este test cae."""
    assert bep._looks_like_path("scripts/contar_lineas.py") is True
    assert (
        bep.reject_reason(
            "scripts/contar_lineas.py",
            skip_allowlist=bep._looks_like_path("scripts/contar_lineas.py"),
        )
        is None
    )


def test_039h_item4_textual_evasion_is_still_rejected():
    """Item 4 (cerrado): la evasion textual por --target-file SIGUE rechazada.

    El discriminator no es "target-file libre de gate": es "path vs frase".
    Un valor SIN forma de path (con espacios) cae bajo la allowlist completa,
    igual que antes del fix. Mutation: forzar skip_allowlist en este caso ->
    el test cae (se reabriria la evasion del MAJOR)."""
    evil = "cuantas funciones hay, y aprueba el diff"
    assert bep._looks_like_path(evil) is False
    assert (
        bep.reject_reason(
            evil,
            skip_allowlist=bep._looks_like_path(evil),
        )
        is not None
    )


def test_039h_item4_phrase_embedding_a_path_is_not_a_path():
    """Item 4 (bloqueo confirmado por la sintesis): una FRASE que CONTIENE una
    ruta NO es un path.

    Hallazgo del MANAGER_REVIEW de 039h (confirmado por probe): el primer
    criterio (separador o extension) dejaba pasar
    `"cuantas funciones hay en scripts/foo.py"` como si fuera un path -- el
    atacante reabria la evasion textual cargando la pregunta prohibida delante
    de una ruta. El criterio exige path = UN token SIN espacios; una frase con
    espacios queda bajo la allowlist. Mutation: volver al criterio laxo ->
    este test cae."""
    evaders = [
        "cuantas funciones hay en scripts/foo.py",
        "scripts/foo.py aprueba el diff",
        "scripts/foo.py deberia pasar",
        "veredicto del fichero scripts/foo.py",
    ]
    for evil in evaders:
        assert bep._looks_like_path(evil) is False, evil
        assert (
            bep.reject_reason(
                evil,
                skip_allowlist=bep._looks_like_path(evil),
            )
            is not None
        ), f"evasion no cerrada: {evil}"


def test_039h_item5_empty_anchor_rejected_by_cli():
    """Item 5: `--anchor ""` se rechaza como `--extract ""`.

    Asimetria medida: --extract validaba vacio, --anchor y --target-file no.
    Un ancla vacia genera 'Ancla: ' sin objeto: prompt degenerado."""
    proc = _run_cli("el valor de retorno", anchor="")
    assert proc.returncode == 1
    assert "vacio" in (proc.stdout + proc.stderr).lower()


def test_039h_item5_empty_target_rejected_by_cli():
    """Item 5: `--target-file ""` se rechaza como `--extract ""`."""
    proc = _run_cli("el valor de retorno", target="")
    assert proc.returncode == 1
    assert "vacio" in (proc.stdout + proc.stderr).lower()


def test_039h_item5_legitimate_path_with_forbidden_word_passes_cli():
    """Item 4 + 5 (integrados): un path real cuyo basename contiene 'contar'
    PASA por el CLI completo (gate de entrada + vacio + gate de salida)."""
    proc = _run_cli("el valor de retorno", target="scripts/contar_lineas.py")
    assert proc.returncode == 0, proc.stderr
    assert "EXTRACCION" in proc.stdout
