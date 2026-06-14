#!/usr/bin/env python3
# ruff: noqa: PERF203
"""Regression tests for the portable Refactor-Kit bundle."""

import subprocess
import sys
import tempfile
from pathlib import Path


KIT_DIR = Path(__file__).parent.parent / "agent_system" / "refactor_kit"


def test_refactor_kit_structure():
    """The refactor-kit bundle keeps its expected portable structure."""
    required_dirs = ["", "prompt_templates"]
    for directory in required_dirs:
        dir_path = KIT_DIR / directory if directory else KIT_DIR
        assert dir_path.is_dir(), f"Missing directory {dir_path}"

    required_files = [
        "__init__.py",
        "refactor_manager.py",
        "install_refactor_kit.py",
        "README.md",
        "prompt_templates/01_analysis.md",
        "prompt_templates/02_plan.md",
        "prompt_templates/03_refactor.md",
        "prompt_templates/04_validation.md",
        "prompt_templates/05_iteration.md",
    ]

    for file_name in required_files:
        assert (KIT_DIR / file_name).exists(), f"Missing file {file_name}"


def test_prompt_templates():
    """Prompt templates exist and contain substantive instructions."""
    templates = [
        "01_analysis.md",
        "02_plan.md",
        "03_refactor.md",
        "04_validation.md",
        "05_iteration.md",
    ]

    for template in templates:
        template_path = KIT_DIR / "prompt_templates" / template
        assert template_path.exists(), f"Template {template} not found"
        content = template_path.read_text(encoding="utf-8")
        assert len(content.strip()) >= 50, (
            f"Template {template} too short ({len(content)} chars)"
        )


def test_refactor_manager_importable():
    """RefactorManager remains importable with its public phase methods."""
    sys.path.insert(0, str(KIT_DIR))
    from refactor_manager import RefactorManager

    required_methods = [
        "run",
        "phase_1_analysis",
        "phase_2_plan",
        "phase_3_refactor",
        "phase_4_validation",
        "phase_5_iteration",
        "_call_agent",
        "_wait_for_approval",
    ]

    for method in required_methods:
        assert hasattr(RefactorManager, method), f"Missing method {method}"


def test_installer_functionality():
    """The installer creates a usable .refactor/kit directory."""
    installer = KIT_DIR / "install_refactor_kit.py"
    assert installer.exists(), "install_refactor_kit.py not found"

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_project = Path(temp_dir) / "test_project"
        temp_project.mkdir()

        result = subprocess.run(
            [sys.executable, str(installer), str(temp_project)],
            capture_output=True,
            text=True,
            timeout=30,
            shell=False,
        )

        assert result.returncode == 0, f"Installer failed: {result.stderr}"

        refactor_kit_dir = temp_project / ".refactor" / "kit"
        assert refactor_kit_dir.exists(), ".refactor/kit directory not created"

        expected_files = ["__init__.py", "refactor_manager.py", "README.md"]
        for file_name in expected_files:
            assert (refactor_kit_dir / file_name).exists(), (
                f"File {file_name} not installed"
            )


def test_portability_no_z_scripts_deps():
    """The portable bundle must not import local z_scripts modules."""
    z_scripts_imports = []

    for py_file in KIT_DIR.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        for line_number, line in enumerate(content.splitlines(), 1):
            if "from z_scripts" in line or "import z_scripts" in line:
                z_scripts_imports.append(
                    f"{py_file.name}:{line_number}: {line.strip()}"
                )

    assert not z_scripts_imports, "Found z_scripts imports:\n" + "\n".join(
        z_scripts_imports
    )


def main():
    """Run tests when executed as a standalone smoke script."""
    tests = [
        test_refactor_kit_structure,
        test_prompt_templates,
        test_refactor_manager_importable,
        test_installer_functionality,
        test_portability_no_z_scripts_deps,
    ]

    failures = []
    for test in tests:
        try:
            test()
        except AssertionError as exc:
            failures.append(f"{test.__name__}: {exc}")

    if failures:
        print("\n".join(failures))
        return 1
    print(f"ALL TESTS PASSED ({len(tests)}/{len(tests)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
