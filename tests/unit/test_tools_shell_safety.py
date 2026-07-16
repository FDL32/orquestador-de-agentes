"""Tests for the shell-safety wrappers (WOT-2026-022p).

run_and_exit.py: must report the REAL exit code of the command it runs, never
a downstream consumer's -- the anti-trap for `cmd | tail` + `$?`.

winpath.py: must convert an MSYS `/c/...` path to a literal Windows path, never
the broken `C:\\c\\...` that pathlib would produce.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TOOLS = PROJECT_ROOT / "scripts" / "tools"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"tools_{name}", TOOLS / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


run_and_exit = _load("run_and_exit")
winpath = _load("winpath")


# ---- run_and_exit -----------------------------------------------------------


def test_reports_real_exit_of_failing_command(capsys):
    """DoD (mutation target): a command that exits non-zero is reported with its
    REAL exit code, not 0.

    This is the anti-trap for `cmd | tail` + `$?`: the pipe would have masked
    the failure. Here run_and_exit runs the command directly, so the failure is
    visible.

    Mutation: make run_and_exit return 0 (or read a consumer's code) and this
    test fails.
    """
    rc = run_and_exit.run_and_exit([sys.executable, "-c", "import sys; sys.exit(7)"])
    assert rc == 7, "run_and_exit must return the command's real exit code"
    out = capsys.readouterr().out
    assert "[run-and-exit] exit_code: 7" in out


def test_reports_zero_for_success(capsys):
    rc = run_and_exit.run_and_exit([sys.executable, "-c", "print('ok')"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "ok" in out
    assert "[run-and-exit] exit_code: 0" in out


def test_tail_limits_output(capsys):
    code = "for i in range(100): print(i)"
    run_and_exit.run_and_exit([sys.executable, "-c", code], tail=3)
    out_lines = capsys.readouterr().out.splitlines()
    # last 3 command lines (97,98,99) + the exit_code line = 4 lines total
    assert out_lines == ["97", "98", "99", "[run-and-exit] exit_code: 0"]


def test_missing_command_returns_127(capsys):
    rc = run_and_exit.run_and_exit(["this_command_does_not_exist_xyz"])
    assert rc == 127


def test_empty_command_is_error():
    assert run_and_exit.run_and_exit([]) == 2


def test_main_strips_leading_double_dash(capsys):
    rc = run_and_exit.main(
        ["--tail", "5", "--", sys.executable, "-c", "import sys; sys.exit(3)"]
    )
    assert rc == 3


def test_main_runs_command_after_double_dash(capsys):
    rc = run_and_exit.main(["--", sys.executable, "-c", "import sys; sys.exit(4)"])
    assert rc == 4


# ---- winpath ----------------------------------------------------------------


def test_msys_drive_path_becomes_windows():
    assert winpath.to_windows_path("/c/Users/x/y") == "C:\\Users\\x\\y"


def test_msys_drive_uppercased():
    assert winpath.to_windows_path("/d/data") == "D:\\data"


def test_bare_drive_root():
    assert winpath.to_windows_path("/c/") == "C:\\"
    assert winpath.to_windows_path("/c") == "C:\\"


def test_already_windows_path_slashes_normalized():
    assert winpath.to_windows_path("C:/a/b") == "C:\\a\\b"


def test_relative_path_slashes_only():
    assert winpath.to_windows_path("rel/x/y") == "rel\\x\\y"


def test_empty_stays_empty():
    assert winpath.to_windows_path("") == ""


def test_not_broken_c_c_path():
    """The specific bug: /c/... must NOT become C:\\c\\... (the pathlib trap)."""
    result = winpath.to_windows_path("/c/Users/fdl")
    assert "\\c\\" not in result
    assert result.startswith("C:\\")
