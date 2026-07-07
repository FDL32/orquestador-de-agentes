"""Functional tests for scripts/setup_dev_worktree.ps1 against a real,
throwaway git fixture (never the motor repo itself).

WOT-2026-019m defers actual activation of the worktree (git checkout
--detach / git worktree add / uv venv+sync on the real motor checkout) to
post-closure; this ticket only versions the script and QUICKSTART.md
section, and verifies the script's logic against a disposable fixture
repo created under tmp_path.

The script resolves its own root via $PSScriptRoot (same pattern as
scripts/launch_agent_terminals.ps1), so to exercise it against a fixture
repo we copy the script into a sibling `scripts/` directory inside that
fixture and invoke it from there. `uv` is faked (a tiny script placed
first on PATH) so the test does not depend on network access or a real
pyproject.toml/uv.lock in the throwaway fixture; `git checkout --detach`
and `git worktree add` run for real against the fixture.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest


# setup_dev_worktree.ps1 is Windows-native infrastructure for the motor's
# dev-worktree (PowerShell, backslash sibling paths `..\orquestador_de_agentes_dev`,
# a `.venv\Scripts\python.exe` layout, and a `uv.bat` fake shim). The motor is
# developed on Windows; this script never runs on the Linux CI runner nor on
# Linux destinations. Same policy as tests/unit/test_launcher_powershell_syntax.py
# (Windows-only launcher scripts). On non-Windows (`pwsh` present but no Windows
# semantics) the fake `uv.bat` is not resolved and the script falls back to the
# real `uv`, which is neither the unit under test nor portable — so skip the
# whole module off Windows.
pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="setup_dev_worktree.ps1 is Windows-only motor dev infrastructure",
)

_MOTOR_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT_SOURCE = _MOTOR_ROOT / "scripts" / "setup_dev_worktree.ps1"

_POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")

_FAKE_UV_BAT = """@echo off
if "%1"=="venv" (
    mkdir "%CD%\\.venv\\Scripts" 2>nul
    echo fake > "%CD%\\.venv\\Scripts\\python.exe"
    exit /b 0
)
if "%1"=="sync" (
    exit /b 0
)
exit /b 0
"""

# WOT-2026-019s: the shared _FAKE_UV_BAT above intentionally does not record
# `uv sync` invocations (the pre-existing tests do not need it, and touching
# the shared fake risks perturbing their exact stdout/stderr expectations).
# This variant is local to test_second_run_resyncs_existing_venv: it behaves
# identically to _FAKE_UV_BAT except the "sync" branch appends one line to a
# marker file inside the fixture repo's cwd BEFORE exiting, so the test can
# read back how many times `uv sync` actually ran across successive
# invocations of the script.
_FAKE_UV_BAT_WITH_SYNC_LOG = """@echo off
if "%1"=="venv" (
    mkdir "%CD%\\.venv\\Scripts" 2>nul
    echo fake > "%CD%\\.venv\\Scripts\\python.exe"
    exit /b 0
)
if "%1"=="sync" (
    echo sync >> "%CD%\\.uv_sync_calls.log"
    exit /b 0
)
exit /b 0
"""


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, cwd=cwd, timeout=30
    )


def _init_fixture_repo(repo_path: Path) -> None:
    """Create a minimal real git repo with the script copied into scripts/.

    Mirrors the motor's own layout closely enough for the script's
    $PSScriptRoot/.. resolution to land on the fixture's root, not the
    motor's.
    """
    repo_path.mkdir(parents=True, exist_ok=True)
    result = _git(["init", "-q", "-b", "main"], cwd=repo_path)
    assert result.returncode == 0, result.stderr

    _git(["config", "user.email", "test@example.com"], cwd=repo_path)
    _git(["config", "user.name", "Test User"], cwd=repo_path)
    # WOT-2026-019d/019c lesson: avoid background gc races; irrelevant here
    # (no commit loops) but kept for consistency with the repo's fixture
    # conventions.
    _git(["config", "gc.auto", "0"], cwd=repo_path)

    scripts_dir = repo_path / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_SCRIPT_SOURCE, scripts_dir / "setup_dev_worktree.ps1")

    # Mirrors the real motor repo: .venv/ is gitignored, so the venv the
    # script creates inside the worktree-dev does not itself count as
    # "uncommitted changes" for the -Remove dirty-check.
    (repo_path / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    (repo_path / "README.md").write_text("# fixture\n", encoding="utf-8")
    _git(["add", "."], cwd=repo_path)
    commit = _git(["commit", "-m", "init fixture"], cwd=repo_path)
    assert commit.returncode == 0, commit.stderr


def _fake_uv_dir(tmp_path: Path, script: str = _FAKE_UV_BAT) -> Path:
    """Create a directory containing a fake `uv.bat` shim to prepend to PATH."""
    fake_bin = tmp_path / "fake_bin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    (fake_bin / "uv.bat").write_text(script, encoding="utf-8")
    return fake_bin


def _run_script(
    repo_path: Path, args: list[str], fake_uv_dir: Path
) -> subprocess.CompletedProcess:
    import os

    env = dict(os.environ)
    env["PATH"] = str(fake_uv_dir) + os.pathsep + env.get("PATH", "")

    script_path = repo_path / "scripts" / "setup_dev_worktree.ps1"
    return subprocess.run(
        [
            _POWERSHELL,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            *args,
        ],
        capture_output=True,
        text=True,
        cwd=repo_path,
        timeout=120,
        env=env,
    )


def _worktree_dev_path(repo_path: Path) -> Path:
    # The script hardcodes the sibling name orquestador_de_agentes_dev
    # (matches QUICKSTART.md / work_plan.md literally), regardless of the
    # fixture repo's own directory name.
    return repo_path.parent / "orquestador_de_agentes_dev"


def _current_branch(repo_path: Path) -> str:
    result = _git(["branch", "--show-current"], cwd=repo_path)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _status_short(repo_path: Path) -> str:
    result = _git(["status", "--short"], cwd=repo_path)
    assert result.returncode == 0, result.stderr
    return result.stdout


def _cleanup_worktree(repo_path: Path, worktree_path: Path) -> None:
    if worktree_path.exists():
        _git(["worktree", "remove", "--force", str(worktree_path)], cwd=repo_path)
    _git(["worktree", "prune"], cwd=repo_path)


@pytest.fixture
def fixture_repo(tmp_path: Path):
    if _POWERSHELL is None:
        pytest.skip("PowerShell not available on this host")

    repo_path = tmp_path / "fixture_repo"
    _init_fixture_repo(repo_path)
    fake_uv_dir = _fake_uv_dir(tmp_path)
    worktree_path = _worktree_dev_path(repo_path)

    yield repo_path, fake_uv_dir, worktree_path

    _cleanup_worktree(repo_path, worktree_path)


def test_creation_detaches_principal_and_adds_worktree_with_venv(
    fixture_repo,
) -> None:
    repo_path, fake_uv_dir, worktree_path = fixture_repo

    result = _run_script(repo_path, [], fake_uv_dir)

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert _current_branch(repo_path) == "", (
        "principal checkout should be detached (no current branch) after "
        f"running the script; branch output={_current_branch(repo_path)!r}"
    )
    assert worktree_path.is_dir(), "worktree-dev directory was not created"

    worktree_list = _git(["worktree", "list"], cwd=repo_path).stdout
    assert "(detached HEAD)" in worktree_list
    assert "[main]" in worktree_list

    venv_python = worktree_path / ".venv" / "Scripts" / "python.exe"
    assert venv_python.is_file(), "fake uv venv step did not materialize python.exe"


def test_creation_fails_closed_when_principal_is_dirty(fixture_repo) -> None:
    """WOT-2026-019m: the whole point is that the consumed (principal) checkout
    stays clean. If it has uncommitted changes, the script must NOT detach it
    (which would leave it detached-and-dirty) nor create the worktree: exit 2,
    principal still on `main`, no worktree-dev."""
    repo_path, fake_uv_dir, worktree_path = fixture_repo

    # Dirty the principal checkout with an uncommitted change.
    (repo_path / "README.md").write_text("# fixture DIRTY\n", encoding="utf-8")
    assert _current_branch(repo_path) == "main"

    result = _run_script(repo_path, [], fake_uv_dir)

    assert result.returncode == 2, (
        f"dirty principal must fail closed with exit 2; got {result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    # Principal was NOT detached (still on main) and the worktree was NOT created.
    assert _current_branch(repo_path) == "main", (
        "principal must remain on `main` (not detached) when it is dirty"
    )
    assert not worktree_path.exists(), (
        "worktree-dev must NOT be created when the principal is dirty"
    )


def test_creation_is_idempotent_on_second_run(fixture_repo) -> None:
    repo_path, fake_uv_dir, _worktree_path = fixture_repo

    first = _run_script(repo_path, [], fake_uv_dir)
    assert first.returncode == 0, first.stderr

    second = _run_script(repo_path, [], fake_uv_dir)
    assert second.returncode == 0, (
        f"second run should be idempotent (exit 0); stdout={second.stdout}\n"
        f"stderr={second.stderr}"
    )
    combined = second.stdout + second.stderr
    assert "idempotente" in combined, (
        "second run should report the already-detached/already-exists paths: "
        f"{combined}"
    )


def test_whatif_creation_mutates_nothing(fixture_repo) -> None:
    repo_path, fake_uv_dir, worktree_path = fixture_repo

    branch_before = _current_branch(repo_path)
    status_before = _status_short(repo_path)
    worktree_list_before = _git(["worktree", "list"], cwd=repo_path).stdout

    result = _run_script(repo_path, ["-WhatIf"], fake_uv_dir)

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert _current_branch(repo_path) == branch_before
    assert not worktree_path.exists(), "-WhatIf must not create the worktree"
    assert _git(["worktree", "list"], cwd=repo_path).stdout == worktree_list_before
    # status may legitimately gain the untracked script copy only once, at
    # fixture creation time; -WhatIf itself must add nothing further.
    assert _status_short(repo_path) == status_before


def test_remove_cleans_worktree_and_reattaches_main(fixture_repo) -> None:
    repo_path, fake_uv_dir, worktree_path = fixture_repo

    created = _run_script(repo_path, [], fake_uv_dir)
    assert created.returncode == 0, created.stderr
    assert worktree_path.is_dir()

    removed = _run_script(repo_path, ["-Remove"], fake_uv_dir)
    assert removed.returncode == 0, f"stdout={removed.stdout}\nstderr={removed.stderr}"
    assert not worktree_path.exists(), "worktree directory should be gone"

    worktree_list = _git(["worktree", "list"], cwd=repo_path).stdout
    # WOT-2026-019q: assert against the specific removed worktree path, not a
    # bare "orquestador_de_agentes_dev" substring. The bare substring collides
    # with the sandbox's own absolute path when the suite runs from inside a
    # checkout literally named orquestador_de_agentes_dev (the dev worktree),
    # making this test fail spuriously there while passing from the principal.
    assert str(worktree_path) not in worktree_list
    assert _current_branch(repo_path) == "main", (
        "principal checkout should be re-attached to main after -Remove"
    )


def test_remove_with_uncommitted_changes_fails_closed(fixture_repo) -> None:
    repo_path, fake_uv_dir, worktree_path = fixture_repo

    created = _run_script(repo_path, [], fake_uv_dir)
    assert created.returncode == 0, created.stderr

    # Dirty the worktree-dev with an uncommitted change.
    (worktree_path / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")

    removed = _run_script(repo_path, ["-Remove"], fake_uv_dir)

    assert removed.returncode == 2, (
        f"expected exit 2 for a dirty worktree; got {removed.returncode}\n"
        f"stdout={removed.stdout}\nstderr={removed.stderr}"
    )
    assert worktree_path.is_dir(), "worktree must remain intact on a failed remove"
    assert (worktree_path / "dirty.txt").is_file()

    worktree_list = _git(["worktree", "list"], cwd=repo_path).stdout
    assert "orquestador_de_agentes_dev" in worktree_list
    assert _current_branch(repo_path) == "", (
        "principal checkout must remain detached; -Remove must not run "
        "git checkout main when it fails closed"
    )


def test_regression_add_without_detach_first_fails(fixture_repo) -> None:
    """MUTATION barrier: if the detach-before-add step were removed from the
    script, `git worktree add ... main` would fail with
    `fatal: 'main' is already used by worktree`. This test reproduces that
    exact failure directly (bypassing the script) to document the invariant
    the script's Step-DetachPrincipal/Step-CreateWorktree ordering protects
    against, and to give a fast, script-independent signal if the ordering
    invariant regresses silently.
    """
    repo_path, _fake_uv_dir, worktree_path = fixture_repo

    # Principal is still on `main` here (nothing has detached it yet).
    assert _current_branch(repo_path) == "main"

    result = _git(
        ["worktree", "add", str(worktree_path), "main"],
        cwd=repo_path,
    )

    assert result.returncode != 0
    assert "already used by worktree" in result.stderr


def test_second_run_resyncs_existing_venv(tmp_path: Path) -> None:
    """WOT-2026-019s barrier: Step-CreateVenv must run `uv sync` on every
    invocation, not just the first one where `.venv\\Scripts\\python.exe` is
    absent. A venv can have python.exe present but dependencies missing or
    stale (e.g. a prior `uv sync` failed or pyproject.toml/uv.lock changed
    after the venv was created); silently skipping `uv sync` on subsequent
    runs would report false success while leaving the venv incomplete.

    Uses a local fake uv.bat (_FAKE_UV_BAT_WITH_SYNC_LOG) that appends a line
    to `.uv_sync_calls.log` inside the worktree-dev on every `uv sync`
    invocation, so the number of recorded syncs across successive script runs
    is readable from Python without parsing the script's own stdout.

    FAIL-sin-fix: with the pre-019s script, Step-CreateVenv's `else` branch
    (python.exe already exists) never calls `uv`, so the log stays at 1 line
    after the second run (this test fails on that assertion).
    PASS-con-fix: `uv sync` runs unconditionally, so the log reaches 2 lines
    after the second run.
    """
    if _POWERSHELL is None:
        pytest.skip("PowerShell not available on this host")

    repo_path = tmp_path / "fixture_repo"
    _init_fixture_repo(repo_path)
    fake_uv_dir = _fake_uv_dir(tmp_path, script=_FAKE_UV_BAT_WITH_SYNC_LOG)
    worktree_path = _worktree_dev_path(repo_path)
    sync_log = worktree_path / ".uv_sync_calls.log"

    try:
        first = _run_script(repo_path, [], fake_uv_dir)
        assert first.returncode == 0, (
            f"first run should succeed; stdout={first.stdout}\nstderr={first.stderr}"
        )
        venv_python = worktree_path / ".venv" / "Scripts" / "python.exe"
        assert venv_python.is_file(), "fake uv venv step did not materialize python.exe"

        first_lines = sync_log.read_text(encoding="utf-8").splitlines()
        assert len(first_lines) == 1, (
            "uv sync should be invoked exactly once on the first run (venv "
            f"just created); log contents={first_lines!r}"
        )

        second = _run_script(repo_path, [], fake_uv_dir)
        assert second.returncode == 0, (
            f"second run should succeed; stdout={second.stdout}\nstderr={second.stderr}"
        )

        second_lines = sync_log.read_text(encoding="utf-8").splitlines()
        assert len(second_lines) == 2, (
            "uv sync must be invoked again on the second run even though "
            "python.exe already exists (Step-CreateVenv must not skip "
            f"dependency sync); log contents={second_lines!r}"
        )
    finally:
        _cleanup_worktree(repo_path, worktree_path)
