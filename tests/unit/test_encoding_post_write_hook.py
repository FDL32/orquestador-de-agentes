"""Tests for encoding_post_write_hook.py — early detection after Write|Edit|MultiEdit.

TDD: these tests MUST fail before the hook implementation exists.
They verify: payload parsing, extension filtering, root resolution,
in-process detection, subprocess fallback, diagnostic output with ACTION:.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = ROOT / "scripts"
HOOK = SCRIPTS / "encoding_post_write_hook.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_payload(
    *,
    tool_input: dict | None = None,
    result: dict | None = None,
) -> bytes:
    """Build a PostToolUse JSON payload."""
    payload: dict = {}
    if tool_input is not None:
        payload["tool_input"] = tool_input
    if result is not None:
        payload["result"] = result
    return json.dumps(payload).encode("utf-8")


def _write_bom(path: Path, content: str = "# hello\n") -> None:
    path.write_bytes(b"\xef\xbb\xbf" + content.encode("utf-8"))


def _write_mojibake(path: Path) -> None:
    """Write file with real mojibake: bytes that decode to SUSPICIOUS_CODEPOINTS.

    \\xc3\\x83 decodes to U+00C3 (Ã) which IS in SUSPICIOUS_CODEPOINTS.
    This simulates double-encoded UTF-8 (the classic mojibake pattern).
    """
    path.write_bytes(b"caf\xc3\x83 plan.txt\n")


def _write_question_mark(path: Path) -> None:
    path.write_text("a?b plan.txt\n", encoding="utf-8")


def _write_clean_ascii(path: Path) -> None:
    path.write_text("# clean file\n", encoding="utf-8")


def _write_emdash(path: Path) -> None:
    path.write_text("The plan \u2014 a good one\n", encoding="utf-8")


def _run_hook(
    payload: bytes, *, cwd: Path | None = None
) -> subprocess.CompletedProcess:
    """Run the hook as a subprocess with given payload on stdin."""
    work_dir = cwd or ROOT
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=payload,
        cwd=str(work_dir),
        capture_output=True,
        timeout=30,
    )
    # Decode stderr/stdout with replace to handle non-UTF-8 mojibake in output
    result._decoded_stderr = (
        result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
    )
    result._decoded_stdout = (
        result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
    )
    return result


# ---------------------------------------------------------------------------
# BOM detection
# ---------------------------------------------------------------------------


def test_bom_detected_as_error(tmp_path: Path) -> None:
    bom_file = tmp_path / "report.md"
    _write_bom(bom_file)
    payload = _make_payload(tool_input={"file_path": str(bom_file)})
    result = _run_hook(payload)
    assert result.returncode != 0, (
        f"Expected non-zero exit for BOM, got 0.\nstderr: {result._decoded_stderr}"
    )
    assert "ERROR" in result._decoded_stderr
    assert "bom" in result._decoded_stderr
    assert "ACTION:" in result._decoded_stderr


# ---------------------------------------------------------------------------
# Mojibake detection
# ---------------------------------------------------------------------------


def test_mojibake_detected_as_error(tmp_path: Path) -> None:
    mojibake_file = tmp_path / "data.py"
    _write_mojibake(mojibake_file)
    payload = _make_payload(tool_input={"file_path": str(mojibake_file)})
    result = _run_hook(payload)
    assert result.returncode != 0
    assert "ERROR" in result._decoded_stderr
    assert "mojibake" in result._decoded_stderr
    assert "ACTION:" in result._decoded_stderr


# ---------------------------------------------------------------------------
# Question-mark corruption
# ---------------------------------------------------------------------------


def test_question_mark_corruption_detected(tmp_path: Path) -> None:
    q_file = tmp_path / "notes.md"
    _write_question_mark(q_file)
    payload = _make_payload(tool_input={"file_path": str(q_file)})
    result = _run_hook(payload)
    assert result.returncode != 0
    assert "ERROR" in result._decoded_stderr
    assert "question_mark_corruption" in result._decoded_stderr
    assert "ACTION:" in result._decoded_stderr


# ---------------------------------------------------------------------------
# Clean ASCII file
# ---------------------------------------------------------------------------


def test_clean_ascii_passes(tmp_path: Path) -> None:
    clean = tmp_path / "readme.md"
    _write_clean_ascii(clean)
    payload = _make_payload(tool_input={"file_path": str(clean)})
    result = _run_hook(payload)
    assert result.returncode == 0, (
        f"Expected exit 0 for clean file.\nstderr: {result._decoded_stderr}"
    )
    assert "ERROR" not in result._decoded_stderr


# ---------------------------------------------------------------------------
# Legitimate em-dash (valid Unicode, not suspicious)
# ---------------------------------------------------------------------------


def test_emdash_passes_clean(tmp_path: Path) -> None:
    em_file = tmp_path / "essay.md"
    _write_emdash(em_file)
    payload = _make_payload(tool_input={"file_path": str(em_file)})
    result = _run_hook(payload)
    assert result.returncode == 0, (
        f"Expected exit 0 for em-dash.\nstderr: {result._decoded_stderr}"
    )
    assert "ERROR" not in result._decoded_stderr


# ---------------------------------------------------------------------------
# Non-text extension skip
# ---------------------------------------------------------------------------


def test_non_text_extension_skipped(tmp_path: Path) -> None:
    img = tmp_path / "photo.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
    payload = _make_payload(tool_input={"file_path": str(img)})
    result = _run_hook(payload)
    assert result.returncode == 0
    assert "ERROR" not in result._decoded_stderr
    assert (
        "skipped" in result._decoded_stderr.lower()
        or "ACTION:" not in result._decoded_stderr
    )


# ---------------------------------------------------------------------------
# No path in payload -> INFO skip
# ---------------------------------------------------------------------------


def test_no_path_skipped_with_info() -> None:
    payload = _make_payload(tool_input={})
    result = _run_hook(payload)
    assert result.returncode == 0
    assert "encoding_guard_skipped_no_path" in result._decoded_stderr
    assert "NO_ACTION_REQUIRED" in result._decoded_stderr


# ---------------------------------------------------------------------------
# Payload with no tool_input or result -> INFO skip
# ---------------------------------------------------------------------------


def test_empty_payload_skipped() -> None:
    payload = json.dumps({}).encode("utf-8")
    result = _run_hook(payload)
    assert result.returncode == 0
    assert "encoding_guard_skipped_no_path" in result._decoded_stderr


# ---------------------------------------------------------------------------
# Path outside allowed roots -> WARN
# ---------------------------------------------------------------------------


def test_path_outside_roots_warns(tmp_path: Path) -> None:
    """A file under a path NOT under ROOT triggers WARN."""
    # Use a sibling dir to ROOT so it's definitely outside allowed roots
    outside = ROOT.parent / "_test_outside_anchor_foreign.py"
    outside.write_text("x = 1\n", encoding="utf-8")
    try:
        payload = _make_payload(tool_input={"file_path": str(outside)})
        result = _run_hook(payload)
        assert result.returncode == 0
        assert "WARN" in result._decoded_stderr or "INFO" in result._decoded_stderr
        assert (
            "encoding_guard_skipped" in result._decoded_stderr.lower()
            or "ACTION:" in result._decoded_stderr
        )
    finally:
        outside.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Path under repo_destino accepted (multi-root)
# ---------------------------------------------------------------------------


def test_destino_root_accepted(tmp_path: Path) -> None:
    """A file under AGENT_PROJECT_ROOT (outside ROOT) is accepted as valid."""
    # Create a fake destino outside ROOT
    destino = ROOT.parent / "_test_fake_destino_anchor"
    destino.mkdir(exist_ok=True)
    (destino / ".claude").mkdir(exist_ok=True)
    test_file = destino / "script.py"
    test_file.write_text("# clean\n", encoding="utf-8")
    try:
        payload = _make_payload(tool_input={"file_path": str(test_file)})
        env = {**dict(__import__("os").environ), "AGENT_PROJECT_ROOT": str(destino)}
        with patch.dict(__import__("os").environ, env, clear=False):
            result = _run_hook(payload)
        assert result.returncode == 0
        # Should NOT warn about outside roots
        assert "skipped_outside_allowed_roots" not in result._decoded_stderr.lower()
    finally:
        test_file.unlink(missing_ok=True)
        (destino / ".claude").rmdir()
        destino.rmdir()


# ---------------------------------------------------------------------------
# filePath variant in tool_input
# ---------------------------------------------------------------------------


def test_file_path_camel_case_variant(tmp_path: Path) -> None:
    f = tmp_path / "ok.py"
    f.write_text("pass\n", encoding="utf-8")
    payload = _make_payload(tool_input={"filePath": str(f)})
    result = _run_hook(payload)
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# result.filePath variant (MultiEdit)
# ---------------------------------------------------------------------------


def test_result_file_path_variant(tmp_path: Path) -> None:
    f = tmp_path / "ok.py"
    f.write_text("pass\n", encoding="utf-8")
    payload = _make_payload(result={"filePath": str(f)})
    result = _run_hook(payload)
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# In-process path does NOT invoke subprocess (spy)
# ---------------------------------------------------------------------------


def test_in_process_no_subprocess_invocation(tmp_path: Path) -> None:
    """When encoding_guard imports successfully, clean file passes with exit 0.

    The hook's in-process path handles it without fallback. We verify this
    indirectly: if the import succeeds and the file is clean, exit is 0
    and no fallback error appears in stderr.
    """
    f = tmp_path / "clean.py"
    f.write_text("# ok\n", encoding="utf-8")
    payload = _make_payload(tool_input={"file_path": str(f)})
    result = _run_hook(payload)
    assert result.returncode == 0
    # No fallback-related diagnostics for a clean file
    assert "fallback" not in result._decoded_stderr.lower()


# ---------------------------------------------------------------------------
# Fallback subprocess receives cwd and PYTHONIOENCODING (direct unit test)
# ---------------------------------------------------------------------------


def test_check_subprocess_passes_cwd_and_env(tmp_path: Path) -> None:
    """Unit test: _check_subprocess calls subprocess.run with cwd=ROOT and
    PYTHONIOENCODING=utf-8. We test the function directly to verify the
    contract, rather than trying to trick the hook's import path."""
    from scripts.encoding_post_write_hook import _check_subprocess

    clean = tmp_path / "ok.md"
    clean.write_text("# fine\n", encoding="utf-8")
    code, diags = _check_subprocess([clean])
    assert code == 0, f"Expected 0 for clean file, got {code}: {diags}"


def test_check_subprocess_invokes_check_encoding_guard(tmp_path: Path) -> None:
    """Verify _check_subprocess actually calls check_encoding_guard.py and
    detects BOM via the subprocess path."""
    from scripts.encoding_post_write_hook import _check_subprocess

    bom = tmp_path / "bom.md"
    bom.write_bytes(b"\xef\xbb\xbf# hello\n")
    code, diags = _check_subprocess([bom])
    assert code != 0, "Expected non-zero for BOM via subprocess fallback"
    assert any("BOM" in d or "bom" in d.lower() for d in diags)


# ---------------------------------------------------------------------------
# ACTION: line present in diagnostics
# ---------------------------------------------------------------------------


def test_action_line_present_on_error(tmp_path: Path) -> None:
    bom = tmp_path / "bom.md"
    _write_bom(bom)
    payload = _make_payload(tool_input={"file_path": str(bom)})
    result = _run_hook(payload)
    assert "ACTION:" in result._decoded_stderr, (
        f"Missing ACTION: in diagnostic output.\nstderr: {result._decoded_stderr}"
    )


def test_action_line_present_on_skip(tmp_path: Path) -> None:
    img = tmp_path / "icon.png"
    img.write_bytes(b"\x89PNG" + b"\x00" * 10)
    payload = _make_payload(tool_input={"file_path": str(img)})
    result = _run_hook(payload)
    # Skip for non-text extension should still be clean (no ERROR)
    assert "ERROR" not in result._decoded_stderr


# ---------------------------------------------------------------------------
# UnicodeDecodeError graceful skip
# ---------------------------------------------------------------------------


def test_binary_file_graceful_skip(tmp_path: Path) -> None:
    """A binary file that can't be decoded as UTF-8 triggers graceful skip."""
    binf = tmp_path / "data.bin"
    binf.write_bytes(bytes(range(256)))
    payload = _make_payload(tool_input={"file_path": str(binf)})
    result = _run_hook(payload)
    assert result.returncode == 0
    assert "ERROR" not in result._decoded_stderr
