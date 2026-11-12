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
    assert all(record["v"] == 2 for record in records)
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


def test_impossible_timestamp_is_rejected_before_writing(tmp_path: Path) -> None:
    """Calendar-invalid timestamps fail before the append."""
    result = run_trace(tmp_path, "--ts", "2026-13-45T25:61:61+01:00")

    assert result.returncode == 2
    assert not (tmp_path / "tick_trace.jsonl").exists()
    assert "TICK_TRACE error" in result.stdout


def test_nonzero_guard_and_quota_rcs_are_recorded_as_data(tmp_path: Path) -> None:
    """Nonzero guard and quota measurements do not degrade a complete record."""
    result = run_trace(
        tmp_path,
        *measured_args(),
        "--guard-rc",
        "1",
        "--quota-rc",
        "3",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    record = read_lines(tmp_path)[0]
    assert record["guard_rc"] == 1
    assert record["quota_rc"] == 3


def test_ops_dir_pointing_to_file_is_rc2(tmp_path: Path) -> None:
    """An existing file cannot serve as the operation directory."""
    ops_file = tmp_path / "ops-file"
    ops_file.write_text("not a directory", encoding="utf-8")

    result = run_trace(ops_file, *measured_args())

    assert result.returncode == 2
    assert "TICK_TRACE error" in result.stdout


def test_non_integer_quota_rc_is_rejected_without_writing(tmp_path: Path) -> None:
    """A non-integer quota measurement fails before the append."""
    result = run_trace(tmp_path, "--quota-rc", "three", "--ts", TS_A)

    assert result.returncode == 2
    assert not (tmp_path / "tick_trace.jsonl").exists()
    assert "TICK_TRACE error" in result.stdout


def test_timestamp_accepts_z_fraction_and_space_forms(tmp_path: Path) -> None:
    """Valid Z, fractional, and space-separated timestamps are preserved."""
    timestamps = (
        "2026-11-06T12:30:01Z",
        "2026-11-06T12:30:01.123+01:00",
        "2026-11-06 12:30:01+01:00",
    )
    for timestamp in timestamps:
        result = run_trace(tmp_path, *measured_args(timestamp))
        assert result.returncode == 0, result.stdout + result.stderr

    assert [record["ts"] for record in read_lines(tmp_path)] == list(timestamps)


def test_empty_quota_summary_is_measured(tmp_path: Path) -> None:
    """An explicitly empty quota summary is recorded with rc 0."""
    result = run_trace(
        tmp_path,
        *measured_args(),
        "--quota-summary",
        "",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    record = read_lines(tmp_path)[0]
    assert record["quota_summary"] == ""
    assert record["unmeasured"] == {}


def test_offset_minute_range_is_rejected_or_preserved(tmp_path: Path) -> None:
    """Offset minutes stay in 00..59 while valid edge offsets are preserved."""
    invalid = run_trace(tmp_path, "--ts", "2026-11-06T12:30:01+00:60")
    assert invalid.returncode == 2
    assert not (tmp_path / "tick_trace.jsonl").exists()

    for timestamp in (
        "2026-11-06T12:30:01+23:59",
        "2026-11-06T12:30:01-05:30",
    ):
        result = run_trace(tmp_path, *measured_args(timestamp))
        assert result.returncode == 0, result.stdout + result.stderr
    assert [record["ts"] for record in read_lines(tmp_path)] == [
        "2026-11-06T12:30:01+23:59",
        "2026-11-06T12:30:01-05:30",
    ]


def test_error_output_escapes_line_breaks(tmp_path: Path) -> None:
    """An interpolated invalid value containing LF stays one stdout line."""
    result = run_trace(
        tmp_path,
        "--unmeasured",
        "invented\nline",
        "--ts",
        TS_A,
    )

    assert result.returncode == 2
    assert result.stdout.count("\n") == 1
    assert r"invented\nline" in result.stdout


def test_duplicate_unmeasured_reason_uses_last_value(tmp_path: Path) -> None:
    """Repeated declarations are characterized as last-value-wins."""
    result = run_trace(
        tmp_path,
        "--unmeasured",
        "guard_rc=first",
        "--unmeasured",
        "guard_rc=last",
        "--ts",
        TS_A,
    )

    assert result.returncode == 1
    assert read_lines(tmp_path)[0]["unmeasured"]["guard_rc"] == "last"


def test_negative_guard_rc_is_recorded_as_data(tmp_path: Path) -> None:
    """A negative guard return code remains data and does not degrade the tick."""
    result = run_trace(tmp_path, *measured_args(), "--guard-rc", "-1")

    assert result.returncode == 0
    assert read_lines(tmp_path)[0]["guard_rc"] == -1


def test_quota_summary_newline_stays_one_physical_line(tmp_path: Path) -> None:
    """JSON escaping keeps a newline-bearing summary on one JSONL line."""
    result = run_trace(tmp_path, *measured_args(), "--quota-summary", "a\nb")

    assert result.returncode == 0
    trace = tmp_path / "tick_trace.jsonl"
    assert len(trace.read_bytes().splitlines()) == 1
    assert read_lines(tmp_path)[0]["quota_summary"] == "a\nb"


def test_quota_summary_unicode_is_utf8_json(tmp_path: Path) -> None:
    """Unicode quota text survives the UTF-8 JSONL append."""
    result = run_trace(tmp_path, *measured_args(), "--quota-summary", "cupo ✓")

    assert result.returncode == 0
    assert read_lines(tmp_path)[0]["quota_summary"] == "cupo ✓"


def test_tick_trace_schema_v2_cola_despachable(tmp_path: Path) -> None:
    """Before: a v2 tick contains the declared dispatch queue and optional summaries.

    During: write a complete v2 record and read it through the compatibility reader.
    After: new fields are measured without entering unmeasured and the enum is preserved.
    """
    result = run_trace(
        tmp_path,
        *measured_args(),
        "--cola-despachable",
        "2",
        "--cola-motivo",
        "SIN_GO",
        "--gate-rc",
        "0",
        "--quota-accounts",
        '[{"cuenta":"brabander","calidad_medida":"OK","block_pct":98,"estado_operativo":"CAMBIO"}]',
        "--destino",
        "IM-42",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    record = read_lines(tmp_path)[0]
    assert record["v"] == 2
    assert record["cola_despachable"] == 2 and record["cola_motivo"] == "SIN_GO"
    assert record["gate_rc"] == 0 and record["destino"] == "IM-42"
    assert record["unmeasured"] == {}


def test_tick_trace_v1_is_read_as_queue_not_declared(tmp_path: Path) -> None:
    """Before: a legacy v1 line has none of the v2 queue fields.

    During: read the real trace file with the bounded compatibility reader.
    After: the legacy record remains readable and queue state is explicitly absent.
    """
    trace = tmp_path / "tick_trace.jsonl"
    trace.write_text(
        json.dumps({"v": 1, "ts": TS_A, "unmeasured": {}}) + "\n", encoding="utf-8"
    )
    import importlib.util

    spec = importlib.util.spec_from_file_location("tick_trace_reader", SCRIPT)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    records = loaded.read_records(tmp_path)
    assert records[0]["v"] == 1 and records[0].get("cola_despachable") is None


def test_tick_trace_quota_missing_account_roundtrip(tmp_path: Path) -> None:
    """Before: quota JSON marks a census account as NO_MEDIDO with null block_pct.

    During: carry that exact entry through the tick_trace quota summary field.
    After: the trace preserves the absence signal for downstream detectors.
    """
    summary = '[{"cuenta":"alvarovans","calidad_medida":"NO_MEDIDO","block_pct":null,"estado_operativo":null}]'
    result = run_trace(
        tmp_path,
        *measured_args(),
        "--quota-accounts",
        summary,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    record = read_lines(tmp_path)[0]
    assert record["quota_accounts"][0]["cuenta"] == "alvarovans"
    assert record["quota_accounts"][0]["calidad_medida"] == "NO_MEDIDO"
    assert record["quota_accounts"][0]["block_pct"] is None
