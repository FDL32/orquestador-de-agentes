"""Unit tests for install_agent_system.py memory-sync functions (WP-2026-179).

Covers:
- parse_wing_sections: wing header parsing and legacy retrocompat
- merge_memory_rules: engine/meta updated, project preserved, idempotency
- sync_memory_rules: dry-run, missing source, file creation, no L1/L3 touch
"""

from __future__ import annotations

import textwrap

from scripts.install_agent_system import (
    merge_memory_rules,
    parse_wing_sections,
    sync_memory_rules,
)


# ---------------------------------------------------------------------------
# parse_wing_sections
# ---------------------------------------------------------------------------


def test_parse_wing_sections_empty_content():
    assert parse_wing_sections("") == {}
    assert parse_wing_sections("   \n  ") == {}


def test_parse_wing_sections_no_wings_retrocompat():
    """Legacy file without Wing headers → entire content maps to 'project'."""
    content = "## Domain: python-hygiene\n\n- Use pathlib\n"
    sections = parse_wing_sections(content)
    assert set(sections.keys()) == {"project"}
    assert "python-hygiene" in sections["project"]


def test_parse_wing_sections_with_wings():
    content = textwrap.dedent("""\
        ## Wing: engine
        ### Domain: architecture
        - Rule A

        ## Wing: meta
        ### Domain: workflow
        - Rule B

        ## Wing: project
        ### Domain: local
        - Rule C
    """)
    sections = parse_wing_sections(content)
    assert set(sections.keys()) == {"engine", "meta", "project"}
    assert "architecture" in sections["engine"]
    assert "workflow" in sections["meta"]
    assert "local" in sections["project"]


def test_parse_wing_sections_normalises_to_lowercase():
    content = "## Wing: Engine\n### Domain: d\n- rule\n"
    sections = parse_wing_sections(content)
    assert "engine" in sections


def test_parse_wing_sections_only_engine():
    content = "## Wing: engine\n### Domain: d\n- rule\n"
    sections = parse_wing_sections(content)
    assert sections.keys() == {"engine"}


# ---------------------------------------------------------------------------
# merge_memory_rules
# ---------------------------------------------------------------------------

ENGINE_BLOCK = "## Wing: engine\n### Domain: arch\n- Eng rule\n"
META_BLOCK = "## Wing: meta\n### Domain: workflow\n- Meta rule\n"
PROJECT_BLOCK = "## Wing: project\n### Domain: local\n- Local rule\n"

FULL_SOURCE = ENGINE_BLOCK + "\n" + META_BLOCK
FULL_DEST = PROJECT_BLOCK


def test_merge_preserves_project_wing():
    result = merge_memory_rules(FULL_SOURCE, FULL_DEST)
    assert "local" in result
    assert "Local rule" in result


def test_merge_updates_engine_wing():
    result = merge_memory_rules(FULL_SOURCE, FULL_DEST)
    assert "arch" in result
    assert "Eng rule" in result


def test_merge_updates_meta_wing():
    result = merge_memory_rules(FULL_SOURCE, FULL_DEST)
    assert "workflow" in result
    assert "Meta rule" in result


def test_merge_canonical_order():
    """Engine must appear before meta, meta before project."""
    result = merge_memory_rules(FULL_SOURCE, FULL_DEST)
    eng_pos = result.index("## Wing: engine")
    meta_pos = result.index("## Wing: meta")
    proj_pos = result.index("## Wing: project")
    assert eng_pos < meta_pos < proj_pos


def test_merge_idempotent():
    """Applying merge twice produces the same output."""
    first_pass = merge_memory_rules(FULL_SOURCE, FULL_DEST)
    second_pass = merge_memory_rules(FULL_SOURCE, first_pass)
    assert first_pass == second_pass


def test_merge_empty_dest():
    """When dest has no content, only engine/meta wings from source are written."""
    result = merge_memory_rules(FULL_SOURCE, "")
    assert "Eng rule" in result
    assert "Meta rule" in result
    # No project section expected
    assert "## Wing: project" not in result


def test_merge_legacy_dest_kept_as_project():
    """Legacy dest without Wing headers gets treated as project."""
    legacy_dest = "## Domain: old-domain\n- old rule\n"
    result = merge_memory_rules(FULL_SOURCE, legacy_dest)
    # Engine/meta from source present
    assert "Eng rule" in result
    # Legacy content preserved under project wing
    assert "old rule" in result


def test_merge_does_not_copy_project_from_source():
    """Source may have a project wing, but it must NOT override dest project."""
    source_with_project = (
        ENGINE_BLOCK
        + "\n"
        + "## Wing: project\n### Domain: source-proj\n- Source proj rule\n"
    )
    result = merge_memory_rules(source_with_project, PROJECT_BLOCK)
    # Dest project wing preserved
    assert "Local rule" in result
    # Source project wing not injected
    assert "Source proj rule" not in result


def test_merge_empty_source_returns_dest():
    """When source has no content, dest is unchanged."""
    result = merge_memory_rules("", PROJECT_BLOCK)
    assert result == PROJECT_BLOCK


# ---------------------------------------------------------------------------
# sync_memory_rules
# ---------------------------------------------------------------------------


def test_sync_memory_rules_dry_run(tmp_path, capsys):
    template_agent = tmp_path / "template" / ".agent"
    src_mem = template_agent / "runtime" / "memory"
    src_mem.mkdir(parents=True)
    (src_mem / "memory_rules.md").write_text(ENGINE_BLOCK, encoding="utf-8")

    project_agent = tmp_path / "dest" / ".agent"
    project_agent.mkdir(parents=True)

    sync_memory_rules(template_agent, project_agent, dry_run=True)
    out = capsys.readouterr().out
    assert "DRY-RUN" in out
    # File must NOT be created
    assert not (project_agent / "runtime" / "memory" / "memory_rules.md").exists()


def test_sync_memory_rules_missing_source_skips(tmp_path, capsys):
    template_agent = tmp_path / "template" / ".agent"
    template_agent.mkdir(parents=True)

    project_agent = tmp_path / "dest" / ".agent"
    project_agent.mkdir(parents=True)

    sync_memory_rules(template_agent, project_agent)
    out = capsys.readouterr().out
    assert "skipping" in out.lower()


def test_sync_memory_rules_creates_dest_when_absent(tmp_path):
    template_agent = tmp_path / "template" / ".agent"
    src_mem = template_agent / "runtime" / "memory"
    src_mem.mkdir(parents=True)
    (src_mem / "memory_rules.md").write_text(ENGINE_BLOCK, encoding="utf-8")

    project_agent = tmp_path / "dest" / ".agent"
    project_agent.mkdir(parents=True)

    sync_memory_rules(template_agent, project_agent)
    dest_rules = project_agent / "runtime" / "memory" / "memory_rules.md"
    assert dest_rules.exists()
    assert "Eng rule" in dest_rules.read_text(encoding="utf-8")


def test_sync_memory_rules_does_not_touch_observations(tmp_path):
    """observations.jsonl in dest must be untouched."""
    template_agent = tmp_path / "template" / ".agent"
    src_mem = template_agent / "runtime" / "memory"
    src_mem.mkdir(parents=True)
    (src_mem / "memory_rules.md").write_text(ENGINE_BLOCK, encoding="utf-8")

    project_agent = tmp_path / "dest" / ".agent"
    dest_mem = project_agent / "runtime" / "memory"
    dest_mem.mkdir(parents=True)
    obs = dest_mem / "observations.jsonl"
    obs.write_text('{"signal": "keep me"}\n', encoding="utf-8")

    sync_memory_rules(template_agent, project_agent)

    assert obs.read_text(encoding="utf-8") == '{"signal": "keep me"}\n'


def test_sync_memory_rules_does_not_touch_profile(tmp_path):
    """memory_profile.md in dest must be untouched."""
    template_agent = tmp_path / "template" / ".agent"
    src_mem = template_agent / "runtime" / "memory"
    src_mem.mkdir(parents=True)
    (src_mem / "memory_rules.md").write_text(ENGINE_BLOCK, encoding="utf-8")

    project_agent = tmp_path / "dest" / ".agent"
    dest_mem = project_agent / "runtime" / "memory"
    dest_mem.mkdir(parents=True)
    profile = dest_mem / "memory_profile.md"
    profile.write_text("# My Profile\n", encoding="utf-8")

    sync_memory_rules(template_agent, project_agent)

    assert profile.read_text(encoding="utf-8") == "# My Profile\n"


def test_sync_memory_rules_idempotent(tmp_path):
    """Running sync twice produces the same file."""
    template_agent = tmp_path / "template" / ".agent"
    src_mem = template_agent / "runtime" / "memory"
    src_mem.mkdir(parents=True)
    (src_mem / "memory_rules.md").write_text(FULL_SOURCE, encoding="utf-8")

    project_agent = tmp_path / "dest" / ".agent"
    dest_mem = project_agent / "runtime" / "memory"
    dest_mem.mkdir(parents=True)
    dest_rules = dest_mem / "memory_rules.md"
    dest_rules.write_text(PROJECT_BLOCK, encoding="utf-8")

    sync_memory_rules(template_agent, project_agent)
    after_first = dest_rules.read_text(encoding="utf-8")

    sync_memory_rules(template_agent, project_agent)
    after_second = dest_rules.read_text(encoding="utf-8")

    assert after_first == after_second
