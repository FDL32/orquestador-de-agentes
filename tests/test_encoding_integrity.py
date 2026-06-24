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

    mojibake, q_in_word, text_corruption = file_issues(file_path)
    assert not mojibake, f"Mojibake detected in {rel}: {mojibake[:12]}"
    assert not q_in_word, (
        f"Question-mark corruption detected in {rel}: {q_in_word[:12]}"
    )
    assert not text_corruption, (
        f"Text corruption detected in {rel}: {text_corruption[:12]}"
    )


@pytest.mark.parametrize("relative", sorted(ALLOWLIST))
def test_known_dirty_files_still_need_cleanup(relative):
    file_path = ROOT / relative
    assert file_path.exists(), f"Allowlist entry missing: {relative}"

    mojibake, q_in_word, text_corruption = file_issues(file_path)
    assert mojibake or q_in_word or text_corruption, (
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
    assert "Text corruption detected" in result.stderr


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


def test_check_encoding_guard_blocks_tab_prefixed_path_bullet(tmp_path):
    file_path = tmp_path / "corrupt.md"
    file_path.write_text("- \ttests/unit/test_content_resolver.py\n", encoding="utf-8")

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
    assert "Text corruption detected" in result.stderr
    assert "<bullet-tab>" in result.stderr


@pytest.mark.parametrize("frag", ["`r", "`n", "`t"])
def test_check_encoding_guard_blocks_broken_backtick_path_bullet(tmp_path, frag):
    """WOT-2026-013q: the broken-backtick path-bullet fragment is caught for the
    whole `[rnt] family (the same heredoc escape mechanism emits `r/`n/`t)."""
    file_path = tmp_path / "corrupt.md"
    file_path.write_text(f"- src/pipeline/{frag}\n", encoding="utf-8")

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
    assert "Text corruption detected" in result.stderr
    assert frag in result.stderr


def test_check_encoding_guard_allows_legit_inline_code_bullet(tmp_path):
    """WOT-2026-013q non-regression: a legitimate inline-code bullet and a clean
    path bullet must NOT trip the path-bullet mangling detector."""
    file_path = tmp_path / "clean.md"
    file_path.write_text(
        "- use `ruff` to lint\n- src/pipeline/content_resolver.py\n- the `-n` flag\n",
        encoding="utf-8",
    )

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


# WOT-2026-011f: PowerShell sources are under the repo-wide guard scope.


def test_launcher_ps1_is_in_guard_scope():
    """The real launcher .ps1 must be inside the guard's repo-wide scope, so its
    BOM/mojibake would be caught (it carried both before 011f). PASS-with: the
    GLOB now includes scripts/**/*.ps1, so the launcher is collected."""
    launcher = ROOT / "scripts" / "launch_agent_terminals.ps1"
    assert is_in_scope(relative_path(launcher)), (
        "launch_agent_terminals.ps1 must be in encoding-guard scope (GLOB)"
    )
    assert launcher in set(collect_files_to_check()), (
        "launcher .ps1 must be collected by the repo-wide guard sweep"
    )


def test_launcher_ps1_is_clean_no_bom_no_mojibake():
    """The launcher itself must be UTF-8 clean after 011f: no BOM, no mojibake."""
    launcher = ROOT / "scripts" / "launch_agent_terminals.ps1"
    assert not has_utf8_bom(launcher), "launcher must have no UTF-8 BOM"
    mojibake, _q_in_word, text_corruption = file_issues(launcher)
    assert not mojibake, f"launcher mojibake: {mojibake[:12]}"
    assert not text_corruption, f"launcher text corruption: {text_corruption[:12]}"


def test_dirty_ps1_would_be_blocked(tmp_path):
    """FAIL-without barrier: a .ps1 carrying BOM + mojibake (the pre-011f launcher
    state) is detected by the guard's issue scanner. Proves the .ps1 scope is real,
    not cosmetic. If the launcher regressed to BOM+mojibake, the parametrized
    test_no_encoding_corruption_in_file would fail because it is now in scope."""
    dirty = tmp_path / "dirty.ps1"
    # BOM + classic double-encoded mojibake ('canÃ³nico') as the launcher had.
    dirty.write_bytes("﻿# artefacto canÃ³nico\n".encode())
    assert has_utf8_bom(dirty), "fixture must carry a BOM"
    mojibake, _q, _c = file_issues(dirty)
    assert mojibake, "guard must flag mojibake in a dirty .ps1"
