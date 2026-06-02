#!/usr/bin/env python3
"""Audit project dependencies from uv.lock via pip-audit.

Exports all dependency groups from uv.lock to a temporary requirements.txt
and runs pip-audit against that surface. Guarantees:
- Only project dependencies are audited (not the system Python environment).
- All dependency groups (dev, test, etc.) are included.
- Results are reproducible from locked versions.

Used by .pre-commit-config.yaml pip-audit hook (pre-push stage).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent

    lockfile = project_root / "uv.lock"
    if not lockfile.exists():
        print("[pip-audit-project] ERROR: uv.lock not found", file=sys.stderr)
        return 1

    uv_cmd = shutil.which("uv")
    if uv_cmd is None:
        print("[pip-audit-project] ERROR: uv not found in PATH", file=sys.stderr)
        return 1

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, prefix="pip_audit_reqs_"
        ) as tmp:
            tmp_path = Path(tmp.name)

        export = subprocess.run(  # noqa: S603
            [
                uv_cmd,
                "export",
                "--all-groups",
                "--no-emit-project",
                "--no-hashes",
                "--locked",
                "--format",
                "requirements.txt",
                "--output-file",
                str(tmp_path),
            ],
            cwd=project_root,
            capture_output=True,
            text=True,
        )
        if export.returncode != 0:
            print(
                f"[pip-audit-project] uv export failed:\n{export.stderr}",
                file=sys.stderr,
            )
            return export.returncode

        lines = [
            ln
            for ln in tmp_path.read_text(encoding="utf-8").splitlines()
            if ln and not ln.startswith("#")
        ]
        print(f"[pip-audit-project] Auditing {len(lines)} packages from uv.lock")

        audit = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "pip_audit", "-r", str(tmp_path)],
            cwd=project_root,
        )
        return audit.returncode

    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
