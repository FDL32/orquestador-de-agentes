"""Tests for scripts/check_audit_skips.py (WOT-2026-074x DoD b).

Red/Green contract: a sealed run with skips MUST fail the close when the
motives are not recorded in the seal log (runner without ``-rs``), when a skip
carries no explicit motive (``pytest.skip()`` prints the literal ``Skipped``),
or when the declaration for the sealed run is missing/stale/partial. It MUST
pass when the log records every motive and the declaration matches the run.
"""

from __future__ import annotations

import json
from pathlib import Path


try:
    from scripts.check_audit_skips import parse_skips, run_check
except ImportError:  # pragma: no cover - direct script execution
    from check_audit_skips import parse_skips, run_check

SEAL_TS = "2026-10-14T00:00:00+00:00"


def _safe_dir(root: Path) -> Path:
    path = root / ".agent" / "runtime" / "pytest-safe"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_seal(safe: Path, skipped: int | None) -> None:
    (safe / "last-run.json").write_text(
        json.dumps({"started_at": SEAL_TS, "skipped": skipped, "status": "finished"}),
        encoding="utf-8",
    )


def _write_log(
    safe: Path,
    *,
    sections: int = 2,
    summary_skipped: int | None = 2,
    default_reason: bool = False,
) -> None:
    lines = []
    for index in range(sections):
        reason = "Skipped" if default_reason else f"surface missing: demo {index}"
        lines.append(f"SKIPPED [1] tests/test_demo.py:{10 + index}: {reason}")
    if summary_skipped is not None:
        lines.append(f"1 passed, {summary_skipped} skipped in 0.01s")
    (safe / "last-run.log").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_declaration(
    safe: Path,
    classes: dict,
    *,
    started_at: str = SEAL_TS,
    notes: str = "detalle de la declaracion",
) -> None:
    payload = {
        "seal_started_at": started_at,
        "declared_at": "2026-10-14T00:01:00+00:00",
        "declared_by": "test",
        "classes": classes,
        "notes": notes,
    }
    (safe / "skip-declarations.json").write_text(json.dumps(payload), encoding="utf-8")


def test_parse_skips_extracts_count_where_and_motive() -> None:
    entries, total = parse_skips(
        "SKIPPED [2] tests/test_x.py:9: parametrized by platform\n"
        "SKIPPED [1] tests/test_y.py:4: Skipped\n"
    )
    assert total == 3
    assert entries[0]["count"] == 2
    assert entries[0]["where"] == "tests/test_x.py:9"
    assert entries[0]["motive_present"] is True
    assert entries[1]["motive_present"] is False


def test_no_seal_is_named_skip(tmp_path: Path) -> None:
    report = run_check(tmp_path)
    assert report["verdict"] == "skip"


def test_sealed_run_with_motives_and_declaration_passes(tmp_path: Path) -> None:
    safe = _safe_dir(tmp_path)
    _write_seal(safe, 2)
    _write_log(safe)
    _write_declaration(safe, {"platform": 1, "surface-missing": 1, "other": 0})
    report = run_check(tmp_path)
    assert report["verdict"] == "pass"
    assert (safe / "skip-report.json").is_file()


def test_skips_without_declaration_fail(tmp_path: Path) -> None:
    safe = _safe_dir(tmp_path)
    _write_seal(safe, 2)
    _write_log(safe)
    report = run_check(tmp_path)
    assert report["verdict"] == "fail"
    assert any("falta skip-declarations.json" in f for f in report["findings"])


def test_motives_not_recorded_in_log_fail(tmp_path: Path) -> None:
    safe = _safe_dir(tmp_path)
    _write_seal(safe, 2)
    (safe / "last-run.log").write_text(
        "1 passed, 2 skipped in 0.01s\n", encoding="utf-8"
    )
    _write_declaration(safe, {"platform": 2})
    report = run_check(tmp_path)
    assert report["verdict"] == "fail"
    assert any("no llega al log" in f for f in report["findings"])


def test_default_reason_counts_as_missing_motive(tmp_path: Path) -> None:
    safe = _safe_dir(tmp_path)
    _write_seal(safe, 2)
    _write_log(safe, default_reason=True)
    _write_declaration(safe, {"platform": 2})
    report = run_check(tmp_path)
    assert report["verdict"] == "fail"
    assert any("sin motivo explicito" in f for f in report["findings"])


def test_seal_undercount_fails(tmp_path: Path) -> None:
    safe = _safe_dir(tmp_path)
    _write_seal(safe, 0)
    _write_log(safe)
    report = run_check(tmp_path)
    assert report["verdict"] == "fail"
    assert any("no cuenta la perdida" in f for f in report["findings"])


def test_stale_declaration_fails(tmp_path: Path) -> None:
    safe = _safe_dir(tmp_path)
    _write_seal(safe, 2)
    _write_log(safe)
    _write_declaration(safe, {"platform": 2}, started_at="2026-01-01T00:00:00+00:00")
    report = run_check(tmp_path)
    assert report["verdict"] == "fail"
    assert any("no corresponde a este sello" in f for f in report["findings"])


def test_declaration_sum_mismatch_fails(tmp_path: Path) -> None:
    safe = _safe_dir(tmp_path)
    _write_seal(safe, 2)
    _write_log(safe)
    _write_declaration(safe, {"platform": 3})
    report = run_check(tmp_path)
    assert report["verdict"] == "fail"
    assert any("suma 3" in f for f in report["findings"])


def test_unknown_class_fails(tmp_path: Path) -> None:
    safe = _safe_dir(tmp_path)
    _write_seal(safe, 2)
    _write_log(safe)
    _write_declaration(safe, {"flaky": 2})
    report = run_check(tmp_path)
    assert report["verdict"] == "fail"
    assert any("vocabulario cerrado" in f for f in report["findings"])


def test_surface_missing_requires_notes(tmp_path: Path) -> None:
    safe = _safe_dir(tmp_path)
    _write_seal(safe, 2)
    _write_log(safe)
    _write_declaration(safe, {"surface-missing": 2}, notes="")
    report = run_check(tmp_path)
    assert report["verdict"] == "fail"
    assert any("notes" in f for f in report["findings"])


def test_zero_skips_pass_without_declaration(tmp_path: Path) -> None:
    safe = _safe_dir(tmp_path)
    _write_seal(safe, 0)
    (safe / "last-run.log").write_text("5 passed in 1.00s\n", encoding="utf-8")
    report = run_check(tmp_path)
    assert report["verdict"] == "pass"


def test_null_skipped_passes_with_clean_log(tmp_path: Path) -> None:
    safe = _safe_dir(tmp_path)
    _write_seal(safe, None)
    (safe / "last-run.log").write_text("5 passed in 1.00s\n", encoding="utf-8")
    report = run_check(tmp_path)
    assert report["verdict"] == "pass"


def test_seal_log_divergence_fails(tmp_path: Path) -> None:
    safe = _safe_dir(tmp_path)
    _write_seal(safe, 2)
    _write_log(safe, sections=1, summary_skipped=1)
    _write_declaration(safe, {"platform": 2})
    report = run_check(tmp_path)
    assert report["verdict"] == "fail"
    assert any("registra" in f for f in report["findings"])


def test_prepush_registers_audit_skips_check() -> None:
    """The closeout obligation is a BARRIER only if prepush actually CALLS the
    check (the static import alone is not enough)."""
    import inspect

    try:
        from scripts import prepush_check
    except ImportError:  # pragma: no cover - direct script execution
        import prepush_check  # type: ignore[no-redef]

    source = inspect.getsource(prepush_check.run_preflight_check)
    assert "run_audit_skips_check(project_root)" in source
