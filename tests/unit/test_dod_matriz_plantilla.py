"""Contract tests exclusively for the DoD matrix template and its fixtures.

Before: the real matrix template and malformed candidate text are available.
During: parse the two six-column tables and exercise every admission invariant.
After: valid content is represented as rows and every listed mutation raises a
specific ``ValueError``. This parser is not reusable for real backlog fichas:
it requires the template-only marker declaration that real backlog rows lack.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pytest


TEMPLATE_PATH = (
    Path(__file__).parents[2]
    / "prompts"
    / "vuelo_builder_templates"
    / "dod_matriz_plantilla.md"
)
BACKLOG_ADMIT_PATH = Path(__file__).parents[2] / "prompts" / "backlog_admit.md"
VUELO_PILARES_PATH = (
    Path(__file__).parents[2] / ".agent" / "rules" / "common" / "vuelo_pilares.md"
)
MATRIX_SECTION_HEADING = "## Matriz de DoD para fichas de mecanismo"
MATRIX_COLUMNS_SENTENCE = (
    "La tabla tiene exactamente estas seis columnas:\n"
    "`id | texto literal | comprobacion | ambito | conteo esperado | control positivo`."
)
NON_RETROACTIVITY_PARAGRAPH = (
    "Esta exigencia no es retroactiva: aplica desde la integracion de WOT-2026-160i,\n"
    "sin reabrir ni exigir la matriz a fichas admitidas antes."
)
AMBIGUOUS_RETROACTIVITY_PHRASE = "desde WOT-2026-160i en adelante"
MARKERS = (
    "CLAUSULA_ID",
    "CLAUSULA_TEXTO",
    "COMPROBACION",
    "AMBITO",
    "CONTEO_ESPERADO",
    "CONTROL_POSITIVO",
)
MARKER_HEADER_RE = re.compile(r"<!-- Marcadores declarados: (?P<body>.*?) -->")
ANY_MARKER_RE = re.compile(r"\{\{([^{}]+)\}\}")
ROW_RE = re.compile(r"^\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|$")
HEADER = "| id | texto literal | comprobacion | ambito | conteo esperado | control positivo |"
SEPARATOR = "|---|---|---|---|---|---|"


def mutate_once(source: str, old: str, new: str) -> str:
    """Replace one uniquely occurring fragment and reject ambiguous fixtures."""
    assert source.count(old) == 1, f"fragment is not unique: {old!r}"
    return source.replace(old, new, 1)


def _pilar_phrase(pilar_id: str) -> str:
    """Extract a pilar rule phrase from the live markdown table."""
    for line in VUELO_PILARES_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = line.strip().split("|")[1:-1]
        if len(cells) >= 2 and cells[0].strip() == pilar_id:
            return cells[1].strip()
    raise ValueError(f"pilar not found: {pilar_id}")


def assert_matrix_section_present_once(text: str) -> None:
    """Require exactly one matrix-section heading."""
    if text.count(MATRIX_SECTION_HEADING) != 1:
        raise ValueError("matrix section heading must appear exactly once")


def assert_cites_p28_p29_and_template_path(text: str) -> None:
    """Require both pilar citations and the canonical template path."""
    if "P28" not in text:
        raise ValueError("backlog_admit.md is missing P28 citation")
    if "P29" not in text:
        raise ValueError("backlog_admit.md is missing P29 citation")
    if "prompts/vuelo_builder_templates/dod_matriz_plantilla.md" not in text:
        raise ValueError("backlog_admit.md is missing matrix template path")


def assert_does_not_redeclare_pilar_rule(text: str, phrase: str) -> None:
    """Reject copying a live pilar rule phrase into the admission prompt."""
    if phrase in text:
        raise ValueError(
            "backlog_admit.md redeclara una regla de pilar en vez de citarla"
        )


def assert_non_retroactivity_paragraph_is_present_and_unambiguous(
    text: str,
) -> None:
    """Require the exact, post-integration non-retroactivity clause."""
    if text.count(NON_RETROACTIVITY_PARAGRAPH) != 1:
        raise ValueError("non-retroactivity paragraph must appear exactly once")
    if "retroactiv" not in text:
        raise ValueError("non-retroactivity paragraph is missing retroactivity wording")
    if "integracion de WOT-2026-160i" not in text:
        raise ValueError("non-retroactivity paragraph is missing integration wording")
    if AMBIGUOUS_RETROACTIVITY_PHRASE in text:
        raise ValueError("non-retroactivity paragraph uses an ambiguous formula")


def _section_text(text: str, heading: str) -> str:
    """Return one markdown section, bounded by the next level-two heading."""
    start = text.find(heading)
    if start < 0:
        raise ValueError(f"section heading not found: {heading}")
    next_heading = text.find("\n## ", start + len(heading))
    return text[start:] if next_heading < 0 else text[start:next_heading]


def _validate_markers(text: str) -> None:
    headers = list(MARKER_HEADER_RE.finditer(text))
    if len(headers) != 1:
        raise ValueError("expected exactly one marker declaration header")
    declared_tokens = ANY_MARKER_RE.findall(headers[0].group("body"))
    declared = set(declared_tokens)
    for marker, count in Counter(declared_tokens).items():
        if count > 1:
            raise ValueError(f"marker declaration duplicates {marker}")
    body = text[: headers[0].start()] + text[headers[0].end() :]
    used = set(ANY_MARKER_RE.findall(body))
    if declared != set(MARKERS):
        raise ValueError("marker declaration does not contain the required set")
    if used != declared:
        missing = sorted(declared - used)
        extra = sorted(used - declared)
        raise ValueError(
            f"marker declaration/body mismatch: missing={missing}, extra={extra}"
        )


def _table_rows(lines: list[str]) -> list[list[str]]:
    """Collect data rows from every exact six-column table header."""
    tables: list[list[str]] = []
    for index, line in enumerate(lines):
        if line.strip() != HEADER:
            continue
        if index + 1 >= len(lines) or lines[index + 1].strip() != SEPARATOR:
            raise ValueError("matrix table header without a valid separator")
        rows: list[str] = []
        cursor = index + 2
        while cursor < len(lines) and lines[cursor].strip().startswith("|"):
            rows.append(lines[cursor].strip())
            cursor += 1
        tables.append(rows)
    return tables


_DIGIT_RE = re.compile(r"\d")
_NA_VARIANT_RE = re.compile(
    r"^(?:n\s*[/.]\s*a\.?(?![A-Za-z0-9])|n\s*a(?=\s*:|$))",
    re.IGNORECASE,
)
_CANONICAL_NA_WITH_REASON_RE = re.compile(r"^n/a:\s*(.*)$", re.IGNORECASE)
_EXPECTED_COLUMN_MARKERS = {
    "id": "{{CLAUSULA_ID}}",
    "texto literal": "{{CLAUSULA_TEXTO}}",
    "comprobacion": "{{COMPROBACION}}",
    "ambito": "{{AMBITO}}",
    "conteo esperado": "{{CONTEO_ESPERADO}}",
    "control positivo": "{{CONTROL_POSITIVO}}",
}


def _is_marker_placeholder_row(row: dict[str, str]) -> bool:
    """Identify the literal six-marker row with each column's own marker."""
    return all(
        row[column] == marker for column, marker in _EXPECTED_COLUMN_MARKERS.items()
    )


def _validate_required_row_fields(row: dict[str, str]) -> None:
    """Reject empty cells required by every matrix row."""
    if not row["id"]:
        raise ValueError("matrix row id is empty")
    if not row["texto literal"]:
        raise ValueError("matrix row texto literal is empty")
    if not row["comprobacion"]:
        raise ValueError("matrix row comprobacion is empty")
    if not row["ambito"]:
        raise ValueError("matrix row ambito is empty")
    if not row["conteo esperado"]:
        raise ValueError("expected count is empty")
    if not row["control positivo"]:
        raise ValueError("positive control is empty")


def _validate_positive_control(positive: str) -> None:
    """Validate the canonical n/a spelling and its two-word reason."""
    if not _NA_VARIANT_RE.match(positive):
        return
    reason_match = _CANONICAL_NA_WITH_REASON_RE.match(positive)
    if reason_match is None:
        raise ValueError(
            "positive control n/a variant requires a non-empty, multi-word reason"
        )
    words = reason_match.group(1).split()
    if len(words) < 2:
        raise ValueError("n/a positive control reason requires at least two words")


def _validate_real_row(row: dict[str, str], columns: tuple[str, ...]) -> None:
    """Validate semantic constraints that apply to populated rows."""
    for column in columns:
        if ANY_MARKER_RE.search(row[column]):
            raise ValueError(f"{column} contains an unfilled marker token")
    for column in columns:
        if column == "control positivo":
            continue
        if _NA_VARIANT_RE.match(row[column]):
            raise ValueError(
                f"{column} must not use n/a; n/a is reserved for control positivo"
            )
    if not _DIGIT_RE.search(row["conteo esperado"]):
        raise ValueError("expected count must contain a digit")
    _validate_positive_control(row["control positivo"])


def _parse_row(raw: str) -> dict[str, str]:
    """Parse and validate one anchored six-column row."""
    match = ROW_RE.fullmatch(raw)
    if not match:
        raise ValueError("malformed matrix row: expected exactly six columns")
    values = [value.strip() for value in match.groups()]
    columns = (
        "id",
        "texto literal",
        "comprobacion",
        "ambito",
        "conteo esperado",
        "control positivo",
    )
    row = dict(zip(columns, values, strict=True))
    _validate_required_row_fields(row)

    if _is_marker_placeholder_row(row):
        return row
    _validate_real_row(row, columns)
    return row


def parse_matriz_table(text: str) -> list[dict[str, str]]:
    """Parse only the template's marker-declared tables and their fixtures.

    This is not a parser for real backlog fichas, which do not have the
    template-only ``Marcadores declarados`` header.
    """
    lines = text.splitlines()
    tables = _table_rows(lines)
    if not tables:
        raise ValueError("no matrix table found")
    _validate_markers(text)

    parsed: list[dict[str, str]] = []
    seen: set[str] = set()
    for rows in tables:
        for raw in rows:
            row = _parse_row(raw)
            if row["id"] in seen:
                raise ValueError(f"matrix row id is duplicated: {row['id']}")
            seen.add(row["id"])
            parsed.append(row)
    return parsed


def _fixture(row: str = "| id | texto | check | scope | 1 | yes |") -> str:
    return (
        "<!-- Marcadores declarados: {{CLAUSULA_ID}} {{CLAUSULA_TEXTO}} "
        "{{COMPROBACION}} {{AMBITO}} {{CONTEO_ESPERADO}} {{CONTROL_POSITIVO}} -->\n"
        f"{HEADER}\n{SEPARATOR}\n"
        "| {{CLAUSULA_ID}} | {{CLAUSULA_TEXTO}} | {{COMPROBACION}} | "
        "{{AMBITO}} | {{CONTEO_ESPERADO}} | {{CONTROL_POSITIVO}} |\n"
        f"{row}\n"
    )


def test_real_template_tables_parse_with_six_columns() -> None:
    rows = parse_matriz_table(TEMPLATE_PATH.read_text(encoding="utf-8"))
    assert rows[0]["id"] == "{{CLAUSULA_ID}}"


def test_real_example_has_two_rows_and_valid_na_reason() -> None:
    rows = parse_matriz_table(TEMPLATE_PATH.read_text(encoding="utf-8"))
    assert {row["id"] for row in rows} == {"{{CLAUSULA_ID}}", "b-01", "b-02"}
    assert next(row for row in rows if row["id"] == "b-02")[
        "control positivo"
    ].startswith("n/a: ")


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (
            "| id |  | check | scope | 1 | yes |",
            "matrix row texto literal is empty",
        ),
        (
            "| id | texto |  | scope | 1 | yes |",
            "matrix row comprobacion is empty",
        ),
        (
            "| id | texto | check |  | 1 | yes |",
            "matrix row ambito is empty",
        ),
        (
            "| id | texto | check | scope | varios | yes |",
            "expected count must contain a digit",
        ),
        (
            "| id | texto | check | n/a - no aplica | 1 | yes |",
            "ambito must not use n/a; n/a is reserved for control positivo",
        ),
        (
            "| id | texto | check | scope | 1 | n/a: x |",
            "n/a positive control reason requires at least two words",
        ),
    ],
)
def test_new_row_validation_mutants_are_rejected(row: str, message: str) -> None:
    """Each newly required non-empty or semantic field has a live rejection."""
    with pytest.raises(ValueError, match=re.escape(message)):
        parse_matriz_table(_fixture(row))


def test_bare_na_without_slash_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="positive control n/a variant requires a non-empty, multi-word reason",
    ):
        parse_matriz_table(_fixture("| id | texto | check | scope | 1 | NA |"))


def test_bare_na_with_period_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="positive control n/a variant requires a non-empty, multi-word reason",
    ):
        parse_matriz_table(_fixture("| id | texto | check | scope | 1 | N.A |"))


@pytest.mark.parametrize(
    ("name", "row", "message"),
    [
        ("empty_id", "|  | texto | check | scope | 1 | yes |", "id is empty"),
        (
            "duplicate_id",
            "| id | texto | check | scope | 1 | yes |\n| id | otro | check | scope | 1 | yes |",
            "duplicated",
        ),
        (
            "empty_positive",
            "| id | texto | check | scope | 1 |  |",
            "positive control is empty",
        ),
        ("bare_na", "| id | texto | check | scope | 1 | n/a |", "requires"),
        ("empty_na_reason", "| id | texto | check | scope | 1 | n/a:   |", "requires"),
        (
            "empty_count",
            "| id | texto | check | scope |  | yes |",
            "expected count is empty",
        ),
        (
            "internal_pipe",
            "| id | texto con | interno | check | scope | 1 | yes |",
            "malformed",
        ),
    ],
)
def test_each_row_mutant_is_rejected(name: str, row: str, message: str) -> None:
    """Every row-level admission defect has an explicit failure branch."""
    del name
    with pytest.raises(ValueError, match=message):
        parse_matriz_table(_fixture(row))


def test_uppercase_na_bare_is_rejected() -> None:
    with pytest.raises(ValueError, match="requires"):
        parse_matriz_table(_fixture("| id | texto | check | scope | 1 | N/A |"))


def test_uppercase_na_empty_reason_is_rejected() -> None:
    with pytest.raises(ValueError, match="requires"):
        parse_matriz_table(_fixture("| id | texto | check | scope | 1 | N/A:   |"))


def test_na_without_colon_is_rejected() -> None:
    with pytest.raises(ValueError, match="requires"):
        parse_matriz_table(
            _fixture("| id | texto | check | scope | 1 | n/a sin dos puntos |")
        )


@pytest.mark.parametrize(
    "positive",
    ["N.A: x", "NA: una cosa", "N.A.: x y", "n / a: x y"],
)
def test_noncanonical_na_variants_with_reasons_are_rejected(positive: str) -> None:
    with pytest.raises(ValueError, match="positive control n/a variant"):
        parse_matriz_table(_fixture(f"| id | texto | check | scope | 1 | {positive} |"))


@pytest.mark.parametrize(
    "row",
    [
        "| id | texto | check | Navegacion | 1 | yes |",
        "| id | texto | check | name | 1 | yes |",
        "| id | texto | check | National | 1 | yes |",
        "| id | texto | check | scope | 1 | Nada cambia al ejecutar el control |",
        "| id | texto | check | scope | 1 | name of test: passed |",
        "| id | texto | check | scope | 1 nadie | yes |",
    ],
)
def test_words_starting_with_na_like_prefixes_are_not_falsely_rejected(
    row: str,
) -> None:
    parse_matriz_table(_fixture(row))


@pytest.mark.parametrize(
    "positive",
    ["na: dos palabras", "n a: x y", "NA", "n/a demora del gate"],
)
def test_more_noncanonical_na_variants_are_rejected(positive: str) -> None:
    with pytest.raises(ValueError, match="positive control n/a variant"):
        parse_matriz_table(_fixture(f"| id | texto | check | scope | 1 | {positive} |"))


def test_duplicate_fixture_uses_mutate_once() -> None:
    source = _fixture()
    candidate = mutate_once(
        source,
        "| id | texto | check | scope | 1 | yes |",
        "| id | texto | check | scope | 1 | yes |\n| id | otro | check | scope | 1 | yes |",
    )
    with pytest.raises(ValueError, match="duplicated"):
        parse_matriz_table(candidate)


def test_no_table_is_rejected() -> None:
    with pytest.raises(ValueError, match="no matrix table"):
        parse_matriz_table("plain text")


def test_consistent_five_marker_template_fails_required_set() -> None:
    text = (
        "<!-- Marcadores declarados: {{CLAUSULA_ID}} {{CLAUSULA_TEXTO}} "
        "{{COMPROBACION}} {{AMBITO}} {{CONTEO_ESPERADO}} -->\n"
        f"{HEADER}\n{SEPARATOR}\n"
        "| {{CLAUSULA_ID}} | {{CLAUSULA_TEXTO}} | {{COMPROBACION}} | "
        "{{AMBITO}} | {{CONTEO_ESPERADO}} | yes |\n"
    )
    with pytest.raises(ValueError, match="does not contain the required set"):
        parse_matriz_table(text)


def test_mixed_row_with_stray_marker_token_is_rejected() -> None:
    with pytest.raises(ValueError, match="unfilled marker token"):
        parse_matriz_table(
            _fixture("| id | texto | check | scope | varios | {{CONTROL_POSITIVO}} |")
        )


def test_header_without_separator_is_not_recognized_as_table() -> None:
    text = (
        "<!-- Marcadores declarados: {{CLAUSULA_ID}} {{CLAUSULA_TEXTO}} "
        "{{COMPROBACION}} {{AMBITO}} {{CONTEO_ESPERADO}} {{CONTROL_POSITIVO}} -->\n"
        f"{HEADER}\n"
        "| id | texto | check | scope | 1 | yes |\n"
    )
    with pytest.raises(
        ValueError, match="matrix table header without a valid separator"
    ):
        parse_matriz_table(text)


def test_second_table_with_malformed_separator_is_rejected() -> None:
    text = (
        _fixture()
        + "\n"
        + HEADER
        + "\n|---|---|---|---|---|\n"
        + "| id | texto | check | scope | 1 | yes |\n"
    )
    with pytest.raises(
        ValueError, match="matrix table header without a valid separator"
    ):
        parse_matriz_table(text)


def test_declared_marker_unused_is_rejected() -> None:
    source = _fixture()
    marker_row = (
        "| {{CLAUSULA_ID}} | {{CLAUSULA_TEXTO}} | {{COMPROBACION}} | "
        "{{AMBITO}} | {{CONTEO_ESPERADO}} | {{CONTROL_POSITIVO}} |"
    )
    candidate = mutate_once(
        source,
        marker_row,
        "| {{CLAUSULA_ID}} | {{CLAUSULA_TEXTO}} | {{COMPROBACION}} | {{AMBITO}} | {{CONTEO_ESPERADO}} | yes |",
    )
    with pytest.raises(ValueError, match="mismatch"):
        parse_matriz_table(candidate)


def test_duplicate_declared_marker_is_rejected() -> None:
    source = _fixture()
    candidate = mutate_once(
        source,
        "{{CLAUSULA_ID}} {{CLAUSULA_TEXTO}}",
        "{{CLAUSULA_ID}} {{CLAUSULA_ID}} {{CLAUSULA_TEXTO}}",
    )
    with pytest.raises(ValueError, match="marker declaration duplicates CLAUSULA_ID"):
        parse_matriz_table(candidate)


def test_undeclared_body_marker_is_rejected() -> None:
    source = _fixture()
    marker_row = (
        "| {{CLAUSULA_ID}} | {{CLAUSULA_TEXTO}} | {{COMPROBACION}} | "
        "{{AMBITO}} | {{CONTEO_ESPERADO}} | {{CONTROL_POSITIVO}} |"
    )
    candidate = mutate_once(
        source,
        marker_row,
        "| {{CLAUSULA_ID}} | {{CLAUSULA_TEXTO}} | {{COMPROBACION}} | {{AMBITO}} | {{CONTEO_ESPERADO}} | {{ORPHAN}} |",
    )
    with pytest.raises(ValueError, match="mismatch"):
        parse_matriz_table(candidate)


def test_missing_final_newline_does_not_silence_row_error() -> None:
    source = _fixture("| id | texto | check | scope |  | yes |").rstrip("\n")
    with pytest.raises(ValueError, match="expected count is empty"):
        parse_matriz_table(source)


def test_real_example_control_positive_mutant_has_exactly_one_precheck() -> None:
    source = TEMPLATE_PATH.read_text(encoding="utf-8")
    candidate = mutate_once(
        source, "La prueba real devuelve dos tablas y tres filas", ""
    )
    with pytest.raises(ValueError, match="positive control is empty"):
        parse_matriz_table(candidate)


def test_template_absent_from_live_index_and_router() -> None:
    from scripts.discover_skills import build_catalog, build_router

    catalog_paths = {entry["path"] for entry in build_catalog()["entries"]}
    assert "prompts/dod_matriz_plantilla.md" not in catalog_paths
    assert (
        "prompts/vuelo_builder_templates/dod_matriz_plantilla.md" not in catalog_paths
    )
    assert "dod_matriz_plantilla" not in build_router()


def test_first_level_template_is_discoverable_precheck(tmp_path: Path) -> None:
    from scripts.discover_skills import build_catalog

    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "dod_matriz_plantilla.md").write_text(
        TEMPLATE_PATH.read_text(encoding="utf-8"), encoding="utf-8"
    )
    catalog_paths = {entry["path"] for entry in build_catalog(tmp_path)["entries"]}
    assert "prompts/dod_matriz_plantilla.md" in catalog_paths


def test_backlog_admit_matrix_section_present_exactly_once() -> None:
    assert_matrix_section_present_once(BACKLOG_ADMIT_PATH.read_text(encoding="utf-8"))


def test_backlog_admit_cites_p28_p29_and_template_path() -> None:
    text = BACKLOG_ADMIT_PATH.read_text(encoding="utf-8")
    assert_cites_p28_p29_and_template_path(_section_text(text, MATRIX_SECTION_HEADING))


def test_backlog_admit_does_not_redeclare_p28_rule_text() -> None:
    phrase = _pilar_phrase("P28")
    assert phrase
    assert_does_not_redeclare_pilar_rule(
        BACKLOG_ADMIT_PATH.read_text(encoding="utf-8"), phrase
    )


def test_backlog_admit_does_not_redeclare_p29_rule_text() -> None:
    phrase = _pilar_phrase("P29")
    assert phrase
    assert_does_not_redeclare_pilar_rule(
        BACKLOG_ADMIT_PATH.read_text(encoding="utf-8"), phrase
    )


def test_backlog_admit_section_cites_exact_matrix_columns() -> None:
    text = BACKLOG_ADMIT_PATH.read_text(encoding="utf-8")
    assert MATRIX_COLUMNS_SENTENCE in _section_text(text, MATRIX_SECTION_HEADING)


def test_backlog_admit_mutant_missing_p29_citation_is_rejected() -> None:
    source = BACKLOG_ADMIT_PATH.read_text(encoding="utf-8")
    candidate = mutate_once(source, "P28 y P29", "P28")
    with pytest.raises(ValueError, match="P29"):
        assert_cites_p28_p29_and_template_path(
            _section_text(candidate, MATRIX_SECTION_HEADING)
        )


def test_backlog_admit_mutant_pasting_p28_phrase_is_rejected() -> None:
    source = BACKLOG_ADMIT_PATH.read_text(encoding="utf-8")
    phrase = _pilar_phrase("P28")
    assert phrase not in source
    candidate = source + "\n" + phrase + "\n"
    with pytest.raises(
        ValueError,
        match=r"backlog_admit\.md redeclara una regla de pilar en vez de citarla",
    ):
        assert_does_not_redeclare_pilar_rule(candidate, phrase)


def test_backlog_admit_section_heading_removed_is_rejected() -> None:
    source = BACKLOG_ADMIT_PATH.read_text(encoding="utf-8")
    candidate = mutate_once(source, MATRIX_SECTION_HEADING, "## Otra seccion")
    with pytest.raises(
        ValueError, match="matrix section heading must appear exactly once"
    ):
        assert_matrix_section_present_once(candidate)


def test_backlog_admit_non_retroactivity_paragraph_present_once_and_unambiguous() -> (
    None
):
    assert_non_retroactivity_paragraph_is_present_and_unambiguous(
        BACKLOG_ADMIT_PATH.read_text(encoding="utf-8")
    )
