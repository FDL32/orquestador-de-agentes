from __future__ import annotations

from pathlib import Path

import skills.validate_all as validate_all


def _write_skill(skill_dir: Path) -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                "name: demo-skill",
                "version: 2.0.0",
                "description: Demo skill",
                "author: agent",
                "role: builder",
                "stage: implement",
                "writes_memory: false",
                "quality_gate: true",
                "tags: [core, system]",
                "---",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_validate_all_skills_ignores_shared_directories(tmp_path, monkeypatch):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    shared_dir = skills_dir / "_shared"
    shared_dir.mkdir()
    (shared_dir / "anti-patterns.md").write_text("AP-01 | Mock drift", encoding="utf-8")

    skill_dir = skills_dir / "demo-skill"
    _write_skill(skill_dir)
    (skill_dir / "references").mkdir()
    (skill_dir / "references" / ".gitkeep").write_text("", encoding="utf-8")

    monkeypatch.setattr(validate_all, "SKILLS_DIR", skills_dir)

    results = validate_all.validate_all_skills()

    assert results["total"] == 1
    assert results["valid"] == 1
    assert results["invalid"] == 0


def test_extract_frontmatter_parses_boolean_fields():
    content = "\n".join(
        [
            "---",
            "name: demo-skill",
            "version: 2.0.0",
            "description: Demo skill",
            "author: agent",
            "role: builder",
            "stage: implement",
            "writes_memory: true",
            "quality_gate: false",
            "tags: [core, system]",
            "---",
        ]
    )
    content += "\n"

    frontmatter = validate_all.extract_frontmatter(content)

    assert frontmatter is not None
    assert frontmatter["writes_memory"] is True
    assert frontmatter["quality_gate"] is False
