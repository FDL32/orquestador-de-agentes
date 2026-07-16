#!/usr/bin/env python3
"""Run a command WITHOUT a pipe and report its REAL exit code (WOT-2026-022p).

Before:
    A caller wants the exit code of a command. The recurring trap: running
    ``cmd | tail`` and reading ``$?`` returns the exit of the LAST pipeline
    stage (``tail``), not of ``cmd``. A failing ``cmd`` whose output is piped
    thus looks like exit 0 -- the "autoengano-por-pipe" that fabricated a false
    fail-open verdict that reached memory (2026-07-11/12).

During:
    Runs argv as a single process (no shell, no pipe), capturing stdout+stderr.
    Prints the LAST N lines of the combined output for the human, then the REAL
    exit code of the command on its own line, and exits with that same code.

After:
    - stdout: the last N lines of the command output, then
      ``[run-and-exit] exit_code: <n>``.
    - process exit code == the command's real exit code (never the consumer's).
    - Exit 127 if the command cannot be launched (not found).

Usage:
    python scripts/tools/run_and_exit.py [--tail N] -- <cmd> [args...]

Prefer this over ``<cmd> | tail`` + ``$?`` whenever you need the exit code of a
command whose output you also want to skim.
"""

from __future__ import annotations

import argparse
import subprocess
import sys


def run_and_exit(cmd: list[str], tail: int = 20) -> int:
    """Run cmd as one process; print tail lines + real exit code; return it.

    Never reads a downstream consumer's exit: the returned code is the command's
    own ``returncode``.
    """
    if not cmd:
        print("[run-and-exit] ERROR: no command given", file=sys.stderr)
        return 2
    try:
        proc = subprocess.run(  # noqa: S603 - explicit argv, no shell
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        print(f"[run-and-exit] ERROR: command not found: {cmd[0]}", file=sys.stderr)
        return 127

    combined = (proc.stdout or "") + (proc.stderr or "")
    lines = combined.splitlines()
    for line in lines[-tail:] if tail > 0 else lines:
        print(line)
    # The REAL exit code of the command, never the consumer's.
    print(f"[run-and-exit] exit_code: {proc.returncode}")
    return proc.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a command without a pipe and report its real exit code."
    )
    parser.add_argument(
        "--tail",
        type=int,
        default=20,
        help="Print the last N lines of output (0 = all). Default 20.",
    )
    parser.add_argument(
        "cmd",
        nargs=argparse.REMAINDER,
        help="The command to run (put it after -- to avoid flag clashes).",
    )
    args = parser.parse_args(argv)

    cmd = args.cmd
    # argparse.REMAINDER keeps a leading "--"; strip one if present.
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    return run_and_exit(cmd, tail=args.tail)


if __name__ == "__main__":
    raise SystemExit(main())
