"""Pytest configuration and fixtures."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = PROJECT_ROOT / ".agent"
TEST_RUNTIME_ROOT = PROJECT_ROOT / "tests" / "sandbox" / "test_runtime"
SESSION_RUNTIME_ROOT = TEST_RUNTIME_ROOT / f"session_{os.getpid()}"


# Add project root FIRST, then .agent directory to path so tests can import
# both runtime.* modules (from root) and bus modules (from .agent/).
# This fixes the import precedence issue for agents_config.py which imports
# runtime.project_root. Insert order matters: last insert wins at position 0.
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class ProjectTmpPathFactory:
    """Project-owned replacement for pytest tmp_path_factory."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._counter = 0

    def mktemp(self, name: str, numbered: bool = True) -> Path:
        safe_name = name.replace("/", "_").replace("\\", "_")
        if numbered:
            self._counter += 1
            path = self.base_dir / f"{safe_name}{self._counter:04d}"
        else:
            path = self.base_dir / safe_name
        path.mkdir(parents=True, exist_ok=True)
        return path


def _restore_env(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


@pytest.fixture(scope="session", autouse=True)
def _project_temp_environment() -> None:
    """Keep pytest temp activity inside the project sandbox."""
    original_tempdir = tempfile.tempdir
    original_env = {
        "TMPDIR": os.environ.get("TMPDIR"),
        "TEMP": os.environ.get("TEMP"),
        "TMP": os.environ.get("TMP"),
    }

    SESSION_RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    tempfile.tempdir = str(SESSION_RUNTIME_ROOT)
    os.environ["TMPDIR"] = str(SESSION_RUNTIME_ROOT)
    os.environ["TEMP"] = str(SESSION_RUNTIME_ROOT)
    os.environ["TMP"] = str(SESSION_RUNTIME_ROOT)

    try:
        yield
    finally:
        tempfile.tempdir = original_tempdir
        for key, value in original_env.items():
            _restore_env(key, value)
        shutil.rmtree(SESSION_RUNTIME_ROOT, ignore_errors=True)


@pytest.fixture(autouse=True)
def _restore_cwd() -> None:
    """Restore the working directory after each test."""
    original_cwd = Path.cwd()
    try:
        yield
    finally:
        os.chdir(original_cwd)


@pytest.fixture(scope="session")
def tmp_path_factory() -> ProjectTmpPathFactory:
    """Project-local tmp_path factory."""
    return ProjectTmpPathFactory(SESSION_RUNTIME_ROOT / "factory")


@pytest.fixture
def tmp_path(
    tmp_path_factory: ProjectTmpPathFactory, request: pytest.FixtureRequest
) -> Path:
    """Project-local tmp_path fixture."""
    return tmp_path_factory.mktemp(request.node.name, numbered=True)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Remove the session runtime once pytest finishes."""
    shutil.rmtree(SESSION_RUNTIME_ROOT, ignore_errors=True)
