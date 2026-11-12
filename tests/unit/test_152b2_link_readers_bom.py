"""WOT-2026-152b-2: the remaining five strict link readers become BOM-tolerant.

``delivery_hygiene_check`` and ``export_review_packet`` read the link through
``prefix_resolver._read_link`` (loader B, like 152b-1). Three readers cannot depend on
importing the motor and carry a LOCAL tolerant reader, each compared with
``runtime.motor_link.read_motor_link`` for equivalence of the dict/None RESULT on the 14
forms of ``EQUIV_FORMS`` (not of the helper's states or reasons; there is no
no-permission form):

- ``encoding_post_write_hook._read_link_dict`` (a HOOK: stdlib only);
- the ``_read_link`` inside ``collect_session_state._QUARANTINE_SCRIPT_TEMPLATE`` (the
  ``python -c`` template finds the motor THROUGH the link);
- ``.agent/motor_checkpoint._read_link`` (loads the helper of ITS OWN motor by path; it
  lives in ``.agent/`` and cannot import ``scripts.*``).

Observable changes (O1-O5 authorised for 152b-1, same here) plus two more. What each
reader ALREADY degraded before this ticket vs what ESCAPED with an exception:

====================  =====================================  ================================
reader                already degraded                       escaped (now degrades)
====================  =====================================  ================================
delivery_hygiene      non-object, non-UTF-8, invalid JSON,   RecursionError
                      non-string, empty string
export_review_packet  non-UTF-8, invalid JSON, OSError,      non-object (AttributeError),
                      empty string                           RecursionError, non-string
motor_checkpoint      absent, invalid JSON, OSError,         non-object, non-UTF-8,
                      empty string                           RecursionError, non-string, NUL
hook (_resolve_...)   absent, invalid JSON, OSError,         non-object, non-UTF-8,
                      empty string                           RecursionError, non-string, NUL
collect template      non-object, non-UTF-8, non-string,     RecursionError (rc != 0 ->
                      NUL, invalid JSON, OSError             "no_measure")
====================  =====================================  ================================

- O1/O2/O3: a non-object, non-UTF-8 or too deeply nested link degrades to each reader's
  fallback (the "escaped" column above; fail-closed).
- O6: ``destination_root``/``motor_root`` that is not a non-empty string is rejected by
  the readers that RESOLVE the path (hook, motor_checkpoint, collect template). A NUL
  byte (which makes ``Path.resolve`` raise ``ValueError``) is rejected by those three; a
  whitespace-only value is rejected ONLY by the hook (O7): motor_checkpoint and the
  collect template resolve it as before (to the cwd). In the collect template an empty
  ``motor_root`` used to resolve to the current directory.
  ``delivery_hygiene_check`` and ``export_review_packet`` only return the value
  unresolved: they do NOT reject NUL or whitespace-only (behaviour unchanged, pinned by
  ``test_value_table_per_reader``).
- O7 (hook only): a whitespace-only ``destination_root`` used to be truthy and resolve
  (on Windows ``Path('   ').resolve()`` is the process cwd, which WIDENED the allowed
  roots); it is now rejected with ``.strip()`` (fail-closed).

Limit L (precise): neither ``delivery_hygiene_check`` nor ``export_review_packet``
imported ``prefix_resolver`` before this ticket, so a failed initialisation of it is
covered here (``test_a_failed_initialisation_...``); there is no unguarded earlier import.
For the hook, an unreadable link degrades to the fallback WITHOUT widening the allowed
roots: the destino files are then skipped with a WARN (rc 0, as with a missing link).
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
import subprocess
import sys
import types
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import pytest
import scripts.collect_session_state as cs
import scripts.delivery_hygiene_check as dh
import scripts.encoding_post_write_hook as eh
import scripts.export_review_packet as ex
import scripts.prefix_resolver as pr
from runtime.motor_link import LINK_OK, read_motor_link

from tests.unit.test_152a_link_readers_bom import STRICT_ENCODINGS, _read_call


REPO = Path(__file__).resolve().parents[2]
LINK_REL = Path(".agent") / "config" / "motor_destination_link.json"
BOM = b"\xef\xbb\xbf"

ABSENT_FORMS = ["absent", "broken-symlink"]
UNREADABLE_FORMS = [
    "empty",
    "truncated",
    "list",
    "non-utf8",
    "directory",
    "deep",
    "field-not-str",
    "empty-string",
]
ALL_FORMS = [*ABSENT_FORMS, "plain", "bom", "no-dest", *UNREADABLE_FORMS]


class _World:
    """A motor dir, a destino dir and a ``repo`` dir (cwd of the hook)."""

    def __init__(self, tmp: Path) -> None:
        self.motor = tmp / "motor_wt"
        self.motor.mkdir()
        self.dest = tmp / "dest_wt"
        self.dest.mkdir()
        self.repo = tmp / "repo"
        (self.repo / ".claude").mkdir(parents=True)

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
        "no-dest": json.dumps({"ticket_prefix": "WOT"}).encode(),
        "field-not-str": json.dumps({"motor_root": 5, "destination_root": 5}).encode(),
        "empty-string": json.dumps({"motor_root": "", "destination_root": ""}).encode(),
        "nul-dest": json.dumps({"destination_root": "a\u0000b"}).encode(),
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


def _load_by_path(rel: str, name: str, monkeypatch):
    """Load ``rel`` as a fresh module (``.agent`` goes on sys.path for scope_gate)."""
    monkeypatch.syspath_prepend(str(REPO / ".agent"))
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


@pytest.fixture
def mc(monkeypatch):
    return _load_by_path(
        ".agent/motor_checkpoint.py", "_b2_motor_checkpoint", monkeypatch
    )


@dataclass(frozen=True)
class _Reader:
    """One link reader: where its link lives, how to call it, healthy/degraded values."""

    name: str
    link_in: Callable[[_World], Path]
    call: Callable[..., object]
    healthy: Callable[[_World], object]
    degraded: Callable[[object, _World], bool]


def _readers() -> list[_Reader]:
    return [
        _Reader(
            "delivery_hygiene_check._read_link_field",
            lambda w: w.dest,
            lambda w, mc: dh._read_link_field(w.dest, "motor_root"),
            lambda w: w.motor.as_posix(),
            lambda r, w: r is None,
        ),
        _Reader(
            "export_review_packet._linked_motor_root",
            lambda w: w.dest,
            lambda w, mc: ex._linked_motor_root(w.dest),
            lambda w: Path(w.motor.as_posix()),
            lambda r, w: r is None,
        ),
        _Reader(
            "motor_checkpoint.resolve_destino_root",
            lambda w: w.motor,
            lambda w, mc: mc.resolve_destino_root(w.motor, None),
            lambda w: w.dest.resolve(),
            lambda r, w: r == w.motor,
        ),
        _Reader(
            "encoding_post_write_hook._resolve_destino",
            lambda w: w.repo,
            lambda w, mc: eh._resolve_destino(w.repo),
            lambda w: w.dest.resolve(),
            lambda r, w: r is None,
        ),
        _Reader(
            "collect_session_state.collect_quarantine",
            lambda w: w.dest,
            lambda w, mc: _quarantine(w),
            lambda w: ("no_module", "cuarentena: modulo no disponible"),
            lambda r, w: r == ("no_link", cs.LABEL_LINK),
        ),
    ]


def _quarantine(w: _World) -> tuple[str, str]:
    result = cs.collect_quarantine(w.motor, w.dest)
    cause = result["cause"]
    if result["status"] == "no_module":
        cause = cause.split(" (")[0]
    return result["status"], cause


READERS = _readers()
IDS = [r.name.split(".")[0] for r in READERS]


def _put(world: _World, reader: _Reader, form: str) -> Path:
    link = reader.link_in(world) / LINK_REL
    _write_link(link, form, world.payload())
    return link


@pytest.mark.parametrize("reader", READERS, ids=IDS)
def test_bom_link_resolves_like_the_plain_link(world, mc, reader):
    """DoD 3: the same link with a BOM gives the same result as without it."""
    _put(world, reader, "plain")
    plain = reader.call(world, mc)
    assert plain == reader.healthy(
        world
    )  # control: the plain link is the healthy value
    _put(world, reader, "bom")
    assert reader.call(world, mc) == plain
    _put(world, reader, "empty")
    assert reader.degraded(
        reader.call(world, mc), world
    )  # control: it does see the link


@pytest.mark.parametrize("reader", READERS, ids=IDS)
@pytest.mark.parametrize("form", [*ABSENT_FORMS, "no-dest"])
def test_absent_or_valueless_link_keeps_each_readers_value(world, mc, reader, form):
    _put(world, reader, form)
    assert reader.degraded(reader.call(world, mc), world)


@pytest.mark.parametrize("reader", READERS, ids=IDS)
@pytest.mark.parametrize("form", UNREADABLE_FORMS)
def test_unreadable_link_keeps_each_readers_fallback(world, mc, reader, form):
    """Includes O1/O2/O3/O6: forms that raised before degrade, never raise."""
    _put(world, reader, form)
    result = reader.call(world, mc)  # must not raise
    assert reader.degraded(result, world), result
    assert result != reader.healthy(world)


@pytest.mark.parametrize("which", ["hook", "checkpoint"])
def test_a_destination_root_with_a_nul_byte_falls_back(world, mc, which):
    """O6: ``Path('a<NUL>b').resolve()`` raises ValueError; both resolvers fall back."""
    if which == "hook":
        _write_link(world.repo / LINK_REL, "nul-dest", world.payload())
        assert eh._resolve_destino(world.repo) is None
    else:
        _write_link(world.motor / LINK_REL, "nul-dest", world.payload())
        assert mc.resolve_destino_root(world.motor, None) == world.motor


_NUL = "a" + chr(0) + "b"
_SPACES = "   "


def _value_call(which: str, w: _World, mc):
    """Run one reader on a link whose motor_root and destination_root hold the value."""
    if which == "delivery":
        return dh._read_link_field(w.dest, "motor_root")
    if which == "export":
        return ex._linked_motor_root(w.dest)
    if which == "hook":
        return eh._resolve_destino(w.repo)
    if which == "checkpoint":
        return mc.resolve_destino_root(w.motor, None)
    return _quarantine(w)


_MOTOR = "MOTOR"  # sentinel: the reader falls back to the motor dir
_NO_LINK = ("no_link", "cuarentena: enlace motor-destino no disponible")
_AT_CWD = ("no_module", "cuarentena: modulo no disponible")
VALUE_TABLE = [
    # (reader, value, expected). The REAL behaviour of each reader, one row per value:
    # not a string / empty / whitespace-only / NUL byte.
    ("delivery", 5, None),
    ("delivery", "", None),
    ("delivery", _SPACES, _SPACES),  # returned as is (unchanged, not rejected)
    ("delivery", _NUL, _NUL),  # returned as is (unchanged, not rejected)
    ("export", 5, None),
    ("export", "", None),
    ("export", _SPACES, Path(_SPACES)),  # unresolved Path (unchanged, not rejected)
    ("export", _NUL, Path(_NUL)),  # unresolved Path (unchanged, not rejected)
    ("hook", 5, None),
    ("hook", "", None),
    ("hook", _SPACES, None),  # O7: used to resolve to the cwd; now rejected
    ("hook", _NUL, None),
    ("checkpoint", 5, _MOTOR),
    ("checkpoint", "", _MOTOR),
    ("checkpoint", _SPACES, Path(_SPACES).resolve()),  # unchanged (resolved as before)
    ("checkpoint", _NUL, _MOTOR),
    ("template", 5, _NO_LINK),
    ("template", "", _NO_LINK),
    pytest.param(
        "template",
        _SPACES,
        _AT_CWD,
        marks=pytest.mark.skipif(
            os.name != "nt",
            reason="Windows elimina espacios finales de componentes de ruta; POSIX no",
        ),
    ),  # unchanged: resolves to the cwd, then no module
    ("template", _NUL, _NO_LINK),
]


@pytest.mark.parametrize(
    ("which", "value", "expected"),
    VALUE_TABLE,
    ids=[
        f"{w}-{type(v).__name__}-{len(str(v))}"
        for row in VALUE_TABLE
        for w, v, _ in [row.values if hasattr(row, "values") else row]
    ],
)
def test_value_table_per_reader(world, mc, which, value, expected):
    """Pins what each reader REALLY does with a non-string, empty, blank or NUL value.

    The hook, motor_checkpoint and the collect template reject a NUL byte (O6) and the
    hook also a whitespace-only value (O7). ``delivery_hygiene_check`` and
    ``export_review_packet`` do NOT: they never resolved the value and still do not.
    """
    payload = {"motor_root": value, "destination_root": value}
    where = {"hook": world.repo, "checkpoint": world.motor}.get(which, world.dest)
    _write_link(where / LINK_REL, "plain", payload)
    result = _value_call(which, world, mc)
    if which == "template":
        status, cause = result
        assert (status, cause.split(" (")[0]) == expected
    else:
        assert result == (world.motor if expected == _MOTOR else expected)


@pytest.mark.skipif(
    os.name != "nt", reason="Windows elimina espacios finales de componentes de ruta"
)
def test_hook_rejects_a_whitespace_only_destination_root(world):
    """O7: whitespace-only is truthy, and Path of blanks resolves to the process cwd."""
    _write_link(world.repo / LINK_REL, "plain", {"destination_root": _SPACES})
    assert Path(_SPACES).resolve() == Path.cwd().resolve()  # the widening this prevents
    assert eh._resolve_destino(world.repo) is None
    assert eh._allowed_roots(world.repo) == [world.repo]


def test_a_project_root_argument_still_wins_over_the_link(world, mc):
    _write_link(world.motor / LINK_REL, "plain", world.payload())
    assert mc.resolve_destino_root(world.motor, world.repo) == world.repo.resolve()


# --- loader B in delivery_hygiene_check and export_review_packet ---------------------

LOADER_B = [
    ("scripts/delivery_hygiene_check.py", dh),
    ("scripts/export_review_packet.py", ex),
]
LOADER_B_IDS = ["delivery_hygiene_check", "export_review_packet"]


def test_the_private_loader_these_modules_consume_keeps_its_contract(tmp_path):
    """Pins ``prefix_resolver._read_link`` and the reasons the readers rely on."""
    assert callable(pr._read_link)
    link = tmp_path / "link.json"
    assert pr._read_link(link) == (None, "missing")
    link.write_bytes(BOM + b'{"a": 1}')
    assert pr._read_link(link) == ({"a": 1}, None)


@pytest.mark.parametrize("mod", [m for _, m in LOADER_B], ids=LOADER_B_IDS)
def test_both_modules_use_the_prefix_resolver_loader(mod):
    assert mod._read_link is pr._read_link


class _ExplodingResolver(types.ModuleType):
    """A ``prefix_resolver`` whose ``_read_link`` raises on access (any exception)."""

    def __getattr__(self, name: str):
        if name == "_read_link":
            raise RuntimeError("loader exploded")
        raise AttributeError(name)


class _InitFailingResolver(types.ModuleType):
    """A ``prefix_resolver`` whose initialisation failed: every name raises."""

    def __getattr__(self, name: str):
        raise RuntimeError("prefix_resolver failed to initialise")


def _install(monkeypatch, fake: types.ModuleType) -> None:
    monkeypatch.setitem(sys.modules, "scripts.prefix_resolver", fake)
    monkeypatch.setitem(sys.modules, "prefix_resolver", fake)


def _load_fresh(rel: str):
    name = "_b2_fresh_" + Path(rel).stem
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


@pytest.mark.parametrize("kind", ["raises", "renamed", "init-fails"])
@pytest.mark.parametrize("rel", [r for r, _ in LOADER_B], ids=LOADER_B_IDS)
def test_a_failed_initialisation_or_missing_loader_makes_the_link_unreadable(
    world, monkeypatch, rel, kind
):
    """No earlier import of prefix_resolver here, so even an init failure is covered."""
    fake = {
        "raises": _ExplodingResolver("prefix_resolver"),
        "renamed": types.ModuleType("prefix_resolver"),
        "init-fails": _InitFailingResolver("prefix_resolver"),
    }[kind]
    _install(monkeypatch, fake)
    fresh = _load_fresh(rel)  # must not raise
    _write_link(world.dest / LINK_REL, "plain", world.payload())  # a healthy link
    data, reason = fresh._read_link(world.dest / LINK_REL)
    assert data is None and reason.startswith("import: ")
    assert fresh._read_link is not pr._read_link
    if rel.endswith("delivery_hygiene_check.py"):
        assert fresh._read_link_field(world.dest, "motor_root") is None
    else:
        assert fresh._linked_motor_root(world.dest) is None


# --- local readers: dict/None result equivalence with read_motor_link, 14 forms -------

EQUIV_FORMS = [*ALL_FORMS, "nul-dest"]


def test_the_header_count_of_equivalence_forms_is_real():
    assert len(EQUIV_FORMS) == len(set(EQUIV_FORMS)) == 14


def _helper_dict(link: Path) -> dict | None:
    result = read_motor_link(link)
    return result.data if result.state == LINK_OK else None


def _template_reader() -> Callable[[Path], dict | None]:
    src = cs._QUARANTINE_SCRIPT_TEMPLATE
    start = src.index("def _read_link(path):")
    namespace: dict = {"json": json}
    exec(src[start : src.index("\n\n\n", start)], namespace)  # noqa: S102
    return namespace["_read_link"]


def _local_readers(mc) -> dict[str, Callable[[Path], dict | None]]:
    return {
        "hook": eh._read_link_dict,
        "template": _template_reader(),
        "checkpoint": lambda p: mc._read_link(p)[0],
    }


@pytest.mark.parametrize("form", EQUIV_FORMS)
def test_every_local_reader_matches_read_motor_link(world, mc, form):
    link = world.dest / LINK_REL
    _write_link(link, form, world.payload())
    expected = _helper_dict(link)
    for name, reader in _local_readers(mc).items():
        assert reader(link) == expected, name


def test_the_equivalence_test_can_see_a_strict_reader(tmp_path):
    """Control negative: a strict utf-8 reader DIFFERS from the helper on the BOM form."""
    link = tmp_path / "link.json"
    link.write_bytes(BOM + json.dumps({"a": 1}).encode())
    assert _helper_dict(link) == {"a": 1}
    with pytest.raises(ValueError):
        json.loads(link.read_text(encoding="utf-8"))


def test_motor_checkpoint_loader_reads_the_helper_of_its_own_motor(mc):
    assert mc.MOTOR_LINK_MODULE_PATH == REPO / "runtime" / "motor_link.py"


@pytest.mark.parametrize("form", ["plain", "bom", "empty", "list", "non-utf8", "deep"])
def test_motor_checkpoint_loader_matches_the_prefix_resolver_loader(world, mc, form):
    link = world.dest / LINK_REL
    _write_link(link, form, world.payload())
    assert mc._read_link(link) == pr._read_link(link)


def test_motor_checkpoint_falls_back_when_the_helper_cannot_load(
    world, mc, monkeypatch
):
    """Fail-closed: no helper -> unreadable -> the motor itself, never a traceback."""
    _write_link(world.motor / LINK_REL, "plain", world.payload())
    monkeypatch.setattr(mc, "_motor_link_module", None)
    monkeypatch.setattr(mc, "MOTOR_LINK_MODULE_PATH", world.motor / "nope" / "x.py")
    data, reason = mc._read_link(world.motor / LINK_REL)
    assert data is None and reason.startswith("import:")
    assert mc.resolve_destino_root(world.motor, None) == world.motor


# --- the hook, end to end -------------------------------------------------------------


def _run_hook(world: _World, target: Path) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "AGENT_PROJECT_ROOT"}
    payload = json.dumps({"tool_input": {"file_path": str(target)}})
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / "encoding_post_write_hook.py")],
        input=payload,
        cwd=world.repo,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


@pytest.mark.parametrize("form", ["plain", "bom"])
def test_hook_checks_a_destino_file_through_a_readable_link(world, form):
    target = world.dest / "note.md"
    target.write_bytes(BOM + b"hello\n")  # a BOM file: the hook must flag it
    _write_link(world.repo / LINK_REL, form, world.payload())
    proc = _run_hook(world, target)
    assert proc.returncode == 1, proc.stderr
    assert "ERROR bom" in proc.stderr


@pytest.mark.parametrize("form", [*UNREADABLE_FORMS, "absent"])
def test_hook_with_an_unreadable_link_does_not_widen_the_roots_and_does_not_crash(
    world, form
):
    """Fail-closed: the destino file is skipped (WARN, rc 0), no traceback."""
    target = world.dest / "note.md"
    target.write_bytes(BOM + b"hello\n")
    _write_link(world.repo / LINK_REL, form, world.payload())
    proc = _run_hook(world, target)
    assert proc.returncode == 0, proc.stderr
    assert "encoding_guard_skipped_outside_allowed_roots" in proc.stderr
    assert "Traceback" not in proc.stderr
    assert "ERROR bom" not in proc.stderr


# --- the template, end to end -----------------------------------------------------------


def test_template_has_no_strict_utf8_read_of_the_link():
    """The link block of the template is tolerant (the other reads are other files)."""
    src = cs._QUARANTINE_SCRIPT_TEMPLATE
    start = src.index("def _read_link(path):")
    block = src[start : src.index('_emit({"status": "no_link"', start)]
    assert re.search(r"""encoding\s*=\s*["']utf-8["']""", block) is None
    assert "utf-8-sig" in block
    # Control: the pattern does see a strict read elsewhere in the same template.
    assert re.search(r"""encoding\s*=\s*["']utf-8["']""", src) is not None


# --- census: DoD (2) "zero strict reads of the LINK in scripts/" -----------------------

LINK_NAMES = frozenset({"LINK_REL", "_LINK_RE", "_MOTOR_LINK_REL"})
LINK_FILE = "motor_destination_link"
# Strict utf-8 reads inside a scope that mentions the link but do NOT read it. The
# exemption is PER READ, never per function: ``scope key -> {receiver text: reason}``. A
# hit is exempt only when its receiver is listed AND that receiver is a local name that is
# never assigned from the link (see ``_receiver_is_clean``); any other strict read in the
# same function (for example of the link) is still a hit.
NOT_THE_LINK = {
    "scripts/census_destination_contracts.py::census_destinations": {
        "contracts_path": (
            "contracts_path = child / _CONTRACTS_RELPATH: reads each destino "
            "ticket_contracts.md; the link is only tested for existence with is_file()"
        ),
    },
    "scripts/install_agent_system.py::ensure_destination_projections_ignored": {
        "gitignore": (
            'gitignore = project_root / ".gitignore": reads and appends to the destino '
            ".gitignore (2 read_text + 2 open('a')); the function names the link path "
            "only to add it to the ignore list (false positive of the heuristic)"
        ),
    },
}
# Denominator of the census: 212 scripts/*.py + .agent/motor_checkpoint.py (prefix_resolver
# is one of the 212). UPDATE RULE: adding/removing a scripts/*.py changes SCRIPTS_COUNT in
# the SAME commit; the new number must be justified by the diff (a new script is either a
# clean file or one more exemption above), never edited just to silence the assertion.
# 211 -> 212: WOT-2026-160p added scripts/espera_checklist_mode.py (clean file: it never
# names motor_destination_link, so no new exemption); the bump was missed in that commit.
SCRIPTS_COUNT = 212
CENSUS_DENOMINATOR = SCRIPTS_COUNT + 1

# MEASURED on the 212 files (211 scripts/*.py + .agent/motor_checkpoint.py), 2026-11-02:
#   functions that name the link directly ............ 1 strict read (census_destinations)
#   + module constants that hold the link path ....... 5 (the 4 extra are the .gitignore
#     reads of ensure_destination_projections_ignored: none reads the link)
#   every function of a file that mentions the link .. 81 (80 extra, none reads the link)
# The census adopts the second level (resolving module constants such as LINK_PATH).
# LIMIT (declared): it is a HEURISTIC by scope: a function, or one module-level statement
# outside any function (compound statements are split into their header and each nested
# statement), that names the link directly or through a module-level constant. A path
# handed over as a parameter, an attribute, a dict value, a function result or a local
# alias bound in ANOTHER statement still evades it. It is evidence against regression,
# not a proof.


def _docstring_node(fn: ast.AST) -> ast.AST | None:
    first = fn.body[0] if fn.body else None
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
        return first.value
    return None


def _names_the_link(node: ast.AST, names: set[str]) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str) and LINK_FILE in node.value
    if isinstance(node, ast.Name):
        return node.id in names
    return isinstance(node, ast.Attribute) and node.attr in names


def _link_names(tree: ast.Module) -> set[str]:
    """Names that hold the link path: LINK_NAMES plus module constants built from it."""
    names = set(LINK_NAMES)
    changed = True
    while changed:
        changed = False
        for stmt in tree.body:
            if isinstance(stmt, ast.Assign):
                targets = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
            elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                targets = [stmt.target.id]
            else:
                continue
            value = getattr(stmt, "value", None)
            if value is None or not any(
                _names_the_link(n, names) for n in ast.walk(value)
            ):
                continue
            fresh = [t for t in targets if t not in names]
            names.update(fresh)
            changed = changed or bool(fresh)
    return names


def _mentions_link(fn: ast.AST, names: set[str]) -> bool:
    doc = _docstring_node(fn)
    return any(n is not doc and _names_the_link(n, names) for n in ast.walk(fn))


class _Hit(NamedTuple):
    scope_key: str  # ``label::function`` or ``label::<module>``
    receiver: str  # text of the path the strict read is made on
    clean: bool  # the receiver is a local name never assigned from the link
    lineno: int
    text: str


def _receiver_is_clean(nodes: list[ast.AST], receiver: str, names: set[str]) -> bool:
    """``receiver`` is a plain name, bound at least once, and never from the link.

    Conservative on purpose: any other binding form of the name (tuple target, ``for``,
    ``with ... as``) or an assignment whose value names the link makes it NOT clean.
    """
    if not receiver.isidentifier():
        return False

    def binds(target: ast.AST) -> bool:
        return any(
            isinstance(n, ast.Name) and n.id == receiver for n in ast.walk(target)
        )

    assigned = False
    for node in nodes:
        if isinstance(node, ast.Assign | ast.AnnAssign | ast.AugAssign | ast.NamedExpr):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if not any(binds(t) for t in targets):
                continue
            assigned = True
            value = node.value
            if value is None or any(_names_the_link(n, names) for n in ast.walk(value)):
                return False
        elif isinstance(node, ast.For | ast.AsyncFor) and binds(node.target):
            return False
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            if binds(node.optional_vars):
                return False
    return assigned


def _module_scopes(stmts: list[ast.stmt]):
    """``(statement, own expression nodes)`` for every statement outside any function.

    Compound statements are split: their header (test, iterable, ``with`` items, bases)
    is one scope and each nested statement is another. Function bodies are skipped: the
    function pass owns them. Class bodies are module-level code and are visited.
    """
    for stmt in stmts:
        if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        own = [
            c
            for c in ast.iter_child_nodes(stmt)
            if not isinstance(c, ast.stmt | ast.excepthandler | ast.match_case)
        ]
        yield stmt, own
        for field in ("body", "orelse", "finalbody"):
            yield from _module_scopes(getattr(stmt, field, []))
        for handler in getattr(stmt, "handlers", []):
            yield from _module_scopes(handler.body)
        for case in getattr(stmt, "cases", []):
            yield from _module_scopes(case.body)


def _scope_hits(
    label: str, scope: str, mentions: bool, nodes: list[ast.AST], binders, names
) -> list[_Hit]:
    """Strict reads among ``nodes`` when the scope names the link."""
    if not mentions:
        return []
    hits = []
    for node in nodes:
        read = _read_call(node) if isinstance(node, ast.Call) else None
        if read is None or read[1] not in STRICT_ENCODINGS:
            continue
        key = f"{label}::{scope}"
        clean = _receiver_is_clean(binders, read[0], names)
        text = f"{key}:{node.lineno}: {ast.unparse(node)}"
        hits.append(_Hit(key, read[0], clean, node.lineno, text))
    return hits


def _strict_read_hits(source: str, label: str) -> list[_Hit]:
    """Strict-utf-8 text reads in a scope that names the link: functions + module level."""
    tree = ast.parse(source)
    names = _link_names(tree)
    hits: list[_Hit] = []
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            nodes = list(ast.walk(fn))
            mentions = _mentions_link(fn, names)
            hits += _scope_hits(label, fn.name, mentions, nodes, nodes, names)
    scopes = list(_module_scopes(tree.body))
    binders = [s for s, _ in scopes] + [
        n for _, own in scopes for r in own for n in ast.walk(r)
    ]
    for _stmt, own in scopes:
        nodes = [n for root in own for n in ast.walk(root)]
        mentions = any(_names_the_link(n, names) for n in nodes)
        hits += _scope_hits(label, "<module>", mentions, nodes, binders, names)
    return hits


def _is_exempt(hit: _Hit, exempt: dict) -> bool:
    """A hit is exempt only for its listed receiver, and only while that receiver is clean."""
    return hit.clean and hit.receiver in exempt.get(hit.scope_key, {})


def _strict_reads_of_the_link(source: str, label: str, exempt: dict | None = None):
    """Texts of the strict reads that are not exempt (see ``NOT_THE_LINK``)."""
    return [
        h.text
        for h in _strict_read_hits(source, label)
        if not _is_exempt(h, exempt or {})
    ]


def _key(hit: str) -> str:
    """``label::function`` of a census hit (``label::function:line: code``)."""
    return hit.split(":")[0] + "::" + hit.split("::")[1].split(":")[0]


def _census_files() -> list[Path]:
    files = sorted((REPO / "scripts").glob("*.py"))
    return [*files, REPO / ".agent" / "motor_checkpoint.py"]


def test_census_finds_an_injected_strict_read_and_ignores_the_rest():
    """Positive control: a synthetic strict reader MUST be detected."""
    injected = (
        '"""module doc mentions motor_destination_link.json"""\n'
        'LINK_PATH = ROOT / ".agent" / "config" / "motor_destination_link.json"\n'
        "ALIAS = LINK_PATH\n"
        'OTHER = ROOT / "x.json"\n'
        "def strict(p):\n"
        '    return json.loads((p / "motor_destination_link.json").read_text(encoding="utf-8"))\n'
        "def implicit(p):\n"
        "    return (p / LINK_REL).read_text()\n"
        "def opened(p):\n"
        '    return open(p / "motor_destination_link.json", encoding="utf-8").read()\n'
        "def tolerant(p):\n"
        '    return (p / "motor_destination_link.json").read_text(encoding="utf-8-sig")\n'
        "def docstring_only(p):\n"
        '    """reads motor_destination_link.json somewhere else"""\n'
        '    return p.read_text(encoding="utf-8")\n'
        "def unrelated(p):\n"
        '    return p.read_text(encoding="utf-8")\n'
        "def via_constant():\n"
        '    return json.loads(LINK_PATH.read_text(encoding="utf-8"))\n'
        "def via_alias():\n"
        "    return ALIAS.read_text()\n"
        "def unrelated_constant():\n"
        '    return OTHER.read_text(encoding="utf-8")\n'
    )
    hits = _strict_reads_of_the_link(injected, "synthetic")
    assert [_key(h) for h in hits] == [
        "synthetic::strict",
        "synthetic::implicit",
        "synthetic::opened",
        "synthetic::via_constant",
        "synthetic::via_alias",
    ]


def test_no_strict_utf8_read_of_the_link_remains_in_scripts():
    """DoD (2) as a census: only the TWO named non-link READS are left (heuristic).

    The reads are ``contracts_path`` in ``census_destinations`` (ticket_contracts.md) and
    ``gitignore`` in ``ensure_destination_projections_ignored`` (.gitignore; a false
    positive of the heuristic). Neither reads the link. The exemption is per read: any
    other strict read in those two functions would still be a hit.
    """
    files = _census_files()
    assert len(files) == CENSUS_DENOMINATOR, (
        f"census denominator changed: {len(files)} != {CENSUS_DENOMINATOR}; "
        "see the update rule above SCRIPTS_COUNT"
    )
    assert REPO / "scripts" / "prefix_resolver.py" in files  # control: a known reader
    hits: list[_Hit] = []
    for path in files:
        label = path.relative_to(REPO).as_posix()
        hits += _strict_read_hits(path.read_text(encoding="utf-8"), label)
    unexplained = [h.text for h in hits if not _is_exempt(h, NOT_THE_LINK)]
    assert unexplained == []
    # Every named exception is real (still strict, still in the census): not a hole.
    expected = {(k, r) for k, readers in NOT_THE_LINK.items() for r in readers}
    assert {(h.scope_key, h.receiver) for h in hits} == expected
    # No module-level statement of the 212 files reads the link strictly (measured).
    assert [h.text for h in hits if h.scope_key.endswith("::<module>")] == []


def test_the_exemption_is_per_read_not_per_function():
    """Positive control: an exempt FUNCTION still fails on a strict read of the link."""
    source = (
        'LINK_PATH = ROOT / ".agent" / "config" / "motor_destination_link.json"\n'
        "def census_destinations(root):\n"
        '    contracts_path = root / "ticket_contracts.md"\n'
        '    text = contracts_path.read_text(encoding="utf-8", errors="replace")\n'
        '    return json.loads(LINK_PATH.read_text(encoding="utf-8")), text\n'
        "def second_receiver(root):\n"
        '    contracts_path = root / "ticket_contracts.md"\n'
        "    return json.loads((root / LINK_REL).read_text())\n"
        "def rebound(root):\n"
        '    contracts_path = root / "ticket_contracts.md"\n'
        "    contracts_path = root / LINK_REL\n"
        '    return contracts_path.read_text(encoding="utf-8")\n'
        "def parameter(contracts_path):\n"
        '    return contracts_path.read_text(encoding="utf-8") if LINK_REL else None\n'
    )
    exempt = {
        f"synthetic::{name}": {"contracts_path": "stands for ticket_contracts.md"}
        for name in ("census_destinations", "second_receiver", "rebound", "parameter")
    }
    left = [
        (h.scope_key, h.receiver)
        for h in _strict_read_hits(source, "synthetic")
        if not _is_exempt(h, exempt)
    ]
    assert left == [
        ("synthetic::census_destinations", "LINK_PATH"),  # same function, other read
        ("synthetic::second_receiver", "root / LINK_REL"),  # receiver not listed
        ("synthetic::rebound", "contracts_path"),  # listed name, rebound from the link
        ("synthetic::parameter", "contracts_path"),  # listed name, never assigned
    ]
    # And the legitimate read of that very function is exempt (the control is not vacuous).
    assert (
        _strict_reads_of_the_link(source, "synthetic", exempt)[0].count("LINK_PATH")
        == 1
    )
    assert len(_strict_read_hits(source, "synthetic")) == len(left) + 1


def test_census_covers_module_level_statements():
    """Positive control: strict reads of the link OUTSIDE any function are detected."""
    source = (
        'LINK_PATH = ROOT / ".agent" / "config" / "motor_destination_link.json"\n'  # 1
        'OTHER = ROOT / "x.json"\n'  # 2
        'STRICT = json.loads(LINK_PATH.read_text(encoding="utf-8"))\n'  # 3 hit
        'INLINE = open(ROOT / "motor_destination_link.json", encoding="utf-8").read()\n'  # 4 hit
        'TOLERANT = LINK_PATH.read_text(encoding="utf-8-sig")\n'  # 5
        'UNRELATED = OTHER.read_text(encoding="utf-8")\n'  # 6 same module, not the link
        "if True:\n"  # 7
        "    NESTED = LINK_PATH.read_text()\n"  # 8 hit
        "class K:\n"  # 9
        '    ATTR = LINK_PATH.read_text(encoding="utf-8")\n'  # 10 hit
        "    def method(self):\n"  # 11
        '        return OTHER.read_text(encoding="utf-8")\n'  # 12 function, unrelated
        'with open(LINK_PATH, encoding="utf-8") as fh:\n'  # 13 hit (header)
        "    pass\n"  # 14
        "try:\n"  # 15
        "    pass\n"  # 16
        "except OSError:\n"  # 17
        "    HANDLER = LINK_PATH.read_text()\n"  # 18 hit
    )
    hits = _strict_read_hits(source, "synthetic")
    assert [(h.scope_key, h.lineno) for h in hits] == [
        ("synthetic::<module>", n) for n in (3, 4, 8, 10, 13, 18)
    ]


def test_the_five_migrated_modules_are_clean_in_the_census():
    for rel in [
        "scripts/delivery_hygiene_check.py",
        "scripts/export_review_packet.py",
        "scripts/encoding_post_write_hook.py",
        "scripts/collect_session_state.py",
        ".agent/motor_checkpoint.py",
    ]:
        source = (REPO / rel).read_text(encoding="utf-8")
        assert _strict_reads_of_the_link(source, rel) == [], rel
