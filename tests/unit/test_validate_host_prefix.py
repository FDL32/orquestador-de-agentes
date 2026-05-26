"""Tests for ticket prefix plumbing in install_agent_system.py."""

from scripts.install_agent_system import _write_prefix_to_project_md


def test_write_prefix_to_project_md_creates_file(tmp_path):
    """When PROJECT.md doesn't exist, _write_prefix_to_project_md creates it."""
    _write_prefix_to_project_md(tmp_path, "XXX", dry_run=False)

    project_md = tmp_path / "PROJECT.md"
    assert project_md.exists()
    content = project_md.read_text(encoding="utf-8")
    assert "Ticket prefix: XXX" in content


def test_write_prefix_to_project_md_updates_existing(tmp_path):
    """When PROJECT.md exists without prefix, add it after the header."""
    project_md = tmp_path / "PROJECT.md"
    project_md.write_text("# Project: test\nSome content\n", encoding="utf-8")

    _write_prefix_to_project_md(tmp_path, "DEST", dry_run=False)

    content = project_md.read_text(encoding="utf-8")
    lines = content.splitlines()
    assert "Ticket prefix: DEST" in content
    assert lines[0] == "# Project: test"
    assert lines[1] == "Ticket prefix: DEST"


def test_write_prefix_to_project_md_replaces_existing(tmp_path):
    """When PROJECT.md has a prefix, replace it with the new one."""
    project_md = tmp_path / "PROJECT.md"
    project_md.write_text(
        "# Project: test\nTicket prefix: OLD\nContent\n", encoding="utf-8"
    )

    _write_prefix_to_project_md(tmp_path, "NEW", dry_run=False)

    content = project_md.read_text(encoding="utf-8")
    assert "Ticket prefix: NEW" in content
    assert "Ticket prefix: OLD" not in content


def test_write_prefix_to_project_md_dry_run(tmp_path, capsys):
    """When dry_run=True, no file is modified but message is printed."""
    project_md = tmp_path / "PROJECT.md"
    project_md.write_text("# Project: test\n", encoding="utf-8")

    _write_prefix_to_project_md(tmp_path, "XXX", dry_run=True)

    # File should not be modified
    content = project_md.read_text(encoding="utf-8")
    assert "Ticket prefix:" not in content

    out = capsys.readouterr().out
    assert "Would update" in out


def test_write_prefix_to_project_md_dry_run_create(tmp_path, capsys):
    """When dry_run=True and file doesn't exist, print create message."""
    _write_prefix_to_project_md(tmp_path, "XXX", dry_run=True)

    project_md = tmp_path / "PROJECT.md"
    assert not project_md.exists()

    out = capsys.readouterr().out
    assert "Would create" in out
