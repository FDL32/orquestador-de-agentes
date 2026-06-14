# ruff: noqa: PERF203
"""Regression checks for refactoring-sensitive entrypoints."""

import json
import subprocess
import sys

import pytest


def test_scripts_executable():
    """Refactoring-sensitive scripts remain syntactically valid."""
    scripts = [
        "scripts/orquestador.py",
        "scripts/discover_skills.py",
        "scripts/run_pytest_safe.py",
    ]

    for script in scripts:
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"{script} syntax error: {result.stderr}"


def test_trigger_map_contains_core_triggers():
    """Skill discovery keeps core triggers while allowing new skills to grow."""
    result = subprocess.run(
        [sys.executable, "scripts/discover_skills.py", "--json"],
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, f"discover_skills.py failed: {result.stderr}"

    data = json.loads(result.stdout)
    trigger_map = data.get("trigger_map", {})
    triggers_after = set(trigger_map.keys())

    # Real invariants: the reported count is self-consistent and the core
    # triggers exist. No magic baseline count (skills grow over time).
    assert data.get("total_triggers") == len(trigger_map)

    required_triggers = {
        "/pipeline",
        "/audit-pipeline",
        "/audit-system-health",
        "/gates",
        "/plan",
        "/implement",
    }
    missing = required_triggers - triggers_after
    assert not missing, f"Missing core triggers: {sorted(missing)}"


def test_skill_execution_unchanged():
    """The /gates skill still executes through the legacy orchestrator path."""
    result = subprocess.run(
        [
            sys.executable,
            "scripts/orquestador.py",
            "--skill",
            "/gates",
            "--query",
            "valida calidad",
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, f"Skill /gates error: {result.stderr}"


def test_code_quality():
    """The scripts surface remains ruff-clean after refactoring."""
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "scripts/"],
        capture_output=True,
        text=True,
        timeout=20,
    )

    if result.returncode != 0 and "No module named ruff" in result.stderr:
        pytest.skip("ruff no disponible")

    assert result.returncode == 0, result.stdout[:500] + result.stderr[:500]


def main():
    """Run checks when executed as a standalone smoke script."""
    tests = [
        test_scripts_executable,
        test_trigger_map_contains_core_triggers,
        test_skill_execution_unchanged,
        test_code_quality,
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
