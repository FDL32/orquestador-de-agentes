#!/usr/bin/env python3
"""Tests for native_post_tool_hook.py payload extraction.

WOT-2026-042z r2 — B1 (hook payload fix) + B2 (test cosmetics) + B4 (hook tests).

TDD: these tests MUST fail before the hook payload extraction fix exists.
They verify that the hook extracts file_path and line_count from the REAL
Claude Code PostToolUse payload format (tool_response / tool_input), not from
the old guessed "result" key that never arrives in production.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
HOOK = ROOT / ".agent" / "hooks" / "native_post_tool_hook.py"
TELEMETRY_DIR = ROOT / ".agent" / "runtime" / "telemetry"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_read_payload(
    *,
    file_path: str,
    content: str,
    use_tool_response: bool = True,
) -> bytes:
    """Build a PostToolUse JSON payload for a Read tool.

    use_tool_response=True -> real Claude Code format (tool_response).
    use_tool_response=False -> old guessed format (result) for regression.
    """
    payload: dict = {
        "tool_name": "Read",
        "session_id": "test-session-001",
    }
    if use_tool_response:
        # Real Claude Code PostToolUse format
        payload["tool_input"] = {"file_path": file_path}
        payload["tool_response"] = content
    else:
        # Old guessed format (never arrives in production)
        payload["result"] = {"filePath": file_path, "content": content}
    return json.dumps(payload).encode("utf-8")


def _make_read_payload_content_array(content_blocks: list[dict]) -> bytes:
    """Build a PostToolUse JSON payload with tool_response as content-block array."""
    return json.dumps(
        {
            "tool_name": "Read",
            "session_id": "test-session-001",
            "tool_input": {"file_path": "test.md"},
            "tool_response": content_blocks,
        }
    ).encode("utf-8")


def _make_read_payload_structured_response(stdout_val: str) -> bytes:
    """Build a PostToolUse JSON payload with tool_response as structured dict."""
    return json.dumps(
        {
            "tool_name": "Read",
            "session_id": "test-session-001",
            "tool_input": {"file_path": "test.md"},
            "tool_response": {"stdout": stdout_val, "stderr": ""},
        }
    ).encode("utf-8")


def _make_grep_payload() -> bytes:
    """Build a PostToolUse JSON payload for a Grep tool."""
    return json.dumps(
        {
            "tool_name": "Grep",
            "session_id": "test-session-001",
            "tool_input": {"pattern": "hello"},
        }
    ).encode("utf-8")


def _run_hook(payload: bytes) -> subprocess.CompletedProcess:
    """Run the hook as a subprocess with given payload on stdin."""
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=payload,
        cwd=str(ROOT),
        capture_output=True,
        timeout=30,
    )
    result._decoded_stderr = (
        result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
    )
    result._decoded_stdout = (
        result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
    )
    return result


# ---------------------------------------------------------------------------
# B1: payload extraction — real Claude Code PostToolUse format
# ---------------------------------------------------------------------------


def test_tool_response_string_extract_path_and_lines(tmp_path: Path) -> None:
    """B1: tool_response as string -> file_path + line_count extracted.

    Probe E2E con dientes: invoca el hook real con payload de Read real y
    asertar que tool_usage.jsonl contiene ruta + line_count UTILIZABLES.
    """
    test_file = tmp_path / "prompts/canon.md"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    content = "line1\nline2\nline3\n"
    test_file.write_text(content, encoding="utf-8")

    payload = _make_read_payload(
        file_path=str(test_file),
        content=content,
        use_tool_response=True,
    )
    result = _run_hook(payload)
    assert result.returncode == 0, (
        f"Expected exit 0 for real payload.\nstderr: {result._decoded_stderr}"
    )
    # Verify telemetry was written with usable file_path and line_count
    telemetry_file = TELEMETRY_DIR / "tool_usage.jsonl"
    assert telemetry_file.is_file(), "tool_usage.jsonl should exist after hook run"
    last_line = telemetry_file.read_text(encoding="utf-8").strip().split("\n")[-1]
    record = json.loads(last_line)
    assert record["tool"] == "view_file"
    # file_path must NOT be "unknown"
    assert "unknown" not in record["context"], (
        f"Expected real file_path, got: {record['context']}"
    )
    # line_count must be > 0
    assert "3 lines" in record["context"], f"Expected 3 lines, got: {record['context']}"


def test_tool_response_content_array(tmp_path: Path) -> None:
    """B1: tool_response as content-block array -> text extracted."""
    test_file = tmp_path / "prompts/canon.md"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    content = "line1\nline2\n"
    test_file.write_text(content, encoding="utf-8")

    payload = _make_read_payload_content_array([{"type": "text", "text": content}])
    result = _run_hook(payload)
    assert result.returncode == 0
    telemetry_file = TELEMETRY_DIR / "tool_usage.jsonl"
    last_line = telemetry_file.read_text(encoding="utf-8").strip().split("\n")[-1]
    record = json.loads(last_line)
    assert "unknown" not in record["context"]
    assert "2 lines" in record["context"]


def test_tool_response_structured_stdout(tmp_path: Path) -> None:
    """B1: tool_response as dict with stdout -> text extracted."""
    payload = _make_read_payload_structured_response("a\nb\nc\n")
    result = _run_hook(payload)
    assert result.returncode == 0
    telemetry_file = TELEMETRY_DIR / "tool_usage.jsonl"
    last_line = telemetry_file.read_text(encoding="utf-8").strip().split("\n")[-1]
    record = json.loads(last_line)
    assert record["tool"] == "view_file"
    assert "3 lines" in record["context"]


def test_old_result_key_no_longer_needed() -> None:
    """B1: the old 'result' key still produces 'unknown' (proves it was wrong).

    This test verifies the REGRESSION: if someone re-introduces result-based
    parsing, the old format still fails because we now read from tool_response.
    The file_path is 'unknown' because tool_input is empty with the old format.
    """
    payload = json.dumps(
        {
            "tool_name": "Read",
            "session_id": "test-session-001",
            "result": {"filePath": "test.md", "content": "hello"},
        }
    ).encode("utf-8")
    result = _run_hook(payload)
    assert result.returncode == 0
    telemetry_file = TELEMETRY_DIR / "tool_usage.jsonl"
    last_line = telemetry_file.read_text(encoding="utf-8").strip().split("\n")[-1]
    record = json.loads(last_line)
    # With the fix, the old 'result' key is ignored -> file_path defaults
    # from tool_input (empty) -> "unknown". This proves the old format was broken.
    assert "unknown" in record["context"]


def test_non_read_tool_no_content_extraction(tmp_path: Path) -> None:
    """Non-Read tools (Grep, Bash) don't extract file_path/content."""
    payload = _make_grep_payload()
    result = _run_hook(payload)
    assert result.returncode == 0
    telemetry_file = TELEMETRY_DIR / "tool_usage.jsonl"
    last_line = telemetry_file.read_text(encoding="utf-8").strip().split("\n")[-1]
    record = json.loads(last_line)
    assert record["tool"] == "grep"
    assert (
        "executed" in record["context"].lower() and "grep" in record["context"].lower()
    )


def test_empty_content_yields_zero_lines() -> None:
    """Empty content -> 0 lines, still writes telemetry."""
    payload = _make_read_payload(
        file_path="empty.md", content="", use_tool_response=True
    )
    result = _run_hook(payload)
    assert result.returncode == 0
    telemetry_file = TELEMETRY_DIR / "tool_usage.jsonl"
    last_line = telemetry_file.read_text(encoding="utf-8").strip().split("\n")[-1]
    record = json.loads(last_line)
    assert "0 lines" in record["context"]


def test_session_id_propagated_to_telemetry() -> None:
    """session_id from payload is propagated to telemetry record."""
    payload = _make_read_payload(
        file_path="test.md", content="line\n", use_tool_response=True
    )
    result = _run_hook(payload)
    assert result.returncode == 0
    telemetry_file = TELEMETRY_DIR / "tool_usage.jsonl"
    last_line = telemetry_file.read_text(encoding="utf-8").strip().split("\n")[-1]
    record = json.loads(last_line)
    assert record["session_id"] == "test-session-001"


def test_path_key_variant_tool_input_file_path(tmp_path: Path) -> None:
    """tool_input with 'file_path' key extracts correctly."""
    test_file = tmp_path / "prompts/canon.md"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text("data\n", encoding="utf-8")

    payload = json.dumps(
        {
            "tool_name": "Read",
            "session_id": "test-session-001",
            "tool_input": {"file_path": str(test_file)},
            "tool_response": "data\n",
        }
    ).encode("utf-8")
    result = _run_hook(payload)
    assert result.returncode == 0
    telemetry_file = TELEMETRY_DIR / "tool_usage.jsonl"
    last_line = telemetry_file.read_text(encoding="utf-8").strip().split("\n")[-1]
    record = json.loads(last_line)
    assert "unknown" not in record["context"]


def test_no_tool_input_key_uses_unknown() -> None:
    """Missing tool_input -> file_path defaults to unknown."""
    payload = json.dumps(
        {
            "tool_name": "Read",
            "session_id": "test-session-001",
            "tool_response": "content\n",
        }
    ).encode("utf-8")
    result = _run_hook(payload)
    assert result.returncode == 0
    telemetry_file = TELEMETRY_DIR / "tool_usage.jsonl"
    last_line = telemetry_file.read_text(encoding="utf-8").strip().split("\n")[-1]
    record = json.loads(last_line)
    assert "unknown" in record["context"]


def test_continuation_flag_in_output() -> None:
    """Hook outputs {continue: true} on success."""
    payload = _make_read_payload(
        file_path="test.md", content="data\n", use_tool_response=True
    )
    result = _run_hook(payload)
    assert result.returncode == 0
    output = json.loads(result._decoded_stdout.strip())
    assert output.get("continue") is True
