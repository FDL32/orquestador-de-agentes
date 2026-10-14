"""Tests for closeout_steps.observations.step_session_observations (WOT-2026-042r).

The step used to translate ANY ``returncode == 0`` of session_close_observations.py
into ``status="PASS"`` with the static detail "Observations processed for <tid>",
ignoring the producer protocol line ``OBSERVATIONS appended=<n> candidates=<m>
ticket=<tid>`` (WOT-2026-042r eje (i)): a session producing zero observations of
the ticket was reported as silent success.

The fakes follow the real fixture pattern of tests/unit/test_closeout_steps_archival.py
(run_script_fn returning an object with returncode/stdout/stderr, matching
support.run_script which uses capture_output=True, text=True).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from scripts.closeout_steps.observations import step_session_observations
from scripts.session_closeout import StepResult


def fake_run_script_fn(returncode: int, stdout: str):
    """Build a run_script_fn fake with the given returncode and stdout."""

    def run_script_fn(script_name, args, project_root, timeout=60):
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")

    return run_script_fn


def _run(
    run_script_fn,
    ticket_ids=None,
    close_timestamps=None,
):
    if ticket_ids is None:
        ticket_ids = ["WOT-2026-999a"]
    if close_timestamps is None:
        close_timestamps = {"WOT-2026-999a": "2026-10-14T00:00:00Z"}
    return step_session_observations(
        Path("unused"),
        False,
        ticket_ids=ticket_ids,
        close_timestamps=close_timestamps,
        run_script_fn=run_script_fn,
        process_diagnostic_fn=lambda r, limit=300: r.stderr,
        step_result_cls=StepResult,
    )


def test_step_observations_skip_when_nothing_written() -> None:
    """appended=0, rc=0: SKIP with explicit reason, NEVER PASS.

    REGRESSION (WOT-2026-042r eje (i)): before the fix this returned PASS with
    "Observations processed for WOT-2026-999a" even though zero observations
    of that ticket were written.
    """
    results = _run(
        fake_run_script_fn(
            0,
            "OBSERVATIONS appended=0 candidates=0 ticket=WOT-2026-999a\n",
        )
    )
    assert len(results) == 1
    assert results[0].status == "SKIP"
    assert "WOT-2026-999a" in results[0].detail
    assert "appended=0" in results[0].detail or "candidates=0" in results[0].detail


def test_step_observations_pass_when_written() -> None:
    """appended >= 1, rc=0: PASS with count.

    POSITIVE CONTROL: without this assert, a wrong implementation like
    ``if appended == 0: WARN`` (which ignores positive counts) would pass
    the skip test and emit false WARNs for every healthy close in production.
    """
    results = _run(
        fake_run_script_fn(
            0,
            "OBSERVATIONS appended=2 candidates=3 ticket=WOT-2026-999a\n",
        )
    )
    assert len(results) == 1
    assert results[0].status == "PASS"
    assert "WOT-2026-999a" in results[0].detail
    assert "2 written" in results[0].detail


def test_step_observations_warn_on_missing_protocol() -> None:
    """stdout without OBSERVATIONS line: WARN, NEVER PASS.

    A legacy producer (or corrupted stdout) must never resolve to PASS.
    """
    results = _run(
        fake_run_script_fn(
            0,
            "legacy producer output\n",
        )
    )
    assert len(results) == 1
    assert results[0].status == "WARN"


def test_step_observations_warn_on_nonzero_rc() -> None:
    """Non-zero return code: WARN (not PASS, not SKIP)."""
    results = _run(
        fake_run_script_fn(
            1,
            "OBSERVATIONS appended=0 candidates=0 ticket=WOT-2026-999a\n",
        )
    )
    assert len(results) == 1
    assert results[0].status == "WARN"
