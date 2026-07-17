"""Contract test: audit_pipeline_codeonly.md pins the code-only motor-frontier
check (WOT-2026-023y, frozen contract T-023Y-001, CF-audit APROBADO).

PINNED CONTRACT (defined HERE, per convention -- see
test_prompt_summary_headers.py for the sibling pattern this test follows):

    In the "Integridad del motor SIN bus" section of
    ``prompts/audit_pipeline_codeonly.md`` (~lines 259-280), a sub-block titled
    "Check de frontera code-only (WOT-2026-023y)" MUST exist and pin, verbatim
    in spirit:

    1. The exact git command that checks the motor-frontier files
       (``MANIFEST.distribute`` and ``MANIFEST.workspace``) for drift between
       ``BASE_SHA`` and ``HEAD``, using ``git diff --name-only``.
    2. A binary criterion: empty output => frontier intact => VERIFICADO
       (dimension stops being NO_VERIFICABLE in code-only).
    3. A closed semantics for non-empty output: every listed file must have at
       least one commit (found via ``git log --format=%H``) that both (a)
       appears as ``commit:<sha>`` in an archived closing block of the audited
       batch_run, and (b) that block mentions MANIFEST.distribute or
       MANIFEST.workspace explicitly. Otherwise ->
       ``INTEGRITY_VIOLATION_DETECTED``.

    ASCII note (probe documented, WOT-2026-023y): the prompt file
    ``audit_pipeline_codeonly.md`` was probed with
    ``data.decode('ascii')`` BEFORE this change and it already raises
    ``UnicodeDecodeError`` on pre-existing em-dash mojibake bytes at lines 69,
    72, 150, 364, 367 (unrelated legacy content, out of this ticket's scope).
    Because the file is NOT currently pure ASCII, no
    ``test_prompt_is_ascii``-style test is added here: it would fail on
    pre-existing content this ticket must not touch. The new sub-block THIS
    ticket adds is itself pure ASCII (verified with the same probe restricted
    to the new lines), consistent with prompt style, but that narrower
    property is not asserted as a separate test to avoid re-encoding the
    unrelated legacy bytes as an implicit requirement of this contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest


PROMPT_PATH = (
    Path(__file__).resolve().parents[2] / "prompts" / "audit_pipeline_codeonly.md"
)

SECTION_HEADER = "Integridad del motor SIN bus"
SUBBLOCK_HEADER = "Check de frontera code-only (WOT-2026-023y)"

FRONTIER_COMMAND_FRAGMENTS = (
    "git -C <_dev> diff --name-only <BASE_SHA>..HEAD",
    "MANIFEST.distribute MANIFEST.workspace",
)

VIOLATION_TOKEN = "INTEGRITY_VIOLATION_DETECTED"  # noqa: S105 (nombre de estado de auditoria, no un secreto)

BINARY_CRITERION_ARMS = (
    "VACIA => frontera intacta",
    "git log --format=%H <BASE_SHA>..HEAD",
)


def _section_text(full_text: str) -> str:
    """Return the text of the 'Integridad del motor SIN bus' bullet section.

    Before: ``full_text`` is the full prompt content. During: locate the
    section header line, then slice up to the next top-level '## ' heading
    (the section is a bullet list nested under a '###'-less '## Fase 2'
    subsection, so we bound it by the next blank-line-delimited '---' or the
    next '## ' heading, whichever comes first). After: returns the bounded
    substring, or the tail of the file if no closing boundary is found
    (fail-open on the upper bound only, since the section is the last bullet
    before the "Estados de integridad" paragraph in the pinned contract).
    """
    start = full_text.find(SECTION_HEADER)
    assert start != -1, f"section header {SECTION_HEADER!r} not found in prompt"
    tail = full_text[start:]
    # Bound the section at the next top-level heading to avoid false positives
    # from unrelated later sections reusing similar tokens.
    next_heading = tail.find("\n## ", 1)
    if next_heading == -1:
        return tail
    return tail[:next_heading]


@pytest.fixture(scope="module")
def prompt_text() -> str:
    assert PROMPT_PATH.is_file(), f"prompt missing on disk: {PROMPT_PATH}"
    return PROMPT_PATH.read_text(encoding="utf-8")


def test_frontier_check_section_present(prompt_text: str) -> None:
    """The prompt pins the frontier-check command (both manifest files) and
    the INTEGRITY_VIOLATION_DETECTED token within the same bounded section.

    Mutation (teeth): delete the "Check de frontera code-only (WOT-2026-023y)"
    sub-block from the prompt (or drop either manifest filename from the
    command) and this test FAILS.
    """
    section = _section_text(prompt_text)
    assert SUBBLOCK_HEADER in section, (
        f"sub-block header {SUBBLOCK_HEADER!r} not found in "
        "'Integridad del motor SIN bus' section"
    )
    for fragment in FRONTIER_COMMAND_FRAGMENTS:
        assert fragment in section, (
            f"frontier command fragment {fragment!r} missing from section"
        )
    assert VIOLATION_TOKEN in section, (
        f"{VIOLATION_TOKEN!r} token missing from the frontier-check section"
    )


def test_frontier_criterion_is_binary(prompt_text: str) -> None:
    """Both arms of the binary criterion are pinned: the empty-output arm
    (VERIFICADO) and the closed non-empty-output semantics (git log lookup
    against an archived closing block).

    Mutation (teeth): remove either arm's phrasing (e.g. replace the
    empty-output criterion with prose, or drop the 'git log --format=%H'
    lookup command for the non-empty case) and this test FAILS.
    """
    section = _section_text(prompt_text)
    for arm in BINARY_CRITERION_ARMS:
        assert arm in section, f"binary-criterion arm {arm!r} missing from section"


def test_prompt_still_has_per_ticket_no_verificable_carveout(prompt_text: str) -> None:
    """The pre-existing NO_VERIFICABLE carve-out for per-ticket accumulated
    drift (outside the frontier) must survive verbatim alongside the new
    sub-block -- this ticket AMPLIFIES the bullet, it does not replace it.

    Mutation (teeth): delete the pre-existing 'NO_VERIFICABLE' phrase for
    per-ticket drift and this test FAILS.
    """
    section = _section_text(prompt_text)
    assert "NO_VERIFICABLE" in section
    assert "drift acumulado por-ticket" in section
    assert "check_motor_pristine.py" in section


def test_frontier_row_added_to_scope_table(prompt_text: str) -> None:
    """The 'Alcance auditado' table gains a sibling row for the frontier
    check next to check_motor_pristine, without removing the existing rows.

    Mutation (teeth): remove the 'frontera_manifest (023y)' table row and
    this test FAILS.
    """
    assert "| check_motor_pristine | <resultado> |" in prompt_text
    assert "| frontera_manifest (023y) | <resultado> |" in prompt_text
    assert "| check_backlog_commits_landed |" in prompt_text
