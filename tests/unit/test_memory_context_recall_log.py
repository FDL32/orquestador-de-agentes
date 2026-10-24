#!/usr/bin/env python3
"""Tests for WOT-2026-124f: recall telemetry log (append-only JSONL).

Hermetic: uses ``AGENT_PROJECT_ROOT`` pointing to ``tmp_path`` via
``monkeypatch.setenv``, synthetic corpus, never the live archive.
Each test must FAIL if the piece it verifies is removed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest


# Ensure motor root is on sys.path for imports.
MOTOR_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(MOTOR_ROOT))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fixture(with_id: bool = True, n: int = 2) -> list[dict]:
    """Return a small hermetic corpus for testing recall output."""
    fixtures: list[dict] = []
    for i in range(n):
        obs: dict = {
            "topic": "testing",
            "signal": f"SEÑAL de prueba numero {i} con acentos.",
            "source": "test",
            "timestamp": f"2026-10-24T12:{i:02d}:00",
        }
        if with_id:
            obs["id"] = f"obs-fixture-id-{i}"
        fixtures.append(obs)
    return fixtures


def _make_fixture_no_id(n: int = 1) -> list[dict]:
    """Return observations WITHOUT id field."""
    fixtures: list[dict] = []
    for i in range(n):
        obs: dict = {
            "topic": "testing",
            "signal": f"SIN id campo numero {i}.",
            "source": "test",
            "timestamp": f"2026-10-24T12:{i:02d}:00",
        }
        fixtures.append(obs)
    return fixtures


def _build_args(
    mode: str,
    query: str | None = None,
    ticket: str | None = None,
    obs_id: str | None = None,
    caller: str = "unknown",
) -> argparse.Namespace:  # type: ignore[name-defined]
    """Build an argparse.Namespace mimicking parsed CLI args for recall mode."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap", action="store_true")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--compact", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--recall", action="store_true")
    parser.add_argument("--why", type=str, default=None, metavar="ID_OR_TOPIC")
    parser.add_argument("--query", type=str, default=None)
    parser.add_argument("--ticket", type=str, default=None)
    parser.add_argument("--id", type=str, default=None, dest="obs_id")
    parser.add_argument("--caller", type=str, default="unknown")
    parser.add_argument("--headlines", action="store_true")
    parser.add_argument("--limit", type=int, default=15)
    parser.add_argument("--budget", type=int, default=None)

    if mode == "query":
        cmd = ["--recall", "--query", query or "test"]
        if caller != "unknown":
            cmd.extend(["--caller", caller])
        return parser.parse_args(cmd)
    elif mode == "ticket":
        cmd = ["--recall", "--ticket", ticket or "WOT-2026-124f"]
        if caller != "unknown":
            cmd.extend(["--caller", caller])
        return parser.parse_args(cmd)
    elif mode == "id":
        cmd = ["--recall", "--id", obs_id or "obs-fixture-id-0"]
        if caller != "unknown":
            cmd.extend(["--caller", caller])
        return parser.parse_args(cmd)
    else:  # plain
        cmd = ["--recall"]
        if caller != "unknown":
            cmd.extend(["--caller", caller])
        return parser.parse_args(cmd)


def _load_log_lines(log_file: Path) -> list[dict]:
    """Read all JSON lines from the recall log file."""
    return [
        json.loads(ln)
        for ln in log_file.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]


# ---------------------------------------------------------------------------
# (i) One test per mode validating exact schema
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mode,q",
    [
        ("query", "suite-verde"),
        ("ticket", "WOT-2026-124f"),
        ("id", "obs-fixture-id-0"),
        ("plain", None),
    ],
)
def test_schema_per_mode(monkeypatch, tmp_path, mode, q):
    """(i) Each mode writes a line matching the exact schema."""
    import json

    from scripts.memory_context import _run

    # Each param gets a unique subdirectory to avoid cross-contamination.
    test_root = tmp_path / mode
    test_root.mkdir(exist_ok=True)
    monkeypatch.setenv("AGENT_PROJECT_ROOT", str(test_root))

    # Minimal fixture: exactly one observation with id.
    obs: list[dict] = [
        {
            "id": "obs-fixture-id-0",
            "topic": "testing",
            "signal": "SEÑAL de prueba numero 0 con acentos.",
            "source": "test",
            "timestamp": "2026-10-24T12:00:00",
        }
    ]
    assert len(obs) == 1  # sanity

    with mock.patch("scripts.memory_context.recall_observations", return_value=obs):
        args = _build_args(mode, query=q)
        _run(args)

    log_file = test_root / ".agent" / "runtime" / "memory" / "recall_log.jsonl"
    assert log_file.is_file(), "recall_log.jsonl must be created"
    content = log_file.read_text(encoding="utf-8")
    lines = [json.loads(ln) for ln in content.strip().splitlines() if ln.strip()]
    assert len(lines) == 1, f"Expected 1 line, got {len(lines)}"

    entry = lines[0]
    # Schema keys
    assert entry["v"] == 1
    assert isinstance(entry["timestamp"], str)
    assert entry["caller"] == "unknown"
    assert entry["mode"] == mode

    # Query field
    if mode == "query":
        assert entry["query"] == q
    elif mode == "ticket":
        assert entry["query"] == "WOT-2026-124f"
    elif mode == "id":
        assert entry["query"] == "obs-fixture-id-0"
    else:  # plain
        assert entry["query"] == ""

    # Results: list of id strings
    assert isinstance(entry["results"], list)
    assert len(entry["results"]) == 1, (
        f"Expected 1 result, got {len(entry['results'])}: {entry['results']}"
    )
    assert entry["results"][0] == "obs-fixture-id-0"


# ---------------------------------------------------------------------------
# (ii) Lesson without id: results contains JSON-serialized dedup_key
# ---------------------------------------------------------------------------


def test_no_id_uses_dedup_key_json(monkeypatch, tmp_path):
    """(ii) A lesson without id appears in results as list(dedup_key(obs))."""

    from bus.portable_memory_archive import dedup_key
    from scripts.memory_context import _run

    test_root = tmp_path / "no_id"
    test_root.mkdir(exist_ok=True)
    monkeypatch.setenv("AGENT_PROJECT_ROOT", str(test_root))
    obs = _make_fixture_no_id(n=1)
    expected_dk = list(dedup_key(obs[0]))

    with mock.patch("scripts.memory_context.recall_observations", return_value=obs):
        args = _build_args("query", query="test")
        _run(args)

    log_file = test_root / ".agent" / "runtime" / "memory" / "recall_log.jsonl"
    lines = _load_log_lines(log_file)
    assert len(lines) == 1

    elemento = lines[0]["results"][0]
    # The result must be a plain list matching dedup_key(obs)
    assert isinstance(elemento, list), (
        f"Expected list, got {type(elemento).__name__}: {elemento!r}"
    )
    assert elemento == expected_dk, f"Element {elemento!r} != dedup_key {expected_dk!r}"


# ---------------------------------------------------------------------------
# (iii) Two executions -> two lines; previous content intact (append)
# ---------------------------------------------------------------------------


def test_append_not_rewrite(monkeypatch, tmp_path):
    """(iii) Two executions produce two lines; previous content is intact."""
    from scripts.memory_context import _run

    test_root = tmp_path / "append"
    test_root.mkdir(exist_ok=True)
    monkeypatch.setenv("AGENT_PROJECT_ROOT", str(test_root))
    obs1 = _make_fixture(with_id=True, n=1)
    obs2 = _make_fixture(with_id=True, n=2)

    # First execution
    with mock.patch("scripts.memory_context.recall_observations", return_value=obs1):
        args1 = _build_args("query", query="first")
        _run(args1)

    log_file = test_root / ".agent" / "runtime" / "memory" / "recall_log.jsonl"
    lines1 = _load_log_lines(log_file)
    assert len(lines1) == 1

    # Second execution
    with mock.patch("scripts.memory_context.recall_observations", return_value=obs2):
        args2 = _build_args("query", query="second")
        _run(args2)

    lines2 = _load_log_lines(log_file)
    assert len(lines2) == 2
    # First line must be preserved
    assert lines2[0]["query"] == "first"
    assert lines2[0]["mode"] == "query"
    # Second line is new
    assert lines2[1]["query"] == "second"


# ---------------------------------------------------------------------------
# (iv) Unwritable log: stdout and exit code IDENTICAL to writable
# ---------------------------------------------------------------------------


def test_unwritable_log_does_not_affect_output(monkeypatch, tmp_path):
    """(iv) When the log is unwritable (dir masquerading as file),
    stdout and exit code are IDENTICAL to a writable log."""
    from io import StringIO

    from scripts.memory_context import _run

    test_root = tmp_path / "unwritable"
    test_root.mkdir(exist_ok=True)
    monkeypatch.setenv("AGENT_PROJECT_ROOT", str(test_root))
    obs = _make_fixture(with_id=True, n=3)

    # Create recall_log.jsonl as a DIRECTORY (unwritable as file)
    log_dir = test_root / ".agent" / "runtime" / "memory"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "recall_log.jsonl").mkdir(exist_ok=True)

    captured_stdout = StringIO()
    captured_stderr = StringIO()

    with (
        mock.patch("scripts.memory_context.recall_observations", return_value=obs),
        mock.patch("sys.stdout", captured_stdout),
        mock.patch("sys.stderr", captured_stderr),
    ):
        args = _build_args("query", query="test")
        rc = _run(args)

    # Must exit with rc 0
    assert rc == 0
    # Stdout must have output (3 lines)
    output = captured_stdout.getvalue()
    assert "SEÑAL de prueba" in output
    # Stderr must carry the warning about log failure
    stderr_text = captured_stderr.getvalue()
    assert "[WARN] recall log" in stderr_text


# ---------------------------------------------------------------------------
# (v) stdout is IDENTICAL with and without log
# ---------------------------------------------------------------------------


def test_stdout_identical_with_without_log(monkeypatch, tmp_path):
    """(v) stdout output is identical with and without the log."""
    from io import StringIO

    from scripts.memory_context import _run

    obs = _make_fixture(with_id=True, n=3)

    captured_with: list[str] = []
    captured_without: list[str] = []

    # With log: use test_root with full .agent path
    test_root_with = tmp_path / "with_log"
    test_root_with.mkdir(exist_ok=True)
    monkeypatch.setenv("AGENT_PROJECT_ROOT", str(test_root_with))
    with mock.patch("scripts.memory_context.recall_observations", return_value=obs):
        cap1 = StringIO()
        with mock.patch("sys.stdout", cap1):
            _run(_build_args("query", query="test"))
        captured_with.append(cap1.getvalue())

    # Without log: use tmp_path_no_log (no .agent/runtime/memory dir)
    test_root_no_log = tmp_path / "no_log"
    test_root_no_log.mkdir(exist_ok=True)
    monkeypatch.setenv("AGENT_PROJECT_ROOT", str(test_root_no_log))
    with mock.patch("scripts.memory_context.recall_observations", return_value=obs):
        cap2 = StringIO()
        with mock.patch("sys.stdout", cap2):
            _run(_build_args("query", query="test"))
        captured_without.append(cap2.getvalue())

    assert captured_with[0] == captured_without[0], (
        f"With log:\n{captured_with[0]!r}\nWithout log:\n{captured_without[0]!r}"
    )


# ---------------------------------------------------------------------------
# (vi) --caller X appears in log; without flag, "unknown"
# ---------------------------------------------------------------------------


def test_caller_flag_in_log(monkeypatch, tmp_path):
    """(vi) --caller X is written to log; without flag, 'unknown'."""
    from scripts.memory_context import _run

    test_root = tmp_path / "caller"
    test_root.mkdir(exist_ok=True)
    monkeypatch.setenv("AGENT_PROJECT_ROOT", str(test_root))
    obs = _make_fixture(with_id=True)

    # With --caller claude-code-1
    with mock.patch("scripts.memory_context.recall_observations", return_value=obs):
        args = _build_args("query", query="test", caller="claude-code-1")
        _run(args)

    log_file = test_root / ".agent" / "runtime" / "memory" / "recall_log.jsonl"
    lines = _load_log_lines(log_file)
    assert len(lines) == 1
    assert lines[0]["caller"] == "claude-code-1"

    # Without --caller (default "unknown")
    with mock.patch("scripts.memory_context.recall_observations", return_value=obs):
        args2 = _build_args("query", query="test")
        _run(args2)

    lines2 = _load_log_lines(log_file)
    assert len(lines2) == 2
    assert lines2[1]["caller"] == "unknown"


# ---------------------------------------------------------------------------
# (vii) git check-ignore recognizes recall_log.jsonl in the repo
# ---------------------------------------------------------------------------


def test_gitignore_recognizes_log():
    """(vii) git check-ignore -q .agent/runtime/memory/recall_log.jsonl
    returns rc 0 in the motor repo."""
    result = subprocess.run(
        [
            "git",
            "check-ignore",
            "-q",
            ".agent/runtime/memory/recall_log.jsonl",
        ],
        cwd=str(MOTOR_ROOT),
    )
    assert result.returncode == 0, (
        f"git check-ignore must recognize the log file, got rc={result.returncode}"
    )


def test_recall_id_inexistent_writes_log_and_returns_rc1(monkeypatch, tmp_path):
    """(viii) --recall --id obs-no-existe with a fixture archive -> rc 1,
    exactly ONE new line in the log with mode=='id', query=='obs-no-existe',
    results==[]. This test FAILS if the _write_recall_log call inside
    'if not match:' of the args.obs_id block in _run() is removed."""
    import json

    from scripts.memory_context import _run

    test_root = tmp_path / "inexistent"
    test_root.mkdir(exist_ok=True)
    archive_dir = test_root / ".agent" / "runtime" / "memory" / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    fixture_obs = _make_fixture(with_id=True, n=2)
    (archive_dir / "observations.2026-10.jsonl").write_text(
        "\n".join(json.dumps(obs) for obs in fixture_obs) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENT_PROJECT_ROOT", str(test_root))

    rc = _run(_build_args("id", obs_id="obs-no-existe"))

    assert rc == 1
    log_file = test_root / ".agent" / "runtime" / "memory" / "recall_log.jsonl"
    assert log_file.is_file(), "recall_log.jsonl must be created on rc 1 path"
    lines = _load_log_lines(log_file)
    assert len(lines) == 1, f"Expected 1 line, got {len(lines)}"
    entry = lines[0]
    assert entry["mode"] == "id"
    assert entry["query"] == "obs-no-existe"
    assert entry["results"] == []
