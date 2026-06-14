"""Tests for the canonical Claude guard entrypoint (WOT-2026-003c)."""

from __future__ import annotations

import json
import sys
from pathlib import Path


sys.path.insert(
    0, str(Path(__file__).resolve().parent.parent.parent / ".agent" / "hooks")
)

import claude_guard_entry as entry


def _make_repo(tmp_path: Path, *, with_guard: bool, guard_exit: int = 7) -> Path:
    """Create a fake repo with a .claude marker and optional stub guard_paths.py."""
    (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)
    if with_guard:
        hooks = tmp_path / ".agent" / "hooks"
        hooks.mkdir(parents=True)
        (hooks / "guard_paths.py").write_text(
            f"import sys; sys.stdin.buffer.read(); sys.exit({guard_exit})\n",
            encoding="utf-8",
        )
    return tmp_path


class TestResolveRepoRoot:
    def test_finds_claude_ancestor(self, tmp_path: Path):
        repo = _make_repo(tmp_path, with_guard=False)
        sub = repo / "a" / "b"
        sub.mkdir(parents=True)
        assert entry.resolve_repo_root(str(sub)) == repo


class TestResolveGuardPaths:
    def test_own_guard_resolves(self, tmp_path: Path):
        repo = _make_repo(tmp_path, with_guard=True)
        assert (
            entry.resolve_guard_paths(repo)
            == repo / ".agent" / "hooks" / "guard_paths.py"
        )

    def test_via_motor_link(self, tmp_path: Path):
        motor = _make_repo(tmp_path / "motor", with_guard=True)
        destino = tmp_path / "destino"
        (destino / ".agent" / "config").mkdir(parents=True)
        (destino / ".claude").mkdir()
        (destino / ".agent" / "config" / "motor_destination_link.json").write_text(
            json.dumps({"motor_root": str(motor)}), encoding="utf-8"
        )
        assert (
            entry.resolve_guard_paths(destino)
            == motor / ".agent" / "hooks" / "guard_paths.py"
        )

    def test_no_guard_no_link_returns_none(self, tmp_path: Path):
        repo = _make_repo(tmp_path, with_guard=False)
        assert entry.resolve_guard_paths(repo) is None

    def test_malformed_link_returns_none(self, tmp_path: Path):
        destino = _make_repo(tmp_path, with_guard=False)
        (destino / ".agent" / "config").mkdir(parents=True)
        (destino / ".agent" / "config" / "motor_destination_link.json").write_text(
            "{ not valid json", encoding="utf-8"
        )
        assert entry.resolve_guard_paths(destino) is None


class TestMain:
    def test_no_guard_fails_closed(self, tmp_path: Path, monkeypatch, capsys):
        repo = _make_repo(tmp_path, with_guard=False)
        monkeypatch.chdir(repo)
        monkeypatch.setattr(
            "sys.stdin",
            type(
                "S",
                (),
                {"buffer": type("B", (), {"read": staticmethod(lambda: b"{}")})()},
            )(),
        )
        assert entry.main([str(repo)]) == 2
        assert "SECURITY HOOK INACTIVE" in capsys.readouterr().err

    def test_runs_resolved_guard(self, tmp_path: Path, monkeypatch):
        repo = _make_repo(tmp_path, with_guard=True, guard_exit=7)
        monkeypatch.setattr(
            "sys.stdin",
            type(
                "S",
                (),
                {"buffer": type("B", (), {"read": staticmethod(lambda: b"{}")})()},
            )(),
        )
        # main delegates to the stub guard which exits 7.
        assert entry.main([str(repo)]) == 7


class TestCanonicalCommand:
    def test_command_references_entrypoint_and_fail_closed(self):
        cmd = entry.canonical_hook_command()
        assert "claude_guard_entry.py" in cmd
        assert "fail-closed" in cmd
        assert cmd.startswith('python -c "')
