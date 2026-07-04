"""Barrier tests for ProjectTmpPathFactory.mktemp folder-name shortening.

WOT-2026-015m: mktemp used to build folder names from the FULL pytest node
name (up to 88+ chars in this repo, more with [param] suffixes). Stacked on
top of the already-deep sandbox base
(tests/sandbox/test_runtime/session_<PID>/factory/...), this crossed
Windows' MAX_PATH (260) once a test created a real git repo inside
``tmp_path`` (git-internal paths like ``.git/objects/.../pack-<40hex>.pack``
add ~70+ more characters), producing an intermittent
``NotADirectoryError [WinError 267]`` under the full suite.

These tests load ``tests/conftest.py`` via
``importlib.util.spec_from_file_location`` because a direct ``import
conftest`` fails in this repo (pytest does not insert ``tests/`` into
``sys.path`` under the current configuration) -- the same loading pattern
already used by ``.agent/agent_controller.py::_auto_archive_closed_artifacts``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_CONFTEST_PATH = Path(__file__).resolve().parent / "conftest.py"
_spec = importlib.util.spec_from_file_location(
    "conftest_sandbox_under_test", _CONFTEST_PATH
)
assert _spec is not None and _spec.loader is not None
conftest_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(conftest_module)

ProjectTmpPathFactory = conftest_module.ProjectTmpPathFactory

# Real long test name measured in this repo's diagnostic (Fase 0), 88 chars.
_REAL_LONG_TEST_NAME = "test_build_review_prompt_includes_manager_learnings_for_code_and_preserves_static_rubric"

# Synthetic, even longer name (150+ chars) to cover parametrize-suffix cases.
_SYNTHETIC_LONG_TEST_NAME = (
    "test_something_with_a_very_long_descriptive_name_that_exercises_parametrize"
    "_suffixes_like_this_one[some-long-parametrize-id-value-here-too]"
)

# Threshold from the plan: 16 (prefix) + 1 (separator) + 8 (hash) + 4 (counter) = 29.
_MAX_FOLDER_NAME_LEN = 29


def test_mktemp_folder_name_is_short_for_long_test_name(tmp_path: Path) -> None:
    """A long pytest node name must not produce a long folder name.

    Uses a native pytest tmp_path (not the project's own tmp_path fixture)
    to instantiate the factory under test, so this barrier test is not
    coupled to the very mechanism it is verifying.
    """
    factory = ProjectTmpPathFactory(tmp_path / "factory_base")

    for name in (_REAL_LONG_TEST_NAME, _SYNTHETIC_LONG_TEST_NAME):
        path = factory.mktemp(name)
        assert len(path.name) <= _MAX_FOLDER_NAME_LEN, (
            f"mktemp({name!r}) produced folder name {path.name!r} "
            f"({len(path.name)} chars), expected <= {_MAX_FOLDER_NAME_LEN}"
        )


def test_mktemp_preserves_uniqueness_via_counter(tmp_path: Path) -> None:
    """Two calls with the same name must produce distinct paths (counter)."""
    factory = ProjectTmpPathFactory(tmp_path / "factory_base")

    path_1 = factory.mktemp(_REAL_LONG_TEST_NAME)
    path_2 = factory.mktemp(_REAL_LONG_TEST_NAME)

    assert path_1 != path_2
    assert path_1.exists()
    assert path_2.exists()


def test_mktemp_short_name_not_padded_or_broken(tmp_path: Path) -> None:
    """A short name must not raise, degenerate, or lose recognizability."""
    factory = ProjectTmpPathFactory(tmp_path / "factory_base")

    short_name = "test_foo"
    path = factory.mktemp(short_name)

    assert path.is_dir()
    # Recognizable: the short name (or its safe-replaced form) still appears
    # as a literal prefix of the generated folder name.
    assert path.name.startswith(short_name)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
