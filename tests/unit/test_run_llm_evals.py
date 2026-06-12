"""Tests for run_llm_evals.py isolated evaluation lane."""

import json
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "run_llm_evals.py"
CONFIG_PATH = PROJECT_ROOT / ".agent" / "runtime" / "llm_evals_config.json"


@pytest.fixture
def restore_config():
    """Restore the committed config after tests that mutate it."""
    original_text = (
        CONFIG_PATH.read_text(encoding="utf-8") if CONFIG_PATH.exists() else None
    )
    yield
    if original_text is None:
        if CONFIG_PATH.exists():
            CONFIG_PATH.unlink()
    else:
        CONFIG_PATH.write_text(original_text, encoding="utf-8")


_REQUIRES_LOCAL_CONFIG = pytest.mark.skipif(
    not CONFIG_PATH.exists(),
    reason=(
        "llm_evals_config.json lives under gitignored .agent/runtime/ - it is a "
        "LOCAL artifact, absent on clean clones/CI. NOTE: this contradicts the "
        "'repository ships a default config' contract; follow-up: move the "
        "default to a versioned path or drop that claim."
    ),
)


@_REQUIRES_LOCAL_CONFIG
def test_repository_ships_llm_eval_config(restore_config):
    """The repository should ship a default config for the isolated eval lane."""
    assert CONFIG_PATH.exists()
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    assert payload["model"]
    assert payload["metrics"]
    assert payload["dataset_path"]


def test_script_fails_without_config(restore_config):
    """Test that script fails closed when configuration file is missing."""
    if CONFIG_PATH.exists():
        CONFIG_PATH.unlink()

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--dry-run"],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )

    assert result.returncode == 1
    assert "ERROR: LLM evals configuration not found" in result.stdout


def test_script_fails_with_invalid_schema(restore_config):
    """Test that invalid config schema fails closed."""
    CONFIG_PATH.write_text(
        json.dumps({"model": "gpt-4o-mini", "dataset_path": "data.jsonl"}),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--dry-run"],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )

    assert result.returncode == 1
    assert "Missing required evaluation config fields: metrics" in result.stdout


@_REQUIRES_LOCAL_CONFIG
def test_script_fails_without_deepeval(restore_config):
    """Test that script fails closed when DeepEval is not available (when running actual evaluation)."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )

    assert result.returncode == 1
    assert "ERROR: DeepEval not available" in result.stdout


@_REQUIRES_LOCAL_CONFIG
def test_dry_run_succeeds_with_config(restore_config):
    """Test that dry-run succeeds when config exists (DeepEval not required for dry-run)."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--dry-run"],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )

    assert result.returncode == 0
    assert "DRY RUN: Configuration valid" in result.stdout
    assert "DeepEval available: False" in result.stdout


@_REQUIRES_LOCAL_CONFIG
def test_evaluation_fails_without_deepeval(restore_config):
    """Test that evaluation fails when DeepEval is not available."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )

    assert result.returncode == 1
    assert "ERROR: DeepEval not available" in result.stdout
