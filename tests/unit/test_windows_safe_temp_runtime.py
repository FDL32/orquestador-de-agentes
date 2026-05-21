
from pathlib import Path

from tests._temp_runtime import managed_test_dir

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_tmp_path_creates_writable_directory(tmp_path):
    marker = tmp_path / 'marker.txt'
    marker.write_text('ok', encoding='utf-8')
    assert marker.exists()
    assert marker.read_text(encoding='utf-8') == 'ok'


def test_managed_test_dir_creates_writable_directory():
    with managed_test_dir('smoke_') as probe:
        marker = probe / 'probe.txt'
        marker.write_text('ok', encoding='utf-8')
        assert marker.exists()


def test_tmp_path_stays_under_runtime_root(tmp_path):
    parts = {part.lower() for part in tmp_path.parts}
    assert 'sandbox' in parts
    assert 'test_runtime' in parts


def test_cwd_is_restored_after_changes(tmp_path, monkeypatch):
    original_cwd = Path.cwd()
    monkeypatch.chdir(tmp_path)
    assert Path.cwd() == tmp_path
    assert Path.cwd() != original_cwd


def test_cwd_starts_at_project_root():
    assert Path.cwd() == PROJECT_ROOT
