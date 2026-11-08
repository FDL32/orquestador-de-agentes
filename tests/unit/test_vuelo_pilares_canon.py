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
ABSOLUTE_ROUTE_RE = re.compile(r"(?:[A-Za-z]:[\\/]|/home/)")

BASE_ROW = (
    "| P0 | Regla de prueba | RATIFICADA | "
    "c38d20f3-796a-4f56-ae3d-50c09952ce25 | fuente.md | mecanismo | coordinadora activa |"
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


def test_real_canon_has_23_rows_and_portable_message_ids() -> None:
    text = CANON_PATH.read_text(encoding="utf-8")
    rows = load_canon(text)
    assert len(rows) == 23
    assert sum(row["state"] == "RATIFICADA" for row in rows) == 7
    assert sum(row["state"] == "NO RATIFICADA" for row in rows) == 16
    assert all(
        len(row["message_id"]) == 36 for row in rows if row["state"] == "RATIFICADA"
    )
    assert all(not row["message_id"] for row in rows if row["state"] == "NO RATIFICADA")
    assert not any(token in text for token in ("C:\\", "C:/Users", "/home/"))


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
            "messageId",
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


def test_empty_canon_fails_explicitly() -> None:
    with pytest.raises(ValueError, match="empty"):
        load_canon("")


def test_canon_without_final_newline_fails_explicitly() -> None:
    candidate = (
        "# title\n| P1 | phrase | NO RATIFICADA |  | source.md | mechanism | usuario |"
    )
    with pytest.raises(ValueError, match="newline"):
        load_canon(candidate)


def test_absolute_route_fixture_fails_explicitly() -> None:
    candidate = "# title\n| P1 | C:\\Users\\alguien\\canon.md | NO RATIFICADA |  | source.md | mechanism | usuario |\n"
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
