from pathlib import Path

import pytest
from bus.exceptions import EmptySkillCatalogError


def test_empty_skill_catalog_error_message():
    """Verify that the EmptySkillCatalogError message suggests checking SKILL.md format.

    Before: EmptySkillCatalogError receives a project_root.
    During: Error is constructed with a fake project root.
    After: Assert that the error string contains the project root and the
           instruction to check SKILL.md format. Does NOT suggest microagents
           as a workaround for an empty skill catalog.
    """
    project_root = Path("/fake/project")
    error = EmptySkillCatalogError(project_root=project_root)

    assert str(project_root) in str(error)
    assert "Check that skills/ directory contains valid SKILL.md files" in str(error)
    assert ".agent/microagents/" not in str(error)


def test_empty_skill_catalog_error_with_skills_dir():
    """Verify that the error includes skills_dir when provided."""
    project_root = Path("/fake/project")
    skills_dir = Path("/fake/project/custom_skills")
    error = EmptySkillCatalogError(project_root=project_root, skills_dir=skills_dir)

    assert str(skills_dir) in str(error)
    assert "Check that skills/ directory contains valid SKILL.md files" in str(error)


def test_empty_skill_catalog_error_raises_correctly():
    """Verify the exception can be raised and caught properly.

    This is a boundary test ensuring EmptySkillCatalogError is a real exception
    that can be used in try/except blocks.
    """
    with pytest.raises(EmptySkillCatalogError) as exc_info:
        raise EmptySkillCatalogError(project_root=Path("/fake/project"))

    assert "Empty skill catalog" in str(exc_info.value)
    assert exc_info.value.project_root == Path("/fake/project")
