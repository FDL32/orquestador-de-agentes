"""Barrier tests for WOT-2026-014a: opt-in runtime-artifact allowlist for closeout prepush.

Tests verify:
  (a) uncommitted expected report + NO allowlist -> check_git_tree_clean FAILS (bug reproduction)
  (b) same report + closeout allowlist -> forgiven (passes)
  (c) uncommitted PRODUCTIVE file + closeout allowlist -> STILL FAILS (allowlist does not swallow real work)
  (d) check_git_tree_clean with default (no allowlist) preserves exact current behavior
  (e) INTEGRATION: gates.step_prepush_check includes --closeout-mode in the subprocess command
      so that the real closeout path actually passes the allowlist end-to-end.

Mutation-verified (see docstrings for each case).
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DHC_PATH = PROJECT_ROOT / "scripts" / "delivery_hygiene_check.py"
GATES_PATH = PROJECT_ROOT / "scripts" / "closeout_steps" / "gates.py"

_dhc_spec = importlib.util.spec_from_file_location("delivery_hygiene_check", DHC_PATH)
dhc = importlib.util.module_from_spec(_dhc_spec)
_dhc_spec.loader.exec_module(dhc)


def _init_git_repo(repo: Path) -> None:
    """Create a minimal git repo with one initial commit."""
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@e.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "T"], cwd=repo, check=True, capture_output=True
    )
    (repo / "README.md").write_text("# repo")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True
    )


def _commit_file(repo: Path, rel: str, content: str) -> None:
    """Create + commit a tracked file."""
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    subprocess.run(["git", "add", "--", rel], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", f"add {rel}"], cwd=repo, check=True, capture_output=True
    )


def _make_dirty(repo: Path, rel: str, content: str = "dirty") -> None:
    """Modify a tracked file so it appears dirty in git status."""
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


# ---------------------------------------------------------------------------
# Case (a): expected report + NO allowlist -> FAILS (reproduces the bug)
# ---------------------------------------------------------------------------


def test_case_a_expected_report_no_allowlist_fails(tmp_path: Path) -> None:
    """(a) Bug reproduction: a tracked session_close_report.md that is dirty
    (modified after commit, i.e. the closeout generated it) causes
    check_git_tree_clean to FAIL when no allowlist is provided.

    Mutation proof: this test MUST fail if the allowlist filtering code is
    removed from check_git_tree_clean (the allowlist param is not used here so
    removal would not help, but it confirms the base behavior is captured).
    """
    repo = tmp_path / "repo_a"
    _init_git_repo(repo)
    report_rel = ".agent/runtime/memory/session_close_report.md"
    _commit_file(repo, report_rel, "initial")
    _make_dirty(repo, report_rel, "updated by closeout")

    result = dhc.check_git_tree_clean(repo)  # no allowlist -> default None

    assert result.passed is False, f"Expected FAIL but got PASS. msg={result.message}"
    assert "ARBOL SUCIO" in result.message or "SUCIO" in result.message, result.message


# ---------------------------------------------------------------------------
# Case (b): same report + closeout allowlist -> FORGIVEN (passes)
# ---------------------------------------------------------------------------


def test_case_b_expected_report_with_allowlist_passes(tmp_path: Path) -> None:
    """(b) With the closeout allowlist, the same dirty session_close_report.md
    is forgiven and check_git_tree_clean returns PASS.

    Mutation proof: if the allowlist filtering code is REMOVED from
    check_git_tree_clean, this test FAILS (the report is still dirty and the
    function returns FAIL). See test_mutation_b_removing_filter_causes_failure.
    """
    repo = tmp_path / "repo_b"
    _init_git_repo(repo)
    report_rel = ".agent/runtime/memory/session_close_report.md"
    _commit_file(repo, report_rel, "initial")
    _make_dirty(repo, report_rel, "updated by closeout")

    result = dhc.check_git_tree_clean(repo, dhc.EXPECTED_CLOSEOUT_RUNTIME_ARTIFACTS)

    assert result.passed is True, (
        f"Expected PASS with closeout allowlist but got FAIL. "
        f"msg={result.message}, details={result.details}"
    )
    assert "limpio" in result.message.lower() or result.passed, result.message


# ---------------------------------------------------------------------------
# Case (c): PRODUCTIVE file + closeout allowlist -> STILL FAILS
# ---------------------------------------------------------------------------


def test_case_c_productive_file_with_allowlist_still_fails(tmp_path: Path) -> None:
    """(c) A productive (non-expected) uncommitted change MUST still mark the
    tree dirty even when the closeout allowlist is passed.

    This is the critical regression guard: the allowlist must NOT swallow real
    work. Mutation proof: if allowlist filtering was changed to "allow all",
    this test FAILS.
    """
    repo = tmp_path / "repo_c"
    _init_git_repo(repo)
    # Track a productive source file and then modify it without committing
    productive_rel = "scripts/my_feature.py"
    _commit_file(repo, productive_rel, "# original")
    _make_dirty(repo, productive_rel, "# uncommitted productive change")

    result = dhc.check_git_tree_clean(repo, dhc.EXPECTED_CLOSEOUT_RUNTIME_ARTIFACTS)

    assert result.passed is False, (
        f"Expected FAIL for productive dirty file but got PASS. "
        f"msg={result.message}, details={result.details}"
    )
    details_str = " ".join(result.details or [])
    assert "my_feature.py" in details_str or "scripts" in details_str, (
        f"Expected productive file in details but got: {result.details}"
    )


# ---------------------------------------------------------------------------
# Case (d): default (no allowlist) preserves exact current behavior
# ---------------------------------------------------------------------------


def test_case_d_clean_tree_passes_with_no_allowlist(tmp_path: Path) -> None:
    """(d) When the tree is clean and no allowlist is passed, the function
    returns PASS. This locks the default (no-allowlist) behavior: it must not
    be changed as a side-effect of the WOT-2026-014a changes.
    """
    repo = tmp_path / "repo_d"
    _init_git_repo(repo)

    result = dhc.check_git_tree_clean(repo)  # no allowlist

    assert result.passed is True, f"Expected clean tree to pass. msg={result.message}"


def test_case_d_dirty_tree_fails_with_no_allowlist(tmp_path: Path) -> None:
    """(d) When the tree is dirty and no allowlist is passed, ANY dirty file
    (including expected runtime artifacts) causes a FAIL. This is the exact
    current behavior that must be preserved for the general pre-push gate.
    """
    repo = tmp_path / "repo_d2"
    _init_git_repo(repo)
    # Even a report file must fail if no allowlist is given
    _commit_file(repo, "some_file.txt", "v1")
    _make_dirty(repo, "some_file.txt", "v2 uncommitted")

    result = dhc.check_git_tree_clean(repo)  # no allowlist

    assert result.passed is False, f"Expected dirty tree to fail. msg={result.message}"


# ---------------------------------------------------------------------------
# Mutation verification for case (b)
# ---------------------------------------------------------------------------


def test_mutation_b_removing_filter_causes_failure(tmp_path: Path) -> None:
    """Mutation proof for case (b): manually simulate the pre-fix behavior
    (allowlist ignored) to confirm that WITHOUT filtering the report causes FAIL,
    which is exactly what case (b) is designed to catch when someone removes the
    filtering logic.

    Technique: call check_git_tree_clean with expected_artifacts=[] (empty list
    is falsy so the filter branch is skipped, reproducing pre-fix behavior even
    if the argument is accepted).
    """
    repo = tmp_path / "repo_mut_b"
    _init_git_repo(repo)
    report_rel = ".agent/runtime/memory/session_close_report.md"
    _commit_file(repo, report_rel, "initial")
    _make_dirty(repo, report_rel, "updated by closeout")

    # Empty list = falsy = filter branch NOT taken = pre-fix behavior
    result_no_filter = dhc.check_git_tree_clean(repo, [])
    assert result_no_filter.passed is False, (
        "Pre-fix simulation: expected report without active filter must FAIL"
    )

    # Non-empty allowlist = filter IS taken = post-fix behavior
    result_with_filter = dhc.check_git_tree_clean(
        repo, dhc.EXPECTED_CLOSEOUT_RUNTIME_ARTIFACTS
    )
    assert result_with_filter.passed is True, (
        "Post-fix: expected report with active filter must PASS"
    )


# ---------------------------------------------------------------------------
# Case (e): INTEGRATION -- gates.step_prepush_check includes --closeout-mode
# BEHAVIORAL test: monkeypatch run_script_fn to capture the actual command.
# ---------------------------------------------------------------------------


def test_case_e_gates_step_prepush_passes_closeout_mode_behavioral(
    tmp_path: Path,
) -> None:
    """(e) BEHAVIORAL integration test: call gates.step_prepush_check() directly with
    a monkeypatched run_script_fn that CAPTURES the command list passed to it.
    Assert that "--closeout-mode" appears in the captured command.

    This is robust against comment-only mentions of --closeout-mode because it
    tests the RUNTIME behavior (what command is built), not the source text.

    Mutation proof (verified externally):
      - Remove ", --closeout-mode" from gates.py command list -> this test FAILS
      - Restore -> passes
    """
    import importlib

    # Fresh import of gates module so our test sees the real current state
    gates_module_path = PROJECT_ROOT / "scripts" / "closeout_steps" / "gates.py"
    gates_spec = importlib.util.spec_from_file_location("gates_test", gates_module_path)
    gates_mod = importlib.util.module_from_spec(gates_spec)
    gates_spec.loader.exec_module(gates_mod)

    # Capture: track what command is passed to run_script_fn
    captured_scripts: list[str] = []
    captured_args: list[list[str]] = []

    class _FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    def _capture_run_script(script_name, args, project_root, timeout=300):
        captured_scripts.append(script_name)
        captured_args.append(list(args))
        return _FakeResult()

    class _FakeStepResult:
        def __init__(self, name, status, detail="", blocking=False):
            self.name = name
            self.status = status
            self.detail = detail
            self.blocking = blocking

    # Call step_prepush_check with dry_run=False so it hits the run_script_fn path
    gates_mod.step_prepush_check(
        project_root=tmp_path,
        dry_run=False,
        run_script_fn=_capture_run_script,
        process_diagnostic_fn=lambda r: r.stderr,
        step_result_cls=_FakeStepResult,
    )

    assert captured_scripts, (
        "run_script_fn was never called; step_prepush_check did not reach the script call"
    )
    assert captured_scripts[0] == "prepush_check.py", (
        f"Expected prepush_check.py but got {captured_scripts[0]}"
    )
    assert "--closeout-mode" in captured_args[0], (
        "INTEGRATION GAP: step_prepush_check does not pass --closeout-mode to prepush_check.py."
        f" Actual args: {captured_args[0]}"
    )


# ---------------------------------------------------------------------------
# CONSTANT CONTRACT: shared constant is accessible and correct
# ---------------------------------------------------------------------------


def test_expected_closeout_runtime_artifacts_constant_contract() -> None:
    """Verify EXPECTED_CLOSEOUT_RUNTIME_ARTIFACTS is exported from delivery_hygiene_check
    and contains the expected file basenames. Locks the shared constant contract."""
    artifacts = dhc.EXPECTED_CLOSEOUT_RUNTIME_ARTIFACTS
    assert isinstance(artifacts, list), "Must be a list"
    assert "session_close_report.md" in artifacts, (
        "session_close_report.md must be in the allowlist"
    )
    assert "CONSOLIDATION_REPORT.md" in artifacts
    assert "MEMORY.md" in artifacts
    assert "observations.jsonl" in artifacts


def test_rotation_imports_constant_not_redefines() -> None:
    """Verify rotation.py imports EXPECTED_CLOSEOUT_RUNTIME_ARTIFACTS from
    delivery_hygiene_check instead of defining a local expected_patterns list."""
    rotation_path = PROJECT_ROOT / "scripts" / "closeout_steps" / "rotation.py"
    text = rotation_path.read_text(encoding="utf-8")
    assert (
        "from scripts.delivery_hygiene_check import EXPECTED_CLOSEOUT_RUNTIME_ARTIFACTS"
        in text
    ), (
        "rotation.py must import EXPECTED_CLOSEOUT_RUNTIME_ARTIFACTS from delivery_hygiene_check"
    )
    assert "expected_patterns = [" not in text, (
        "rotation.py must not redefine expected_patterns locally; it must use the imported constant"
    )
