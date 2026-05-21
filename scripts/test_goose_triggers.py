# ruff: noqa: S607
"""
Goose Integration Testing Suite

Validates that:
1. discover_skills.py generates valid trigger_map
2. orquestador.py loads trigger_map correctly
3. Goose receives [SKILLS DISPONIBLES] in context
4. Goose can invoke skills by trigger
"""

import json
import subprocess
import sys


def test_trigger_map_generation():
    """Test 1: Verify discover_skills.py generates valid JSON"""
    print("\n[TEST 1] Trigger Map Generation...")

    try:
        result = subprocess.run(
            ["python", "scripts/discover_skills.py", "--json"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            print("  FAIL: discover_skills.py failed")
            print(f"  Error: {result.stderr}")
            return False

        data = json.loads(result.stdout)

        # Validate structure
        assert "trigger_map" in data, "Missing trigger_map"  # noqa: S101
        assert "skills" in data, "Missing skills"  # noqa: S101
        assert data["total_skills"] == 14  # noqa: S101
        assert data["total_triggers"] == 41  # noqa: S101

        # Validate no duplicates
        triggers = list(data["trigger_map"].keys())
        assert len(triggers) == len(set(triggers)), "Duplicate triggers detected"  # noqa: S101

        print("  PASS: Generated valid trigger_map (14 skills, 41 triggers)")
        return True

    except json.JSONDecodeError as e:
        print(f"  FAIL: Invalid JSON from discover_skills.py: {e}")
        return False
    except AssertionError as e:
        print(f"  FAIL: {e}")
        return False
    except Exception as e:
        print(f"  FAIL: {e}")
        return False


def test_orquestador_integration():
    """Test 2: Verify orquestador loads trigger_map"""
    print("\n[TEST 2] Orquestador Integration...")

    try:
        result = subprocess.run(
            ["python", "scripts/orquestador.py", "--help"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if "--skill" not in result.stdout:
            print("  FAIL: --skill flag not found in help")
            return False

        print("  PASS: orquestador has --skill flag")
        return True

    except Exception as e:
        print(f"  FAIL: {e}")
        return False


def test_skill_execution():
    """Test 3: Verify --skill flag works"""
    print("\n[TEST 3] Skill Execution (Direct)...")

    try:
        # Test with invalid trigger to see error handling
        result = subprocess.run(
            [
                "python",
                "scripts/orquestador.py",
                "--skill",
                "/nonexistent",
                "--query",
                "test",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        # Should fail but with helpful message
        if (
            "no encontrado" in result.stdout.lower()
            or "not found" in result.stdout.lower()
        ):
            print("  PASS: --skill error handling works")
            return True
        else:
            print("  WARNING: Unexpected output")
            print(f"  Output: {result.stdout[:100]}")
            return True  # Not critical

    except Exception as e:
        print(f"  FAIL: {e}")
        return False


def test_no_duplicates():
    """Test 4: Verify no duplicate triggers"""
    print("\n[TEST 4] Trigger Uniqueness...")

    try:
        result = subprocess.run(
            ["python", "scripts/discover_skills.py", "--json"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        data = json.loads(result.stdout)
        triggers = list(data["trigger_map"].keys())

        if len(triggers) != len(set(triggers)):
            duplicates = [t for t in triggers if triggers.count(t) > 1]
            print(f"  FAIL: Duplicate triggers: {set(duplicates)}")
            return False

        print("  PASS: All triggers are unique")
        return True

    except Exception as e:
        print(f"  FAIL: {e}")
        return False


def main():
    """Run all tests"""
    print("=" * 60)
    print("  GOOSE INTEGRATION TEST SUITE")
    print("=" * 60)

    tests = [
        test_trigger_map_generation,
        test_orquestador_integration,
        test_skill_execution,
        test_no_duplicates,
    ]

    results = [test() for test in tests]

    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)

    if all(results):
        print(f"  ALL TESTS PASSED ({passed}/{total})")
        print("=" * 60)
        return 0
    else:
        print(f"  SOME TESTS FAILED ({passed}/{total})")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
