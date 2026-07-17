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
) -> dict:
    """One run_history record in the REAL measured shape."""
    top = [
        {"seconds": s, "phase": "call", "nodeid": nid}
        for nid, s in (slow or {}).items()
    ]
    return {
        "finished_at": "2026-07-17T00:00:00+00:00",
        "level": level,
        "args_mode": "default",
        "status": status,
        "exit_code": 1 if (failed_count or errors) else 0,
        "passed": 4000,
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
