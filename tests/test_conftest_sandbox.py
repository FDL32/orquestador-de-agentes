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
import os
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
_purge_orphan_session_dirs = conftest_module._purge_orphan_session_dirs
_pid_is_alive = conftest_module._pid_is_alive

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


def _find_dead_pid() -> int:
    """Return a pid that is (almost certainly) not running.

    Scans downward from a high value; falls back to a fixed high pid if the
    liveness check is inconclusive on this platform.
    """
    for candidate in range(999983, 900000, -1):
        if not _pid_is_alive(candidate):
            return candidate
    return 999983


def test_purge_preserves_live_sibling_and_removes_dead(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WOT-2026-020p barrier: the orphan purge must NOT delete a living process's
    ``session_<pid>`` sandbox (xdist sibling), but MUST still remove dead ones.

    Mutation: revert the liveness guard in ``_purge_orphan_session_dirs`` and the
    live sibling gets purged -> this test FAILS. Reproduces the cross-worker TOCTOU
    that made ``tempfile.TemporaryDirectory()`` crash with WinError 3 under ``-n``.
    """
    runtime_root = tmp_path / "test_runtime"
    runtime_root.mkdir()
    monkeypatch.setattr(conftest_module, "TEST_RUNTIME_ROOT", runtime_root)

    live_pid = os.getpid()  # this test process is provably alive
    dead_pid = _find_dead_pid()
    other_live_pid = os.getppid()  # parent process, also alive

    live_dir = runtime_root / f"session_{live_pid}"
    dead_dir = runtime_root / f"session_{dead_pid}"
    other_live_dir = runtime_root / f"session_{other_live_pid}"
    for d in (live_dir, dead_dir, other_live_dir):
        d.mkdir()
        (d / "marker.txt").write_text("x", encoding="utf-8")

    # Purge with a keep_pid that matches NONE of the three dirs, so live_dir is
    # not merely skipped by the keep_pid==self short-circuit: it must survive
    # purely because the liveness check reports its pid alive. keep_pid=1 is a
    # sentinel with no session_1 dir present.
    purged = _purge_orphan_session_dirs(keep_pid=1)

    assert live_dir.exists(), (
        "live sibling sandbox was wrongly purged (TOCTOU regression)"
    )
    assert other_live_dir.exists(), "live parent-process sandbox was wrongly purged"
    assert not dead_dir.exists(), "dead orphan sandbox was not purged"
    assert purged == 1, f"expected exactly 1 dead dir purged, got {purged}"


def test_pid_is_alive_true_for_self_false_for_dead() -> None:
    """``_pid_is_alive`` recognizes the running process and rejects a dead pid."""
    assert _pid_is_alive(os.getpid()) is True
    assert _pid_is_alive(_find_dead_pid()) is False
    assert _pid_is_alive(0) is False
    assert _pid_is_alive(-1) is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
