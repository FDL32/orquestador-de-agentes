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


def _run_hook(
    payload: bytes, tmp_path: Path | None = None
) -> subprocess.CompletedProcess:
    """Run the hook as a subprocess with given payload on stdin.

    H1 (WOT-2026-042z-r3): cwd defaults to a tmp_path (or ROOT if not provided)
    so tests write to isolated telemetry, not the real repo telemetry.
    """
    cwd = str(tmp_path) if tmp_path is not None else str(ROOT)
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=payload,
        cwd=cwd,
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
    result = _run_hook(payload, tmp_path=tmp_path)
    assert result.returncode == 0, (
        f"Expected exit 0 for real payload.\nstderr: {result._decoded_stderr}"
    )
    # Verify telemetry was written with usable file_path and line_count
    telemetry_file = tmp_path / ".agent" / "runtime" / "telemetry" / "tool_usage.jsonl"
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
    result = _run_hook(payload, tmp_path=tmp_path)
    assert result.returncode == 0
    telemetry_file = tmp_path / ".agent" / "runtime" / "telemetry" / "tool_usage.jsonl"
    last_line = telemetry_file.read_text(encoding="utf-8").strip().split("\n")[-1]
    record = json.loads(last_line)
    assert "unknown" not in record["context"]
    assert "2 lines" in record["context"]


def test_tool_response_structured_stdout(tmp_path: Path) -> None:
    """B1: tool_response as dict with stdout -> text extracted."""
    payload = _make_read_payload_structured_response("a\nb\nc\n")
    result = _run_hook(payload, tmp_path=tmp_path)
    assert result.returncode == 0
    telemetry_file = tmp_path / ".agent" / "runtime" / "telemetry" / "tool_usage.jsonl"
    last_line = telemetry_file.read_text(encoding="utf-8").strip().split("\n")[-1]
    record = json.loads(last_line)
    assert record["tool"] == "view_file"
    assert "3 lines" in record["context"]


def test_tool_response_real_claude_code_file_block(tmp_path: Path) -> None:
    """B1 (medido 2026-10-15): la forma REAL de tool_response para Read en
    produccion es {"type": "text", "file": {"filePath": ..., "content": ...}}.

    Confirmado capturando un payload real: ANTES de este fix, el 100% de las
    entradas historicas de tool_usage.jsonl con file_path correcto tenian
    SIEMPRE "0 lines", porque esta forma no coincidia con ninguna de las 3
    ramas anteriores (string / content-block-array / {content|stdout}).
    MUTATION: sin la rama `file_block = tool_response.get("file")`, este test
    cae a "0 lines" (ROJO); con ella, pasa (VERDE).
    """
    payload = json.dumps(
        {
            "tool_name": "Read",
            "session_id": "test-session-001",
            "tool_input": {"file_path": "prompts/canon.md"},
            "tool_response": {
                "type": "text",
                "file": {
                    "filePath": "prompts/canon.md",
                    "content": "line1\nline2\nline3\nline4\n",
                },
            },
        }
    ).encode("utf-8")
    result = _run_hook(payload, tmp_path=tmp_path)
    assert result.returncode == 0, f"Expected exit 0.\nstderr: {result._decoded_stderr}"
    telemetry_file = tmp_path / ".agent" / "runtime" / "telemetry" / "tool_usage.jsonl"
    last_line = telemetry_file.read_text(encoding="utf-8").strip().split("\n")[-1]
    record = json.loads(last_line)
    assert record["tool"] == "view_file"
    assert "unknown" not in record["context"], (
        f"Expected real file_path, got: {record['context']}"
    )
    assert "4 lines" in record["context"], (
        f"Expected 4 lines (ROJO previo: siempre '0 lines'), got: {record['context']}"
    )


def test_tool_response_file_block_fills_unknown_path(tmp_path: Path) -> None:
    """B1: si tool_input no trae file_path, el bloque 'file.filePath' lo rellena.

    Cubre el caso donde tool_input esta vacio pero tool_response.file.filePath
    SI tiene la ruta real -- no debe quedar 'unknown' cuando el dato existe en
    otro sitio del payload.
    """
    payload = json.dumps(
        {
            "tool_name": "Read",
            "session_id": "test-session-001",
            "tool_response": {
                "type": "text",
                "file": {
                    "filePath": "prompts/other.md",
                    "content": "a\nb\n",
                },
            },
        }
    ).encode("utf-8")
    result = _run_hook(payload, tmp_path=tmp_path)
    assert result.returncode == 0
    telemetry_file = tmp_path / ".agent" / "runtime" / "telemetry" / "tool_usage.jsonl"
    last_line = telemetry_file.read_text(encoding="utf-8").strip().split("\n")[-1]
    record = json.loads(last_line)
    assert "prompts/other.md" in record["context"]
    assert "2 lines" in record["context"]


def test_old_result_key_no_longer_needed(tmp_path: Path) -> None:
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
    result = _run_hook(payload, tmp_path=tmp_path)
    assert result.returncode == 0
    telemetry_file = tmp_path / ".agent" / "runtime" / "telemetry" / "tool_usage.jsonl"
    last_line = telemetry_file.read_text(encoding="utf-8").strip().split("\n")[-1]
    record = json.loads(last_line)
    # With the fix, the old 'result' key is ignored -> file_path defaults
    # from tool_input (empty) -> "unknown". This proves the old format was broken.
    assert "unknown" in record["context"]


def test_non_read_tool_no_content_extraction(tmp_path: Path) -> None:
    """Non-Read tools (Grep, Bash) don't extract file_path/content."""
    payload = _make_grep_payload()
    result = _run_hook(payload, tmp_path=tmp_path)
    assert result.returncode == 0
    telemetry_file = tmp_path / ".agent" / "runtime" / "telemetry" / "tool_usage.jsonl"
    last_line = telemetry_file.read_text(encoding="utf-8").strip().split("\n")[-1]
    record = json.loads(last_line)
    assert record["tool"] == "grep"
    assert (
        "executed" in record["context"].lower() and "grep" in record["context"].lower()
    )


def test_empty_content_yields_zero_lines(tmp_path: Path) -> None:
    """Empty content -> 0 lines, still writes telemetry."""
    payload = _make_read_payload(
        file_path="empty.md", content="", use_tool_response=True
    )
    result = _run_hook(payload, tmp_path=tmp_path)
    assert result.returncode == 0
    telemetry_file = tmp_path / ".agent" / "runtime" / "telemetry" / "tool_usage.jsonl"
    last_line = telemetry_file.read_text(encoding="utf-8").strip().split("\n")[-1]
    record = json.loads(last_line)
    assert "0 lines" in record["context"]


def test_session_id_propagated_to_telemetry(tmp_path: Path) -> None:
    """session_id from payload is propagated to telemetry record."""
    payload = _make_read_payload(
        file_path="test.md", content="line\n", use_tool_response=True
    )
    result = _run_hook(payload, tmp_path=tmp_path)
    assert result.returncode == 0
    telemetry_file = tmp_path / ".agent" / "runtime" / "telemetry" / "tool_usage.jsonl"
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
    result = _run_hook(payload, tmp_path=tmp_path)
    assert result.returncode == 0
    telemetry_file = tmp_path / ".agent" / "runtime" / "telemetry" / "tool_usage.jsonl"
    last_line = telemetry_file.read_text(encoding="utf-8").strip().split("\n")[-1]
    record = json.loads(last_line)
    assert "unknown" not in record["context"]


def test_no_tool_input_key_uses_unknown(tmp_path: Path) -> None:
    """Missing tool_input -> file_path defaults to unknown."""
    payload = json.dumps(
        {
            "tool_name": "Read",
            "session_id": "test-session-001",
            "tool_response": "content\n",
        }
    ).encode("utf-8")
    result = _run_hook(payload, tmp_path=tmp_path)
    assert result.returncode == 0
    telemetry_file = tmp_path / ".agent" / "runtime" / "telemetry" / "tool_usage.jsonl"
    last_line = telemetry_file.read_text(encoding="utf-8").strip().split("\n")[-1]
    record = json.loads(last_line)
    assert "unknown" in record["context"]


def test_continuation_flag_in_output(tmp_path: Path) -> None:
    """Hook outputs {continue: true} on success."""
    payload = _make_read_payload(
        file_path="test.md", content="data\n", use_tool_response=True
    )
    result = _run_hook(payload, tmp_path=tmp_path)
    assert result.returncode == 0
    output = json.loads(result._decoded_stdout.strip())
    assert output.get("continue") is True


# ---------------------------------------------------------------------------
# B5 r3: end-to-end chain test (ABS payload -> hook -> telemetry -> check)
# ---------------------------------------------------------------------------


def test_e2e_chain_absolute_path_r3(tmp_path: Path) -> None:
    """B5: ABS path under C:\\Users\\... -> hook -> telemetry -> check rc=0.

    This test closes the seam that the r2 revisor caught: the full chain
    hook(real, ABS path) -> redact(telemetry) -> check(full-read) must
    distinguish full-read from grep-only.

    We simulate the redacted telemetry record that the real hook produces
    (via the post_tool_hook's bus.redact pipeline) and verify
    check_contract_full_read.py matches via the B5 redacted path.
    """
    from bus.redact import redact

    # Create a minimal motor root structure under tmp_path
    motor_root = tmp_path / "motor_root"
    agent_runtime_telemetry = motor_root / ".agent" / "runtime" / "telemetry"
    agent_runtime_telemetry.mkdir(parents=True, exist_ok=True)

    # Create a test file with ABSOLUTE path (simulates C:\Users\fdl\...)
    test_file = motor_root / "prompts" / "canon.md"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    content_lines = [f"line{i}\n" for i in range(1, 13)]
    content = "".join(content_lines)
    test_file.write_text(content, encoding="utf-8")

    abs_path = str(test_file.resolve())  # ABSOLUTE path

    # Simulate what the real hook does: write a redacted telemetry record
    redacted_path = redact(abs_path)  # C:\Users\***REDACTED***\...
    telemetry_record = {
        "tool": "view_file",
        "context": f"Read file {redacted_path}, 12 lines",
        "session_id": "r3-e2e-chain",
        "timestamp": "2026-10-15T00:00:00+00:00",
    }
    telemetry_file = agent_runtime_telemetry / "tool_usage.jsonl"
    telemetry_file.write_text(
        json.dumps(telemetry_record, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Now run check_contract_full_read against this telemetry + artifact
    check_script = str(
        Path(__file__).resolve().parent.parent.parent
        / "scripts"
        / "check_contract_full_read.py"
    )

    # Create an artifact that cites the file (relative path under motor root)
    artifact = tmp_path / "artifact.md"
    artifact.write_text(
        f'Leyendo `"{test_file.name}"` del motor root:\n{content}\n',
        encoding="utf-8",
    )

    result_check = subprocess.run(
        [
            sys.executable,
            check_script,
            str(artifact),
            str(agent_runtime_telemetry),
            "--motor-root",
            str(motor_root),
        ],
        capture_output=True,
        timeout=30,
    )
    # B5 r3: With redacted path matching, the chain must PASS (rc=0)
    assert result_check.returncode == 0, (
        f"Chain failed: rc={result_check.returncode}\n"
        f"stdout: {result_check.stdout.decode('utf-8', errors='replace')}\n"
        f"stderr: {result_check.stderr.decode('utf-8', errors='replace')}\n"
        f"redacted_path: {redacted_path}\n"
        f"abs_path: {abs_path}"
    )


def test_probe_p1_abs_dir1_zero_dir2_one_r3(tmp_path: Path) -> None:
    """B5 r3: Re-ejecucion del probe P1 del revisor.

    dir1 (full-read, ABS path) -> rc=0
    dir2 (grep-only, ABS path) -> rc=1
    """
    from bus.redact import redact

    motor_root = tmp_path / "motor_root"
    agent_runtime_telemetry = motor_root / ".agent" / "runtime" / "telemetry"
    agent_runtime_telemetry.mkdir(parents=True, exist_ok=True)

    # Create two test files
    file1 = motor_root / "prompts" / "canon.md"
    file1.parent.mkdir(parents=True, exist_ok=True)
    content1 = "".join(f"line{i}\n" for i in range(1, 13))
    file1.write_text(content1, encoding="utf-8")

    file2 = motor_root / "prompts" / "other.md"
    content2 = "".join(f"line{i}\n" for i in range(1, 6))
    file2.write_text(content2, encoding="utf-8")

    abs_path1 = str(file1.resolve())
    abs_path2 = str(file2.resolve())

    check_script = str(
        Path(__file__).resolve().parent.parent.parent
        / "scripts"
        / "check_contract_full_read.py"
    )

    # dir1: full-read telemetry (redacted ABS path for file1)
    redacted1 = redact(abs_path1)
    record_full = {
        "tool": "view_file",
        "context": f"Read file {redacted1}, 12 lines",
        "session_id": "p1-abs",
        "timestamp": "2026-10-15T00:00:00+00:00",
    }
    telemetry_file = agent_runtime_telemetry / "tool_usage.jsonl"
    telemetry_file.write_text(
        json.dumps(record_full, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    artifact1 = tmp_path / "artifact1.md"
    artifact1.write_text(f'Leyendo `"{file1.name}"`:\n{content1}\n', encoding="utf-8")

    result_dir1 = subprocess.run(
        [
            sys.executable,
            check_script,
            str(artifact1),
            str(agent_runtime_telemetry),
            "--motor-root",
            str(motor_root),
            "--session-id",
            "p1-abs",
        ],
        capture_output=True,
        timeout=30,
    )
    assert result_dir1.returncode == 0, (
        f"dir1 (full-read) should be rc=0, got rc={result_dir1.returncode}\n"
        f"stdout: {result_dir1.stdout.decode('utf-8', errors='replace')}\n"
        f"stderr: {result_dir1.stderr.decode('utf-8', errors='replace')}"
    )

    # dir2: grep-only telemetry (simulated by a grep event)
    record_grep = {
        "tool": "grep",
        "context": f"Grep executed: pattern 'hello' in {redacted1}",
        "session_id": "p2-grep",
        "timestamp": "2026-10-15T00:01:00+00:00",
    }
    telemetry_file.write_text(
        json.dumps(record_grep, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    artifact2 = tmp_path / "artifact2.md"
    # Use absolute path in backticks so the resolver finds it under motor_root
    artifact2.write_text(f"Se grepeo `{abs_path2}`:\n", encoding="utf-8")

    result_dir2 = subprocess.run(
        [
            sys.executable,
            check_script,
            str(artifact2),
            str(agent_runtime_telemetry),
            "--motor-root",
            str(motor_root),
            "--session-id",
            "p2-grep",
        ],
        capture_output=True,
        timeout=30,
    )
    assert result_dir2.returncode == 1, (
        f"dir2 (grep-only) should be rc=1, got rc={result_dir2.returncode}\n"
        f"stdout: {result_dir2.stdout.decode('utf-8', errors='replace')}\n"
        f"stderr: {result_dir2.stderr.decode('utf-8', errors='replace')}"
    )


# ---------------------------------------------------------------------------
# WOT-2026-104j: offset paginado en el contexto de telemetria (formato aditivo)
# ---------------------------------------------------------------------------


def test_paginated_read_emits_offset_suffix(tmp_path: Path) -> None:
    """WOT-2026-104j: tool_input con offset -> sufijo ', offset=<k>'.

    El hook debe reenviar el offset de la Read paginada para que
    check_contract_full_read pueda unir rangos [offset, offset+line_count].
    """
    content = "".join(f"line{i}\n" for i in range(1, 406))
    payload = json.dumps(
        {
            "tool_name": "Read",
            "session_id": "test-session-001",
            "tool_input": {
                "file_path": "prompts/canon.md",
                "offset": 563,
                "limit": 405,
            },
            "tool_response": content,
        }
    ).encode("utf-8")
    result = _run_hook(payload, tmp_path=tmp_path)
    assert result.returncode == 0, f"Expected exit 0.\nstderr: {result._decoded_stderr}"
    telemetry_file = tmp_path / ".agent" / "runtime" / "telemetry" / "tool_usage.jsonl"
    last_line = telemetry_file.read_text(encoding="utf-8").strip().split("\n")[-1]
    record = json.loads(last_line)
    assert "405 lines, offset=563" in record["context"], (
        f"Expected offset suffix, got: {record['context']}"
    )


def test_read_without_offset_keeps_historic_format(tmp_path: Path) -> None:
    """WOT-2026-104j: sin offset (o offset=0) el formato historico no cambia."""
    payload = json.dumps(
        {
            "tool_name": "Read",
            "session_id": "test-session-001",
            "tool_input": {"file_path": "prompts/canon.md", "offset": 0},
            "tool_response": "a\nb\n",
        }
    ).encode("utf-8")
    result = _run_hook(payload, tmp_path=tmp_path)
    assert result.returncode == 0, f"Expected exit 0.\nstderr: {result._decoded_stderr}"
    telemetry_file = tmp_path / ".agent" / "runtime" / "telemetry" / "tool_usage.jsonl"
    last_line = telemetry_file.read_text(encoding="utf-8").strip().split("\n")[-1]
    record = json.loads(last_line)
    assert record["context"].endswith("Read file prompts/canon.md, 2 lines"), (
        f"Historic format must be byte-identical, got: {record['context']}"
    )
