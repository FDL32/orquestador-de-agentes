#!/usr/bin/env python3
# ruff: noqa: S101
"""
Test Suite for Goose Native Skill Integration

Validates that:
1. goose-skill.json is valid manifest
2. goose_integration.py can be imported
3. RefactorManager supports goose_context
4. Backward compatibility maintained
5. Native skill invocation works
"""

import json
from pathlib import Path


def test_skill_manifest():
    """Verify goose-skill.json is valid JSON with required fields."""
    manifest_file = Path("skills/refactor-manager/goose-skill.json")
    assert manifest_file.exists(), "goose-skill.json not found"

    with open(manifest_file, encoding="utf-8-sig") as f:
        manifest = json.load(f)

    assert manifest["name"] == "refactor-manager"
    assert manifest["version"] == "1.0.0"
    assert manifest["entry_point"] == "agent_system.refactor_kit:RefactorManager"
    assert "/refactor" in manifest["triggers"]
    assert manifest["approval_gates"]
    print("[PASS] Skill manifest valid")


def test_goose_integration_import():
    """Verify goose_integration.py can be imported."""
    import importlib.util
    import sys

    sys.path.insert(0, "..")
    sys.path.insert(0, ".")

    # Import using importlib due to hyphen in directory name
    spec = importlib.util.spec_from_file_location(
        "goose_integration", "skills/refactor-manager/goose_integration.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert callable(module.invoke)
    print("[PASS] Wrapper callable")


def test_refactor_manager_goose_context():
    """Verify RefactorManager accepts goose_context parameter."""
    import sys

    sys.path.insert(0, "..")
    from agent_system.refactor_kit import RefactorManager

    manager = RefactorManager(target="scripts/discover_skills.py", goose_context=True)
    assert manager.goose_context
    print("[PASS] RefactorManager accepts goose_context")


def test_backward_compatibility():
    """Verify CLI (goose_context=False) still works."""
    import sys

    sys.path.insert(0, "..")
    from agent_system.refactor_kit import RefactorManager

    manager = RefactorManager(target="scripts/discover_skills.py")
    assert not manager.goose_context  # Default is False
    print("[PASS] Backward compatibility maintained")


def test_native_skill_invocation():
    """Test that invoke() can be called and returns proper structure."""
    import importlib.util
    import sys

    sys.path.insert(0, "..")
    sys.path.insert(0, ".")

    # Import using importlib
    spec = importlib.util.spec_from_file_location(
        "goose_integration", "skills/refactor-manager/goose_integration.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    invoke = module.invoke

    # Test with a simple file that exists
    result = invoke(target="scripts/discover_skills.py")

    # Should return a dict
    assert isinstance(result, dict)
    assert result["status"] in ["COMPLETED", "FAILED"]
    assert "target" in result

    if result["status"] == "COMPLETED":
        assert "phases" in result
        assert "artifacts" in result
    else:
        assert "error" in result

    print(
        f"[PASS] Invocation returned: status={result['status']}, target={result['target']}"
    )
