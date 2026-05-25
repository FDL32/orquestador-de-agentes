"""
Test para detectar referencias obsoletas en documentacion operativa ACTIVA
Evita que vuelvan comandos antiguos que ya no existen en v5

ALCANCE DOCUMENTAL:
- DOCUMENTACION OPERATIVA ACTIVA: Archivos que contienen instrucciones vigentes
  para usar el sistema (README, workflows, skills principales, referencias activas).
- LEGACY/TEMPLATES: Archivos historicos o plantillas que NO son instrucciones
  vigentes. Pueden contener contenido antiguo pero no se usan como fuente de verdad.

Los checks de referencias obsoletas SOLO aplican a docs operativas activas.
Legacy/templates se excluyen por diseÃ±o para evitar falsos positivos.
"""

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).parent.parent
AGENT_DIR = ROOT / ".agent"

# DOCUMENTACION OPERATIVA ACTIVA: Instrucciones vigentes del sistema
# Estos archivos contienen comandos y referencias que los usuarios deben seguir actualmente.
ACTIVE_OPERATIONAL_DOCS = [
    AGENT_DIR / "README.md",
    AGENT_DIR / "workflows" / "manager_workflow.md",
    AGENT_DIR / "workflows" / "builder_workflow.md",
    ROOT / "skills" / "bui-run-quality-gates" / "SKILL.md",
    ROOT / "skills" / "bui-implement-from-plan" / "SKILL.md",
    ROOT / "skills" / "bui-self-audit" / "SKILL.md",
    ROOT / "skills" / "man-review-implementation" / "SKILL.md",
    ROOT / "skills" / "bui-run-quality-gates" / "references" / "common-fixes.md",
    ROOT / "skills" / "bui-implement-from-plan" / "references" / "log-format.md",
]

# LEGACY/TEMPLATES: Archivos historicos o plantillas (NO instrucciones vigentes)
# Estos archivos pueden contener contenido antiguo pero NO se usan como fuente de verdad operacional.
# Se incluyen en encoding checks pero se EXCLUYEN de checks de referencias obsoletas.
LEGACY_TEMPLATE_DOCS = [
    AGENT_DIR / "templates" / "work_plan_template.md",
    AGENT_DIR / "templates" / "findings_template.md",
    AGENT_DIR / "templates" / "PRIVATE_REGISTRY.md",
    AGENT_DIR / "templates" / "work_plan_example_v2.md",
    AGENT_DIR / "legacy" / "manager_workflow.md",
    AGENT_DIR / "legacy" / "builder_workflow.md",
    AGENT_DIR / "legacy" / "MANAGER_SKILLS.md",
    AGENT_DIR / "legacy" / "BUILDER_SKILLS.md",
    AGENT_DIR / "legacy" / "MANAGER_CONTEXT.md",
    AGENT_DIR / "legacy" / "BUILDER_CONTEXT.md",
]

# Todos los archivos para checks de encoding (activos + legacy/templates)
FILES_TO_CHECK_ENCODING = ACTIVE_OPERATIONAL_DOCS + LEGACY_TEMPLATE_DOCS

# Solo docs operativas activas para checks de referencias obsoletas
FILES_TO_CHECK_REFERENCES = ACTIVE_OPERATIONAL_DOCS

# Comandos OBSOLETOS que NO deben aparecer nunca mas en la documentacion
OBSOLETE_COMMANDS = [
    r"uv run ruff",
    r"uv run pytest",
    r"src/.*obligatorio",
    r"require.*src/",
    r"ruff check src/ tests/",
    r"v2\.0",
]

# Comandos ACTUALES que SI deben aparecer (solo en README)
REQUIRED_COMMANDS = [
    r"run_pytest_safe\.py",
    r"agent_controller\.py --validate",
]


@pytest.mark.parametrize("file_path", FILES_TO_CHECK_REFERENCES)
def test_no_obsolete_commands_in_operational_docs(file_path):
    if not file_path.exists():
        pytest.skip(f"File {file_path} does not exist")

    content = file_path.read_text(encoding="utf-8")

    found = []
    for pattern in OBSOLETE_COMMANDS:
        matches = re.findall(pattern, content, re.IGNORECASE)
        if matches:
            found.extend(matches)

    assert len(found) == 0, (
        f"Comandos obsoletos encontrados en {file_path.name}: {found}"
    )


def test_required_commands_are_present_in_readme():
    readme_path = AGENT_DIR / "README.md"
    readme_content = readme_path.read_text(encoding="utf-8")

    missing = [
        pattern
        for pattern in REQUIRED_COMMANDS
        if not re.search(pattern, readme_content)
    ]

    assert len(missing) == 0, f"Comandos actuales faltantes en README: {missing}"


@pytest.mark.parametrize("file_path", FILES_TO_CHECK_REFERENCES)
def test_no_src_requirement_note(file_path):
    if not file_path.exists():
        pytest.skip(f"File {file_path} does not exist")

    content = file_path.read_text(encoding="utf-8")

    # Verificar que no dice que src/ es obligatorio
    assert "requiere `src/`" not in content
    assert "Quality Gate requiere src/" not in content
