"""Contract tests for the portable Builder specification template.

Before: the Builder specification template exists at the canonical prompt path
and candidate fixture text is supplied for negative cases.
During: parse marker declarations and validate the template's portable,
operational, DoD, reporting, and authorship invariants.
After: the real template passes every contract; each malformed fixture raises
``ValueError`` with the exact actionable message required by the contract.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


TEMPLATE_PATH = Path(__file__).parents[2] / "prompts" / "builder_spec_plantilla.md"
ABSOLUTE_ROUTE_RE = re.compile(
    r"(?:[A-Za-z]:[\\/]|/home/|/Users/|\\\\[^\\/\s]+[\\/][^\\/\s]+)"
)
CUPO_FIGURE_RE = re.compile(
    r"P\s*>=\s*\d+"
    r"|\d+\s*por ciento"
    r"|cupo[^\n]{0,40}>=\s*\d+"
    r"|\d+\s+(?:unidades?\s+)?de\s+cupo"
)
PROHIBITION_LINE = (
    "PROHIBIDO git commit --no-verify, --no-gpg-sign y cualquier forma de "
    "saltar hooks; si un hook falla, arreglas la causa y lo cuentas."
)
REQUIRED_MARKERS = frozenset(
    {"TICKET_ID", "FICHA_REF", "RAMA", "FLT", "DOD_LITERAL", "MATRIZ_DOD"}
)
UPPER_TOKEN_RE = re.compile(r"\{\{[A-Z_]+\}\}")
ANY_TOKEN_RE = re.compile(r"\{\{[^{}]*\}\}")
VALID_TOKEN_RE = re.compile(r"\{\{[A-Za-z_]*\}\}")
HEADER_RE = re.compile(r"<!-- Marcadores declarados: (.*?) -->")
VERSIONED_TRAILER_RE = re.compile(
    r"Co-Authored-By: Claude\s+[^\s<][^\n<]*<noreply@anthropic\.com>"
)
REQUIRED_MARKER_HEADER = (
    "<!-- Marcadores declarados: {{TICKET_ID}} {{FICHA_REF}} {{RAMA}} "
    "{{FLT}} {{DOD_LITERAL}} {{MATRIZ_DOD}} -->"
)
REQUIRED_MARKER_BODY = (
    "Body: {{TICKET_ID}} {{FICHA_REF}} {{RAMA}} {{FLT}} "
    "{{DOD_LITERAL}} {{MATRIZ_DOD}}\n"
)
RULE_LINES_REQUIRED = (
    "- pre-commit se verifica SIEMPRE sobre la lista EXACTA del diff real "
    "(`git diff --name-only`), nunca una lista mas amplia: una lista mas "
    "amplia puede mutar ficheros ajenos al ticket.",
    "- Si el cambio toca AGENTS.md, el FLT de arriba incluye tambien sus "
    "derivados llms-full.txt y llms.txt (el hook check-llms-full-sync los "
    "regenera y los exige sincronizados).",
    "- No pidas encoding-guard explicito (`scripts/check_encoding_guard.py` "
    "con ficheros como argumento) sobre ficheros .txt generados: "
    "GLOB_PATTERNS no los cubre y el modo explicito da una falsa alarma.",
    "- No copies cifras de cupo ni otras cifras de estado de la fuente al "
    "entregable: remite siempre a la fuente unica, nunca las transcribas.",
    "Un solo informe por hito, con estos campos fijos, en este orden exacto:",
    "Pega aqui el DoD LITERAL completo de la fila (sin resumir ni parafrasear):",
)


def _first_non_empty_line(text: str) -> str:
    """Return the first line that is not the empty string.

    Before: ``text`` is candidate template content split by ``\\n``.
    During: scan lines in order, skipping only truly empty lines (a BOM or
    any other non-empty content still counts and is returned, never tolerated
    as blank).
    After: return the first non-empty line, or ``""`` if every line is empty.
    """
    for line in text.split("\n"):
        if line != "":
            return line
    return ""


def parse_template(text: str) -> tuple[set[str], set[str]]:
    """Parse and validate declared and used template markers.

    Before: ``text`` is candidate UTF-8 Markdown for the Builder template.
    During: validate the first-line prohibition, portability, marker header,
    balanced braces, marker syntax, and declaration/body equality in order. A
    marker token containing a digit or other non-letter character is reported
    as unbalanced marker braces (checked first), never malformed marker
    (checked later), because VALID_TOKEN_RE only recognizes letters and
    underscores as a marker's shape.
    After: return the declared and used marker sets, or raise ``ValueError``
    with the first violated contract message.
    """
    if _first_non_empty_line(text) != PROHIBITION_LINE:
        raise ValueError("first line does not forbid --no-verify")
    if ABSOLUTE_ROUTE_RE.search(text):
        raise ValueError("template contains an absolute route")
    header = HEADER_RE.search(text)
    if header is None:
        raise ValueError("template is missing marker header")
    declared = _parse_declared_markers(header)
    unbalanced = VALID_TOKEN_RE.sub("", text)
    if "{" in unbalanced or "}" in unbalanced:
        raise ValueError("unbalanced marker braces")
    body_text = text[header.end() :]
    all_tokens = set(ANY_TOKEN_RE.findall(body_text))
    if not all_tokens:
        raise ValueError("template has no markers")
    invalid = all_tokens - set(UPPER_TOKEN_RE.findall(text))
    if invalid:
        raise ValueError("template contains malformed marker")
    used = {token.strip("{}") for token in UPPER_TOKEN_RE.findall(body_text)}
    if declared - used:
        raise ValueError("declared marker is unused")
    if used - declared:
        raise ValueError("body marker is undeclared")
    return declared, used


def _parse_declared_markers(header: re.Match[str]) -> set[str]:
    """Extract and validate the declared marker set from a header match.

    Before: ``header`` is a successful ``HEADER_RE`` match.
    During: split the declared-marker list and check it is non-empty and
    equal to the required set.
    After: return the declared marker set, or raise ``ValueError`` naming the
    first violated invariant.
    """
    tokens = header.group(1).split()
    for token in tokens:
        if not UPPER_TOKEN_RE.fullmatch(token):
            raise ValueError("declared marker is missing its braces")
    declared = {token.strip("{}") for token in tokens}
    if not declared:
        raise ValueError("template declares no markers")
    if declared != REQUIRED_MARKERS:
        raise ValueError("template marker set does not match the required set")
    return declared


def mutate_once(source: str, old: str, new: str) -> str:
    """Apply one unique fixture mutation.

    Before: ``source`` contains exactly one copy of ``old``.
    During: assert uniqueness and replace that one fragment.
    After: return the mutated source, or fail the test if the fixture drifted.
    """
    assert source.count(old) == 1, f"fixture fragment is not unique: {old!r}"
    return source.replace(old, new)


def assert_mentions_exact_diff_precommit(text: str) -> None:
    """Require the exact-diff pre-commit instruction.

    Before: ``text`` is a candidate Builder specification.
    During: search for the literal exact-diff fragment.
    After: return silently when present; otherwise raise the contract error.
    """
    if "lista EXACTA del diff real" not in text:
        raise ValueError("missing exact-diff pre-commit instruction")


def assert_mentions_llms_derivatives_in_flt(text: str) -> None:
    """Require the AGENTS-derived llms files in the FLT rule.

    Before: ``text`` is a candidate Builder specification.
    During: check the three required literal references together.
    After: return silently when all are present; otherwise raise the contract
    error.
    """
    if not all(
        fragment in text for fragment in ("llms-full.txt", "llms.txt", "AGENTS.md")
    ):
        raise ValueError("missing llms derivatives instruction")


def assert_forbids_explicit_encoding_guard_on_txt(text: str) -> None:
    """Require a same-line prohibition for explicit encoding-guard on txt.

    Before: ``text`` is a candidate Builder specification.
    During: inspect every encoding-guard line for one of the allowed negative
    phrases.
    After: return silently when the prohibition exists and is scoped correctly;
    otherwise raise the exact contract error.
    """
    lines = text.splitlines()
    guard_lines = [line for line in lines if "encoding-guard" in line.lower()]
    if not guard_lines:
        raise ValueError("missing encoding-guard prohibition")
    negations = ("No pidas", "no pidas", "No exijas", "no exijas", "nunca")
    if any(not any(negation in line for negation in negations) for line in guard_lines):
        raise ValueError("encoding-guard mentioned without prohibition")


def assert_forbids_copying_quota_figures_instruction(text: str) -> None:
    """Require the single-source instruction for quota figures.

    Before: ``text`` is a candidate Builder specification.
    During: search for the literal source-of-truth wording.
    After: return silently when present; otherwise raise the contract error.
    """
    if "remite siempre a la fuente unica" not in text:
        raise ValueError("missing quota-copy prohibition instruction")


def assert_no_cupo_figures(text: str) -> None:
    """Reject embedded quota figures in a Builder specification.

    Before: ``text`` is a candidate Builder specification.
    During: scan it with the canonical cupo figure regex.
    After: return silently when no figure matches; otherwise raise the contract
    error.
    """
    if CUPO_FIGURE_RE.findall(text):
        raise ValueError("template contains cupo figures")


def assert_rule_lines_present(text: str) -> None:
    """Require each hard-rule line verbatim, not a loose fragment of it.

    Before: ``text`` is a candidate Builder specification.
    During: check every required rule line is present byte-for-byte.
    After: return silently when all are present; otherwise raise naming the
    first missing line's leading words.
    """
    for line in RULE_LINES_REQUIRED:
        if line not in text:
            raise ValueError(f"missing exact rule line starting: {line[:30]!r}")


def assert_has_dod_literal_and_matrix_sections(text: str) -> None:
    """Require both DoD markers inside the dedicated section.

    Before: ``text`` is a candidate Builder specification.
    During: bound the DoD section at the next level-two heading and inspect its
    marker placement.
    After: return silently when both markers are inside; otherwise raise the
    exact contract error.
    """
    heading = "## DoD LITERAL y Matriz DoD"
    section_start = text.find(heading)
    if section_start < 0:
        raise ValueError("missing DoD literal and matrix section")
    next_heading = text.find("\n## ", section_start + len(heading))
    section = (
        text[section_start:] if next_heading < 0 else text[section_start:next_heading]
    )
    if "{{DOD_LITERAL}}" not in section or "{{MATRIZ_DOD}}" not in section:
        raise ValueError("DoD literal or matrix marker outside its section")


def assert_informe_unico_fields_fixed_and_ordered(text: str) -> None:
    """Require the seven Informe UNICO fields in their fixed order.

    Before: ``text`` is a candidate Builder specification.
    During: locate the report heading and then find each literal field label in
    strictly increasing order.
    After: return silently when all labels are ordered; otherwise raise the
    exact contract error.
    """
    heading = "## Informe UNICO por hito"
    start = text.find(heading)
    if start < 0:
        raise ValueError("missing informe unico heading")
    fields = (
        "1. Hash",
        "2. Gates (comando exacto, rc literal, hora)",
        "3. Mutantes (precheck de fragmento unico, matados/total, ejecutados DENTRO de la suite)",
        "4. Conteos de grep (patron, universo barrido, conteo medido, control positivo)",
        "5. Decisiones por confirmar",
        "6. Autoria (por fichero: quien escribio que, IM o builder)",
        "7. Matriz DoD (clausula, test citado por nombre, conteo esperado, conteo medido, control positivo)",
    )
    position = start + len(heading)
    for field in fields:
        position = text.find(field, position + 1)
        if position < 0:
            raise ValueError("informe unico fields missing or out of order")


def assert_mentions_pythonioencoding_for_run_and_exit(text: str) -> None:
    """Require UTF-8 console encoding before invoking run_and_exit.

    Before: ``text`` is a candidate Builder specification.
    During: check both required literal fragments.
    After: return silently when both are present; otherwise raise the contract
    error.
    """
    if "PYTHONIOENCODING=utf-8" not in text or "run_and_exit.py" not in text:
        raise ValueError("missing PYTHONIOENCODING instruction")


def assert_mentions_exact_coauthor_trailer(text: str) -> None:
    """Require the exact Claude trailer without a model version.

    Before: ``text`` is a candidate Builder specification.
    During: require the exact trailer, then reject a versioned Claude variant.
    After: return silently only for the exact unversioned trailer; otherwise
    raise the corresponding contract error.
    """
    if VERSIONED_TRAILER_RE.search(text):
        raise ValueError("co-author trailer must not carry a model version")
    if "Co-Authored-By: Claude <noreply@anthropic.com>" not in text:
        raise ValueError("missing exact co-author trailer")


def test_real_template_has_complete_portable_marker_contract() -> None:
    """The real template has a complete, equal declaration/body marker set."""
    declared, used = parse_template(TEMPLATE_PATH.read_text(encoding="utf-8"))
    assert declared == used


def test_real_template_declares_the_required_marker_set() -> None:
    """The real template declares exactly the six required markers."""
    declared, _used = parse_template(TEMPLATE_PATH.read_text(encoding="utf-8"))
    assert declared == REQUIRED_MARKERS


def test_required_marker_removed_from_header_and_body_fails_explicitly() -> None:
    """Removing one marker everywhere is rejected as an incomplete set."""
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    candidate = mutate_once(text, "{{RAMA}} ", "")
    candidate = mutate_once(candidate, "Rama: {{RAMA}}\n", "")
    with pytest.raises(ValueError, match="required set"):
        parse_template(candidate)


def test_real_template_with_digit_in_marker_raises_unbalanced_before_malformed() -> (
    None
):
    """A digit inside a marker is reported as unbalanced braces, not malformed."""
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    candidate = mutate_once(text, "Rama: {{RAMA}}\n", "Rama: {{RAMA2}}\n")
    with pytest.raises(ValueError, match="unbalanced marker braces"):
        parse_template(candidate)


def test_real_template_first_line_forbids_bypass() -> None:
    """The real template starts with the exact hook-bypass prohibition."""
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    assert text.split("\n", 1)[0] == PROHIBITION_LINE


def test_real_template_with_leading_blank_lines_still_parses() -> None:
    """Leading blank lines before the prohibition are tolerated."""
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    candidate = "\n\n" + text
    declared, used = parse_template(candidate)
    assert declared == used == REQUIRED_MARKERS


@pytest.mark.parametrize(
    ("fixture", "old", "new", "reason"),
    [
        (
            f"{PROHIBITION_LINE}\n{REQUIRED_MARKER_HEADER}\n\n{REQUIRED_MARKER_BODY}",
            REQUIRED_MARKER_HEADER,
            "<!-- not a declared header -->",
            "template is missing marker header",
        ),
        (
            f"{PROHIBITION_LINE}\n{REQUIRED_MARKER_HEADER}\n\n{REQUIRED_MARKER_BODY}",
            "{{DOD_LITERAL}} {{MATRIZ_DOD}}\n",
            "{{MATRIZ_DOD}}\n",
            "declared marker is unused",
        ),
        (
            f"{PROHIBITION_LINE}\n{REQUIRED_MARKER_HEADER}\n\n{REQUIRED_MARKER_BODY}",
            "{{MATRIZ_DOD}}\n",
            "{{MATRIZ_DOD}} {{ORPHAN}}\n",
            "body marker is undeclared",
        ),
        (
            f"{PROHIBITION_LINE}\n{REQUIRED_MARKER_HEADER}\n\n# title\n{REQUIRED_MARKER_BODY}",
            "# title",
            r"# C:\Users\alguien\spec.md",
            "template contains an absolute route",
        ),
        (
            f"{PROHIBITION_LINE}\n{REQUIRED_MARKER_HEADER}\n\n{REQUIRED_MARKER_BODY}",
            "{{MATRIZ_DOD}}\n",
            "{{MATRIZ_DOD}\n",
            "unbalanced marker braces",
        ),
        (
            f"{PROHIBITION_LINE}\n{REQUIRED_MARKER_HEADER}\n\n{REQUIRED_MARKER_BODY}",
            REQUIRED_MARKER_BODY,
            "Body: sin marcadores\n",
            "template has no markers",
        ),
    ],
)
def test_template_marker_negative_mutates_one_unique_fragment(
    fixture: str, old: str, new: str, reason: str
) -> None:
    """Each generic marker mutation dies at the intended parser invariant."""
    parse_template(fixture)
    candidate = mutate_once(fixture, old, new)
    with pytest.raises(ValueError, match=reason):
        parse_template(candidate)


def test_empty_marker_header_fails_explicitly() -> None:
    """An empty marker declaration keeps its dedicated error branch."""
    fixture = (
        f"{PROHIBITION_LINE}\n<!-- Marcadores declarados: {{{{ROL}}}} -->\n\n"
        "Body: {{ROL}}\n"
    )
    candidate = mutate_once(fixture, "{{ROL}} -->", " -->")
    with pytest.raises(ValueError, match="declares no markers"):
        parse_template(candidate)


def test_malformed_lowercase_body_marker_fails_explicitly() -> None:
    """A lowercase body marker reaches the malformed-marker branch."""
    fixture = (
        f"{PROHIBITION_LINE}\n"
        "<!-- Marcadores declarados: "
        "{{TICKET_ID}} {{FICHA_REF}} {{RAMA}} {{FLT}} "
        "{{DOD_LITERAL}} {{MATRIZ_DOD}} -->\n\n"
        "Body: {{TICKET_ID}} {{FICHA_REF}} {{RAMA}} {{FLT}} "
        "{{DOD_LITERAL}} {{MATRIZ_DOD}}\n"
        "Body extra: {{rol}}\n"
    )
    with pytest.raises(ValueError, match="malformed marker"):
        parse_template(fixture)


def test_header_marker_without_braces_fails_explicitly() -> None:
    """A declared marker token without braces is rejected."""
    fixture = (
        f"{PROHIBITION_LINE}\n"
        "<!-- Marcadores declarados: TICKET_ID FICHA_REF RAMA FLT "
        "DOD_LITERAL MATRIZ_DOD -->\n\n"
        f"{REQUIRED_MARKER_BODY}"
    )
    with pytest.raises(ValueError, match="missing its braces"):
        parse_template(fixture)


@pytest.mark.parametrize(
    ("source", "old", "new", "reason"),
    [
        (
            TEMPLATE_PATH.read_text(encoding="utf-8"),
            PROHIBITION_LINE,
            "",
            "does not forbid",
        ),
        (
            f"{PROHIBITION_LINE}\n# second\n<!-- Marcadores declarados: {{{{ROL}}}} -->\n\nBody: {{{{ROL}}}}\n",
            PROHIBITION_LINE,
            "# first\n# second\n" + PROHIBITION_LINE,
            "does not forbid",
        ),
    ],
)
def test_template_first_line_negative_mutates_one_unique_fragment(
    source: str, old: str, new: str, reason: str
) -> None:
    """A missing or displaced prohibition is rejected before other checks."""
    candidate = mutate_once(source, old, new)
    with pytest.raises(ValueError, match=reason):
        parse_template(candidate)


def test_real_template_mentions_exact_diff_precommit() -> None:
    """The real template names the exact real diff for pre-commit."""
    assert_mentions_exact_diff_precommit(TEMPLATE_PATH.read_text(encoding="utf-8"))


def test_real_template_has_all_rule_lines_exact() -> None:
    """The real template contains every required hard-rule line verbatim."""
    assert_rule_lines_present(TEMPLATE_PATH.read_text(encoding="utf-8"))


def test_precommit_rule_line_weakened_fails_explicitly() -> None:
    """Removing the pre-commit rule's leading phrase is rejected."""
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    candidate = mutate_once(text, "pre-commit se verifica SIEMPRE sobre la ", "")
    with pytest.raises(ValueError, match="missing exact rule line"):
        assert_rule_lines_present(candidate)


def test_llms_rule_line_weakened_fails_explicitly() -> None:
    """Changing the LLMS derivative rule is rejected."""
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    candidate = mutate_once(
        text,
        "el FLT de arriba incluye tambien sus derivados",
        "no incluyas en el FLT",
    )
    with pytest.raises(ValueError, match="missing exact rule line"):
        assert_rule_lines_present(candidate)


def test_encoding_guard_rule_line_weakened_fails_explicitly() -> None:
    """Shortening the encoding-guard rule is rejected."""
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    old = (
        "- No pidas encoding-guard explicito (`scripts/check_encoding_guard.py` "
        "con ficheros como argumento) sobre ficheros .txt generados: "
        "GLOB_PATTERNS no los cubre y el modo explicito da una falsa alarma."
    )
    candidate = mutate_once(text, old, "- No pidas encoding-guard")
    with pytest.raises(ValueError, match="missing exact rule line"):
        assert_rule_lines_present(candidate)


def test_quota_rule_line_weakened_fails_explicitly() -> None:
    """Removing the quota rule's lead is rejected."""
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    candidate = mutate_once(
        text,
        "No copies cifras de cupo ni otras cifras de estado de la fuente al entregable: ",
        "",
    )
    with pytest.raises(ValueError, match="missing exact rule line"):
        assert_rule_lines_present(candidate)


def test_informe_lead_sentence_missing_fails_explicitly() -> None:
    """Removing the report lead sentence is rejected."""
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    candidate = mutate_once(
        text,
        "Un solo informe por hito, con estos campos fijos, en este orden exacto:",
        "",
    )
    with pytest.raises(ValueError, match="missing exact rule line"):
        assert_rule_lines_present(candidate)


def test_dod_paste_instruction_weakened_fails_explicitly() -> None:
    """Removing the DoD-paste instruction is rejected."""
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    candidate = mutate_once(
        text,
        "Pega aqui el DoD LITERAL completo de la fila (sin resumir ni parafrasear):",
        "",
    )
    with pytest.raises(ValueError, match="missing exact rule line"):
        assert_rule_lines_present(candidate)


def test_precommit_fragment_missing_fails_explicitly() -> None:
    """Removing the exact-diff fragment is rejected."""
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    candidate = mutate_once(text, "lista EXACTA del diff real", "")
    with pytest.raises(ValueError, match="missing exact-diff pre-commit instruction"):
        assert_mentions_exact_diff_precommit(candidate)


def test_real_template_mentions_llms_derivatives_in_flt() -> None:
    """The real template names all AGENTS-derived llms files."""
    assert_mentions_llms_derivatives_in_flt(TEMPLATE_PATH.read_text(encoding="utf-8"))


def test_llms_derivatives_fragment_missing_fails_explicitly() -> None:
    """Removing one derivative name is rejected."""
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    candidate = mutate_once(text, "llms-full.txt", "")
    with pytest.raises(ValueError, match="missing llms derivatives instruction"):
        assert_mentions_llms_derivatives_in_flt(candidate)


def test_real_template_forbids_explicit_encoding_guard_on_txt() -> None:
    """The real template prohibits explicit encoding checks on generated txt."""
    assert_forbids_explicit_encoding_guard_on_txt(
        TEMPLATE_PATH.read_text(encoding="utf-8")
    )


def test_encoding_guard_prohibition_missing_fails_explicitly() -> None:
    """A fixture without encoding-guard wording is rejected."""
    with pytest.raises(ValueError, match="missing encoding-guard prohibition"):
        assert_forbids_explicit_encoding_guard_on_txt("No explicit check here.")


def test_encoding_guard_mentioned_without_prohibition_fails_explicitly() -> None:
    """An unqualified encoding-guard mention is rejected."""
    with pytest.raises(
        ValueError, match="encoding-guard mentioned without prohibition"
    ):
        assert_forbids_explicit_encoding_guard_on_txt("Run encoding-guard on txt.")


def test_real_template_forbids_copying_quota_figures_instruction() -> None:
    """The real template points quota figures to their single source."""
    assert_forbids_copying_quota_figures_instruction(
        TEMPLATE_PATH.read_text(encoding="utf-8")
    )


def test_quota_instruction_missing_fails_explicitly() -> None:
    """Removing the source-of-truth wording is rejected."""
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    candidate = mutate_once(text, "remite siempre a la fuente unica", "")
    with pytest.raises(ValueError, match="missing quota-copy prohibition instruction"):
        assert_forbids_copying_quota_figures_instruction(candidate)


def test_real_template_has_no_embedded_cupo_figures() -> None:
    """The real template carries no numeric cupo threshold."""
    assert_no_cupo_figures(TEMPLATE_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "cupo_text", ["P>=85", "90 por ciento", "cupo de 5h >=90", "90 de cupo"]
)
def test_cupo_figure_fixture_fails_explicitly(cupo_text: str) -> None:
    """Every canonical cupo figure form is rejected."""
    candidate = mutate_once("# Contexto\n", "# Contexto", f"# Contexto {cupo_text}")
    with pytest.raises(ValueError, match="template contains cupo figures"):
        assert_no_cupo_figures(candidate)


def test_real_template_has_dod_literal_and_matrix_sections() -> None:
    """Both DoD markers occur inside the dedicated DoD section."""
    assert_has_dod_literal_and_matrix_sections(
        TEMPLATE_PATH.read_text(encoding="utf-8")
    )


def test_dod_section_header_missing_fails_explicitly() -> None:
    """Removing the DoD heading is rejected."""
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    candidate = mutate_once(text, "## DoD LITERAL y Matriz DoD", "")
    with pytest.raises(ValueError, match="missing DoD literal and matrix section"):
        assert_has_dod_literal_and_matrix_sections(candidate)


def test_matrix_marker_outside_section_fails_explicitly() -> None:
    """A matrix marker moved beyond the next section is rejected."""
    fixture = (
        "## DoD LITERAL y Matriz DoD\n\n{{DOD_LITERAL}}\n\n"
        "## Informe UNICO por hito\n\n{{MATRIZ_DOD}}\n"
    )
    with pytest.raises(
        ValueError, match="DoD literal or matrix marker outside its section"
    ):
        assert_has_dod_literal_and_matrix_sections(fixture)


def test_real_template_informe_unico_fields_fixed_and_ordered() -> None:
    """The real template lists every Informe UNICO field in order."""
    assert_informe_unico_fields_fixed_and_ordered(
        TEMPLATE_PATH.read_text(encoding="utf-8")
    )


def test_informe_unico_heading_missing_fails_explicitly() -> None:
    """The report fields are invalid without their required heading."""
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    candidate = mutate_once(text, "## Informe UNICO por hito", "")
    with pytest.raises(ValueError, match="missing informe unico heading"):
        assert_informe_unico_fields_fixed_and_ordered(candidate)


@pytest.mark.parametrize(
    "absolute_route",
    [
        r"C:\Users\otro\x",
        "/home/otro/x",
        "/Users/otro/x",
        r"\\host\share\x",
    ],
)
def test_real_template_with_each_absolute_route_form_fails_explicitly(
    absolute_route: str,
) -> None:
    """Every ABSOLUTE_ROUTE_RE alternative is rejected on the real template."""
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    candidate = mutate_once(
        text,
        "# Spec de Builder: {{TICKET_ID}}",
        "# Spec de Builder: " + absolute_route + " {{TICKET_ID}}",
    )
    with pytest.raises(ValueError, match="template contains an absolute route"):
        parse_template(candidate)


def test_real_template_with_relative_route_does_not_fail() -> None:
    """A legitimate relative route is not mistaken for an absolute one."""
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    candidate = mutate_once(
        text,
        "# Spec de Builder: {{TICKET_ID}}",
        "# Spec de Builder: scripts/x.py {{TICKET_ID}}",
    )
    parse_template(candidate)


def test_real_template_encoding_guard_negation_removed_fails_explicitly() -> None:
    """Removing the encoding-guard negation from the real template is rejected."""
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    candidate = mutate_once(
        text, "No pidas encoding-guard explicito", "encoding-guard explicito"
    )
    with pytest.raises(
        ValueError, match="encoding-guard mentioned without prohibition"
    ):
        assert_forbids_explicit_encoding_guard_on_txt(candidate)


@pytest.mark.parametrize(
    "field",
    [
        "1. Hash",
        "2. Gates (comando exacto, rc literal, hora)",
        "3. Mutantes (precheck de fragmento unico, matados/total, ejecutados DENTRO de la suite)",
        "4. Conteos de grep (patron, universo barrido, conteo medido, control positivo)",
        "5. Decisiones por confirmar",
        "6. Autoria (por fichero: quien escribio que, IM o builder)",
        "7. Matriz DoD (clausula, test citado por nombre, conteo esperado, conteo medido, control positivo)",
    ],
)
def test_informe_field_missing_fails_explicitly(field: str) -> None:
    """Removing each fixed report field is rejected."""
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    candidate = mutate_once(text, field, "")
    with pytest.raises(
        ValueError, match="informe unico fields missing or out of order"
    ):
        assert_informe_unico_fields_fixed_and_ordered(candidate)


def test_informe_fields_out_of_order_fails_explicitly() -> None:
    """Inverting two report fields is rejected."""
    fixture = (
        "## Informe UNICO por hito\n\n"
        "1. Hash\n"
        "2. Gates (comando exacto, rc literal, hora)\n"
        "3. Mutantes (precheck de fragmento unico, matados/total, ejecutados DENTRO de la suite)\n"
        "4. Conteos de grep (patron, universo barrido, conteo medido, control positivo)\n"
        "5. Decisiones por confirmar\n"
        "6. Autoria (por fichero: quien escribio que, IM o builder)\n"
        "7. Matriz DoD (clausula, test citado por nombre, conteo esperado, conteo medido, control positivo)\n"
    )
    assert_informe_unico_fields_fixed_and_ordered(fixture)
    candidate = mutate_once(
        fixture,
        "1. Hash\n2. Gates (comando exacto, rc literal, hora)",
        "2. Gates (comando exacto, rc literal, hora)\n1. Hash",
    )
    with pytest.raises(
        ValueError, match="informe unico fields missing or out of order"
    ):
        assert_informe_unico_fields_fixed_and_ordered(candidate)


def test_real_template_mentions_pythonioencoding_for_run_and_exit() -> None:
    """The real template fixes console encoding before run_and_exit."""
    assert_mentions_pythonioencoding_for_run_and_exit(
        TEMPLATE_PATH.read_text(encoding="utf-8")
    )


def test_pythonioencoding_fragment_missing_fails_explicitly() -> None:
    """Removing the encoding assignment is rejected."""
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    candidate = mutate_once(text, "PYTHONIOENCODING=utf-8", "")
    with pytest.raises(ValueError, match="missing PYTHONIOENCODING instruction"):
        assert_mentions_pythonioencoding_for_run_and_exit(candidate)


def test_real_template_mentions_exact_coauthor_trailer() -> None:
    """The real template carries the exact unversioned Claude trailer."""
    assert_mentions_exact_coauthor_trailer(TEMPLATE_PATH.read_text(encoding="utf-8"))


def test_coauthor_trailer_versioned_variant_rejected() -> None:
    """A model-versioned Claude trailer is rejected."""
    fixture = "Co-Authored-By: Claude Sonnet <noreply@anthropic.com>"
    with pytest.raises(
        ValueError, match="co-author trailer must not carry a model version"
    ):
        assert_mentions_exact_coauthor_trailer(fixture)


def test_coauthor_trailer_real_incident_variant_rejected() -> None:
    """The two-word version from the incident is rejected on its own."""
    fixture = "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
    with pytest.raises(
        ValueError, match="co-author trailer must not carry a model version"
    ):
        assert_mentions_exact_coauthor_trailer(fixture)


def test_coauthor_trailer_missing_fails_explicitly() -> None:
    """A candidate without the exact trailer is rejected."""
    with pytest.raises(ValueError, match="missing exact co-author trailer"):
        assert_mentions_exact_coauthor_trailer("No trailer.")
