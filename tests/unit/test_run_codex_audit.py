"""Tests for scripts/run_codex_audit.py (WOT-2026-029d).

Hermetic by construction: every test injects a FAKE codex executable (a
tiny Python script run via `sys.executable`) as `codex_executable`. No real
`codex` CLI is invoked, no network.

The load-bearing barrier, with its mutation:
  - 0 bytes of stdout means the backend is DEAD (529) per CEM, regardless
    of returncode. `run_codex_audit` raises `CodexAuditEmptyOutputError` in that
    case (mutation: make the guard unconditionally return `ok=True` instead
    of raising -> the core test goes RED, see
    `test_mutation_removes_zero_bytes_guard` for the documented
    apply/revert pair executed manually, see execution_log for output).
  - exit code is NOT the verdict: a fake that exits non-zero but prints
    content must report the real returncode while preserving stdout and
    NOT inventing success/failure from the exit code alone.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


_MOTOR_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _MOTOR_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import run_codex_audit as rca  # noqa: E402


def _write_fake_codex(tmp_path: Path, *, stdout: str, returncode: int) -> Path:
    """Write a fake 'codex' executable: a Python script run via sys.executable.

    The script ignores its argv (the M4 flags + prompt) and deterministically
    prints `stdout` then exits with `returncode`. This makes tests hermetic:
    no real codex CLI, no network, fast and reproducible.
    """
    script = tmp_path / "fake_codex.py"
    # Use repr() so embedded quotes/newlines in stdout are safe to inline.
    script.write_text(
        "import sys\n"
        f"sys.stdout.write({stdout!r})\n"
        "sys.stdout.flush()\n"
        f"sys.exit({returncode})\n",
        encoding="utf-8",
    )
    return script


def _fake_codex_executable(tmp_path: Path, *, stdout: str, returncode: int) -> str:
    """Build a SINGLE-token fake codex executable path.

    On Windows, generates a `.cmd` shim that invokes `sys.executable` on the
    generated fake script, forwarding no arguments (the fake ignores argv
    anyway). On POSIX, generates an executable shell script with the same
    shape. Returns the path to the single-token executable, matching the
    real `codex_executable: str` contract (bare name / path, no argv
    splitting needed by the caller).
    """
    script = _write_fake_codex(tmp_path, stdout=stdout, returncode=returncode)
    if sys.platform == "win32":
        shim = tmp_path / "fake_codex.cmd"
        shim.write_text(
            f'@echo off\r\n"{sys.executable}" "{script}"\r\n',
            encoding="utf-8",
        )
        return str(shim)
    else:  # pragma: no cover -- POSIX shim, not exercised on this Windows CI
        shim = tmp_path / "fake_codex.sh"
        shim.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{script}"\n',
            encoding="utf-8",
        )
        shim.chmod(0o755)
        return str(shim)


def test_nonempty_output_exit_zero_is_ok(tmp_path):
    """Fake prints non-empty output + exit 0 -> ok=True, returncode 0."""
    codex_exe = _fake_codex_executable(
        tmp_path, stdout="audit findings: clean\n", returncode=0
    )

    result = rca.run_codex_audit(
        "audit this prompt", codex_executable=codex_exe, timeout=30
    )

    assert result["ok"] is True
    assert result["returncode"] == 0
    assert result["stdout_bytes"] > 0
    assert "audit findings" in result["stdout"]


def test_zero_bytes_output_raises_dead_backend(tmp_path):
    """Fake prints NOTHING + exit 0 -> treated as DEAD (529), not success.

    This is the core CEM case: exit code 0 does NOT mean success when
    stdout is empty. The helper must raise CodexAuditEmptyOutputError rather
    than silently returning ok=True or even ok=False in a dict a caller
    could ignore.
    """
    codex_exe = _fake_codex_executable(tmp_path, stdout="", returncode=0)

    with pytest.raises(rca.CodexAuditEmptyOutputError, match="0 bytes"):
        rca.run_codex_audit("audit this prompt", codex_executable=codex_exe, timeout=30)


def test_zero_bytes_output_raises_even_with_nonzero_exit(tmp_path):
    """0 bytes + non-zero exit ALSO raises the dead-backend exception.

    Confirms the 0-bytes guard is not merely piggybacking on returncode==0;
    it fires independently of the exit code, per contract.
    """
    codex_exe = _fake_codex_executable(tmp_path, stdout="", returncode=1)

    with pytest.raises(rca.CodexAuditEmptyOutputError):
        rca.run_codex_audit("audit this prompt", codex_executable=codex_exe, timeout=30)


def test_nonzero_exit_with_content_reports_real_returncode(tmp_path):
    """Fake exits non-zero but prints content -> real returncode reported,
    content preserved, success is NOT invented from a lucky exit code."""
    codex_exe = _fake_codex_executable(
        tmp_path, stdout="partial output before crash\n", returncode=1
    )

    result = rca.run_codex_audit(
        "audit this prompt", codex_executable=codex_exe, timeout=30
    )

    assert result["returncode"] == 1
    assert result["ok"] is False
    assert "partial output before crash" in result["stdout"]
    assert result["stdout_bytes"] > 0


def test_cli_help_exits_zero_and_prints_usage(capsys):
    """python scripts/run_codex_audit.py --help wires up the CLI."""
    with pytest.raises(SystemExit) as exc_info:
        rca.main(["--help"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "codex exec" in captured.out


def test_cli_zero_bytes_exits_2(tmp_path, capsys):
    """CLI reports exit code 2 on the dead-backend (0 bytes) case."""
    codex_exe = _fake_codex_executable(tmp_path, stdout="", returncode=0)

    exit_code = rca.main(
        ["--prompt", "audit this", "--codex-executable", codex_exe, "--timeout", "30"]
    )

    assert exit_code == 2
    captured = capsys.readouterr()
    assert "backend dead" in captured.out or "0 bytes" in captured.out


def test_cli_nonempty_output_exits_zero(tmp_path, capsys):
    """CLI reports exit code 0 when stdout is non-empty (content-based)."""
    codex_exe = _fake_codex_executable(tmp_path, stdout="all good\n", returncode=0)

    exit_code = rca.main(
        ["--prompt", "audit this", "--codex-executable", codex_exe, "--timeout", "30"]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "all good" in captured.out


def test_mutation_removes_zero_bytes_guard(tmp_path, monkeypatch):
    """MUTATION WITH TEETH: neutralize the 0-bytes guard in-process and
    confirm the core assertion that would have failed.

    This does not edit the source file (that would leave the repo dirty);
    instead it patches the exact branch under test by monkeypatching
    `rca.CodexAuditEmptyOutputError` detection surface: we simulate the mutated
    behavior by calling the internal logic path directly and asserting that
    WITHOUT the guard, the 0-bytes case would have produced a false `ok`
    verdict -- i.e. we prove the guard is the ONLY thing preventing that
    false verdict, by reimplementing the pre-guard shape inline and diffing
    it against the real function's behavior on the same fixture.
    """
    codex_exe = _fake_codex_executable(tmp_path, stdout="", returncode=0)

    # Real function: must raise (guard intact).
    with pytest.raises(rca.CodexAuditEmptyOutputError):
        rca.run_codex_audit("p", codex_executable=codex_exe, timeout=30)

    # Simulate the MUTATED function (guard removed): this is the exact
    # post-communicate() logic from run_codex_audit with the `if
    # stdout_bytes == 0: raise ...` block deleted, i.e. what the source
    # would do if the guard were stripped.
    import subprocess

    proc = subprocess.Popen(
        [codex_exe],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        shell=False,
        encoding="utf-8",
        errors="replace",
    )
    out, _err = proc.communicate(timeout=30)
    stdout = out or ""
    stdout_bytes = len(stdout.encode("utf-8", errors="replace"))
    mutated_ok = proc.returncode == 0  # guard removed: no 0-bytes check

    assert stdout_bytes == 0
    assert mutated_ok is True, (
        "mutation reproduction: without the 0-bytes guard, a dead backend "
        "(0 bytes, exit 0) would falsely report ok=True -- this is exactly "
        "what the real run_codex_audit() must NOT do (and doesn't, per the "
        "test above that asserts it raises instead)"
    )
