"""Run a Codex M4-recipe audit invocation and validate its output by CONTENT.

Before:
    - `codex` (the ChatGPT/Codex CLI, shim `codex.cmd` on Windows, bare
      `codex` on POSIX) is resolvable on PATH, or an explicit executable is
      injected via `codex_executable` / `--codex-executable` for testing.
    - Caller has a prompt string ready, either literal (`--prompt`), from a
      file (`--prompt-file`), or piped via stdin (default when neither flag
      is given and stdin is not a TTY).
During:
    - Builds the "M4" command around `codex exec`:
      `codex exec --sandbox read-only --skip-git-repo-check
      -c service_tier=fast <prompt>`.
    - Launches it with `subprocess.Popen(..., stdin=subprocess.DEVNULL,
      stdout=PIPE, stderr=PIPE, text=True, shell=False, encoding="utf-8",
      errors="replace")`, mirroring the productive shape measured in
      `scripts/ensemble_dispatch.py::_transport_agent` (Windows
      pipe-inheritance hang, 2026-07-16 smoke).
    - On `subprocess.TimeoutExpired`, kills the FULL process tree (Windows:
      `taskkill /T /F`; POSIX: `os.kill(pid, SIGKILL)`) before raising,
      replicating the minimal shape of
      `scripts/ensemble_dispatch.py::_kill_process_tree` (not imported: that
      module pulls in `agents_config` + sys.path mutation at import time,
      which is unwanted weight for this narrow helper).
After:
    - Returns a structured dict: `returncode` (int), `stdout` (str),
      `stdout_bytes` (int, `len(stdout.encode("utf-8", errors="replace"))`),
      `ok` (bool), `reason` (str).
    - CEM hard-won lesson encoded here: exit code is NOT the verdict (codex
      can exit 0 on an Auth Error). The caller must validate by CONTENT.
      Per CEM, 0 bytes of stdout means the backend is DEAD (529), regardless
      of returncode. That case is UNAMBIGUOUS: this helper raises
      `CodexAuditEmptyOutputError` (a `RuntimeError` subclass) instead of
      returning `ok=False`, so a caller cannot silently ignore it by
      forgetting to check a dict key. All other outcomes (non-empty stdout,
      any returncode) return normally with `ok` reflecting `returncode == 0`
      and `reason` explaining the verdict.
    - CLI (`main`): exit 0 on non-empty output regardless of the wrapped
      command's own returncode (the wrapped returncode is reported in the
      printed JSON, per "exit code is not the verdict"); exit 2 on the
      0-bytes/dead case; exit 1 on invocation errors (e.g. codex binary not
      found, timeout).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


DEFAULT_CODEX_EXECUTABLE = "codex.cmd" if os.name == "nt" else "codex"
DEFAULT_TIMEOUT = 300
M4_ARGS = [
    "exec",
    "--sandbox",
    "read-only",
    "--skip-git-repo-check",
    "-c",
    "service_tier=fast",
]


class CodexAuditEmptyOutputError(RuntimeError):
    """Raised when the codex invocation produced 0 bytes of stdout.

    Per CEM: 0 bytes of output means the backend is DEAD (529), even if the
    process exited with returncode 0. Exit code is not the verdict; content
    is. Callers MUST handle this exception explicitly rather than trusting a
    dict-shaped `ok` flag that could be overlooked.
    """


def _kill_process_tree(pid: int) -> None:
    """Kill the FULL process tree of `pid` (Windows: taskkill /T /F).

    Minimal replica of `scripts/ensemble_dispatch.py::_kill_process_tree`
    (not imported to avoid that module's import-time sys.path mutation and
    `agents_config` dependency). Same rationale: `codex exec` via the
    `.cmd` shim on Windows spawns `node.exe`, which inherits the pipes; a
    plain kill of the direct child leaves `communicate()` blocked forever
    waiting on EOF from the surviving descendant (measured 2026-07-16).
    """
    if os.name == "nt":
        taskkill = (
            Path(os.environ.get("SYSTEMROOT", r"C:\Windows"))
            / "System32"
            / "taskkill.exe"
        )
        subprocess.run(  # noqa: S603
            [str(taskkill), "/T", "/F", "/PID", str(pid)],
            capture_output=True,
            timeout=30,
            shell=False,
        )
    else:  # pragma: no cover -- non-Windows branch
        import contextlib
        import signal

        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGKILL)


def run_codex_audit(
    prompt: str,
    *,
    codex_executable: str = DEFAULT_CODEX_EXECUTABLE,
    timeout: int = DEFAULT_TIMEOUT,
    extra_args: list[str] | None = None,
) -> dict:
    """Run `codex exec` with the M4 recipe and validate output by content.

    Before: `codex_executable` must be resolvable (bare name via PATH, or an
        injected path/script for tests). `prompt` is the audit instruction
        text passed as the final positional argument to `codex exec`.
    During: builds `[codex_executable, *M4_ARGS, *extra_args, prompt]` and
        runs it via `subprocess.Popen` with `stdin=DEVNULL`, capturing
        stdout+stderr as text (UTF-8, replace-on-error). On timeout, kills
        the process tree and re-raises as `TimeoutError` with diagnostic
        context (no silent success is invented).
    After: on 0-byte stdout, raises `CodexAuditEmptyOutputError` (backend is dead
        per CEM), regardless of returncode. Otherwise returns a dict with
        `returncode`, `stdout`, `stdout_bytes`, `ok` (`returncode == 0`),
        and `reason`.
    """
    cmd = [codex_executable, *M4_ARGS, *(extra_args or []), prompt]
    proc = subprocess.Popen(  # noqa: S603
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        shell=False,
        encoding="utf-8",
        errors="replace",
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc.pid)
        raise TimeoutError(
            f"codex exec timed out after {timeout}s; process tree killed "
            "(pipe-inheritance hang, see ensemble_dispatch.py 2026-07-16)"
        ) from None

    stdout = out or ""
    stdout_bytes = len(stdout.encode("utf-8", errors="replace"))

    if stdout_bytes == 0:
        raise CodexAuditEmptyOutputError(
            f"codex exec returned 0 bytes of stdout (returncode={proc.returncode}); "
            "0 bytes = backend dead (529), regardless of exit code. "
            f"stderr={err or ''!r}"
        )

    returncode = proc.returncode
    ok = returncode == 0
    reason = (
        "codex exec succeeded: non-empty stdout, returncode 0"
        if ok
        else f"codex exec returned non-zero exit ({returncode}) but produced "
        "non-empty stdout; content preserved, exit code is not the verdict"
    )
    return {
        "returncode": returncode,
        "stdout": stdout,
        "stdout_bytes": stdout_bytes,
        "ok": ok,
        "reason": reason,
    }


def _read_prompt(args: argparse.Namespace) -> str:
    if args.prompt is not None:
        return args.prompt
    if args.prompt_file is not None:
        return Path(args.prompt_file).read_text(encoding="utf-8")
    if sys.stdin.isatty():
        raise SystemExit(
            "no prompt provided: use --prompt, --prompt-file, or pipe via stdin"
        )
    return sys.stdin.read()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a Codex M4-recipe audit (codex exec --sandbox read-only "
            "--skip-git-repo-check -c service_tier=fast) and validate the "
            "result by CONTENT, not exit code."
        )
    )
    prompt_group = parser.add_mutually_exclusive_group()
    prompt_group.add_argument("--prompt", help="Literal prompt text.")
    prompt_group.add_argument(
        "--prompt-file", help="Path to a file containing the prompt text."
    )
    parser.add_argument(
        "--codex-executable",
        default=DEFAULT_CODEX_EXECUTABLE,
        help=f"Codex executable to invoke (default: {DEFAULT_CODEX_EXECUTABLE}).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"Timeout in seconds (default: {DEFAULT_TIMEOUT}).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint.

    Before: argv holds an optional --prompt / --prompt-file / stdin source.
    During: reads the prompt, invokes `run_codex_audit`, prints a JSON
        result to stdout.
    After: exit 0 when stdout was non-empty (regardless of the wrapped
        codex process's own returncode, which is reported inside the JSON
        body per "exit code is not the verdict"); exit 2 when codex
        produced 0 bytes of stdout (backend dead, CodexAuditEmptyOutputError);
        exit 1 on any other invocation error (binary not found, timeout).
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        prompt = _read_prompt(args)
    except SystemExit as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    try:
        result = run_codex_audit(
            prompt,
            codex_executable=args.codex_executable,
            timeout=args.timeout,
        )
    except CodexAuditEmptyOutputError as exc:
        print(json.dumps({"ok": False, "reason": str(exc)}, indent=2))
        return 2
    except (TimeoutError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0 if result["ok"] or result["stdout_bytes"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
