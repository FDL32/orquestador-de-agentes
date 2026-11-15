"""Hermetic subprocess tests for the counter and prompt budget gate."""

from __future__ import annotations

import ast
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
PY = Path(sys.executable)
GUARD = ROOT / "scripts" / "check_counter_budget_gate.py"
AUDIT = ROOT / "scripts" / "check_prompt_line_budget.py"


def _repo(tmp_path: Path, count: int = 1) -> Path:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "tests" / "unit").mkdir(parents=True)
    shutil.copy2(GUARD, tmp_path / "scripts" / GUARD.name)
    shutil.copy2(AUDIT, tmp_path / "scripts" / AUDIT.name)
    (tmp_path / "tests" / "unit" / "test_152b2_link_readers_bom.py").write_text(
        f"SCRIPTS_COUNT = {count}\n", encoding="utf-8"
    )
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    return tmp_path


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            str(PY),
            "-I",
            str(repo / "scripts" / GUARD.name),
            "--motor-root",
            str(repo),
            *args,
        ],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )


def _stage_script(repo: Path, name: str = "zz_tmp.py") -> None:
    (repo / "scripts" / name).write_text("# temporary\n", encoding="utf-8")
    subprocess.run(["git", "add", "scripts"], cwd=repo, check=True)


def _assert_guard_source_has_no_runner(source: str) -> None:
    tree = ast.parse(source)
    imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    names = {
        alias.name if isinstance(node, ast.Import) else node.module
        for node in imports
        for alias in node.names
    }
    assert "pytest" not in names
    assert "run_pytest_safe" not in source
    assert "--level" not in source


def test_guard_never_imports_a_test_runner() -> None:
    _assert_guard_source_has_no_runner(GUARD.read_text(encoding="utf-8"))
    with pytest.raises(AssertionError):
        _assert_guard_source_has_no_runner("import pytest\n")
    with pytest.raises(AssertionError):
        _assert_guard_source_has_no_runner("from pytest import main\n")
    with pytest.raises(AssertionError):
        _assert_guard_source_has_no_runner("from scripts.run_pytest_safe import main\n")
    with pytest.raises(AssertionError):
        _assert_guard_source_has_no_runner("import run_pytest_safe\n")


def test_guard_runs_without_any_pytest_runner_present(tmp_path: Path) -> None:
    repo = _repo(tmp_path, count=1)
    (repo / "conftest.py").write_text(
        "from pathlib import Path\nPath('COLLECTED').write_text('x')\n",
        encoding="utf-8",
    )
    positive = subprocess.run(
        [str(PY), "-I", str(repo / "conftest.py")],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    assert positive.returncode == 0
    assert (repo / "COLLECTED").exists()
    (repo / "COLLECTED").unlink()
    _stage_script(repo)
    result = _run(repo)
    assert result.returncode == 1
    assert "test_152b2_link_readers_bom.py" in result.stdout
    assert "esperado" in result.stdout and "encontrado" in result.stdout
    assert not (repo / "COLLECTED").exists()
    (repo / "tests" / "unit" / "test_152b2_link_readers_bom.py").write_text(
        "SCRIPTS_COUNT = 3\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", "tests"], cwd=repo, check=True)
    result = _run(repo)
    assert result.returncode == 0
    assert not (repo / "COLLECTED").exists()


def test_delete_without_bump_is_red(tmp_path: Path) -> None:
    repo = _repo(tmp_path, count=3)
    _stage_script(repo, "three.py")
    subprocess.run(["git", "commit", "-qm", "scripts"], cwd=repo, check=True)
    (repo / "scripts" / "three.py").unlink()
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    result = _run(repo)
    assert result.returncode == 1
    assert "test_152b2_link_readers_bom.py" in result.stdout
    assert "esperado SCRIPTS_COUNT=3" in result.stdout
    assert "scripts/*.py=2" in result.stdout
    (repo / "tests" / "unit" / "test_152b2_link_readers_bom.py").write_text(
        "SCRIPTS_COUNT = 2\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", "tests"], cwd=repo, check=True)
    assert _run(repo).returncode == 0


def test_docs_only_is_explicit_skip(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "README.md").write_text("docs\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    result = _run(repo)
    assert result.returncode == 0
    assert "SKIP EXPLICITO" in result.stdout and "No es un PASS" in result.stdout


def test_delete_and_rename_inside_scripts_use_index_census(tmp_path: Path) -> None:
    repo = _repo(tmp_path, count=3)
    (repo / "scripts" / "one.py").write_text("x\n", encoding="utf-8")
    (repo / "scripts" / "two.py").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "scripts"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "scripts"], cwd=repo, check=True)
    (repo / "scripts" / "two.py").unlink()
    (repo / "scripts" / "one.py").rename(repo / "scripts" / "renamed.py")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    (repo / "tests" / "unit" / "test_152b2_link_readers_bom.py").write_text(
        "SCRIPTS_COUNT = 3\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", "tests"], cwd=repo, check=True)
    result = _run(repo)
    assert result.returncode == 0


def test_prompt_over_budget_and_within_budget(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    prompt = repo / "prompts" / "manager_review.md"
    prompt.parent.mkdir()
    prompt.write_text(
        "---\nline_budget: 1\n---\nline one\nline two\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", "prompts"], cwd=repo, check=True)
    result = _run(repo)
    assert result.returncode == 1
    assert "manager_review.md" in result.stdout and "presupuesto=1" in result.stdout
    prompt.write_text(
        "---\nline_budget: 5\n---\nline one\nline two\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", "prompts"], cwd=repo, check=True)
    assert _run(repo).returncode == 0


def test_staged_prompt_blob_wins_over_unstaged_disk(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    prompt = repo / "prompts" / "manager_review.md"
    prompt.parent.mkdir()
    prompt.write_text("---\nline_budget: 4\n---\nline one\n", encoding="utf-8")
    subprocess.run(["git", "add", "prompts"], cwd=repo, check=True)
    prompt.write_text(
        "---\nline_budget: 4\n---\nline one\nline two\nline three\n",
        encoding="utf-8",
    )
    result = _run(repo)
    assert result.returncode == 0
    prompt.write_text(
        "---\nline_budget: 3\n---\nline one\nline two\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "prompts"], cwd=repo, check=True)
    prompt.write_text("---\nline_budget: 3\n---\nline one\n", encoding="utf-8")
    result = _run(repo)
    assert result.returncode == 1


def test_prompt_import_is_deferred_until_prompt_matter(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "scripts" / "check_prompt_line_budget.py").unlink()
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    (repo / "README.md").write_text("docs\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    assert _run(repo).returncode == 0
    prompt = repo / "prompts" / "manager_review.md"
    prompt.parent.mkdir()
    prompt.write_text("---\nline_budget: 1\n---\nline\n", encoding="utf-8")
    subprocess.run(["git", "add", "prompts"], cwd=repo, check=True)
    result = _run(repo)
    assert result.returncode == 1
    assert "check_prompt_line_budget" in result.stderr


def test_non_ascii_script_add_delete_and_rename_are_counted(tmp_path: Path) -> None:
    repo = _repo(tmp_path, count=1)
    script_name = "\u00f1and\u00fa.py"
    renamed_name = "\u00f1and\u00fa-renamed.py"
    _stage_script(repo, script_name)
    result = _run(repo)
    assert result.returncode == 1
    assert "scripts/*.py=3" in result.stdout
    (repo / "tests" / "unit" / "test_152b2_link_readers_bom.py").write_text(
        "SCRIPTS_COUNT = 3\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", "tests"], cwd=repo, check=True)
    assert _run(repo).returncode == 0
    (repo / "scripts" / script_name).rename(repo / "scripts" / renamed_name)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    assert _run(repo).returncode == 0
    subprocess.run(["git", "commit", "-qm", "rename"], cwd=repo, check=True)
    (repo / "scripts" / renamed_name).unlink()
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    result = _run(repo)
    assert result.returncode == 1
    assert "scripts/*.py=2" in result.stdout
    (repo / "tests" / "unit" / "test_152b2_link_readers_bom.py").write_text(
        "SCRIPTS_COUNT = 2\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", "tests"], cwd=repo, check=True)
    assert _run(repo).returncode == 0


def test_range_uses_tip_blobs(tmp_path: Path) -> None:
    repo = _repo(tmp_path, count=2)
    _stage_script(repo)
    (repo / "tests" / "unit" / "test_152b2_link_readers_bom.py").write_text(
        "SCRIPTS_COUNT = 3\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", "tests"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "change"], cwd=repo, check=True)
    result = _run(repo, "--range", "HEAD~1..HEAD")
    assert result.returncode == 0
