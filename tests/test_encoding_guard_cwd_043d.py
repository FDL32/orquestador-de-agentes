"""WOT-2026-043d: the staged-path encoding guard audits the REAL tree (cwd),
never the module anchor (ROOT = parent of scripts/).

DoD under test:
(a) the guard root resolves from the real cwd (fail-closed exit 2 when the cwd
    is not inside a git tree);
(b) two-direction mutation: mojibake staged in a foreign repo (cwd != motor
    ROOT) -> RED; the same clean -> GREEN;
(c) BOTH anchors covered by independent tests: the enumerator via the CLI, the
    scope (collect_files_to_check / is_in_scope / iter_staged_files) in-process
    against a foreign root;
(d) anti-false-positive: invoked from the clean motor -> GREEN;
(e) mutation evidence via stash-revert of the anchoring is recorded in the
    ticket execution log (which node falls, and that only the anchor tests do).

The invariant is cwd-vs-ROOT divergence, so fixtures use plain `git init` in
tmp_path (no `git worktree add`), per the ticket's own method note. The
mojibake literal below is deliberate fixture data, same exception class as
tests/test_encoding_edge_cases.py (the guard's scope never covers tests/).
"""

import subprocess
import sys
from pathlib import Path

import pytest
from scripts.encoding_guard import is_in_scope, iter_staged_files


ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "scripts" / "check_encoding_guard.py"

# Real mojibake: "configuracion" double-encoded (UTF-8 read back as cp1252).
_MOJIBAKE = "# Documento de configuraciÃ³n del proyecto\n"
_CLEAN = "# Documento de configuracion del proyecto\n"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _init_foreign_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "foreign_repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    return repo


def _run_guard(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GUARD), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


# ---------------------------------------------------------------------------
# (b) two-direction mutation on a foreign index, via the CLI (enumerator path)
# ---------------------------------------------------------------------------


def test_foreign_index_with_mojibake_is_blocked(tmp_path):
    """Staged mojibake in a foreign repo (cwd != motor ROOT) must be RED."""
    repo = _init_foreign_repo(tmp_path)
    (repo / "corrupt.md").write_text(_MOJIBAKE, encoding="utf-8")
    _git(repo, "add", "corrupt.md")

    result = _run_guard(repo)

    assert result.returncode == 1, result.stderr
    assert "Encoding guard blocked this commit" in result.stderr
    assert "Mojibake detected" in result.stderr


def test_foreign_index_clean_is_green(tmp_path):
    """The same foreign repo with a clean staged file must stay GREEN."""
    repo = _init_foreign_repo(tmp_path)
    (repo / "clean.md").write_text(_CLEAN, encoding="utf-8")
    _git(repo, "add", "clean.md")

    result = _run_guard(repo)

    assert result.returncode == 0, result.stderr


def test_foreign_index_out_of_scope_stays_green(tmp_path):
    """Scope semantics are preserved per-tree: a staged file outside the
    foreign tree's scope is not audited (negative control for (b))."""
    repo = _init_foreign_repo(tmp_path)
    nested = repo / "nested"
    nested.mkdir()
    (nested / "corrupt.txt").write_text(_MOJIBAKE, encoding="utf-8")
    _git(repo, "add", "nested/corrupt.txt")

    result = _run_guard(repo)

    assert result.returncode == 0, result.stderr


def test_foreign_static_scope_work_plan_is_blocked(tmp_path):
    """L801 refutation (Codex): the canonical static surfaces resolve RELATIVE
    to the audited tree. A staged, corrupted `.agent/collaboration/work_plan.md`
    in a foreign repo (cwd != motor ROOT) must be RED: the glob patterns never
    covered `.agent/**/*.md`, so under a motor-only static set this file stayed
    invisible in any foreign tree (residual false green)."""
    repo = _init_foreign_repo(tmp_path)
    static_file = repo / ".agent" / "collaboration" / "work_plan.md"
    static_file.parent.mkdir(parents=True)
    static_file.write_text(_MOJIBAKE, encoding="utf-8")
    _git(repo, "add", ".agent/collaboration/work_plan.md")

    result = _run_guard(repo)

    assert result.returncode == 1, result.stderr
    assert "Mojibake detected" in result.stderr


# ---------------------------------------------------------------------------
# (c) scope anchor, independent of the CLI: in-process, foreign audit root
# ---------------------------------------------------------------------------


def test_scope_anchor_resolves_against_audit_root(tmp_path):
    """iter_staged_files/is_in_scope must compute scope from the AUDITED tree.

    Under the pre-043d anchoring both calls resolved against the motor ROOT, so
    the first assertion returned [] (motor/<rel> does not exist) and the scope
    membership was False for any foreign path."""
    foreign = _init_foreign_repo(tmp_path)
    target = foreign / "corrupt.md"
    target.write_text(_CLEAN, encoding="utf-8")
    rel = "corrupt.md"

    assert iter_staged_files([rel], root=foreign) == [target.resolve()]
    assert is_in_scope(rel, root=foreign) is True

    # Canonical static surfaces belong to the FOREIGN scope too (L801): the
    # static list resolves relative to the audited tree, not only to the motor.
    assert is_in_scope(".agent/collaboration/work_plan.md", root=foreign) is True

    # Contrast: under the motor default the same relative path does not exist,
    # so nothing is staged (the old anchor could never see the foreign file).
    assert iter_staged_files([rel]) == []


# ---------------------------------------------------------------------------
# (a) fail-closed resolution + explicit-path backward compatibility
# ---------------------------------------------------------------------------


def test_guard_fails_closed_when_cwd_is_not_a_git_tree(tmp_path):
    repo = _init_foreign_repo(tmp_path)
    plain = tmp_path / "not_a_repo"
    plain.mkdir()
    assert repo.exists()

    result = _run_guard(plain)

    assert result.returncode == 2, result.stderr
    assert "FAIL-CLOSED" in result.stderr


def test_explicit_path_invocation_does_not_need_a_git_cwd(tmp_path):
    """Backward compat: explicit paths keep working from a non-git cwd (the
    audit root is resolved lazily, only on the staged path)."""
    plain = tmp_path / "not_a_repo"
    plain.mkdir()
    file_path = plain / "bom.md"
    file_path.write_bytes(b"\xef\xbb\xbf# hello\n")

    result = _run_guard(plain, str(file_path))

    assert result.returncode == 1, result.stderr
    assert "UTF-8 BOM detected" in result.stderr


# ---------------------------------------------------------------------------
# (d) anti-false-positive: the clean motor stays GREEN
# ---------------------------------------------------------------------------


def test_clean_motor_invocation_stays_green():
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if staged.stdout.strip():
        pytest.skip(
            "declared skip, NOT a pass: the motor index is not clean in this "
            f"environment ({len(staged.stdout.splitlines())} staged paths)"
        )

    result = _run_guard(ROOT)

    assert result.returncode == 0, result.stderr
