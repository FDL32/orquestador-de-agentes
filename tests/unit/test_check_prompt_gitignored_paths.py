"""Real subprocess tests for WOT-2026-044m prompt path auditing."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from scripts import check_prompt_gitignored_paths as guard


ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "scripts" / "check_prompt_gitignored_paths.py"


def _git_commit(repo: Path, message: str, *, date: str | None = None) -> str:
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    env = os.environ.copy()
    if date:
        env["GIT_AUTHOR_DATE"] = date
        env["GIT_COMMITTER_DATE"] = date
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            message,
        ],
        cwd=repo,
        env=env,
        check=True,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _repo(tmp_path: Path, body: str, *, ignored: str = "ignored/*\n") -> Path:
    repo = tmp_path / "repo"
    (repo / "prompts").mkdir(parents=True)
    (repo / ".gitignore").write_text(ignored, encoding="utf-8")
    (repo / "prompts" / "demo.md").write_text(body, encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    _git_commit(repo, "fixture", date="2026-12-01T00:00:00+0000")
    return repo


def _head(repo: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _new_exec_repo(
    tmp_path: Path, body: str, *, date: str = "2026-12-01T00:00:00+0000"
) -> tuple[Path, str]:
    repo = _repo(tmp_path, "Texto normal.\n")
    intro = _head(repo)
    (repo / "prompts" / "demo.md").write_text(body, encoding="utf-8")
    _git_commit(repo, "exec", date=date)
    return repo, intro


def _run(repo: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GUARD), "--motor-root", str(repo), *extra],
        text=True,
        capture_output=True,
        check=False,
    )


def test_detects_and_names_new_executable_path(tmp_path: Path):
    repo, intro = _new_exec_repo(tmp_path, "Ejecuta `python ignored/tool.py --flag`.\n")
    result = _run(repo, "--intro-commit", intro)
    assert result.returncode == 1
    assert "prompts/demo.md:1:ignored/tool.py" in result.stdout
    assert "EXEC=1" in result.stdout


def test_mutation_bidirectional_real_subprocess(tmp_path: Path):
    repo = _repo(tmp_path, "Texto normal.\n")
    intro = _head(repo)
    assert _run(repo).returncode == 0
    prompt = repo / "prompts" / "demo.md"
    prompt.write_text("Ejecuta `python ignored/tool.py`.\n", encoding="utf-8")
    _git_commit(repo, "mutation")
    result = _run(repo, "--intro-commit", intro)
    assert result.returncode == 1
    assert "prompts/demo.md:1:ignored/tool.py" in result.stdout
    assert "EXEC=1" in result.stdout
    prompt.write_text("Texto normal.\n", encoding="utf-8")
    _git_commit(repo, "restore")
    assert _run(repo, "--intro-commit", intro).returncode == 0


def test_uncommitted_exec_fails_closed(tmp_path: Path):
    repo = _repo(tmp_path, "Texto normal.\n")
    intro = _head(repo)
    (repo / "prompts" / "demo.md").write_text(
        "Ejecuta `python ignored/tool.py`.\n", encoding="utf-8"
    )
    result = _run(repo, "--intro-commit", intro)
    assert result.returncode == 1
    assert "prompts/demo.md:1:ignored/tool.py" in result.stdout
    assert "EXEC=1" in result.stdout
    assert "not present in HEAD" in result.stdout


def test_role_prefix_exec_fails_closed(tmp_path: Path):
    repo, intro = _new_exec_repo(
        tmp_path, "Ejecuta `python <workspace>/ignored/tool.py`.\n"
    )
    result = _run(repo, "--intro-commit", intro)
    assert result.returncode == 1
    assert "ignored/tool.py" in result.stdout
    assert "EXEC=1" in result.stdout


def test_inline_route_with_flags_is_exec(tmp_path: Path):
    repo, intro = _new_exec_repo(tmp_path, "Usa `ignored/tool.py --flag`.\n")
    result = _run(repo, "--intro-commit", intro)
    assert result.returncode == 1
    assert "prompts/demo.md:1:ignored/tool.py" in result.stdout
    assert "EXEC=1" in result.stdout


def test_mixed_line_marker_is_not_adjacent_and_fails(tmp_path: Path):
    repo, intro = _new_exec_repo(
        tmp_path,
        "Ejecuta `ignored/tool.py --flag` (la version vieja fue retirado).\n",
    )
    result = _run(repo, "--intro-commit", intro)
    assert result.returncode == 1
    assert "prompts/demo.md:1:ignored/tool.py" in result.stdout
    assert "EXEC=1" in result.stdout


def test_adjacent_marker_silences_route(tmp_path: Path):
    repo, intro = _new_exec_repo(
        tmp_path, "Ejemplo ilustrativo `ignored/tool.py --flag`.\n"
    )
    result = _run(repo, "--intro-commit", intro)
    assert result.returncode == 0
    assert "EXEC=0" in result.stdout
    assert "ILLUS=1" in result.stdout


def test_marker_after_clause_boundary_does_not_silence_route(tmp_path: Path):
    repo, intro = _new_exec_repo(
        tmp_path,
        "Ejecuta `ignored/tool.py`; ejemplo ilustrativo en otra clausula.\n",
    )
    result = _run(repo, "--intro-commit", intro)
    assert result.returncode == 1
    assert "prompts/demo.md:1:ignored/tool.py" in result.stdout
    assert "EXEC=1" in result.stdout


def test_data_with_execution_signal_is_exec(tmp_path: Path):
    repo, intro = _new_exec_repo(
        tmp_path, "Lee el informe y ejecuta `python ignored/tool.py --flag`.\n"
    )
    result = _run(repo, "--intro-commit", intro)
    assert result.returncode == 1
    assert "prompts/demo.md:1:ignored/tool.py" in result.stdout
    assert "EXEC=1" in result.stdout


@pytest.mark.parametrize(
    "date",
    [
        pytest.param("2026-11-14T00:00:00+0000", id="same-day"),
        pytest.param("2026-11-01T00:00:00+0000", id="delayed"),
    ],
)
def test_author_date_does_not_grandfather_new_exec(tmp_path: Path, date: str):
    repo, intro = _new_exec_repo(
        tmp_path, "Ejecuta `python ignored/tool.py --flag`.\n", date=date
    )
    result = _run(repo, "--intro-commit", intro)
    assert result.returncode == 1
    assert "prompts/demo.md:1:ignored/tool.py" in result.stdout
    assert "EXEC=1" in result.stdout


@pytest.mark.parametrize(
    "body",
    [
        "Escribe `ignored/tool.py`; ejecuta `ignored/tool.py --flag`.\n",
        "Ejecuta `ignored/tool.py`; escribe la salida en `ignored/tool.py`.\n",
    ],
    ids=["data-before-exec", "exec-before-data"],
)
def test_multiple_spans_use_route_span_severity(tmp_path: Path, body: str):
    repo, intro = _new_exec_repo(tmp_path, body)
    result = _run(repo, "--intro-commit", intro)
    assert result.returncode == 1
    assert "prompts/demo.md:1:ignored/tool.py" in result.stdout
    assert "EXEC=1" in result.stdout


def test_negation_only_at_clause_start_is_mention(tmp_path: Path):
    repo, intro = _new_exec_repo(
        tmp_path, "Ejecuta `python ignored/tool.py --flag` no en produccion.\n"
    )
    result = _run(repo, "--intro-commit", intro)
    assert result.returncode == 1
    assert "prompts/demo.md:1:ignored/tool.py" in result.stdout
    assert "EXEC=1" in result.stdout


def test_negated_execution_at_clause_start_is_mention(tmp_path: Path):
    repo, intro = _new_exec_repo(
        tmp_path, "No ejecutes `python ignored/tool.py --flag`.\n"
    )
    result = _run(repo, "--intro-commit", intro)
    assert result.returncode == 0
    assert "EXEC=0" in result.stdout
    assert "MENTION=1" in result.stdout


def test_explicit_intro_commit_not_resolvable_fails_closed(tmp_path: Path):
    repo, _intro = _new_exec_repo(
        tmp_path, "Ejecuta `python ignored/tool.py --flag`.\n"
    )
    result = _run(repo, "--intro-commit", "0" * 40)
    assert result.returncode == 1
    assert "prompts/demo.md:1:ignored/tool.py" in result.stdout
    assert "EXEC=1" in result.stdout
    assert "intro commit" in result.stdout
    assert "not resolvable" in result.stdout


def test_default_intro_commit_not_resolvable_in_fixture_fails_closed(tmp_path: Path):
    repo, _intro = _new_exec_repo(
        tmp_path, "Ejecuta `python ignored/tool.py --flag`.\n"
    )
    result = _run(repo)
    assert result.returncode == 1
    assert "prompts/demo.md:1:ignored/tool.py" in result.stdout
    assert "EXEC=1" in result.stdout
    assert (
        "intro commit fa3bf8da69382bded237fc80b0bfdfc679dd2bdf not resolvable"
        in result.stdout
    )


def test_illustration_and_output_are_not_exec(tmp_path: Path):
    body = "Historico legacy: `ignored/tool.py` was retired.\nEscribe el informe en `ignored/tool.py`.\n"
    result = _run(_repo(tmp_path, body), "--inventory", str(tmp_path / "inventory.txt"))
    assert result.returncode == 0
    assert "EXEC=0" in result.stdout
    inventory = (tmp_path / "inventory.txt").read_text(encoding="utf-8")
    assert inventory.count("ILLUS") == 1
    assert inventory.count("MENTION") == 1


def test_warns_for_old_exec_and_publishes_denominator(tmp_path: Path):
    repo = _repo(tmp_path, "Ejecuta `python ignored/tool.py`.\n")
    intro = _head(repo)
    result = _run(repo, "--intro-commit", intro)
    assert result.returncode == 0
    assert "WARN prompts/demo.md:1:ignored/tool.py" in result.stdout
    assert "denominator: 1 prompts" in result.stdout


def test_zero_prompts_fails_closed(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    result = _run(repo)
    assert result.returncode == 1
    assert "denominator is empty" in result.stdout


def test_git_unavailable_fails_closed(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        guard,
        "_run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("git unavailable: missing")
        ),
    )
    assert guard.main(["--motor-root", str(tmp_path)]) == 1


def test_check_ignore_unexpected_rc_fails_closed(tmp_path: Path, monkeypatch):
    repo = _repo(tmp_path, "Ejecuta `python ignored/tool.py`.\n")
    calls = iter(
        [
            subprocess.CompletedProcess([], 0, b"prompts/demo.md\n", b""),
            subprocess.CompletedProcess([], 2, b"", b"broken"),
        ]
    )
    monkeypatch.setattr(guard, "_run", lambda *args, **kwargs: next(calls))
    assert guard.main(["--motor-root", str(repo)]) == 1


def test_blame_failure_fails_closed(tmp_path: Path, monkeypatch, capsys):
    repo = _repo(tmp_path, "Texto normal.\n")
    prompt = repo / "prompts" / "demo.md"
    prompt.write_text("Ejecuta `python ignored/tool.py`.\n", encoding="utf-8")
    _git_commit(repo, "exec")
    monkeypatch.setattr(
        guard,
        "_line_commit",
        lambda *args: (_ for _ in ()).throw(RuntimeError("blame failed")),
    )
    assert guard.main(["--motor-root", str(repo), "--intro-commit", _head(repo)]) == 1
    assert "prompts/demo.md:1:ignored/tool.py" in capsys.readouterr().out


def test_invalid_prompt_encoding_fails_closed(tmp_path: Path):
    repo = _repo(tmp_path, "Texto normal.\n")
    (repo / "prompts" / "demo.md").write_bytes(b"\xff\xfe\n")
    result = _run(repo)
    assert result.returncode == 1
    assert "cannot read prompt" in result.stdout


def test_negated_ignore_is_not_reported(tmp_path: Path):
    repo = _repo(
        tmp_path,
        "Ejecuta `python ignored/tool.py`.\n",
        ignored="ignored/*\n!ignored/tool.py\n",
    )
    result = _run(repo)
    assert result.returncode == 0
    assert "ignored_routes(unique)=0" in result.stdout


def test_real_tree_is_green_and_hook_is_declared():
    result = _run(ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "denominator:" in result.stdout
    assert "method:" in result.stdout
    hook = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    baseline = (
        ROOT / "tests" / "fixtures" / "guard_wiring_wired_baseline.yaml"
    ).read_text(encoding="utf-8")
    assert "id: check-prompt-gitignored-paths" in hook
    assert "check_prompt_gitignored_paths:" in baseline
