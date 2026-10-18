"""Mutation-verified barrier tests for WOT-2026-060t.

The canonical encoding guard (``scripts/check_encoding_guard.py``) is the one
``prompts/orchestrator_launch_builder.md`` orders the Builder to run to
guarantee "sin mojibake ni puntuacion tipografica (em-dash, comillas curvas:
usa guion y comillas ASCII)". Before this ticket the guard had no check for
that punctuation: a file with an em-dash or a curly quote passed rc=0.

DoD under test (ficha WOT-2026-060t):
(a) a file with em-dash or curly quote -> rc=1 (CLI) / flagged (function).
(b) CONTROL NEGATIVE: a clean file stays rc=0; a BOM file stays rc=1
    (proves the new check does not change unrelated behavior).
(c) MUTATION: removing the new check (monkeypatching the codepoint set to
    empty) reverts the em-dash fixture to "not flagged".
(d) the codepoint list is explicit and the test fixtures name the exact
    bytes.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from encoding_guard import (  # noqa: E402
    file_issues,
    find_typographic_punctuation,
)


ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "scripts" / "check_encoding_guard.py"

# Built via chr() (not literal chars) so this source file itself stays ASCII,
# per the repo convention this ticket enforces. Exact bytes from the ficha's
# own recibo: em-dash is E2 80 94, left/right double curly quotes are
# E2 80 9C / E2 80 9D.
_EM_DASH = chr(0x2014)
_LEFT_DOUBLE_QUOTE = chr(0x201C)
_RIGHT_DOUBLE_QUOTE = chr(0x201D)
_LEFT_SINGLE_QUOTE = chr(0x2018)
_RIGHT_SINGLE_QUOTE = chr(0x2019)


def _write_utf8(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def _run_guard_explicit(*paths: Path) -> subprocess.CompletedProcess[str]:
    # PYTHONIOENCODING: on Windows the child's stderr defaults to the console
    # codepage (cp1252), which mangles the em-dash/curly-quote snippets this
    # guard now prints; without it the parent's utf-8 decode here crashes.
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        [sys.executable, str(GUARD), *[str(p) for p in paths]],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )


# ---------------------------------------------------------------------------
# Barrier (a): em-dash / curly quotes -> flagged
# ---------------------------------------------------------------------------


class TestTypographicPunctuationBarrier:
    @pytest.mark.parametrize(
        "char,codepoint",
        [
            (_EM_DASH, 0x2014),
            (_LEFT_SINGLE_QUOTE, 0x2018),
            (_RIGHT_SINGLE_QUOTE, 0x2019),
            (_LEFT_DOUBLE_QUOTE, 0x201C),
            (_RIGHT_DOUBLE_QUOTE, 0x201D),
        ],
    )
    def test_codepoint_flagged_by_find_typographic_punctuation(
        self, char: str, codepoint: int
    ) -> None:
        text = "clean prefix " + char + " clean suffix"
        result = find_typographic_punctuation(text)
        assert result, (
            f"BARRIER FAILURE: U+{codepoint:04X} was NOT flagged by "
            f"find_typographic_punctuation. Result: {result!r}"
        )

    def test_em_dash_flagged_via_file_issues(self, tmp_path: Path) -> None:
        text = "una frase " + _EM_DASH + " con em-dash\n"
        p = _write_utf8(tmp_path, "fixture.md", text)
        _mj, _qm, corruption = file_issues(p)
        assert corruption, (
            f"BARRIER FAILURE: file_issues did not report the em-dash. "
            f"corruption={corruption!r}"
        )

    def test_em_dash_flagged_via_cli_explicit_path(self, tmp_path: Path) -> None:
        """DoD (a): a fichero con em-dash pasado explicitamente -> rc=1."""
        p = _write_utf8(tmp_path, "em_dash.md", "titulo " + _EM_DASH + " resto\n")
        result = _run_guard_explicit(p)
        assert result.returncode == 1, (
            f"BARRIER FAILURE: em-dash file did not get rc=1. "
            f"rc={result.returncode} stderr={result.stderr!r}"
        )
        assert "Text corruption" in result.stderr or "Encoding guard" in result.stderr

    def test_curly_double_quote_flagged_via_cli_explicit_path(
        self, tmp_path: Path
    ) -> None:
        p = _write_utf8(
            tmp_path,
            "curly_quote.md",
            _LEFT_DOUBLE_QUOTE + "cita" + _RIGHT_DOUBLE_QUOTE + "\n",
        )
        result = _run_guard_explicit(p)
        assert result.returncode == 1, (
            f"BARRIER FAILURE: curly-quote file did not get rc=1. "
            f"rc={result.returncode} stderr={result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# Barrier (b): CONTROL NEGATIVE -- clean stays rc=0, BOM stays rc=1
# ---------------------------------------------------------------------------


class TestControlNegative:
    def test_clean_ascii_file_stays_rc0(self, tmp_path: Path) -> None:
        p = _write_utf8(tmp_path, "clean.md", 'titulo -- resto, comillas "ascii"\n')
        result = _run_guard_explicit(p)
        assert result.returncode == 0, (
            f"REGRESSION: clean ASCII file no longer rc=0. "
            f"rc={result.returncode} stderr={result.stderr!r}"
        )

    def test_bom_file_still_rc1(self, tmp_path: Path) -> None:
        p = tmp_path / "bom.md"
        p.write_bytes(b"\xef\xbb\xbf" + b"contenido limpio\n")
        result = _run_guard_explicit(p)
        assert result.returncode == 1, (
            f"REGRESSION: BOM detection broken by the new check. "
            f"rc={result.returncode} stderr={result.stderr!r}"
        )
        assert "BOM" in result.stderr

    def test_no_false_positive_on_ascii_hyphen_and_straight_quotes(self) -> None:
        clean = 'Paso 1 -- Verificacion "ascii" normal, sin em-dash ni comillas curvas'
        assert find_typographic_punctuation(clean) == []


# ---------------------------------------------------------------------------
# Barrier (c): MUTATION -- removing the check reverts to not-flagged
# ---------------------------------------------------------------------------


class TestMutationVerify:
    def test_empty_codepoint_set_stops_detecting_em_dash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mutating TYPOGRAPHIC_PUNCTUATION_CODEPOINTS to empty must flip the
        em-dash fixture from flagged to not-flagged -- proves the barrier is
        load-bearing, not a decorative no-op."""
        import encoding_guard

        text = "frase " + _EM_DASH + " con em-dash"
        assert find_typographic_punctuation(text), (
            "PREMISE BROKEN: em-dash should be flagged before the mutation"
        )

        monkeypatch.setattr(
            encoding_guard, "TYPOGRAPHIC_PUNCTUATION_CODEPOINTS", frozenset()
        )
        mutated_result = encoding_guard.find_typographic_punctuation(text)
        assert mutated_result == [], (
            "MUTATION-VERIFY FAILURE: emptying the codepoint set should stop "
            f"detection, got: {mutated_result!r}"
        )
