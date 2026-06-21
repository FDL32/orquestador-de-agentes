"""WOT-2026-010m: barriers for the additive xdist pilot in quality-gates.yml.

The pilot consumes the 011e opt-in capability (--xdist-workers) in CI WITHOUT
making xdist the gate: it is non-blocking, and the canonical serial run must
stay serial. These barriers fail if the pilot disappears OR if the canonical
run accidentally adopts xdist.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml


def get_repo_root() -> Path:
    return Path(__file__).parent.parent.parent


def load_yaml_file(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


class TestQualityGatesXdistPilot:
    @pytest.fixture
    def workflow(self) -> dict[str, Any]:
        return load_yaml_file(
            get_repo_root() / ".github" / "workflows" / "quality-gates.yml"
        )

    @staticmethod
    def _pytest_steps(workflow: dict[str, Any]) -> list[dict[str, Any]]:
        steps = workflow["jobs"]["quality-gates"]["steps"]
        return [s for s in steps if "run_pytest_safe.py" in str(s.get("run", ""))]

    @staticmethod
    def _canonical_step(workflow: dict[str, Any]) -> dict[str, Any]:
        """The canonical serial run: run_pytest_safe.py without --xdist-workers."""
        for s in TestQualityGatesXdistPilot._pytest_steps(workflow):
            if "--xdist-workers" not in str(s.get("run", "")):
                return s
        raise AssertionError("No canonical serial pytest step (without xdist) found")

    @staticmethod
    def _pilot_step(workflow: dict[str, Any]) -> dict[str, Any]:
        """The xdist pilot: run_pytest_safe.py with --xdist-workers."""
        for s in TestQualityGatesXdistPilot._pytest_steps(workflow):
            if "--xdist-workers" in str(s.get("run", "")):
                return s
        raise AssertionError("No xdist pilot step (--xdist-workers) found")

    def test_canonical_serial_run_still_exists(self, workflow):
        """The real gate: a serial run_pytest_safe.py with no xdist, blocking."""
        step = self._canonical_step(workflow)
        assert "--xdist-workers" not in str(step.get("run", "")), (
            "the canonical run must NOT use xdist"
        )
        # Blocking (continue-on-error is false/absent): it gates the job.
        assert not step.get("continue-on-error", False), (
            "the canonical run must stay a real (blocking) gate"
        )

    def test_xdist_pilot_exists(self, workflow):
        """FAIL-without barrier: the additive xdist pilot must be present."""
        step = self._pilot_step(workflow)
        assert "--xdist-workers" in str(step.get("run", "")), (
            "the pilot must invoke run_pytest_safe.py with --xdist-workers"
        )

    def test_xdist_pilot_is_non_blocking(self, workflow):
        """The pilot must be non-blocking (continue-on-error): the unit subset still
        has known non-parallel-safe tests (011e), so the pilot must never fail CI."""
        step = self._pilot_step(workflow)
        assert step.get("continue-on-error") is True, (
            "the xdist pilot must set continue-on-error: true (non-blocking)"
        )

    def test_pilot_uses_runner_not_raw_pytest(self, workflow):
        """The pilot reuses the runner's opt-in seam, not a raw `pytest -n`."""
        run = str(self._pilot_step(workflow).get("run", ""))
        assert "run_pytest_safe.py" in run, (
            "the pilot must go through scripts/run_pytest_safe.py (the 011e seam)"
        )

    def test_canonical_run_is_not_continue_on_error(self, workflow):
        """Guard against the canonical run being silently softened to non-blocking."""
        step = self._canonical_step(workflow)
        assert step.get("continue-on-error", False) is False
