from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ENCODING_SCRIPT = ROOT / "scripts" / "check_encoding_guard.py"
SKILL_SCRIPT = ROOT / "scripts" / "check_skill_collisions.py"


def _run(script: Path, *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _write_skill(root: Path, name: str, trigger: str) -> None:
    skill_dir = root / "skills" / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ntriggers: [{trigger}]\n---\n",
        encoding="utf-8",
    )


def test_skill_collisions_real_surface_declares_three_items(tmp_path: Path) -> None:
    """Real subprocess path reports its three hermetic SKILL.md inputs."""
    for name in ("a", "b", "c"):
        _write_skill(tmp_path, name, f"/{name}")

    result = _run(SKILL_SCRIPT, "--root", str(tmp_path), cwd=tmp_path)

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "3 elementos auditados" in output
    assert "OK: no skill name or trigger collisions" in output


def test_skill_collisions_real_surface_detects_collision(tmp_path: Path) -> None:
    """A real subprocess keeps the denominator when a trigger collides."""
    _write_skill(tmp_path, "a", "/shared")
    _write_skill(tmp_path, "b", "/shared")

    result = _run(SKILL_SCRIPT, "--root", str(tmp_path), cwd=tmp_path)

    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert "2 elementos auditados" in output


def test_skill_collisions_empty_surface_is_explicit_skip(tmp_path: Path) -> None:
    result = _run(SKILL_SCRIPT, "--root", str(tmp_path), cwd=tmp_path)

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "SKIP EXPLICITO" in output
    assert "No es un PASS" in output
    assert "OK:" not in output


def test_encoding_guard_empty_staged_index_is_explicit_skip(tmp_path: Path) -> None:
    subprocess.run(
        ["git", "init"], cwd=tmp_path, capture_output=True, text=True, check=True
    )
    result = _run(ENCODING_SCRIPT, cwd=tmp_path)

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "SKIP EXPLICITO" in output
    assert "No es un PASS" in output


def test_encoding_guard_explicit_bom_declares_one_inspected_file(
    tmp_path: Path,
) -> None:
    bom_file = tmp_path / "bom.md"
    bom_file.write_bytes(b"\xef\xbb\xbf# bom\n")

    result = _run(ENCODING_SCRIPT, str(bom_file), cwd=tmp_path)

    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert "inspeccionados=1" in output
