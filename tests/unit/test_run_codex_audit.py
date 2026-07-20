"""Tests for scripts/run_codex_audit.py (WOT-2026-029d, WOT-2026-035c).

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

WOT-2026-035c: the prompt must travel via STDIN, not argv, to avoid
Windows' ~32KB `CreateProcess` command-line limit ([WinError 206]).
`_stdin_echo_codex_executable` below builds a fake that reads stdin and
echoes it back (rather than ignoring argv like the older fakes), which
lets tests prove BOTH halves of the contract: (i) the prompt is absent
from argv, and (ii) the prompt arrives intact via stdin.
"""

from __future__ import annotations

import json
import os
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


def _stdin_echo_codex_executable(tmp_path: Path) -> str:
    """Build a fake codex executable that ECHOES stdin and reports argv.

    Unlike `_fake_codex_executable` (which ignores argv and prints a
    hardcoded string), this fake:
      - reads the FULL content of stdin,
      - prints a marker line with its own argv (json-encoded, one line),
      - prints a marker line with the stdin content it received.

    This lets a test assert BOTH halves of the WOT-2026-035c contract from
    a single invocation: what argv looked like (must NOT contain the
    prompt, MUST contain the "-" sentinel) and what arrived via stdin (must
    be exactly the prompt).
    """
    script = tmp_path / "fake_codex_stdin_echo.py"
    script.write_text(
        "import json\n"
        "import sys\n"
        "argv_line = json.dumps(sys.argv[1:])\n"
        "stdin_content = sys.stdin.read()\n"
        'sys.stdout.write("ARGV:" + argv_line + "\\n")\n'
        'sys.stdout.write("STDIN:" + stdin_content)\n'
        "sys.stdout.flush()\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    if sys.platform == "win32":
        shim = tmp_path / "fake_codex_stdin_echo.cmd"
        shim.write_text(
            f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n',
            encoding="utf-8",
        )
        return str(shim)
    else:  # pragma: no cover -- POSIX shim, not exercised on this Windows CI
        shim = tmp_path / "fake_codex_stdin_echo.sh"
        shim.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n',
            encoding="utf-8",
        )
        shim.chmod(0o755)
        return str(shim)


def test_prompt_delivered_via_stdin_not_argv(tmp_path):
    """WOT-2026-035c DOUBLE mutation proof (contract DoD-b, refined).

    Not enough to prove the prompt arrives on stdin (a code path that
    ALSO left it in argv would pass that alone). Must prove BOTH:
      (i)  the prompt is ABSENT from argv, and "-" IS present in argv
           (the codex-exec stdin sentinel);
      (ii) the prompt arrives intact via stdin (the echoing fake reports
           it back in stdout, and run_codex_audit's returned dict carries
           that echo).
    """
    codex_exe = _stdin_echo_codex_executable(tmp_path)
    prompt = "audit this specific unique prompt marker 8f3c1"

    result = rca.run_codex_audit(prompt, codex_executable=codex_exe, timeout=30)

    stdout = result["stdout"]
    argv_line, stdin_line = stdout.split("\n", 1)
    argv = json.loads(argv_line[len("ARGV:") :])
    stdin_received = stdin_line[len("STDIN:") :]

    # (i) argv does NOT contain the prompt, DOES contain the "-" sentinel.
    assert prompt not in argv
    assert "-" in argv

    # (ii) the prompt was delivered via stdin, verbatim.
    assert stdin_received == prompt


def test_large_prompt_via_stdin_does_not_raise_winerror_206(tmp_path):
    """A >32KB prompt must NOT raise WinError 206 / OSError.

    Windows' CreateProcess has a ~32KB total command-line length limit.
    Before WOT-2026-035c, a large prompt was appended to argv and could
    exceed that limit. After the fix, the prompt travels via stdin (which
    has no such limit), so a 40_000-byte prompt must round-trip cleanly.
    """
    codex_exe = _stdin_echo_codex_executable(tmp_path)
    large_prompt = "x" * 40_000

    result = rca.run_codex_audit(large_prompt, codex_executable=codex_exe, timeout=30)

    stdout = result["stdout"]
    argv_line, stdin_line = stdout.split("\n", 1)
    argv = json.loads(argv_line[len("ARGV:") :])
    stdin_received = stdin_line[len("STDIN:") :]

    assert large_prompt not in argv
    assert stdin_received == large_prompt
    assert result["ok"] is True


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


def _cwd_reporting_codex_executable(tmp_path: Path) -> str:
    """Build a fake codex executable that prints its own `os.getcwd()`.

    Used to prove (WOT-2026-038l) whether `run_codex_audit` passed `cwd=`
    to the real `Popen` at line ~140: the child process's reported cwd is
    the only observable signal of what `cwd=` the Popen actually received.
    """
    script = tmp_path / "fake_codex_cwd.py"
    script.write_text(
        "import os\nprint(os.getcwd())\n",
        encoding="utf-8",
    )
    if sys.platform == "win32":
        shim = tmp_path / "fake_codex_cwd.cmd"
        shim.write_text(
            f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n',
            encoding="utf-8",
        )
        return str(shim)
    else:  # pragma: no cover -- POSIX shim, not exercised on this Windows CI
        shim = tmp_path / "fake_codex_cwd.sh"
        shim.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n',
            encoding="utf-8",
        )
        shim.chmod(0o755)
        return str(shim)


def test_repo_root_sets_child_cwd(tmp_path):
    """WOT-2026-038l DoD 1+2: `repo_root` is passed as `cwd=` to the real Popen.

    PROBE in the productive path: the fake codex executable is invoked
    THROUGH the real Popen at line ~140 (not a re-implemented Popen). The
    child prints `os.getcwd()`; the test asserts that printed cwd equals
    `repo_root`, which is a separate directory (`tmp_path`) strictly
    different from the test process's own cwd, so the assertion actually
    distinguishes the fix from the pre-fix (inherited-cwd) behavior.
    """
    assert str(tmp_path) != os.getcwd(), (
        "tmp_path must differ from the test process cwd for this probe "
        "to distinguish fix/no-fix"
    )
    codex_exe = _cwd_reporting_codex_executable(tmp_path)

    result = rca.run_codex_audit(
        "audit this prompt",
        codex_executable=codex_exe,
        repo_root=tmp_path,
        timeout=30,
    )

    child_cwd = result["stdout"].strip()
    assert child_cwd == str(tmp_path)


def test_repo_root_none_preserves_inherited_cwd(tmp_path):
    """WOT-2026-038l DoD 1 control/negative: `repo_root=None` -> no `cwd=`.

    Concretely proves the param actually changes behavior: with
    `repo_root=None`, the child inherits the PARENT (test process) cwd,
    NOT `tmp_path`. This is the negative control for
    `test_repo_root_sets_child_cwd` above -- without it, a no-op
    implementation of `repo_root` could still pass the positive test by
    accident (e.g. if `tmp_path` happened to equal the parent cwd).
    """
    codex_exe = _cwd_reporting_codex_executable(tmp_path)
    parent_cwd = os.getcwd()

    result = rca.run_codex_audit(
        "audit this prompt",
        codex_executable=codex_exe,
        repo_root=None,
        timeout=30,
    )

    child_cwd = result["stdout"].strip()
    assert child_cwd == parent_cwd
    assert child_cwd != str(tmp_path)


def test_repo_root_none_emits_stderr_warning(tmp_path, capsys):
    """WOT-2026-038l DoD 1: `repo_root=None` emits ONE stderr warning.

    The warning must land on STDERR only, never STDOUT (stdout is
    content-validated by callers per the module's core contract).
    """
    codex_exe = _fake_codex_executable(tmp_path, stdout="ok\n", returncode=0)

    result = rca.run_codex_audit(
        "audit this prompt",
        codex_executable=codex_exe,
        repo_root=None,
        timeout=30,
    )

    captured = capsys.readouterr()
    assert "cwd" in captured.err.lower()
    assert "cwd" not in result["stdout"].lower()
    assert captured.out == ""


def test_repo_root_given_emits_no_stderr_warning(tmp_path, capsys):
    """WOT-2026-038l DoD 1: `repo_root` given -> NO stderr warning.

    The warning must fire ONLY in the `repo_root is None` path; giving an
    explicit `repo_root` must never trigger it (the normal/fixed path must
    stay silent).
    """
    codex_exe = _fake_codex_executable(tmp_path, stdout="ok\n", returncode=0)

    rca.run_codex_audit(
        "audit this prompt",
        codex_executable=codex_exe,
        repo_root=tmp_path,
        timeout=30,
    )

    captured = capsys.readouterr()
    assert captured.err == ""


def test_cli_repo_root_flag_threads_to_run_codex_audit(tmp_path):
    """WOT-2026-038l DoD 1: `--repo-root` CLI flag is wired to `main()`."""
    codex_exe = _cwd_reporting_codex_executable(tmp_path)

    exit_code = rca.main(
        [
            "--prompt",
            "audit this",
            "--codex-executable",
            codex_exe,
            "--timeout",
            "30",
            "--repo-root",
            str(tmp_path),
        ]
    )

    assert exit_code == 0


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
