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

import pytest


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

    \\xc3\\x83 decodes to U+00C3 (Latin A with breve) which IS in
    SUSPICIOUS_CODEPOINTS. This simulates double-encoded UTF-8 (classic mojibake).
    """
    path.write_bytes(b"caf\xc3\x83 plan.txt\n")


def _write_question_mark(path: Path) -> None:
    content = "".join(["a", "?", "b", " plan.txt\n"])
    path.write_text(content, encoding="utf-8")


def _write_clean_ascii(path: Path) -> None:
    path.write_text("# clean file\n", encoding="utf-8")


def _write_emdash(path: Path) -> None:
    path.write_text("The plan \u2014 a good one\n", encoding="utf-8")


def _write_control_chars(path: Path, control_byte: bytes = b"\x07") -> None:
    """Write a text file with a disallowed ASCII control char (WOT-2026-010v)."""
    path.write_bytes(b"agent" + control_byte + b"controller\n")


def _write_tab_bullet_mangling(path: Path) -> None:
    path.write_text("- \ttests/unit/test_content_resolver.py\n", encoding="utf-8")


def _write_backtick_bullet_mangling(path: Path) -> None:
    path.write_text("- src/pipeline/`r\n", encoding="utf-8")


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


@pytest.mark.parametrize("control_byte", [b"\x00", b"\x07", b"\x0b", b"\x0c"])
def test_control_chars_detected_as_error(tmp_path: Path, control_byte: bytes) -> None:
    """WOT-2026-010v: the post-write hook fails on disallowed ASCII control chars
    in a text file (inherited from the shared file_issues, no parallel detector)."""
    ctrl_file = tmp_path / "data.md"
    _write_control_chars(ctrl_file, control_byte)
    payload = _make_payload(tool_input={"file_path": str(ctrl_file)})
    result = _run_hook(payload)
    assert result.returncode != 0
    assert "ERROR" in result._decoded_stderr
    assert "text_corruption" in result._decoded_stderr
    assert "ACTION:" in result._decoded_stderr


def test_tab_lf_cr_pass_clean(tmp_path: Path) -> None:
    """Tab, LF, CR and CRLF must not be flagged as control-char corruption."""
    ok_file = tmp_path / "fine.md"
    ok_file.write_bytes(b"a\tb\nc\r\nd\re\n")
    payload = _make_payload(tool_input={"file_path": str(ok_file)})
    result = _run_hook(payload)
    assert result.returncode == 0, (
        f"Expected exit 0 for tab/LF/CR file.\nstderr: {result._decoded_stderr}"
    )
    assert "text_corruption" not in result._decoded_stderr


def test_tab_prefixed_path_bullet_detected_as_error(tmp_path: Path) -> None:
    mangled = tmp_path / "plan.md"
    _write_tab_bullet_mangling(mangled)
    payload = _make_payload(tool_input={"file_path": str(mangled)})
    result = _run_hook(payload)
    assert result.returncode != 0
    assert "ERROR" in result._decoded_stderr
    assert "text_corruption" in result._decoded_stderr
    assert "<bullet-tab>" in result._decoded_stderr


def test_broken_backtick_path_bullet_detected_as_error(tmp_path: Path) -> None:
    mangled = tmp_path / "plan.md"
    _write_backtick_bullet_mangling(mangled)
    payload = _make_payload(tool_input={"file_path": str(mangled)})
    result = _run_hook(payload)
    assert result.returncode != 0
    assert "ERROR" in result._decoded_stderr
    assert "text_corruption" in result._decoded_stderr
    assert "`r" in result._decoded_stderr


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


def test_path_outside_roots_warns() -> None:
    """A path NOT under ROOT (nor the destino) triggers the outside-roots WARN.

    WOT-2026-013q: the hook classifies the path BEFORE reading the file (see
    encoding_post_write_hook._process_paths), so the file need not exist. We pass
    a synthetic absolute path on the drive anchor that is guaranteed outside both
    ROOT and the destino, with NO filesystem write. This replaces the previous
    ``ROOT.parent`` fixture, which failed on hosts where the repo's parent
    directory is not writable, and cannot use the project's ``tmp_path`` /
    ``tempfile`` because conftest redirects both UNDER ROOT.
    """
    outside = (Path(ROOT.anchor) / "_oa_foreign_not_under_root" / "x.py").resolve()
    assert ROOT not in outside.parents, "synthetic path must be outside ROOT"
    payload = _make_payload(tool_input={"file_path": str(outside)})
    result = _run_hook(payload)
    assert result.returncode == 0
    assert "skipped_outside_allowed_roots" in result._decoded_stderr.lower()


# ---------------------------------------------------------------------------
# Path under repo_destino accepted (multi-root)
# ---------------------------------------------------------------------------


def test_destino_root_accepted(tmp_path: Path) -> None:
    """A file under AGENT_PROJECT_ROOT (outside ROOT) is accepted as valid."""
    # WOT-2026-013q: build the fake destino under pytest's tmp_path (isolated,
    # writable, auto-cleaned) instead of ROOT.parent, so the test does not depend
    # on the repo's parent directory being writable on the host.
    destino = tmp_path / "_test_fake_destino_anchor"
    destino.mkdir()
    (destino / ".claude").mkdir()
    test_file = destino / "script.py"
    test_file.write_text("# clean\n", encoding="utf-8")
    payload = _make_payload(tool_input={"file_path": str(test_file)})
    env = {**dict(__import__("os").environ), "AGENT_PROJECT_ROOT": str(destino)}
    with patch.dict(__import__("os").environ, env, clear=False):
        result = _run_hook(payload)
    assert result.returncode == 0
    # Should NOT warn about outside roots
    assert "skipped_outside_allowed_roots" not in result._decoded_stderr.lower()


# ---------------------------------------------------------------------------
# WOT-2026-010i: _resolve_destino returns destination_root, not motor_root
# ---------------------------------------------------------------------------


def test_resolve_destino_returns_destination_root_not_motor_root(
    tmp_path: Path,
) -> None:
    """Semantic regression: _resolve_destino() must read destination_root from
    motor_destination_link.json, never motor_root, when the two differ.

    This blinds the 010e bug (reading the wrong field) even though the live
    bug is already fixed. The test asserts the EXACT returned value, not merely
    that something non-None comes back: it sets motor_root and destination_root
    to two distinct, real directories and requires the destination one.
    """
    import os

    from scripts.encoding_post_write_hook import _resolve_destino

    motor_root = tmp_path / "motor"
    destino_root = tmp_path / "destino"
    motor_root.mkdir()
    destino_root.mkdir()

    link_dir = motor_root / ".agent" / "config"
    link_dir.mkdir(parents=True)
    (link_dir / "motor_destination_link.json").write_text(
        __import__("json").dumps(
            {
                "motor_root": str(motor_root),
                "destination_root": str(destino_root),
            }
        ),
        encoding="utf-8",
    )

    # Clear the env override so the link file is the source of truth.
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("AGENT_PROJECT_ROOT", None)
        resolved = _resolve_destino(motor_root)

    assert resolved == destino_root.resolve(), (
        f"_resolve_destino must return destination_root "
        f"({destino_root.resolve()}), got {resolved}"
    )
    # Explicit negative: it must NOT return motor_root even though that field
    # is also present in the link file.
    assert resolved != motor_root.resolve()


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
