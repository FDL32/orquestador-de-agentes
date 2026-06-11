"""Tests for WT-2026-253c: local_audit.py parser alignment with real artifacts.

[NON-REVERSE-CLASSICAL: coverage matrix for parser fixes against real-world
formats — canonical format is already live in PROJECT.md and execution_log.md]
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


_MOTOR_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_MOTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_MOTOR_ROOT))


def _load_local_audit():
    spec = importlib.util.spec_from_file_location(
        "local_audit",
        _MOTOR_ROOT / "scripts" / "local_audit.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("local_audit", mod)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def la():
    return _load_local_audit()


class TestGetVersionsBoldMarkdownFormat:
    """get_versions must parse **Version:** (canonical bold markdown format)."""

    def test_bold_markdown_version(self, la, tmp_path, monkeypatch):
        project_md = tmp_path / "PROJECT.md"
        project_md.write_text(
            "# Project: foo\n**Version:** v9.15.0\n", encoding="utf-8"
        )
        monkeypatch.setattr(la, "PROJECT_ROOT", tmp_path)
        versions = la.get_versions()
        assert versions.get("project_md") == "v9.15.0", (
            f"Expected v9.15.0, got {versions.get('project_md')!r}"
        )

    def test_legacy_list_item_version(self, la, tmp_path, monkeypatch):
        project_md = tmp_path / "PROJECT.md"
        project_md.write_text("# Project: foo\n- Version: v7.0.0\n", encoding="utf-8")
        monkeypatch.setattr(la, "PROJECT_ROOT", tmp_path)
        versions = la.get_versions()
        assert versions.get("project_md") == "v7.0.0"

    def test_missing_version_returns_no_key(self, la, tmp_path, monkeypatch):
        project_md = tmp_path / "PROJECT.md"
        project_md.write_text("# Project: foo\nNo version here.\n", encoding="utf-8")
        monkeypatch.setattr(la, "PROJECT_ROOT", tmp_path)
        versions = la.get_versions()
        assert "project_md" not in versions


class TestGetRecentWpsTicketIDPattern:
    """get_recent_wps must find WT-, WP-, and 3-letter prefix headings."""

    def test_finds_wt_prefix(self, la, tmp_path, monkeypatch):
        collab = tmp_path / ".agent" / "collaboration"
        collab.mkdir(parents=True)
        (collab / "execution_log.md").write_text(
            "### WT-2026-251a some description\ncontent\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(la, "COLLAB_DIR", collab)
        wps = la.get_recent_wps()
        assert any("WT-2026-251a" in wp for wp in wps), f"Got {wps}"

    def test_finds_wot_prefix(self, la, tmp_path, monkeypatch):
        collab = tmp_path / ".agent" / "collaboration"
        collab.mkdir(parents=True)
        (collab / "execution_log.md").write_text(
            "### WOT-2026-001a some description\ncontent\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(la, "COLLAB_DIR", collab)
        wps = la.get_recent_wps()
        assert any("WOT-2026-001a" in wp for wp in wps), f"Got {wps}"

    def test_ignores_plain_headings(self, la, tmp_path, monkeypatch):
        collab = tmp_path / ".agent" / "collaboration"
        collab.mkdir(parents=True)
        (collab / "execution_log.md").write_text(
            "### Some plain heading\ncontent\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(la, "COLLAB_DIR", collab)
        wps = la.get_recent_wps()
        assert wps == [], f"Expected empty, got {wps}"
