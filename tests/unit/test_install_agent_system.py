"""Unit tests for install_agent_system.py.

Covers:
- parse_wing_sections: wing header parsing and legacy retrocompat
- merge_memory_rules: engine/meta updated, project preserved, idempotency
- sync_memory_rules: dry-run, missing source, file creation, no L1/L3 touch
- copy_project_template: guard (no overwrite), prefix substitution, dry-run,
  missing template
- write_motor_destination_link: ticket_prefix preservation on re-sync
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import textwrap
from pathlib import Path

import scripts.install_agent_system as ias
from scripts.install_agent_system import (
    TEMPLATE_ROOT,
    copy_destination_bootstrap,
    copy_gitleaks_config,
    copy_project_template,
    copy_tree,
    detect_destination_residues,
    ensure_destination_projections_ignored,
    get_motor_head_sha,
    install_agent_system,
    merge_memory_rules,
    parse_wing_sections,
    prune_residues,
    read_manifest_allowlist,
    sync_agent_system,
    sync_memory_rules,
    untrack_ignored_projections,
    write_motor_destination_link,
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

    residues = detect_destination_residues(source_agent, dest_agent)
    assert "unknown.tmp" in {r.as_posix() for r in residues}

    # Dry-run: should report but NOT delete
    pruned = prune_residues(dest_agent, residues, dry_run=True, interactive=False)
    # The pruning report should include the file
    pruned_names = {r.as_posix() for r in pruned}
    assert "unknown.tmp" in pruned_names
    # But the file must still exist
    assert (dest_agent / "unknown.tmp").exists(), "Dry-run must not delete files"


def test_prune_residues_skips_git_tracked_agent_docs_and_prunes_untracked(
    tmp_path, capsys
):
    """Strict prune must preserve tracked destino docs while pruning untracked residue."""
    source_root = tmp_path / "source"
    dest_root = tmp_path / "dest"
    source_agent = _create_minimal_agent_dir(source_root)
    dest_agent = _create_minimal_agent_dir(dest_root)

    subprocess.run(
        ["git", "init"],
        cwd=dest_root,
        check=True,
        capture_output=True,
        text=True,
    )

    docs_dir = dest_agent / "docs"
    docs_dir.mkdir(parents=True)
    tracked_doc = docs_dir / "resource_precedence.md"
    tracked_doc.write_text("# tracked deliverable\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", ".agent/docs/resource_precedence.md"],
        cwd=dest_root,
        check=True,
        capture_output=True,
        text=True,
    )

    untracked_dir = dest_agent / "tmp_cache"
    untracked_dir.mkdir()
    (untracked_dir / "garbage.txt").write_text("junk\n", encoding="utf-8")

    residues = detect_destination_residues(source_agent, dest_agent)
    residue_names = {r.as_posix() for r in residues}
    assert "docs" in residue_names
    assert "tmp_cache" in residue_names

    pruned = prune_residues(dest_agent, residues, dry_run=False, interactive=False)
    pruned_names = {r.as_posix() for r in pruned}

    assert "docs" not in pruned_names
    assert "tmp_cache" in pruned_names
    assert docs_dir.exists()
    assert tracked_doc.exists()
    assert not untracked_dir.exists()

    out = capsys.readouterr().out
    assert "[SKIP] residue is git-tracked" in out
    assert ".agent/docs" in out


def test_prune_residues_fails_safe_when_git_tracked_status_unknown(
    tmp_path, monkeypatch, capsys
):
    """If tracked status cannot be determined, prune must abort safely."""
    source_agent = _create_minimal_agent_dir(tmp_path / "source")
    dest_agent = _create_minimal_agent_dir(tmp_path / "dest")
    residue = dest_agent / "unknown.tmp"
    residue.write_text("data", encoding="utf-8")

    residues = detect_destination_residues(source_agent, dest_agent)
    assert "unknown.tmp" in {r.as_posix() for r in residues}

    monkeypatch.setattr(
        "scripts.install_agent_system._git_tracked_relpaths", lambda _: None
    )

    pruned = prune_residues(dest_agent, residues, dry_run=False, interactive=False)

    assert pruned == []
    assert residue.exists()
    out = capsys.readouterr().out
    assert "cannot determine git-tracked status" in out


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

    copy_destination_bootstrap(project_agent)
    assert (project_agent / "context").exists()
    assert (project_agent / "context").is_dir()


def test_copy_destination_bootstrap_creates_config(tmp_path, capsys):
    """Creates destination_context.json with defaults."""
    project_agent = tmp_path / ".agent"
    project_agent.mkdir(parents=True)

    copy_destination_bootstrap(project_agent)
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

    copy_destination_bootstrap(project_agent)
    data = json.loads(
        (config_dir / "destination_context.json").read_text(encoding="utf-8")
    )
    assert data["custom"] is True
    assert data["max_bytes"] == 99999


def test_copy_destination_bootstrap_dry_run(tmp_path, capsys):
    """Dry-run does not create files."""
    project_agent = tmp_path / ".agent"
    project_agent.mkdir(parents=True)

    copy_destination_bootstrap(project_agent, dry_run=True)
    assert not (project_agent / "context").exists()
    assert not (project_agent / "config" / "destination_context.json").exists()
    out = capsys.readouterr().out
    assert "DRY-RUN" in out


def test_copy_destination_bootstrap_idempotent(tmp_path, capsys):
    """Second call does not change anything."""
    project_agent = tmp_path / ".agent"
    project_agent.mkdir(parents=True)

    copy_destination_bootstrap(project_agent)
    config_file = project_agent / "config" / "destination_context.json"
    content_first = config_file.read_text(encoding="utf-8")

    copy_destination_bootstrap(project_agent)
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


# ---------------------------------------------------------------------------
# copy_gitleaks_config (WOT-2026-004b): portable seed, no-clobber
# ---------------------------------------------------------------------------


def _make_gitleaks_template(
    template_root: Path, body: str = "title = 'seed'\n"
) -> Path:
    src = template_root / "agent_system" / "templates" / "gitleaks.config.toml"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(body, encoding="utf-8")
    return src


def test_copy_gitleaks_config_creates_when_absent(tmp_path):
    template_root = tmp_path / "motor"
    dest_root = tmp_path / "dest"
    dest_root.mkdir()
    _make_gitleaks_template(template_root, "title = 'seed'\n")

    result = copy_gitleaks_config(template_root, dest_root, dry_run=False)

    dest = dest_root / ".gitleaks.toml"
    assert result is True
    assert dest.exists()
    assert dest.read_text(encoding="utf-8") == "title = 'seed'\n"


def test_copy_gitleaks_config_no_clobber_when_present(tmp_path):
    template_root = tmp_path / "motor"
    dest_root = tmp_path / "dest"
    dest_root.mkdir()
    _make_gitleaks_template(template_root, "title = 'seed'\n")

    custom = dest_root / ".gitleaks.toml"
    custom.write_text("title = 'destino custom'\n", encoding="utf-8")

    result = copy_gitleaks_config(template_root, dest_root, dry_run=False)

    # No-clobber: existing destino config preserved verbatim.
    assert result is True
    assert custom.read_text(encoding="utf-8") == "title = 'destino custom'\n"


def test_copy_gitleaks_config_missing_template_returns_false(tmp_path):
    template_root = tmp_path / "motor"
    (template_root / "agent_system" / "templates").mkdir(parents=True)
    dest_root = tmp_path / "dest"
    dest_root.mkdir()

    result = copy_gitleaks_config(template_root, dest_root, dry_run=False)

    assert result is False
    assert not (dest_root / ".gitleaks.toml").exists()


def test_copy_gitleaks_config_dry_run_does_not_write(tmp_path):
    template_root = tmp_path / "motor"
    dest_root = tmp_path / "dest"
    dest_root.mkdir()
    _make_gitleaks_template(template_root)

    result = copy_gitleaks_config(template_root, dest_root, dry_run=True)

    assert result is True
    assert not (dest_root / ".gitleaks.toml").exists()


# ---------------------------------------------------------------------------
# copy_gitleaks_config divergence WARN (WOT-2026-039k): the no-clobber opened a
# cascade gap -- seed additions never reached an already-provisioned destino.
# The installer now DETECTS and NAMES the absent seed sections without merging.
# ---------------------------------------------------------------------------

_SEED_TWO_BLOCKS = """\
title = "seed"
[extend]
useDefault = true

[[allowlists]]
description = "structural log paths"
paths = [
  '''(^|/)execution_log\\.md$''',
]

[[allowlists]]
description = "027n privacy_preflight fixtures"
regexes = [
  '''sk-live-abc12345''',
  '''A1b2C3d4E5f6G7h8''',
]
"""

_DEST_MISSING_027N = """\
title = "destino custom"
[extend]
useDefault = true

[[allowlists]]
description = "structural log paths"
paths = [
  '''(^|/)execution_log\\.md$''',
]
"""


def test_copy_gitleaks_config_warns_and_names_missing_section(tmp_path, capsys):
    """A pre-existing destino config missing a seed section gets a NAMED WARN,
    and the no-clobber keeps the destino file verbatim (no merge)."""
    template_root = tmp_path / "motor"
    _make_gitleaks_template(template_root, _SEED_TWO_BLOCKS)
    dest_root = tmp_path / "dest"
    dest_root.mkdir()
    config = dest_root / ".gitleaks.toml"
    config.write_text(_DEST_MISSING_027N, encoding="utf-8")
    before = config.read_text(encoding="utf-8")

    result = copy_gitleaks_config(template_root, dest_root, dry_run=False)

    out = capsys.readouterr().out
    assert result is True
    assert "[WARN]" in out
    assert "027n privacy_preflight fixtures" in out
    # The local section is preserved: the destino file is untouched.
    assert config.read_text(encoding="utf-8") == before


def test_copy_gitleaks_config_silent_when_destino_carries_all_sections(
    tmp_path, capsys
):
    """A destino that already carries every seed section (plus its own local
    block) produces NO warning: the local section never triggers a false hit."""
    template_root = tmp_path / "motor"
    _make_gitleaks_template(template_root, _SEED_TWO_BLOCKS)
    dest_root = tmp_path / "dest"
    dest_root.mkdir()
    (dest_root / ".gitleaks.toml").write_text(
        _SEED_TWO_BLOCKS + "\n[[allowlists]]\n"
        'description = "LOCAL destino block"\n'
        "regexes = [\n  '''sk_live_1234567890''',\n]\n",
        encoding="utf-8",
    )

    copy_gitleaks_config(template_root, dest_root, dry_run=False)

    out = capsys.readouterr().out
    assert "[WARN]" not in out


# ---------------------------------------------------------------------------
# propagate_claude_guard_hook (WOT-2026-071d): propagate the guard_paths
# write guard into a destino's tracked .claude/settings.json via a
# STRUCTURAL merge (never a clobber), atomic write, idempotent on re-sync.
# ---------------------------------------------------------------------------


def _canonical_command() -> str:
    import sys as _sys
    from pathlib import Path as _Path

    agent_hooks_dir = str(
        _Path(ias.__file__).resolve().parent.parent / ".agent" / "hooks"
    )
    if agent_hooks_dir not in _sys.path:
        _sys.path.insert(0, agent_hooks_dir)
    import claude_guard_entry

    return claude_guard_entry.canonical_hook_command()


def test_propagate_claude_guard_hook_creates_when_absent(tmp_path):
    dest_root = tmp_path / "dest"
    dest_root.mkdir()

    result = ias.propagate_claude_guard_hook(dest_root, dry_run=False)

    settings_path = dest_root / ".claude" / "settings.json"
    assert result is True
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    gating = settings["hooks"]["PreToolUse"]
    assert len(gating) == 1
    assert gating[0]["matcher"] == "Write|Edit|MultiEdit"
    assert gating[0]["hooks"][0]["command"] == _canonical_command()


def test_propagate_claude_guard_hook_preserves_unrelated_hooks(tmp_path):
    """MERGE, not clobber: unrelated hooks/keys in an existing settings.json
    survive the propagation untouched."""
    dest_root = tmp_path / "dest"
    claude_dir = dest_root / ".claude"
    claude_dir.mkdir(parents=True)
    existing = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "SomeOtherTool",
                    "hooks": [{"type": "command", "command": "echo hi"}],
                }
            ],
            "Stop": [
                {"matcher": "", "hooks": [{"type": "command", "command": "echo bye"}]}
            ],
        },
        "permissions": {"allow": ["Bash(ls)"]},
    }
    (claude_dir / "settings.json").write_text(json.dumps(existing, indent=2))

    ias.propagate_claude_guard_hook(dest_root, dry_run=False)

    settings = json.loads((claude_dir / "settings.json").read_text(encoding="utf-8"))
    assert settings["hooks"]["Stop"] == existing["hooks"]["Stop"]
    assert settings["permissions"] == existing["permissions"]
    pretooluse = settings["hooks"]["PreToolUse"]
    assert len(pretooluse) == 2
    assert any(e["matcher"] == "SomeOtherTool" for e in pretooluse)
    gating = [e for e in pretooluse if e["matcher"] == "Write|Edit|MultiEdit"]
    assert len(gating) == 1
    assert gating[0]["hooks"][0]["command"] == _canonical_command()


def test_propagate_claude_guard_hook_replaces_stale_command(tmp_path):
    """MUTATION target: a destino whose guard command drifted from canonical
    (e.g. an old bootstrap literal, or hand-edited) must be corrected, not
    left stale."""
    dest_root = tmp_path / "dest"
    claude_dir = dest_root / ".claude"
    claude_dir.mkdir(parents=True)
    stale = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Write|Edit|MultiEdit",
                    "hooks": [{"type": "command", "command": "echo STALE_COMMAND"}],
                }
            ]
        }
    }
    (claude_dir / "settings.json").write_text(json.dumps(stale, indent=2))

    ias.propagate_claude_guard_hook(dest_root, dry_run=False)

    settings = json.loads((claude_dir / "settings.json").read_text(encoding="utf-8"))
    gating = settings["hooks"]["PreToolUse"]
    assert len(gating) == 1
    assert gating[0]["hooks"][0]["command"] == _canonical_command()
    assert gating[0]["hooks"][0]["command"] != "echo STALE_COMMAND"


def test_propagate_claude_guard_hook_idempotent_on_resync(tmp_path):
    """Re-running on an already-wired destino is a byte-identical no-op."""
    dest_root = tmp_path / "dest"
    dest_root.mkdir()
    ias.propagate_claude_guard_hook(dest_root, dry_run=False)
    settings_path = dest_root / ".claude" / "settings.json"
    before = settings_path.read_text(encoding="utf-8")

    result = ias.propagate_claude_guard_hook(dest_root, dry_run=False)

    after = settings_path.read_text(encoding="utf-8")
    assert result is True
    assert after == before


def test_propagate_claude_guard_hook_dry_run_does_not_write(tmp_path):
    dest_root = tmp_path / "dest"
    dest_root.mkdir()

    result = ias.propagate_claude_guard_hook(dest_root, dry_run=True)

    assert result is True
    assert not (dest_root / ".claude" / "settings.json").exists()


def test_propagate_claude_guard_hook_rejects_invalid_json(tmp_path):
    """Fail-safe: never overwrite a settings.json it cannot parse."""
    dest_root = tmp_path / "dest"
    claude_dir = dest_root / ".claude"
    claude_dir.mkdir(parents=True)
    settings_path = claude_dir / "settings.json"
    settings_path.write_text("{not valid json", encoding="utf-8")

    result = ias.propagate_claude_guard_hook(dest_root, dry_run=False)

    assert result is False
    assert settings_path.read_text(encoding="utf-8") == "{not valid json"


def test_propagate_claude_guard_hook_fixes_all_duplicate_gating_entries(tmp_path):
    """A malformed settings.json with TWO gating entries, neither canonical,
    gets BOTH fixed -- never leaves a stale duplicate beside the correct one."""
    dest_root = tmp_path / "dest"
    claude_dir = dest_root / ".claude"
    claude_dir.mkdir(parents=True)
    malformed = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Write|Edit|MultiEdit",
                    "hooks": [{"type": "command", "command": "echo FIRST_STALE"}],
                },
                {
                    "matcher": "Write|Edit|MultiEdit",
                    "hooks": [{"type": "command", "command": "echo SECOND_STALE"}],
                },
            ]
        }
    }
    (claude_dir / "settings.json").write_text(json.dumps(malformed, indent=2))

    ias.propagate_claude_guard_hook(dest_root, dry_run=False)

    settings = json.loads((claude_dir / "settings.json").read_text(encoding="utf-8"))
    gating = settings["hooks"]["PreToolUse"]
    assert len(gating) == 2
    for entry in gating:
        assert entry["hooks"][0]["command"] == _canonical_command()


# ---------------------------------------------------------------------------
# propagate_session_start_hook (Fase 0, M4/M5 integration 2026-10-15):
# sibling of propagate_claude_guard_hook -- same structural-merge, atomic,
# idempotent contract, for the SessionStart hook instead of PreToolUse.
# ---------------------------------------------------------------------------


def _canonical_session_start_command() -> str:
    import sys as _sys
    from pathlib import Path as _Path

    agent_hooks_dir = str(
        _Path(ias.__file__).resolve().parent.parent / ".agent" / "hooks"
    )
    if agent_hooks_dir not in _sys.path:
        _sys.path.insert(0, agent_hooks_dir)
    import claude_guard_entry

    return claude_guard_entry.canonical_session_start_command()


def test_propagate_session_start_hook_creates_when_absent(tmp_path):
    dest_root = tmp_path / "dest"
    dest_root.mkdir()

    result = ias.propagate_session_start_hook(dest_root, dry_run=False)

    settings_path = dest_root / ".claude" / "settings.json"
    assert result is True
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    session_start = settings["hooks"]["SessionStart"]
    assert len(session_start) == 1
    assert session_start[0]["matcher"] == ""
    assert session_start[0]["hooks"][0]["command"] == _canonical_session_start_command()


def test_propagate_session_start_hook_preserves_unrelated_hooks(tmp_path):
    """MERGE, not clobber: unrelated hooks/keys in an existing settings.json
    survive the propagation untouched -- including the PreToolUse write
    guard, so re-running install doesn't silently drop it."""
    dest_root = tmp_path / "dest"
    claude_dir = dest_root / ".claude"
    claude_dir.mkdir(parents=True)
    existing = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Write|Edit|MultiEdit",
                    "hooks": [{"type": "command", "command": "echo guard"}],
                }
            ],
            "Stop": [
                {"matcher": "", "hooks": [{"type": "command", "command": "echo bye"}]}
            ],
        },
        "permissions": {"allow": ["Bash(ls)"]},
    }
    (claude_dir / "settings.json").write_text(json.dumps(existing, indent=2))

    ias.propagate_session_start_hook(dest_root, dry_run=False)

    settings = json.loads((claude_dir / "settings.json").read_text(encoding="utf-8"))
    assert settings["hooks"]["Stop"] == existing["hooks"]["Stop"]
    assert settings["hooks"]["PreToolUse"] == existing["hooks"]["PreToolUse"]
    assert settings["permissions"] == existing["permissions"]
    session_start = settings["hooks"]["SessionStart"]
    assert len(session_start) == 1
    assert session_start[0]["hooks"][0]["command"] == _canonical_session_start_command()


def test_propagate_session_start_hook_replaces_stale_command(tmp_path):
    """MUTATION target: a destino whose SessionStart command drifted from
    canonical must be corrected, not left stale."""
    dest_root = tmp_path / "dest"
    claude_dir = dest_root / ".claude"
    claude_dir.mkdir(parents=True)
    stale = {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "",
                    "hooks": [{"type": "command", "command": "echo STALE_COMMAND"}],
                }
            ]
        }
    }
    (claude_dir / "settings.json").write_text(json.dumps(stale, indent=2))

    ias.propagate_session_start_hook(dest_root, dry_run=False)

    settings = json.loads((claude_dir / "settings.json").read_text(encoding="utf-8"))
    session_start = settings["hooks"]["SessionStart"]
    assert len(session_start) == 1
    assert session_start[0]["hooks"][0]["command"] == _canonical_session_start_command()
    assert session_start[0]["hooks"][0]["command"] != "echo STALE_COMMAND"
    # The stale command must be REMOVED, not merely pushed behind the
    # canonical one -- Claude Code would otherwise still run it.
    assert len(session_start[0]["hooks"]) == 1


def test_propagate_session_start_hook_migrates_old_fail_closed_literal(tmp_path):
    """WOT-2026-058a Revisor finding (codex, P1): a destino installed
    BEFORE this ticket carries the OLD fail-closed generator's literal in
    its SessionStart entry. Re-sync must REPLACE it, never leave it
    sitting alongside the new fail-open command -- otherwise the stale
    rc=2 launcher still runs when the target is missing, defeating the
    whole point of this ticket.
    """
    import sys as _sys
    from pathlib import Path as _Path

    agent_hooks_dir = str(
        _Path(ias.__file__).resolve().parent.parent / ".agent" / "hooks"
    )
    if agent_hooks_dir not in _sys.path:
        _sys.path.insert(0, agent_hooks_dir)
    import claude_guard_entry

    old_fail_closed = claude_guard_entry.canonical_command_for(
        "session_start_hook.py", "agent_hooks"
    )
    dest_root = tmp_path / "dest"
    claude_dir = dest_root / ".claude"
    claude_dir.mkdir(parents=True)
    pre_ticket = {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "",
                    "hooks": [{"type": "command", "command": old_fail_closed}],
                }
            ]
        }
    }
    (claude_dir / "settings.json").write_text(json.dumps(pre_ticket, indent=2))

    ias.propagate_session_start_hook(dest_root, dry_run=False)

    settings = json.loads((claude_dir / "settings.json").read_text(encoding="utf-8"))
    session_start = settings["hooks"]["SessionStart"]
    assert len(session_start) == 1
    hooks = session_start[0]["hooks"]
    assert len(hooks) == 1, (
        "the old fail-closed literal must be REMOVED, not kept alongside "
        "the new fail-open one"
    )
    assert hooks[0]["command"] == _canonical_session_start_command()
    assert hooks[0]["command"] != old_fail_closed

    # Behavioral proof: launch the RESULTING command with the target
    # absent and confirm it degrades (rc=0), not the old rc=2.
    import shlex
    import subprocess

    code = shlex.split(hooks[0]["command"])[-1]
    result = subprocess.run(
        [_sys.executable, "-c", code],
        input=b"{}",
        cwd=str(dest_root),
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")


def test_propagate_session_start_hook_cleans_up_already_coexisting_stale(tmp_path):
    """WOT-2026-058a Revisor finding (codex, ronda 2, P1): a destino that
    was ALREADY re-synced once by the pre-fix (prepend-and-keep) logic
    carries BOTH the new canonical command and the old fail-closed one in
    the SAME entry's hooks list. The old already_wired check
    (`canonical_hook in entry.hooks`) returned True for this exact shape
    and SKIPPED cleanup forever -- a destino that hit this state once
    before the fix never self-heals on any later re-sync.
    """
    import sys as _sys
    from pathlib import Path as _Path

    agent_hooks_dir = str(
        _Path(ias.__file__).resolve().parent.parent / ".agent" / "hooks"
    )
    if agent_hooks_dir not in _sys.path:
        _sys.path.insert(0, agent_hooks_dir)
    import claude_guard_entry

    old_fail_closed = claude_guard_entry.canonical_command_for(
        "session_start_hook.py", "agent_hooks"
    )
    new_canonical = _canonical_session_start_command()
    dest_root = tmp_path / "dest"
    claude_dir = dest_root / ".claude"
    claude_dir.mkdir(parents=True)
    coexisting = {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "",
                    "hooks": [
                        {"type": "command", "command": new_canonical},
                        {"type": "command", "command": old_fail_closed},
                    ],
                }
            ]
        }
    }
    (claude_dir / "settings.json").write_text(json.dumps(coexisting, indent=2))

    ias.propagate_session_start_hook(dest_root, dry_run=False)

    settings = json.loads((claude_dir / "settings.json").read_text(encoding="utf-8"))
    session_start = settings["hooks"]["SessionStart"]
    assert len(session_start) == 1
    hooks = session_start[0]["hooks"]
    assert hooks == [{"type": "command", "command": new_canonical}], (
        "the coexisting stale literal must be purged, not left alongside "
        "the canonical command just because the canonical one is PRESENT"
    )


def test_propagate_session_start_hook_cleans_up_old_plus_new_separate_entries(
    tmp_path: Path,
):
    """Sibling of the coexisting-in-one-entry case: the new command lives
    in its OWN entry, separate from an old entry that still carries only
    the stale fail-closed command. already_wired must not short-circuit
    here either.
    """
    import sys as _sys
    from pathlib import Path as _Path

    agent_hooks_dir = str(
        _Path(ias.__file__).resolve().parent.parent / ".agent" / "hooks"
    )
    if agent_hooks_dir not in _sys.path:
        _sys.path.insert(0, agent_hooks_dir)
    import claude_guard_entry

    old_fail_closed = claude_guard_entry.canonical_command_for(
        "session_start_hook.py", "agent_hooks"
    )
    new_canonical = _canonical_session_start_command()
    dest_root = tmp_path / "dest"
    claude_dir = dest_root / ".claude"
    claude_dir.mkdir(parents=True)
    separate_entries = {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "",
                    "hooks": [{"type": "command", "command": new_canonical}],
                },
                {
                    "matcher": "",
                    "hooks": [{"type": "command", "command": old_fail_closed}],
                },
            ]
        }
    }
    (claude_dir / "settings.json").write_text(json.dumps(separate_entries, indent=2))

    ias.propagate_session_start_hook(dest_root, dry_run=False)

    settings = json.loads((claude_dir / "settings.json").read_text(encoding="utf-8"))
    session_start = settings["hooks"]["SessionStart"]
    for entry in session_start:
        assert entry["hooks"] == [{"type": "command", "command": new_canonical}], (
            "every SessionStart entry must end up canonical-only; an old "
            "sibling entry must not survive just because another entry "
            "already carries the new command"
        )


def test_propagate_session_start_hook_idempotent_on_resync(tmp_path):
    """Re-running on an already-wired destino is a byte-identical no-op."""
    dest_root = tmp_path / "dest"
    dest_root.mkdir()
    ias.propagate_session_start_hook(dest_root, dry_run=False)
    settings_path = dest_root / ".claude" / "settings.json"
    before = settings_path.read_text(encoding="utf-8")

    result = ias.propagate_session_start_hook(dest_root, dry_run=False)

    after = settings_path.read_text(encoding="utf-8")
    assert result is True
    assert after == before


def test_propagate_session_start_hook_dry_run_does_not_write(tmp_path):
    dest_root = tmp_path / "dest"
    dest_root.mkdir()

    result = ias.propagate_session_start_hook(dest_root, dry_run=True)

    assert result is True
    assert not (dest_root / ".claude" / "settings.json").exists()


def test_propagate_session_start_hook_rejects_invalid_json(tmp_path):
    """Fail-safe: never overwrite a settings.json it cannot parse."""
    dest_root = tmp_path / "dest"
    claude_dir = dest_root / ".claude"
    claude_dir.mkdir(parents=True)
    settings_path = claude_dir / "settings.json"
    settings_path.write_text("{not valid json", encoding="utf-8")

    result = ias.propagate_session_start_hook(dest_root, dry_run=False)

    assert result is False
    assert settings_path.read_text(encoding="utf-8") == "{not valid json"


def test_propagate_session_start_hook_fixes_all_duplicate_gating_entries(tmp_path):
    """A malformed settings.json with TWO SessionStart entries, neither
    canonical, gets BOTH fixed -- never leaves a stale duplicate beside the
    correct one."""
    dest_root = tmp_path / "dest"
    claude_dir = dest_root / ".claude"
    claude_dir.mkdir(parents=True)
    malformed = {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "",
                    "hooks": [{"type": "command", "command": "echo FIRST_STALE"}],
                },
                {
                    "matcher": "",
                    "hooks": [{"type": "command", "command": "echo SECOND_STALE"}],
                },
            ]
        }
    }
    (claude_dir / "settings.json").write_text(json.dumps(malformed, indent=2))

    ias.propagate_session_start_hook(dest_root, dry_run=False)

    settings = json.loads((claude_dir / "settings.json").read_text(encoding="utf-8"))
    session_start = settings["hooks"]["SessionStart"]
    assert len(session_start) == 2
    for entry in session_start:
        assert entry["hooks"][0]["command"] == _canonical_session_start_command()
        assert len(entry["hooks"]) == 1, "stale literal left alongside canonical"


# ---------------------------------------------------------------------------
# ensure_destination_projections_ignored (WOT-2026-020t)
# ---------------------------------------------------------------------------


def test_destination_projections_adds_collaboration_for_destination(tmp_path):
    """WOT-2026-059f: a real destination (motor_root != project_root) gets the
    6 explicit collaboration files gitignored (not the blanket directory --
    STRATEGY_WOT-*.md/AUDIT_WOT-*.md are canonical artefacts excluded on
    purpose) alongside the shared projection entries."""
    motor_root = tmp_path / "motor"
    motor_root.mkdir()
    dest_root = tmp_path / "dest"
    dest_root.mkdir()

    added = ensure_destination_projections_ignored(
        dest_root, dry_run=False, motor_root=motor_root
    )

    gitignore = (dest_root / ".gitignore").read_text(encoding="utf-8")
    expected_files = {
        ".agent/collaboration/work_plan.md",
        ".agent/collaboration/STATE.md",
        ".agent/collaboration/TURN.md",
        ".agent/collaboration/execution_log.md",
        ".agent/collaboration/notifications.md",
        ".agent/collaboration/review_queue.md",
    }
    assert expected_files.issubset(set(added))
    assert ".agent/collaboration/" not in added
    assert ".agent/config/motor_destination_link.json" in added
    for entry in expected_files:
        assert entry in gitignore
    assert ".agent/collaboration/\n" not in gitignore
    assert "# motor-managed: regenerable projections (WOT-2026-016p)" in gitignore


def test_destination_projections_skips_collaboration_for_motor(tmp_path):
    """The motor itself (motor_root == project_root) versions .agent/collaboration/;
    the guard is a no-op and must NOT touch its .gitignore."""
    motor_root = tmp_path / "motor"
    motor_root.mkdir()

    added = ensure_destination_projections_ignored(
        motor_root, dry_run=False, motor_root=motor_root
    )

    assert added == []
    assert not (motor_root / ".gitignore").exists()


def test_destination_projections_idempotent(tmp_path):
    """Running twice adds nothing the second time and leaves the file unchanged."""
    motor_root = tmp_path / "motor"
    motor_root.mkdir()
    dest_root = tmp_path / "dest"
    dest_root.mkdir()

    ensure_destination_projections_ignored(
        dest_root, dry_run=False, motor_root=motor_root
    )
    first = (dest_root / ".gitignore").read_text(encoding="utf-8")

    added2 = ensure_destination_projections_ignored(
        dest_root, dry_run=False, motor_root=motor_root
    )
    second = (dest_root / ".gitignore").read_text(encoding="utf-8")

    assert added2 == []
    assert first == second


def test_destination_projections_dry_run_does_not_write(tmp_path):
    """Dry-run reports the missing entries but does not create .gitignore."""
    motor_root = tmp_path / "motor"
    motor_root.mkdir()
    dest_root = tmp_path / "dest"
    dest_root.mkdir()

    added = ensure_destination_projections_ignored(
        dest_root, dry_run=True, motor_root=motor_root
    )

    assert ".agent/collaboration/work_plan.md" in added
    assert ".agent/collaboration/" not in added
    assert not (dest_root / ".gitignore").exists()


def test_destination_projections_no_motor_root_defaults_to_destination(tmp_path):
    """Without motor_root (backward-compat default) the call assumes a destination
    and gitignores collaboration."""
    dest_root = tmp_path / "dest"
    dest_root.mkdir()

    added = ensure_destination_projections_ignored(dest_root, dry_run=False)

    assert ".agent/collaboration/work_plan.md" in added
    assert ".agent/collaboration/" not in added
    text = (dest_root / ".gitignore").read_text(encoding="utf-8")
    assert ".agent/collaboration/work_plan.md" in text


def test_destination_projections_respects_existing_entries(tmp_path):
    """Entries already present (user's own or a prior managed block) are not
    duplicated; only missing ones are appended."""
    motor_root = tmp_path / "motor"
    motor_root.mkdir()
    dest_root = tmp_path / "dest"
    dest_root.mkdir()
    (dest_root / ".gitignore").write_text(
        ".agent/collaboration/work_plan.md\n.agent/runtime/\n", encoding="utf-8"
    )

    added = ensure_destination_projections_ignored(
        dest_root, dry_run=False, motor_root=motor_root
    )

    assert ".agent/collaboration/work_plan.md" not in added
    assert ".agent/runtime/" not in added
    assert ".agent/collaboration/STATE.md" in added
    assert ".agent/config/motor_destination_link.json" in added
    text = (dest_root / ".gitignore").read_text(encoding="utf-8")
    assert text.count(".agent/collaboration/work_plan.md") == 1


# ---------------------------------------------------------------------------
# write_motor_destination_link: ticket_prefix preservation (WOT-2026-023i)
# ---------------------------------------------------------------------------


def _write_link(tmp_path: Path, prefix: str | None = None, **kwargs) -> Path:
    """Run write_motor_destination_link against a scratch destination and
    return the link file path."""
    motor_root = tmp_path / "motor"
    motor_root.mkdir(exist_ok=True)
    dest_root = tmp_path / "dest"
    dest_root.mkdir(exist_ok=True)
    project_agent = dest_root / ".agent"
    project_agent.mkdir(exist_ok=True)
    write_motor_destination_link(
        project_agent=project_agent,
        motor_root=motor_root,
        destination_root=dest_root,
        motor_version="v9.17.1",
        ticket_prefix=prefix,
        **kwargs,
    )
    return project_agent / "config" / "motor_destination_link.json"


def _read_prefix(link_file: Path) -> str | None:
    return json.loads(link_file.read_text(encoding="utf-8"))["ticket_prefix"]


def test_sync_without_prefix_preserves_existing_ticket_prefix(tmp_path):
    """WOT-2026-023i: a `--sync` without `--prefix` must NOT null the prefix.

    This is the regression the ticket had to close before it could land. The
    link file is gitignored (the installer itself adds it to the destination's
    .gitignore), so the prefix lives only on disk -- and write_motor_
    destination_link used to write `"ticket_prefix": ticket_prefix`
    unconditionally, meaning any sync without the flag silently un-declared the
    destination's namespace.

    That was survivable while prefix_resolver hardcoded a special case for WOT.
    It no longer is: with WOT resolving through the links like every other
    prefix, a null-ed workspace link makes the topology guard fail to resolve
    WOT (exit 2) and block every motor ticket.

    Mutation-to-prove: drop the preservation and this goes red with None.
    """
    link = _write_link(tmp_path, prefix="WOT")
    assert _read_prefix(link) == "WOT"

    # Re-sync with no prefix (the exact shape of `install_agent_system.py --sync`
    # invoked without --prefix).
    link = _write_link(tmp_path, prefix=None)
    assert _read_prefix(link) == "WOT"


def test_explicit_prefix_overrides_existing(tmp_path):
    """Preservation must not become stickiness: an explicit prefix still wins."""
    _write_link(tmp_path, prefix="WOT")
    link = _write_link(tmp_path, prefix="CTL")
    assert _read_prefix(link) == "CTL"


def test_new_destination_without_prefix_is_null(tmp_path):
    """A brand-new destination has nothing to preserve: the prefix stays null,
    which is the pre-existing contract for `--install` without --prefix."""
    link = _write_link(tmp_path, prefix=None)
    assert _read_prefix(link) is None


def test_clear_ticket_prefix_nulls_it_explicitly(tmp_path):
    """Nulling a prefix stays possible, but only on purpose."""
    _write_link(tmp_path, prefix="WOT")
    link = _write_link(tmp_path, prefix=None, clear_ticket_prefix=True)
    assert _read_prefix(link) is None


def test_malformed_existing_link_degrades_to_none(tmp_path):
    """Preservation is best-effort: a corrupt link must not crash the install."""
    link = _write_link(tmp_path, prefix="WOT")
    link.write_text("{ not json", encoding="utf-8")
    link = _write_link(tmp_path, prefix=None)
    assert _read_prefix(link) is None


# ---------------------------------------------------------------------------
# motor_sha field written into the link (WOT-2026-024j)
# ---------------------------------------------------------------------------


def test_link_contains_motor_sha_when_provided(tmp_path):
    """The written link carries motor_sha when the caller passes one.

    Mutation-to-prove: dropping the `motor_sha` key from the payload dict
    makes this KeyError/AssertionError instead of finding "deadbeef".
    """
    link = _write_link(tmp_path, prefix="WOT", motor_sha="deadbeef")
    data = json.loads(link.read_text(encoding="utf-8"))
    assert data["motor_sha"] == "deadbeef"


def test_link_motor_sha_defaults_to_unknown(tmp_path):
    """Without a motor_sha, the link degrades to 'unknown' (mirrors
    motor_version's existing 'unknown' fallback) instead of a missing key
    or None -- destination_context's drift guard relies on this sentinel."""
    link = _write_link(tmp_path, prefix="WOT")
    data = json.loads(link.read_text(encoding="utf-8"))
    assert data["motor_sha"] == "unknown"


def test_get_motor_head_sha_real_git_repo(tmp_path):
    """get_motor_head_sha resolves a real repo's HEAD sha (40 hex chars)."""
    motor_root = tmp_path / "motor"
    motor_root.mkdir()
    subprocess.run(["git", "init"], cwd=motor_root, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=motor_root,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=motor_root,
        capture_output=True,
        check=True,
    )
    (motor_root / "f.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=motor_root, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=motor_root, capture_output=True, check=True
    )

    sha = get_motor_head_sha(motor_root)
    assert sha is not None
    assert len(sha) == 40
    assert all(c in "0123456789abcdef" for c in sha)


def test_get_motor_head_sha_non_git_dir_degrades_to_none(tmp_path):
    """A plain non-git directory must NOT crash -- degrades to None (best
    effort metadata, never a gate)."""
    plain_dir = tmp_path / "not_a_repo"
    plain_dir.mkdir()
    assert get_motor_head_sha(plain_dir) is None


# ---------------------------------------------------------------------------
# WOT-2026-024d: .agent/planning/ is destination-owned
#
# The motor ships ONE seed file (planning/ticket_contracts.md); the destination's
# Contract Formation Pipeline then produces its own artifacts there. --sync
# threatened that content through TWO independent vectors, and a fix for only one
# of them is a false-green:
#   vector 1 (overwrite): copy_tree -> _copy_allowlisted_dir -> unconditional copy2
#   vector 2 (prune):     everything the motor does NOT ship looks like a residue
# Measured 2026-07-15: 9 destinations hold their own ticket_contracts.md (0 equal to
# the seed) and Upscaler gitignores .agent/, so the WOT-2026-003d git-tracked
# fail-safe leaves its 4 other CF artifacts unprotected.
# ---------------------------------------------------------------------------

# The Contract Formation set a destination owns. ticket_contracts.md is the only
# one the motor also ships: the other four exercise the prune vector specifically.
_CF_ARTIFACTS = (
    "ticket_contracts.md",
    "repo_charter.md",
    "plan_graph.md",
    "decisions.md",
    "evidence_catalog.md",
)

_MOTOR_SEED = "SEED FROM MOTOR: dogfooding contracts\n"


def _build_motor_template(tmp_path: Path) -> Path:
    """Motor template shipping ONLY the planning seed, like the real one."""
    template_root = tmp_path / "template"
    template_agent = template_root / ".agent"
    (template_agent / "planning").mkdir(parents=True)
    (template_agent / "planning" / "ticket_contracts.md").write_text(
        _MOTOR_SEED, encoding="utf-8"
    )
    (template_root / "MANIFEST.workspace").write_text(
        ".agent/planning/\n", encoding="utf-8"
    )
    return template_agent


def _build_destination_with_own_cf(tmp_path: Path) -> Path:
    """Destination whose planning/ holds its OWN Contract Formation artifacts.

    Ships a valid hooks_config.json so ensure_hooks_config_integrity passes and a
    full sync can reach rc == 0: otherwise the sync ABORTS mid-way and an
    end-to-end test would silently measure a truncated run (sister-audit nit).
    """
    project_agent = tmp_path / "dest" / ".agent"
    planning = project_agent / "planning"
    planning.mkdir(parents=True)
    for name in _CF_ARTIFACTS:
        (planning / name).write_text(f"DESTINATION-OWNED: {name}\n", encoding="utf-8")
    config = project_agent / "config"
    config.mkdir(parents=True)
    (config / "hooks_config.json").write_text(
        json.dumps({"version": "1", "enabled": True}), encoding="utf-8"
    )
    return project_agent


def test_copy_tree_deposits_planning_when_absent(tmp_path):
    """DoD (a): a fresh install must still receive the seed.

    Mutation-2 target: putting 'planning' in LOCAL_DIRS makes this FAIL, because
    LOCAL_DIRS means 'never copied at all' and would starve a fresh install.
    """
    template_agent = _build_motor_template(tmp_path)
    project_agent = tmp_path / "dest" / ".agent"
    project_agent.mkdir(parents=True)

    copy_tree(
        template_agent,
        project_agent,
        allowlist={".agent/planning/"},
    )

    seeded = project_agent / "planning" / "ticket_contracts.md"
    assert seeded.exists(), "a fresh install must receive the Contract Formation seed"
    assert seeded.read_text(encoding="utf-8") == _MOTOR_SEED


def test_copy_tree_does_not_clobber_destination_planning(tmp_path):
    """DoD (b), vector 1: --sync must not overwrite the destination's contracts.

    Fails today without the no-clobber guard (measured: copy2 is unconditional).
    Mutation-1 target.
    """
    template_agent = _build_motor_template(tmp_path)
    project_agent = _build_destination_with_own_cf(tmp_path)
    owned = project_agent / "planning" / "ticket_contracts.md"
    before = hashlib.sha256(owned.read_bytes()).hexdigest()

    copy_tree(
        template_agent,
        project_agent,
        allowlist={".agent/planning/"},
    )

    after = hashlib.sha256(owned.read_bytes()).hexdigest()
    assert after == before, "sync clobbered the destination's own ticket_contracts.md"
    assert _MOTOR_SEED not in owned.read_text(encoding="utf-8")


def test_copy_tree_dry_run_per_file_respects_no_clobber(tmp_path):
    """Post-WOT-2026-025g: per-file dry-run still respects the no-clobber guard.

    History: an earlier version of copy_tree returned at its is_dir() branch
    before reaching _copy_allowlisted_dir, so a dry-run NEVER yielded per-file
    entries (directory-level granularity only, follow-up WOT-2026-025g). That
    coarser contract was pinned here and caught a vacuous assertion in the
    process (sister audit WOT-2026-024d): "dry-run does not list the
    destination-owned file as copied" passed trivially because dry-run never
    listed ANY file.

    WOT-2026-025g moved the dry_run branch to descend into
    _copy_allowlisted_dir, so dry-run now reports PER-FILE paths. This test
    pins the property that matters after that change: for a destination that
    already owns a file inside an allowlisted directory, dry-run's per-file
    list must still EXCLUDE that file (no-clobber applies before granularity)
    AND must not touch the destination's content.
    """
    template_agent = _build_motor_template(tmp_path)
    project_agent = _build_destination_with_own_cf(tmp_path)

    copied = copy_tree(
        template_agent,
        project_agent,
        dry_run=True,
        allowlist={".agent/planning/"},
    )

    # The destination-owned file must not appear in the per-file dry-run list.
    assert copied == []
    # And the DECISIVE property: a dry-run must not touch the destination at all.
    owned = project_agent / "planning" / "ticket_contracts.md"
    assert (
        owned.read_text(encoding="utf-8") == "DESTINATION-OWNED: ticket_contracts.md\n"
    )


def test_copy_tree_dry_run_reports_per_file_granularity(tmp_path):
    """WOT-2026-025g: dry-run must report per-file granularity for allowlisted dirs.

    Before fix: dry-run returns [Path("subdir")] for a directory, even if it
    contains allowlisted files.
    After fix: dry-run returns [Path("subdir/allowed.txt")] for allowlisted
    files, and excludes non-allowlisted siblings within the same directory.
    """
    source = tmp_path / "source"
    subdir = source / "subdir"
    subdir.mkdir(parents=True)
    (subdir / "allowed.txt").write_text("hello", encoding="utf-8")
    (subdir / "secret.txt").write_text("secret", encoding="utf-8")

    dest = tmp_path / "dest"
    dest.mkdir()
    dest_subdir = dest / "subdir"
    dest_subdir.mkdir()
    (dest_subdir / "allowed.txt").write_text("old content", encoding="utf-8")

    allowlist = {"subdir/allowed.txt"}

    copied = copy_tree(source, dest, dry_run=True, allowlist=allowlist)

    assert Path("subdir/allowed.txt") in copied
    assert Path("subdir/secret.txt") not in copied
    # Per-file granularity: the directory itself must not appear as an entry.
    assert Path("subdir") not in copied


def test_detect_destination_residues_excludes_destination_owned(tmp_path):
    """Vector 2 in isolation: destination-owned artifacts are not residues.

    Mutation-3 target: dropping the DESTINATION_OWNED_DIRS filter makes the four
    artifacts the motor does not ship reappear as residues (and prune deletes them).
    """
    template_agent = _build_motor_template(tmp_path)
    project_agent = _build_destination_with_own_cf(tmp_path)

    residues = detect_destination_residues(template_agent, project_agent)

    # Assert on the planning surface specifically. Other entries the motor does
    # not ship (e.g. the destination's config/) ARE legitimate residues, so a
    # blanket `== []` would fail for reasons unrelated to what this protects.
    planning_residues = [r for r in residues if r.parts and r.parts[0] == "planning"]
    assert planning_residues == [], (
        f"destination-owned CF artifacts flagged as residues: {planning_residues}"
    )


def test_sync_preserves_destination_contract_formation_end_to_end(tmp_path):
    """DoD (e): the WHOLE sync (copy + prune) must not destroy the destination's CF.

    This asserts at the level where the damage happens. The copy_tree-level tests
    above can all pass while sync_agent_system still deletes four files, because
    the second vector lives in prune_residues, not in copy_tree.

    The sandbox reproduces the Upscaler condition: dest has no .git, so
    _filter_git_tracked_residues finds nothing tracked and the WOT-2026-003d
    fail-safe does NOT protect these files.

    Asserts rc == 0 on purpose: a sync that ABORTS half-way would still leave the
    files intact and turn this into a false green (sister-audit nit).
    """
    template_agent = _build_motor_template(tmp_path)
    project_agent = _build_destination_with_own_cf(tmp_path)
    planning = project_agent / "planning"
    before = {
        name: hashlib.sha256((planning / name).read_bytes()).hexdigest()
        for name in _CF_ARTIFACTS
    }

    rc = sync_agent_system(template_agent, project_agent)

    assert rc == 0, (
        f"the sync aborted (rc={rc}); this test would measure a truncated run"
    )
    for name in _CF_ARTIFACTS:
        target = planning / name
        assert target.exists(), f"sync DELETED the destination's {name}"
        after = hashlib.sha256(target.read_bytes()).hexdigest()
        assert after == before[name], f"sync MODIFIED the destination's {name}"


def test_manifest_workspace_really_allowlists_planning():
    """Contract guard: if planning ever leaves MANIFEST.workspace, the tests above
    would keep passing VACUOUSLY (nothing to copy => nothing to clobber). This test
    pins the premise they depend on, against the real manifest.
    """
    allowlist = read_manifest_allowlist(TEMPLATE_ROOT)

    assert allowlist, "MANIFEST.workspace not found or empty"
    assert ".agent/planning/" in allowlist


# ---------------------------------------------------------------------------
# WOT-2026-020t: --untrack-existing (OPT-IN ONLY) + hard anti-fail-open barrier
# ---------------------------------------------------------------------------


def _untrack_git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )
    return proc.stdout


def _build_git_destination(tmp_path: Path) -> Path:
    """Destination repo (own git init, vector WOT-2026-020r) that TRACKS the
    managed projections: link file + collaboration/ + a runtime file, plus one
    unrelated tracked file that must never be touched."""
    root = tmp_path / "dest"
    config = root / ".agent" / "config"
    config.mkdir(parents=True)
    (config / "motor_destination_link.json").write_text("{}\n", encoding="utf-8")
    (config / "hooks_config.json").write_text(
        json.dumps({"version": "1", "enabled": True}), encoding="utf-8"
    )
    collab = root / ".agent" / "collaboration"
    collab.mkdir(parents=True)
    (collab / "execution_log.md").write_text("C:/Users/x local\n", encoding="utf-8")
    runtime = root / ".agent" / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "state.json").write_text("{}\n", encoding="utf-8")
    (root / "README.md").write_text("keep me tracked\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(root), "init", "-q", "-b", "main"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "add", "-A"], check=True, capture_output=True
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "-m",
            "fixture",
        ],
        check=True,
        capture_output=True,
    )
    return root


def test_untrack_removes_index_only_and_is_idempotent(tmp_path):
    """DoD (e): index cleared for managed entries, worktree intact, unrelated
    tracked files untouched, second run is a no-op."""
    root = _build_git_destination(tmp_path)
    motor = tmp_path / "motor"
    motor.mkdir()

    untracked = untrack_ignored_projections(root, motor_root=motor)

    assert untracked, "expected tracked managed projections to be untracked"
    assert _untrack_git(root, "ls-files", "--", ".agent/collaboration/") == ""
    assert (
        _untrack_git(
            root, "ls-files", "--", ".agent/config/motor_destination_link.json"
        )
        == ""
    )
    assert _untrack_git(root, "ls-files", "--", ".agent/runtime/") == ""
    # Worktree intact + unrelated file still tracked + nothing committed.
    assert (root / ".agent" / "collaboration" / "execution_log.md").exists()
    assert (root / ".agent" / "config" / "motor_destination_link.json").exists()
    assert "README.md" in _untrack_git(root, "ls-files")
    assert _untrack_git(root, "diff", "--cached", "--name-only") != ""
    # Idempotent: second run finds nothing tracked.
    assert untrack_ignored_projections(root, motor_root=motor) == []


def test_untrack_dry_run_does_not_mutate_index(tmp_path):
    root = _build_git_destination(tmp_path)
    motor = tmp_path / "motor"
    motor.mkdir()
    before = _untrack_git(root, "ls-files")

    would = untrack_ignored_projections(root, dry_run=True, motor_root=motor)

    assert would, "dry-run must report what it would untrack"
    assert _untrack_git(root, "ls-files") == before


def test_untrack_motor_identity_is_noop(tmp_path):
    """DoD (f): the motor itself (dogfooding) is never untracked."""
    root = _build_git_destination(tmp_path)

    assert untrack_ignored_projections(root, motor_root=root) == []
    assert _untrack_git(root, "ls-files", "--", ".agent/collaboration/") != ""


def test_untrack_without_own_git_is_noop(tmp_path):
    """Vector WOT-2026-020r: without its own .git, git would walk up; no-op."""
    root = tmp_path / "dest_nogit"
    (root / ".agent" / "collaboration").mkdir(parents=True)

    assert untrack_ignored_projections(root, motor_root=tmp_path / "motor") == []


def test_sync_without_flag_never_untracks(tmp_path):
    """DoD (d), mutation-2 of the ticket (HARD BARRIER): a sync WITHOUT
    --untrack-existing must leave the tracked set byte-identical. If this test
    ever fails, the barrier went fail-open and a routine --sync would de-track
    published repos through the back door."""
    template_agent = _build_motor_template(tmp_path)
    root = _build_git_destination(tmp_path)
    project_agent = root / ".agent"
    before = _untrack_git(root, "ls-files")

    rc = sync_agent_system(template_agent, project_agent)

    assert rc == 0, f"sync aborted (rc={rc}); this would measure a truncated run"
    assert _untrack_git(root, "ls-files") == before, (
        "FAIL-OPEN: sync without --untrack-existing changed the tracked set"
    )


def test_sync_with_flag_untracks(tmp_path):
    """Positive control pairing the mutation-2 test: without it, a sync that
    silently IGNORED untrack_existing would pass the barrier test vacuously."""
    template_agent = _build_motor_template(tmp_path)
    root = _build_git_destination(tmp_path)
    project_agent = root / ".agent"

    rc = sync_agent_system(template_agent, project_agent, untrack_existing=True)

    assert rc == 0
    assert _untrack_git(root, "ls-files", "--", ".agent/collaboration/") == ""
    assert (root / ".agent" / "collaboration" / "execution_log.md").exists()


def test_install_calls_untrack_only_with_flag(tmp_path, monkeypatch):
    """DoD (d), install path: the untrack call happens IFF the flag was passed.
    (A fresh install has nothing tracked, so the observable contract here is
    the call gate itself, patched at the real call-site name.)"""
    calls: list[Path] = []
    monkeypatch.setattr(
        ias, "untrack_ignored_projections", lambda root, **kw: calls.append(root)
    )
    template_agent = _build_motor_template(tmp_path)

    install_agent_system(template_agent, tmp_path / "d1" / ".agent")
    assert calls == [], "install WITHOUT the flag must never invoke untrack"

    install_agent_system(
        template_agent, tmp_path / "d2" / ".agent", untrack_existing=True
    )
    assert calls == [tmp_path / "d2"], "install WITH the flag must invoke untrack"


# ---------------------------------------------------------------------------
# WOT-2026-024h: the motor stops versioning .agent/planning/ticket_contracts.md
#
# DEC-024H-001 chose option (c): no seed, no neutral placeholder, no change to
# validate_contract_formation. The motor shipped 49881 B with 3 REAL dogfooding
# contracts (021k/023r/023s) that landed in EVERY fresh destination (measured
# 2026-07-21 by a real --install into a clean tmp dir: 3 '## WOT-' headers).
#
# Scope note: .agent/planning/ STAYS in MANIFEST.workspace on purpose. It is what
# keeps the DESTINATION's own Contract Formation artifacts safe from the --sync
# prune (WOT-2026-024d). Probed: with no seed file present, copy_tree deposits
# nothing at all -- not even an empty planning/ dir -- so removing the file is
# sufficient and removing the manifest entry would REGRESS 024d.
# ---------------------------------------------------------------------------


def test_motor_ships_no_ticket_contracts_seed():
    """C1': the seed file must not exist in the motor's distributable surface.

    Nace ROJO: the file exists and is git-tracked at HEAD ecd496c.
    """
    seed = TEMPLATE_ROOT / ".agent" / "planning" / "ticket_contracts.md"

    assert not seed.exists(), (
        "the motor must not ship .agent/planning/ticket_contracts.md "
        "(DEC-024H-001 option (c)); it travels to every fresh destination"
    )


def test_fresh_install_deposits_no_real_wot_contracts(tmp_path):
    """C3': a fresh install must not deposit REAL WOT contracts.

    Asserts on the OUTCOME at the destination (where the damage lands), not on
    the absence of a file: this stays meaningful even if the seed returns under
    another name.
    """
    project_agent = tmp_path / "dest" / ".agent"
    project_agent.mkdir(parents=True)

    copy_tree(
        TEMPLATE_ROOT / ".agent",
        project_agent,
        allowlist=read_manifest_allowlist(TEMPLATE_ROOT),
    )

    contracts = project_agent / "planning" / "ticket_contracts.md"
    if not contracts.exists():
        return  # nothing deposited: the C1' end-state
    body = contracts.read_text(encoding="utf-8-sig")
    leaked = re.findall(r"^##\s+WOT-\d{4}-\d+[a-z]?", body, flags=re.MULTILINE)
    assert leaked == [], f"fresh install deposited real WOT contracts: {leaked}"


def test_destination_can_still_bootstrap_planning_from_templates():
    """C3' other half: removing the seed must not orphan the destination.

    The documented bootstrap (docs/contract_formation/README.md:26) is copying the
    templates. If those disappear, the destination has no route to a planning set
    and (c) would have degraded into option (a).
    """
    templates = TEMPLATE_ROOT / "docs" / "contract_formation" / "templates"

    assert (templates / "ticket_contract.md").exists(), (
        "the destination bootstraps its planning by copying this template"
    )


# WOT-2026-053h: `motor_workspace_root` -- el dato que evita que un escalado
# aterrice en el buzon equivocado. Medido 2026-08-09: el link tenia 8 campos y
# NINGUNO nombraba el workspace del motor, asi que un destino que escalaba no
# tenia de donde sacar la ruta y el sobre acabo en su PROPIO buzon (forma
# correcta, superficie equivocada, rc=0 y cero senal de error).
def test_read_motor_workspace_root_resolves_declared_sibling(tmp_path):
    """Con declaracion valida, resuelve el hermano; sin ella, None.

    Mutation-to-prove: si `read_motor_workspace_root` devolviera siempre None,
    la primera asercion cae; si ignorase la existencia del directorio, cae la
    de `no_existe`.
    """
    motor = tmp_path / "motor"
    (motor / ".agent" / "config").mkdir(parents=True)
    (tmp_path / "ws").mkdir()
    decl = motor / ".agent" / "config" / "motor_workspace.txt"

    assert ias.read_motor_workspace_root(motor) is None, "sin fichero -> None"

    decl.write_text("# comentario\n\nws\n", encoding="utf-8")
    assert ias.read_motor_workspace_root(motor) == (tmp_path / "ws").resolve(), (
        "salta comentarios y lineas vacias hasta el primer NOMBRE real"
    )

    decl.write_text("no_existe\n", encoding="utf-8")
    assert ias.read_motor_workspace_root(motor) is None, (
        "un nombre que no es un directorio existente NO se acepta"
    )


def test_read_motor_workspace_root_rejects_paths_not_names(tmp_path):
    """Solo NOMBRES: una ruta (absoluta o con separador) se rechaza.

    Es la barrera de portabilidad: aceptar una ruta absoluta dejaria que el
    motor nombrase una maquina concreta. Mutation-to-prove: quitar la guarda de
    separadores hace que estas tres aserciones encuentren un Path en vez de None.
    """
    motor = tmp_path / "motor"
    (motor / ".agent" / "config").mkdir(parents=True)
    decl = motor / ".agent" / "config" / "motor_workspace.txt"
    bs = chr(92)
    for bad in [f"C:{bs}ruta{bs}absoluta", "sub/dir", "..", "# solo comentario"]:
        decl.write_text(bad + "\n", encoding="utf-8")
        assert ias.read_motor_workspace_root(motor) is None, f"debe rechazar {bad!r}"


def test_link_carries_motor_workspace_root_and_degrades_to_none(tmp_path):
    """El link propaga el campo; sin declaracion queda None, nunca inventado.

    `None` es un resultado NORMAL del contrato: el emisor del escalado cae a su
    fallback declarado en vez de deducir una ruta. Mutation-to-prove: omitir la
    clave del payload hace fallar la asercion de pertenencia.
    """
    link = _write_link(tmp_path, prefix="WOT")
    data = json.loads(link.read_text(encoding="utf-8"))
    assert "motor_workspace_root" in data, "el campo debe existir SIEMPRE"
    assert data["motor_workspace_root"] is None, (
        "un motor sin declaracion deja el campo a null, no a una ruta adivinada"
    )


def test_link_populates_workspace_root_when_declaration_exists(tmp_path):
    """WOT-2026-060b: un motor que declara motor_workspace.txt ve el campo
    populated en el link; el generador no lo ignora.

    El defecto medido: el link de v_audio tenia el campo a null porque el motor
    NO tenia el fichero de declaracion. Cuando el fichero existe y apunta a un
    directorio valido, el generador debe rellenar el campo con la ruta resuelta.

    Mutation-to-prove: si `write_motor_destination_link` no llama a
    `read_motor_workspace_root` (o lo ignora), el campo sigue None a pesar de
    que el motor declara su workspace.
    """
    motor = tmp_path / "motor"
    motor.mkdir()
    (motor / ".agent" / "config").mkdir(parents=True)
    ws = tmp_path / "dogfood_workspace"
    ws.mkdir()
    decl = motor / ".agent" / "config" / "motor_workspace.txt"
    decl.write_text("dogfood_workspace\n", encoding="utf-8")

    project_agent = tmp_path / "dest" / ".agent"
    project_agent.mkdir(parents=True)

    link = project_agent / "config" / "motor_destination_link.json"
    write_motor_destination_link(
        project_agent=project_agent,
        motor_root=motor,
        destination_root=tmp_path / "dest",
        motor_version="v9.17.1",
        ticket_prefix="WOT",
    )

    data = json.loads(link.read_text(encoding="utf-8"))
    assert "motor_workspace_root" in data
    expected = str((motor.parent / "dogfood_workspace").resolve())
    assert data["motor_workspace_root"] == expected, (
        f"el generador no rellenó el campo: esperaba {expected}, "
        f"got {data.get('motor_workspace_root')}"
    )
