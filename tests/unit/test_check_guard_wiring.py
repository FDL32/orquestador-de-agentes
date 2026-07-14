"""Tests for scripts/check_guard_wiring.py (WOT-2026-024u).

The irony to avoid: a guard-of-guards that passes vacuously would be the very defect it
exists to catch. So the counterfactual (`test_a_wired_guard_is_recognised`) is not a nice
extra -- without it, every other test here could pass because `audit()` returns nothing at
all.

Hermetic: each test builds a synthetic motor root. The verdict is decided by the code
under test, never by the state of the real repo (which changes with every ticket -- the
failure mode WOT-2026-020q taught us).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


_SPEC = importlib.util.spec_from_file_location(
    "check_guard_wiring",
    Path(__file__).resolve().parents[2] / "scripts" / "check_guard_wiring.py",
)
cgw = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cgw)


def _motor(tmp_path: Path, *, guards: list[str], hook_invokes: list[str]) -> Path:
    """Synthetic motor: some guards in scripts/, some invoked from a self-running path."""
    (tmp_path / "scripts").mkdir()
    for g in guards:
        (tmp_path / "scripts" / f"{g}.py").write_text("# guard\n", encoding="utf-8")
    hooks = "\n".join(
        f"        entry: uv run python scripts/{g}.py" for g in hook_invokes
    )
    (tmp_path / ".pre-commit-config.yaml").write_text(
        f"repos:\n  - repo: local\n    hooks:\n{hooks}\n", encoding="utf-8"
    )
    return tmp_path


def test_a_wired_guard_is_recognised(tmp_path):
    """COUNTERFACTUAL. Without this, every other test could pass because audit() finds
    nothing at all -- the exact vacuous-green this module exists to prevent.

    Mutation: make is_wired() always return False -> this test fails.
    """
    root = _motor(tmp_path, guards=["check_alpha"], hook_invokes=["check_alpha"])

    wired, unwired = cgw.audit(root)

    assert wired == ["check_alpha"]
    assert unwired == []


def test_an_unwired_guard_is_caught(tmp_path):
    """The whole point: a guard nobody invokes.

    Mutation: make is_wired() always return True -> this test fails.
    """
    root = _motor(
        tmp_path, guards=["check_alpha", "check_orphan"], hook_invokes=["check_alpha"]
    )

    wired, unwired = cgw.audit(root)

    assert wired == ["check_alpha"]
    assert unwired == ["check_orphan"]


def test_an_undeclared_unwired_guard_fails(tmp_path, monkeypatch):
    """A NEW guard, wired nowhere and not declared as debt -> exit 1.

    This is the rule that stops the debt from growing. Mutation: stop treating
    `undeclared` as an error (return 0 regardless) -> this test fails.
    """
    root = _motor(tmp_path, guards=["check_brandnew"], hook_invokes=[])
    monkeypatch.setattr(cgw, "KNOWN_UNWIRED", {})

    assert cgw.main(["--motor-root", str(root)]) == 1


def test_declared_debt_only_warns(tmp_path, monkeypatch):
    """The 15 known-unwired guards must NOT block: a retroactive fail would be dead noise
    and would block every close until all of them are wired.

    Mutation: make declared debt fail too (drop the KNOWN_UNWIRED lookup) -> this fails,
    and so would every close in the repo.
    """
    root = _motor(tmp_path, guards=["check_known"], hook_invokes=[])
    monkeypatch.setattr(cgw, "KNOWN_UNWIRED", {"check_known": "WOT-2026-024u"})

    assert cgw.main(["--motor-root", str(root)]) == 0


def test_strict_mode_fails_on_the_declared_debt_too(tmp_path, monkeypatch):
    """--strict is the retro audit: the debt counts as failure.

    Mutation: ignore --strict -> this test fails.
    """
    root = _motor(tmp_path, guards=["check_known"], hook_invokes=[])
    monkeypatch.setattr(cgw, "KNOWN_UNWIRED", {"check_known": "WOT-2026-024u"})

    assert cgw.main(["--motor-root", str(root), "--strict"]) == 1


def test_a_prompt_citation_is_not_wiring(tmp_path, monkeypatch):
    """The load-bearing distinction. Being named in a prompt/skill/AGENTS.md is a NORM,
    and this repo has broken its own norms repeatedly (the orphan-commit incident, the
    write-guard in 0/13 destinations, the gates the barrier forgot to enumerate).

    Here the guard is cited in a prompt but invoked by nothing that runs on its own: it
    must still count as UNWIRED.

    Mutation: add prompts/ to self_running_paths() -> this test fails, and the check
    starts blessing norms as mechanisms.
    """
    root = _motor(tmp_path, guards=["check_only_a_norm"], hook_invokes=[])
    (root / "prompts").mkdir()
    (root / "prompts" / "some_prompt.md").write_text(
        "Corre `python scripts/check_only_a_norm.py` antes de cerrar.\n",
        encoding="utf-8",
    )

    wired, unwired = cgw.audit(root)

    assert unwired == ["check_only_a_norm"]
    assert wired == []


def test_the_real_repo_has_no_undeclared_unwired_guard():
    """Live contract: every unwired guard in THIS repo is a ticketed exception.

    This is the test that actually holds the line. If you add a guard and wire it
    nowhere, this goes red -- which is the whole point of the module.
    """
    assert cgw.main([]) == 0
