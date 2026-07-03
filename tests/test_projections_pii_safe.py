from __future__ import annotations

import json
import re
from pathlib import Path

from scripts import project_scanner
from scripts.install_agent_system import (
    PROJECTIONS_GITIGNORE_ENTRIES,
    PROJECTIONS_GITIGNORE_MARKER,
    ensure_destination_projections_ignored,
)


# Any absolute local path shape (drive letter or unix home) is a leak in a
# regenerable projection (WOT-2026-016p / N7).
_ABS_PATH_RE = re.compile(r"[A-Za-z]:[\\/]|/home/")


def _make_destino(tmp_path: Path) -> Path:
    root = tmp_path / "destino_demo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("print('hola')\n", encoding="utf-8")
    return root


class TestEnsureProjectionsIgnored:
    def test_adds_all_entries_when_gitignore_missing(self, tmp_path: Path) -> None:
        root = _make_destino(tmp_path)
        added = ensure_destination_projections_ignored(root)
        assert set(added) == set(PROJECTIONS_GITIGNORE_ENTRIES)
        text = (root / ".gitignore").read_text(encoding="utf-8")
        assert PROJECTIONS_GITIGNORE_MARKER in text
        for entry in PROJECTIONS_GITIGNORE_ENTRIES:
            assert entry in text.splitlines()

    def test_idempotent_no_duplicates_on_rerun(self, tmp_path: Path) -> None:
        root = _make_destino(tmp_path)
        ensure_destination_projections_ignored(root)
        again = ensure_destination_projections_ignored(root)
        assert again == []
        lines = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
        for entry in PROJECTIONS_GITIGNORE_ENTRIES:
            assert lines.count(entry) == 1

    def test_respects_existing_user_entries(self, tmp_path: Path) -> None:
        root = _make_destino(tmp_path)
        (root / ".gitignore").write_text(".venv/\n.agent/runtime/\n", encoding="utf-8")
        added = ensure_destination_projections_ignored(root)
        # runtime ya estaba: no se duplica; el resto se anade
        assert ".agent/runtime/" not in added
        lines = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
        assert lines.count(".agent/runtime/") == 1
        assert ".venv/" in lines  # lo del usuario se conserva

    def test_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        root = _make_destino(tmp_path)
        added = ensure_destination_projections_ignored(root, dry_run=True)
        assert added  # detecta faltantes
        assert not (root / ".gitignore").exists()


class TestGeneratorsPiiSafe:
    def test_project_map_has_no_absolute_paths(self, tmp_path: Path) -> None:
        """DoD #3 + BARRERA: con el comportamiento antiguo (str(project_root))
        este assert falla; con el fix (folder name) pasa."""
        root = _make_destino(tmp_path)
        project_map = project_scanner.scan_project(root)
        assert project_map["project_root"] == root.name
        blob = json.dumps(project_map)
        leaks = _ABS_PATH_RE.findall(blob)
        assert not leaks, f"rutas absolutas en project-map: {leaks[:3]}"

    def test_destination_map_identity_has_no_absolute_paths(
        self, tmp_path: Path
    ) -> None:
        from scripts import destination_context as dc

        root = _make_destino(tmp_path)
        (root / ".agent" / "config").mkdir(parents=True)
        (root / ".agent" / "config" / "motor_destination_link.json").write_text(
            json.dumps(
                {
                    "motor_root": str(tmp_path / "motor_falso"),
                    "motor_version": "9.9",
                }
            ),
            encoding="utf-8",
        )
        motor_link = dc.resolve_motor_link(root)
        assert motor_link is not None
        # La seccion de identidad se construye con nombres, no rutas
        assert Path(str(motor_link.get("motor_root"))).name == "motor_falso"
