#!/usr/bin/env python3
"""Normalize a POSIX/MSYS path to a literal Windows path (WOT-2026-022p).

Before:
    A caller has a path in MSYS/Git-Bash form such as ``/c/Users/x/y`` and needs
    to hand it to pathlib or a Windows tool. Passing ``/c/Users/x/y`` straight to
    ``pathlib.Path`` yields ``C:\\c\\Users\\x\\y`` -- a nonexistent path that
    produced 4 false negatives in a single session (2026-07-11/12).

During:
    Detects an MSYS drive prefix (``/c/`` .. ``/z/``) and rewrites it to
    ``C:\\``. Converts forward slashes to backslashes. Leaves an already-Windows
    path (``C:\\...`` or ``C:/...``) intact except for slash normalization.

After:
    Returns the literal Windows path string. Never touches the filesystem (pure
    string transform); it does not require the path to exist.

Usage:
    python scripts/tools/winpath.py /c/Users/x/y      ->  C:\\Users\\x\\y
    from scripts.tools.winpath import to_windows_path  (import form)

Prefer this over hand-passing a ``/c/...`` path to pathlib on Windows.
"""

from __future__ import annotations

import argparse
import re


# /c/... or /C/... (single drive letter followed by a slash or end of string).
_MSYS_DRIVE_RE = re.compile(r"^/([a-zA-Z])(/.*)?$")


def to_windows_path(path: str) -> str:
    """Convert an MSYS/POSIX path to a literal Windows path string (pure).

    ``/c/Users/x`` -> ``C:\\Users\\x``; ``C:/a`` -> ``C:\\a``; ``rel/x`` ->
    ``rel\\x``. An empty string returns empty.
    """
    if not path:
        return path
    match = _MSYS_DRIVE_RE.match(path)
    if match:
        drive = match.group(1).upper()
        rest = match.group(2) or ""
        # rest starts with "/" (or is empty); strip the leading slash then join.
        rest = rest[1:] if rest.startswith("/") else rest
        win = f"{drive}:\\" + rest.replace("/", "\\")
        return win
    # Already Windows-ish or relative: just normalize slashes.
    return path.replace("/", "\\")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Normalize an MSYS/POSIX path to a literal Windows path."
    )
    parser.add_argument("path", help="The path to normalize.")
    args = parser.parse_args(argv)
    print(to_windows_path(args.path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
