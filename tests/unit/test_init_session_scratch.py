"""WOT-2026-059o: the chat close flow must leave session telemetry.

Contract T-059O-001: the autonomous batch prompt and both pipeline prompts
register session telemetry (scripts/init_session_scratch.py, WOT-2026-022c),
but the chat close flow did not -- a whole chat session registered ZERO events
and Bloque 2.5 of the close always fell to SKIP_NO_TELEMETRY (absence of
EVIDENCE, not absence of problems). This file pins the wiring the ticket adds
to prompts/orchestrator_session_close_chat.md:

- (a) the prompt invokes init_session_scratch (invocation + record_count > 0
  verification). LOAD-BEARING for the ticket mutation.
- (b) the empty-manifest INVARIANT is named by the close.
- (c) the NEGATIVE CONTROL: a session without artifacts is not obligated to
  write ledger.
- (e) sessions with records keep listing identically (regression pin of the
  `list` CLI through the real subprocess path).

Mutation isolation (DoD d): reverting the INVOCATION (the init_session_scratch
commands) fails ONLY test (a); (b)/(c) anchor on invariant prose that does not
reference the invocation tokens, and (e) never reads the prompt.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


_MOTOR_ROOT = Path(__file__).resolve().parents[2]
_PROMPT = _MOTOR_ROOT / "prompts" / "orchestrator_session_close_chat.md"
_SCRIPT = _MOTOR_ROOT / "scripts" / "init_session_scratch.py"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _norm(text: str) -> str:
    """Collapse whitespace so prose anchors survive markdown re-wrapping.

    The contract is about WORDS, not line wrapping: an editor reflowing a
    bullet must not turn these tests red, and a mutation removing the prose
    must still turn them red.
    """
    return " ".join(text.split())


# ---------------------------------------------------------------------------
# (a) LOAD-BEARING: the chat close prompt invokes the session telemetry CLI.
# ---------------------------------------------------------------------------


def test_close_chat_prompt_invokes_init_session_scratch() -> None:
    """DoD (a): the chat close flow must invoke init_session_scratch so a chat
    session leaves at least one verifiable event (record_count > 0).

    LOAD-BEARING (ticket mutation): before WOT-2026-059o this prompt had 0 refs
    to the script. Reverting the invocation removes both anchors below and ONLY
    this test fails -- the invariant/control anchors live in other tests on
    purpose, so this one carries the teeth.
    """
    text = _norm(_read(_PROMPT))
    assert "init_session_scratch.py --project-root" in text, (
        "orchestrator_session_close_chat.md must invoke "
        "scripts/init_session_scratch.py with --project-root so a chat-flow "
        "session leaves telemetry for the close audit (WOT-2026-059o)"
    )
    assert "record_count > 0" in text, (
        "the chat close prompt must verify via `init_session_scratch list` that "
        "the session appears with record_count > 0 (the verifiable event of "
        "DoD a)"
    )


# ---------------------------------------------------------------------------
# (b) INVARIANT: an artifact-producing session never closes with an empty
# manifest without the close NAMING it.
# ---------------------------------------------------------------------------


def test_close_chat_prompt_names_empty_manifest_invariant() -> None:
    """DoD (b): the close must NAME an empty manifest for a session that
    produced artifacts; silent omission is the false green this invariant
    kills. Anchors are invariant prose only -- no invocation tokens -- so the
    ticket mutation (revert the invocation) does NOT touch this test.
    """
    text = _norm(_read(_PROMPT))
    assert "manifest vacio" in text, (
        "the chat close prompt must state the empty-manifest invariant "
        "(an artifact-producing session does not close with an empty manifest "
        "without the close naming it) (WOT-2026-059o, DoD b)"
    )
    assert "sin que el cierre lo nombre" in text, (
        "the invariant must require the close to NAME the empty manifest, not "
        "just skip it silently (WOT-2026-059o, DoD b)"
    )


# ---------------------------------------------------------------------------
# (c) NEGATIVE CONTROL: a session without artifacts is not obligated to write
# ledger.
# ---------------------------------------------------------------------------


def test_close_chat_prompt_keeps_empty_sessions_free_of_ledger_duty() -> None:
    """DoD (c): a session that produced no artifacts must NOT be forced to
    write ledger entries; SKIP_NO_TELEMETRY stays a legitimate verdict for an
    empty session. Same anchor discipline as (b): prose only.
    """
    text = _norm(_read(_PROMPT))
    assert "CONTROL NEGATIVO" in text, (
        "the chat close prompt must declare the negative control explicitly "
        "(WOT-2026-059o, DoD c)"
    )
    assert "no queda obligada a escribir ledger" in text, (
        "a session without artifacts must not be obligated to write ledger "
        "(WOT-2026-059o, DoD c)"
    )


# ---------------------------------------------------------------------------
# (e) Sessions with records keep listing identically (regression pin of the
# `list` CLI through the real subprocess path).
# ---------------------------------------------------------------------------


def test_list_lists_sessions_with_records_unchanged(tmp_path: Path) -> None:
    """DoD (e): sessions with records keep listing the same.

    Regression pin through the REAL CLI path (subprocess, the same invocation
    shape the prompts use): init a session, append two events, `list` must
    report it with record_count == 2 and the exact output shape the close
    audit consumes.
    """
    root = tmp_path / "destino"
    (root / ".agent").mkdir(parents=True)
    sid = "20260101-1200-nogit-a1b2c3d4"

    def run(*args: str) -> dict:
        proc = subprocess.run(
            [sys.executable, str(_SCRIPT), "--project-root", str(root), *args],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert proc.returncode == 0, (proc.stdout, proc.stderr)
        return json.loads(proc.stdout)

    run("init", "--session-id", sid, "--generator", "close-chat-test")
    run(
        "add",
        "--session-id",
        sid,
        "--event",
        "tool_used",
        "--generator",
        "close-chat-test",
        "--reference",
        "ref-0001",
    )
    run(
        "add",
        "--session-id",
        sid,
        "--event",
        "tool_used",
        "--generator",
        "close-chat-test",
        "--reference",
        "ref-0002",
    )

    out = run("list")
    mine = [s for s in out["sessions"] if s["session_id"] == sid]
    assert len(mine) == 1, out
    assert mine[0]["record_count"] == 2, mine[0]
    assert set(mine[0]) == {"session_id", "record_count", "lock_state", "archived"}
