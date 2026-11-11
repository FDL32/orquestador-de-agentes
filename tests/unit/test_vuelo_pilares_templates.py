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
CANON_PATH = (
    Path(__file__).parents[2] / ".agent" / "rules" / "common" / "vuelo_pilares.md"
)
TEMPLATE_PATHS = (
    TEMPLATES_DIR / "LATIDO_PLANTILLA.md",
    TEMPLATES_DIR / "ARRANQUE_PLANTILLA.md",
)
REQUIRED_MARKERS_BY_TEMPLATE: dict[Path, frozenset[str]] = {
    TEMPLATE_PATHS[0]: frozenset({"MOTOR_ROOT"}),
    TEMPLATE_PATHS[1]: frozenset({"HEAD_SHA"}),
}
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
    "asienta (settle) todo CO fuera de la terna",
    "conteo esperado",
    "conteo medido",
    "como primer paso",
    "ejecuta el paso K-93",
)


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
    declared = {token.strip("{}") for token in header.group(1).split()}
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
    body = {token.strip("{}") for token in UPPER_TOKEN_RE.findall(body_text)}
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
    matches = [fragment for fragment in KNOWN_CRITERION_FRAGMENTS if fragment in body]
    if matches:
        raise ValueError(f"criterion fragment copied: {matches[0]}")


def assert_required_markers(template_path: Path, declared: set[str]) -> None:
    """Require every marker required by a portable template.

    Before: ``declared`` is the marker set already validated by
    :func:`parse_template`.
    During: look up the required set for ``template_path``.
    After: return silently when every required marker is declared; otherwise
    raise ``ValueError`` naming the first missing marker.
    """
    required = REQUIRED_MARKERS_BY_TEMPLATE.get(template_path, frozenset())
    missing = sorted(required - declared)
    if missing:
        raise ValueError(f"missing required marker: {missing[0]}")


def read_pillar_state(canon_text: str, pillar: str) -> str:
    """Read one pillar's ESTADO column from the real canon index.

    Before: ``canon_text`` is the complete canonical pillar index.
    During: locate the row whose first cell is exactly ``pillar``.
    After: return its ESTADO cell; raise ``ValueError`` if the row is missing.
    """
    row_re = re.compile(rf"^\| {re.escape(pillar)} \|.*\|$", re.MULTILINE)
    match = row_re.search(canon_text)
    if match is None:
        raise ValueError(f"pillar {pillar} is missing from canon")
    cells = [c.strip() for c in match.group(0).strip("|").split("|")]
    return cells[2]


def assert_pillar_cited_with_state(text: str, pillar: str, state: str) -> None:
    """Require one exact citation of pillar with its real state.

    Before: ``text`` is a complete template with its marker header.
    During: scan the body after the header for ``PILLAR (STATE`` citations.
    After: return silently on exactly one match; raise ``ValueError`` if the
    pillar/state citation is absent, or if it appears more than once.
    """
    header = HEADER_RE.search(text)
    if header is None:
        raise ValueError("template is missing marker header")
    body = text[header.end() :]
    pattern = re.compile(rf"\b{re.escape(pillar)}\s*\(\s*{re.escape(state)}\b")
    count = len(pattern.findall(body))
    if count == 0:
        raise ValueError(f"template does not cite {pillar} with state {state}")
    if count > 1:
        raise ValueError(f"template cites {pillar} more than once")


def test_real_templates_have_complete_portable_marker_contract() -> None:
    for path in TEMPLATE_PATHS:
        declared, used = parse_template(path.read_text(encoding="utf-8"))
        assert_required_markers(path, declared)
        assert declared == used


def test_real_templates_do_not_copy_canon_criteria() -> None:
    for path in TEMPLATE_PATHS:
        assert_no_criterion_fragments(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("pillar", ["P28", "P29"])
def test_real_templates_cite_pillar_with_its_real_state(pillar: str) -> None:
    canon_text = CANON_PATH.read_text(encoding="utf-8")
    state = read_pillar_state(canon_text, pillar)
    for path in TEMPLATE_PATHS:
        assert_pillar_cited_with_state(path.read_text(encoding="utf-8"), pillar, state)


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
    if not re.search(r"GO nuevo.*cada salto", block, re.DOTALL):
        raise ValueError("relevo must require GO per jump (P6 semantics)")


def test_real_latido_relevo_requires_three_conditions() -> None:
    assert_relevo_requires_three_conditions(
        TEMPLATE_PATHS[0].read_text(encoding="utf-8")
    )


def test_arranque_missing_head_sha_marker_fails_explicitly() -> None:
    text = TEMPLATE_PATHS[1].read_text(encoding="utf-8")
    assert text.count("{{HEAD_SHA}}") == 2
    candidate = text.replace("{{HEAD_SHA}}", "")
    declared, _used = parse_template(candidate)
    with pytest.raises(ValueError, match="missing required marker: HEAD_SHA"):
        assert_required_markers(TEMPLATE_PATHS[1], declared)


def test_latido_missing_motor_root_marker_fails_explicitly() -> None:
    text = TEMPLATE_PATHS[0].read_text(encoding="utf-8")
    assert text.count("{{MOTOR_ROOT}}") == 3
    candidate = text.replace("{{MOTOR_ROOT}}", "")
    declared, _used = parse_template(candidate)
    with pytest.raises(ValueError, match="missing required marker: MOTOR_ROOT"):
        assert_required_markers(TEMPLATE_PATHS[0], declared)


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
   P6 (RATIFICADA, vinculante: GO nuevo, re-verificado con `user_msgs.py` por
   cada salto) y
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


def test_p24_fragment_fixture_fails_explicitly(fixture_template: str) -> None:
    candidate = mutate_once(
        fixture_template,
        "# Plantilla",
        "# Plantilla\n\nasienta (settle) todo CO fuera de la terna",
    )
    with pytest.raises(ValueError, match="criterion fragment copied"):
        assert_no_criterion_fragments(candidate)


@pytest.mark.parametrize("fragment", ["conteo esperado", "conteo medido"])
def test_p28_matrix_fragment_fixture_fails_explicitly(
    fixture_template: str, fragment: str
) -> None:
    candidate = mutate_once(fixture_template, "# Plantilla", f"# Plantilla\n{fragment}")
    with pytest.raises(ValueError, match="criterion fragment copied"):
        assert_no_criterion_fragments(candidate)


@pytest.mark.parametrize("fragment", ["como primer paso", "ejecuta el paso K-93"])
def test_p24_first_step_fragment_fixture_fails_explicitly(
    fixture_template: str, fragment: str
) -> None:
    candidate = mutate_once(fixture_template, "# Plantilla", f"# Plantilla\n{fragment}")
    with pytest.raises(ValueError, match="criterion fragment copied"):
        assert_no_criterion_fragments(candidate)


def test_pillar_fixture_without_p28_citation_fails_explicitly(
    fixture_template: str,
) -> None:
    with pytest.raises(ValueError, match="does not cite P28"):
        assert_pillar_cited_with_state(fixture_template, "P28", "RATIFICADA")


def test_pillar_fixture_with_wrong_p28_state_fails_explicitly(
    fixture_template: str,
) -> None:
    candidate = mutate_once(
        fixture_template,
        "Identidad: {{ROL}} / {{ID_PROPIO}}",
        "Aplica P28 (NO RATIFICADA, no vinculante).\n\n"
        "Identidad: {{ROL}} / {{ID_PROPIO}}",
    )
    with pytest.raises(ValueError, match="does not cite P28 with state RATIFICADA"):
        assert_pillar_cited_with_state(candidate, "P28", "RATIFICADA")


def test_latido_missing_p28_citation_fails_on_real_template() -> None:
    text = TEMPLATE_PATHS[0].read_text(encoding="utf-8")
    candidate = mutate_once(text, "P28 (RATIFICADA, vinculante) y ", "")
    with pytest.raises(ValueError, match="does not cite P28 with state RATIFICADA"):
        assert_pillar_cited_with_state(candidate, "P28", "RATIFICADA")


def test_arranque_missing_p29_citation_fails_on_real_template() -> None:
    text = TEMPLATE_PATHS[1].read_text(encoding="utf-8")
    candidate = mutate_once(text, "P29 (RATIFICADA, vinculante)", "")
    with pytest.raises(ValueError, match="does not cite P29 with state RATIFICADA"):
        assert_pillar_cited_with_state(candidate, "P29", "RATIFICADA")


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


def test_relevo_conjunction_outside_step_nine_fails(
    fixture_relevo_template: str,
) -> None:
    candidate = mutate_once(
        fixture_relevo_template,
        "9. Contexto y relevo:",
        "8. Contexto previo: LAS TRES condiciones A LA VEZ.\n\n9. Contexto y relevo:",
    )
    candidate = mutate_once(
        candidate,
        "LAS TRES\n   condiciones A LA VEZ: ",
        "se cumplen: ",
    )
    with pytest.raises(ValueError, match="all three conditions together"):
        assert_relevo_requires_three_conditions(candidate)


def test_relevo_without_go_per_jump_fails(fixture_relevo_template: str) -> None:
    candidate = mutate_once(
        fixture_relevo_template,
        "GO nuevo, re-verificado con `user_msgs.py`",
        "no se requiere GO",
    )
    with pytest.raises(ValueError, match="GO per jump"):
        assert_relevo_requires_three_conditions(candidate)


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


def extract_primera_accion_block(text: str) -> str:
    """Extract ARRANQUE step 3b without accepting evidence from other steps.

    Before: ``text`` is a complete ARRANQUE template with its marker header.
    During: cut the body from the ``3b.`` header up to the next ``4.`` step.
    After: return the raw 3b block, or an empty string when it is absent.
    """
    header = HEADER_RE.search(text)
    if header is None:
        raise ValueError("template is missing marker header")
    body = text[header.end() :]
    start = body.find("3b. PRIMERA ACCION tras el ACTIVO:")
    if start < 0:
        return ""
    end = body.find("\n4.", start)
    return body[start:] if end < 0 else body[start:end]


def assert_primera_accion_before_latido(text: str) -> None:
    """Require the imperative first action between ARRANQUE steps 3 and 4.

    Before: ``text`` is a complete ARRANQUE template with its marker header.
    During: locate steps 3, 3b and 4 in the raw body, then normalize the 3b
    block by whitespace and check its three literals.
    After: return silently only when 3b sits strictly between steps 3 and 4 and
    keeps the first-action, before-the-heartbeat and not-a-trigger clauses;
    otherwise raise ``ValueError`` naming the violated invariant.
    """
    header = HEADER_RE.search(text)
    if header is None:
        raise ValueError("template is missing marker header")
    body = text[header.end() :]
    start_three = body.find("3. Objetivo propio:")
    start_three_b = body.find("3b. PRIMERA ACCION tras el ACTIVO:")
    start_four = body.find("\n4. Procedimiento de ticket:")
    if min(start_three, start_three_b, start_four) < 0:
        raise ValueError("arranque steps 3, 3b and 4 must all be present")
    if not start_three < start_three_b < start_four:
        raise ValueError("step 3b must sit after step 3 and before step 4")
    normalized = " ".join(extract_primera_accion_block(text).split())
    for literal in (
        "PRIMERA ACCION tras el ACTIVO",
        "ANTES de crear el latido",
        "NO es disparador",
    ):
        if literal not in normalized:
            raise ValueError(f"step 3b is missing literal: {literal}")


def test_real_arranque_primera_accion_before_latido() -> None:
    """Pin the imperative first action between steps 3 and 4 of ARRANQUE."""
    assert_primera_accion_before_latido(TEMPLATE_PATHS[1].read_text(encoding="utf-8"))


def assert_first_steps_order_objetivo_accion_latido(text: str) -> None:
    """Require the declared first-steps order in ARRANQUE step 5.

    Before: ``text`` is a complete ARRANQUE template with its marker header.
    During: normalize the body by whitespace and look for the declared order
    literal, keeping the P24, P6 and go-message requirements of the step.
    After: return silently when the order and every preserved element appear;
    otherwise raise ``ValueError`` naming the missing element.
    """
    header = HEADER_RE.search(text)
    if header is None:
        raise ValueError("template is missing marker header")
    normalized = " ".join(text[header.end() :].split())
    required = (
        "objetivo con C0 y P medidos, primera accion, y despues el latido propio",
        "P24 (RATIFICADA, vinculante)",
        "P6 (RATIFICADA, vinculante)",
        "{{GO_MENSAJE_ID}}",
    )
    for fragment in required:
        if fragment not in normalized:
            raise ValueError(f"step 5 is missing element: {fragment}")


def test_real_arranque_first_steps_order_objetivo_accion_latido() -> None:
    """Pin the declared objetivo/accion/latido order in ARRANQUE step 5."""
    assert_first_steps_order_objetivo_accion_latido(
        TEMPLATE_PATHS[1].read_text(encoding="utf-8")
    )


@pytest.mark.parametrize("pillar", ["P8", "P9"])
def test_real_templates_cite_p8_p9_with_its_real_state(pillar: str) -> None:
    """Require P8 and P9 cited with their real canon state in both templates.

    Before: both real templates and the real canon index exist on disk.
    During: read the pillar state from the canon and demand exactly one
    citation of that pillar with that state in each template body.
    After: return silently for the matching state; otherwise propagate the
    ``ValueError`` from the shared citation helper.
    """
    canon_text = CANON_PATH.read_text(encoding="utf-8")
    state = read_pillar_state(canon_text, pillar)
    for path in TEMPLATE_PATHS:
        assert_pillar_cited_with_state(path.read_text(encoding="utf-8"), pillar, state)
