"""Real subprocess tests for WOT-2026-044m prompt path auditing."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from scripts import check_prompt_gitignored_paths as guard


ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "scripts" / "check_prompt_gitignored_paths.py"


def _repo(tmp_path: Path, body: str, *, ignored: str = "ignored/*\n") -> Path:
    repo = tmp_path / "repo"
    (repo / "prompts").mkdir(parents=True)
    (repo / ".gitignore").write_text(ignored, encoding="utf-8")
    (repo / "prompts" / "demo.md").write_text(body, encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    env = os.environ | {
        "GIT_AUTHOR_DATE": "2026-12-01T00:00:00+0000",
        "GIT_COMMITTER_DATE": "2026-12-01T00:00:00+0000",
    }
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=repo,
        env=env,
        check=True,
    )
    return repo


def _run(repo: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GUARD), "--motor-root", str(repo), *extra],
        text=True,
        capture_output=True,
        check=False,
    )


def test_detects_and_names_new_executable_path(tmp_path: Path):
    result = _run(_repo(tmp_path, "Ejecuta `python ignored/tool.py --flag`.\n"))
    assert result.returncode == 1
    assert "prompts/demo.md:1:ignored/tool.py" in result.stdout
    assert "EXEC=1" in result.stdout


def test_mutation_bidirectional_real_subprocess(tmp_path: Path):
    repo = _repo(tmp_path, "Texto normal.\n")
    assert _run(repo).returncode == 0
    prompt = repo / "prompts" / "demo.md"
    prompt.write_text("Ejecuta `python ignored/tool.py`.\n", encoding="utf-8")
    subprocess.run(["git", "add", "prompts/demo.md"], cwd=repo, check=True)
    future = os.environ | {
        "GIT_AUTHOR_DATE": "2026-12-01T00:00:00+0000",
        "GIT_COMMITTER_DATE": "2026-12-01T00:00:00+0000",
    }
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "mutation",
        ],
        cwd=repo,
        env=future,
        check=True,
    )
    assert _run(repo).returncode == 1
    prompt.write_text("Texto normal.\n", encoding="utf-8")
    subprocess.run(["git", "add", "prompts/demo.md"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "restore",
        ],
        cwd=repo,
        check=True,
    )
    assert _run(repo).returncode == 0


def test_uncommitted_exec_fails_closed(tmp_path: Path):
    repo = _repo(tmp_path, "Texto normal.\n")
    (repo / "prompts" / "demo.md").write_text(
        "Ejecuta `python ignored/tool.py`.\n", encoding="utf-8"
    )
    result = _run(repo)
    assert result.returncode == 1
    assert "prompts/demo.md:1:ignored/tool.py" in result.stdout
    assert "not present in HEAD" in result.stdout


def test_role_prefix_exec_fails_closed(tmp_path: Path):
    result = _run(_repo(tmp_path, "Ejecuta `python <workspace>/ignored/tool.py`.\n"))
    assert result.returncode == 1
    assert "ignored/tool.py" in result.stdout


def test_inline_route_with_flags_is_exec(tmp_path: Path):
    result = _run(_repo(tmp_path, "Usa `ignored/tool.py --flag`.\n"))
    assert result.returncode == 1
    assert "EXEC=1" in result.stdout


def test_illustration_and_output_are_not_exec(tmp_path: Path):
    body = "Historico legacy: `ignored/tool.py` was retired.\nEscribe el informe en `ignored/tool.py`.\n"
    result = _run(_repo(tmp_path, body), "--inventory", str(tmp_path / "inventory.txt"))
    assert result.returncode == 0
    assert "EXEC=0" in result.stdout
    inventory = (tmp_path / "inventory.txt").read_text(encoding="utf-8")
    assert inventory.count("ILLUS") == 1
    assert inventory.count("MENTION") == 1


def test_warns_for_old_exec_and_publishes_denominator(tmp_path: Path):
    repo = _repo(tmp_path, "Texto normal.\n")
    (repo / "prompts" / "demo.md").write_text(
        "Ejecuta `python ignored/tool.py`.\n", encoding="utf-8"
    )
    env = os.environ | {
        "GIT_AUTHOR_DATE": "2026-11-14T00:00:00+0000",
        "GIT_COMMITTER_DATE": "2026-11-14T00:00:00+0000",
    }
    subprocess.run(["git", "add", "prompts/demo.md"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "old",
        ],
        cwd=repo,
        env=env,
        check=True,
    )
    result = _run(repo)
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
    subprocess.run(["git", "add", "prompts/demo.md"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "exec",
        ],
        cwd=repo,
        check=True,
    )
    monkeypatch.setattr(
        guard,
        "_blame_date",
        lambda *args: (_ for _ in ()).throw(RuntimeError("blame failed")),
    )
    assert guard.main(["--motor-root", str(repo)]) == 1
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
