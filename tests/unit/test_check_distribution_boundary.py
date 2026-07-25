"""Tests for scripts/check_distribution_boundary.py (WOT-2026-025i).

Guard that enforces MANIFEST.distribute as a MECHANISM (not a norm): every
manifest entry must resolve to >=1 tracked file via `git ls-files`. A stale
entry means the declared frontier has a hole. Published denominator:
"N entradas -> M ficheros versionados auditados".

Cobertura (una idea por test):
  T-BOUNDARY-EXPANDE    : a directory entry expands to its tracked files.
  T-BOUNDARY-PUBLICA    : the output publishes "N entradas -> M ficheros".
  T-BOUNDARY-STALE      : a manifest entry matching no tracked file -> exit 1.
  T-BOUNDARY-MISSING    : MANIFEST absent -> exit 1 (fail-closed).
  T-BOUNDARY-EMPTY      : MANIFEST with only comments -> exit 1.
  T-BOUNDARY-INSIDE     : a tracked file covered by manifest entry -> pass.
  T-BOUNDARY-DELETED    : a tracked file deleted after being in manifest -> stale.
  T-REAL-REPO           : live contract on the real motor tree.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

from tests.conftest import REAL_SYSTEM_TEMP


_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "check_distribution_boundary",
    _ROOT / "scripts" / "check_distribution_boundary.py",
)
cdb = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cdb)


# --------------------------------------------------------------------- helpers
def _wb(path: Path, text: str) -> None:
    """Write text as LF bytes (never let the platform CRLF-ify a fixture)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.replace("\r\n", "\n").encode("utf-8"))


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(root), capture_output=True, text=True, timeout=30
    )


@pytest.fixture
def fake_motor(request: pytest.FixtureRequest):
    """A git-init'd fake motor under the REAL system temp."""
    base = REAL_SYSTEM_TEMP / f"cdb_{abs(hash(request.node.name)) % 10**8}"
    if base.exists():
        _rmtree_ro(base)
    base.mkdir(parents=True)
    _git(base, "init", "-q")
    _git(base, "config", "user.email", "t@t.t")
    _git(base, "config", "user.name", "t")
    yield base

    def _rm():
        _rmtree_ro(base)

    request.addfinalizer(_rm)


def _rmtree_ro(path: Path) -> None:
    import shutil
    import stat

    def _onerror(func, p, _exc):
        Path(p).chmod(stat.S_IWRITE)
        func(p)

    shutil.rmtree(path, onerror=_onerror)


def _commit_all(root: Path) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "x")


# ---------------------------------------------------------------- T-BOUNDARY-EXPANDE
def test_boundary_expands_directory(fake_motor: Path):
    """A directory entry counts its tracked files (3), not 1."""
    _wb(fake_motor / "MANIFEST.distribute", "AGENTS.md\npkg/\n")
    _wb(fake_motor / "AGENTS.md", "hello\n")
    _wb(fake_motor / "pkg" / "a.py", "a\n")
    _wb(fake_motor / "pkg" / "b.py", "b\n")
    _wb(fake_motor / "pkg" / "c.py", "c\n")
    _commit_all(fake_motor)

    entries = cdb.manifest_entries(fake_motor)
    assert len(entries) == 2
    n_entries, files, err = cdb.build_denominator(fake_motor)
    assert err is None
    assert n_entries == 2
    assert set(files) == {"AGENTS.md", "pkg/a.py", "pkg/b.py", "pkg/c.py"}


# ---------------------------------------------------------------- T-BOUNDARY-PUBLICA
def test_publishes_the_count(fake_motor: Path):
    _wb(fake_motor / "MANIFEST.distribute", "AGENTS.md\npkg/\n")
    _wb(fake_motor / "AGENTS.md", "hi\n")
    _wb(fake_motor / "pkg" / "a.py", "a\n")
    _wb(fake_motor / "pkg" / "b.py", "b\n")
    _commit_all(fake_motor)
    code, lines = cdb.audit(fake_motor)
    assert code == 0
    assert any("2 entradas -> 3 ficheros" in ln for ln in lines), lines


# ---------------------------------------------------------------- T-BOUNDARY-STALE
def test_stale_entry_fails(fake_motor: Path):
    """A manifest entry that resolves to NO tracked files -> exit 1."""
    _wb(fake_motor / "MANIFEST.distribute", "AGENTS.md\nDOES_NOT_EXIST.md\n")
    _wb(fake_motor / "AGENTS.md", "ok\n")
    _commit_all(fake_motor)
    code, lines = cdb.audit(fake_motor)
    assert code == 1
    assert any("stale" in ln.lower() or "DOES_NOT_EXIST" in ln for ln in lines), lines


# ---------------------------------------------------------------- T-BOUNDARY-MISSING
def test_missing_manifest_fails(fake_motor: Path):
    """No MANIFEST.distribute -> exit 1 (fail-closed)."""
    code, _lines = cdb.audit(fake_motor)
    assert code == 1


def test_empty_manifest_fails(fake_motor: Path):
    """MANIFEST with only comments -> exit 1 (no entries)."""
    _wb(fake_motor / "MANIFEST.distribute", "# only comments\n# nothing here\n")
    _commit_all(fake_motor)
    code, _lines = cdb.audit(fake_motor)
    assert code == 1


# ---------------------------------------------------------------- T-BOUNDARY-INSIDE
def test_tracked_file_inside_manifest_passes(fake_motor: Path):
    """A tracked file covered by a manifest entry -> pass."""
    _wb(fake_motor / "MANIFEST.distribute", "AGENTS.md\npkg/\n")
    _wb(fake_motor / "AGENTS.md", "ok\n")
    _wb(fake_motor / "pkg" / "mod.py", "x = 1\n")
    _commit_all(fake_motor)

    code, lines = cdb.audit(fake_motor)
    assert code == 0, "\n".join(lines)


# ---------------------------------------------------------------- T-BOUNDARY-DELETED
def test_deleted_file_makes_entry_stale(fake_motor: Path):
    """A manifest entry pointing to a deleted file -> stale -> exit 1."""
    _wb(fake_motor / "MANIFEST.distribute", "AGENTS.md\nvanishing.txt\n")
    _wb(fake_motor / "AGENTS.md", "ok\n")
    _wb(fake_motor / "vanishing.txt", "temp\n")
    _commit_all(fake_motor)
    # now delete the file and commit
    _git(fake_motor, "rm", "-f", "vanishing.txt")
    _git(fake_motor, "commit", "-q", "-m", "delete vanishing")

    code, lines = cdb.audit(fake_motor)
    assert code == 1
    assert any("vanishing.txt" in ln for ln in lines), lines


# ---------------------------------------------------------------- T-REAL-REPO
def test_real_repo_is_green():
    """LIVE contract: the real motor tree must audit clean. The point IS the
    real tree -- a synthetic-only suite is blind to the boundary."""
    code, lines = cdb.audit(_ROOT)
    joined = "\n".join(lines)
    assert "ficheros versionados auditados" in joined, joined
    assert code == 0, joined
