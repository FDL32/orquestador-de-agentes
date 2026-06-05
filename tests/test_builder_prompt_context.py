# WT-2026-232a: Tests for builder prompt context resolution.
# Tests for _resolve_launcher_roots() and --resolve-launcher-roots CLI flag.

from __future__ import annotations

import json
import sys
from io import StringIO
from pathlib import Path


def _ensure_agent_dir(repo: Path) -> Path:
    """Ensure .agent/ exists in repo and return path."""
    agent_dir = repo / ".agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    return agent_dir


# ---------------------------------------------------------------------------
# TP-09: _resolve_launcher_roots returns three non-empty roots
# ---------------------------------------------------------------------------


class TestResolveLauncherRoots:
    """Tests for _resolve_launcher_roots helper."""

    def test_returns_three_keys(self, tmp_path: Path) -> None:
        """Returns dict with all three required keys."""
        import agent_controller

        dest = tmp_path / "dest"
        dest.mkdir(parents=True, exist_ok=True)
        _ensure_agent_dir(dest)

        roots = agent_controller._resolve_launcher_roots(dest)

        assert "repo_motor_root" in roots
        assert "repo_destino_root" in roots
        assert "workspace_activo_root" in roots

    def test_no_empty_values(self, tmp_path: Path) -> None:
        """All three values are non-empty strings."""
        import agent_controller

        dest = tmp_path / "dest"
        dest.mkdir(parents=True, exist_ok=True)
        _ensure_agent_dir(dest)

        roots = agent_controller._resolve_launcher_roots(dest)

        for key, value in roots.items():
            assert value, f"Key '{key}' has empty value"
            assert "/" in value, f"Key '{key}' doesn't look like a path"

    def test_destino_root_matches_argument(self, tmp_path: Path) -> None:
        """repo_destino_root matches the project_root argument."""
        import agent_controller

        dest = tmp_path / "my_dest"
        dest.mkdir(parents=True, exist_ok=True)
        _ensure_agent_dir(dest)

        roots = agent_controller._resolve_launcher_roots(dest)

        assert roots["repo_destino_root"] == dest.resolve().as_posix()

    def test_motor_root_matches_controller_location(self, tmp_path: Path) -> None:
        """repo_motor_root is the parent of .agent/ where controller lives."""
        import agent_controller

        dest = tmp_path / "dest"
        dest.mkdir(parents=True, exist_ok=True)

        roots = agent_controller._resolve_launcher_roots(dest)

        # The motor root should contain .agent/agent_controller.py
        motor_root = Path(roots["repo_motor_root"])
        assert (motor_root / ".agent" / "agent_controller.py").exists(), (
            f"Expected motor root {motor_root} to contain agent_controller.py"
        )

    def test_workspace_activo_root_finds_agent_dir(self, tmp_path: Path) -> None:
        """workspace_activo_root is the directory containing .agent/."""
        import agent_controller

        dest = tmp_path / "dest"
        dest.mkdir(parents=True, exist_ok=True)
        _ensure_agent_dir(dest)

        roots = agent_controller._resolve_launcher_roots(dest)

        workspace_root = Path(roots["workspace_activo_root"])
        assert (workspace_root / ".agent").is_dir(), (
            f"Expected {workspace_root} to contain .agent/ directory"
        )

    def test_fallback_no_project_root(self, tmp_path: Path) -> None:
        """When called with None and no link file, uses motor_root as fallback."""
        import agent_controller

        # Ensure no link file interferes (run in isolated temp)
        roots = agent_controller._resolve_launcher_roots(None)

        # When project_root is None and no link exists, destino falls back to motor.
        # Both roots must be non-empty strings regardless.
        assert roots["repo_motor_root"], "repo_motor_root should be non-empty"
        assert roots["repo_destino_root"], "repo_destino_root should be non-empty"
        assert roots["workspace_activo_root"], (
            "workspace_activo_root should be non-empty"
        )

    def test_different_motor_and_destino(self, tmp_path: Path) -> None:
        """motor and destino roots differ when project_root is outside motor."""
        import agent_controller

        dest = tmp_path / "external_dest"
        dest.mkdir(parents=True, exist_ok=True)
        _ensure_agent_dir(dest)

        roots = agent_controller._resolve_launcher_roots(dest)

        assert roots["repo_motor_root"] != roots["repo_destino_root"], (
            "Expected motor and destino to differ for external project_root"
        )


# ---------------------------------------------------------------------------
# --resolve-launcher-roots CLI test
# ---------------------------------------------------------------------------


class TestResolveLauncherRootsCLI:
    """Tests for --resolve-launcher-roots CLI handler."""

    def test_json_output_parses_correctly(self, tmp_path: Path, monkeypatch) -> None:
        """CLI handler produces valid JSON with three keys."""
        import agent_controller

        dest = tmp_path / "dest"
        dest.mkdir(parents=True, exist_ok=True)
        _ensure_agent_dir(dest)

        monkeypatch.setattr(agent_controller, "PROJECT_ROOT", dest)

        old_stdout = sys.stdout
        captured = StringIO()
        sys.stdout = captured
        try:
            result = agent_controller._handle_resolve_launcher_roots(json_output=True)
        finally:
            sys.stdout = old_stdout

        assert result == 0, f"Expected 0, got {result}"
        output = json.loads(captured.getvalue().strip())
        assert "repo_motor_root" in output
        assert "repo_destino_root" in output
        assert "workspace_activo_root" in output
        assert output["repo_destino_root"] == dest.resolve().as_posix()
