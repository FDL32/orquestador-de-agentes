#!/usr/bin/env python3
# DEPRECATED (WT-2026-254a): Goose integration deprecated. Moved from scripts/ to tests/deprecated/.
"""
Goose Real-World Integration Test

Ejecuta Goose con un plan real y captura:
1. Que Goose recibe trigger_map
2. Que Goose sugiere triggers en conversación
3. Que Builder puede ejecutar los triggers sugeridos
"""

import json
import subprocess
import sys
from pathlib import Path


# Configurar encoding para Windows
if sys.platform == "win32":
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def run_cmd(args, timeout=30):
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        shell=False,
    )


def test_goose_receives_trigger_map():
    """Test 1: Goose recibe trigger_map al startup"""
    print("\n[TEST 1] Goose Receives Trigger Map...")

    try:
        result = run_cmd(
            [
                "python",
                "scripts/orquestador.py",
                "--engine",
                "goose",
                "--query",
                "¿Qué triggers tengo disponibles? Lista los primeros 5.",
            ]
        )

        if result.returncode == 0:
            output = result.stdout
            trigger_keywords = [
                "/implement",
                "/review",
                "/gates",
                "trigger",
                "disponible",
            ]
            found = sum(1 for kw in trigger_keywords if kw.lower() in output.lower())

            if found >= 2:
                print("  PASS: Goose menciona triggers disponibles")
                print(f"  Output sample: {output[:200]}...")
                return True
            else:
                print("  WARNING: Goose no menciona triggers claramente")
                print(f"  Output: {output[:300]}")
                return False
        else:
            print(f"  FAIL: orquestador error: {result.stderr}")
            return False

    except subprocess.TimeoutExpired:
        print("  FAIL: Goose timeout (>30s)")
        return False
    except Exception as e:
        print(f"  FAIL: {e}")
        return False


def test_goose_suggests_workflow():
    """Test 2: Goose sugiere workflow usando triggers"""
    print("\n[TEST 2] Goose Suggests Workflow with Triggers...")

    try:
        plan_path = Path(".session/work_plan.md")
        if not plan_path.exists():
            print("  SKIP: .session/work_plan.md no existe (run from project root)")
            return True

        with open(plan_path, encoding="utf-8", errors="replace") as f:
            plan_content = f.read()[:500]

        query = f"""Basado en este plan, ¿cuál es el workflow que sugiero?

{plan_content}

Sugiere qué triggers puedo usar para cada fase."""

        result = run_cmd(
            ["python", "scripts/orquestador.py", "--engine", "goose", "--query", query],
            timeout=90,
        )

        if result.returncode == 0:
            output = result.stdout
            suggested_triggers = ["/implement", "/review", "/gates", "/audit"]
            found = sum(1 for trigger in suggested_triggers if trigger in output)

            if found >= 1:
                print(f"  PASS: Goose sugirio {found} triggers")
                print(f"  Workflow suggestion: {output[:300]}...")
                return True
            else:
                print("  WARNING: Goose no sugirio triggers explicitos")
                return False
        else:
            print(f"  FAIL: {result.stderr}")
            return False

    except subprocess.TimeoutExpired:
        print("  FAIL: Goose timeout (>45s)")
        return False
    except Exception as e:
        print(f"  FAIL: {e}")
        return False


def test_skill_execution_integration():
    """Test 3: Builder puede ejecutar triggers que Goose sugirió"""
    print("\n[TEST 3] Builder Executes Suggested Triggers...")

    try:
        result = run_cmd(
            [
                "python",
                "scripts/orquestador.py",
                "--skill",
                "/gates",
                "--query",
                "valida la calidad del código",
            ],
            timeout=20,
        )

        if result.returncode == 0:
            print("  PASS: /gates trigger ejecuto correctamente")
            print(f"  Output: {result.stdout[:200]}...")
            return True
        else:
            print(f"  FAIL: /gates returned error: {result.stderr}")
            return False

    except subprocess.TimeoutExpired:
        print("  FAIL: Trigger timeout")
        return False
    except Exception as e:
        print(f"  FAIL: {e}")
        return False


def test_trigger_map_consistency():
    """Test 4: Trigger map es consistente entre ejecuciones"""
    print("\n[TEST 4] Trigger Map Consistency...")

    try:
        results = []
        for i in range(2):
            result = run_cmd(
                ["python", "scripts/discover_skills.py", "--json"], timeout=10
            )

            if result.returncode == 0:
                data = json.loads(result.stdout)
                results.append(set(data["trigger_map"].keys()))
            else:
                print(f"  FAIL: discover_skills.py failed iteration {i + 1}")
                return False

        if results[0] == results[1]:
            print(f"  PASS: Trigger map consistente ({len(results[0])} triggers)")
            return True
        else:
            print("  FAIL: Trigger map inconsistente")
            print(f"    Iteracion 1: {len(results[0])} triggers")
            print(f"    Iteracion 2: {len(results[1])} triggers")
            return False

    except Exception as e:
        print(f"  FAIL: {e}")
        return False


def main():
    """Run all integration tests"""
    print("=" * 70)
    print("  GOOSE REAL-WORLD INTEGRATION TEST SUITE")
    print("=" * 70)

    tests = [
        test_goose_receives_trigger_map,
        test_goose_suggests_workflow,
        test_skill_execution_integration,
        test_trigger_map_consistency,
    ]

    results = [test() for test in tests]

    print("\n" + "=" * 70)
    passed = sum(results)
    total = len(results)

    if all(results):
        print(f"  SUCCESS: ALL TESTS PASSED ({passed}/{total})")
        print("  Goose Real-World Integration: READY")
        print("=" * 70)
        return 0
    else:
        print(f"  WARNING: {passed}/{total} TESTS PASSED")
        print("  Some integration points need attention")
        print("=" * 70)
        return 1


if __name__ == "__main__":
    sys.exit(main())
