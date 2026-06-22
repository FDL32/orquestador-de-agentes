import importlib.util
import os
import stat
import sys
from pathlib import Path

from tests._temp_runtime import managed_test_dir


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_conftest():
    """Load tests/conftest.py as a module to exercise its purge helpers directly.

    pytest loads conftest as a plugin but not under an importable ``conftest``
    name from a sibling package, so resolve it by path (reusing an already-loaded
    instance from sys.modules when present).
    """
    for mod in sys.modules.values():
        if getattr(mod, "__file__", None) == str(
            PROJECT_ROOT / "tests" / "conftest.py"
        ):
            return mod
    spec = importlib.util.spec_from_file_location(
        "_conftest_under_test", PROJECT_ROOT / "tests" / "conftest.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


conftest = _load_conftest()


def _make_readonly_git_like_tree(root: Path) -> Path:
    """Build a session_<pid> dir holding a read-only file like git's objects.

    Reproduces the WOT-2026-013i failure surface: a fixture .git/objects entry
    that git marks read-only, which on Windows makes shutil.rmtree raise
    PermissionError and the old ignore_errors=True purge a silent no-op.
    """
    session = root / "session_999999"
    objects = session / "dest" / ".git" / "objects" / "ab"
    objects.mkdir(parents=True)
    blob = objects / "deadbeef"
    blob.write_text("obj", encoding="utf-8")
    os.chmod(blob, stat.S_IREAD)  # read-only, like a real git object
    return session


def test_rmtree_robust_deletes_readonly_tree(tmp_path):
    """WOT-2026-013i: _rmtree_robust clears the read-only bit and deletes the tree.

    PASS-with-fix: _rmtree_robust chmods+retries and the tree is gone, where the
    prior ``shutil.rmtree(..., ignore_errors=True)`` would silently leave a
    read-only git object behind (the 013i no-op purge).
    """
    session = _make_readonly_git_like_tree(tmp_path)

    gone = conftest._rmtree_robust(session)
    assert gone is True
    assert not session.exists()


def test_purge_orphan_session_dirs_removes_readonly_orphan(tmp_path, monkeypatch):
    """The purge actually deletes a read-only orphan and honors keep_pid.

    Guards the new semantics: before 013i the purge returned 0 and left orphans
    (ignore_errors swallowed the PermissionError); now it must report the real
    deletion count and keep the live session's dir.
    """
    monkeypatch.setattr(conftest, "TEST_RUNTIME_ROOT", tmp_path)
    orphan = _make_readonly_git_like_tree(tmp_path)
    keep = tmp_path / "session_111111"
    keep.mkdir()

    purged = conftest._purge_orphan_session_dirs(keep_pid=111111)

    assert purged == 1, "the read-only orphan must be counted as actually purged"
    assert not orphan.exists(), "orphan session dir must be gone"
    assert keep.exists(), "the live session dir (keep_pid) must be preserved"


def test_force_remove_readonly_does_not_raise_on_locked(tmp_path):
    """The handler is fail-open: a func that keeps failing must not raise."""

    def _always_fails(_path):
        raise PermissionError("locked by a live process")

    # Should swallow the OSError rather than propagate it.
    conftest._force_remove_readonly(_always_fails, str(tmp_path / "x"), None)


def test_tmp_path_creates_writable_directory(tmp_path):
    marker = tmp_path / "marker.txt"
    marker.write_text("ok", encoding="utf-8")
    assert marker.exists()
    assert marker.read_text(encoding="utf-8") == "ok"


def test_managed_test_dir_creates_writable_directory():
    with managed_test_dir("smoke_") as probe:
        marker = probe / "probe.txt"
        marker.write_text("ok", encoding="utf-8")
        assert marker.exists()


def test_tmp_path_stays_under_runtime_root(tmp_path):
    parts = {part.lower() for part in tmp_path.parts}
    assert "sandbox" in parts
    assert "test_runtime" in parts


def test_cwd_is_restored_after_changes(tmp_path, monkeypatch):
    original_cwd = Path.cwd()
    monkeypatch.chdir(tmp_path)
    assert Path.cwd() == tmp_path
    assert Path.cwd() != original_cwd


def test_cwd_starts_at_project_root():
    assert Path.cwd() == PROJECT_ROOT
