"""Unit tests for install_agent_system.py.

Covers:
- parse_wing_sections: wing header parsing and legacy retrocompat
- merge_memory_rules: engine/meta updated, project preserved, idempotency
- sync_memory_rules: dry-run, missing source, file creation, no L1/L3 touch
- copy_project_template: guard (no overwrite), prefix substitution, dry-run,
  missing template
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from scripts.install_agent_system import (
    copy_destination_bootstrap,
    copy_project_template,
    copy_tree,
    detect_destination_residues,
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


# ---------------------------------------------------------------------------
# copy_project_template
# ---------------------------------------------------------------------------


def _write_template(tmp_path: Path, content: str | None = None) -> Path:
    """Helper: create a PROJECT_TEMPLATE.md in a templates/ dir under tmp_path."""
    template_dir = tmp_path / "agent_system" / "templates"
    template_dir.mkdir(parents=True)
    tpl = template_dir / "PROJECT_TEMPLATE.md"
    if content is None:
        content = (
            "# PROJECT.md — Project Manifest\n"
            "Ticket prefix: XXX\n"
            "\n"
            "## Stack\n"
            "- Python\n"
        )
    tpl.write_text(content, encoding="utf-8")
    return tpl


TEMPLATE_WITH_PREFIX = (
    "# PROJECT.md — Project Manifest\nTicket prefix: XXX\n\n## Stack\n- Python\n"
)


def test_copy_project_template_creates_file(tmp_path):
    """Template is copied to destination as PROJECT.md when not present."""
    _write_template(tmp_path, TEMPLATE_WITH_PREFIX)
    dest = tmp_path / "dest"
    dest.mkdir()

    result = copy_project_template(
        template_root=tmp_path, destination_root=dest, prefix=None
    )

    assert result is True
    project_md = dest / "PROJECT.md"
    assert project_md.exists()
    assert "Ticket prefix: XXX" in project_md.read_text(encoding="utf-8")


def test_copy_project_template_guard_no_overwrite(tmp_path):
    """Existing PROJECT.md must NOT be overwritten (guard)."""
    _write_template(tmp_path, TEMPLATE_WITH_PREFIX)
    dest = tmp_path / "dest"
    dest.mkdir()
    project_md = dest / "PROJECT.md"
    original_content = "# My Custom Project\nTicket prefix: CUSTOM\n"
    project_md.write_text(original_content, encoding="utf-8")

    result = copy_project_template(
        template_root=tmp_path, destination_root=dest, prefix="NEW"
    )

    assert result is False
    assert project_md.read_text(encoding="utf-8") == original_content


def test_copy_project_template_prefix_substitution(tmp_path):
    """--prefix WT substitutes Ticket prefix placeholder in deposited file."""
    _write_template(tmp_path, TEMPLATE_WITH_PREFIX)
    dest = tmp_path / "dest"
    dest.mkdir()

    result = copy_project_template(
        template_root=tmp_path, destination_root=dest, prefix="MYPROJ"
    )

    assert result is True
    content = (dest / "PROJECT.md").read_text(encoding="utf-8")
    assert "Ticket prefix: MYPROJ" in content
    assert "Ticket prefix: XXX" not in content


def test_copy_project_template_dry_run_does_not_write(tmp_path):
    """Dry-run must not create PROJECT.md."""
    _write_template(tmp_path, TEMPLATE_WITH_PREFIX)
    dest = tmp_path / "dest"
    dest.mkdir()

    result = copy_project_template(
        template_root=tmp_path, destination_root=dest, prefix="WT", dry_run=True
    )

    assert result is True
    assert not (dest / "PROJECT.md").exists()


def test_copy_project_template_missing_template(tmp_path, capsys):
    """Missing template file logs a warning and returns False."""
    dest = tmp_path / "dest"
    dest.mkdir()

    result = copy_project_template(
        template_root=tmp_path, destination_root=dest, prefix="WT"
    )

    assert result is False
    out = capsys.readouterr().out
    assert "WARN" in out
    assert "PROJECT_TEMPLATE.md not found" in out


# ---------------------------------------------------------------------------
# INSTALLER_MANAGED_PATHS / detect_destination_residues
# ---------------------------------------------------------------------------


def _create_minimal_agent_dir(base: Path) -> Path:
    """Helper: create a minimal .agent/ directory with one canonical file."""
    agent = base / ".agent"
    config = agent / "config"
    config.mkdir(parents=True)
    (config / "hooks_config.json").write_text(
        '{"version": "1", "enabled": true}', encoding="utf-8"
    )
    return agent


def test_sync_twice_preserves_glossary(tmp_path):
    """glossary.md (installer-managed) must survive detect_destination_residues."""
    source_agent = _create_minimal_agent_dir(tmp_path / "source")
    dest_agent = _create_minimal_agent_dir(tmp_path / "dest")
    # Add glossary.md only in dest (simulating first install)
    (dest_agent / "glossary.md").write_text("# Glossary\n", encoding="utf-8")

    residues = detect_destination_residues(source_agent, dest_agent)
    residue_names = {r.as_posix() for r in residues}
    assert "glossary.md" not in residue_names, (
        f"glossary.md should be filtered by INSTALLER_MANAGED_PATHS, "
        f"got residues: {residue_names}"
    )


def test_sync_twice_preserves_microagents(tmp_path):
    """microagents/ directory (installer-managed) must survive detect_destination_residues."""
    source_agent = _create_minimal_agent_dir(tmp_path / "source")
    dest_agent = _create_minimal_agent_dir(tmp_path / "dest")
    # Add microagents/ only in dest (simulating first install)
    micro = dest_agent / "microagents"
    micro.mkdir(parents=True)
    (micro / "onboarding.md").write_text("# Onboarding\n", encoding="utf-8")

    residues = detect_destination_residues(source_agent, dest_agent)
    residue_names = {r.as_posix() for r in residues}
    assert "microagents" not in residue_names, (
        f"microagents should be filtered by INSTALLER_MANAGED_PATHS, "
        f"got residues: {residue_names}"
    )
    assert "microagents/onboarding.md" not in residue_names, (
        f"microagents/onboarding.md should be filtered, got residues: {residue_names}"
    )


def test_sync_preserves_user_modified_glossary(tmp_path):
    """Existing glossary with user modifications must not be touched by detect_destination_residues."""
    source_agent = _create_minimal_agent_dir(tmp_path / "source")
    dest_agent = _create_minimal_agent_dir(tmp_path / "dest")
    # Simulate user-modified glossary
    user_content = "# My Custom Glossary\nModified by user\n"
    (dest_agent / "glossary.md").write_text(user_content, encoding="utf-8")

    residues = detect_destination_residues(source_agent, dest_agent)
    assert "glossary.md" not in {r.as_posix() for r in residues}
    # The actual file content must not be changed by a sync
    assert (dest_agent / "glossary.md").read_text(encoding="utf-8") == user_content, (
        "User-modified glossary content must be preserved"
    )


def test_sync_prunes_real_unknown_residue(tmp_path):
    """A genuinely unknown file in dest (not installer-managed) IS detected as residue."""
    source_agent = _create_minimal_agent_dir(tmp_path / "source")
    dest_agent = _create_minimal_agent_dir(tmp_path / "dest")
    # Add a genuinely unknown cache file to dest
    (dest_agent / "some_random_cache.tmp").write_text("garbage", encoding="utf-8")

    residues = detect_destination_residues(source_agent, dest_agent)
    residue_names = {r.as_posix() for r in residues}
    assert "some_random_cache.tmp" in residue_names, (
        f"Unknown residue should be detected, got residues: {residue_names}"
    )


def test_sync_dry_run_reports_without_deleting(tmp_path):
    """Dry-run mode reports residues but does not delete them."""
    source_agent = _create_minimal_agent_dir(tmp_path / "source")
    dest_agent = _create_minimal_agent_dir(tmp_path / "dest")
    # Add a residue
    (dest_agent / "unknown.tmp").write_text("data", encoding="utf-8")

    from scripts.install_agent_system import prune_residues

    residues = detect_destination_residues(source_agent, dest_agent)
    assert "unknown.tmp" in {r.as_posix() for r in residues}

    # Dry-run: should report but NOT delete
    pruned = prune_residues(dest_agent, residues, dry_run=True, interactive=False)
    # The pruning report should include the file
    pruned_names = {r.as_posix() for r in pruned}
    assert "unknown.tmp" in pruned_names
    # But the file must still exist
    assert (dest_agent / "unknown.tmp").exists(), "Dry-run must not delete files"


# ---------------------------------------------------------------------------
# copy_tree — recursive allowlist
# ---------------------------------------------------------------------------


def test_copy_tree_does_not_copy_unallowlisted_child(tmp_path):
    """A child file not in the allowlist must NOT be copied even inside an allowed dir."""
    source = tmp_path / "source"
    config_dir = source / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "allowed.json").write_text("{}", encoding="utf-8")
    (config_dir / "secret.json").write_text("{}", encoding="utf-8")

    dest = tmp_path / "dest"
    dest.mkdir()

    allowlist = {".agent/config/allowed.json"}
    copied = copy_tree(source, dest, allowlist=allowlist)

    copied_names = {r.as_posix() for r in copied}
    # allowed.json should be copied
    assert "config/allowed.json" in copied_names, (
        f"allowed.json should be copied, got: {copied_names}"
    )
    # secret.json must NOT be copied (not in allowlist)
    assert "config/secret.json" not in copied_names, (
        f"secret.json should NOT be copied, got: {copied_names}"
    )
    assert not (dest / "config" / "secret.json").exists(), (
        "secret.json must not exist in destination"
    )
    # allowed.json should exist in dest
    assert (dest / "config" / "allowed.json").exists()


def test_copy_tree_copies_allowlisted_file(tmp_path):
    """An explicitly allowlisted file at root level IS copied."""
    source = tmp_path / "source"
    (source / "config").mkdir(parents=True)
    (source / "config" / "hooks_config.json").write_text(
        '{"version": "1"}', encoding="utf-8"
    )

    dest = tmp_path / "dest"
    dest.mkdir()

    allowlist = {".agent/config/hooks_config.json"}
    copied = copy_tree(source, dest, allowlist=allowlist)

    copied_names = {r.as_posix() for r in copied}
    assert "config/hooks_config.json" in copied_names
    assert (dest / "config" / "hooks_config.json").exists()


def test_copy_tree_copies_allowlisted_nested_child(tmp_path):
    """An allowlisted file nested inside subdirectories IS copied."""
    source = tmp_path / "source"
    deep = source / "a" / "b" / "c"
    deep.mkdir(parents=True)
    (deep / "deep_file.json").write_text("{}", encoding="utf-8")

    dest = tmp_path / "dest"
    dest.mkdir()

    allowlist = {".agent/a/b/c/deep_file.json"}
    copied = copy_tree(source, dest, allowlist=allowlist)

    copied_names = {r.as_posix() for r in copied}
    assert "a/b/c/deep_file.json" in copied_names, (
        f"Nested allowlisted file should be copied, got: {copied_names}"
    )
    assert (dest / "a" / "b" / "c" / "deep_file.json").exists()


# ---------------------------------------------------------------------------
# copy_destination_bootstrap
# ---------------------------------------------------------------------------


def test_copy_destination_bootstrap_creates_context_dir(tmp_path, capsys):
    """Creates .agent/context/ directory."""
    project_agent = tmp_path / ".agent"
    project_agent.mkdir(parents=True)

    copy_destination_bootstrap(project_agent, tmp_path)
    assert (project_agent / "context").exists()
    assert (project_agent / "context").is_dir()


def test_copy_destination_bootstrap_creates_config(tmp_path, capsys):
    """Creates destination_context.json with defaults."""
    project_agent = tmp_path / ".agent"
    project_agent.mkdir(parents=True)

    copy_destination_bootstrap(project_agent, tmp_path)
    config_file = project_agent / "config" / "destination_context.json"
    assert config_file.exists()
    import json

    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert data["version"] == "1"
    assert data["max_bytes"] == 204800


def test_copy_destination_bootstrap_does_not_overwrite(tmp_path, capsys):
    """Existing destination_context.json is not overwritten."""
    project_agent = tmp_path / ".agent"
    config_dir = project_agent / "config"
    config_dir.mkdir(parents=True)
    existing = {"version": "2", "max_bytes": 99999, "custom": True}
    (config_dir / "destination_context.json").write_text(
        json.dumps(existing), encoding="utf-8"
    )

    copy_destination_bootstrap(project_agent, tmp_path)
    data = json.loads(
        (config_dir / "destination_context.json").read_text(encoding="utf-8")
    )
    assert data["custom"] is True
    assert data["max_bytes"] == 99999


def test_copy_destination_bootstrap_dry_run(tmp_path, capsys):
    """Dry-run does not create files."""
    project_agent = tmp_path / ".agent"
    project_agent.mkdir(parents=True)

    copy_destination_bootstrap(project_agent, tmp_path, dry_run=True)
    assert not (project_agent / "context").exists()
    assert not (project_agent / "config" / "destination_context.json").exists()
    out = capsys.readouterr().out
    assert "DRY-RUN" in out


def test_copy_destination_bootstrap_idempotent(tmp_path, capsys):
    """Second call does not change anything."""
    project_agent = tmp_path / ".agent"
    project_agent.mkdir(parents=True)

    copy_destination_bootstrap(project_agent, tmp_path)
    config_file = project_agent / "config" / "destination_context.json"
    content_first = config_file.read_text(encoding="utf-8")

    copy_destination_bootstrap(project_agent, tmp_path)
    content_second = config_file.read_text(encoding="utf-8")
    assert content_first == content_second


# ---------------------------------------------------------------------------
# INSTALLER_BOOTSTRAP_PATHS - residue survival
# ---------------------------------------------------------------------------


def test_destination_context_json_survives_residue_detection(tmp_path):
    """config/destination_context.json must not be pruned by detect_destination_residues."""
    source_agent = _create_minimal_agent_dir(tmp_path / "source")
    dest_agent = _create_minimal_agent_dir(tmp_path / "dest")
    # Add the bootstrap file to dest (simulating first install)
    config_dir = dest_agent / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "destination_context.json").write_text(
        '{"version": "1"}', encoding="utf-8"
    )

    residues = detect_destination_residues(source_agent, dest_agent)
    residue_names = {r.as_posix() for r in residues}
    assert "config/destination_context.json" not in residue_names, (
        f"destination_context.json should be excluded by INSTALLER_BOOTSTRAP_PATHS, "
        f"got residues: {residue_names}"
    )
