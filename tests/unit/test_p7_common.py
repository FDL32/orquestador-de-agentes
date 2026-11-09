from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.flight import p7_common


def _write_list(path: Path, entries: list[dict[str, object]]) -> str:
    path.write_text(
        "\n".join(json.dumps(item, sort_keys=True) for item in entries) + "\n",
        encoding="utf-8",
    )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_manifiesto_arbol(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("alpha", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "b.txt").write_text("beta", encoding="utf-8")
    manifest = p7_common.manifest_of_tree(tmp_path)
    assert [row["rel"] for row in manifest] == ["a.txt", "nested/b.txt"]
    assert set(manifest[0]) == {"rel", "size", "mtime", "sha256"}
    assert manifest[0]["size"] == (tmp_path / "a.txt").stat().st_size
    assert manifest[0]["mtime"] == (tmp_path / "a.txt").stat().st_mtime
    assert manifest[0]["sha256"] == p7_common.sha256_file(tmp_path / "a.txt")
    assert p7_common.verify_manifest_entries(tmp_path, manifest) is None


def test_guardas_locks(tmp_path: Path) -> None:
    lock = tmp_path / "p7.lock"
    with pytest.raises(p7_common.ArchiveError):
        p7_common.acquire_lock(lock, pid=os.getpid(), cwd=str(tmp_path / "missing"))
    lock.write_text(
        json.dumps({"pid": 999999999, "cwd": str(tmp_path)}), encoding="utf-8"
    )
    p7_common.acquire_lock(lock, pid=os.getpid(), cwd=str(tmp_path))
    assert p7_common.lock_is_held(lock)
    with pytest.raises(p7_common.ArchiveError):
        p7_common.acquire_lock(lock, pid=os.getpid(), cwd=str(tmp_path))
    p7_common.release_lock(lock)
    assert not lock.exists()


def test_reparse_point_real_no_se_sigue(tmp_path: Path) -> None:
    if os.name != "nt":
        pytest.skip("junction requiere Windows")
    target = tmp_path / "target"
    target.mkdir()
    (target / "inside.txt").write_text("x", encoding="utf-8")
    junction = tmp_path / "junction"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=10,
    )
    if result.returncode != 0:
        pytest.fail(result.stderr or result.stdout)
    try:
        assert p7_common.is_reparse_or_link(junction)
        assert all(
            "junction" not in str(path)
            for path in p7_common.walk_files_no_links(tmp_path)
        )
    finally:
        subprocess.run(
            ["cmd", "/c", "rmdir", str(junction)],
            check=False,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )


def test_cuadre_bidireccional(tmp_path: Path) -> None:
    family = "arranques"
    root = tmp_path / family
    root.mkdir()
    (root / "real.zip").write_text("real", encoding="utf-8")
    (root / "real.manifest.json").write_text("manifest", encoding="utf-8")
    rows = [
        {
            "status": "ARCHIVADO",
            "zip": str(root / "ghost.zip"),
            "manifest": str(root / "ghost.manifest.json"),
        }
    ]
    findings = p7_common.reconcile_index(tmp_path, rows, family)
    assert findings == [
        "fila_sin_fichero: ghost.manifest.json",
        "fila_sin_fichero: ghost.zip",
        "fichero_sin_fila: real.manifest.json",
        "fichero_sin_fila: real.zip",
    ]


def test_lista_aprobada_hash_y_entrada(tmp_path: Path) -> None:
    payload = tmp_path / "item.txt"
    payload.write_text("approved", encoding="utf-8")
    entry = {
        "rel": "item.txt",
        "sha256": p7_common.sha256_file(payload),
        "mtime": payload.stat().st_mtime,
        "size": payload.stat().st_size,
    }
    approved = tmp_path / "approved.jsonl"
    list_hash = _write_list(approved, [entry])
    entries = p7_common.load_approved_list(approved, list_hash)
    p7_common.verify_list_entries(entries, tmp_path)
    payload.write_text("tampered", encoding="utf-8")
    with pytest.raises(p7_common.ArchiveError):
        p7_common.verify_list_entries(entries, tmp_path)


def test_manifest_discrepancy_aborts_on_first_change(tmp_path: Path) -> None:
    path = tmp_path / "x.txt"
    path.write_text("before", encoding="utf-8")
    manifest = p7_common.manifest_of_tree(tmp_path)
    path.write_text("after", encoding="utf-8")
    with pytest.raises(p7_common.ArchiveError, match="discrepante"):
        p7_common.verify_manifest_entries(tmp_path, manifest)


def test_ttl_only_generates_candidates(tmp_path: Path) -> None:
    path = tmp_path / "candidate.txt"
    path.write_text("keep", encoding="utf-8")
    before = path.read_bytes()
    candidates = p7_common.classify_candidates(
        [{"rel": "candidate.txt", "mtime": 0}],
        now=10 * 86400,
        ttl_dias=7,
        min_age_segundos=0,
    )
    assert candidates == [{"rel": "candidate.txt", "mtime": 0}]
    assert path.read_bytes() == before


def test_archive_script_imports_from_neutral_cwd(tmp_path: Path) -> None:
    project = tmp_path / "project"
    arranques = project / "orchestrator_pipeline" / "arranques"
    arranques.mkdir(parents=True)
    (arranques / "ARRANQUE_subproceso.md").write_text("x\n", encoding="utf-8")
    collaboration = project / ".agent" / "collaboration"
    collaboration.mkdir(parents=True)
    (collaboration / "backlog.md").write_text("", encoding="utf-8")
    subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
    script = Path(__file__).resolve().parents[2] / "scripts" / "archive_arranques.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--project-root",
            str(project),
            "--dry-run",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "denominador: 1" in result.stdout
