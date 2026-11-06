"""WOT-2026-010m: barriers for the additive xdist pilot in quality-gates.yml.

The pilot consumes the 011e opt-in capability (--xdist-workers) in CI WITHOUT
making xdist the gate: it is non-blocking, and the canonical serial run must
stay serial. These barriers fail if the pilot disappears OR if the canonical
run accidentally adopts xdist.
"""

import copy
import re
import shlex
from pathlib import Path
from typing import Any

import pytest
import yaml


def get_repo_root() -> Path:
    return Path(__file__).parent.parent.parent


def load_yaml_file(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def assert_ruff_steps_are_readonly(workflow: dict[str, Any]) -> None:
    """Protect declared workflow invocations from accidental Ruff autofix.

    This does not cover indirection, external config files, or shell obfuscation.
    An ``echo`` or comment containing ``ruff``/``--fix`` may therefore false-red.
    """
    ruff_steps: list[tuple[str, list[str]]] = []
    for job_name, job in workflow.get("jobs", {}).items():
        for step in job.get("steps", []):
            run = step.get("run")
            if not isinstance(run, str):
                continue
            normalized = re.sub(r"[\"\\']", "", run)
            if not re.search(r"(?<![\w-])ruff(?![\w-])", normalized):
                continue
            assert not re.search(
                r"--(unsafe-)?fix(-only)?\b|--unsafe-fixes\b|--fix=", normalized
            ), f"el paso Ruff del job {job_name!r} contiene autofix: {run!r}"
            assert not re.search(
                r'fix\s*=\s*(true|"true")', normalized, re.IGNORECASE
            ), f"el paso Ruff del job {job_name!r} activa fix por --config: {run!r}"
            ruff_steps.append((job_name, shlex.split(run)))

    assert ruff_steps, "no se encontró ningún paso que invoque el token ruff"

    lint_steps = [
        tokens
        for _, tokens in ruff_steps
        if re.search(
            r"(?<![\w-])ruff(?![\w-])"
            r"(?:(?:\s+--[^\s]+)(?:\s+[^\s-][^\s]*)?)*"
            r"\s+check(?:\s|$)",
            " ".join(tokens),
            re.IGNORECASE,
        )
    ]
    assert len(lint_steps) == 1, (
        f"debe existir exactamente un paso de lint Ruff; encontrados {len(lint_steps)}"
    )
    assert lint_steps[0] == ["uv", "run", "ruff", "check", "."], (
        "el paso de lint Ruff debe ser exactamente 'uv run ruff check .'"
    )


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

    def test_ruff_lint_step_is_exactly_readonly(self, workflow):
        """The real workflow has only a read-only, exact Ruff lint step."""
        assert_ruff_steps_are_readonly(workflow)

    @pytest.mark.parametrize(
        ("case", "expected_reason"),
        [
            ("E1", "autofix"),
            ("E2", "autofix"),
            ("E4", "autofix"),
            ("E4b", "autofix"),
            ("python-fix", "autofix"),
            ("config-fix", "activa fix"),
            ("fix-equals", "autofix"),
            ("M1", "autofix"),
            ("M2", "autofix"),
            ("quoted-ruff", "autofix"),
            ("legit-format", None),
            ("second-lint", "exactamente un paso de lint"),
        ],
    )
    def test_ruff_workflow_rejects_autofix_and_duplicate_lint(
        self, workflow, case, expected_reason
    ):
        mutated = copy.deepcopy(workflow)
        if case == "E4":
            mutated["jobs"]["autofix"] = {
                "runs-on": "ubuntu-latest",
                "steps": [{"run": "uv run ruff check --fix ."}],
            }
        else:
            run = {
                "E1": "uv run ruff --config pyproject.toml check --fix .",
                "E2": "uv run ruff check --fix .",
                "E4b": "uv run ruff check --unsafe-fixes .",
                "python-fix": "python -m ruff check --fix .",
                "config-fix": "uv run ruff --config fix=true check .",
                "fix-equals": 'uv run ruff check --fix="true" .',
                "M1": "uv run .venv/bin/ruff check --fix .",
                "M2": "bash -c 'ruff check --fix .'",
                "quoted-ruff": 'uv run r"uff" check --fix .',
                "legit-format": "uv run ruff format --check src/",
                "second-lint": "uv run ruff --config x check",
            }[case]
            mutated["jobs"]["quality-gates"]["steps"].append({"run": run})

        if expected_reason is None:
            assert_ruff_steps_are_readonly(mutated)
        else:
            with pytest.raises(AssertionError, match=expected_reason):
                assert_ruff_steps_are_readonly(mutated)
