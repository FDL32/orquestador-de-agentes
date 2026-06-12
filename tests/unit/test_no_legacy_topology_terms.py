"""Guard against reintroducing retired external-topology terminology."""

from __future__ import annotations

import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LEGACY_PATTERN = re.compile(
    "|".join(
        [
            r"Model\s+" + "B",
            r"Modelo\s+" + "B",
            "model[_-]" + "b",
        ]
    ),
    re.IGNORECASE,
)
EXCLUDED_PATHS = {
    Path("CHANGELOG.md"),
}
EXCLUDED_PARTS = {
    ".agent",
    ".codex",
    ".git",
    ".opencode",
    ".tmp",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "sandbox",
}


def _is_excluded(relative_path: Path) -> bool:
    if relative_path in EXCLUDED_PATHS:
        return True
    return any(part in EXCLUDED_PARTS for part in relative_path.parts)


def test_repo_has_no_live_retired_topology_terms() -> None:
    matches: list[str] = []

    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative_path = path.relative_to(PROJECT_ROOT)
        if _is_excluded(relative_path):
            continue
        if path.suffix.lower() in {
            ".pyc",
            ".pyo",
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".ico",
        }:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if LEGACY_PATTERN.search(content):
            matches.append(relative_path.as_posix())

    assert matches == [], f"Retired topology terminology still present: {matches}"
