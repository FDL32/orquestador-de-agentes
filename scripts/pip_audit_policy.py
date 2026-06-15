"""Policy deciding whether to run pip-audit based on the active dependency surface."""

from __future__ import annotations

import re
import sys
from pathlib import Path


_PROJECT_ROOT_BOOTSTRAP = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT_BOOTSTRAP) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT_BOOTSTRAP))
_AGENT_DIR = _PROJECT_ROOT_BOOTSTRAP / ".agent"
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

import scope_gate  # noqa: E402


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


def _parse_files_likely_touched(work_plan_content: str) -> set[str]:
    """Parse productive raw FLT paths from work_plan.md.

    Delegates to the canonical scope_gate parser and selects only the bucket
    relevant for the active delivery_authority.
    """
    delivery_authority = scope_gate.read_delivery_authority(work_plan_content)
    return scope_gate.parse_flt_raw_paths(
        work_plan_content,
        delivery_authority=delivery_authority,
        target="authority",
    )


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
