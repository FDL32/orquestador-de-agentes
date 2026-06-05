"""Tests for scripts/destination_context.py.

Covers:
- New destination without graphify produces a useful map
- Absence of git does not crash
- Unversioned repo (no .git) does not crash
- Missing/invalid motor_destination_link.json gives clear error
- Byte budget truncation preserves identity + operational state
- Optional files missing degrades cleanly
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.destination_context import (
    build_map,
    extract_file_preview,
    get_git_info,
    get_operational_state,
    main,
    resolve_motor_link,
)


def _write_link(project_root: Path, *, ticket_prefix: str | None = None) -> dict:
    """Helper: write a valid motor_destination_link.json in the project."""
    config_dir = project_root / ".agent" / "config"
    config_dir.mkdir(parents=True)
    payload = {
        "motor_root": str(project_root.resolve()),
        "destination_root": str(project_root.resolve()),
        "motor_version": "9.15.0-test",
        "destination_id": project_root.name,
        "ticket_prefix": ticket_prefix,
        "created_at": "2026-06-05T00:00:00+00:00",
        "manifest_version": "1.0",
    }
    link_path = config_dir / "motor_destination_link.json"
    link_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def _write_work_plan(project_root: Path, *, ticket_id: str = "WT-9999-NNN") -> None:
    """Helper: write a minimal work_plan.md in the project."""
    collab = project_root / ".agent" / "collaboration"
    collab.mkdir(parents=True)
    content = (
        f"# Work Ticket - {ticket_id}\n"
        f"\n"
        f"## Metadata\n"
        f"- **ID:** {ticket_id}\n"
        f"- **Title:** Test ticket for destination context\n"
        f"- **Priority:** Alta\n"
        f"- **Estado:** APPROVED\n"
        f"- **deliverable_type:** code\n"
    )
    (collab / "work_plan.md").write_text(content, encoding="utf-8")


def _write_state_md(project_root: Path) -> None:
    """Helper: write a minimal STATE.md in the project."""
    collab = project_root / ".agent" / "collaboration"
    collab.mkdir(parents=True, exist_ok=True)
    (collab / "STATE.md").write_text(
        "ACTIVE_TICKET: WT-9999-NNN\nSTATUS: IN_PROGRESS\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# resolve_motor_link
# ---------------------------------------------------------------------------


def test_resolve_motor_link_valid(tmp_path):
    """Valid link returns parsed dict."""
    payload = _write_link(tmp_path, ticket_prefix="WT")
    result = resolve_motor_link(tmp_path)
    assert result is not None
    assert result["motor_root"] == payload["motor_root"]
    assert result["ticket_prefix"] == "WT"


def test_resolve_motor_link_missing(tmp_path):
    """Missing link returns None."""
    assert resolve_motor_link(tmp_path) is None


def test_resolve_motor_link_invalid_json(tmp_path):
    """Invalid JSON returns None."""
    config_dir = tmp_path / ".agent" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "motor_destination_link.json").write_text(
        "{invalid", encoding="utf-8"
    )
    assert resolve_motor_link(tmp_path) is None


# ---------------------------------------------------------------------------
# get_git_info
# ---------------------------------------------------------------------------


def test_git_info_no_git_dir(tmp_path):
    """No .git directory returns None."""
    info = get_git_info(tmp_path)
    assert info is None


def test_git_info_clean_repo(tmp_path):
    """Clean git repo returns clean status."""
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True
    )
    (tmp_path / "README.md").write_text("# Test", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)

    info = get_git_info(tmp_path)
    assert info is not None
    assert info["branch"] in ("main", "master")
    assert info["dirty"] is False
    assert "error" not in info


# ---------------------------------------------------------------------------
# extract_file_preview
# ---------------------------------------------------------------------------


def test_extract_file_preview(tmp_path):
    """Returns first N lines of a text file."""
    f = tmp_path / "test.md"
    f.write_text("line1\nline2\nline3\n", encoding="utf-8")
    preview = extract_file_preview(f, max_lines=2)
    assert preview is not None
    assert "line1" in preview
    assert "line2" in preview
    assert "line3" not in preview


def test_extract_file_preview_missing(tmp_path):
    """Missing file returns None."""
    assert extract_file_preview(tmp_path / "nonexistent.md") is None


# ---------------------------------------------------------------------------
# get_operational_state
# ---------------------------------------------------------------------------


def test_get_operational_state_no_collab(tmp_path):
    """No collaboration directory returns empty state."""
    state = get_operational_state(tmp_path)
    assert state.get("ticket_id") is None
    assert state.get("state_md_present") is False


def test_get_operational_state_with_ticket(tmp_path):
    """Active ticket ID is parsed from work_plan.md."""
    _write_work_plan(tmp_path, ticket_id="WT-9999-NNN")
    state = get_operational_state(tmp_path)
    assert state["ticket_id"] == "WT-9999-NNN"
    assert state["ticket_title"] == "Test ticket for destination context"
    assert state["estado"] == "APPROVED"


def test_get_operational_state_with_state_md(tmp_path):
    """STATE.md content is captured."""
    _write_state_md(tmp_path)
    state = get_operational_state(tmp_path)
    assert state["state_md_present"] is True
    assert "WT-9999-NNN" in state.get("state_md_content", "")


# ---------------------------------------------------------------------------
# build_map - identity and topology
# ---------------------------------------------------------------------------


def test_build_map_includes_identity(tmp_path):
    """Map contains destination root and motor link info."""
    _write_link(tmp_path, ticket_prefix="WT")
    content = build_map(tmp_path, max_bytes=204800)
    assert str(tmp_path.resolve()) in content
    assert "destination-hosted" in content
    assert "Motor link:" in content
    assert "valid" in content


def test_build_map_identity_without_link(tmp_path):
    """Without link, identity shows standalone mode."""
    content = build_map(tmp_path, max_bytes=204800)
    assert "standalone" in content
    assert "absent" in content
    assert "not resolvable" in content


# ---------------------------------------------------------------------------
# build_map - operational state
# ---------------------------------------------------------------------------


def test_build_map_includes_ticket_info(tmp_path):
    """Active ticket metadata appears in the map."""
    _write_link(tmp_path)
    _write_work_plan(tmp_path)
    content = build_map(tmp_path, max_bytes=204800)
    assert "WT-9999-NNN" in content
    assert "APPROVED" in content


def test_build_map_no_ticket_shows_none(tmp_path):
    """When no ticket exists, shows 'none'."""
    _write_link(tmp_path)
    content = build_map(tmp_path, max_bytes=204800)
    assert "Active Ticket:" in content
    assert "**none**" in content or "none" in content


# ---------------------------------------------------------------------------
# build_map - git section
# ---------------------------------------------------------------------------


def test_build_map_no_git(tmp_path):
    """Map includes degraded git section when no repo."""
    _write_link(tmp_path)
    content = build_map(tmp_path, max_bytes=204800)
    assert "no git repository" in content or "Git State" in content


# ---------------------------------------------------------------------------
# build_map - byte budget truncation
# ---------------------------------------------------------------------------


def test_build_map_respects_byte_budget(tmp_path):
    """Map never exceeds max_bytes limit."""
    _write_link(tmp_path)
    _write_work_plan(tmp_path)
    content = build_map(tmp_path, max_bytes=1024)
    assert len(content.encode("utf-8")) <= 1024


def test_build_map_small_budget_preserves_identity(tmp_path):
    """Even with small budget, identity and state survive."""
    _write_link(tmp_path)
    _write_work_plan(tmp_path)
    _write_state_md(tmp_path)
    # Use budget large enough for identity + operational but small enough
    # to force truncation of lower-priority sections
    content = build_map(tmp_path, max_bytes=1024)
    # Identity must be there
    assert str(tmp_path.resolve()) in content
    # Operational state must be there
    assert "WT-9999-NNN" in content
    assert "IN_PROGRESS" in content
    # Size must be within budget
    assert len(content.encode("utf-8")) <= 1024


# ---------------------------------------------------------------------------
# build_map - graphify absent
# ---------------------------------------------------------------------------


def test_build_map_no_graphify(tmp_path):
    """Absence of graphify-out/ does not crash or add graphify section."""
    _write_link(tmp_path)
    content = build_map(tmp_path, max_bytes=204800)
    assert "Graphify" not in content


# ---------------------------------------------------------------------------
# main() integration
# ---------------------------------------------------------------------------


def test_main_missing_link_returns_error(tmp_path, capsys):
    """--bootstrap without link gives clear error and non-zero exit."""
    exit_code = main(
        [
            "--bootstrap",
            "--project-root",
            str(tmp_path),
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "not found or invalid" in captured.err


def test_main_generates_map(tmp_path, capsys):
    """--bootstrap with valid link generates destination_map.md."""
    _write_link(tmp_path)
    exit_code = main(
        [
            "--bootstrap",
            "--project-root",
            str(tmp_path),
        ]
    )
    assert exit_code == 0
    map_file = tmp_path / ".agent" / "context" / "destination_map.md"
    assert map_file.exists()
    content = map_file.read_text(encoding="utf-8")
    assert str(tmp_path.resolve()) in content
    assert "Destination Context Map" in content


def test_main_respects_max_bytes(tmp_path, capsys):
    """--max-bytes flag limits output size."""
    _write_link(tmp_path)
    _write_work_plan(tmp_path)
    # Use 800 bytes — enough for identity + operational + partial git
    exit_code = main(
        [
            "--bootstrap",
            "--project-root",
            str(tmp_path),
            "--max-bytes",
            "800",
        ]
    )
    assert exit_code == 0
    map_file = tmp_path / ".agent" / "context" / "destination_map.md"
    content = map_file.read_text(encoding="utf-8")
    assert len(content.encode("utf-8")) <= 800


def test_main_invalid_project_root(tmp_path, capsys):
    """Non-existent project root returns error."""
    exit_code = main(
        [
            "--bootstrap",
            "--project-root",
            str(tmp_path / "nonexistent"),
        ]
    )
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "does not exist" in captured.err


# ---------------------------------------------------------------------------
# Regression: no graphify, no crash
# ---------------------------------------------------------------------------


def test_build_map_no_optional_files(tmp_path):
    """Map handles missing PROJECT.md, README, etc. gracefully."""
    _write_link(tmp_path)
    content = build_map(tmp_path, max_bytes=204800)
    # Should not crash, key sections present
    assert "Identity & Topology" in content
    assert "Operational State" in content
