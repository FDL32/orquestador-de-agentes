"""Tests for scripts/check_commit_message_encoding.py (WOT-2026-046f).

The ticket's DoD is BINARY: either commit messages enter the encoding guard's
scope, or the exclusion is declared in writing. Decision taken with the
operator: BLOCK structural corruption, WARN on accents/typographic
punctuation -- mirroring what the file guard already does (it chases
CORRUPTION, not STYLE).

These tests pin both halves. The WARN half matters as much as the block: a
guard that blocked legitimate Spanish would reject 64 of the repo's own
historic commits, turning a barrier into a false-positive generator (the
pathology WOT-2026-047f was opened for).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "scripts" / "check_commit_message_encoding.py"


def _run(tmp_path: Path, message: str) -> subprocess.CompletedProcess:
    """Invoke the hook exactly as git does: a path to the message file."""
    msg_file = tmp_path / "COMMIT_EDITMSG"
    msg_file.write_text(message, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(msg_file)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# BLOCK half: structural corruption stops the commit.
# ---------------------------------------------------------------------------


def test_046f_mojibake_is_blocked(tmp_path: Path) -> None:
    """The class the guard exists for: text decoded through the wrong codec."""
    result = _run(tmp_path, "fix: Ã©sto es mojibake")
    assert result.returncode == 1
    assert "mojibake" in result.stderr.lower()


def test_046f_control_char_is_blocked(tmp_path: Path) -> None:
    """A raw control character is corruption, never authored prose."""
    result = _run(tmp_path, "fix: algo\x07 con un BEL dentro")
    assert result.returncode == 1
    assert "control" in result.stderr.lower()


def test_046f_diagnostic_names_the_remedy(tmp_path: Path) -> None:
    """AGENTS.md, 'gates self-service': a gate must say how to fix it.

    The remedy is not generic advice here -- `git commit -F <file>` is exactly
    what avoids the here-string that injected a stray '@' into 70277ff's
    subject during this very flight.
    """
    result = _run(tmp_path, "fix: Ã©sto es mojibake")
    assert "-F" in result.stderr, "must point at the concrete escape hatch"


# ---------------------------------------------------------------------------
# WARN half: legitimate prose is reported, never blocked.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "WOT-2026-045g: el test de discover_motor_root aísla AGENT_PROJECT_ROOT",
        "fix(tests): 2 barreras cosméticas ahora con dientes",
    ],
)
def test_046f_real_historic_accented_subjects_are_not_blocked(
    tmp_path: Path, message: str
) -> None:
    """CONTROL POSITIVO with the repo's OWN commits (a3966ae, 1f823ec).

    Measured before choosing the scope: 64 of 1385 messages carry accents or
    typographic punctuation, all of it correct Spanish. Blocking them would
    reject the project's own history.
    """
    result = _run(tmp_path, message)
    assert result.returncode == 0, (
        f"legitimate Spanish must NOT be blocked (stderr={result.stderr!r})"
    )
    assert "WARN" in result.stderr, "but it must still be reported"
    assert "acentos" in result.stderr.lower()


def test_046f_typographic_punctuation_warns_without_blocking(tmp_path: Path) -> None:
    result = _run(tmp_path, "fix: usa “comillas” curvas y un guion — largo")
    assert result.returncode == 0
    assert "tipografica" in result.stderr.lower()


def test_046f_clean_ascii_message_is_silent(tmp_path: Path) -> None:
    """(MUTATION half) Without this, the WARN could degrade into always-on
    noise and every test above would still pass."""
    result = _run(tmp_path, "WOT-2026-046f: guard de encoding para commit-msg")
    assert result.returncode == 0
    assert result.stderr.strip() == "", f"expected silence, got {result.stderr!r}"


# ---------------------------------------------------------------------------
# Robustness: the guard must never be the reason a commit cannot happen.
# ---------------------------------------------------------------------------


def test_046f_comment_lines_are_ignored(tmp_path: Path) -> None:
    """git's own template is full of '#' lines; they must never trigger."""
    result = _run(
        tmp_path,
        "WOT-2026-046f: mensaje limpio\n"
        "# Por favor introduce el mensaje — con tipografia\n"
        "# Ã©sto es mojibake pero va en un comentario\n",
    )
    assert result.returncode == 0, "comment lines must not be inspected"
    assert result.stderr.strip() == ""


def test_046f_missing_file_fails_open(tmp_path: Path) -> None:
    """A guard-side error must not block every commit in the repo."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path / "does_not_exist")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, "fail OPEN: a broken guard must not wedge the repo"


def test_046f_no_argument_is_a_noop(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], capture_output=True, text=True
    )
    assert result.returncode == 0
