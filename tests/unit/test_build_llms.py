"""Tests for the llms.txt/llms-full.txt generator (WOT-2026-024g).

Contract under test:
- ``--base`` default points to the REAL public repo, never the 404 one.
- ``--check`` regenerates in memory, compares against disk, exit 1 on drift,
  exit 0 when in sync, and writes NOTHING.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "build_llms.py"


def _load_build_llms():
    spec = importlib.util.spec_from_file_location("build_llms_under_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


build_llms = _load_build_llms()


def test_default_base_is_the_real_repo():
    # The dead repo (404) must never be the default again.
    assert "orquestacion-agentes" not in build_llms.DEFAULT_BASE
    assert "orquestador-de-agentes" in build_llms.DEFAULT_BASE


def test_cli_base_overrides_env_and_default(monkeypatch):
    monkeypatch.setenv("LLMS_REPO_BASE", "https://example.com/env-base")
    assert build_llms._resolve_base("https://example.com/cli-base/") == (
        "https://example.com/cli-base"
    )
    # Without --base, the env var wins over the default.
    assert build_llms._resolve_base(None) == "https://example.com/env-base"


def test_render_contains_no_dead_repo():
    index, full = build_llms.render(build_llms.DEFAULT_BASE)
    assert "orquestacion-agentes" not in index
    assert "orquestacion-agentes" not in full
    assert "orquestador-de-agentes" in index


def test_check_returns_zero_when_in_sync(monkeypatch, capsys):
    # Point the generator at a tmp PROJECT_ROOT and generate first, so disk
    # matches the generator output exactly.
    tmp_root = Path(pytest.importorskip("tempfile").mkdtemp())
    monkeypatch.setattr(build_llms, "PROJECT_ROOT", tmp_root)
    rc_gen = build_llms.main([])
    assert rc_gen == 0
    capsys.readouterr()

    rc_check = build_llms.main(["--check"])
    assert rc_check == 0, "in-sync tree must return exit 0"


def test_check_detects_drift_and_writes_nothing(monkeypatch, capsys):
    tmp_root = Path(pytest.importorskip("tempfile").mkdtemp())
    monkeypatch.setattr(build_llms, "PROJECT_ROOT", tmp_root)
    assert build_llms.main([]) == 0
    capsys.readouterr()

    # Mutate one line on disk -> drift must be detected.
    llms_path = tmp_root / "llms.txt"
    original = llms_path.read_text(encoding="utf-8")
    llms_path.write_text(original + "\n<!-- drift -->\n", encoding="utf-8")

    rc = build_llms.main(["--check"])
    assert rc == 1, "drift must return exit 1"
    # --check must not have rewritten the file (it stays mutated).
    assert llms_path.read_text(encoding="utf-8").endswith("<!-- drift -->\n")


def test_check_missing_file_is_drift(monkeypatch):
    tmp_root = Path(pytest.importorskip("tempfile").mkdtemp())
    monkeypatch.setattr(build_llms, "PROJECT_ROOT", tmp_root)
    # No files generated at all -> absent files count as drift.
    assert build_llms.main(["--check"]) == 1
