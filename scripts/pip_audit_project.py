#!/usr/bin/env python3
"""Audit project dependencies from uv.lock via pip-audit.

Exports all dependency groups from uv.lock to a temporary requirements.txt
and runs pip-audit against that surface. Guarantees:
- Only project dependencies are audited (not the system Python environment).
- All dependency groups (dev, test, etc.) are included.
- Results are reproducible from locked versions.

Used by .pre-commit-config.yaml pip-audit hook (pre-push and manual stages,
language: system via uv run). Fails closed when the running interpreter
does not match the requires-python floor while the uv.lock export
carries python_version / python_full_version markers.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib


def _ignored_vulnerabilities(project_root: Path) -> list[str]:
    """Return pip-audit vulnerability IDs explicitly ignored by project policy."""
    pyproject = project_root / "pyproject.toml"
    if not pyproject.exists():
        return []

    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    ignore_vuln = data.get("tool", {}).get("pip-audit", {}).get("ignore-vuln", [])
    if not isinstance(ignore_vuln, list):
        return []
    return [vuln for vuln in ignore_vuln if isinstance(vuln, str) and vuln.strip()]


def _requires_python_floor(project_root: Path) -> tuple[int, int] | None:
    """Read requires-python from pyproject.toml and return its lower bound.

    Before: project_root path is provided (file may or may not exist).
    During: parses [project].requires-python with tomllib, extracts the
        >=X.Y lower bound as a (X, Y) tuple.
    After: returns (X, Y) for a lower bound, None if the key is missing,
        the file is absent, or the expression has no lower bound.
    """
    pyproject = project_root / "pyproject.toml"
    if not pyproject.exists():
        return None
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except Exception:
        return None
    spec = data.get("project", {}).get("requires-python")
    if not isinstance(spec, str):
        return None
    for part in spec.split(","):
        part = part.strip()
        if part.startswith(">="):
            ver_str = part[2:].strip()
            parts = ver_str.split(".")
            try:
                return (int(parts[0]), int(parts[1]))
            except (ValueError, IndexError):
                return None
    return None


def _export_has_python_markers(requirements_text: str) -> bool:
    """Check if any requirement line carries a python_version marker.

    Before: requirements_text is the content of the uv.lock export.
    During: scans non-empty, non-comment lines for python_version or
        python_full_version substrings.
    After: returns True if at least one marker is found, False otherwise.
    """
    for line in requirements_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "python_version" in stripped or "python_full_version" in stripped:
            return True
    return False


def _running_version() -> tuple[int, int, int]:
    """Return the running Python version as (major, minor, micro).

    Before: nothing.
    During: reads sys.version_info and truncates to three integers.
    After: returns a 3-tuple representing the exact runtime version.
    """
    return tuple(sys.version_info[:3])


def _interpreter_problem(
    project_root: Path,
    requirements_text: str,
    version: tuple[int, int, int],
) -> str | None:
    """Detect interpreter mismatch between runtime and requires-python floor.

    Before: project_root, requirements_text, and version are provided.
    During: checks for python markers in the export; if absent returns None.
        If markers are present and no floor is determinable returns an error.
        If markers are present and floor differs from version returns an error.
    After: returns None on acceptance, or an ASCII error message on rejection.
    """
    if not _export_has_python_markers(requirements_text):
        return None

    floor = _requires_python_floor(project_root)
    ver_str = f"{version[0]}.{version[1]}.{version[2]}"

    if floor is None:
        return (
            "[pip-audit-project] ERROR: uv.lock export carries python "
            "version markers but requires-python lower bound is "
            "indeterminable; cannot verify interpreter compatibility"
        )

    if version[:2] != floor:
        return (
            f"[pip-audit-project] ERROR: running Python {ver_str} does not "
            f"match the requires-python floor {floor[0]}.{floor[1]}; "
            "pip-audit will only audit dependency branches satisfied by "
            f"Python {ver_str}. Remediate with: uv sync --python {floor[0]}.{floor[1]} "
            f"and then: uv run --frozen python scripts/pip_audit_project.py"
        )

    return None


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

        version = _running_version()
        floor = _requires_python_floor(project_root)
        floor_str = f"{floor[0]}.{floor[1]}" if floor else "indeterminable"
        print(
            f"[pip-audit-project] Interpreter: CPython {version[0]}.{version[1]}.{version[2]} "
            f"(requires-python floor: {floor_str})"
        )

        problem = _interpreter_problem(
            project_root, tmp_path.read_text(encoding="utf-8"), version
        )
        if problem:
            print(problem, file=sys.stderr)
            return 1

        audit_cmd = [sys.executable, "-m", "pip_audit", "-r", str(tmp_path)]
        for vuln_id in _ignored_vulnerabilities(project_root):
            audit_cmd.extend(["--ignore-vuln", vuln_id])

        audit = subprocess.run(  # noqa: S603
            audit_cmd,
            cwd=project_root,
        )
        return audit.returncode

    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
