"""Focal tests for the append-only per-tick trace CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "flight" / "tick_trace.py"
TS_A = "2026-11-06T12:30:01+01:00"
TS_B = "2026-11-06T12:30:02+01:00"


def run_trace(ops_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run the versioned script through its production CLI."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--ops-dir", str(ops_dir), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def run_direct(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run the CLI without injecting the mandatory ops-dir argument."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def read_lines(ops_dir: Path) -> list[dict[str, object]]:
    """Parse every physical JSONL line from the trace."""
    raw = (ops_dir / "tick_trace.jsonl").read_bytes()
    assert raw.endswith(b"\n")
    return [json.loads(line) for line in raw.decode().splitlines()]


def measured_args(ts: str = TS_A) -> tuple[str, ...]:
    """Return a complete, valid tick invocation."""
    return (
        "--coordinator",
        "CO-48",
        "--roster-sha12",
        "0123456789ab",
        "--guard-rc",
        "0",
        "--quota-rc",
        "0",
        "--quota-summary",
        "QUOTA OK",
        "--ts",
        ts,
    )


def test_append_writes_one_parseable_line_per_call(tmp_path: Path) -> None:
    """Two successful calls produce two complete JSONL records."""
    first = run_trace(tmp_path, *measured_args())
    second = run_trace(tmp_path, *measured_args(TS_B))

    assert first.returncode == 0, first.stdout + first.stderr
    assert second.returncode == 0, second.stdout + second.stderr
    records = read_lines(tmp_path)
    assert [record["ts"] for record in records] == [TS_A, TS_B]
    assert all(record["v"] == 1 for record in records)
    assert all(record["unmeasured"] == {} for record in records)


def test_missing_values_are_null_with_reasons_and_degraded_rc(tmp_path: Path) -> None:
    """Omitted measurements are explicit nulls, never invented zeroes."""
    result = run_trace(tmp_path, "--ts", TS_A)

    assert result.returncode == 1, result.stdout + result.stderr
    record = read_lines(tmp_path)[0]
    for field in (
        "coordinator",
        "roster_sha12",
        "guard_rc",
        "quota_rc",
        "quota_summary",
    ):
        assert record[field] is None
        assert record["unmeasured"][field] == "not_provided"


def test_custom_unmeasured_reason_is_preserved(tmp_path: Path) -> None:
    """The caller can explain a missing measurement without changing its null value."""
    result = run_trace(
        tmp_path,
        "--coordinator",
        "CO-48",
        "--unmeasured",
        "quota_rc=monitor stale",
        "--ts",
        TS_A,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    record = read_lines(tmp_path)[0]
    assert record["quota_rc"] is None
    assert record["unmeasured"]["quota_rc"] == "monitor stale"


def test_existing_missing_lf_is_repaired_without_changing_prefix(
    tmp_path: Path,
) -> None:
    """A legacy unterminated record is preserved and separated before append."""
    trace = tmp_path / "tick_trace.jsonl"
    prefix = b'{"legacy":true}'
    trace.write_bytes(prefix)

    result = run_trace(tmp_path, *measured_args())

    assert result.returncode == 0, result.stdout + result.stderr
    raw = trace.read_bytes()
    assert raw.startswith(prefix + b"\n")
    assert len(raw.splitlines()) == 2
    assert json.loads(raw.splitlines()[1])["ts"] == TS_A


def test_quota_summary_is_truncated_to_200_chars(tmp_path: Path) -> None:
    """Long quota text remains one bounded JSONL line."""
    summary = "x" * 250
    result = run_trace(
        tmp_path,
        *measured_args(),
        "--quota-summary",
        summary,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    record = read_lines(tmp_path)[0]
    assert record["quota_summary"] == "x" * 200
    assert len((tmp_path / "tick_trace.jsonl").read_bytes().splitlines()) == 1


def test_missing_ops_dir_is_rc2_and_not_created(tmp_path: Path) -> None:
    """The mandatory output directory is never created implicitly."""
    missing = tmp_path / "does-not-exist"

    result = run_trace(missing, *measured_args())

    assert result.returncode == 2
    assert not missing.exists()
    assert "TICK_TRACE error" in result.stdout
    assert "Traceback" not in result.stdout + result.stderr


def test_invalid_value_is_rc2_and_leaves_existing_file_intact(tmp_path: Path) -> None:
    """Invalid values fail before opening or changing the append-only file."""
    first = run_trace(tmp_path, *measured_args())
    before = (tmp_path / "tick_trace.jsonl").read_bytes()

    result = run_trace(tmp_path, "--roster-sha12", "not-a-sha", "--ts", TS_B)

    assert first.returncode == 0
    assert result.returncode == 2
    assert (tmp_path / "tick_trace.jsonl").read_bytes() == before
    assert "TICK_TRACE error" in result.stdout
    assert "Traceback" not in result.stdout + result.stderr


def test_invalid_return_code_is_rc2_and_does_not_create_trace(tmp_path: Path) -> None:
    """Non-integer guard data is rejected before the first write."""
    result = run_trace(tmp_path, "--guard-rc", "zero", "--ts", TS_A)

    assert result.returncode == 2
    assert not (tmp_path / "tick_trace.jsonl").exists()
    assert "TICK_TRACE error" in result.stdout


def test_relative_ops_dir_is_rejected_without_writing(tmp_path: Path) -> None:
    """The output directory must be absolute even when a relative one exists."""
    relative = tmp_path / "relative-ops"
    relative.mkdir()

    result = run_direct(
        "--ops-dir",
        relative.name,
        *measured_args(),
        cwd=tmp_path,
    )

    assert result.returncode == 2
    assert not (relative / "tick_trace.jsonl").exists()
    assert "TICK_TRACE error" in result.stdout


def test_unknown_option_and_missing_ops_dir_are_named_errors(tmp_path: Path) -> None:
    """Argparse failures are converted to the heartbeat's named error output."""
    for args in (("--unknown",), tuple()):
        result = run_direct(*args, cwd=tmp_path)
        assert result.returncode == 2
        assert "TICK_TRACE error" in result.stdout
        assert "Traceback" not in result.stdout + result.stderr


def test_invalid_unmeasured_declarations_are_rejected(tmp_path: Path) -> None:
    """Malformed, unknown, and empty-reason declarations write nothing."""
    for declaration in ("guard_rc", "invented=x", "guard_rc="):
        result = run_trace(
            tmp_path,
            "--unmeasured",
            declaration,
            "--ts",
            TS_A,
        )
        assert result.returncode == 2
        assert not (tmp_path / "tick_trace.jsonl").exists()
        assert "TICK_TRACE error" in result.stdout


def test_timestamp_requires_offset_and_seconds(tmp_path: Path) -> None:
    """Naive, date-only, and minute-only timestamps are invalid."""
    for timestamp in (
        "2026-11-06T12:30:01",
        "2026-11-06",
        "2026-11-06T12:30+01:00",
    ):
        result = run_trace(tmp_path, "--ts", timestamp)
        assert result.returncode == 2
        assert not (tmp_path / "tick_trace.jsonl").exists()
        assert "TICK_TRACE error" in result.stdout


def test_trace_path_as_directory_is_rc2(tmp_path: Path) -> None:
    """A directory at the fixed trace path is never opened for append."""
    (tmp_path / "tick_trace.jsonl").mkdir()

    result = run_trace(tmp_path, *measured_args())

    assert result.returncode == 2
    assert "TICK_TRACE error" in result.stdout
    assert "trace path is not a file" in result.stdout
    assert "Traceback" not in result.stdout + result.stderr
