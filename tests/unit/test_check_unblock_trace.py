"""Useful red tests for WOT-2026-231d's git-derived unblock verifier."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_unblock_trace.py"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.invalid")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "seed.txt")
    _git(repo, "commit", "-qm", "base")
    return repo


def _commit(repo: Path, subject: str, files: dict[str, str]) -> str:
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", subject)
    return _git(repo, "rev-parse", "HEAD")


def _run(repo: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--motor-root",
            str(repo),
            "--range",
            "HEAD~1..HEAD",
            *extra,
        ],
        capture_output=True,
        text=True,
    )


def test_m02_declarative_commit_without_trace_fails_and_trace_passes(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    _commit(repo, "hotfix: unblock closeout", {"scripts/check_example.py": "x\n"})
    assert _run(repo).returncode != 0

    _git(repo, "reset", "--soft", "HEAD~1")
    _git(repo, "reset", "--mixed")
    (repo / "scripts" / "check_example.py").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(
        repo,
        "commit",
        "-qm",
        "hotfix: unblock closeout\n\nPREEXISTING_GATE_UNBLOCK: gate-x",
    )
    assert _run(repo).returncode == 0


def test_m04_corrected_candidate_requires_guard_and_gate_surfaces(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    _commit(
        repo,
        "fix: maintenance",
        {
            "scripts/check_example.py": "x\n",
            "docs/note.md": "x\n",
            "scripts/prepush_check.py": "x\n",
        },
    )
    result = _run(repo)
    assert result.returncode != 0
    assert "unclassified" in result.stdout.lower()

    repo2 = _repo(tmp_path / "negative")
    _commit(repo2, "fix: maintenance", {"scripts/check_example.py": "x\n"})
    assert _run(repo2).returncode == 0


def test_m03_grandfather_allowlist_is_closed(tmp_path: Path, monkeypatch) -> None:
    spec = importlib.util.spec_from_file_location("check_unblock_trace", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    repo = _repo(tmp_path)
    sha = _commit(repo, "hotfix: unblock closeout", {"notes.txt": "x\n"})
    monkeypatch.setattr(module, "GRANDFATHERED_SHAS", (sha,))
    monkeypatch.setattr(module, "GRANDFATHERED_COUNT", 1)
    assert module.run_check(repo, "HEAD~1..HEAD") == 0

    monkeypatch.setattr(module, "GRANDFATHERED_SHAS", (sha, "extra-sha"))
    assert module.run_check(repo, "HEAD~1..HEAD") == 1


def test_m05_non_declarative_classification_is_required(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _commit(
        repo,
        "fix: gate maintenance\n\nNOT_PREEXISTING_UNBLOCK: own ticket fix",
        {"scripts/check_example.py": "x\n", "scripts/prepush_check.py": "x\n"},
    )
    assert _run(repo).returncode == 0


def test_m06_deleting_local_ledgers_does_not_change_git_verdict(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _commit(repo, "hotfix: unblock closeout", {"scripts/check_example.py": "x\n"})
    before = _run(repo)
    scratch = repo / ".agent" / "runtime" / "session" / "sid"
    scratch.mkdir(parents=True)
    (scratch / "manifest.jsonl").write_text("{}\n", encoding="utf-8")
    (scratch / ".session_state.json").write_text("{}\n", encoding="utf-8")
    (scratch / "manifest.jsonl").unlink()
    (scratch / ".session_state.json").unlink()
    after = _run(repo)
    assert (before.returncode, before.stdout) == (after.returncode, after.stdout)


def test_m08_removing_real_commit_trace_is_detected(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _commit(
        repo,
        "hotfix: unblock closeout\n\nPREEXISTING_GATE_UNBLOCK: gate-x",
        {"scripts/check_example.py": "x\n"},
    )
    assert _run(repo).returncode == 0
    _git(repo, "reset", "--soft", "HEAD~1")
    _git(repo, "reset", "--mixed")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "hotfix: unblock closeout")
    assert _run(repo).returncode != 0


def test_m10_docstring_declares_limit_and_surface_source() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "LIMITE DECLARADO" in text
    assert "GUARD_SURFACE" in text
