#!/usr/bin/env python3
# ruff: noqa: PERF203
"""
Test Suite para Refactor-Kit Portable

Valida que:
1. Estructura del kit es correcta
2. No hay dependencias de z_scripts
3. Templates son vÃ¡lidos
4. Instalador funciona
5. RefactorManager es importable
"""

import subprocess
import sys
import tempfile
from pathlib import Path


def test_refactor_kit_structure():
    """Test 1: Verificar estructura de directorios y archivos"""
    print("\n[TEST 1] Refactor Kit Structure...")

    kit_dir = Path(__file__).parent.parent / "agent_system" / "refactor-kit"
    print(f"  Kit dir: {kit_dir}")

    # Verificar directorios
    required_dirs = ["", "prompt_templates"]
    for d in required_dirs:
        dir_path = kit_dir / d if d else kit_dir
        if not dir_path.is_dir():
            print(f"  FAIL: Missing directory {dir_path}")
            return False

    # Verificar archivos
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

    for f in required_files:
        file_path = kit_dir / f
        if not file_path.exists():
            print(f"  FAIL: Missing file {file_path}")
            return False

    print(f"  [PASS] All {len(required_files)} files and directories present")
    return True


def test_prompt_templates():
    """Test 2: Verificar que templates tienen contenido vÃ¡lido"""
    print("\n[TEST 2] Prompt Templates...")

    kit_dir = Path(__file__).parent.parent / "agent_system" / "refactor-kit"

    templates = [
        "01_analysis.md",
        "02_plan.md",
        "03_refactor.md",
        "04_validation.md",
        "05_iteration.md",
    ]

    for template in templates:
        template_path = kit_dir / "prompt_templates" / template
        if not template_path.exists():
            print(f"  [FAIL] Template {template} not found")
            return False

        content = template_path.read_text(encoding="utf-8")
        if len(content.strip()) < 50:
            print(f"  FAIL: Template {template} too short ({len(content)} chars)")
            return False

    print(f"  [PASS] All {len(templates)} templates are valid")
    return True


def test_refactor_manager_importable():
    """Test 3: Verificar que RefactorManager se puede importar"""
    print("\n[TEST 3] RefactorManager Import...")

    try:
        sys.path.insert(
            0, str(Path(__file__).parent.parent / "agent_system" / "refactor-kit")
        )
        from refactor_manager import RefactorManager

        # Verificar que tiene mÃ©todos
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
            if not hasattr(RefactorManager, method):
                print(f"  FAIL: Missing method {method}")
                return False

        print(f"  PASS: RefactorManager imported with {len(required_methods)} methods")
        return True

    except ImportError as e:
        print(f"  FAIL: Cannot import RefactorManager: {e}")
        return False


def test_installer_functionality():
    """Test 4: Verificar que el instalador funciona"""
    print("\n[TEST 4] Installer Functionality...")

    kit_dir = Path(__file__).parent.parent / "agent_system" / "refactor-kit"
    installer = kit_dir / "install_refactor_kit.py"

    if not installer.exists():
        print("  FAIL: install_refactor_kit.py not found")
        return False

    # Crear directorio temporal para test
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_project = Path(temp_dir) / "test_project"
        temp_project.mkdir()

        # Ejecutar instalador
        try:
            result = subprocess.run(
                [sys.executable, str(installer), str(temp_project)],
                capture_output=True,
                text=True,
                timeout=30,
                shell=False,
            )

            if result.returncode != 0:
                print(f"  FAIL: Installer failed: {result.stderr}")
                return False

            # Verificar que se creÃ³ .refactor/kit
            refactor_kit_dir = temp_project / ".refactor" / "kit"
            if not refactor_kit_dir.exists():
                print("  FAIL: .refactor/kit directory not created")
                return False

            # Verificar archivos instalados
            expected_files = ["__init__.py", "refactor_manager.py", "README.md"]
            for f in expected_files:
                if not (refactor_kit_dir / f).exists():
                    print(f"  FAIL: File {f} not installed")
                    return False

            print("  PASS: Installer created refactor-kit directory with all files")
            return True

        except subprocess.TimeoutExpired:
            print("  FAIL: Installer timeout")
            return False
        except Exception as e:
            print(f"  FAIL: Installer error: {e}")
            return False


def test_portability_no_z_scripts_deps():
    """Test 5: Verificar cero dependencias de z_scripts"""
    print("\n[TEST 5] Portability (No z_scripts Dependencies)...")

    kit_dir = Path(__file__).parent.parent / "agent_system" / "refactor-kit"

    # Buscar imports de z_scripts en todos los archivos
    z_scripts_imports = []

    for py_file in kit_dir.rglob("*.py"):
        try:
            content = py_file.read_text(encoding="utf-8")
            lines = content.split("\n")
            for i, line in enumerate(lines, 1):
                if "from z_scripts" in line or "import z_scripts" in line:
                    z_scripts_imports.append(f"{py_file.name}:{i}: {line.strip()}")
        except Exception as e:
            print(f"  FAIL: Error reading {py_file}: {e}")
            return False

    if z_scripts_imports:
        print("  FAIL: Found z_scripts imports:")
        for imp in z_scripts_imports:
            print(f"    {imp}")
        return False

    print("  PASS: Zero z_scripts dependencies found")
    return True


def main():
    """Run all tests"""
    print("=" * 60)
    print("  REFACTOR-KIT PORTABLE TEST SUITE")
    print("=" * 60)

    tests = [
        test_refactor_kit_structure,
        test_prompt_templates,
        test_refactor_manager_importable,
        test_installer_functionality,
        test_portability_no_z_scripts_deps,
    ]

    results = [test() for test in tests]

    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)

    if all(results):
        print(f"  ALL TESTS PASSED ({passed}/{total})")
        print("  Refactor-Kit is PORTABLE and READY for any Python project")
        print("=" * 60)
        return 0
    else:
        print(f"  SOME TESTS FAILED ({passed}/{total})")
        print("  Fix issues before deploying to other projects")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
