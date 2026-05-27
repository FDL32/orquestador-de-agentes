"""
Tests for WP-2026-151: Retire legacy project_map path.

These tests verify that the legacy generate_project_map() path has been
removed from the controller and that project-map.json is the only
runtime-consumed project-map artifact.
"""

from pathlib import Path

import pytest


# Path to the controller source file
CONTROLLER_PATH = Path(__file__).parent.parent.parent / ".agent" / "agent_controller.py"


class TestLegacyProjectMapCleanup:
    """Static source inspection tests for legacy project_map cleanup."""

    def test_generate_project_map_function_removed(self):
        """Fail if generate_project_map function definition still exists in controller."""
        source = CONTROLLER_PATH.read_text(encoding="utf-8")
        assert "def generate_project_map()" not in source, (
            "generate_project_map() function should be removed from agent_controller.py"
        )

    def test_project_map_constant_removed(self):
        """Fail if PROJECT_MAP constant still exists in controller."""
        source = CONTROLLER_PATH.read_text(encoding="utf-8")
        # Check for the constant definition pattern (not just any reference)
        lines = source.split("\n")
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("PROJECT_MAP ="):
                pytest.fail(
                    f"PROJECT_MAP constant should be removed from agent_controller.py. Found: {stripped}"
                )

    def test_project_map_md_runtime_reference_removed(self):
        """Fail if project_map.md appears in any non-comment line in the controller."""
        source = CONTROLLER_PATH.read_text(encoding="utf-8")
        lines = source.split("\n")
        violations = [
            f"line {i}: {line.strip()}"
            for i, line in enumerate(lines, start=1)
            if "project_map.md" in line and not line.strip().startswith("#")
        ]
        assert not violations, (
            "project_map.md found in non-comment lines of agent_controller.py:\n"
            + "\n".join(violations)
        )

    def test_exclude_files_uses_project_map_json(self):
        """Verify _exclude_files() excludes project-map.json, not project_map.md."""
        source = CONTROLLER_PATH.read_text(encoding="utf-8")
        # Find the _exclude_files function
        in_exclude_files = False
        found_json_exclude = False
        found_md_exclude = False

        for line in source.split("\n"):
            if "def _exclude_files()" in line:
                in_exclude_files = True
            elif in_exclude_files and line.startswith("def "):
                break
            elif in_exclude_files:
                if "project-map.json" in line and "exclude" in line.lower():
                    found_json_exclude = True
                if "project_map.md" in line and "exclude" in line.lower():
                    found_md_exclude = True

        assert found_json_exclude, "_exclude_files() should exclude project-map.json"
        assert not found_md_exclude, (
            "_exclude_files() should not exclude project_map.md (legacy)"
        )

    def test_scanner_context_injection_present(self):
        """Verify scanner-driven context injection is present."""
        source = CONTROLLER_PATH.read_text(encoding="utf-8")
        assert "_inject_scanner_context" in source, (
            "Scanner context injection function should be present"
        )
        assert "project-map.json" in source, (
            "Scanner JSON artifact should be referenced"
        )

    def test_no_legacy_fallback_in_handle_main_action(self):
        """Verify _handle_main_action() does not call generate_project_map()."""
        source = CONTROLLER_PATH.read_text(encoding="utf-8")
        # Find the _handle_main_action function
        in_function = False
        function_lines = []

        for line in source.split("\n"):
            if "def _handle_main_action(" in line:
                in_function = True
            elif in_function and line.strip().startswith("def "):
                break
            elif in_function:
                function_lines.append(line)

        # Check for actual function calls, not comments
        # A call would be on a line that's not a comment and contains the function call syntax
        for line in function_lines:
            stripped = line.strip()
            if not stripped.startswith("#") and "generate_project_map()" in stripped:
                pytest.fail(
                    f"_handle_main_action() should not call generate_project_map(). "
                    f"Found: {stripped}"
                )


class TestScannerContextFlow:
    """Tests for scanner-driven context flow presence."""

    def test_scanner_import_present(self):
        """Verify project_scanner imports are present."""
        source = CONTROLLER_PATH.read_text(encoding="utf-8")
        assert "from scripts.project_scanner import" in source or (
            "from scripts.project_scanner" in source
        ), "Project scanner should be imported"

    def test_scanner_available_flag_present(self):
        """Verify SCANNER_AVAILABLE flag is defined."""
        source = CONTROLLER_PATH.read_text(encoding="utf-8")
        assert "SCANNER_AVAILABLE" in source, "SCANNER_AVAILABLE flag should be defined"

    def test_context_dir_usage_for_json(self):
        """Verify context directory is used for project-map.json."""
        source = CONTROLLER_PATH.read_text(encoding="utf-8")
        assert 'context_dir / "project-map.json"' in source or (
            "context_dir / 'project-map.json'" in source
        ), "Context directory should be used for project-map.json"
