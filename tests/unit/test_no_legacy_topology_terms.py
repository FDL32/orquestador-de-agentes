"""Guard against reintroducing retired external-topology terminology."""

from __future__ import annotations

import os
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
    Path("tests/unit/test_no_legacy_topology_terms.py"),
}
EXCLUDED_PARTS = {
    ".agent",
    ".codex",
    ".git",
    ".kilo",
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


def _is_ignored_negative_assert(line: str) -> bool:
    stripped = line.strip()
    if not stripped.startswith("assert "):
        return False
    return " not in " in stripped


def _has_live_legacy_match(content: str) -> bool:
    for line in content.splitlines():
        if not LEGACY_PATTERN.search(line):
            continue
        if _is_ignored_negative_assert(line):
            continue
        return True
    return False


def _iter_candidate_files(root: Path):
    """Yield file paths under root, pruning EXCLUDED_PARTS directories early.

    Path.rglob("*") cannot prune: it enumerates every entry under excluded
    directories (e.g. tests/sandbox/test_runtime/ accumulates ~380k runtime
    artifacts from prior test sessions) before _is_excluded discards them,
    which dominates this test's wall-clock cost. os.walk's dirnames[:] = ...
    in-place filter stops os.walk from descending into excluded directories
    at all, producing the same file set without paying to enumerate what
    gets discarded anyway (WOT-2026-010k).
    """
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_PARTS]
        for filename in filenames:
            yield Path(dirpath) / filename


def test_repo_has_no_live_retired_topology_terms() -> None:
    matches: list[str] = []

    for path in _iter_candidate_files(PROJECT_ROOT):
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
        if _has_live_legacy_match(content):
            matches.append(relative_path.as_posix())

    assert matches == [], f"Retired topology terminology still present: {matches}"


def test_iter_candidate_files_smoke_no_shortcut(tmp_path):
    """Regression: _iter_candidate_files must produce the same file set as an
    unpruned Path.rglob("*") walk (minus excluded dirs) -- the pruning is a
    performance shortcut, not a behavior change. Builds a small synthetic
    tree with both included and excluded-directory files and asserts the
    pruned walk finds exactly the included ones, matching what an unpruned
    rglob("*") + _is_excluded filter would have found."""
    (tmp_path / "kept.py").write_text("import os", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "also_kept.md").write_text("# doc", encoding="utf-8")

    excluded_dir = tmp_path / "sandbox"
    excluded_dir.mkdir()
    (excluded_dir / "should_not_appear.py").write_text("x = 1", encoding="utf-8")

    pruned_result = {
        p.relative_to(tmp_path).as_posix() for p in _iter_candidate_files(tmp_path)
    }

    unpruned_result = {
        p.relative_to(tmp_path).as_posix()
        for p in tmp_path.rglob("*")
        if p.is_file() and not _is_excluded(p.relative_to(tmp_path))
    }

    assert pruned_result == unpruned_result
    assert pruned_result == {"kept.py", "nested/also_kept.md"}
    assert "sandbox/should_not_appear.py" not in pruned_result


def test_iter_candidate_files_does_not_descend_into_excluded_dirs(
    tmp_path, monkeypatch
):
    """Smoke test without the shortcut: if pruning is removed (simulated by
    monkeypatching EXCLUDED_PARTS to empty), the walk must visit the excluded
    directory's file -- proving the prune is what keeps it out, not luck."""
    excluded_dir = tmp_path / "sandbox"
    excluded_dir.mkdir()
    (excluded_dir / "inside.py").write_text("x = 1", encoding="utf-8")

    pruned = {p.name for p in _iter_candidate_files(tmp_path)}
    assert "inside.py" not in pruned

    monkeypatch.setattr(
        "tests.unit.test_no_legacy_topology_terms.EXCLUDED_PARTS", frozenset()
    )
    unpruned = {p.name for p in _iter_candidate_files(tmp_path)}
    assert "inside.py" in unpruned


def test_negative_assertions_are_not_treated_as_live_legacy_terms() -> None:
    content = 'assert "Model B" not in context\n'
    assert _has_live_legacy_match(content) is False


def test_positive_live_legacy_terms_still_fail() -> None:
    content = 'message = "Model B is still the active name"\n'
    assert _has_live_legacy_match(content) is True
