"""Contract test for prompts/audit_agent_output.md's portable-memory destino
guidance (WOT-2026-023h).

Background: the `memoria_no_portable` bullet presented the GITIGNORED
`observations.jsonl` as the "DESTINO EXACTO ... verificado" for a claim of
PORTABLE learning persistence. That contradicts the canon already fixed in
`memory_upload.md:71` ("El fichero al que se promueve es el ARCHIVE VERSIONADO,
no observations.jsonl") and `AGENTS.md:390` ("Lo canonico es lo VERSIONADO:
archive/observations.YYYY-MM.jsonl"). A portable claim's destino is the
versioned archive; `observations.jsonl` is runtime (gitignored), not portable.

Criterion is a PHRASE marker (the destino sentence), NOT a blind grep: the
prompt legitimately mentions `observations.jsonl` elsewhere (schema, source of
promotion), and `memory_upload.md`'s source-mentions are legitimate too. Only
the DESTINO-for-portable sentence must point at the versioned archive.
"""

from __future__ import annotations

import re
from pathlib import Path


PROMPTS = Path(__file__).resolve().parents[2] / "prompts"
AUDIT_PROMPT = PROMPTS / "audit_agent_output.md"


def _memoria_bullet() -> str:
    """The `memoria_no_portable` bullet (from its header until the next '- **'
    top-level bullet), so assertions are scoped to the destino guidance, not
    prose elsewhere in the file."""
    text = AUDIT_PROMPT.read_text(encoding="utf-8")
    start = text.index('**Claims de "quedo en memoria"')
    # next top-level bullet begins with '\n- **'
    m = re.search(r"\n- \*\*", text[start:])
    end = start + m.start() if m else len(text)
    return text[start:end]


def test_portable_destino_is_the_versioned_archive() -> None:
    """WOT-2026-023h: the portable-claim DESTINO must EXPLICITLY name the
    versioned archive as THE portable destination (a destino PHRASE, not merely
    a passing mention of the path elsewhere), aligning with memory_upload.md /
    AGENTS.md. Mutation: rephrase the destino sentence back to bare
    observations.jsonl -> RED."""
    bullet = _memoria_bullet()
    # PHRASE marker: the sentence that DESIGNATES the portable destino, not any
    # incidental `archive/observations` mention in the verification steps.
    assert re.search(
        r"destino\s+portable\s+es\s+el\s+archive\s+versionado",
        bullet,
        re.IGNORECASE,
    ), (
        "the memoria bullet must DESIGNATE the versioned archive "
        "(archive/observations.YYYY-MM.jsonl) as THE portable destino with an "
        "explicit phrase (not just mention the path); the gitignored "
        "observations.jsonl is runtime, not portable "
        "(canon: memory_upload.md, AGENTS.md)"
    )
    assert "archive/observations" in bullet, (
        "and the archive path must appear so the destino is concrete"
    )


def test_gitignored_jsonl_not_presented_as_portable_destino() -> None:
    """The bullet must NOT present the gitignored observations.jsonl as the
    portable destino. It marks the destino-for-portable with a phrase; if that
    phrase still points bare `observations.jsonl` as the portable target
    without the archive, the claim guidance recreates the false-green.
    Mutation: rephrase the destino back to bare observations.jsonl -> RED."""
    bullet = _memoria_bullet()
    # The bullet must explicitly tie 'portable' to the versioned archive, and
    # explicitly note observations.jsonl is gitignored/runtime (not portable).
    assert re.search(
        r"observations\.jsonl.*gitignored", bullet, re.IGNORECASE
    ) or re.search(r"gitignored.*observations\.jsonl", bullet, re.IGNORECASE), (
        "the bullet must state that observations.jsonl is gitignored/runtime, so "
        "it is not the portable destino (the versioned archive is)"
    )
