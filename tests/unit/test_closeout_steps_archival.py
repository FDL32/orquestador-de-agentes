"""Tests for closeout_steps.archival.step_archive_execution_log (WOT-2026-068c).

The step used to translate ANY ``returncode == 0`` of archive_execution_log.py
into ``status="PASS"`` with the static detail ``"Execution log archived"``,
ignoring the producer protocol ``COUNTS archived=N recognized=N present=N``
(WOT-2026-068d): an archiver that runs, does not fail, and recognizes zero
headers (present > 0, recognized == 0) was reported as silent success.

The fakes follow the real fixture pattern of tests/test_session_closeout.py
(run_script_fn returning an object with returncode/stdout/stderr, matching
support.run_script which uses capture_output=True, text=True).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from scripts.closeout_steps.archival import step_archive_execution_log
from scripts.session_closeout import StepResult


def fake_run_script_fn(returncode: int, stdout: str):
    """Build a run_script_fn fake with the given returncode and stdout."""

    def run_script_fn(script_name, args, project_root, timeout=60):
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")

    return run_script_fn


def _run(run_script_fn) -> StepResult:
    return step_archive_execution_log(
        Path("unused"),
        False,
        run_script_fn=run_script_fn,
        step_result_cls=StepResult,
    )


def test_step_archive_execution_log_warn_on_unrecognized_headers() -> None:
    """present=23, recognized=0 with rc=0: WARN, never a silent PASS.

    REGRESSION (WOT-2026-068c): before the fix this returned PASS with the
    static detail, hiding the real denominator.
    """
    result = _run(
        fake_run_script_fn(
            0,
            "COUNTS archived=0 recognized=0 present=23\n"
            "SKIPPED []\n"
            "CONTENT state=nonempty\n",
        )
    )
    assert result.status == "WARN"
    assert "archived=0" in result.detail
    assert "recognized=0" in result.detail
    assert "present=23" in result.detail


def test_step_archive_execution_log_pass_on_empty_log() -> None:
    """present=0 (nothing to archive): PASS -- idempotency is legitimate."""
    result = _run(
        fake_run_script_fn(
            0,
            "COUNTS archived=0 recognized=0 present=0\n"
            "SKIPPED []\n"
            "CONTENT state=empty\n",
        )
    )
    assert result.status == "PASS"
    assert "archived=0" in result.detail
    assert "recognized=0" in result.detail
    assert "present=0" in result.detail


def test_step_archive_execution_log_pass_on_recognized_headers() -> None:
    """present=5, recognized=5 (healthy case): PASS.

    POSITIVE CONTROL: without this assert, a wrong implementation like
    ``if present > 0: WARN`` (which ignores `recognized` entirely) would pass
    the other four tests and emit false WARNs for every healthy log in
    production.
    """
    result = _run(
        fake_run_script_fn(
            0,
            "COUNTS archived=5 recognized=5 present=5\n"
            "SKIPPED []\n"
            "CONTENT state=nonempty\n",
        )
    )
    assert result.status == "PASS"
    assert "archived=5" in result.detail
    assert "recognized=5" in result.detail
    assert "present=5" in result.detail


def test_step_archive_execution_log_fallback_missing_protocol() -> None:
    """stdout without a COUNTS line: degrade to the returncode criterion."""
    result = _run(fake_run_script_fn(0, "legacy producer output\n"))
    assert result.status == "PASS"
    assert result.detail == "Execution log archived"


def test_step_archive_execution_log_fallback_malformed_counts_line() -> None:
    """A COUNTS line that does not match the exact regex is the SAME as an
    absent protocol: degrade to returncode, never raise.

    ``re.match`` returns None for a missing `present` field or a non-numeric
    value; the consumer must not assume `match` always exists.
    """
    malformed_lines = (
        "COUNTS archived=0 recognized=0\n",
        "COUNTS archived=abc recognized=0 present=0\n",
    )
    for stdout in malformed_lines:
        result = _run(fake_run_script_fn(0, stdout))
        assert result.status == "PASS", stdout
        assert result.detail == "Execution log archived", stdout
