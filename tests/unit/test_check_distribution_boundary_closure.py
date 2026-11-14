"""Tests for the travel-reference closure direction of the boundary guard."""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "check_distribution_boundary_closure",
    _ROOT / "scripts" / "check_distribution_boundary.py",
)
cdb = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cdb)


def _wb(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.replace("\r\n", "\n").encode("utf-8"))


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(root), capture_output=True, text=True, timeout=30
    )


def _repo(tmp_path: Path, manifest: str, files: dict[str, str]) -> Path:
    root = tmp_path / "motor"
    root.mkdir()
    _wb(root / "MANIFEST.distribute", manifest)
    for name, text in files.items():
        _wb(root / name, text)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t.t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    committed = _git(root, "commit", "-q", "-m", "fixture")
    assert committed.returncode == 0, committed.stderr
    return root


def _script(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(_ROOT / "scripts" / "check_distribution_boundary.py"),
            "--motor-root",
            str(root),
        ],
        cwd=str(_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_real_shape_and_published_method():
    code, lines = cdb.audit(_ROOT)
    text = "\n".join(lines)
    assert code == 0, text
    denominator = next(
        line for line in lines if line.startswith("[dist-boundary-closure] ")
    )
    match = re.fullmatch(
        r"\[dist-boundary-closure\] \d+ entradas -> \d+ ficheros que viajan -> "
        r"\d+ ficheros fuente -> \d+ pares \(fichero,ref\) -> "
        r"\d+ referencias distintas \(\d+ fuera del manifiesto, "
        r"(?P<frozen>\d+) congeladas\)",
        denominator,
    )
    assert match is not None, denominator
    assert int(match.group("frozen")) == len(cdb._FROZEN_TRAVEL_REFS)
    assert "METODO:" in text
    assert "(2026-11-14)" in text


def test_missing_manifest_is_explicit_skip(tmp_path: Path):
    root = tmp_path / "missing"
    root.mkdir()
    code, lines = cdb.audit_travel_refs(root)
    text = "\n".join(lines)
    assert code == 1
    assert "SKIP" in text and "NO es un PASS" in text


def test_git_failure_is_explicit_skip(tmp_path: Path):
    root = tmp_path / "not_git"
    root.mkdir()
    _wb(root / "MANIFEST.distribute", "src/\n")
    _wb(root / "src" / "a.md", "sin refs\n")
    code, lines = cdb.audit_travel_refs(root)
    text = "\n".join(lines)
    assert code == 1
    assert "git" in text and "SKIP" in text


def test_no_source_is_explicit_skip(tmp_path: Path):
    root = _repo(tmp_path, "data/\n", {"data/a.json": "{}\n"})
    code, lines = cdb.audit_travel_refs(root, ())
    text = "\n".join(lines)
    assert code == 1
    assert "0 ficheros fuente" in text and "NO es un PASS" in text


def test_missing_traveled_prompt_fails_and_intact_passes(tmp_path: Path):
    manifest = "skills/\n"
    files = {"skills/SKILL.md": "Consulta prompts/orphan.md\n"}
    root = _repo(tmp_path, manifest, {**files, "prompts/orphan.md": "x\n"})
    code, lines = cdb.audit_travel_refs(root, ())
    assert code == 1
    assert "skills/SKILL.md" in "\n".join(lines)
    assert "prompts/orphan.md" in "\n".join(lines)

    _wb(root / "MANIFEST.distribute", "skills/\nprompts/orphan.md\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "manifest-intact")
    code, lines = cdb.audit_travel_refs(root, ())
    assert code == 0, "\n".join(lines)


def test_subprocess_exercises_red_and_green_paths(tmp_path: Path):
    frozen_citations = "\n".join(cdb._FROZEN_TRAVEL_REFS)
    root = _repo(
        tmp_path,
        "skills/\nprompts/orphan.md\n",
        {
            "skills/SKILL.md": f"{frozen_citations}\nprompts/orphan.md\n",
            "prompts/orphan.md": "x\n",
            **{ref: "x\n" for ref in cdb._FROZEN_TRAVEL_REFS},
        },
    )
    _wb(root / "MANIFEST.distribute", "skills/\n")
    _git(root, "add", "MANIFEST.distribute")
    _git(root, "commit", "-q", "-m", "remove-ref")
    result = _script(root)
    assert result.returncode != 0
    assert "skills/SKILL.md" in result.stdout + result.stderr
    assert "prompts/orphan.md" in result.stdout + result.stderr

    _wb(root / "MANIFEST.distribute", "skills/\nprompts/orphan.md\n")
    _git(root, "add", "MANIFEST.distribute")
    _git(root, "commit", "-q", "-m", "restore-ref")
    result = _script(root)
    assert result.returncode == 0, result.stdout + result.stderr


def test_frozen_exemption_and_stale_service(tmp_path: Path):
    ref = "prompts/frozen.md"
    root = _repo(tmp_path, "src/\n", {"src/a.md": f"{ref}\n", ref: "x\n"})
    code, lines = cdb.audit_travel_refs(root, (ref,))
    assert code == 0, "\n".join(lines)

    _wb(root / "src/a.md", "sin ref\n")
    code, lines = cdb.audit_travel_refs(root, (ref,))
    text = "\n".join(lines)
    assert code == 1
    assert ref in text
    assert "_FROZEN_TRAVEL_REFS" in text
    assert "python scripts/check_distribution_boundary.py --motor-root ." in text


def test_stale_frozen_reference_missing_from_disk(tmp_path: Path):
    ref = "prompts/__never_cited_frozen_probe__.md"
    root = _repo(tmp_path, "src/\n", {"src/a.md": "sin ref\n"})
    code, lines = cdb.audit_travel_refs(root, (ref,))
    text = "\n".join(lines)
    assert code == 1
    assert ref in text
    assert "_FROZEN_TRAVEL_REFS" in text
    assert "python scripts/check_distribution_boundary.py --motor-root ." in text


def test_nonexistent_reference_is_filtered(tmp_path: Path):
    root = _repo(tmp_path, "src/\n", {"src/a.md": "prompts/not-on-disk.md\n"})
    code, lines = cdb.audit_travel_refs(root, ())
    text = "\n".join(lines)
    assert code == 0, text
    assert "no existir en disco" in text


def test_dedupe_is_per_file(tmp_path: Path):
    ref = "prompts/orphan.md"
    root = _repo(tmp_path, "src/\n", {"src/a.md": f"{ref} {ref}\n{ref}\n", ref: "x\n"})
    code, lines = cdb.audit_travel_refs(root, ())
    text = "\n".join(lines)
    assert code == 1
    assert "-> 1 pares" in text


def test_travel_prompt_is_also_a_citing_source(tmp_path: Path):
    ref = "prompts/audit_pipeline_codeonly.md"
    root = _repo(
        tmp_path,
        "prompts/audit_pipeline.md\n",
        {"prompts/audit_pipeline.md": f"{ref}\n", ref: "x\n"},
    )
    code, lines = cdb.audit_travel_refs(root, ())
    text = "\n".join(lines)
    assert code == 1
    assert "prompts/audit_pipeline.md" in text and ref in text
