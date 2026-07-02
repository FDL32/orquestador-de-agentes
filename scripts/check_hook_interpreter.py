"""Detect (and optionally repair) stale INSTALL_PYTHON paths in git hooks.

Before:
    pre-commit generates `.git/hooks/pre-commit` and `.git/hooks/pre-push` with
    a hardcoded `INSTALL_PYTHON='<abs path to interpreter>'` line. When the repo
    is moved, that path goes stale and no longer exists on disk.
During:
    The hook then falls through to the `command -v pre-commit` PATH fallback,
    which on some machines resolves to a broken launcher (e.g. a conda shim),
    so commits/pushes fail or run the wrong interpreter silently.
After:
    This check reads both hooks, verifies each `INSTALL_PYTHON` exists on disk,
    and either FAILS with an actionable message (default) or REGENERATES the
    hooks via `pre-commit install --overwrite` (`--fix`). It never versions the
    generated hooks; the deliverable is the check, not the hook.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent

# The two hook types pre-commit generates that embed INSTALL_PYTHON.
HOOK_TYPES = ("pre-commit", "pre-push")

# Line 7 of a generated hook: INSTALL_PYTHON='...'  or  INSTALL_PYTHON="..."
_INSTALL_PYTHON_RE = re.compile(
    r"""^\s*INSTALL_PYTHON=(?P<quote>['"])(?P<path>.*?)(?P=quote)\s*$""",
    re.MULTILINE,
)


@dataclass(frozen=True)
class HookStatus:
    """Result of inspecting one generated hook.

    Before: hook_type names one of HOOK_TYPES. During: parse + stat. After:
    `present` says the hook file exists; `interpreter` is the parsed path (None
    if absent/unparseable); `interpreter_ok` is True only when a parsed
    interpreter exists on disk.
    """

    hook_type: str
    present: bool
    interpreter: str | None
    interpreter_ok: bool

    @property
    def stale(self) -> bool:
        """A present hook with a parsed interpreter that does not exist on disk."""
        return self.present and self.interpreter is not None and not self.interpreter_ok


def parse_install_python(hook_text: str) -> str | None:
    """Extract the INSTALL_PYTHON path from a generated hook.

    Before: hook_text is the raw hook file. During: match the templated line.
    After: return the quoted path, or None if the line is absent/unparseable.
    """
    match = _INSTALL_PYTHON_RE.search(hook_text)
    if not match:
        return None
    return match.group("path")


def check_hook(hooks_dir: Path, hook_type: str) -> HookStatus:
    """Inspect one generated hook for a stale interpreter.

    Before: hooks_dir is a `.git/hooks` directory. During: read + parse + stat.
    After: return a HookStatus. An absent hook is not an error (present=False).
    """
    hook_path = hooks_dir / hook_type
    if not hook_path.is_file():
        return HookStatus(
            hook_type, present=False, interpreter=None, interpreter_ok=False
        )

    text = hook_path.read_text(encoding="utf-8", errors="replace")
    interpreter = parse_install_python(text)
    if interpreter is None:
        # Present hook without an INSTALL_PYTHON line: nothing to validate.
        return HookStatus(
            hook_type, present=True, interpreter=None, interpreter_ok=False
        )

    interpreter_ok = Path(interpreter).exists()
    return HookStatus(
        hook_type,
        present=True,
        interpreter=interpreter,
        interpreter_ok=interpreter_ok,
    )


def check_all(hooks_dir: Path) -> list[HookStatus]:
    """Inspect every managed hook type.

    Before: hooks_dir may or may not exist. During: check each HOOK_TYPE.
    After: return one HookStatus per hook type, in HOOK_TYPES order.
    """
    return [check_hook(hooks_dir, hook_type) for hook_type in HOOK_TYPES]


def _default_hooks_dir(repo_root: Path) -> Path:
    """Before: repo_root is a git repo. During: join. After: `.git/hooks` path."""
    return repo_root / ".git" / "hooks"


def _regenerate_hooks(repo_root: Path) -> subprocess.CompletedProcess[str]:
    """Regenerate hooks via `pre-commit install --overwrite` for both types.

    Before: pre-commit is importable in the current interpreter. During: run the
    module with the running interpreter (never the broken PATH one). After:
    return the completed process; caller inspects returncode.
    """
    return subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "pre_commit",
            "install",
            "--overwrite",
            "--hook-type",
            "pre-commit",
            "--hook-type",
            "pre-push",
        ],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _actionable_message(repo_root: Path, stale: list[HookStatus]) -> str:
    """Build the operator-facing remediation message for stale hooks."""
    lines = ["[check-hook-interpreter] FAIL: stale hook interpreter(s) detected."]
    lines.extend(
        f"  - {status.hook_type}: INSTALL_PYTHON does not exist on disk: "
        f"{status.interpreter}"
        for status in stale
    )
    lines.append(
        "  Fix: regenerate the hooks with the repo venv interpreter, e.g.\n"
        "    <repo>\\.venv\\Scripts\\python.exe -m pre_commit install --overwrite "
        "--hook-type pre-commit --hook-type pre-push"
    )
    lines.append(
        f"  Or run this check with --fix: python scripts/check_hook_interpreter.py "
        f"--fix (repo: {repo_root})"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Before: caller picks the repo and mode. During: inspect both hooks; with
    --fix, regenerate and re-inspect. After: return 0 when every present hook has
    an existing interpreter; 1 when a stale interpreter remains; 2 on error.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument(
        "--hooks-dir",
        type=Path,
        default=None,
        help="Override the hooks dir (default: <repo-root>/.git/hooks)",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Regenerate hooks via pre-commit install --overwrite when stale.",
    )
    args = parser.parse_args(argv)

    try:
        repo_root = args.repo_root.resolve()
        hooks_dir = (
            args.hooks_dir.resolve()
            if args.hooks_dir
            else _default_hooks_dir(repo_root)
        )

        statuses = check_all(hooks_dir)
        stale = [s for s in statuses if s.stale]

        if not stale:
            checked = (
                ", ".join(s.hook_type for s in statuses if s.present) or "none present"
            )
            print(f"[check-hook-interpreter] PASS: hook interpreters ok ({checked}).")
            return 0

        if args.fix:
            proc = _regenerate_hooks(repo_root)
            if proc.returncode != 0:
                print(
                    "[check-hook-interpreter] FAIL: regeneration failed "
                    f"(exit {proc.returncode}).\n{proc.stderr.strip()}",
                    file=sys.stderr,
                )
                return 1
            # Re-inspect to confirm the regeneration actually fixed the paths.
            statuses = check_all(hooks_dir)
            stale = [s for s in statuses if s.stale]
            if not stale:
                print(
                    "[check-hook-interpreter] PASS: regenerated hooks; "
                    "interpreters now exist on disk."
                )
                return 0
            print(_actionable_message(repo_root, stale), file=sys.stderr)
            return 1

        print(_actionable_message(repo_root, stale), file=sys.stderr)
        return 1

    except OSError as exc:
        print(f"[check-hook-interpreter] ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
