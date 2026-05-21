"""Policy deciding whether to run pip-audit based on the active dependency surface."""

from __future__ import annotations

import re
from pathlib import Path


DEPENDENCY_SURFACE_PATTERNS = [
    r"pyproject\.toml",
    r"uv\.lock",
    r"requirements.*\.txt",
    r"setup\.py",
    r"setup\.cfg",
    r"Pipfile",
    r"Pipfile\.lock",
    r"poetry\.lock",
]


def _looks_like_path_token(token: str) -> bool:
    if not token or " " in token:
        return False
    if token.startswith("."):
        return True
    if "/" in token or "\\" in token:
        return True
    basename = token.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return "." in basename


def _parse_files_likely_touched(work_plan_content: str) -> set[str]:
    """Parse Files Likely Touched from work_plan.md."""
    lines = work_plan_content.split("\n")
    in_section = False
    files = set()

    for line in lines:
        line = line.strip()
        if "## Files Likely Touched" in line:
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break  # next section
        if in_section and line and not line.startswith("---"):
            # normalize: remove backticks, quotes, bullets, trim
            normalized = (
                line.lstrip("*- ")
                .replace("`", "")
                .replace('"', "")
                .replace("'", "")
                .strip()
            )
            if normalized and _looks_like_path_token(normalized):
                files.add(normalized)
    return files


def should_run_pip_audit(project_root: Path | None = None) -> tuple[bool, str]:
    """Decide if pip-audit should be run.

    Returns:
        (bool, reason)
    """
    if project_root is None:
        project_root = Path.cwd()

    work_plan = project_root / ".agent" / "collaboration" / "work_plan.md"
    if not work_plan.exists():
        return True, "Conservative fallback: work_plan.md not found"

    try:
        content = work_plan.read_text(encoding="utf-8")
    except Exception as e:
        return True, f"Conservative fallback: could not read work_plan.md ({e})"

    files = _parse_files_likely_touched(content)

    if not files:
        return (
            True,
            "Conservative fallback: No files found in 'Files Likely Touched' section",
        )

    for f in files:
        basename = Path(f).name
        for pattern in DEPENDENCY_SURFACE_PATTERNS:
            if re.match(f"^{pattern}$", basename, re.IGNORECASE):
                return True, f"Dependency surface matched: {f}"

    return False, "No dependency manifests found in the active scope"
