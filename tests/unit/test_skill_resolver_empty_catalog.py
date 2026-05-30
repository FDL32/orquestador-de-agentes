from pathlib import Path

from bus.exceptions import EmptySkillCatalogError


def test_empty_skill_catalog_error_message():
    """Verify that the EmptySkillCatalogError message suggests adding microagents."""
    project_root = Path("/fake/project")
    error = EmptySkillCatalogError(project_root=project_root)

    assert str(project_root) in str(error)
    assert ".agent/microagents/" in str(error)
    assert "Check that skills/ directory contains valid SKILL.md files" in str(error)
