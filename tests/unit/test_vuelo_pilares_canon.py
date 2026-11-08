"""Contract tests for the versioned flight-pillars index.

Before: the repository contains the canonical Markdown index, or a test
fixture supplies a candidate row/text.
During: parse rows and load the small canonical-file contract used by this
ticket; the future F1b validator remains deliberately out of scope.
After: malformed rows/files raise ``ValueError`` with a reason, while the
real index is checked for its basic shape and portability.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


CANON_PATH = (
    Path(__file__).parents[2] / ".agent" / "rules" / "common" / "vuelo_pilares.md"
)
ALLOWED_STATES = {"RATIFICADA", "PILOTO", "NO RATIFICADA", "SUPERADA"}
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
ABSOLUTE_ROUTE_RE = re.compile(
    r"(?:[A-Za-z]:[\\/]|/home/|/Users/|\\\\[^\\/\s]+[\\/][^\\/\s]+)"
)
CUPO_FIGURE_RE = re.compile(
    r"P\s*>=\s*\d+"
    r"|\d+\s*por ciento"
    r"|cupo[^\n]{0,40}>=\s*\d+"
    r"|\d+\s+(?:unidades?\s+)?de\s+cupo"
)

BASE_ROW = (
    "| P0 | Regla de prueba | RATIFICADA | "
    "c38d20f3-796a-4f56-ae3d-50c09952ce25 | fuente.md | mecanismo | coordinadora activa |"
)

P28_MESSAGE_ID = "71ce07a9-cadf-4882-85bb-b408632139ec"
P28_FIXTURE_ROW = (
    "| P28 | Regla de prueba P28 | RATIFICADA | "
    f"{P28_MESSAGE_ID} | fuente.md | mecanismo | coordinadora activa |"
)
P29_FIXTURE_ROW = (
    "| P29 | Regla de prueba P29 | RATIFICADA | "
    f"{P28_MESSAGE_ID} | fuente.md | mecanismo | coordinadora activa |"
)


def parse_row(line: str) -> dict[str, str]:
    """Parse and validate one Markdown table row.

    Before: ``line`` is one candidate Markdown table row.
    During: split the row into its seven cells and validate the state/message
    relationship and the UUID shape.
    After: return named fields, or raise ``ValueError`` identifying the first
    violated invariant.
    """
    cells = [cell.strip() for cell in line.strip().split("|")]
    if cells and cells[0] == "":
        cells.pop(0)
    if cells and cells[-1] == "":
        cells.pop()
    if len(cells) != 7:
        raise ValueError("row must have seven columns")

    pillar, phrase, state, message_id, source, mechanism, ask = cells
    if not state:
        raise ValueError("state is required")
    if state not in ALLOWED_STATES:
        raise ValueError("invalid state")
    if state == "RATIFICADA":
        if not message_id:
            raise ValueError("ratified row requires messageId")
        if not UUID_RE.fullmatch(message_id):
            raise ValueError("messageId must be a UUID")
    elif message_id:
        raise ValueError("only ratified rows may carry messageId")
    return {
        "pillar": pillar,
        "phrase": phrase,
        "state": state,
        "message_id": message_id,
        "source": source,
        "mechanism": mechanism,
        "ask": ask,
    }


def load_canon(text: str) -> list[dict[str, str]]:
    """Load canonical rows with explicit empty/EOF/portability checks.

    Before: ``text`` is the complete file content.
    During: reject an empty file, missing final LF, and machine-absolute paths,
    then parse non-header table rows.
    After: return all parsed rows; malformed input raises ``ValueError``.
    """
    if not text:
        raise ValueError("canonical file is empty")
    if not text.endswith("\n"):
        raise ValueError("canonical file must end with a newline")
    if ABSOLUTE_ROUTE_RE.search(text):
        raise ValueError("canonical file contains an absolute route")
    rows = [
        parse_row(line)
        for line in text.splitlines()
        if line.startswith("| P") and not line.startswith("| Pilar")
    ]
    if not rows:
        raise ValueError("canonical file has no rows")
    return rows


def mutate_once(source: str, old: str, new: str) -> str:
    """Apply one exact fixture mutation, guarding against fragile tests."""
    assert source.count(old) == 1, f"fixture fragment is not unique: {old!r}"
    return source.replace(old, new)


def assert_no_cupo_figures(text: str) -> None:
    """Reject cupo thresholds that belong in the flight state sources.

    Before: ``text`` is the complete canonical pillar index.
    During: scan all text for numeric cupo threshold forms.
    After: return silently when no threshold is embedded; otherwise raise
    ``ValueError`` naming the portability invariant.
    """
    matches = CUPO_FIGURE_RE.findall(text)
    if matches:
        raise ValueError("canonical file contains cupo figures")


def assert_pillar_ratified(text: str, pillar: str, expected_message_id: str) -> None:
    """Require one canon pillar row RATIFICADA with an exact messageId.

    Before: ``text`` is a complete canonical pillar index (real file or
    fixture) and ``pillar`` is a bare id such as ``"P28"``.
    During: locate the row whose first cell is exactly ``pillar`` and parse
    it with the same rules as every other row.
    After: return silently when the row is RATIFICADA with
    ``expected_message_id``; otherwise raise ``ValueError`` naming the gap.
    """
    row_re = re.compile(rf"^\| {re.escape(pillar)} \|.*\|$", re.MULTILINE)
    match = row_re.search(text)
    if match is None:
        raise ValueError(f"pillar {pillar} is missing")
    row = parse_row(match.group(0))
    if row["state"] != "RATIFICADA":
        raise ValueError(f"pillar {pillar} is not RATIFICADA")
    if row["message_id"] != expected_message_id:
        raise ValueError(f"pillar {pillar} messageId mismatch")


def assert_pillar_contains_terms(
    text: str, pillar: str, required_terms: tuple[str, ...]
) -> None:
    """Require every term in ``required_terms`` inside pillar's own phrase.

    Before: ``text`` is a complete canonical pillar index (real file or
    fixture) and ``pillar`` is a bare id such as ``"P28"``.
    During: locate the row and read its phrase cell (second column) only;
    never the other six columns.
    After: return silently when every required term appears in the phrase;
    otherwise raise ``ValueError`` naming the first missing term.
    """
    row_re = re.compile(rf"^\| {re.escape(pillar)} \|.*\|$", re.MULTILINE)
    match = row_re.search(text)
    if match is None:
        raise ValueError(f"pillar {pillar} is missing")
    row = parse_row(match.group(0))
    missing = [term for term in required_terms if term not in row["phrase"]]
    if missing:
        raise ValueError(f"pillar {pillar} phrase missing term: {missing[0]}")


P28_REQUIRED_TERMS = (
    "REVISOR",
    "cláusula",
    "comprobación",
    "ámbito",
    "conteo esperado",
    "conteo medido",
    "control positivo",
    "la coordinadora comprueba cobertura",
)
P29_REQUIRED_TERMS = ("sin matriz", "no se acepta")


def test_real_canon_p28_phrase_has_required_terms() -> None:
    text = CANON_PATH.read_text(encoding="utf-8")
    assert_pillar_contains_terms(text, "P28", P28_REQUIRED_TERMS)


def test_real_canon_p29_phrase_has_required_terms() -> None:
    text = CANON_PATH.read_text(encoding="utf-8")
    assert_pillar_contains_terms(text, "P29", P29_REQUIRED_TERMS)


def test_p28_fixture_without_revisor_fails_explicitly() -> None:
    fixture_row = (
        "| P28 | La verificación del DoD es de la coordinadora mediante una "
        "matriz (cláusula, comprobación, ámbito, conteo esperado, conteo "
        "medido, control positivo); la coordinadora comprueba cobertura. | "
        f"RATIFICADA | {P28_MESSAGE_ID} | fuente.md | mecanismo | coordinadora activa |"
    )
    candidate = "# title\n" + fixture_row + "\n"
    with pytest.raises(ValueError, match="phrase missing term"):
        assert_pillar_contains_terms(candidate, "P28", P28_REQUIRED_TERMS)


def test_p28_fixture_term_only_in_other_column_still_fails_explicitly() -> None:
    """Require the missing term to be absent from the WHOLE row, not just
    rephrased elsewhere: the phrase cell lacks REVISOR, but the mecanismo
    cell names it, so a mutant that scanned the whole row instead of only
    the phrase cell would wrongly find it there and stay silent."""
    fixture_row = (
        "| P28 | La verificación del DoD es de la coordinadora mediante una "
        "matriz (cláusula, comprobación, ámbito, conteo esperado, conteo "
        "medido, control positivo); la coordinadora comprueba cobertura. | "
        f"RATIFICADA | {P28_MESSAGE_ID} | fuente.md | "
        "REVISOR hace la matriz, conteo medido lo repite la coordinadora | "
        "coordinadora activa |"
    )
    candidate = "# title\n" + fixture_row + "\n"
    with pytest.raises(ValueError, match="phrase missing term: REVISOR"):
        assert_pillar_contains_terms(candidate, "P28", P28_REQUIRED_TERMS)


def test_p29_fixture_inverted_meaning_fails_explicitly() -> None:
    fixture_row = (
        "| P29 | Una caja con matriz ejecutada por el revisor se acepta. | "
        f"RATIFICADA | {P28_MESSAGE_ID} | fuente.md | mecanismo | coordinadora activa |"
    )
    candidate = "# title\n" + fixture_row + "\n"
    with pytest.raises(ValueError, match="phrase missing term"):
        assert_pillar_contains_terms(candidate, "P29", P29_REQUIRED_TERMS)


def test_p28_real_canon_mutant_revisor_to_coordinadora_fails_explicitly() -> None:
    text = CANON_PATH.read_text(encoding="utf-8")
    assert text.count("REVISOR de la celda") == 1
    candidate = mutate_once(text, "REVISOR de la celda", "coordinadora de la celda")
    with pytest.raises(ValueError, match="phrase missing term"):
        assert_pillar_contains_terms(candidate, "P28", P28_REQUIRED_TERMS)


def test_p29_real_canon_mutant_inverted_meaning_fails_explicitly() -> None:
    text = CANON_PATH.read_text(encoding="utf-8")
    original = "sin matriz ejecutada por el revisor no se acepta"
    assert text.count(original) == 1
    candidate = mutate_once(
        text, original, "con matriz ejecutada por el revisor se acepta"
    )
    with pytest.raises(ValueError, match="phrase missing term"):
        assert_pillar_contains_terms(candidate, "P29", P29_REQUIRED_TERMS)


def test_real_canon_rows_are_well_formed_and_portable() -> None:
    text = CANON_PATH.read_text(encoding="utf-8")
    rows = load_canon(text)
    assert rows
    assert all(row["state"] in ALLOWED_STATES for row in rows)
    assert all(
        len(row["message_id"]) == 36 for row in rows if row["state"] == "RATIFICADA"
    )
    assert all(
        not row["message_id"]
        for row in rows
        if row["state"] in {"NO RATIFICADA", "PILOTO", "SUPERADA"}
    )
    assert not any(token in text for token in ("C:\\", "C:/Users", "/home/"))


def test_real_canon_has_no_embedded_cupo_figures() -> None:
    text = CANON_PATH.read_text(encoding="utf-8")
    assert_no_cupo_figures(text)


@pytest.mark.parametrize(
    "cupo_text",
    [
        "P>=85",
        "cupo de 5h >=90",
        "~85 por ciento",
        "P>=95",
        "quedan 90 unidades de cupo",
        "90 de cupo",
    ],
)
def test_cupo_figure_fixture_fails_explicitly(cupo_text: str) -> None:
    candidate = mutate_once(BASE_ROW, "Regla de prueba", f"Regla {cupo_text}")
    with pytest.raises(ValueError, match="cupo figures"):
        assert_no_cupo_figures(candidate)


@pytest.mark.parametrize(
    "context_text",
    [
        "contexto de la saliente al relevar / 600000",
        "ticks con cupo medido (rc 0); episodios de cupo alto sin accion",
    ],
)
def test_cupo_figure_does_not_flag_context_or_unrelated_numbers(
    context_text: str,
) -> None:
    assert CUPO_FIGURE_RE.findall(context_text) == []


def test_real_canon_pillar_ids_are_contiguous() -> None:
    text = CANON_PATH.read_text(encoding="utf-8")
    numbers = [int(match) for match in re.findall(r"^\| P(\d+) \|", text, re.MULTILINE)]
    assert numbers
    assert max(numbers) >= 27
    assert numbers == list(range(1, max(numbers) + 1))


@pytest.mark.parametrize("pillar", ["P28", "P29"])
def test_real_canon_pillar_is_ratified_with_message_id(pillar: str) -> None:
    text = CANON_PATH.read_text(encoding="utf-8")
    assert_pillar_ratified(text, pillar, P28_MESSAGE_ID)


@pytest.mark.parametrize("pillar", ["P28", "P29"])
def test_pillar_fixture_without_row_fails_explicitly(pillar: str) -> None:
    candidate = "# title\n" + BASE_ROW + "\n"
    with pytest.raises(ValueError, match=f"{pillar} is missing"):
        assert_pillar_ratified(candidate, pillar, P28_MESSAGE_ID)


@pytest.mark.parametrize("pillar", ["P28", "P29"])
def test_pillar_fixture_not_ratified_fails_explicitly(pillar: str) -> None:
    fixture_row = (
        f"| {pillar} | Regla de prueba {pillar} | NO RATIFICADA |  | "
        "fuente.md | mecanismo | coordinadora activa |"
    )
    candidate = "# title\n" + fixture_row + "\n"
    with pytest.raises(ValueError, match=f"{pillar} is not RATIFICADA"):
        assert_pillar_ratified(candidate, pillar, P28_MESSAGE_ID)


@pytest.mark.parametrize(
    ("pillar", "fixture_row"),
    [("P28", P28_FIXTURE_ROW), ("P29", P29_FIXTURE_ROW)],
)
def test_pillar_fixture_with_other_message_id_fails_explicitly(
    pillar: str, fixture_row: str
) -> None:
    candidate = (
        "# title\n"
        + mutate_once(
            fixture_row, P28_MESSAGE_ID, "c38d20f3-796a-4f56-ae3d-50c09952ce25"
        )
        + "\n"
    )
    with pytest.raises(ValueError, match="messageId mismatch"):
        assert_pillar_ratified(candidate, pillar, P28_MESSAGE_ID)


def test_ratified_positive_row_parses() -> None:
    row = parse_row(BASE_ROW)
    assert row["state"] == "RATIFICADA"
    assert len(row["message_id"]) == 36


@pytest.mark.parametrize(
    ("old", "new", "reason"),
    [
        ("RATIFICADA", "", "state is required"),
        ("RATIFICADA", "CONFIRMADA", "invalid state"),
        (
            "c38d20f3-796a-4f56-ae3d-50c09952ce25",
            "c38d20f3-796a-4f56-ae3d-50c09952ce2",
            "UUID",
        ),
        (
            "c38d20f3-796a-4f56-ae3d-50c09952ce25",
            "c38d20f3-796a-4f56-ae3d-50c09952ce250",
            "UUID",
        ),
        (
            "c38d20f3-796a-4f56-ae3d-50c09952ce25",
            "",
            "^ratified row requires messageId$",
        ),
        ("RATIFICADA", "NO RATIFICADA", "only ratified"),
    ],
)
def test_row_negative_mutates_one_unique_fragment(
    old: str, new: str, reason: str
) -> None:
    candidate = mutate_once(BASE_ROW, old, new)
    with pytest.raises(ValueError, match=reason):
        parse_row(candidate)


def test_row_with_six_columns_fails_explicitly() -> None:
    candidate = mutate_once(BASE_ROW, "| mecanismo |", "| mecanismo")
    with pytest.raises(ValueError, match="row must have seven columns"):
        parse_row(candidate)


def test_empty_canon_fails_explicitly() -> None:
    with pytest.raises(ValueError, match="empty"):
        load_canon("")


def test_canon_without_final_newline_fails_explicitly() -> None:
    candidate = (
        "# title\n| P1 | phrase | NO RATIFICADA |  | source.md | mechanism | usuario |"
    )
    with pytest.raises(ValueError, match="newline"):
        load_canon(candidate)


def test_canon_with_no_data_rows_fails_explicitly() -> None:
    candidate = "# title\n| Pilar | Frase | ESTADO | messageId | fuente larga | mecanismo | actor |\n"
    with pytest.raises(ValueError, match="no rows"):
        load_canon(candidate)


def test_absolute_route_fixture_fails_explicitly() -> None:
    candidate = "# title\n| P1 | C:\\Users\\alguien\\canon.md | NO RATIFICADA |  | source.md | mechanism | usuario |\n"
    with pytest.raises(ValueError, match="absolute route"):
        load_canon(candidate)


def test_absolute_route_posix_users_fixture_fails_explicitly() -> None:
    candidate = "# title\n| P1 | /Users/alguien/canon.md | NO RATIFICADA |  | source.md | mechanism | usuario |\n"
    with pytest.raises(ValueError, match="absolute route"):
        load_canon(candidate)


def test_absolute_route_unc_fixture_fails_explicitly() -> None:
    candidate = (
        "# title\n| P1 | \\\\servidor\\recurso\\canon.md | NO RATIFICADA |  | "
        "source.md | mechanism | usuario |\n"
    )
    with pytest.raises(ValueError, match="absolute route"):
        load_canon(candidate)


def test_readme_reference_points_to_existing_canon() -> None:
    readme = (CANON_PATH.parents[3] / ".claude" / "rules" / "README.md").read_text(
        encoding="utf-8"
    )
    assert ".agent/rules/common/vuelo_pilares.md" in readme
    assert CANON_PATH.exists()


def test_agents_reference_points_to_canon() -> None:
    agents = (CANON_PATH.parents[3] / "AGENTS.md").read_text(encoding="utf-8")
    assert "vuelo_pilares.md" in agents
