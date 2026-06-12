"""Tests for the safe pytest runner argument contract."""

from __future__ import annotations

import importlib.util
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = PROJECT_ROOT / "scripts" / "run_pytest_safe.py"


def load_runner_module():
    spec = importlib.util.spec_from_file_location("run_pytest_safe", RUNNER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_args_are_reported_as_default_discovery() -> None:
    runner = load_runner_module()

    assert runner.pytest_args_mode([]) == runner.DEFAULT_ARGS_MODE
    assert runner.pytest_args_mode(["--"]) == runner.DEFAULT_ARGS_MODE
    assert runner.default_test_target() == "tests/"


def test_explicit_args_are_not_reported_as_default_discovery() -> None:
    runner = load_runner_module()

    assert runner.pytest_args_mode(["--", "tests"]) == runner.EXPLICIT_ARGS_MODE
    assert runner.pytest_args_mode(["tests/unit"]) == runner.EXPLICIT_ARGS_MODE
