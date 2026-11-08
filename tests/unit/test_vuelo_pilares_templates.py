"""Contract tests for the versioned flight prompt templates.

Before: the two template files and their declared-marker header exist in the
repository, or a fixture supplies candidate Markdown text.
During: parse declared and body markers, then validate portability and marker
coverage invariants, including malformed marker syntax.
After: valid production templates parse successfully; each malformed fixture
raises ``ValueError`` with an actionable reason.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


TEMPLATES_DIR = Path(__file__).parents[2] / "prompts" / "vuelo_pilares_templates"
TEMPLATE_PATHS = (
    TEMPLATES_DIR / "LATIDO_PLANTILLA.md",
    TEMPLATES_DIR / "ARRANQUE_PLANTILLA.md",
)
ABSOLUTE_ROUTE_RE = re.compile(
    r"(?:[A-Za-z]:[\\/]|/home/|/Users/|\\\\[^\\/\s]+[\\/][^\\/\s]+)"
)
UPPER_TOKEN_RE = re.compile(r"\{\{[A-Z_]+\}\}")
ANY_TOKEN_RE = re.compile(r"\{\{[^{}]*\}\}")
VALID_TOKEN_RE = re.compile(r"\{\{[A-Za-z_]*\}\}")
HEADER_RE = re.compile(r"\A<!-- Marcadores declarados: (.*?) -->")
KNOWN_CRITERION_FRAGMENTS = (
    "IM fresco por ticket",
    "una ronda de lentes a la vez",
    "IM<2",
    "IM vivos <2",
    "no hay APTO con brief",
    "para avanzar otra tarea durante la espera",
    "cada 6 h",
    "6 horas",
    "máximo de 5 entradas",
    "maximo 5 entradas",
    "sha12 coincide",
    "Builder vivo",
    "ninguna sesión fuera del roster",
    "dos IM en paralelo",
    "objetivo y tope",
    "protocolo de escalada",
    "cambio de cuenta según tokens",
    "el usuario no es cuello de botella",
    "sin push",
    "puedes lanzar el rotador",
    "lo lanza la supervisora",
)
EXCEPCIONES_C5 = {
    "No existe condición de contexto mínimo (retirada por P4)": (
        "DoD (c): es el propio paso de relevo CORREGIDO (sin la condición A "
        "de 380k), no un criterio copiado de otra fila del canon."
    ),
    "objetivo cerrado": (
        "DoD (c): el paso de relevo corregido exige las tres condiciones a la "
        "vez; no es un criterio copiado de otra fila."
    ),
    "ventana de no-relevo abierta": (
        "DoD (c): el paso de relevo corregido exige las tres condiciones a la "
        "vez; no es un criterio copiado de otra fila."
    ),
}


def parse_template(text: str) -> tuple[set[str], set[str]]:
    """Parse and validate one template's declared and used markers.

    Before: ``text`` is complete UTF-8 Markdown for one flight prompt
    template, beginning with a declared-marker header.
    During: extract the header list, validate every token's uppercase syntax,
    compare declarations with body usage, and reject machine-absolute routes.
    After: return the declared and body marker sets, or raise ``ValueError``
    naming the violated template invariant.
    """
    if ABSOLUTE_ROUTE_RE.search(text):
        raise ValueError("template contains an absolute route")
    header = HEADER_RE.search(text)
    if header is None:
        raise ValueError("template is missing marker header")
    declared = set(header.group(1).split())
    if not declared:
        raise ValueError("template declares no markers")
    body_text = text[header.end() :]
    unbalanced = VALID_TOKEN_RE.sub("", text)
    if "{" in unbalanced or "}" in unbalanced:
        raise ValueError("unbalanced marker braces")
    all_tokens = set(ANY_TOKEN_RE.findall(body_text))
    if not all_tokens:
        raise ValueError("template has no markers")
    invalid = all_tokens - set(UPPER_TOKEN_RE.findall(text))
    if invalid:
        raise ValueError("template contains malformed marker")
    body = set(UPPER_TOKEN_RE.findall(body_text))
    missing = declared - body
    if missing:
        raise ValueError("declared marker is unused")
    orphaned = body - declared
    if orphaned:
        raise ValueError("body marker is undeclared")
    return declared, body


def mutate_once(source: str, old: str, new: str) -> str:
    """Apply one exact fixture mutation, guarding against fragile tests."""
    assert source.count(old) == 1, f"fixture fragment is not unique: {old!r}"
    return source.replace(old, new)


def assert_no_criterion_fragments(text: str) -> None:
    """Reject literal canon criteria copied into a template body.

    Before: ``text`` is a complete template with its marker header.
    During: remove the header and scan the body against the explicit list of
    canon-derived criterion fragments.
    After: return silently when no criterion is copied; otherwise raise
    ``ValueError`` naming the first matching fragment.
    """
    header = HEADER_RE.search(text)
    if header is None:
        raise ValueError("template is missing marker header")
    body = text[header.end() :]
    for exception_text in EXCEPCIONES_C5:
        body = body.replace(exception_text, "")
    matches = [fragment for fragment in KNOWN_CRITERION_FRAGMENTS if fragment in body]
    if matches:
        raise ValueError(f"criterion fragment copied: {matches[0]}")


def test_real_templates_have_complete_portable_marker_contract() -> None:
    for path in TEMPLATE_PATHS:
        declared, used = parse_template(path.read_text(encoding="utf-8"))
        assert declared == used


def test_real_templates_do_not_copy_canon_criteria() -> None:
    for path in TEMPLATE_PATHS:
        assert_no_criterion_fragments(path.read_text(encoding="utf-8"))


def extract_relevo_block(text: str) -> str:
    """Extract LATIDO step 9 without accepting evidence from later steps."""
    start = text.find("9. Contexto y relevo:")
    if start < 0:
        return ""
    end = text.find("\n\n10.", start)
    return text[start:] if end < 0 else text[start:end]


def assert_relevo_requires_three_conditions(text: str) -> None:
    """Require the operational conjunction in LATIDO step 9.

    Before: ``text`` is a complete LATIDO template.
    During: inspect the body for all three pillar citations and an explicit
    conjunction, preserving the separate-result requirement.
    After: return silently only for the corrected relevo step; otherwise raise
    ``ValueError`` naming the missing operational invariant.
    """
    header = HEADER_RE.search(text)
    if header is None:
        raise ValueError("template is missing marker header")
    block = extract_relevo_block(text[header.end() :])
    if not all(pillar in block for pillar in ("P4", "P6", "P23")):
        raise ValueError("relevo must cite P4, P6 and P23")
    if not re.search(r"LAS TRES.*A LA VEZ", block, re.DOTALL):
        raise ValueError("relevo must require all three conditions together")
    if "resultado de cada una" not in block:
        raise ValueError("relevo must record each condition result")


def test_real_latido_relevo_requires_three_conditions() -> None:
    assert_relevo_requires_three_conditions(
        TEMPLATE_PATHS[0].read_text(encoding="utf-8")
    )


def test_c5_exceptions_are_explicit_and_present() -> None:
    latido = TEMPLATE_PATHS[0].read_text(encoding="utf-8")
    for exception_text, reason in EXCEPCIONES_C5.items():
        assert reason
        assert latido.count(exception_text) == 1


@pytest.fixture
def fixture_template() -> str:
    return """<!-- Marcadores declarados: {{ROL}} {{ID_PROPIO}} -->
# Plantilla

Identidad: {{ROL}} / {{ID_PROPIO}}
"""


@pytest.fixture
def fixture_relevo_template() -> str:
    return """<!-- Marcadores declarados: {{ROL}} {{ID_PROPIO}} -->
# Plantilla

8. Envíos: comprueba la entrega.

9. Contexto y relevo: el relevo SOLO procede si se cumplen LAS TRES
   condiciones A LA VEZ: P4 (NO RATIFICADA en el canon; objetivo cerrado),
   P6 (RATIFICADA, vinculante: GO nuevo, re-verificado con `user_msgs.py`) y
   P23 (NO RATIFICADA en el canon; ventana de no-relevo abierta). Registra el
   resultado de cada una.

10. Registra el estado.
"""


@pytest.mark.parametrize(
    ("old", "new", "reason"),
    [
        (
            "{{ID_PROPIO}} -->",
            "{{ID_PROPIO}} {{FANTASMA}} -->",
            "declared marker is unused",
        ),
        (
            "Identidad: {{ROL}} / {{ID_PROPIO}}",
            "Identidad: {{ROL}} / {{ID_PROPIO}} / {{HUERFANO}}",
            "body marker is undeclared",
        ),
        (
            "# Plantilla",
            "# C:\\Users\\alguien\\plantilla.md",
            "absolute route",
        ),
        (
            "Identidad: {{ROL}} / {{ID_PROPIO}}",
            "Identidad: sin marcadores",
            "template has no markers",
        ),
        (
            "Identidad: {{ROL}} / {{ID_PROPIO}}",
            "Identidad: {{ROL}} / {{rol}}",
            "malformed marker",
        ),
    ],
)
def test_template_negative_mutates_one_unique_fragment(
    fixture_template: str, old: str, new: str, reason: str
) -> None:
    candidate = mutate_once(fixture_template, old, new)
    with pytest.raises(ValueError, match=reason):
        parse_template(candidate)


@pytest.mark.parametrize(
    ("old", "new", "reason"),
    [
        (
            "<!-- Marcadores declarados: {{ROL}} {{ID_PROPIO}} -->\n",
            "",
            "template is missing marker header",
        ),
        (
            "<!-- Marcadores declarados: {{ROL}} {{ID_PROPIO}} -->",
            "<!-- Marcadores declarados:  -->",
            "template declares no markers",
        ),
        (
            "<!-- Marcadores declarados: {{ROL}} {{ID_PROPIO}} -->",
            "# prefix\n<!-- Marcadores declarados: {{ROL}} {{ID_PROPIO}} -->",
            "template is missing marker header",
        ),
        (
            "Identidad: {{ROL}} / {{ID_PROPIO}}",
            "Identidad: {{ROL} / {{ID_PROPIO}}",
            "unbalanced marker braces",
        ),
        (
            "# Plantilla",
            "# /Users/alguien/plantilla.md",
            "absolute route",
        ),
        (
            "# Plantilla",
            r"# \\servidor\recurso",
            "absolute route",
        ),
    ],
)
def test_template_structure_negative_mutates_one_unique_fragment(
    fixture_template: str, old: str, new: str, reason: str
) -> None:
    candidate = mutate_once(fixture_template, old, new)
    with pytest.raises(ValueError, match=reason):
        parse_template(candidate)


def test_template_criterion_fragment_fixture_fails_explicitly(
    fixture_template: str,
) -> None:
    candidate = mutate_once(
        fixture_template,
        "# Plantilla",
        "# Plantilla\n\nuna ronda de lentes a la vez",
    )
    with pytest.raises(ValueError, match="criterion fragment copied"):
        assert_no_criterion_fragments(candidate)


def test_relevo_fixture_without_three_conditions_fails_explicitly(
    fixture_template: str,
) -> None:
    candidate = mutate_once(
        fixture_template,
        "# Plantilla",
        "# Plantilla\n\n9. P6 (RATIFICADA): aplica.",
    )
    with pytest.raises(ValueError, match="P4, P6 and P23"):
        assert_relevo_requires_three_conditions(candidate)


def test_relevo_fixture_with_three_conditions_is_positive(
    fixture_relevo_template: str,
) -> None:
    assert_relevo_requires_three_conditions(fixture_relevo_template)


@pytest.mark.parametrize(
    ("old", "new", "reason"),
    [
        ("P23", "", "P4, P6 and P23"),
        (
            "LAS TRES\n   condiciones A LA VEZ",
            "",
            "all three conditions together",
        ),
        ("resultado de cada una", "", "record each condition result"),
    ],
)
def test_relevo_block_negative_mutates_one_unique_fragment(
    fixture_relevo_template: str, old: str, new: str, reason: str
) -> None:
    candidate = mutate_once(fixture_relevo_template, old, new)
    with pytest.raises(ValueError, match=reason):
        assert_relevo_requires_three_conditions(candidate)


@pytest.mark.parametrize(
    "fragment",
    ["puedes lanzar el rotador", "lo lanza la supervisora"],
)
def test_p25_fragment_fixture_fails_explicitly(
    fixture_template: str, fragment: str
) -> None:
    candidate = mutate_once(fixture_template, "# Plantilla", f"# Plantilla\n{fragment}")
    with pytest.raises(ValueError, match="criterion fragment copied"):
        assert_no_criterion_fragments(candidate)
