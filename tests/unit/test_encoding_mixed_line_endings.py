"""WOT-2026-069i: tests for find_mixed_line_endings and CLI integration.

Covers the pure function, CLI end-to-end, and baseline rc==0 cases.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent


class TestFindMixedLineEndings:
    """Tests for the pure function find_mixed_line_endings."""

    def test_mixed_crlf_lf_returns_snippets(self) -> None:
        """CRLF + bare LF → snippets with concrete line numbers."""
        from scripts.encoding_guard import find_mixed_line_endings

        # line1 CRLF line2 bare-LF line3 CRLF
        raw = b"line1\r\nline2\nline3\r\n"
        result = find_mixed_line_endings(raw)
        assert len(result) == 1
        assert "bare LF at line 2" in result

    def test_mixed_crlf_lf_cr_returns_snippets(self) -> None:
        """CRLF + bare LF + bare CR → bare LF at line 2, bare CR at line 3."""
        from scripts.encoding_guard import find_mixed_line_endings

        raw = b"line1\r\nline2\nline3\rline4\n"
        result = find_mixed_line_endings(raw)
        assert "bare LF at line 2" in result
        assert "bare LF at line 4" in result

    def test_crlf_only_returns_empty(self) -> None:
        """CRLF-only file is NOT flagged."""
        from scripts.encoding_guard import find_mixed_line_endings

        raw = b"line1\r\nline2\r\nline3\r\n"
        assert find_mixed_line_endings(raw) == []

    def test_lf_only_returns_empty(self) -> None:
        """LF-only file is NOT flagged."""
        from scripts.encoding_guard import find_mixed_line_endings

        raw = b"line1\nline2\nline3\n"
        assert find_mixed_line_endings(raw) == []

    def test_empty_bytes_returns_empty(self) -> None:
        """Empty file returns empty list."""
        from scripts.encoding_guard import find_mixed_line_endings

        assert find_mixed_line_endings(b"") == []

    def test_multiple_bare_lf_lines(self) -> None:
        """Multiple bare LF positions all reported."""
        from scripts.encoding_guard import find_mixed_line_endings

        # CRLF, bare LF, CRLF, bare LF, CRLF
        raw = b"a\r\nb\nc\r\nd\ne\r\n"
        result = find_mixed_line_endings(raw)
        assert len(result) == 2
        assert "bare LF at line 2" in result
        assert "bare LF at line 4" in result

    def test_only_bare_cr_and_crlf_returns_empty(self) -> None:
        """bare CR + CRLF (no bare LF) is NOT flagged."""
        from scripts.encoding_guard import find_mixed_line_endings

        raw = b"a\rb\r\nc\r\nd\re\r\n"
        result = find_mixed_line_endings(raw)
        assert result == []


class TestFindMixedLineEndingsRegression:
    """Regression tests: bare LF at position 0 and multi-count accuracy."""

    def test_bare_lf_at_position_0(self) -> None:
        """A file starting with bare LF is reported as mixed."""
        from scripts.encoding_guard import find_mixed_line_endings

        raw = b"\nfoo\r\n"
        result = find_mixed_line_endings(raw)
        assert len(result) >= 1
        assert "bare LF at line 1" in result

    def test_multiple_bare_lf_count(self) -> None:
        """Multiple bare LF positions all reported with correct count."""
        from scripts.encoding_guard import find_mixed_line_endings

        raw = b"\na\nb\r\n"
        result = find_mixed_line_endings(raw)
        assert len(result) == 2
        assert "bare LF at line 1" in result
        assert "bare LF at line 2" in result

    def test_bare_lf_only_crlf_mixed(self) -> None:
        """b'\\n\\r\\n' -> bare LF at line 1, bare CR at line 2, rc!=0."""
        from scripts.encoding_guard import find_mixed_line_endings

        raw = b"\n\r\n"
        result = find_mixed_line_endings(raw)
        assert len(result) >= 1
        assert "bare LF at line 1" in result


class TestCLIMixedLineEndings:
    """End-to-end CLI tests for check_encoding_guard.py."""

    def test_cli_mixed_file_returns_rc1(self, tmp_path: Path) -> None:
        """A file with mixed line endings causes check_encoding_guard to fail."""
        file_path = tmp_path / "mixed.md"
        file_path.write_bytes(b"line1\r\nline2\nline3\r\n")

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

        assert result.returncode == 1, result.stderr
        assert "Mixed line endings" in result.stderr
        assert "bare LF at lines 2" in result.stderr

    def test_cli_mixed_file_reports_crlf_total(self, tmp_path: Path) -> None:
        """The CLI output includes CRLF total count."""
        file_path = tmp_path / "mixed.md"
        file_path.write_bytes(b"a\r\nb\nc\r\n")

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
        assert "2 CRLF total" in result.stderr

    def test_cli_bare_lf_at_position_0(self, tmp_path: Path) -> None:
        """WOT-2026-069i fix 2: file starting with bare LF -> rc!=0, snippet 'line 1'."""
        file_path = tmp_path / "start_lf.md"
        file_path.write_bytes(b"\nfoo\r\n")

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

        assert result.returncode == 1, result.stderr
        assert "Mixed line endings" in result.stderr
        assert "at lines 1" in result.stderr

    def test_cli_multiple_bare_lf_snippets(self, tmp_path: Path) -> None:
        """WOT-2026-069i fix 2: b'\\na\\nb\\r\\n' -> '2 bare LF at lines 1, 2'."""
        file_path = tmp_path / "multi_lf.md"
        file_path.write_bytes(b"\na\nb\r\n")

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

        assert result.returncode == 1, result.stderr
        assert "2 bare LF" in result.stderr
        assert "at lines 1, 2" in result.stderr

    def test_cli_bare_lf_only_crlf_snippets(self, tmp_path: Path) -> None:
        """WOT-2026-069i fix 2: b'\\n\\r\\n' -> bare LF at line 1, rc!=0."""
        file_path = tmp_path / "bare_crlf.md"
        file_path.write_bytes(b"\n\r\n")

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

        assert result.returncode == 1, result.stderr
        assert "Mixed line endings" in result.stderr
        assert "bare LF" in result.stderr


class TestCLIBaseLinesRc0:
    """Baseline tests: files that must NOT trigger mixed line endings."""

    def test_crlf_only_passes(self, tmp_path: Path) -> None:
        file_path = tmp_path / "crlf.md"
        file_path.write_bytes(b"line1\r\nline2\r\nline3\r\n")

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

    def test_lf_only_passes(self, tmp_path: Path) -> None:
        file_path = tmp_path / "lf.md"
        file_path.write_bytes(b"line1\nline2\nline3\n")

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

    def test_lf_only_sh_passes(self, tmp_path: Path) -> None:
        file_path = tmp_path / "script.sh"
        file_path.write_bytes(b"#!/bin/bash\necho hello\n")

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

    def test_crlf_only_ps1_passes(self, tmp_path: Path) -> None:
        file_path = tmp_path / "script.ps1"
        file_path.write_bytes(b"# script\r\nWrite-Host hello\r\n")

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
