#!/usr/bin/env python3
"""Tests for WOT-2026-124g: --usage-report mode of memory_context.py.

Hermetic: uses ``AGENT_PROJECT_ROOT`` pointing to ``tmp_path`` via
``monkeypatch.setenv``, synthetic log, never the live archive.
Each test must FAIL if the piece it verifies is removed.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


MOTOR_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(MOTOR_ROOT))

from scripts.memory_context import _usage_report  # noqa: E402


def _write_fixture_log(
    log_file: Path,
    entries: list[dict],
) -> None:
    """Write JSON lines to the log file."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n",
        encoding="utf-8",
    )


def _make_entry(
    ts: str,
    caller: str,
    mode: str = "query",
    query: str = "test",
    session: str | None = None,
    v: int = 2,
) -> dict:
    """Create a single recall log entry."""
    return {
        "v": v,
        "timestamp": ts,
        "caller": caller,
        "mode": mode,
        "query": query,
        "results": [],
        "session": session,
    }


def _parse_report(result_stdout: str) -> dict:
    """Parse the JSON report from stdout."""
    return json.loads(result_stdout.strip())


# ---------------------------------------------------------------------------
# (iii) --usage-report: fixture log with v1, v2, mixed callers, before-since,
#       invalid JSON -> exact counts
# ---------------------------------------------------------------------------


def test_usage_report_fixture_counts(tmp_path):
    """(iii) A fixture log with v1 and v2 lines, callers
    agent/measure_recall_quality/session_state_validate/unknown, one line
    before since and one non-JSON line -> exact counts."""
    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
    since = "2026-10-20T00:00:00"

    entries = [
        _make_entry("2026-10-21T10:00:00", "agent", session="sess001"),
        _make_entry("2026-10-22T10:00:00", "agent", session="sess001"),
        _make_entry("2026-10-23T10:00:00", "agent", session="sess002"),
        _make_entry("2026-10-23T15:00:00", "agent", v=1),
        _make_entry("2026-10-21T12:00:00", "measure_recall_quality", session="probe1"),
        _make_entry("2026-10-21T13:00:00", "session_state_validate", session="ssv1"),
        _make_entry("2026-10-21T14:00:00", "unknown"),
        _make_entry("2026-10-19T10:00:00", "agent", session="old1"),
    ]

    log_file = tmp_path / ".agent" / "runtime" / "memory" / "recall_log.jsonl"
    _write_fixture_log(log_file, entries)

    # Inject a non-JSON line directly (not as a dict entry)
    raw = log_file.read_text(encoding="utf-8")
    log_file.write_text(raw + "THIS IS NOT VALID JSON{{{{\n", encoding="utf-8")

    rc, stdout = _run_usage_report(tmp_path, since, 30, now=now)
    assert rc == 0
    report = _parse_report(stdout)

    # Real use: agent calls after since (4 lines: 3 v2 + 1 v1)
    assert report["llamadas_reales"] == 4, (
        f"Expected 4 real calls, got {report['llamadas_reales']}"
    )
    # Distinct sessions: sess001, sess002 (2)
    assert report["sesiones_distintas"] == 2, (
        f"Expected 2 distinct sessions, got {report['sesiones_distintas']}"
    )
    # Distinct days: 2026-10-21, 2026-10-22, 2026-10-23 (3)
    assert report["dias_distintos"] == 3, (
        f"Expected 3 distinct days, got {report['dias_distintos']}"
    )
    # Outside list: measure_recall_quality, session_state_validate, unknown (3)
    assert report["lineas_fuera_de_lista"] == 3, (
        f"Expected 3 outside-list, got {report['lineas_fuera_de_lista']}"
    )
    # Invalid: 1 non-JSON line
    assert report["lineas_invalidas"] == 1, (
        f"Expected 1 invalid, got {report['lineas_invalidas']}"
    )


# ---------------------------------------------------------------------------
# (iv) Verdicts with injected now
# ---------------------------------------------------------------------------


def test_verdict_hay_uso_real_three_sessions(tmp_path):
    """(iv) 30 calls in 3 distinct sessions -> 'hay uso real'."""
    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
    since = "2026-10-20T00:00:00"

    entries = [
        _make_entry(f"2026-10-{21 + i}T{hour}:00:00", "agent", session=sess)
        for hour, sess in (("10", "sessA"), ("11", "sessB"), ("12", "sessC"))
        for i in range(10)
    ]

    log_file = tmp_path / ".agent" / "runtime" / "memory" / "recall_log.jsonl"
    _write_fixture_log(log_file, entries)

    rc, stdout = _run_usage_report(tmp_path, since, 30, now=now)
    assert rc == 0
    report = _parse_report(stdout)
    assert report["veredicto"] == "hay uso real", (
        f"Expected 'hay uso real', got {report['veredicto']}"
    )
    assert report["llamadas_reales"] == 30


def test_verdict_no_hay_uso_real_two_sessions(tmp_path):
    """(iv) 30 calls in 2 sessions -> not 'hay uso real' (needs >= 3 or
    >= 3 days without session)."""
    now = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)
    since = "2026-09-01T00:00:00"

    entries = [
        _make_entry(f"2026-09-{i + 1:02d}T{hour}:00:00", "agent", session=sess)
        for hour, sess in (("10", "sessX"), ("11", "sessY"))
        for i in range(15)
    ]

    log_file = tmp_path / ".agent" / "runtime" / "memory" / "recall_log.jsonl"
    _write_fixture_log(log_file, entries)

    rc, stdout = _run_usage_report(tmp_path, since, 30, now=now)
    assert rc == 0
    report = _parse_report(stdout)
    assert report["veredicto"] != "hay uso real", (
        f"30 calls in 2 sessions should NOT be 'hay uso real', got {report['veredicto']}"
    )


def test_verdict_hay_uso_real_three_days_no_session(tmp_path):
    """(iv) 30 calls with no session in 3 distinct days -> 'hay uso real'."""
    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
    since = "2026-10-20T00:00:00"

    entries = [
        _make_entry(
            f"2026-10-{21 + day_offset}T10:00:00", "agent", v=1
        )  # v1: no session
        for day_offset in range(3)
        for _i in range(10)
    ]

    log_file = tmp_path / ".agent" / "runtime" / "memory" / "recall_log.jsonl"
    _write_fixture_log(log_file, entries)

    rc, stdout = _run_usage_report(tmp_path, since, 30, now=now)
    assert rc == 0
    report = _parse_report(stdout)
    assert report["veredicto"] == "hay uso real", (
        f"Expected 'hay uso real' (3 days no session), got {report['veredicto']}"
    )
    assert report["sesiones_distintas"] == 0


def test_verdict_uso_insuficiente_29_past_window(tmp_path):
    """(iv) 29 calls past window -> 'uso insuficiente'."""
    now = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)
    since = "2026-10-01T00:00:00"

    entries = [
        _make_entry("2026-10-15T10:00:00", "agent", session="sess001")
        for _ in range(29)
    ]

    log_file = tmp_path / ".agent" / "runtime" / "memory" / "recall_log.jsonl"
    _write_fixture_log(log_file, entries)

    rc, stdout = _run_usage_report(tmp_path, since, 30, now=now)
    assert rc == 0
    report = _parse_report(stdout)
    assert report["veredicto"] == "uso insuficiente", (
        f"Expected 'uso insuficiente', got {report['veredicto']}"
    )


def test_verdict_ventana_abierta_29_within_window(tmp_path):
    """(iv) 29 calls within window -> 'ventana abierta'."""
    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
    since = "2026-10-20T00:00:00"

    entries = [
        _make_entry("2026-10-22T10:00:00", "agent", session="sess001")
        for _ in range(29)
    ]

    log_file = tmp_path / ".agent" / "runtime" / "memory" / "recall_log.jsonl"
    _write_fixture_log(log_file, entries)

    rc, stdout = _run_usage_report(tmp_path, since, 30, now=now)
    assert rc == 0
    report = _parse_report(stdout)
    assert report["veredicto"] == "ventana abierta", (
        f"Expected 'ventana abierta', got {report['veredicto']}"
    )


# ---------------------------------------------------------------------------
# (v) --since invalid -> rc 2; log nonexistent -> rc 0 and zeros
# ---------------------------------------------------------------------------


def test_since_invalid_rc2():
    """(v) --since with invalid date returns rc 2."""
    rc, _ = _run_usage_report(Path("/tmp"), "not-a-date", 30)
    assert rc == 2


def test_since_missing_rc2():
    """(v) --since=None returns rc 2."""
    rc, _ = _run_usage_report(Path("/tmp"), None, 30)
    assert rc == 2


def test_log_nonexistent_rc0_zeros(tmp_path):
    """(v) Missing log file -> rc 0 with all zeros."""
    log_dir = tmp_path / ".agent" / "runtime" / "memory"
    log_dir.mkdir(parents=True, exist_ok=True)
    # Do NOT create recall_log.jsonl

    rc, stdout = _run_usage_report(tmp_path, "2026-10-20T00:00:00", 30)
    assert rc == 0
    report = _parse_report(stdout)
    assert report["llamadas_reales"] == 0
    assert report["sesiones_distintas"] == 0
    assert report["dias_distintos"] == 0
    assert report["lineas_fuera_de_lista"] == 0
    assert report["lineas_invalidas"] == 0
    assert report["veredicto"] == "ventana abierta"


# ---------------------------------------------------------------------------
# (vii) Positive control for collect_session_state: hermetic invocation
# ---------------------------------------------------------------------------


def test_collect_session_state_validation_can_be_run_hermetically(
    tmp_path, monkeypatch
):
    """(vii) The REAL slug validation (``collect_memory_slugs``, real
    subprocess) run against a temporary AGENT_PROJECT_ROOT writes its recall
    log line with ``caller == 'session_state_validate'`` -- so it is never
    counted as real agent use (codex review of fe25854b, MINOR 1)."""
    from scripts.collect_session_state import collect_memory_slugs

    monkeypatch.setenv("AGENT_PROJECT_ROOT", str(tmp_path))
    out = collect_memory_slugs(MOTOR_ROOT, ["obs-124g-slug-que-no-existe"])

    assert [r["citable"] for r in out] == [False]
    log_file = tmp_path / ".agent" / "runtime" / "memory" / "recall_log.jsonl"
    lines = [json.loads(x) for x in log_file.read_text(encoding="utf-8").splitlines()]
    assert [(ln["caller"], ln["mode"]) for ln in lines] == [
        ("session_state_validate", "id")
    ]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _run_usage_report(
    root: Path, since: str | None, window_days: int, *, now: datetime | None = None
) -> tuple[int, str]:
    """Run _usage_report and capture its return code and stdout."""
    import io

    cap = io.StringIO()
    with mock.patch("sys.stdout", cap):
        rc = _usage_report(root, since, window_days, now=now)
    return rc, cap.getvalue()


def test_verdict_29_calls_three_sessions_is_not_real_use(tmp_path):
    """(iv) Boundary of the call threshold: 29 calls spread over 3 sessions,
    window closed -> 'uso insuficiente' (30 is the minimum, not 29)."""
    now = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)
    since = "2026-10-01T00:00:00"
    entries = [
        _make_entry(f"2026-10-{10 + i % 3}T10:00:00", "agent", session=f"s{i % 3}")
        for i in range(29)
    ]
    log_file = tmp_path / ".agent" / "runtime" / "memory" / "recall_log.jsonl"
    _write_fixture_log(log_file, entries)
    rc, stdout = _run_usage_report(tmp_path, since, 30, now=now)
    report = _parse_report(stdout)
    assert rc == 0
    assert report["sesiones_distintas"] == 3
    assert report["llamadas_reales"] == 29
    assert report["veredicto"] == "uso insuficiente"


def test_malformed_records_are_invalid_not_a_crash(tmp_path):
    """codex MAJOR 1 (ae04a8fe): valid JSON that is not a usable record is
    counted in ``lineas_invalidas`` and never raises."""
    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
    good = _make_entry("2026-10-21T10:00:00", "agent", session="s1")
    bad_lines = [
        "[]",
        "null",
        '"texto"',
        "42",
        json.dumps({**good, "timestamp": 20261021}),
        json.dumps({**good, "caller": ["agent"]}),
        json.dumps({**good, "session": ["s1"]}),
        json.dumps({**good, "v": True}),
    ]
    log_file = tmp_path / ".agent" / "runtime" / "memory" / "recall_log.jsonl"
    log_file.parent.mkdir(parents=True)
    log_file.write_text(
        "\n".join([json.dumps(good), *bad_lines]) + "\n", encoding="utf-8"
    )
    rc, stdout = _run_usage_report(tmp_path, "2026-10-20T00:00:00", 30, now=now)
    report = _parse_report(stdout)
    assert rc == 0
    assert report["lineas_invalidas"] == len(bad_lines)
    assert report["llamadas_reales"] == 1
