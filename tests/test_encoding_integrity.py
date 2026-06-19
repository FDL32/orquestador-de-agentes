"""Tests to ensure no encoding corruption exists in operational files."""

import subprocess
import sys

import pytest
from scripts.encoding_guard import (
    ALLOWLIST,
    ROOT,
    collect_files_to_check,
    file_issues,
    has_utf8_bom,
    is_in_scope,
    relative_path,
)


FILES_TO_CHECK = collect_files_to_check()


@pytest.mark.parametrize(
    "file_path",
    FILES_TO_CHECK,
    ids=lambda path: path.relative_to(ROOT).as_posix(),
)
def test_no_encoding_corruption_in_file(file_path):
    if not file_path.exists():
        pytest.skip(f"File {file_path} does not exist")

    rel = relative_path(file_path)
    if rel in ALLOWLIST:
        pytest.skip(f"Known dirty file pending cleanup: {rel}")

    mojibake, q_in_word, control_chars = file_issues(file_path)
    assert not mojibake, f"Mojibake detected in {rel}: {mojibake[:12]}"
    assert not q_in_word, (
        f"Question-mark corruption detected in {rel}: {q_in_word[:12]}"
    )
    assert not control_chars, f"Control chars detected in {rel}: {control_chars[:12]}"


@pytest.mark.parametrize("relative", sorted(ALLOWLIST))
def test_known_dirty_files_still_need_cleanup(relative):
    file_path = ROOT / relative
    assert file_path.exists(), f"Allowlist entry missing: {relative}"

    mojibake, q_in_word, control_chars = file_issues(file_path)
    assert mojibake or q_in_word or control_chars, (
        f"Allowlist entry is now clean and should be removed: {relative}"
    )


CORE_SCOPE_REGRESSION = [
    ".agent/agent_controller.py",
    ".agent/completion_checker.py",
    "scripts/update_project_map.py",
    "scripts/orquestador.py",
    "runtime/ui_state_projector.py",
    "bus/event_bus.py",
    "scripts/check_encoding_guard.py",
]


@pytest.mark.parametrize("relative", CORE_SCOPE_REGRESSION)
def test_hook_scope_matches_test_scope_for_core_files(relative):
    file_path = ROOT / relative
    assert file_path in FILES_TO_CHECK, (
        f"Regression fixture missing from test scope: {relative}"
    )
    assert is_in_scope(relative), f"Hook scope should include: {relative}"


def test_has_utf8_bom_detects_bom(tmp_path):
    file_path = tmp_path / "bom.md"
    file_path.write_bytes(b"\xef\xbb\xbf# hello\n")
    assert has_utf8_bom(file_path) is True


def test_check_encoding_guard_explicit_path_blocks_bom(tmp_path):
    file_path = tmp_path / "bom.md"
    file_path.write_bytes(b"\xef\xbb\xbf# hello\n")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "check_encoding_guard.py"),
            str(file_path),
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )

    assert result.returncode == 1
    assert "UTF-8 BOM detected" in result.stderr


@pytest.mark.parametrize("control_byte", [b"\x00", b"\x07", b"\x0b", b"\x0c"])
def test_check_encoding_guard_explicit_path_blocks_control_chars(
    tmp_path, control_byte
):
    """WOT-2026-010v: the CLI guard fails closed on disallowed ASCII control
    chars (the class that slipped past in 008f/008j)."""
    file_path = tmp_path / "corrupt.md"
    file_path.write_bytes(b"agent" + control_byte + b"controller\n")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "check_encoding_guard.py"),
            str(file_path),
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )

    assert result.returncode == 1
    assert "Control chars detected" in result.stderr


def test_check_encoding_guard_explicit_path_allows_tab_lf_cr(tmp_path):
    """Tab, LF, CR and CRLF are legitimate and must not trip the guard."""
    file_path = tmp_path / "clean.md"
    file_path.write_bytes(b"line1\twith tab\nline2\r\nline3\rline4\n")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "check_encoding_guard.py"),
            str(file_path),
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )

    assert result.returncode == 0, result.stderr
