"""Tests for `scripts/prepare_cloud_bundle.py` (WOT cloud bundle helper)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parents[2]
    path = root / "scripts" / "prepare_cloud_bundle.py"
    spec = importlib.util.spec_from_file_location("prepare_cloud_bundle", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def test_prepare_cloud_bundle_writes_bundle_and_manifest(tmp_path):
    repo = _init_repo(tmp_path)
    pcb = _load_module()

    assert pcb.main(["--task", "revisar README", "--repo", str(repo)]) == 0

    bundle = repo / ".agent" / "cloud_bundle.md"
    manifest = repo / ".agent" / "cloud_manifest.json"
    assert bundle.exists()
    assert manifest.exists()
    assert "revisar README" in bundle.read_text(encoding="utf-8")

    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["task"] == "revisar README"
    assert data["task_id"] == "revisar-readme"
    assert data["commit"] == _git(repo, "rev-parse", "HEAD")
    assert data["base_branch"] in {"main", "master"}
    assert data["branch"] == "cloud/revisar-readme"
    assert data["model"] == "sonnet"
    assert data["allowed_tools"] == "Read,Grep,Glob"
    assert data["bundle"] == ".agent/cloud_bundle.md"
    assert data["bundle_sha256"] == hashlib.sha256(bundle.read_bytes()).hexdigest()


def test_prepare_cloud_bundle_manifest_hash_tracks_current_bundle(tmp_path):
    repo = _init_repo(tmp_path)
    pcb = _load_module()

    assert pcb.main(["--task", "t", "--repo", str(repo)]) == 0
    assert pcb.main(["--task", "t", "--repo", str(repo)]) == 0

    bundle = repo / ".agent" / "cloud_bundle.md"
    data = json.loads(
        (repo / ".agent" / "cloud_manifest.json").read_text(encoding="utf-8")
    )
    assert data["bundle_sha256"] == hashlib.sha256(bundle.read_bytes()).hexdigest()
