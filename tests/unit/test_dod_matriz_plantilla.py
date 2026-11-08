"""Contract tests for the DoD matrix template.

Before: the real matrix template and malformed candidate text are available.
During: parse the two six-column tables and exercise every admission invariant.
After: valid content is represented as rows and every listed mutation raises a
specific ``ValueError``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


TEMPLATE_PATH = (
    Path(__file__).parents[2]
    / "prompts"
    / "vuelo_builder_templates"
    / "dod_matriz_plantilla.md"
)
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


def _validate_markers(text: str) -> None:
    headers = list(MARKER_HEADER_RE.finditer(text))
    if len(headers) != 1:
        raise ValueError("expected exactly one marker declaration header")
    declared = set(ANY_MARKER_RE.findall(headers[0].group("body")))
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
            continue
        rows: list[str] = []
        cursor = index + 2
        while cursor < len(lines) and lines[cursor].strip().startswith("|"):
            rows.append(lines[cursor].strip())
            cursor += 1
        tables.append(rows)
    return tables


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
    if not row["id"]:
        raise ValueError("matrix row id is empty")
    if not row["conteo esperado"]:
        raise ValueError("expected count is empty")
    positive = row["control positivo"]
    if not positive:
        raise ValueError("positive control is empty")
    if positive.lower().startswith("n/a") and not re.fullmatch(
        r"n/a:\s*\S.*", positive, re.IGNORECASE
    ):
        raise ValueError("n/a positive control requires a non-empty reason")
    return row


def parse_matriz_table(text: str) -> list[dict[str, str]]:
    """Parse all recognized six-column matrix tables and validate their rows."""
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
    assert len(rows) >= 3


def test_real_example_has_two_rows_and_valid_na_reason() -> None:
    rows = parse_matriz_table(TEMPLATE_PATH.read_text(encoding="utf-8"))
    assert {row["id"] for row in rows} == {"{{CLAUSULA_ID}}", "b-01", "b-02"}
    assert next(row for row in rows if row["id"] == "b-02")[
        "control positivo"
    ].startswith("n/a: ")


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
