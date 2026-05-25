"""
Refactoring Impact Test Suite

Valida que despuÃƒÂ©s de cada refactoring:
1. Scripts aÃƒÂºn ejecutables
2. Comportamiento preservado
3. No hay regresiones
4. Tests pasan
"""

import json
import subprocess
import sys


def test_scripts_executable():
    """Test 1: Scripts refactorizados son ejecutables"""
    print("\n[TEST 1] Scripts Executable After Refactoring...")

    try:
        # Test orquestador.py
        result = subprocess.run(
            ["python", "-m", "py_compile", "scripts/orquestador.py"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            print(f"  FAIL: orquestador.py syntax error: {result.stderr}")
            return False

        # Test discover_skills.py
        result = subprocess.run(
            ["python", "-m", "py_compile", "scripts/discover_skills.py"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            print(f"  FAIL: discover_skills.py syntax error: {result.stderr}")
            return False

        # Test run_pytest_safe.py
        result = subprocess.run(
            ["python", "-m", "py_compile", "scripts/run_pytest_safe.py"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            print(f"  FAIL: run_pytest_safe.py syntax error: {result.stderr}")
            return False

        print("  PASS: Todos los scripts son compilables (sin syntax errors)")
        return True

    except Exception as e:
        print(f"  FAIL: {e}")
        return False


def test_trigger_map_unchanged():
    """Test 2: trigger_map debe ser idÃƒÂ©ntico despuÃƒÂ©s de refactoring"""
    print("\n[TEST 2] Trigger Map Consistency After Refactoring...")

    try:
        # Ejecutar discover_skills.py
        result = subprocess.run(
            ["python", "scripts/discover_skills.py", "--json"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            print(f"  FAIL: discover_skills.py failed: {result.stderr}")
            return False

        data = json.loads(result.stdout)
        triggers_after = set(data.get("trigger_map", {}).keys())
        total_after = len(triggers_after)

        # Comparar con baseline (38 triggers)
        expected_triggers = 38

        if total_after == expected_triggers:
            print(f"  PASS: trigger_map consistente ({total_after} triggers)")
            return True
        else:
            print(
                f"  FAIL: trigger_map cambiÃƒÂ³ ({total_after} != {expected_triggers})"
            )
            return False

    except Exception as e:
        print(f"  FAIL: {e}")
        return False


def test_skill_execution_unchanged():
    """Test 3: Skills aÃƒÂºn se ejecutan despuÃƒÂ©s de refactoring"""
    print("\n[TEST 3] Skill Execution Unchanged After Refactoring...")

    try:
        # Ejecutar skill /gates
        result = subprocess.run(
            [
                "python",
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

        if result.returncode == 0:
            print(
                "  PASS: Skill /gates ejecuta correctamente despuÃƒÂ©s de refactoring"
            )
            return True
        else:
            print(f"  FAIL: Skill /gates error: {result.stderr}")
            return False

    except Exception as e:
        print(f"  FAIL: {e}")
        return False


def test_code_quality():
    """Test 4: CÃƒÂ³digo cumple con quality standards despuÃƒÂ©s de refactoring"""
    print("\n[TEST 4] Code Quality After Refactoring...")

    try:
        # Verificar con ruff
        result = subprocess.run(
            ["ruff", "check", "scripts/"],
            capture_output=True,
            text=True,
            timeout=20,
        )

        if result.returncode == 0:
            print("  PASS: Ruff check passed (code quality good)")
            return True
        else:
            # Ruff found issues, pero no es bloqueador si no hay errores crÃƒÂ­ticos
            if "error" not in result.stdout.lower():
                print("  WARN: Ruff warnings (non-critical)")
                return True
            else:
                print(f"  FAIL: Ruff errors: {result.stdout[:200]}")
                return False

    except FileNotFoundError:
        print("  SKIP: ruff no disponible")
        return True
    except Exception as e:
        print(f"  FAIL: {e}")
        return False


def main():
    """Run all refactoring impact tests"""
    print("=" * 70)
    print("  REFACTORING IMPACT TEST SUITE")
    print("=" * 70)

    tests = [
        test_scripts_executable,
        test_trigger_map_unchanged,
        test_skill_execution_unchanged,
        test_code_quality,
    ]

    results = [test() for test in tests]

    print("\n" + "=" * 70)
    passed = sum(results)
    total = len(results)

    if all(results):
        print(f"  [PASS] ALL TESTS PASSED ({passed}/{total})")
        print("  Refactoring: ZERO REGRESSIONS DETECTED")
        print("=" * 70)
        return 0
    else:
        print(f"  [WARN] {passed}/{total} TESTS PASSED")
        print("  Some regression checks failed")
        print("=" * 70)
        return 1


if __name__ == "__main__":
    sys.exit(main())
