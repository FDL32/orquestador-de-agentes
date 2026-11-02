"""WOT-2026-152c: the security hooks read the motor link with utf-8-sig.

``guard_paths.py`` and ``claude_guard_entry.py`` resolve the motor THROUGH
``motor_destination_link.json``, so they cannot import ``runtime.motor_link``;
each carries a stdlib-only ``_read_link_value``. These tests pin, in two
directions, that:

* a link with the PowerShell BOM and the correct motor resolves exactly like
  the same link without BOM (the only permissive change);
* every other link (unreadable, wrong shape, forged motor, no repo marker)
  still resolves to nothing, so the hooks keep blocking -- and the shapes that
  used to CRASH (rc 1: non-string motor_root, non-UTF-8, deep nesting) now
  block (rc 2).

The three ``python -c`` bootstraps are generated strings (and are tracked
literally in ``.claude/settings.json``): they are executed here against a link
with BOM in a temp destino, never the real link.
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from runtime.motor_link import LINK_OK, read_motor_link


_ROOT = Path(__file__).resolve().parents[2]
_HOOKS = _ROOT / ".agent" / "hooks"
_BOM = b"\xef\xbb\xbf"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_gp = _load("hook152c_guard_paths", _HOOKS / "guard_paths.py")
_ge = _load("hook152c_guard_entry", _HOOKS / "claude_guard_entry.py")


class _World:
    """A fake motor, a destino linked to it, and two plain directories."""

    def __init__(self, base: Path) -> None:
        base = base.resolve()
        self.motor = base / "motor"
        hooks = self.motor / ".agent" / "hooks"
        hooks.mkdir(parents=True)
        (self.motor / ".claude").mkdir()
        for name in ("guard_paths.py", "claude_guard_entry.py"):
            shutil.copy2(_HOOKS / name, hooks / name)
        (hooks / "guard_channel_identity.py").write_text("# stub\n", encoding="utf-8")
        self.destino = base / "destino"
        (self.destino / ".claude").mkdir(parents=True)
        (self.destino / ".agent" / "config").mkdir(parents=True)
        self.other = base / "other"
        (self.other / ".git").mkdir(parents=True)
        self.bare = base / "bare"
        self.bare.mkdir()
        # A "forged" motor: real hooks but NO repo marker (.claude/.git).
        self.forged = base / "forged"
        forged_hooks = self.forged / ".agent" / "hooks"
        forged_hooks.mkdir(parents=True)
        for name in ("guard_paths.py", "claude_guard_entry.py"):
            shutil.copy2(_HOOKS / name, forged_hooks / name)
        (forged_hooks / "guard_channel_identity.py").write_text(
            "# stub\n", encoding="utf-8"
        )
        self.link = self.destino / ".agent" / "config" / "motor_destination_link.json"
        self.target = self.destino / "f.txt"

    def doc(self, motor: object = None, dest: object = None) -> dict:
        return {
            "motor_root": str(self.motor) if motor is None else motor,
            "destination_root": str(self.other) if dest is None else dest,
        }

    def put(self, raw: bytes | None) -> None:
        """Write the link bytes; ``None`` leaves it absent."""
        if self.link.is_dir():
            self.link.rmdir()
        self.link.unlink(missing_ok=True)
        if raw is not None:
            self.link.write_bytes(raw)

    def put_dir(self) -> None:
        self.link.unlink(missing_ok=True)
        self.link.mkdir()


@pytest.fixture
def world(tmp_path_factory) -> _World:
    return _World(tmp_path_factory.mktemp("w"))


def _enc(doc: object, bom: bool = False) -> bytes:
    return (_BOM if bom else b"") + json.dumps(doc).encode("utf-8")


#: form name -> builder(world) -> bytes (None = absent, "dir" = a directory).
_UNREADABLE = {
    "empty": lambda w: b"",
    "truncated": lambda w: _enc(w.doc())[:25],
    "bom_only": lambda w: _BOM,
    "bom_broken": lambda w: _BOM + b"{not json",
    "list": lambda w: b'["motor_root"]',
    "str": lambda w: b'"x"',
    "null": lambda w: b"null",
    "no_key": lambda w: b'{"other": 1}',
    "int_values": lambda w: b'{"motor_root": 123, "destination_root": 123}',
    "null_values": lambda w: b'{"motor_root": null, "destination_root": null}',
    "empty_str": lambda w: b'{"motor_root": "", "destination_root": ""}',
    "blank_str": lambda w: b'{"motor_root": "   ", "destination_root": "  "}',
    "not_utf8": lambda w: b'{"motor_root": "\xff\xfe"}',
    "utf16": lambda w: json.dumps(w.doc()).encode("utf-16"),
    "deep": lambda w: b"[" * 100000,
    "dir": lambda w: "dir",
    "absent": lambda w: None,
}

#: reader name -> (callable(world) -> value, expected value of a good link).
_READERS = {
    "G2_destino_from_target": (
        lambda w: _gp._resolve_destino_from_target(w.target, w.motor),
        lambda w: w.destino,
    ),
    "G1_extra_root_src2": (
        lambda w: _gp._resolve_extra_root(w.destino, None),
        lambda w: w.other,
    ),
    "E1_resolve_guard_paths": (
        lambda w: _ge.resolve_guard_paths(w.destino),
        lambda w: w.motor / ".agent" / "hooks" / "guard_paths.py",
    ),
    "E2_channel_identity": (
        lambda w: _ge.resolve_guard_channel_identity(w.destino),
        lambda w: w.motor / ".agent" / "hooks" / "guard_channel_identity.py",
    ),
    "E3_linked_root": (
        lambda w: _ge._linked_root(w.destino),
        lambda w: w.motor,
    ),
    "E4_destino_linked": (
        lambda w: _ge._destino_linked_to_motor(w.target, w.motor),
        lambda w: w.destino,
    ),
}


@pytest.fixture(autouse=True)
def _no_project_root(monkeypatch):
    monkeypatch.delenv("AGENT_PROJECT_ROOT", raising=False)


def _put_form(w: _World, form: str) -> None:
    built = _UNREADABLE[form](w)
    if built == "dir":
        w.put_dir()
    else:
        w.put(built)


# --------------------------------------------------------------------------
# Direction 1: BOM + correct motor == the same link without BOM (never None).
# --------------------------------------------------------------------------


@pytest.mark.parametrize("reader", sorted(_READERS))
def test_bom_link_resolves_like_the_plain_link(world: _World, reader: str):
    call, expected = _READERS[reader]
    world.put(_enc(world.doc()))
    plain = call(world)
    world.put(_enc(world.doc(), bom=True))
    with_bom = call(world)
    assert plain is not None, "control: the plain link must resolve (non-vacuous)"
    assert Path(plain) == expected(world)
    assert with_bom is not None and Path(with_bom) == Path(plain)


def test_channel_identity_guard_is_located_through_a_bom_link(world: _World):
    """Only the LOCATION of the second guard (that it RUNS is proven by process
    in ``test_channel_identity_guard_runs_through_the_link_with_or_without_bom``)."""
    world.put(_enc(world.doc(), bom=True))
    found = _ge.resolve_guard_channel_identity(world.destino)
    assert found == world.motor / ".agent" / "hooks" / "guard_channel_identity.py"


def test_authorized_roots_include_the_motor_only_with_a_marker(world: _World):
    world.put(_enc(world.doc(), bom=True))
    assert world.motor in _ge._authorized_roots(world.destino, [])
    shutil.rmtree(world.motor / ".claude")
    assert _ge._authorized_roots(world.destino, []) == [world.destino]


# --------------------------------------------------------------------------
# Direction 2: everything else still resolves to nothing (and never raises).
# --------------------------------------------------------------------------


@pytest.mark.parametrize("bom", [False, True])
@pytest.mark.parametrize("form", sorted(_UNREADABLE))
@pytest.mark.parametrize("reader", sorted(_READERS))
def test_unreadable_or_malformed_link_resolves_to_nothing(
    world: _World, reader: str, form: str, bom: bool
):
    call = _READERS[reader][0]
    _put_form(world, form)
    if bom and form not in {"dir", "absent"}:
        raw = world.link.read_bytes()
        world.put(_BOM + raw if not raw.startswith(_BOM) else raw)
    assert call(world) is None


@pytest.mark.parametrize("reader", ["G2_destino_from_target", "E4_destino_linked"])
def test_bom_link_to_another_motor_still_resolves_to_nothing(
    world: _World, reader: str
):
    call = _READERS[reader][0]
    world.put(_enc(world.doc(motor=str(world.bare)), bom=True))
    assert call(world) is None


@pytest.mark.parametrize("reader", ["E1_resolve_guard_paths", "E2_channel_identity"])
def test_bom_link_to_a_motor_without_hooks_resolves_to_nothing(
    world: _World, reader: str
):
    call = _READERS[reader][0]
    world.put(_enc(world.doc(motor=str(world.bare)), bom=True))
    assert call(world) is None


@pytest.mark.parametrize("reader", ["G2_destino_from_target", "E4_destino_linked"])
def test_bom_link_without_a_repo_marker_still_resolves_to_nothing(
    world: _World, reader: str
):
    call = _READERS[reader][0]
    world.put(_enc(world.doc(), bom=True))
    assert call(world) is not None
    shutil.rmtree(world.destino / ".claude")
    assert call(world) is None


def test_bom_destination_root_without_a_marker_or_self_pointing_is_ignored(
    world: _World,
):
    call = _READERS["G1_extra_root_src2"][0]
    world.put(_enc(world.doc(dest=str(world.bare)), bom=True))
    assert call(world) is None
    world.put(_enc(world.doc(dest=str(world.destino)), bom=True))
    assert call(world) is None


# --------------------------------------------------------------------------
# The two local readers cannot drift: equivalent to each other and to the helper.
# --------------------------------------------------------------------------

_EQUIV = dict(_UNREADABLE)
_EQUIV["good"] = lambda w: _enc(w.doc())
_EQUIV["bom_good"] = lambda w: _enc(w.doc(), bom=True)
_EQUIV["bom_other"] = lambda w: _enc(w.doc(motor=str(w.bare)), bom=True)


def _helper_value(link: Path, key: str) -> str | None:
    result = read_motor_link(link)
    if result.state != LINK_OK:
        return None
    value = result.data.get(key)
    return value if isinstance(value, str) and value.strip() else None


@pytest.mark.parametrize("key", ["motor_root", "destination_root"])
@pytest.mark.parametrize("form", sorted(_EQUIV))
def test_both_local_readers_match_each_other_and_read_motor_link(
    world: _World, form: str, key: str
):
    built = _EQUIV[form](world)
    if built == "dir":
        world.put_dir()
    else:
        world.put(built)
    from_gp = _gp._read_link_value(world.link, key)
    from_ge = _ge._read_link_value(world.link, key)
    assert from_gp == from_ge == _helper_value(world.link, key)


def _function_without_docstring(path: Path, name: str) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name]
    assert len(found) == 1, f"{path.name} must define {name} exactly once"
    fn = found[0]
    assert isinstance(fn.body[0], ast.Expr), "the reader keeps its docstring"
    fn.body = fn.body[1:]
    return ast.dump(fn)


def test_the_two_copies_of_the_reader_are_the_same_code():
    assert _function_without_docstring(
        _HOOKS / "guard_paths.py", "_read_link_value"
    ) == _function_without_docstring(
        _HOOKS / "claude_guard_entry.py", "_read_link_value"
    )


_STRICT = re.compile(r"""encoding\s*=\s*["']utf-8["']""")


def test_strict_utf8_pattern_matches_what_it_claims_to_forbid():
    assert _STRICT.search('p.read_text(encoding="utf-8")')
    assert _STRICT.search("l.read_text(encoding='utf-8')")
    assert not _STRICT.search("l.read_text(encoding='utf-8-sig')")


def test_no_hook_link_reader_or_bootstrap_is_strict_utf8():
    """Invariant (not a count): no link reader of the two hooks is strict."""
    gp_fns = (
        _gp._read_link_value,
        _gp._resolve_destino_from_target,
        _gp._resolve_extra_root,
    )
    ge_fns = (
        _ge._read_link_value,
        _ge.resolve_guard_paths,
        _ge.resolve_guard_channel_identity,
        _ge._linked_root,
        _ge._destino_linked_to_motor,
        _ge.canonical_command_for,
        _ge.canonical_hook_command,
        _ge.canonical_session_start_command,
    )
    for fn in (*gp_fns, *ge_fns):
        assert not _STRICT.search(inspect.getsource(fn)), fn.__name__
    for cmd in (
        _ge.canonical_hook_command(),
        _ge.canonical_command_for("native_stop_hook.py"),
        _ge.canonical_command_for("encoding_post_write_hook.py", "scripts"),
        _ge.canonical_session_start_command(),
    ):
        assert "encoding='utf-8-sig'" in cmd and not _STRICT.search(cmd)


def test_tracked_settings_commands_carry_the_tolerant_reader():
    settings = json.loads((_ROOT / ".claude" / "settings.json").read_text("utf-8"))
    commands = [
        h["command"]
        for entries in settings["hooks"].values()
        for entry in entries
        for h in entry["hooks"]
    ]
    assert commands
    for cmd in commands:
        assert "encoding='utf-8-sig'" in cmd and not _STRICT.search(cmd)


# --------------------------------------------------------------------------
# End to end: real hook processes (rc is the decision).
# --------------------------------------------------------------------------


def _run(argv: list[str], cwd: Path, stdin: bytes) -> tuple[int, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"AGENT_PROJECT_ROOT", "GUARD_PATHS_CONFIG"}
    }
    done = subprocess.run(
        argv, cwd=str(cwd), input=stdin, capture_output=True, env=env, timeout=120
    )
    return done.returncode, done.stderr.decode("utf-8", "replace")


def _payload(path: Path) -> bytes:
    return json.dumps(
        {"tool_name": "Write", "tool_input": {"file_path": str(path)}}
    ).encode("utf-8")


def _entry_rc(w: _World, target: Path | None = None) -> tuple[int, str]:
    script = w.motor / ".agent" / "hooks" / "claude_guard_entry.py"
    return _run(
        [sys.executable, "-I", str(script)], w.destino, _payload(target or w.target)
    )


def _guard_rc(w: _World, target: Path | None = None) -> tuple[int, str]:
    script = w.motor / ".agent" / "hooks" / "guard_paths.py"
    return _run(
        [sys.executable, "-I", str(script)], w.motor, _payload(target or w.target)
    )


def test_entry_process_bom_link_allows_like_the_plain_link(world: _World):
    world.put(_enc(world.doc()))
    assert _entry_rc(world)[0] == 0
    world.put(_enc(world.doc(), bom=True))
    assert _entry_rc(world)[0] == 0
    world.put(None)
    assert _entry_rc(world)[0] == 2, "control: with no link the entry blocks"


@pytest.mark.parametrize(
    "form",
    [
        "bom_broken",
        "list",
        "int_values",
        "not_utf8",
        "utf16",
        "deep",
        "no_key",
        "null",
    ],
)
def test_entry_process_blocks_every_unreadable_link_with_rc_2(world: _World, form: str):
    """Includes the shapes that used to crash with rc 1 (fail-open in the harness)."""
    _put_form(world, form)
    rc, err = _entry_rc(world)
    assert rc == 2, err


def test_entry_process_bom_link_to_a_motor_without_guard_still_blocks(
    world: _World,
):
    world.put(_enc(world.doc(motor=str(world.bare)), bom=True))
    assert _entry_rc(world)[0] == 2


def test_guard_process_bom_link_allows_like_the_plain_link(world: _World):
    world.put(_enc(world.doc()))
    assert _guard_rc(world)[0] == 0
    world.put(_enc(world.doc(), bom=True))
    assert _guard_rc(world)[0] == 0
    world.put(None)
    rc, err = _guard_rc(world)
    assert rc == 2 and "fuera del repo" in err, "control: no link -> outside repo"


def test_guard_process_keeps_its_policy_for_protected_paths_with_a_bom_link(
    world: _World,
):
    world.put(_enc(world.doc(), bom=True))
    rc, err = _guard_rc(world, world.destino / ".env")
    assert rc == 2 and "archivo protegido" in err, err


@pytest.mark.parametrize(
    "form",
    [
        "bom_broken",
        "list",
        "null",
        "no_key",
        "int_values",
        "not_utf8",
        "utf16",
        "deep",
        "dir",
        "truncated",
    ],
)
def test_guard_process_blocks_every_unreadable_link_with_rc_2(world: _World, form: str):
    _put_form(world, form)
    rc, err = _guard_rc(world)
    assert rc == 2 and "fuera del repo" in err, err


def test_guard_process_bom_link_to_another_motor_or_without_marker_blocks(
    world: _World,
):
    world.put(_enc(world.doc(motor=str(world.bare)), bom=True))
    assert _guard_rc(world)[0] == 2
    world.put(_enc(world.doc(), bom=True))
    assert _guard_rc(world)[0] == 0
    shutil.rmtree(world.destino / ".claude")
    assert _guard_rc(world)[0] == 2


# --------------------------------------------------------------------------
# The three generated `python -c` bootstraps, executed against a BOM link.
# --------------------------------------------------------------------------

_STUB = (
    "import pathlib, sys\n"
    "sys.stdin.buffer.read()\n"
    "pathlib.Path(sys.argv[0] + '.ran').write_text('ok', encoding='utf-8')\n"
)

_BOOTSTRAPS = {
    "write_guard": (
        lambda: _ge.canonical_hook_command(),
        Path(".agent/hooks/claude_guard_entry.py"),
    ),
    "generic_hook": (
        lambda: _ge.canonical_command_for("native_stop_hook.py"),
        Path(".agent/hooks/native_stop_hook.py"),
    ),
    "generic_script": (
        lambda: _ge.canonical_command_for("encoding_post_write_hook.py", "scripts"),
        Path("scripts/encoding_post_write_hook.py"),
    ),
    "session_start": (
        lambda: _ge.canonical_session_start_command(),
        Path(".agent/hooks/session_start_hook.py"),
    ),
}


def _run_bootstrap(w: _World, name: str, motor: Path | None = None) -> tuple[int, Path]:
    make, rel = _BOOTSTRAPS[name]
    stub = (motor or w.motor) / rel
    stub.parent.mkdir(parents=True, exist_ok=True)
    stub.write_text(_STUB, encoding="utf-8")
    marker = Path(str(stub) + ".ran")
    marker.unlink(missing_ok=True)
    cmd = make()
    assert cmd.startswith('python -c "') and cmd.endswith('"')
    rc, _ = _run(
        [sys.executable, "-I", "-c", cmd[len('python -c "') : -1]], w.destino, b"{}"
    )
    return rc, marker


@pytest.mark.parametrize("name", sorted(_BOOTSTRAPS))
def test_generated_bootstrap_runs_the_motor_hook_through_a_bom_link(
    world: _World, name: str
):
    world.put(_enc(world.doc()))
    rc_plain, marker = _run_bootstrap(world, name)
    assert rc_plain == 0 and marker.exists(), "control: the plain link works"
    world.put(_enc(world.doc(), bom=True))
    rc_bom, marker = _run_bootstrap(world, name)
    assert rc_bom == 0 and marker.exists()


@pytest.mark.parametrize("name", sorted(_BOOTSTRAPS))
def test_generated_bootstrap_does_not_run_the_hook_through_an_unreadable_link(
    world: _World, name: str
):
    """Declared limit (152c / H155): this pins ONLY "the hook is not executed and the
    bootstrap exits non-zero". It does NOT pin "the write is blocked": the
    bootstrap crashes with rc 1 (an uncaught traceback), and in Claude Code only
    rc 2 blocks. Making these bootstraps fail closed (rc 2) is H155's design,
    deliberately not done here (a generic excepthook would also change the
    non-security Stop/SessionStart hooks)."""
    world.put(_BOM + b"{not json")
    rc, marker = _run_bootstrap(world, name)
    assert rc != 0 and not marker.exists()


# --------------------------------------------------------------------------
# Round 2: the BOM changes NOTHING versus the same link without BOM.
# --------------------------------------------------------------------------

_CHANNEL_STUB = (
    "import pathlib, sys\n"
    "sys.stdin.buffer.read()\n"
    "pathlib.Path(sys.argv[0] + '.ran').write_text('ok', encoding='utf-8')\n"
    "sys.exit({code})\n"
)


@pytest.mark.parametrize("code", [0, 2])
@pytest.mark.parametrize("bom", [False, True])
def test_channel_identity_guard_runs_through_the_link_with_or_without_bom(
    world: _World, bom: bool, code: int
):
    """The second guard EXECUTES (marker) and its rc propagates, BOM or not."""
    own = world.destino / ".agent" / "hooks"
    own.mkdir(parents=True)
    shutil.copy2(_HOOKS / "guard_paths.py", own / "guard_paths.py")
    stub = world.motor / ".agent" / "hooks" / "guard_channel_identity.py"
    stub.write_text(_CHANNEL_STUB.format(code=code), encoding="utf-8")
    marker = Path(str(stub) + ".ran")
    world.put(_enc(world.doc(), bom=bom))
    rc, err = _entry_rc(world)
    assert marker.exists() and rc == code, err


def test_channel_identity_guard_is_skipped_by_an_unreadable_link(world: _World):
    """Control: additive by design, an unreadable link skips it (rc 0, no marker)."""
    own = world.destino / ".agent" / "hooks"
    own.mkdir(parents=True)
    shutil.copy2(_HOOKS / "guard_paths.py", own / "guard_paths.py")
    stub = world.motor / ".agent" / "hooks" / "guard_channel_identity.py"
    stub.write_text(_CHANNEL_STUB.format(code=2), encoding="utf-8")
    world.put(_BOM + b"{not json")
    rc, _ = _entry_rc(world)
    assert rc == 0 and not Path(str(stub) + ".ran").exists()


def _forged(w: _World, bom: bool) -> bytes:
    return _enc(w.doc(motor=str(w.forged)), bom=bom)


def _both(w: _World, fn):
    """Evaluate ``fn`` against the plain link and the BOM link; return both."""
    w.put(_forged(w, bom=False))
    plain = fn()
    w.put(_forged(w, bom=True))
    return plain, fn()


def test_forged_motor_without_marker_resolves_identically_with_or_without_bom(
    world: _World,
):
    """Level 1 (resolution). The invariant is "BOM changes nothing", not "blocks":
    a linked motor with hooks but no repo marker is trusted by link design
    (declared LIMIT); the repo-marker check only excludes it from the authorized
    roots, with or without BOM."""
    readers = {
        "G2": lambda: _gp._resolve_destino_from_target(world.target, world.forged),
        "E1": lambda: _ge.resolve_guard_paths(world.destino),
        "E2": lambda: _ge.resolve_guard_channel_identity(world.destino),
        "E3": lambda: _ge._linked_root(world.destino),
        "E4": lambda: _ge._destino_linked_to_motor(world.target, world.forged),
        "roots": lambda: _ge._authorized_roots(world.destino, [str(world.target)]),
    }
    for name, fn in readers.items():
        plain, with_bom = _both(world, fn)
        assert plain == with_bom, name
        assert plain not in (None, []), f"control: {name} exercises the forged motor"
    plain, _ = _both(world, readers["roots"])
    assert plain == [world.destino], "no marker: the forged motor is not a root"
    (world.forged / ".git").mkdir()
    plain, with_bom = _both(world, readers["roots"])
    assert plain == with_bom == [world.destino, world.forged]


def test_forged_motor_authorization_by_process_is_the_same_with_or_without_bom(
    world: _World,
):
    """Level 2 (authorization): guard_paths run AS the forged motor."""
    script = world.forged / ".agent" / "hooks" / "guard_paths.py"

    def run():
        return _run(
            [sys.executable, "-I", str(script)], world.forged, _payload(world.target)
        )

    plain, with_bom = _both(world, run)
    assert plain[0] == 0, "control: the plain link is accepted by design"
    assert with_bom == plain
    shutil.rmtree(world.destino / ".claude")
    plain, with_bom = _both(world, run)
    assert plain[0] == 2 and with_bom == plain, "no marker on the destino: both block"


def test_forged_motor_entry_process_is_the_same_with_or_without_bom(world: _World):
    """Level 3a (execution through entry.py): the forged motor's guard runs."""
    script = world.forged / ".agent" / "hooks" / "claude_guard_entry.py"

    def run():
        return _run(
            [sys.executable, "-I", str(script)], world.destino, _payload(world.target)
        )

    plain, with_bom = _both(world, run)
    assert plain[0] == 0, "control: by design the linked motor's guard is trusted"
    assert with_bom == plain


@pytest.mark.parametrize("name", sorted(_BOOTSTRAPS))
def test_forged_motor_bootstrap_is_the_same_with_or_without_bom(
    world: _World, name: str
):
    """Level 3b (execution through the generated bootstrap)."""

    def run():
        rc, marker = _run_bootstrap(world, name, world.forged)
        return rc, marker.exists()

    plain, with_bom = _both(world, run)
    assert plain == (0, True), "control: the stub ran with the plain link"
    assert with_bom == plain
