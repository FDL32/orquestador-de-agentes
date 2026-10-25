"""Deterministic regression for the scorecard rotation race (WOT-2026-124i).

Mechanism (reproduced by the Manager on the pre-fix code, 2026-10-25):
  1. Active P = inode A (rows A). Rotator R1 opens its handle on A.
  2. Before R1 takes the lock, R0 rotates P (A -> archive N0); P becomes
     inode B and receives rows B.
  3. R1 locks its STALE handle (A), sees P big (B) and enters the locked
     rotation although it holds no lock on B.
  4. While R1 is in the locked section, a fresh rotator R2 (lock on B) rotates
     P (B -> N1) and P becomes inode C with rows C.
  5. R1 archives P towards a name it computed BEFORE R2 ran. Pre-fix result:
     on Windows ``os.rename`` raises ``FileExistsError`` (same name N1); with
     POSIX overwrite semantics the rotators also sweep each other's
     ``*.rotate-*.tmp`` and the rotation breaks. Rows can be lost.

The fix: ``_rotate_scorecard`` revalidates, after taking the lock, that its
handle's inode is the one at ``path`` (same pattern as ``append_scorecard``);
a stale handle returns without rotating, so rotations stay serialized.

The interleaving is forced with hooks (no threads, no sleeps). The tests assert
the INVARIANT (every row readable, no exception), not the implementation, so
they are RED on the pre-fix code and GREEN with the fix.
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


_SCRIPTS_DIR = str(Path(__file__).resolve().parents[2] / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import ensemble_dispatch as ed  # noqa: E402


_FIXED_DT = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)


class _FixedClock(datetime):
    """Every rotation lands in the same second (worst case for archive names)."""

    @classmethod
    def now(cls, tz=None):
        return _FIXED_DT


def _all_rows(active: Path) -> list[bytes]:
    """Every non-empty line of the active scorecard and of its archives."""
    rows: list[bytes] = []
    for f in sorted(active.parent.glob(f"{active.stem}*.jsonl")):
        rows += [ln for ln in f.read_bytes().splitlines() if ln]
    return rows


@pytest.mark.parametrize("semantics", ["native", "posix_overwrite"])
def test_stale_rotator_interleaved_with_fresh_rotator_loses_no_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, semantics: str
) -> None:
    """A stale rotator (R1) interleaved with R0 and R2 never loses a row.

    ``native`` uses this platform's ``os.rename``; ``posix_overwrite`` swaps it
    for ``os.replace`` so the POSIX silent-overwrite case is exercised on
    Windows too.
    """
    p = tmp_path / ed.SCORECARD_REL
    p.parent.mkdir(parents=True)
    p.write_bytes(b"A1\nA2\n")
    monkeypatch.setattr(ed, "SCORECARD_ROTATION_THRESHOLD_BYTES", 1)
    monkeypatch.setattr(ed, "datetime", _FixedClock)
    real_open, real_rotate = ed._open_append_handle, ed._rotate_scorecard
    real_rename, real_link = os.rename, os.link
    state = {"r0": False, "r2": False, "in_r1": False}

    def open_hook(path):
        handle = real_open(path)
        if not state["r0"]:
            state["r0"] = True
            real_rotate(path)  # R0: A -> N0, P = B
            with open(path, "ab") as f:
                f.write(b"B1\nB2\n")
            state["in_r1"] = True
        return handle

    def before_archive() -> None:
        if state["in_r1"] and not state["r2"]:
            state["r2"] = True
            real_rotate(p)  # R2: B -> N1, P = C
            with open(p, "ab") as f:
                f.write(b"C1\nC2\n")

    def rename_hook(src, dst, *args, **kwargs):
        before_archive()
        if semantics == "posix_overwrite":
            return os.replace(src, dst)
        return real_rename(src, dst, *args, **kwargs)

    def link_hook(src, dst, *args, **kwargs):
        before_archive()
        return real_link(src, dst, *args, **kwargs)

    monkeypatch.setattr(ed, "_open_append_handle", open_hook)
    monkeypatch.setattr(os, "rename", rename_hook)
    monkeypatch.setattr(os, "link", link_hook)

    real_rotate(p)  # R1: its handle is opened through open_hook (stale)

    expected = [b"A1", b"A2", b"B1", b"B2"]
    if state["r2"]:
        expected += [b"C1", b"C2"]
    assert sorted(_all_rows(p)) == sorted(expected), state


def test_fresh_rotation_still_rotates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative control of the fix: a NON-stale handle still rotates an active
    over the threshold (the inode check must not turn rotation into a no-op)."""
    p = tmp_path / ed.SCORECARD_REL
    p.parent.mkdir(parents=True)
    p.write_bytes(b"A1\nA2\n")
    monkeypatch.setattr(ed, "SCORECARD_ROTATION_THRESHOLD_BYTES", 1)
    monkeypatch.setattr(ed, "datetime", _FixedClock)

    archived = ed._rotate_scorecard(p)

    assert archived != p
    assert archived.read_bytes() == b"A1\nA2\n"
    assert p.read_bytes() == b""


def test_writer_arriving_while_active_is_absent_keeps_its_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Writer window (codex review of 9624f249, MAJOR 2): right after the
    rotation renames the active away, a writer recreates it and writes its row
    (its inode check passes: the new file IS the path). The rotation must not
    then clobber that file. Pre-fix, ``os.replace(tmp, path)`` replaced it and
    the row vanished silently."""
    p = tmp_path / ed.SCORECARD_REL
    p.parent.mkdir(parents=True)
    ed.append_scorecard(tmp_path, {"ts": "a", "ticket": "ROW-A"})
    monkeypatch.setattr(ed, "SCORECARD_ROTATION_THRESHOLD_BYTES", 1)
    real_rename = os.rename
    state = {"writer_ran": False}

    def rename_hook(src, dst, *args, **kwargs):
        result = real_rename(src, dst, *args, **kwargs)
        if Path(src) == p and not state["writer_ran"]:
            state["writer_ran"] = True
            assert not p.exists(), "the window under test: active is absent"
            monkeypatch.setattr(ed, "SCORECARD_ROTATION_THRESHOLD_BYTES", 10**9)
            ed.append_scorecard(tmp_path, {"ts": "w", "ticket": "ROW-W"})
        return result

    monkeypatch.setattr(os, "rename", rename_hook)

    ed.append_scorecard(tmp_path, {"ts": "b", "ticket": "ROW-B"})  # rotates first

    assert state["writer_ran"], "the rotation never reached the window"
    text = b"\n".join(_all_rows(p))
    for ticket in (b"ROW-A", b"ROW-B", b"ROW-W"):
        assert ticket in text, ticket
