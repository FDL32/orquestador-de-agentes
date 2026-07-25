#!/usr/bin/env python3
r"""Guard: enforce MANIFEST.distribute as the distribution frontier (WOT-2026-025i).

Today check_distribution_agnostic audits AGNOSTICISM (leaks), but nobody enforces
that the manifest entries are valid. This guard closes that gap: it verifies every
manifest entry resolves to >=1 tracked file (no stale entries = no holes in the
frontier).

How it differs from check_distribution_agnostic:
  - That guard: "does what travels contain machine-specific names?" (AGNOSTICISM)
  - This guard: "does every manifest entry correspond to real tracked files?" (BOUNDARY)

The denominator is REUSED from check_distribution_agnostic via import (NOT
rewritten): build_denominator() and manifest_entries().

FAIL-CLOSED:
  - MANIFEST absent or empty -> exit 1
  - git ls-files fails -> exit 1
  - denominator empty -> exit 1
  - stale entry (resolves to 0 tracked files) -> exit 1

Publishes denominator on every path: "<N> entradas -> <M> ficheros versionados
auditados". A guard that doesn't publish its denominator cannot be distinguished
from "0 violations over 0 files".
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_distribution_agnostic import (
    build_denominator,
    manifest_entries,
)


MOTOR_ROOT = Path(__file__).resolve().parent.parent


def _git_ls_files(root: Path, entry: str) -> tuple[int, list[str]]:
    """(returncode, matched tracked paths) for `git ls-files -- <entry>`."""
    git = shutil.which("git")
    if git is None:
        return 1, []
    try:
        p = subprocess.run(  # noqa: S603 - git resuelto por shutil.which, args fijos
            [git, "ls-files", "--", entry],
            capture_output=True,
            text=True,
            cwd=str(root),
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 1, []
    files = [ln.strip() for ln in p.stdout.splitlines() if ln.strip()]
    return p.returncode, files


def audit(root: Path) -> tuple[int, list[str]]:
    """Return (exit_code, output_lines). Publishes denominator on every path."""
    out: list[str] = []

    entries = manifest_entries(root)
    if not entries:
        out.append("[dist-boundary] ERROR: MANIFEST.distribute is missing or empty")
        out.append("[dist-boundary] 0 entradas -> 0 ficheros (FAIL-CLOSED)")
        return 1, out

    n_entries, files, err = build_denominator(root)
    if err is not None:
        out.append(f"[dist-boundary] ERROR: {err}")
        out.append(
            f"[dist-boundary] {n_entries} entradas -> 0 ficheros versionados "
            "auditados (FAIL-CLOSED)"
        )
        return 1, out

    out.append(
        f"[dist-boundary] {n_entries} entradas -> {len(files)} ficheros versionados "
        "auditados"
    )

    stale_entries: list[str] = []
    for entry in entries:
        rc, matched = _git_ls_files(root, entry)
        if rc != 0:
            stale_entries.append(f"  {entry} (git ls-files failed, rc={rc})")
        elif not matched:
            stale_entries.append(f"  {entry} (0 tracked files)")

    if stale_entries:
        out.append(
            "[dist-boundary] ERROR: stale manifest entry (resolves to 0 tracked "
            "files = hole in the frontier):"
        )
        out.extend(stale_entries)
        return 1, out

    out.append("[dist-boundary] OK: all manifest entries resolve to tracked files.")
    return 0, out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--motor-root", default=str(MOTOR_ROOT))
    args = ap.parse_args(argv)
    root = Path(args.motor_root).resolve()
    code, lines = audit(root)
    stream = sys.stderr if code else sys.stdout
    for ln in lines:
        print(ln, file=stream)
    return code


if __name__ == "__main__":
    sys.exit(main())
