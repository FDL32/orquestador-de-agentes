#!/usr/bin/env python3
"""Diff-driven focal test selector (WOT-2026-010l).

Proposes a reproducible subset of tests for the Builder's local iteration loop,
derived from the real working-tree diff. It is *ergonomia local*: it never
relaxes the canonical handoff contract. By construction the runner turns any
proposed subset into explicit pytest args (``args_mode=explicit_args``), so
``010q`` keeps blocking a focal run for ``--mark-ready``.

Design contract (Before / During / After):

- **Before:** a motor repo with a readable git working tree. The caller supplies
  ``project_root`` and an optional ``motor_root`` (the same seams the scope gate
  uses). No parallel git parser is opened: the diff is read through
  ``scope_gate.get_changed_files``.
- **During:** read changed files, classify each, and resolve a conservative
  file->tests map. The mapping is auditable: a test file maps to itself; a
  ``scripts/<name>.py`` change maps to tests whose name contains ``<name>``.
  Anything that cannot be resolved to a concrete, safe test contributes to a
  fail-open decision.
- **After:** return a :class:`SelectionResult`. When safe, ``mode == "subset"``
  with a sorted, reproducible ``tests`` list. Otherwise ``mode == "fallback"``
  with a human-readable ``reason`` explaining the replegue to the canonical
  suite. The selector never raises for an empty/unsafe resolution and never
  pass-opens silently: an unknown situation always falls open to the full suite
  with an auditable reason.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path


# Bootstrap: the project root (and .agent) must be importable for scope_gate.
_PROJECT_ROOT_BOOTSTRAP = Path(__file__).resolve().parent.parent
for _candidate in (_PROJECT_ROOT_BOOTSTRAP, _PROJECT_ROOT_BOOTSTRAP / ".agent"):
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

import scope_gate  # noqa: E402


# Structural files: a change here invalidates any safe subset. The discovery
# surface, plugin config or agent runtime can alter which tests are relevant or
# how they collect, so we replegamos a la suite canonica completa.
STRUCTURAL_FILES = {"pyproject.toml", "pytest.ini"}
STRUCTURAL_DIR_PREFIXES = (".agent/",)

# Test file name shapes accepted as auditable test targets.
_TEST_PREFIX = "test_"
_TEST_SUFFIX = "_test.py"


@dataclass
class SelectionResult:
    """Outcome of a focal selection.

    ``mode`` is either ``"subset"`` (a reproducible, safe subset was resolved)
    or ``"fallback"`` (replegar a la suite canonica completa). ``tests`` is a
    sorted list of repo-relative test paths when ``mode == "subset"``.
    ``reason`` always carries an auditable explanation.
    """

    mode: str
    reason: str
    tests: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)

    @property
    def is_subset(self) -> bool:
        return self.mode == "subset"

    @property
    def is_fallback(self) -> bool:
        return self.mode == "fallback"


def _relativize(abs_path: str, roots: list[Path]) -> str | None:
    """Return ``abs_path`` relative to the first matching root, or ``None``.

    The ``root == p or root in p.parents`` guard guarantees ``relative_to`` will
    not raise, so no per-iteration try/except is needed.
    """
    p = Path(abs_path)
    for root in roots:
        if root == p or root in p.parents:
            return p.relative_to(root).as_posix()
    return None


def _resolve_changed_rel(changed_abs: set[str], roots: list[Path]) -> list[str]:
    """Map absolute changed paths to repo-relative posix paths under a root."""
    rel_changed: list[str] = []
    for abs_path in sorted(changed_abs):
        rel = _relativize(abs_path, roots)
        if rel is not None:
            rel_changed.append(rel)
    return rel_changed


def _resolve_subset(rel_changed: list[str], *, tests_root: Path) -> set[str]:
    """Resolve the auditable file->tests subset for the changed files."""
    selected: set[str] = set()
    for rel in rel_changed:
        if _is_test_path(rel):
            selected.add(rel)
            continue
        stem = _module_stem(rel)
        if stem is not None:
            selected |= _discover_tests_for_stem(stem, tests_root=tests_root)
    return selected


def _is_test_path(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return (
        rel.startswith("tests/")
        and (name.startswith(_TEST_PREFIX) and name.endswith(".py"))
    ) or (rel.startswith("tests/") and name.endswith(_TEST_SUFFIX))


def _is_structural(rel: str) -> bool:
    if rel in STRUCTURAL_FILES:
        return True
    return any(rel.startswith(prefix) for prefix in STRUCTURAL_DIR_PREFIXES)


def _module_stem(rel: str) -> str | None:
    """Return the module stem for a ``scripts/<name>.py`` change, else None."""
    if not rel.startswith("scripts/") or not rel.endswith(".py"):
        return None
    stem = rel.rsplit("/", 1)[-1][: -len(".py")]
    return stem or None


def _discover_tests_for_stem(stem: str, *, tests_root: Path) -> set[str]:
    """Find auditable test files whose name contains ``stem`` under ``tests/``.

    Returns repo-relative posix paths. A change to ``scripts/foo.py`` matches
    ``tests/**/test_foo.py`` and ``tests/**/foo_test.py`` (and any test file
    whose stem contains ``foo``), which is a conservative, name-based map.
    """
    if not tests_root.is_dir():
        return set()
    matches: set[str] = set()
    for path in tests_root.rglob("*.py"):
        name = path.name
        is_test = (name.startswith(_TEST_PREFIX) and name != "test.py") or (
            name.endswith(_TEST_SUFFIX)
        )
        if not is_test:
            continue
        if stem in path.stem:
            rel = path.relative_to(tests_root.parent).as_posix()
            matches.add(rel)
    return matches


def select_focal_tests(
    *,
    project_root: Path,
    motor_root: Path | None,
    run_fn=None,
) -> SelectionResult:
    """Resolve a focal subset from the working-tree diff, or fall open.

    See module docstring for the full Before/During/After contract.
    """
    kwargs = {"project_root": project_root, "motor_root": motor_root}
    if run_fn is not None:
        kwargs["run_fn"] = run_fn
    changed_abs = scope_gate.get_changed_files(**kwargs)

    if changed_abs is None:
        return SelectionResult(
            mode="fallback",
            reason="no_diff_available: git working tree could not be read; "
            "running the canonical full suite.",
        )

    roots = [project_root] + ([motor_root] if motor_root is not None else [])
    rel_changed = _resolve_changed_rel(changed_abs, roots)

    if not rel_changed:
        return SelectionResult(
            mode="fallback",
            reason="empty_diff: no changed files resolved under a known root; "
            "running the canonical full suite.",
            changed_files=[],
        )

    structural = sorted(r for r in rel_changed if _is_structural(r))
    if structural:
        return SelectionResult(
            mode="fallback",
            reason=(
                "structural_change: changed structural file(s) "
                f"{structural} invalidate a safe subset; running the canonical "
                "full suite."
            ),
            changed_files=sorted(rel_changed),
        )

    tests_root = project_root / "tests"
    selected = _resolve_subset(rel_changed, tests_root=tests_root)

    if not selected:
        return SelectionResult(
            mode="fallback",
            reason=(
                "no_safe_mapping: changed files did not resolve to any concrete "
                "test; running the canonical full suite."
            ),
            changed_files=sorted(rel_changed),
        )

    return SelectionResult(
        mode="subset",
        reason=f"focal_subset: {len(selected)} test file(s) selected from diff.",
        tests=sorted(selected),
        changed_files=sorted(rel_changed),
    )
