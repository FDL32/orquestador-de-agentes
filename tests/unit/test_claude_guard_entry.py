"""Tests for the canonical Claude guard entrypoint (WOT-2026-003c, WOT-2026-038c)."""

from __future__ import annotations

import json
import sys
from pathlib import Path


sys.path.insert(
    0, str(Path(__file__).resolve().parent.parent.parent / ".agent" / "hooks")
)

import claude_guard_entry as entry


def _make_repo(tmp_path: Path, *, with_guard: bool, guard_exit: int = 7) -> Path:
    """Create a fake repo with a .claude marker and optional stub guard_paths.py."""
    (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)
    if with_guard:
        hooks = tmp_path / ".agent" / "hooks"
        hooks.mkdir(parents=True)
        (hooks / "guard_paths.py").write_text(
            f"import sys; sys.stdin.buffer.read(); sys.exit({guard_exit})\n",
            encoding="utf-8",
        )
    return tmp_path


def _make_repo_with_recording_guard(tmp_path: Path) -> Path:
    """Create a fake repo whose stub guard records its own real cwd and
    applies the SAME "inside cwd or exit 2" rule as the real guard_paths.py.

    Used to prove WHICH root the entrypoint actually invoked guard_paths
    with (not just the exit code): the stub writes ``Path.cwd()`` to
    ``<tmp_path>/_cwd_seen.txt`` (an absolute, test-controlled sentinel path)
    ONLY when it accepts the payload path as being inside its own cwd --
    mirroring ``guard_paths._is_within_repo`` well enough that a request
    which entry.py mis-routes to the wrong root is correctly rejected here
    too, instead of a naive stub always returning 0.
    """
    (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)
    hooks = tmp_path / ".agent" / "hooks"
    hooks.mkdir(parents=True)
    sentinel = tmp_path / "_cwd_seen.txt"
    (hooks / "guard_paths.py").write_text(
        "import sys, json\n"
        "from pathlib import Path\n"
        "data = sys.stdin.buffer.read()\n"
        "try:\n"
        "    payload = json.loads(data.decode('utf-8'))\n"
        "except Exception:\n"
        "    payload = {}\n"
        "tool_input = payload.get('tool_input', {}) if isinstance(payload, dict) else {}\n"
        "paths = [v for k, v in tool_input.items() "
        "if k in ('file_path', 'path', 'target_path', 'new_path') and isinstance(v, str)]\n"
        "cwd = Path.cwd()\n"
        "def _within(p):\n"
        "    try:\n"
        "        Path(p).resolve().relative_to(cwd)\n"
        "        return True\n"
        "    except ValueError:\n"
        "        return False\n"
        "if paths and not all(_within(p) for p in paths):\n"
        "    sys.exit(2)\n"
        f"Path({str(sentinel)!r}).write_text(str(cwd), encoding='utf-8')\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    return tmp_path


def _link(destino: Path, motor: Path) -> None:
    """Write a real motor_destination_link.json in ``destino`` pointing at ``motor``."""
    cfg = destino / ".agent" / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "motor_destination_link.json").write_text(
        json.dumps(
            {
                "motor_root": str(motor.resolve()),
                "destination_root": str(destino.resolve()),
            }
        ),
        encoding="utf-8",
    )


def _payload(*file_paths: str) -> bytes:
    if len(file_paths) == 1:
        tool_input: dict[str, object] = {"file_path": file_paths[0]}
    else:
        # Simulate a bulk-ish payload: multiple path-bearing keys in one call.
        keys = ["file_path", "path", "target_path", "new_path"]
        tool_input = {keys[i]: fp for i, fp in enumerate(file_paths)}
    return json.dumps({"tool_input": tool_input}).encode("utf-8")


class TestResolveRepoRoot:
    def test_finds_claude_ancestor(self, tmp_path: Path):
        repo = _make_repo(tmp_path, with_guard=False)
        sub = repo / "a" / "b"
        sub.mkdir(parents=True)
        assert entry.resolve_repo_root(str(sub)) == repo


class TestResolveGuardPaths:
    def test_own_guard_resolves(self, tmp_path: Path):
        repo = _make_repo(tmp_path, with_guard=True)
        assert (
            entry.resolve_guard_paths(repo)
            == repo / ".agent" / "hooks" / "guard_paths.py"
        )

    def test_via_motor_link(self, tmp_path: Path):
        motor = _make_repo(tmp_path / "motor", with_guard=True)
        destino = tmp_path / "destino"
        (destino / ".agent" / "config").mkdir(parents=True)
        (destino / ".claude").mkdir()
        (destino / ".agent" / "config" / "motor_destination_link.json").write_text(
            json.dumps({"motor_root": str(motor)}), encoding="utf-8"
        )
        assert (
            entry.resolve_guard_paths(destino)
            == motor / ".agent" / "hooks" / "guard_paths.py"
        )

    def test_no_guard_no_link_returns_none(self, tmp_path: Path):
        repo = _make_repo(tmp_path, with_guard=False)
        assert entry.resolve_guard_paths(repo) is None

    def test_malformed_link_returns_none(self, tmp_path: Path):
        destino = _make_repo(tmp_path, with_guard=False)
        (destino / ".agent" / "config").mkdir(parents=True)
        (destino / ".agent" / "config" / "motor_destination_link.json").write_text(
            "{ not valid json", encoding="utf-8"
        )
        assert entry.resolve_guard_paths(destino) is None


class TestMain:
    def test_no_guard_fails_closed(self, tmp_path: Path, monkeypatch, capsys):
        repo = _make_repo(tmp_path, with_guard=False)
        monkeypatch.chdir(repo)
        monkeypatch.setattr(
            "sys.stdin",
            type(
                "S",
                (),
                {"buffer": type("B", (), {"read": staticmethod(lambda: b"{}")})()},
            )(),
        )
        assert entry.main([str(repo)]) == 2
        assert "SECURITY HOOK INACTIVE" in capsys.readouterr().err

    def test_runs_resolved_guard(self, tmp_path: Path, monkeypatch):
        repo = _make_repo(tmp_path, with_guard=True, guard_exit=7)
        monkeypatch.setattr(
            "sys.stdin",
            type(
                "S",
                (),
                {"buffer": type("B", (), {"read": staticmethod(lambda: b"{}")})()},
            )(),
        )
        # main delegates to the stub guard which exits 7.
        assert entry.main([str(repo)]) == 7


class TestCanonicalCommand:
    def test_command_references_entrypoint_and_fail_closed(self):
        cmd = entry.canonical_hook_command()
        assert "claude_guard_entry.py" in cmd
        assert "fail-closed" in cmd
        assert cmd.startswith('python -c "')


class TestFilePathAwareRootSelection:
    """WOT-2026-038c: entry.py must retarget guard invocation by file_path,
    not blindly trust cwd-derived repo_root, while staying fail-closed
    against unauthorized/forged roots."""

    def test_cwd_destino_file_path_in_linked_motor_resolves_rc0(
        self, tmp_path: Path, monkeypatch
    ):
        """(a) cwd=workspace(destino) + file_path=real motor file -> rc0.

        Today (pre-fix) this scenario returns rc2 ("fuera del repo") because
        repo_root is derived purely from cwd/argv. The fix must re-target the
        guard invocation's cwd to the linked motor root when the payload's
        file_path lives there.
        """
        motor = _make_repo_with_recording_guard(tmp_path / "motor")
        destino = tmp_path / "destino"
        _link(destino, motor)
        (destino / ".claude").mkdir(parents=True, exist_ok=True)

        target_file = motor / "README.md"
        target_file.write_text("hello", encoding="utf-8")

        monkeypatch.setattr(
            "sys.stdin",
            type(
                "S",
                (),
                {
                    "buffer": type(
                        "B",
                        (),
                        {"read": staticmethod(lambda: _payload(str(target_file)))},
                    )()
                },
            )(),
        )
        # No argv -> repo_root resolved purely from cwd, exactly like the
        # settings.json boot invocation (cwd=<cwd-root>, no argv).
        monkeypatch.chdir(destino)
        rc = entry.main([])
        assert rc == 0
        sentinel = motor / "_cwd_seen.txt"
        assert sentinel.exists(), (
            "guard_paths stub was never invoked with the motor as cwd"
        )
        assert Path(sentinel.read_text(encoding="utf-8")) == motor.resolve()

    def test_file_path_outside_all_roots_stays_blocked(
        self, tmp_path: Path, monkeypatch
    ):
        """(b) cwd=workspace + file_path totally unrelated -> stays rc2."""
        motor = _make_repo_with_recording_guard(tmp_path / "motor")
        destino = tmp_path / "destino"
        _link(destino, motor)
        (destino / ".claude").mkdir(parents=True, exist_ok=True)

        outside = tmp_path / "unrelated" / "x.txt"
        outside.parent.mkdir(parents=True, exist_ok=True)
        outside.write_text("nope", encoding="utf-8")

        monkeypatch.setattr(
            "sys.stdin",
            type(
                "S",
                (),
                {
                    "buffer": type(
                        "B",
                        (),
                        {"read": staticmethod(lambda: _payload(str(outside)))},
                    )()
                },
            )(),
        )
        monkeypatch.chdir(destino)
        rc = entry.main([])
        assert rc == 2
        # No authorized root (destino nor motor) contains the unrelated path,
        # so entry.py must keep effective_root=destino (repo_root fallback).
        # destino has no own guard_paths.py, so resolve_guard_paths follows
        # the link to the motor's stub guard, invoked with cwd=destino (NOT
        # motor) -- the stub then rejects because the path isn't inside
        # cwd=destino, and the sentinel (written only inside the motor root)
        # never appears.
        assert not (motor / "_cwd_seen.txt").exists()

    def test_forged_marker_root_is_not_authorized(self, tmp_path: Path, monkeypatch):
        """(b') a fakeroot with a bogus .claude/.git (no matching link) must
        NOT become an authorized root -- guards against the nearest-marker
        forgery hole explicitly called out in WOT-2026-038c."""
        motor = _make_repo_with_recording_guard(tmp_path / "motor")
        destino = tmp_path / "destino"
        _link(destino, motor)
        (destino / ".claude").mkdir(parents=True, exist_ok=True)

        fakeroot = tmp_path / "fakeroot"
        (fakeroot / ".claude").mkdir(parents=True, exist_ok=True)
        (fakeroot / ".git").mkdir(parents=True, exist_ok=True)
        forged_file = fakeroot / "payload.py"
        forged_file.write_text("print('evil')", encoding="utf-8")

        monkeypatch.setattr(
            "sys.stdin",
            type(
                "S",
                (),
                {
                    "buffer": type(
                        "B",
                        (),
                        {"read": staticmethod(lambda: _payload(str(forged_file)))},
                    )()
                },
            )(),
        )
        monkeypatch.chdir(destino)
        rc = entry.main([])
        assert rc == 2
        assert not (motor / "_cwd_seen.txt").exists()

    def test_bulk_payload_any_path_outside_roots_blocks_all(
        self, tmp_path: Path, monkeypatch
    ):
        """(d) bulk payload: one path inside the linked motor, one outside ->
        must still be rc2 (fail-closed for the WHOLE request), not just the
        first path validated."""
        motor = _make_repo_with_recording_guard(tmp_path / "motor")
        destino = tmp_path / "destino"
        _link(destino, motor)
        (destino / ".claude").mkdir(parents=True, exist_ok=True)

        good_file = motor / "README.md"
        good_file.write_text("hello", encoding="utf-8")
        outside = tmp_path / "unrelated" / "y.txt"
        outside.parent.mkdir(parents=True, exist_ok=True)
        outside.write_text("nope", encoding="utf-8")

        monkeypatch.setattr(
            "sys.stdin",
            type(
                "S",
                (),
                {
                    "buffer": type(
                        "B",
                        (),
                        {
                            "read": staticmethod(
                                lambda: _payload(str(good_file), str(outside))
                            )
                        },
                    )()
                },
            )(),
        )
        monkeypatch.chdir(destino)
        rc = entry.main([])
        assert rc == 2
        # Proves the fix did NOT retarget cwd to the motor just because ONE
        # of the two paths matched it -- the bulk request as a whole must be
        # rejected, so the motor's recording guard must never have run.
        assert not (motor / "_cwd_seen.txt").exists()

    def test_bulk_payload_all_paths_in_motor_resolves_rc0(
        self, tmp_path: Path, monkeypatch
    ):
        """Bulk payload where ALL paths live in the linked motor -> rc0."""
        motor = _make_repo_with_recording_guard(tmp_path / "motor")
        destino = tmp_path / "destino"
        _link(destino, motor)
        (destino / ".claude").mkdir(parents=True, exist_ok=True)

        file_a = motor / "a.txt"
        file_b = motor / "b.txt"
        file_a.write_text("a", encoding="utf-8")
        file_b.write_text("b", encoding="utf-8")

        monkeypatch.setattr(
            "sys.stdin",
            type(
                "S",
                (),
                {
                    "buffer": type(
                        "B",
                        (),
                        {
                            "read": staticmethod(
                                lambda: _payload(str(file_a), str(file_b))
                            )
                        },
                    )()
                },
            )(),
        )
        monkeypatch.chdir(destino)
        rc = entry.main([])
        assert rc == 0
        assert (motor / "_cwd_seen.txt").exists()

    def test_no_payload_paths_keeps_legacy_behavior(self, tmp_path: Path, monkeypatch):
        """A payload without any file_path-like key must behave exactly as
        before the fix: guard runs with cwd=repo_root, no root-widening
        logic engaged."""
        repo = _make_repo_with_recording_guard(tmp_path)
        monkeypatch.setattr(
            "sys.stdin",
            type(
                "S",
                (),
                {"buffer": type("B", (), {"read": staticmethod(lambda: b"{}")})()},
            )(),
        )
        monkeypatch.chdir(repo)
        rc = entry.main([])
        assert rc == 0
        sentinel = repo / "_cwd_seen.txt"
        assert sentinel.exists()
        assert Path(sentinel.read_text(encoding="utf-8")) == repo.resolve()

    def test_cwd_motor_file_path_in_linked_destino_resolves_rc0(
        self, tmp_path: Path, monkeypatch
    ):
        """Inverse direction: cwd=motor + file_path=destino linked to it -> rc0.

        Exercises ``_destino_linked_to_motor`` inside ``_authorized_roots``
        (the branch where ``repo_root`` IS the motor and has no link of its
        own -- the link only lives in the destino, pointing back at this
        motor). The motor is the cwd-root (has its own recording guard); the
        destino only carries the link + a repo marker, no guard of its own,
        so a correctly selected root must resolve the guard via the motor
        (through ``resolve_guard_paths``' own link-follow) and run it with
        cwd=destino -- proven by the sentinel's recorded content (the
        subprocess's own ``Path.cwd()``), NOT the sentinel's fixed on-disk
        location (the stub script always writes to a path fixed at fixture
        creation time, under the motor, regardless of the invocation cwd).
        """
        motor = _make_repo_with_recording_guard(tmp_path / "motor")
        (motor / ".git").mkdir(parents=True, exist_ok=True)
        destino = tmp_path / "destino"
        _link(destino, motor)
        (destino / ".claude").mkdir(parents=True, exist_ok=True)

        target_file = destino / "work_plan.md"
        target_file.write_text("plan", encoding="utf-8")

        monkeypatch.setattr(
            "sys.stdin",
            type(
                "S",
                (),
                {
                    "buffer": type(
                        "B",
                        (),
                        {"read": staticmethod(lambda: _payload(str(target_file)))},
                    )()
                },
            )(),
        )
        # No argv -> repo_root resolved purely from cwd=motor, exactly like
        # the settings.json boot invocation when Claude Code runs FROM the
        # motor and edits a file that lives in the linked destino.
        monkeypatch.chdir(motor)
        rc = entry.main([])
        assert rc == 0
        # The stub's sentinel path is fixed (under the motor) at fixture
        # creation time; what proves the SELECTED root is its CONTENT
        # (str(Path.cwd()) captured by the subprocess at run time).
        sentinel = motor / "_cwd_seen.txt"
        assert sentinel.exists(), "guard_paths stub was never invoked"
        assert Path(sentinel.read_text(encoding="utf-8")) == destino.resolve()

    def test_malformed_payload_falls_back_to_legacy_behavior(
        self, tmp_path: Path, monkeypatch
    ):
        """Malformed / path-less stdin must never crash main(): ``_payload_paths``
        returns [] and entry.py falls back to effective_root=repo_root, exactly
        as if no root-widening logic existed.

        Covers two malformed shapes in one test: invalid JSON (``b"{ not
        json"``) is exercised directly against ``_payload_paths`` (unit-level,
        since feeding literally malformed bytes as stdin would make ANY
        payload -- with or without file_path -- behave identically at the
        main() level, so the interesting behavioral assertion is the
        no-tool_input JSON payload run through main() end-to-end).
        """
        # Malformed JSON never raises and yields no paths.
        assert entry._payload_paths(b"{ not json") == []
        # Valid JSON without tool_input also yields no paths.
        assert entry._payload_paths(b'{"other_key": "value"}') == []
        # Valid JSON with tool_input but no path-bearing keys yields no paths.
        assert entry._payload_paths(json.dumps({"tool_input": {}}).encode()) == []

        repo = _make_repo_with_recording_guard(tmp_path)
        monkeypatch.setattr(
            "sys.stdin",
            type(
                "S",
                (),
                {
                    "buffer": type(
                        "B",
                        (),
                        {"read": staticmethod(lambda: b"{ not json")},
                    )()
                },
            )(),
        )
        monkeypatch.chdir(repo)
        # main() must not crash on malformed stdin; it falls back to
        # effective_root=repo_root and delegates to the guard as before.
        rc = entry.main([])
        assert rc == 0
        sentinel = repo / "_cwd_seen.txt"
        assert sentinel.exists()
        assert Path(sentinel.read_text(encoding="utf-8")) == repo.resolve()
