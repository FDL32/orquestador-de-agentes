"""Tests del centinela manual de checklist de espera (WOT-2026-160p)."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from scripts import espera_checklist_mode as mode


def test_on_default_observe_escribe_json(tmp_path: Path) -> None:
    assert mode.main(["on", "--root", str(tmp_path)]) == 0
    data = json.loads((tmp_path / mode.SENTINEL_RELPATH).read_text(encoding="utf-8"))
    assert data["mode"] == "observe"
    datetime.fromisoformat(data["activated_at"])


def test_on_block_escribe_modo_block(tmp_path: Path) -> None:
    assert mode.main(["on", "--mode", "block", "--root", str(tmp_path)]) == 0
    data = json.loads((tmp_path / mode.SENTINEL_RELPATH).read_text(encoding="utf-8"))
    assert data["mode"] == "block"


def test_off_es_idempotente(tmp_path: Path, capsys) -> None:
    assert mode.main(["off", "--root", str(tmp_path)]) == 0
    assert "ya estaba OFF" in capsys.readouterr().out
    assert mode.main(["on", "--root", str(tmp_path)]) == 0
    assert mode.main(["off", "--root", str(tmp_path)]) == 0
    assert not (tmp_path / mode.SENTINEL_RELPATH).exists()
    assert mode.main(["off", "--root", str(tmp_path)]) == 0


def test_status_off_legible_e_ilegible(tmp_path: Path, capsys) -> None:
    assert mode.main(["status", "--root", str(tmp_path)]) == 0
    assert "espera_checklist_mode: OFF" in capsys.readouterr().out
    assert mode.main(["on", "--mode", "block", "--root", str(tmp_path)]) == 0
    assert mode.main(["status", "--root", str(tmp_path)]) == 0
    assert "ON (mode=block" in capsys.readouterr().out
    (tmp_path / mode.SENTINEL_RELPATH).write_text("{roto", encoding="utf-8")
    assert mode.main(["status", "--root", str(tmp_path)]) == 0
    assert "ON pero ILEGIBLE" in capsys.readouterr().out


def test_cli_real_status(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, str(Path(mode.__file__)), "status", "--root", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == "espera_checklist_mode: OFF"
