"""Unit tests for prefix_resolver.py (WOT-2026-020s).

Covers: resolve known/unknown/duplicate, WOT->motor, None->error,
malformed->error, guard mismatch blocks, mutation (without guard no block),
verify detects duplicates/drift, project-name resolution.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from scripts.prefix_resolver import (
    discover_motor_root,
    extract_prefix,
    guard,
    resolve_by_project_name,
    resolve_prefix,
    scan_links,
)


def _make_link(
    dest_root: Path,
    motor_root: Path,
    prefix: str | None,
    dest_id: str | None = None,
) -> None:
    """Create a motor_destination_link.json in dest_root."""
    link_dir = dest_root / ".agent" / "config"
    link_dir.mkdir(parents=True, exist_ok=True)
    data: dict = {
        "motor_root": str(motor_root),
        "destination_root": str(dest_root),
        "motor_version": "v9.17.1",
    }
    if prefix is not None:
        data["ticket_prefix"] = prefix
    if dest_id is not None:
        data["destination_id"] = dest_id
    (link_dir / "motor_destination_link.json").write_text(
        json.dumps(data), encoding="utf-8"
    )


def _make_motor(tmp_path: Path) -> Path:
    """Create a fake motor root with agent_controller.py."""
    motor = tmp_path / "motor"
    agent_dir = motor / ".agent"
    agent_dir.mkdir(parents=True)
    (agent_dir / "agent_controller.py").write_text("# motor\n", encoding="utf-8")
    return motor


def _git_init_main(repo_path: Path) -> None:
    """Init a git repo at repo_path with the branch forced to 'main'.

    Before: repo_path exists as a plain directory (no .git yet).
    During: `git init -b main` (git >= 2.28). Explicitly forces the branch
            name instead of relying on init.defaultBranch, which is 'main'
            on this machine but 'master' on the CI runner (no such config
            there) -- an unforced init would false-RED the
            `symbolic-ref --short HEAD == "main"` check ONLY in CI. Also
            configures a throwaway user.email/user.name (needed for commit)
            and creates one commit so the branch ref actually exists (an
            empty repo has no commits and `symbolic-ref HEAD` would still
            resolve, but rev-parse/worktree operations are more robust with
            at least one commit).
    After: repo_path is a git repo on branch 'main' with one commit.
    """
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=repo_path, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    (repo_path / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )


def _make_git_tree(tmp_path: Path) -> tuple[Path, Path]:
    """Create a synthetic motor + _dev worktree pair, mirroring real topology.

    Before: tmp_path is an empty pytest tmp_path fixture.
    During: creates a real git repo at <tmp_path>/motor (branch 'main',
            forced explicitly via `git init -b main`, one commit), then
            detaches motor's HEAD (`git checkout --detach main`) BEFORE
            adding the linked worktree -- git refuses to have the same
            branch checked out in two worktrees at once
            ("fatal: 'main' is already used by worktree at ..."), so the
            _dev worktree cannot check out 'main' while motor still has it
            checked out. Detaching motor first mirrors the REAL topology of
            this machine exactly (verified live: the primary checkout is
            `(detached HEAD)`, only `_dev` carries `main` --
            see work_plan.md "Verificacion en vivo",
            `git worktree list` output). Then adds a real linked worktree
            at <tmp_path>/motor_dev via `git worktree add <path> main`
            (checks out the EXISTING 'main' branch, now free). This is a
            NEW, SEPARATE helper from _make_tree: used ONLY by the
            WOT-branch tests that need real git repos (guard()'s
            git-common-dir comparison, and Fase 4's _check_wot_topology),
            never by the ~15 pre-existing tests that use the plain
            _make_tree fixture.
    After: returns (motor_root, dev_root): motor_root is a detached-HEAD
          git worktree, dev_root is a linked worktree of the SAME repo
          (same git-common-dir) on branch 'main' -- the exact shape guard()
          and check_worktree_topology.py must recognize as "same motor,
          _dev correctly on main".
    """
    motor = tmp_path / "motor"
    motor.mkdir()
    _git_init_main(motor)
    subprocess.run(
        ["git", "checkout", "--detach", "main"],
        cwd=motor,
        check=True,
        capture_output=True,
    )
    dev = tmp_path / "motor_dev"
    subprocess.run(
        ["git", "worktree", "add", str(dev), "main"],
        cwd=motor,
        check=True,
        capture_output=True,
    )
    return motor, dev


def _make_tree(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    """Create motor + EXF + CTL destinations + the WOT workspace under tmp_path.

    The workspace declares ticket_prefix "WOT" exactly like the 12 real
    destinations declare theirs (WOT-2026-023i). Before that ticket the real
    link carried ticket_prefix: null and prefix_resolver hardcoded an
    early-return for WOT, so the fixture didn't need it; now WOT resolves
    through the same scan as every other prefix and the fixture must mirror
    the real topology.

    Returns (motor_root, exf_root, ctl_root, search_root).
    """
    search_root = tmp_path / "projects"
    search_root.mkdir()
    motor = search_root / "orquestador_de_agentes"
    motor.mkdir()
    (motor / ".agent").mkdir(parents=True)
    (motor / ".agent" / "agent_controller.py").write_text("# motor\n", encoding="utf-8")
    exf = search_root / "Extractor_Facturas_PDF_Seguro"
    exf.mkdir()
    ctl = search_root / "Crear_Texto_LLM"
    ctl.mkdir()
    workspace = search_root / "orquestador_de_agentes_workspace"
    workspace.mkdir()
    _make_link(exf, motor, "EXF", "Extractor_Facturas_PDF_Seguro")
    _make_link(ctl, motor, "CTL", "Crear_Texto_LLM")
    _make_link(workspace, motor, "WOT", "orquestador_de_agentes_workspace")
    return motor, exf, ctl, search_root


# ---------------------------------------------------------------------------
# resolve_prefix
# ---------------------------------------------------------------------------


def test_resolve_known_prefix(tmp_path: Path) -> None:
    motor, exf, ctl, _ = _make_tree(tmp_path)
    assert resolve_prefix("EXF", motor) == exf
    assert resolve_prefix("CTL", motor) == ctl


def test_resolve_wot_returns_workspace_via_scan(tmp_path: Path) -> None:
    """WOT-2026-023i: WOT resolves through scan_links like every other prefix.

    It used to short-circuit to motor_root via a hardcoded early-return,
    which existed only because the real workspace link carried
    ticket_prefix: null. The link now declares "WOT", so the generic path
    works and the special case is gone. Where WOT is WORKED (the _dev
    worktree) and where it is COMMITTED (repo_motor) are different axes --
    see scripts/check_worktree_topology.py.
    """
    motor, _, _, search_root = _make_tree(tmp_path)
    workspace = search_root / "orquestador_de_agentes_workspace"
    assert resolve_prefix("WOT", motor) == workspace
    assert resolve_prefix("WOT", motor) != motor


def test_resolve_wot_duplicate_returns_none(tmp_path: Path) -> None:
    """WOT-2026-023i: with the special case gone, WOT is subject to the same
    ambiguity rule as any other prefix -- two links declaring it resolve to
    None. This failure mode did not exist while the early-return masked it,
    and it is why guard() must not require a resolution for WOT (a duplicate
    would otherwise block every WOT ticket; see
    test_guard_wot_passes_from_motor_without_wot_link)."""
    motor, _, _, search_root = _make_tree(tmp_path)
    dup = search_root / "otro_workspace"
    dup.mkdir()
    _make_link(dup, motor, "WOT", "otro_workspace")
    assert resolve_prefix("WOT", motor) is None


def test_resolve_unknown_prefix_returns_none(tmp_path: Path) -> None:
    motor, _, _, _ = _make_tree(tmp_path)
    assert resolve_prefix("XYZ", motor) is None


def test_resolve_none_prefix_returns_none(tmp_path: Path) -> None:
    motor, _, _, _ = _make_tree(tmp_path)
    assert resolve_prefix(None, motor) is None


def test_resolve_duplicate_prefix_returns_none(tmp_path: Path) -> None:
    motor, _exf, _ctl, search_root = _make_tree(tmp_path)
    # Create a second destination with the same prefix
    dup = search_root / "Another_EXF"
    dup.mkdir()
    _make_link(dup, motor, "EXF", "Another_EXF")
    assert resolve_prefix("EXF", motor) is None


def test_resolve_skips_null_prefix(tmp_path: Path) -> None:
    motor, exf, _ctl, search_root = _make_tree(tmp_path)
    # Add a destination with null prefix
    null_dest = search_root / "NoPrefix"
    null_dest.mkdir()
    _make_link(null_dest, motor, None, "NoPrefix")
    # EXF and CTL still resolve; null-prefix dest is not in the map
    assert resolve_prefix("EXF", motor) == exf
    assert resolve_prefix("NoPrefix", motor) is None


# ---------------------------------------------------------------------------
# extract_prefix
# ---------------------------------------------------------------------------


def test_extract_prefix_from_ticket_id() -> None:
    assert extract_prefix("WOT-2026-020t") == "WOT"
    assert extract_prefix("EXF-2026-010a") == "EXF"


def test_extract_prefix_project_name_returns_none() -> None:
    assert extract_prefix("Extractor_Facturas_PDF_Seguro") is None


def test_extract_prefix_malformed_raises() -> None:
    with pytest.raises(ValueError, match="Malformed"):
        extract_prefix("WOT-2026-020")
    with pytest.raises(ValueError, match="Malformed"):
        extract_prefix("wot-2026-020t")


def test_extract_prefix_malformed_short_sequence_raises() -> None:
    with pytest.raises(ValueError, match="Malformed"):
        extract_prefix("ABC-2026-1a")


def test_extract_prefix_empty_string_returns_none() -> None:
    assert extract_prefix("") is None


# ---------------------------------------------------------------------------
# guard
# ---------------------------------------------------------------------------


def test_guard_match_returns_zero(tmp_path: Path) -> None:
    motor, exf, _, _ = _make_tree(tmp_path)
    assert guard("EXF-2026-010a", cwd=exf, motor_root=motor) == 0


def test_guard_mismatch_blocks(tmp_path: Path) -> None:
    motor, exf, _ctl, _ = _make_tree(tmp_path)
    # cwd is EXF but ticket is CTL -> mismatch -> block
    assert guard("CTL-2026-001a", cwd=exf, motor_root=motor) == 1


def test_guard_wot_in_motor_passes(tmp_path: Path) -> None:
    """cwd == motor_root (same directory). Under the fail-closed-per-side
    degradation of the WOT git-common-dir fix, a plain _make_tree directory
    (no .git) would make BOTH sides fail to resolve git-common-dir, and the
    guard would return 1 (degraded) instead of 0 (same real motor). This
    test's local fixture DELIBERATELY gains a real `git init` (via
    _git_init_main) on top of _make_tree, so it keeps representing a
    "same real motor" case -> exit 0. _make_tree itself stays untouched;
    only this test's own directory is git-initialized in addition."""
    motor, _, _, _ = _make_tree(tmp_path)
    _git_init_main(motor)
    assert guard("WOT-2026-020t", cwd=motor, motor_root=motor) == 0


def test_guard_wot_in_destination_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """cwd=exf (destination, no git init), prefix=WOT so resolved=motor
    (also no git init). Neither _make_tree directory has its own .git, so
    without isolation git's ambient discovery would ASCEND past tmp_path
    into whatever real repo contains the pytest tmp dir (this repo itself,
    since the test sandbox lives under this worktree) and find a git-
    common-dir there for BOTH sides -- producing a false MATCH (0) instead
    of the intended degraded mismatch (1). GIT_CEILING_DIRECTORIES stops
    git's directory-discovery walk at tmp_path, so neither side resolves to
    a repo -> fail-closed degradation -> exit 1, exactly the pre-fix
    behavior (mismatch by literal path) preserved for a different reason.
    This is test-fixture isolation only; production code (_git_common_dir)
    is untouched."""
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    motor, exf, _, _ = _make_tree(tmp_path)
    # cwd is EXF but ticket is WOT -> resolves to motor -> mismatch -> block
    assert guard("WOT-2026-020t", cwd=exf, motor_root=motor) == 1


def test_guard_unknown_prefix_returns_2(tmp_path: Path) -> None:
    motor, exf, _, _ = _make_tree(tmp_path)
    assert guard("XYZ-2026-001a", cwd=exf, motor_root=motor) == 2


def test_guard_malformed_id_returns_2(tmp_path: Path) -> None:
    motor, exf, _, _ = _make_tree(tmp_path)
    assert guard("wot-2026-020t", cwd=exf, motor_root=motor) == 2


def test_guard_project_name_match(tmp_path: Path) -> None:
    motor, exf, _, _ = _make_tree(tmp_path)
    assert guard("Extractor_Facturas_PDF_Seguro", cwd=exf, motor_root=motor) == 0


def test_guard_project_name_mismatch_blocks(tmp_path: Path) -> None:
    motor, exf, _ctl, _ = _make_tree(tmp_path)
    assert guard("Crear_Texto_LLM", cwd=exf, motor_root=motor) == 1


def test_guard_wot_from_dev_worktree_passes(tmp_path: Path) -> None:
    """WOT-2026-021g: guard() from the _dev worktree (rama main) must
    recognize it as the SAME motor as the detached primary checkout, via
    git-common-dir comparison -- this is the exact bug fix under test."""
    motor, dev = _make_git_tree(tmp_path)
    assert guard("WOT-2026-021g", cwd=dev, motor_root=motor) == 0


def test_guard_wot_passes_from_motor_without_wot_link(tmp_path: Path) -> None:
    """WOT-2026-023i (BLOCKER-1): guard() must authorize a WOT ticket from a
    worktree of the motor EVEN IF the WOT prefix does not resolve.

    guard()'s WOT branch answers "is cwd the same git repo as motor_root",
    which does not depend on where WOT resolves to. Before the fix, guard()
    demanded a resolution first (`if resolved is None: return 2`) -- harmless
    only because the early-return guaranteed one. With the early-return gone,
    requiring a resolution would make a missing WOT link (this test) or a
    duplicate one (the next) return 2 and block every WOT ticket from the
    correct worktree.

    Mutation-to-prove: move the WOT branch back below the `resolved is None`
    check and this test goes red with exit 2.
    """
    motor = tmp_path / "motor"
    motor.mkdir()
    _git_init_main(motor)
    # No link anywhere: resolve_prefix("WOT") is None.
    assert resolve_prefix("WOT", motor) is None
    assert guard("WOT-2026-023i", cwd=motor, motor_root=motor) == 0


def test_guard_wot_passes_from_motor_with_duplicate_wot_link(tmp_path: Path) -> None:
    """WOT-2026-023i (BLOCKER-1): same as above for the AMBIGUOUS case. Two
    links declaring ticket_prefix WOT make resolve_prefix return None; guard()
    must still authorize from the motor's own worktree."""
    motor, _, _, search_root = _make_tree(tmp_path)
    _git_init_main(motor)
    dup = search_root / "otro_workspace"
    dup.mkdir()
    _make_link(dup, motor, "WOT", "otro_workspace")
    assert resolve_prefix("WOT", motor) is None
    assert guard("WOT-2026-023i", cwd=motor, motor_root=motor) == 0


def test_guard_wot_mismatch_message_does_not_cite_resolved(
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WOT-2026-023i: the WOT mismatch message must talk about repos (cwd vs
    motor), never about where the WOT prefix RESOLVES to.

    Once the WOT special-case in prefix_resolver.resolve_prefix is retired,
    'WOT' resolves through the links like any other prefix -- to the
    WORKSPACE destination, not to the motor. A message citing that resolved
    path would read "resolves to ..._workspace, but cwd is ..._workspace",
    i.e. it would claim cwd differs from itself. guard()'s WOT branch does
    not consult the resolution at all (it compares git-common-dir), so its
    message must not cite it either.

    Mutation-to-prove: re-introduce {resolved} into that f-string and this
    test goes red. Before this test existed, NOTHING in the suite asserted
    on the TEXT of guard()'s messages (verified: deleting {resolved}
    produced a delta of 0 failures).

    cwd must be a DIFFERENT REAL git repo, not a plain directory: a plain
    directory takes the fail-closed branch ("cannot determine
    git-common-dir"), which is a different message entirely.
    """
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    motor = tmp_path / "motor"
    motor.mkdir()
    _git_init_main(motor)
    other_repo = tmp_path / "not_the_motor"
    other_repo.mkdir()
    _git_init_main(other_repo)

    assert guard("WOT-2026-023i", cwd=other_repo, motor_root=motor) == 1
    err = capsys.readouterr().err
    assert "different git repo" in err
    assert str(other_repo) in err
    # The barrier: the resolved destination must NOT appear in the message.
    assert "resolves to" not in err


def test_guard_wot_cwd_not_git_repo_returns_one_no_crash(tmp_path: Path) -> None:
    """WOT-2026-021g: fail-closed degradation. cwd is a plain directory
    (no git init) while motor_root IS a real git repo. guard() must return
    1 deterministically -- never raise CalledProcessError or any other
    uncaught exception."""
    motor = tmp_path / "motor"
    motor.mkdir()
    _git_init_main(motor)
    bare_cwd = tmp_path / "not_a_repo"
    bare_cwd.mkdir()
    result = guard("WOT-2026-021g", cwd=bare_cwd, motor_root=motor)
    assert result == 1


# ---------------------------------------------------------------------------
# mutation: without guard, mismatch is not detected
# ---------------------------------------------------------------------------


def test_mutation_without_guard_mismatch_not_blocked(tmp_path: Path) -> None:
    """If the guard is removed (not called), a prefix/cwd mismatch goes
    undetected. This proves the guard IS the barrier: resolve_prefix alone
    never blocks, it just returns the path."""
    motor, exf, ctl, _ = _make_tree(tmp_path)
    # Without guard: resolve CTL -> ctl_root (no comparison, no blocking)
    resolved = resolve_prefix("CTL", motor)
    assert resolved == ctl
    # The mismatch (cwd=exf, resolved=ctl) is NOT detected without the guard
    # Simulate "guard removed": just resolve, don't compare
    assert resolved != exf  # they ARE different, but nothing blocks


# ---------------------------------------------------------------------------
# discover_motor_root
# ---------------------------------------------------------------------------


def test_discover_motor_root_from_destination_link(tmp_path: Path) -> None:
    motor, exf, _, _ = _make_tree(tmp_path)
    assert discover_motor_root(exf) == motor


def test_discover_motor_root_when_cwd_is_motor(tmp_path: Path) -> None:
    motor, _, _, _ = _make_tree(tmp_path)
    assert discover_motor_root(motor) == motor


def test_discover_motor_root_undiscoverable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WOT-2026-045g: a bare tmp_path must be undiscoverable regardless of the
    process environment. discover_motor_root's third path consults
    AGENT_PROJECT_ROOT; the canonical suite runs with that variable exported
    (run_pytest_safe.py is invoked with it), so without isolation this test
    returns the real motor and goes red for whoever measures the motor the
    documented way. delenv isolates the test, not the resolver."""
    monkeypatch.delenv("AGENT_PROJECT_ROOT", raising=False)
    bare = tmp_path / "bare"
    bare.mkdir()
    assert discover_motor_root(bare) is None


# ---------------------------------------------------------------------------
# scan_links
# ---------------------------------------------------------------------------


def test_scan_links_finds_all(tmp_path: Path) -> None:
    _motor, exf, ctl, search_root = _make_tree(tmp_path)
    mapping = scan_links(search_root)
    assert "EXF" in mapping
    assert "CTL" in mapping
    assert mapping["EXF"] == [exf]
    assert mapping["CTL"] == [ctl]


def test_scan_links_empty_when_no_links(tmp_path: Path) -> None:
    search_root = tmp_path / "empty"
    search_root.mkdir()
    assert scan_links(search_root) == {}


# ---------------------------------------------------------------------------
# resolve_by_project_name
# ---------------------------------------------------------------------------


def test_resolve_by_project_name(tmp_path: Path) -> None:
    motor, exf, _, _ = _make_tree(tmp_path)
    assert resolve_by_project_name("Extractor_Facturas_PDF_Seguro", motor) == exf


def test_resolve_by_project_name_not_found(tmp_path: Path) -> None:
    motor, _, _, _ = _make_tree(tmp_path)
    assert resolve_by_project_name("Nonexistent", motor) is None


# ---------------------------------------------------------------------------
# CLI (integration via main)
# ---------------------------------------------------------------------------


def test_cli_resolve_prints_path(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    motor, exf, _, _ = _make_tree(tmp_path)
    from scripts.prefix_resolver import main

    rc = main(["--resolve", "EXF", "--motor-root", str(motor)])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert Path(out) == exf


def test_cli_resolve_unknown_exits_1(tmp_path: Path) -> None:
    motor, _, _, _ = _make_tree(tmp_path)
    from scripts.prefix_resolver import main

    rc = main(["--resolve", "XYZ", "--motor-root", str(motor)])
    assert rc == 1


def test_cli_resolve_malformed_exits_2(tmp_path: Path) -> None:
    motor, _, _, _ = _make_tree(tmp_path)
    from scripts.prefix_resolver import main

    rc = main(["--resolve", "exf", "--motor-root", str(motor)])
    assert rc == 2


def test_cli_resolve_prefix_with_numbers_exits_2(tmp_path: Path) -> None:
    motor, _, _, _ = _make_tree(tmp_path)
    from scripts.prefix_resolver import main

    rc = main(["--resolve", "EXF2", "--motor-root", str(motor)])
    assert rc == 2


def test_cli_resolve_empty_prefix_exits_2(tmp_path: Path) -> None:
    motor, _, _, _ = _make_tree(tmp_path)
    from scripts.prefix_resolver import main

    rc = main(["--resolve", "", "--motor-root", str(motor)])
    assert rc == 2


def test_cli_guard_mismatch_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    motor, exf, _ctl, _ = _make_tree(tmp_path)
    from scripts.prefix_resolver import main

    monkeypatch.chdir(exf)
    rc = main(["--guard", "CTL-2026-001a", "--motor-root", str(motor)])
    assert rc == 1


def test_cli_guard_match_exits_0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    motor, exf, _, _ = _make_tree(tmp_path)
    from scripts.prefix_resolver import main

    monkeypatch.chdir(exf)
    rc = main(["--guard", "EXF-2026-010a", "--motor-root", str(motor)])
    assert rc == 0


def test_cli_verify_detects_duplicate(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    motor, _exf, _ctl, search_root = _make_tree(tmp_path)
    dup = search_root / "Dup_EXF"
    dup.mkdir()
    _make_link(dup, motor, "EXF", "Dup_EXF")
    from scripts.prefix_resolver import main

    rc = main(["--verify", "--motor-root", str(motor)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "DUPLICATE" in err
    assert "EXF" in err


def test_cli_verify_clean_exits_0(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    motor, _, _, _ = _make_tree(tmp_path)
    from scripts.prefix_resolver import main

    rc = main(["--verify", "--motor-root", str(motor)])
    assert rc == 0
