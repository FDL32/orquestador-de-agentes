"""Tests for scripts/check_guard_wiring.py (WOT-2026-024u).

The irony to avoid: a guard-of-guards that passes vacuously would be the very defect it
exists to catch. So the counterfactual (`test_a_wired_guard_is_recognised`) is not a nice
extra -- without it, every other test here could pass because `audit()` returns nothing.

The four tests marked FALSO-VERDE are the ones an adversarial sibling audit extracted from
the first version of this module, which shipped all four and would have reached origin.
Each of them is a way of blessing a NORM as a MECHANISM -- exactly what the module claims
it will never do. They are the reason this file exists in this shape.

Hermetic: each test builds a synthetic motor root. The verdict is decided by the code
under test, never by the state of the real repo (which changes with every ticket -- the
failure mode WOT-2026-020q taught us). The single exception is the last test, which is a
LIVE contract on this repo and is meant to go red when someone adds an unwired guard.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_SPEC = importlib.util.spec_from_file_location(
    "check_guard_wiring",
    Path(__file__).resolve().parents[2] / "scripts" / "check_guard_wiring.py",
)
cgw = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cgw)


def _motor(
    tmp_path: Path,
    *,
    guards: list[str],
    hooks: list[dict] | None = None,
    extra_yaml: str = "",
) -> Path:
    """Synthetic motor: guards in scripts/, and a pre-commit config that may invoke them."""
    (tmp_path / "scripts").mkdir(exist_ok=True)
    for g in guards:
        (tmp_path / "scripts" / f"{g}.py").write_text("# guard\n", encoding="utf-8")

    body = ["repos:", "  - repo: local", "    hooks:"]
    for h in hooks or []:
        body.append(f"      - id: {h['id']}")
        body.append(f"        entry: uv run python scripts/{h['id']}.py")
        if "stages" in h:
            body.append(f"        stages: [{', '.join(h['stages'])}]")
    if not hooks:
        body.append("      []")
    text = "\n".join(body) + "\n" + extra_yaml
    (tmp_path / ".pre-commit-config.yaml").write_text(text, encoding="utf-8")
    return tmp_path


def test_a_wired_guard_is_recognised(tmp_path):
    """COUNTERFACTUAL. Without this, every other test could pass because audit() finds
    nothing at all -- the exact vacuous-green this module exists to prevent.
    """
    root = _motor(tmp_path, guards=["check_alpha"], hooks=[{"id": "check_alpha"}])

    wired, unwired = cgw.audit(root)

    assert wired == ["check_alpha"]
    assert unwired == []


def test_an_unwired_guard_is_caught(tmp_path):
    """The whole point: a guard nobody invokes."""
    root = _motor(
        tmp_path,
        guards=["check_alpha", "check_orphan"],
        hooks=[{"id": "check_alpha"}],
    )

    wired, unwired = cgw.audit(root)

    assert wired == ["check_alpha"]
    assert unwired == ["check_orphan"]


def test_a_prompt_citation_is_not_wiring(tmp_path):
    """The load-bearing distinction: being named in a prompt is a NORM, not a mechanism."""
    root = _motor(tmp_path, guards=["check_only_a_norm"], hooks=[])
    (root / "prompts").mkdir()
    (root / "prompts" / "p.md").write_text(
        "Corre `python scripts/check_only_a_norm.py` antes de cerrar.\n",
        encoding="utf-8",
    )

    wired, unwired = cgw.audit(root)

    assert unwired == ["check_only_a_norm"]
    assert wired == []


def test_a_yaml_comment_is_not_wiring(tmp_path):
    """FALSO-VERDE #1 (real, shipped): the first version matched raw text, so a guard named
    only inside a YAML comment counted as wired.

    In the live repo that was `check_ruff_hook_scope`: its ONE appearance in
    .pre-commit-config.yaml is the comment `# Hook scope protected by
    scripts/check_ruff_hook_scope.py`, and nothing executes it. The guard-of-guards was
    blessing it.

    Mutation: go back to substring-matching the raw file text -> this test fails.
    """
    root = _motor(
        tmp_path,
        guards=["check_mentioned_in_a_comment"],
        hooks=[],
        extra_yaml="# protected by scripts/check_mentioned_in_a_comment.py\n",
    )

    wired, unwired = cgw.audit(root)

    assert unwired == ["check_mentioned_in_a_comment"], "un comentario no ejecuta nada"
    assert wired == []


def test_a_manual_only_hook_is_not_wiring(tmp_path):
    """FALSO-VERDE #2 (real, shipped): a hook with `stages: [manual]` does not run on its
    own -- a human must remember to invoke it, which is the definition of a norm.

    Live case: `check_hook_interpreter`. Mutation: count manual hooks -> this fails.
    """
    root = _motor(
        tmp_path,
        guards=["check_manual", "check_auto"],
        hooks=[
            {"id": "check_manual", "stages": ["manual"]},
            {"id": "check_auto", "stages": ["pre-commit"]},
        ],
    )

    wired, unwired = cgw.audit(root)

    assert wired == ["check_auto"]
    assert unwired == ["check_manual"]


def test_a_hook_on_pre_push_is_wiring(tmp_path):
    """...but `stages: [pre-push, manual]` DOES run on its own (pre-push is automatic).

    The falso-rojo twin of the test above: over-correcting would make every multi-stage
    hook look unwired. Mutation: treat any hook listing `manual` as non-automatic -> fails.
    """
    root = _motor(
        tmp_path,
        guards=["check_prepush"],
        hooks=[{"id": "check_prepush", "stages": ["pre-push", "manual"]}],
    )

    wired, _ = cgw.audit(root)

    assert wired == ["check_prepush"]


def test_a_name_that_is_a_prefix_of_a_wired_guard_is_not_wired(tmp_path):
    """FALSO-VERDE #3 (real, shipped): substring matching meant a NEW `check_backlog.py`
    would be blessed by the existing `check_backlog_commits_landed`, because
    `"check_backlog" in "...check_backlog_commits_landed..."` is True.

    That silently voids the module's only fail-closed rule. Mutation: drop the word
    boundaries from is_wired() -> this test fails.
    """
    root = _motor(
        tmp_path,
        guards=["check_alpha", "check_alpha_extended"],
        hooks=[{"id": "check_alpha_extended"}],
    )

    wired, unwired = cgw.audit(root)

    assert wired == ["check_alpha_extended"]
    assert unwired == ["check_alpha"], "el prefijo no hereda el cableado del largo"


def test_guards_outside_scripts_are_inventoried(tmp_path):
    """FALSO-VERDE #4 (real, shipped): find_guards() only globbed scripts/, so the
    write-guard `.agent/hooks/guard_paths.py` -- the example the module's own docstring
    cites as THE disease -- was not even in the inventory.

    An inventory blind to a whole directory reports 'all clear' about a place it never
    looked. Mutation: restrict GUARD_DIRS back to ('scripts',) -> this test fails.
    """
    root = _motor(tmp_path, guards=[], hooks=[])
    (root / ".agent" / "hooks").mkdir(parents=True)
    (root / ".agent" / "hooks" / "guard_elsewhere.py").write_text(
        "# guard\n", encoding="utf-8"
    )

    assert "guard_elsewhere" in cgw.find_guards(root)


def test_an_undeclared_unwired_guard_fails(tmp_path, monkeypatch):
    """The rule that stops the debt from growing: a NEW guard, wired nowhere, undeclared."""
    root = _motor(tmp_path, guards=["check_brandnew"], hooks=[])
    monkeypatch.setattr(cgw, "KNOWN_UNWIRED", {})

    assert cgw.main(["--motor-root", str(root)]) == 1


def test_declared_debt_only_warns(tmp_path, monkeypatch):
    """Declared debt must NOT block: a retroactive fail would be dead noise and would
    block every close until every guard is wired.
    """
    root = _motor(tmp_path, guards=["check_known"], hooks=[])
    monkeypatch.setattr(cgw, "KNOWN_UNWIRED", {"check_known": "WOT-2026-024u"})

    assert cgw.main(["--motor-root", str(root)]) == 0


def test_strict_mode_fails_on_the_declared_debt(tmp_path, monkeypatch):
    """--strict is the retro audit: the debt counts as failure."""
    root = _motor(tmp_path, guards=["check_known"], hooks=[])
    monkeypatch.setattr(cgw, "KNOWN_UNWIRED", {"check_known": "WOT-2026-024u"})

    assert cgw.main(["--motor-root", str(root), "--strict"]) == 1


def test_strict_mode_does_not_fail_on_a_by_design_exemption(tmp_path, monkeypatch):
    """...but a BY-DESIGN exemption is not debt: nobody will ever 'pay' it.

    `check_hook_interpreter` is manual on purpose -- an automatic hook would be circular.
    If --strict failed on it, the retro audit could never reach zero and would be ignored.
    Mutation: treat BY-DESIGN as debt -> this test fails.
    """
    root = _motor(tmp_path, guards=["check_by_design"], hooks=[])
    monkeypatch.setattr(
        cgw, "KNOWN_UNWIRED", {"check_by_design": "BY-DESIGN: circular por naturaleza"}
    )

    assert cgw.main(["--motor-root", str(root), "--strict"]) == 0


def test_a_stale_allowlist_entry_fails(tmp_path, monkeypatch):
    """An entry for a guard that IS wired (or no longer exists) must be removed.

    Otherwise the allowlist rots into a cemetery, and -- worse -- it pre-blesses any
    future file with that name: someone creates scripts/check_ghost.py years later and it
    sails through, already 'declared'. Mutation: stop reporting stale entries -> fails.
    """
    root = _motor(tmp_path, guards=["check_alpha"], hooks=[{"id": "check_alpha"}])
    monkeypatch.setattr(cgw, "KNOWN_UNWIRED", {"check_alpha": "WOT-2026-024u"})

    assert cgw.main(["--motor-root", str(root)]) == 1


def test_a_free_text_owner_is_rejected(tmp_path, monkeypatch):
    """The owner must be a ticket or an explicit BY-DESIGN reason.

    Free text is how the ghost ticket WOT-2026-021a survived: decision accepted, zero rows
    in the backlog. An owner nobody can look up is not an owner. Mutation: skip the owner
    format check -> this test fails.
    """
    root = _motor(tmp_path, guards=["check_known"], hooks=[])
    monkeypatch.setattr(cgw, "KNOWN_UNWIRED", {"check_known": "pendiente, ya lo vere"})

    assert cgw.main(["--motor-root", str(root)]) == 1


def test_an_unreadable_self_running_path_fails_closed(tmp_path):
    """If a self-running path cannot be parsed, we CANNOT claim any guard is wired.

    Staying quiet here would be the module's own disease: a missing denominator reported
    as 'all clear'. Mutation: swallow the exception and continue -> this test fails.
    """
    root = _motor(tmp_path, guards=["check_alpha"], hooks=[{"id": "check_alpha"}])
    (root / ".pre-commit-config.yaml").write_text(
        "repos: [ unclosed\n", encoding="utf-8"
    )

    with pytest.raises(SystemExit):
        cgw.audit(root)


def test_the_real_repo_has_no_undeclared_unwired_guard():
    """LIVE contract on THIS repo -- and the only thing that can catch this module being
    unwired from itself.

    check_guard_wiring does not exempt itself from the inventory, but it obviously cannot
    fail when nothing runs it. This test can: it runs in the suite, the suite runs in CI.
    Delete the pre-commit hook and CI goes red. That is what closes the loop.
    """
    assert cgw.main([]) == 0
