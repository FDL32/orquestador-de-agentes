"""Direction-2 frontier tests for scripts/check_distribution_boundary.py.

WOT-2026-043b: a file that TRAVELS must not cite a governing prompt that does
NOT travel. ``audit_skill_citations`` enumerates NORMATIVE citations
(frontmatter ``source_prompt`` / ``source_of_truth``) from
``skills/*/SKILL.md`` to ``prompts/*.md`` and fails when the cited prompt exists
in the motor but is absent from MANIFEST.distribute. In-prose mentions are WARN.
The real-repo debt is FROZEN in ``_FROZEN_DEBT``.

Coverage (one idea per test):
  T-CIT-FAILS      : normative citation to a non-shipped prompt -> exit 1.
  T-CIT-MENTION-OK : in-prose mention (no frontmatter key) -> exit 0, WARN only.
  T-CIT-TRAVELS-OK : normative citation to a SHIPPED prompt -> exit 0.
  T-CIT-DENOM      : publishes "<N> skills -> <M> referencias normativas".
  T-CIT-EMPTY      : no skills -> explicit SKIP, exit 1 (0 files is not a pass).
  T-CIT-FROZEN     : a frozen_debt entry exempts the violation -> exit 0.
  T-CIT-STALE      : a frozen_debt entry that never fires -> exit 1 (STALE).
  T-CIT-REAL       : live contract on the real motor tree (baseline applies).
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "check_distribution_boundary",
    _ROOT / "scripts" / "check_distribution_boundary.py",
)
cdb = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cdb)


def _wb(path: Path, text: str) -> None:
    """Write text as LF bytes (never let the platform CRLF-ify a fixture)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.replace("\r\n", "\n").encode("utf-8"))


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(root), capture_output=True, text=True, timeout=30
    )


@pytest.fixture
def motor(tmp_path: Path) -> Path:
    """A git-init'd fake motor under pytest's tmp_path."""
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t.t")
    _git(tmp_path, "config", "user.name", "t")
    return tmp_path


def _commit(root: Path) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "x")


def _skill(path: Path, frontmatter: str, body: str = "") -> None:
    _wb(path, f"---\n{frontmatter}\n---\n\n# skill\n\n{body}\n")


def _base_motor(motor: Path) -> None:
    """One shipped prompt (travels) and one orphan (does not travel)."""
    _wb(motor / "MANIFEST.distribute", "prompts/travels.md\n")
    _wb(motor / "prompts" / "travels.md", "governs\n")
    _wb(motor / "prompts" / "orphan.md", "not shipped\n")


# ---------------------------------------------------------------- T-CIT-FAILS
def test_normative_citation_to_untraveled_prompt_fails(motor: Path):
    _base_motor(motor)
    _skill(motor / "skills" / "bad" / "SKILL.md", "source_prompt: prompts/orphan.md")
    _commit(motor)

    code, lines = cdb.audit_skill_citations(motor, frozen_debt=())
    joined = "\n".join(lines)
    assert code == 1, joined
    assert "orphan.md" in joined
    assert "skills/bad/SKILL.md" in joined


# ------------------------------------------------------------ T-CIT-MENTION-OK
def test_prose_mention_does_not_fail(motor: Path):
    _base_motor(motor)
    _skill(
        motor / "skills" / "ok" / "SKILL.md",
        "name: ok",
        "Detalle en `prompts/orphan.md` seccion 1.",
    )
    _commit(motor)

    code, lines = cdb.audit_skill_citations(motor, frozen_debt=())
    joined = "\n".join(lines)
    assert code == 0, joined
    assert "orphan.md" in joined  # reported as WARN, does not fail


# ----------------------------------------------------------- T-CIT-TRAVELS-OK
def test_normative_citation_to_shipped_prompt_passes(motor: Path):
    _base_motor(motor)
    _skill(motor / "skills" / "good" / "SKILL.md", "source_prompt: prompts/travels.md")
    _commit(motor)

    code, lines = cdb.audit_skill_citations(motor, frozen_debt=())
    assert code == 0, "\n".join(lines)


# ---------------------------------------------------------------- T-CIT-DENOM
def test_publishes_denominator(motor: Path):
    _base_motor(motor)
    _skill(motor / "skills" / "good" / "SKILL.md", "source_prompt: prompts/travels.md")
    _commit(motor)

    _code, lines = cdb.audit_skill_citations(motor, frozen_debt=())
    assert any("skills -> 1 referencias normativas auditadas" in ln for ln in lines), (
        lines
    )


# ---------------------------------------------------------------- T-CIT-EMPTY
def test_zero_skills_is_explicit_skip_not_pass(motor: Path):
    _base_motor(motor)
    _commit(motor)

    code, lines = cdb.audit_skill_citations(motor, frozen_debt=())
    joined = "\n".join(lines)
    assert code == 1, joined
    assert "SKIP EXPLICITO" in joined
    assert "NO es un PASS" in joined


# --------------------------------------------------------------- T-CIT-FROZEN
def test_frozen_entry_exempts_violation(motor: Path):
    _base_motor(motor)
    _skill(motor / "skills" / "bad" / "SKILL.md", "source_prompt: prompts/orphan.md")
    _commit(motor)

    code, lines = cdb.audit_skill_citations(
        motor, frozen_debt=(("skills/bad/SKILL.md", "prompts/orphan.md"),)
    )
    assert code == 0, "\n".join(lines)


# ---------------------------------------------------------------- T-CIT-STALE
def test_stale_frozen_entry_fails(motor: Path):
    _base_motor(motor)
    _skill(motor / "skills" / "good" / "SKILL.md", "source_prompt: prompts/travels.md")
    _commit(motor)

    code, lines = cdb.audit_skill_citations(
        motor, frozen_debt=(("skills/good/SKILL.md", "prompts/never.md"),)
    )
    joined = "\n".join(lines)
    assert code == 1, joined
    assert "STALE" in joined


# ----------------------------------------------------------------- T-CIT-REAL
def test_real_repo_is_green():
    """LIVE contract: the real motor tree must audit clean WITH its frozen debt.
    The point IS the real tree -- a synthetic-only suite is blind to it."""
    code, lines = cdb.audit_skill_citations(_ROOT)
    joined = "\n".join(lines)
    assert "referencias normativas auditadas" in joined, joined
    assert code == 0, joined
