"""Contract-sync test for prompts/ensemble_loop.md (WOT-2026-093b).

The phase -> task-type table added to the prompt must stay aligned with the
production vocabularies: ``TASK_TYPES`` (scripts/ensemble_dispatch.py) and
``PHASE_LOOP_PARAMS`` (scripts/discover_skills.py, itself validated against the
dispatcher by tests/unit/test_prompt_router.py::TestPhaseLoopParams). This test
adds the comparison against the PROMPT TEXT, which the router test does not do.

The prompt path is parameterizable via the ``ENSEMBLE_LOOP_PROMPT_PATH`` env var
so a mutation run can point the test at a pre-fix copy
(``git show HEAD:prompts/ensemble_loop.md > tmp``) and confirm it fails.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from scripts.discover_skills import PHASE_LOOP_PARAMS


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROMPT = ROOT / "prompts" / "ensemble_loop.md"
PROMPT_PATH_ENV = "ENSEMBLE_LOOP_PROMPT_PATH"

# D1 (WOT-2026-093b) removed this claim: the refuter DOES count if its round is
# substantive (check_loop_execution.py excludes only the emitter, muted rounds
# and BA01 substitutions).
STALE_REFUTER_PHRASE = "no cuenta dentro de las N lentes"

# Any heading level, so a misplaced ``## 3.7`` before ``### 3.5`` is caught too.
_SUBSECTION_RE = re.compile(r"^(#{2,4})\s+3\.(\d+)\b", re.MULTILINE)


@pytest.fixture()
def prompt_path() -> Path:
    override = os.environ.get(PROMPT_PATH_ENV)
    path = Path(override) if override else DEFAULT_PROMPT
    assert path.is_file(), f"prompt not found: {path}"
    return path


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _task_type_table(text: str) -> dict[str, str]:
    """Return ``{phase: --task-type}`` parsed from the prompt's new table."""
    lines = text.splitlines()
    start = next(
        (
            i
            for i, line in enumerate(lines)
            if line.lstrip().startswith("|") and "--task-type" in line
        ),
        None,
    )
    assert start is not None, "phase -> task-type table not found in the prompt"
    header = [c.strip() for c in lines[start].strip().strip("|").split("|")]
    type_col = header.index("--task-type")
    table: dict[str, str] = {}
    for line in lines[start + 2 :]:
        if not line.lstrip().startswith("|"):
            break
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        table[cells[0]] = cells[type_col]
    return table


def test_task_type_table_matches_phase_loop_params(prompt_path: Path) -> None:
    """Every task-type in the table is valid and mirrors PHASE_LOOP_PARAMS."""
    from scripts.ensemble_dispatch import TASK_TYPES

    table = _task_type_table(_read(prompt_path))
    expected = {phase: params[2] for phase, params in PHASE_LOOP_PARAMS.items()}
    assert table == expected
    assert set(table.values()) <= TASK_TYPES


def test_refuter_counts_statement_is_gone(prompt_path: Path) -> None:
    """D1: the refuter counts as a lens if its round is substantive."""
    assert STALE_REFUTER_PHRASE not in _read(prompt_path)


def test_subsections_are_numeric_and_ordered(prompt_path: Path) -> None:
    """3.x subsections are h3 headings in strictly increasing numeric order."""
    matches = _SUBSECTION_RE.findall(_read(prompt_path))
    assert matches, "no 3.x subsections found"
    levels = [level for level, _number in matches]
    numbers = [int(number) for _level, number in matches]
    assert levels == ["###"] * len(levels)
    assert numbers == sorted(numbers)
    assert len(set(numbers)) == len(numbers)
