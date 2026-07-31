"""Tests for scripts/suite_regression_report.py (WOT-2026-022q).

The fixtures use the REAL measured run_history schema (219 real records,
2026-07-17): keys finished_at/level/args_mode/status/exit_code/passed/skipped/
failed_count/errors/duration_s/top_slowest/tested_commit_sha; top_slowest[i] =
{seconds, phase, nodeid}; level in {all, unit}; status in {finished, dry-run}.

The point of the ticket is a read-only WARN that NEVER blocks (exit 0 always)
and that actually DISCRIMINATES a real degradation from noise (no floor).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "suite_regression_report", _ROOT / "scripts" / "suite_regression_report.py"
)
csr = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(csr)


# --------------------------------------------------------------------- helpers
def _rec(
    duration_s: float | None,
    *,
    level: str = "all",
    status: str = "finished",
    failed_count: int = 0,
    errors: int = 0,
    slow: dict[str, float] | None = None,
    sha: str = "abc1234",
    args_mode: str = "default_discovery",
    passed: int = 4000,
) -> dict:
    """One run_history record in the REAL measured shape.

    WOT-2026-044o: ``args_mode`` defaults to ``default_discovery`` -- the value the
    runner REALLY writes for an unfiltered run. The previous default was
    ``"default"``, a value that appears in ZERO of the 498 measured records
    (the real domain is ``default_discovery`` | ``explicit_args``); an unreal
    fixture cannot exercise the filter this ticket adds.
    """
    top = [
        {"seconds": s, "phase": "call", "nodeid": nid}
        for nid, s in (slow or {}).items()
    ]
    return {
        "finished_at": "2026-07-17T00:00:00+00:00",
        "level": level,
        "args_mode": args_mode,
        "status": status,
        "exit_code": 1 if (failed_count or errors) else 0,
        "passed": passed,
        "skipped": 47,
        "failed_count": failed_count,
        "errors": errors,
        "duration_s": duration_s,
        "top_slowest": top,
        "tested_commit_sha": sha,
    }


def _write(path: Path, records: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


_STABLE = [_rec(250.0), _rec(252.0), _rec(248.0), _rec(251.0), _rec(249.0)]


# ------------------------------------------------------------- total duration
def test_degraded_total_duration_emits_warn(tmp_path: Path) -> None:
    """Median ~250, threshold 20% -> warn above 300. Current 360 (+44%) -> WARN."""
    hist = _write(tmp_path / "h.jsonl", [*_STABLE, _rec(360.0)])
    warns, _info = csr.analyze(csr._iter_records(hist), window=5, threshold_pct=20.0)
    assert any("[total]" in w for w in warns), warns


def test_stable_total_duration_is_silent(tmp_path: Path) -> None:
    """Current 255 (+2%) is far below the 300 threshold -> NO warn (no floor)."""
    hist = _write(tmp_path / "h.jsonl", [*_STABLE, _rec(255.0)])
    warns, _info = csr.analyze(csr._iter_records(hist), window=5, threshold_pct=20.0)
    assert not any("[total]" in w for w in warns), warns


# ----------------------------------------------------------------- per nodeid
def test_degraded_nodeid_emits_warn(tmp_path: Path) -> None:
    """One test's median ~5.0s; current 8.0s (+60%) -> per-test WARN naming it."""
    slow_hist = [_rec(250.0, slow={"tests/x.py::t_slow": s}) for s in (5.0, 5.1, 4.9)]
    cur = _rec(250.0, slow={"tests/x.py::t_slow": 8.0})
    hist = _write(tmp_path / "h.jsonl", [*slow_hist, cur])
    warns, _info = csr.analyze(csr._iter_records(hist), window=5, threshold_pct=20.0)
    assert any("t_slow" in w and "[test]" in w for w in warns), warns


def test_stable_nodeid_is_silent(tmp_path: Path) -> None:
    slow_hist = [_rec(250.0, slow={"tests/x.py::t_slow": s}) for s in (5.0, 5.1, 4.9)]
    cur = _rec(250.0, slow={"tests/x.py::t_slow": 5.2})
    hist = _write(tmp_path / "h.jsonl", [*slow_hist, cur])
    warns, _info = csr.analyze(csr._iter_records(hist), window=5, threshold_pct=20.0)
    assert not warns, warns


# ------------------------------------------------------------- never blocks
def test_missing_file_exits_zero_no_crash(tmp_path: Path) -> None:
    assert csr.main(["--history", str(tmp_path / "nope.jsonl")]) == 0


def test_corrupt_line_is_skipped_not_crash(tmp_path: Path) -> None:
    p = tmp_path / "h.jsonl"
    p.write_text(
        json.dumps(_STABLE[0]) + "\n{ this is not json\n" + json.dumps(_rec(360.0)),
        encoding="utf-8",
    )
    recs = csr._iter_records(p)
    assert len(recs) == 2  # the corrupt middle line dropped, no raise
    assert csr.main(["--history", str(p)]) == 0


def test_dry_run_current_is_ignored(tmp_path: Path) -> None:
    """A dry-run last record must NOT be compared (not real timing)."""
    hist = _write(tmp_path / "h.jsonl", [*_STABLE, _rec(999.0, status="dry-run")])
    warns, info = csr.analyze(csr._iter_records(hist), window=5, threshold_pct=20.0)
    assert not warns
    assert "dry-run" in info


def test_failed_current_suppresses_warn(tmp_path: Path) -> None:
    """A FAILED current run (huge duration) must NOT raise a perf WARN."""
    hist = _write(tmp_path / "h.jsonl", [*_STABLE, _rec(900.0, failed_count=3)])
    warns, info = csr.analyze(csr._iter_records(hist), window=5, threshold_pct=20.0)
    assert not warns, warns
    assert "SUPRIMIDO" in info or "FALLO" in info


def test_failed_history_excluded_from_median(tmp_path: Path) -> None:
    """Failed runs poison the median; they must be excluded from the baseline."""
    # If the failed 900s run were counted, the median would jump and hide a real
    # regression. Green median stays ~250 -> current 360 still flags.
    poisoned = [*_STABLE, _rec(900.0, failed_count=5), _rec(360.0)]
    hist = _write(tmp_path / "h.jsonl", poisoned)
    warns, _info = csr.analyze(csr._iter_records(hist), window=5, threshold_pct=20.0)
    assert any("[total]" in w for w in warns), warns


def test_insufficient_history_is_informative(tmp_path: Path) -> None:
    hist = _write(tmp_path / "h.jsonl", [_rec(250.0), _rec(360.0)])  # only 1 prior
    warns, info = csr.analyze(csr._iter_records(hist), window=5, threshold_pct=20.0)
    assert not warns
    assert "insuficiente" in info


def test_unit_level_records_ignored(tmp_path: Path) -> None:
    """Only level=all is compared; unit rows must not enter the baseline."""
    mixed = [_rec(250.0, level="unit") for _ in range(5)] + [*_STABLE, _rec(360.0)]
    hist = _write(tmp_path / "h.jsonl", mixed)
    warns, _info = csr.analyze(csr._iter_records(hist), window=5, threshold_pct=20.0)
    assert any("[total]" in w for w in warns)


def test_main_always_exits_zero_even_with_warn(tmp_path: Path) -> None:
    """The invariant: WARN present, but the process still exits 0 (never blocks)."""
    hist = _write(tmp_path / "h.jsonl", [*_STABLE, _rec(360.0)])
    assert csr.main(["--history", str(hist)]) == 0


# ------------------------------------- WOT-2026-044o: only COMPLETE runs count
#
# A run launched with a filter (``-k something``) executes a SUBSET of the suite
# but is recorded with ``level=all`` just like a complete one. Measured on the
# real history (498 records, 2026-07-31): ``args_mode`` separates the two
# populations -- ``default_discovery`` n=304 passed median 4618, vs
# ``explicit_args`` n=25 passed median 1. Reading "the last level=all row"
# without that filter can land on a filtered run and declare the suite within
# budget while it is not.
#
# DECLARED LIMIT (measured, not assumed): ``args_mode`` is an IMPERFECT PROXY for
# "complete". 1 of those 25 ``explicit_args`` rows was actually complete
# (passed=4396, duration 303.58s) -- an explicit invocation of the whole suite.
# The filter discards it. The bias is SAFE BY CONSTRUCTION: it drops complete
# runs, never accepts filtered ones, so it can make the trigger stricter but can
# NEVER manufacture a false green.


def test_filtered_current_run_no_longer_hides_a_regression(tmp_path: Path) -> None:
    """MUTATION: the exact false green this ticket closes.

    The last ``level=all`` row is a FILTERED run that took 27s. Before the fix the
    comparison anchored on it and stayed silent (27s < median -> no regression).
    After the fix that row is not eligible as CURRENT, the last COMPLETE run
    (353s vs a ~250s median) is, and the regression surfaces.

    The filtered row is the ONLY thing deciding the verdict: remove it and the
    outcome is identical (see the negative control below).
    """
    records = [*_STABLE, _rec(353.0), _rec(27.0, args_mode="explicit_args", passed=1)]
    hist = _write(tmp_path / "h.jsonl", records)
    warns, info = csr.analyze(csr._iter_records(hist), window=5, threshold_pct=20.0)
    assert any("[total]" in w for w in warns), (
        f"the filtered 27s run still masks the 353s regression; info={info!r}"
    )


def test_filtered_runs_excluded_from_the_median(tmp_path: Path) -> None:
    """The OTHER end: a filtered run must not pollute the baseline either.

    Both ends of the comparison use the same eligibility rule; filtering only one
    of them leaves the bug alive through the other half.
    """
    noisy = [_rec(5.0, args_mode="explicit_args", passed=1) for _ in range(4)]
    hist = _write(tmp_path / "h.jsonl", [*_STABLE, *noisy, _rec(360.0)])
    warns, _info = csr.analyze(csr._iter_records(hist), window=5, threshold_pct=20.0)
    assert any("[total]" in w for w in warns), (
        "median got polluted by 5s filtered runs -> 360s no longer looks degraded"
    )


def test_negative_control_all_complete_runs_unchanged(tmp_path: Path) -> None:
    """NEGATIVE CONTROL: with no filtered rows the filter is the identity.

    Distinguishes "I fixed the selection" from "I changed the computation": on a
    history where every row is complete, the verdict must be exactly what it was
    before the ticket -- WARN for a degraded run, silence for a stable one.
    """
    degraded = _write(tmp_path / "d.jsonl", [*_STABLE, _rec(360.0)])
    warns, _info = csr.analyze(
        csr._iter_records(degraded), window=5, threshold_pct=20.0
    )
    assert any("[total]" in w for w in warns)

    stable = _write(tmp_path / "s.jsonl", [*_STABLE, _rec(251.0)])
    warns, _info = csr.analyze(csr._iter_records(stable), window=5, threshold_pct=20.0)
    assert not warns


def test_no_level_all_rows_at_all_is_distinct_from_no_complete_ones(
    tmp_path: Path,
) -> None:
    """A history with NO ``level=all`` row is its own case, not "no complete runs".

    Gap found by the closing adversarial pass (lens mimo) and confirmed by probe:
    the branch behaved correctly but no test reached it. The two emptiness cases
    must stay distinguishable -- "nothing to compare" (no full-suite run was ever
    recorded) is a different operational fact from "rows exist but all of them are
    filtered", and collapsing them would hide which one you are looking at.
    """
    hist = _write(tmp_path / "h.jsonl", [_rec(10.0, level="unit") for _ in range(4)])
    warns, info = csr.analyze(csr._iter_records(hist), window=5, threshold_pct=20.0)
    assert not warns
    assert "sin corridas level=all" in info, info
    assert "COMPLETAS" not in info, "collapsed into the no-complete-runs message"


def test_no_complete_runs_says_so_instead_of_falling_back(tmp_path: Path) -> None:
    """FALLBACK: no complete run -> say it, never silently use the old criterion.

    A silent fallback to "last level=all" would reintroduce the very defect this
    ticket closes, so the absence of eligible data must be NAMED.
    """
    only_filtered = [_rec(27.0, args_mode="explicit_args", passed=1) for _ in range(6)]
    hist = _write(tmp_path / "h.jsonl", only_filtered)
    warns, info = csr.analyze(csr._iter_records(hist), window=5, threshold_pct=20.0)
    assert not warns
    assert "completa" in info.lower(), f"the reason is not named; info={info!r}"


def test_report_publishes_its_denominator(tmp_path: Path) -> None:
    """DENOMINATOR (WOT-2026-043l): say how many rows were compared and dropped.

    A report that does not publish its denominator is indistinguishable from one
    that looked at nothing.
    """
    records = [*_STABLE, _rec(27.0, args_mode="explicit_args", passed=1), _rec(360.0)]
    hist = _write(tmp_path / "h.jsonl", records)
    _warns, info = csr.analyze(csr._iter_records(hist), window=5, threshold_pct=20.0)
    assert "1 filtrada" in info, f"discarded count not published; info={info!r}"


def test_close_prompt_states_the_complete_run_criterion() -> None:
    """The prose reader must not silently keep the old criterion.

    ``prompts/orchestrator_session_close_full_audit.md`` fixes the trigger in
    prose; if the code filters by ``args_mode`` and the prompt still says "the
    last level=all row", the next auditor has to rediscover this by measuring.
    This asserts the prompt NAMES the field -- not semantic parity between prose
    and code (that has no oracle), just that the prose cannot stay stale unnoticed.
    """
    prompt = _ROOT / "prompts" / "orchestrator_session_close_full_audit.md"
    text = prompt.read_text(encoding="utf-8")
    assert "args_mode" in text or "default_discovery" in text, (
        "the close prompt still states the trigger without the complete-run "
        "criterion (WOT-2026-044o)"
    )
