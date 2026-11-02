"""WOT-2026-152b-1: six workspace/destino link readers go through the tolerant loader.

``backlog_reconcile``, ``check_backlog_commits_landed``, ``check_guard_wiring``,
``check_claude_settings_portability``, ``check_settings_canonical_drift`` and
``create_worktree_pair`` used to read ``motor_destination_link.json`` with a strict
``utf-8``; a link written by PowerShell 5.1 (UTF-8 BOM) looked unreadable to all of
them. They now call ``prefix_resolver._read_link`` (the 152a loader of
``runtime.motor_link.read_motor_link``).

Observable changes authorised by the coordinator (O1-O5), all pinned below:

- O1/O2/O3: a link that is a JSON non-object, not UTF-8, or nested too deeply used
  to RAISE (``AttributeError``/``UnicodeDecodeError``/``RecursionError``); it now
  degrades to each reader's own "unreadable" value (fail-closed, never a pass).
- O4: a directory where the link should be reads "unreadable: io" in the trio
  (it used to say "not found").
- O5: the reason carries the helper's cause prefix (``json:``, ``decode:``, ...).

Fail-closed on a loader name that cannot be imported (absent, renamed or raising on
access): every module defines a synthetic ``_read_link`` returning
``(None, "import: ...")``.

Limit L (declared, not widened): ``backlog_reconcile`` and
``check_backlog_commits_landed`` already imported ``resolve_ticket_alternation`` from
``prefix_resolver`` unguarded BEFORE this ticket. If ``prefix_resolver`` fails while it
initialises, that earlier import raises before the synthetic ``_read_link`` exists:
a traceback that is PRE-EXISTING and unchanged (pinned by
``test_limit_l_a_prefix_resolver_that_fails_to_initialise_still_raises_in_two_modules``).
The "unreadable, never a traceback" guarantee covers the loader NAME in all six
modules and any import failure in the four modules without that earlier import
(portability, guard_wiring, drift, create_worktree_pair).
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
import scripts.backlog_reconcile as br
import scripts.check_backlog_commits_landed as cb
import scripts.check_claude_settings_portability as cp
import scripts.check_guard_wiring as gw
import scripts.check_settings_canonical_drift as dr
import scripts.create_worktree_pair as cw
import scripts.prefix_resolver as pr


REPO = Path(__file__).resolve().parents[2]
LINK_REL = Path(".agent") / "config" / "motor_destination_link.json"
BOM = b"\xef\xbb\xbf"

# Forms that must read as "the link is not there" vs "there but cannot be read".
ABSENT_FORMS = ["absent", "broken-symlink"]
UNREADABLE_FORMS = ["empty", "truncated", "list", "non-utf8", "directory", "deep"]
# O1/O2/O3: these RAISED in the old strict readers.
FORMERLY_RAISING = ["list", "non-utf8", "deep"]


class _World:
    """A motor dir with the guard entry, a destino dir, and a roots dir for the drift scan."""

    def __init__(self, tmp: Path) -> None:
        self.motor = tmp / "motor_wt"
        hooks = self.motor / ".agent" / "hooks"
        hooks.mkdir(parents=True)
        (hooks / "claude_guard_entry.py").write_text("# stub\n", encoding="utf-8")
        self.dest = tmp / "dest_wt"
        self.dest.mkdir()
        self.roots = tmp / "roots"
        (self.roots / "ws1").mkdir(parents=True)

    def payload(self) -> dict:
        return {
            "motor_root": self.motor.as_posix(),
            "destination_root": self.dest.as_posix(),
            "ticket_prefix": "WOT",
        }


def _link_bytes(form: str, payload: dict) -> bytes | None:
    """The bytes of a file-shaped ``form``; None for absent/directory/symlink forms."""
    raw = json.dumps(payload).encode("utf-8")
    shaped = {
        "plain": raw,
        "bom": BOM + raw,
        "empty": b"",
        "truncated": raw[: len(raw) // 2],
        "list": b'["x"]',
        "non-utf8": b'{"motor_root": "caf\xe9"}',
        "deep": b"[" * 200000 + b"]" * 200000,
        "no-dest": json.dumps({"motor_root": payload["motor_root"]}).encode(),
    }
    if form in shaped:
        return shaped[form]
    assert form in ("absent", "directory", "broken-symlink"), form
    return None


def _write_link(link: Path, form: str, payload: dict) -> None:
    """(Re)create ``link`` in ``form``; an earlier form is removed first."""
    if link.is_symlink() or link.is_file():
        link.unlink()
    elif link.is_dir():
        link.rmdir()
    link.parent.mkdir(parents=True, exist_ok=True)
    content = _link_bytes(form, payload)
    if content is not None:
        link.write_bytes(content)
    elif form == "directory":
        link.mkdir()
    elif form == "broken-symlink":
        try:
            os.symlink(str(link.parent / "no_such_target"), str(link))
        except (OSError, NotImplementedError):
            pytest.skip("symlinks cannot be created here")


@pytest.fixture(autouse=True)
def _no_env_root(monkeypatch):
    monkeypatch.delenv("AGENT_PROJECT_ROOT", raising=False)


@pytest.fixture
def world(tmp_path):
    return _World(tmp_path)


@dataclass(frozen=True)
class _Reader:
    """One link reader: how to call it and what it returns healthy / degraded."""

    name: str
    ws_rel: str
    call: Callable[[_World, Path], object]
    healthy: Callable[[_World], object]
    absent: Callable[[object, Path], bool]
    unreadable: Callable[[object, Path], bool]

    def link(self, w: _World) -> Path:
        return w.dest.parent / self.ws_rel / LINK_REL


def _trio(mod) -> Callable:
    return lambda w, ws: mod._resolve_destino_root(None, str(ws))


def _trio_reader(name: str, mod) -> _Reader:
    return _Reader(
        name=name,
        ws_rel="dest_wt",
        call=_trio(mod),
        healthy=lambda w: (w.dest.resolve(), None),
        absent=lambda r, ws: (
            r[0] is None and r[1] == f"motor_destination_link.json not found under {ws}"
        ),
        unreadable=lambda r, ws: (
            r[0] is None and r[1].startswith("motor_destination_link.json unreadable: ")
        ),
    )


def _diag_output(w: _World, capsys) -> str:
    capsys.readouterr()
    cw._print_partial_diagnostic(w.motor, w.dest, w.motor.parent / "mr", w.dest)
    return capsys.readouterr().out


READERS = [
    _trio_reader("backlog_reconcile", br),
    _trio_reader("check_backlog_commits_landed", cb),
    _trio_reader("check_guard_wiring", gw),
    _Reader(
        name="portability._resolve_link",
        ws_rel="dest_wt",
        call=lambda w, ws: cp._resolve_link(w.dest / LINK_REL),
        healthy=lambda w: (w.dest.resolve(), w.motor.resolve(), None),
        absent=lambda r, ws: (
            r[:2] == (None, None) and r[2].startswith("unreadable link (")
        ),
        unreadable=lambda r, ws: (
            r[:2] == (None, None) and r[2].startswith("unreadable link (")
        ),
    ),
    _Reader(
        name="portability._canonical_entry_resolves",
        ws_rel="dest_wt",
        call=lambda w, ws: cp._canonical_entry_resolves(w.dest),
        healthy=lambda w: True,
        absent=lambda r, ws: r is False,
        unreadable=lambda r, ws: r is False,
    ),
    _Reader(
        name="drift.discover_destinos",
        ws_rel="roots/ws1",
        call=lambda w, ws: dr.discover_destinos([w.roots]),
        healthy=lambda w: ([w.dest], []),
        absent=lambda r, ws: r == ([], []),
        unreadable=lambda r, ws: (
            r[0] == [] and len(r[1]) == 1 and "JSON invalido o ilegible (" in r[1][0]
        ),
    ),
    _Reader(
        name="create_worktree_pair.classify_pair_state",
        ws_rel="dest_wt",
        call=lambda w, ws: cw.classify_pair_state(w.motor, w.dest),
        healthy=lambda w: "complete",
        absent=lambda r, ws: r == "partial",
        unreadable=lambda r, ws: r == "partial",
    ),
]
IDS = [r.name for r in READERS]


def _prepare(w: _World, reader: _Reader, form: str) -> Path:
    ws = w.dest.parent / reader.ws_rel
    payload = w.payload()
    # The drift scan reaches the destino through ``destination_root``; the other
    # readers look at the link inside ``dest_wt`` itself.
    _write_link(reader.link(w), form, payload)
    return ws


@pytest.mark.parametrize("reader", READERS, ids=IDS)
def test_bom_link_resolves_like_the_plain_link(world, reader):
    """DoD 3: the same link with a BOM gives the same result as without it."""
    ws = _prepare(world, reader, "plain")
    plain = reader.call(world, ws)
    assert plain == reader.healthy(
        world
    )  # control: the plain link is the healthy value
    _write_link(reader.link(world), "bom", world.payload())
    assert reader.call(world, ws) == plain
    _write_link(reader.link(world), "empty", world.payload())
    assert reader.call(world, ws) != plain  # control: the reader does see the link


@pytest.mark.parametrize("reader", READERS, ids=IDS)
@pytest.mark.parametrize("form", ABSENT_FORMS)
def test_absent_link_keeps_each_readers_value(world, reader, form):
    ws = _prepare(world, reader, form)
    assert reader.absent(reader.call(world, ws), ws)


@pytest.mark.parametrize("reader", READERS, ids=IDS)
@pytest.mark.parametrize("form", UNREADABLE_FORMS)
def test_unreadable_link_keeps_each_readers_value(world, reader, form):
    """Includes O1/O2/O3: forms that raised before now degrade, never raise."""
    ws = _prepare(world, reader, form)
    result = reader.call(world, ws)  # must not raise
    assert reader.unreadable(result, ws), result
    assert result != reader.healthy(world)


@pytest.mark.parametrize("form", FORMERLY_RAISING)
@pytest.mark.parametrize("module", [br, cb, gw], ids=["reconcile", "landed", "wiring"])
def test_trio_reason_carries_the_helper_cause(world, module, form):
    """O5: the reason names the cause (json/decode/not-a-dict), after ``unreadable: ``."""
    reader = _trio_reader("x", module)
    ws = _prepare(world, reader, form)
    _, reason = reader.call(world, ws)
    cause = {"list": "not-a-dict", "non-utf8": "decode", "deep": "json"}[form]
    assert reason.startswith(f"motor_destination_link.json unreadable: {cause}")


@pytest.mark.parametrize("module", [br, cb, gw], ids=["reconcile", "landed", "wiring"])
def test_trio_directory_in_place_of_the_link_reads_io(world, module):
    """O4: a directory is unreadable (io), no longer "not found"."""
    reader = _trio_reader("x", module)
    ws = _prepare(world, reader, "directory")
    _, reason = reader.call(world, ws)
    assert reason.startswith("motor_destination_link.json unreadable: io")
    assert "not found" not in reason


@pytest.mark.parametrize("module", [br, cb, gw], ids=["reconcile", "landed", "wiring"])
def test_trio_link_without_destination_root_keeps_its_message(world, module):
    reader = _trio_reader("x", module)
    ws = _prepare(world, reader, "no-dest")
    assert reader.call(world, ws) == (
        None,
        "motor_destination_link.json has no destination_root",
    )


def test_portability_and_drift_keep_the_no_destination_root_messages(world):
    _write_link(world.dest / LINK_REL, "no-dest", world.payload())
    assert cp._resolve_link(world.dest / LINK_REL)[2] == (
        "no destination_root in motor_destination_link.json"
    )
    _write_link(world.roots / "ws1" / LINK_REL, "no-dest", world.payload())
    dests, problems = dr.discover_destinos([world.roots])
    assert dests == []
    assert problems[0].endswith("destination_root ausente o no es directorio")


@pytest.mark.parametrize("form", ["plain", "bom"])
def test_create_pair_diagnostic_reads_the_link_the_same_with_or_without_bom(
    world, capsys, form
):
    _write_link(world.dest / LINK_REL, form, world.payload())
    out = _diag_output(world, capsys)
    assert "no se pudo leer" not in out
    assert (
        "worktree git valido" in out
    )  # went on to the git check, as with a healthy link


@pytest.mark.parametrize("form", UNREADABLE_FORMS)
def test_create_pair_diagnostic_says_it_cannot_read_an_unreadable_link(
    world, capsys, form
):
    """Includes O1/O3: ``list`` and ``deep`` used to raise out of the diagnostic."""
    _write_link(world.dest / LINK_REL, form, world.payload())
    assert "no se pudo leer el link" in _diag_output(world, capsys)


def test_create_pair_diagnostic_keeps_reporting_a_missing_link(world, capsys):
    _write_link(world.dest / LINK_REL, "absent", world.payload())
    assert "no existe" in _diag_output(world, capsys)


def test_canonical_entry_found_through_a_bom_link_only_when_the_motor_has_it(world):
    """The motor's guard entry is reached through the link; without it, False."""
    _write_link(world.dest / LINK_REL, "bom", world.payload())
    assert cp._canonical_entry_resolves(world.dest) is True
    (world.motor / ".agent" / "hooks" / "claude_guard_entry.py").unlink()
    assert cp._canonical_entry_resolves(world.dest) is False


# --- the loader this ticket consumes -------------------------------------------------

MODULES = [
    ("scripts/backlog_reconcile.py", br),
    ("scripts/check_backlog_commits_landed.py", cb),
    ("scripts/check_guard_wiring.py", gw),
    ("scripts/check_claude_settings_portability.py", cp),
    ("scripts/check_settings_canonical_drift.py", dr),
    ("scripts/create_worktree_pair.py", cw),
]
MODULE_IDS = [rel.split("/")[-1] for rel, _ in MODULES]


def test_the_private_loader_this_ticket_consumes_exists_with_its_contract(tmp_path):
    """Pins the private name and the two outcomes the readers branch on.

    If 152a renames ``prefix_resolver._read_link`` or changes the "missing" reason,
    this fails first instead of the readers degrading silently.
    """
    assert callable(pr._read_link)
    link = tmp_path / "link.json"
    assert pr._read_link(link) == (None, "missing")
    link.write_bytes(BOM + b'{"a": 1}')
    assert pr._read_link(link) == ({"a": 1}, None)
    link.write_bytes(b"")
    data, reason = pr._read_link(link)
    assert data is None and reason.startswith("json")


@pytest.mark.parametrize("mod", [m for _, m in MODULES], ids=MODULE_IDS)
def test_every_migrated_module_uses_the_prefix_resolver_loader(mod):
    assert mod._read_link is pr._read_link


class _ExplodingResolver(types.ModuleType):
    """A ``prefix_resolver`` whose ``_read_link`` raises on access (any exception)."""

    def __getattr__(self, name: str):
        if name == "_read_link":
            raise RuntimeError("loader exploded")
        raise AttributeError(name)


def _install_broken_resolver(monkeypatch, kind: str) -> None:
    """kind 'raises': attribute access raises; 'renamed': the name is gone (ImportError)."""
    fake = (
        _ExplodingResolver("prefix_resolver")
        if kind == "raises"
        else types.ModuleType("prefix_resolver")
    )
    fake.resolve_ticket_alternation = pr.resolve_ticket_alternation
    monkeypatch.setitem(sys.modules, "scripts.prefix_resolver", fake)
    monkeypatch.setitem(sys.modules, "prefix_resolver", fake)


def _load_fresh(rel: str):
    name = "_b1_fresh_" + Path(rel).stem
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    module = importlib.util.module_from_spec(spec)
    # ``@dataclass`` under ``from __future__ import annotations`` resolves the
    # class's module through ``sys.modules`` while the module body runs.
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


@pytest.mark.parametrize("kind", ["raises", "renamed"])
@pytest.mark.parametrize("rel", [r for r, _ in MODULES], ids=MODULE_IDS)
def test_a_loader_that_cannot_be_imported_makes_the_link_unreadable(
    world, monkeypatch, rel, kind
):
    """Any import failure -> synthetic ``(None, 'import: ...')``; no traceback, no pass."""
    _install_broken_resolver(monkeypatch, kind)
    fresh = _load_fresh(rel)
    plain = world.dest / LINK_REL
    _write_link(plain, "plain", world.payload())  # a perfectly healthy link
    data, reason = fresh._read_link(plain)
    assert data is None
    assert reason.startswith("import: ")
    assert fresh._read_link is not pr._read_link


@pytest.mark.parametrize("kind", ["raises", "renamed"])
def test_every_reader_degrades_when_the_loader_cannot_be_imported(
    world, monkeypatch, capsys, kind
):
    """A healthy link still reads as unreadable in each reader (fail-closed)."""
    _install_broken_resolver(monkeypatch, kind)
    ws = world.dest
    _write_link(world.dest / LINK_REL, "plain", world.payload())
    _write_link(world.roots / "ws1" / LINK_REL, "plain", world.payload())
    for mod_name, rel in [
        ("reconcile", "scripts/backlog_reconcile.py"),
        ("landed", "scripts/check_backlog_commits_landed.py"),
        ("wiring", "scripts/check_guard_wiring.py"),
    ]:
        fresh = _load_fresh(rel)
        dest, reason = fresh._resolve_destino_root(None, str(ws))
        assert dest is None, mod_name
        assert reason.startswith("motor_destination_link.json unreadable: import: ")
    fresh = _load_fresh("scripts/check_claude_settings_portability.py")
    assert fresh._resolve_link(world.dest / LINK_REL)[:2] == (None, None)
    assert fresh._resolve_link(world.dest / LINK_REL)[2].startswith(
        "unreadable link (import: "
    )
    assert fresh._canonical_entry_resolves(world.dest) is False
    fresh = _load_fresh("scripts/check_settings_canonical_drift.py")
    dests, problems = fresh.discover_destinos([world.roots])
    assert dests == [] and "import: " in problems[0]
    fresh = _load_fresh("scripts/create_worktree_pair.py")
    assert fresh.classify_pair_state(world.motor, world.dest) == "partial"
    capsys.readouterr()
    fresh._print_partial_diagnostic(world.motor, world.dest, world.dest, world.dest)
    out = capsys.readouterr().out
    assert "no se pudo leer el link" in out
    assert "apunta a" not in out and "worktree git valido" not in out


class _InitFailingResolver(types.ModuleType):
    """A ``prefix_resolver`` whose initialisation failed: every name raises."""

    def __getattr__(self, name: str):
        raise RuntimeError("prefix_resolver failed to initialise")


@pytest.mark.parametrize(
    "rel",
    ["scripts/backlog_reconcile.py", "scripts/check_backlog_commits_landed.py"],
    ids=["backlog_reconcile", "check_backlog_commits_landed"],
)
def test_limit_l_a_prefix_resolver_that_fails_to_initialise_still_raises_in_two_modules(
    monkeypatch, rel
):
    """Pre-existing: their earlier unguarded import raises; this ticket leaves it alone."""
    fake = _InitFailingResolver("prefix_resolver")
    monkeypatch.setitem(sys.modules, "scripts.prefix_resolver", fake)
    monkeypatch.setitem(sys.modules, "prefix_resolver", fake)
    with pytest.raises(RuntimeError, match="failed to initialise"):
        _load_fresh(rel)


@pytest.mark.parametrize(
    "rel",
    [
        "scripts/check_guard_wiring.py",
        "scripts/check_claude_settings_portability.py",
        "scripts/check_settings_canonical_drift.py",
        "scripts/create_worktree_pair.py",
    ],
    ids=["guard_wiring", "portability", "drift", "create_worktree_pair"],
)
def test_the_four_modules_without_an_earlier_import_survive_a_failed_initialisation(
    monkeypatch, rel
):
    """No earlier import of prefix_resolver: the failure becomes an unreadable link."""
    fake = _InitFailingResolver("prefix_resolver")
    monkeypatch.setitem(sys.modules, "scripts.prefix_resolver", fake)
    monkeypatch.setitem(sys.modules, "prefix_resolver", fake)
    fresh = _load_fresh(rel)
    data, reason = fresh._read_link(Path("any.json"))
    assert data is None and reason.startswith("import: ")
