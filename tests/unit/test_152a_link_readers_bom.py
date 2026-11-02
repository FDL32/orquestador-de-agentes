"""WOT-2026-152a: the 7 readers of motor_destination_link.json go through the helper.

The readers are ``prefix_resolver`` (discover_motor_root x2 branches, scan_links,
resolve_by_project_name, resolve_prefix_for_destination, resolve_ticket_alternation)
and ``destination_context.resolve_motor_link``.

Contract under test:
- a link with a UTF-8 BOM resolves exactly like one without it, in every reader;
- every other form of the link keeps the value each reader returned before;
- a non-UTF-8 link and a too-deeply nested one used to RAISE and now give each
  reader's "unreadable" value. Cambio observable autorizado por la coordinadora
  (GO 2, 11:36:08): lanzar -> valor de ilegible; motivo: docstrings 'Nunca lanza' +
  el helper no conserva el lanzar (un traceback no es un valor de retorno);
- if the helper cannot be loaded the link counts as unreadable (fail-closed), never
  an exception; both loader copies behave the same.

Nothing here depends on the autouse fixtures of tests/conftest.py: the prefix used
(ZZX) is not WOT and no backlog gate is touched.

Mutations to prove (each one on a COPY outside the worktree, per reader):
- revert one reader to ``json.loads(path.read_text(encoding="utf-8"))``: the BOM
  test of THAT reader fails;
- ``_read_link`` stops catching the loader failure: the load-failure tests fail;
- ``_read_link`` returns the helper's data without checking the state: the
  non-dict / unreadable tests fail.
"""

from __future__ import annotations

import ast
import json
import os
from collections.abc import Callable
from pathlib import Path

import pytest
from scripts import destination_context as dc, prefix_resolver as pr


BOM = b"\xef\xbb\xbf"
PREFIX = "ZZX"
ALTERNATION = f"{PREFIX}|WOT|WP|WT"


def _payload(case: Path) -> dict:
    return {
        "motor_root": str(case / "motor"),
        "ticket_prefix": PREFIX,
        "destination_id": "proj",
        "destination_root": str(case / "dest"),
    }


def _link_path(case: Path) -> Path:
    return case / "dest" / ".agent" / "config" / "motor_destination_link.json"


@pytest.fixture
def case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """<case>/motor (no runtime/), <case>/dest/.agent/config/, <case>/other."""
    monkeypatch.delenv("AGENT_PROJECT_ROOT", raising=False)
    (tmp_path / "motor").mkdir()
    (tmp_path / "other").mkdir()
    _link_path(tmp_path).parent.mkdir(parents=True)
    return tmp_path


# --- the 7 readers: (call, value when the link resolves, value when it does not)


def _a69(case: Path):
    return pr.discover_motor_root(case / "dest")


def _a82(case: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENT_PROJECT_ROOT", str(case / "dest"))
    return pr.discover_motor_root(case / "other")


def _b110(case: Path):
    return dict(pr.scan_links(case))


def _c205(case: Path):
    return pr.resolve_by_project_name("proj", case / "motor")


def _d229(case: Path):
    return pr.resolve_prefix_for_destination(case / "dest")


def _e345(case: Path):
    return pr.resolve_ticket_alternation(case / "dest" / "x.md")


def _f92(case: Path):
    return dc.resolve_motor_link(case / "dest")


def _resolved(case: Path) -> dict[str, object]:
    return {
        "A69 discover_motor_root(cwd link)": Path(case / "motor"),
        "A82 discover_motor_root(env link)": Path(case / "motor"),
        "B110 scan_links": {PREFIX: [Path(case / "dest")]},
        "C205 resolve_by_project_name": Path(case / "dest"),
        "D229 resolve_prefix_for_destination": PREFIX,
        "E345 resolve_ticket_alternation": (ALTERNATION, None),
        "F92 destination_context.resolve_motor_link": _payload(case),
    }


NAMES = list(_resolved(Path("x")))


def _call(name: str, case: Path, monkeypatch: pytest.MonkeyPatch):
    table: dict[str, Callable[[], object]] = {
        NAMES[0]: lambda: _a69(case),
        NAMES[1]: lambda: _a82(case, monkeypatch),
        NAMES[2]: lambda: _b110(case),
        NAMES[3]: lambda: _c205(case),
        NAMES[4]: lambda: _d229(case),
        NAMES[5]: lambda: _e345(case),
        NAMES[6]: lambda: _f92(case),
    }
    return table[name]()


def _e345_message(case: Path, kind: str) -> str:
    """The COMPLETE message resolve_ticket_alternation returns (path and suffix included)."""
    if kind == "missing":
        return (
            "ticket_prefix no resoluble: ningun motor_destination_link.json "
            "declarado encontrado desde el origen dado (ascenso + AGENT_PROJECT_ROOT)"
        )
    return (
        f"link {kind} en {_link_path(case)}: ticket_prefix no resoluble "
        "(fail-closed, el motor no inventa politica)"
    )


def _assert_unresolved(name: str, got: object, e345_kind: str, case: Path) -> None:
    """The value each reader returned (and keeps) when the link gives nothing."""
    if name == NAMES[2]:
        assert got == {}
    elif name == NAMES[5]:
        assert got == (None, _e345_message(case, e345_kind))
    else:
        assert got is None


# --- (3) BOM resolves like no BOM, per reader


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("with_bom", [False, True], ids=["sin-bom", "con-bom"])
def test_link_resolves_the_same_with_and_without_bom(
    name: str, with_bom: bool, case: Path, monkeypatch: pytest.MonkeyPatch
):
    raw = json.dumps(_payload(case)).encode("utf-8")
    if with_bom:
        raw = BOM + raw
        # Negative control: the fixture really is what the old strict reader choked on.
        with pytest.raises(json.JSONDecodeError):
            json.loads(raw.decode("utf-8"))
    _link_path(case).write_bytes(raw)
    assert _call(name, case, monkeypatch) == _resolved(case)[name]


# --- every other form keeps the value it had


UNRESOLVED_FORMS = [
    # (id, raw bytes or marker, what E345 says)
    ("vacio", b"", "ilegible"),
    ("truncado", b'{"motor_root": "x", "ticket_prefi', "ilegible"),
    ("no_dict", b'["motor_root"]', "malformado"),
    ("directorio", "DIR", "ilegible"),
    ("ausente", None, "missing"),
    ("symlink_roto", "SYMLINK", "missing"),
]


def _install(case: Path, raw) -> None:
    link = _link_path(case)
    if raw is None:
        return
    if raw == "DIR":
        link.mkdir()
    elif raw == "SYMLINK":
        try:
            os.symlink(case / "no_existe.json", link)
        except OSError as exc:  # no privilege to create symlinks
            pytest.skip(f"symlink not available: {exc}")
    else:
        link.write_bytes(raw)


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize(
    ("form", "raw", "e345_kind"), UNRESOLVED_FORMS, ids=[f[0] for f in UNRESOLVED_FORMS]
)
def test_unresolvable_forms_keep_each_readers_value(
    name: str,
    form: str,
    raw,
    e345_kind: str,
    case: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _install(case, raw)
    _assert_unresolved(name, _call(name, case, monkeypatch), e345_kind, case)


@pytest.mark.parametrize("name", NAMES)
def test_link_without_motor_root_keeps_each_readers_value(
    name: str, case: Path, monkeypatch: pytest.MonkeyPatch
):
    """A valid dict with no ``motor_root``: only the two motor-root readers refuse."""
    payload = _payload(case)
    del payload["motor_root"]
    _link_path(case).write_bytes(json.dumps(payload).encode("utf-8"))
    got = _call(name, case, monkeypatch)
    if name in NAMES[:2]:
        assert got is None
    else:
        expected = _resolved(case)[name]
        if name == NAMES[6]:
            expected = payload
        assert got == expected


# --- (H3) non-UTF-8 and RecursionError: used to raise, now "unreadable"


RAISING_FORMS = [
    ("no_utf8", b'{"ticket_prefix": "\xff\xfe"}', UnicodeDecodeError),
    ("recursion", b"[" * 5000 + b"]" * 5000, RecursionError),
]


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize(
    ("form", "raw", "old_error"), RAISING_FORMS, ids=[f[0] for f in RAISING_FORMS]
)
def test_non_utf8_and_deep_nesting_are_unreadable_not_an_exception(
    name: str,
    form: str,
    raw: bytes,
    old_error: type[Exception],
    case: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Cambio observable autorizado por la coordinadora (GO 2, 11:36:08): lanzar ->
    valor de ilegible; motivo: docstrings 'Nunca lanza' + el helper no conserva el lanzar.
    """
    # Negative control: the previous reading expression raised on this very input.
    with pytest.raises(old_error):
        json.loads(raw.decode("utf-8"))
    _link_path(case).write_bytes(raw)
    _assert_unresolved(name, _call(name, case, monkeypatch), "ilegible", case)


@pytest.mark.parametrize(
    "unreadable_raw",
    [b'{"ticket_prefix": "\xff\xfe"}', b"[" * 5000 + b"]" * 5000],
    ids=["no_utf8", "recursion"],
)
def test_discover_motor_root_treats_non_utf8_like_a_broken_json_link(
    unreadable_raw: bytes, case: Path, monkeypatch: pytest.MonkeyPatch
):
    """The one change stays bounded: for ``discover_motor_root`` a non-UTF-8 / too-deep
    link in cwd takes the SAME branch as a UTF-8 link with broken JSON (which already
    fell through to ``AGENT_PROJECT_ROOT`` before 152a): same value, no new path.
    """
    env_dest = case / "dest_env"
    link_env = env_dest / ".agent" / "config" / "motor_destination_link.json"
    link_env.parent.mkdir(parents=True)
    link_env.write_bytes(json.dumps({"motor_root": str(case / "motor_env")}).encode())
    cwd_link = _link_path(case)
    outcomes = {}
    for label, raw in (("json_roto", b"{ not json"), ("ilegible", unreadable_raw)):
        cwd_link.write_bytes(raw)
        monkeypatch.delenv("AGENT_PROJECT_ROOT", raising=False)
        without_env = pr.discover_motor_root(case / "dest")
        monkeypatch.setenv("AGENT_PROJECT_ROOT", str(env_dest))
        with_env = pr.discover_motor_root(case / "dest")
        outcomes[label] = (without_env, with_env)
    assert outcomes["json_roto"] == (None, Path(case / "motor_env"))
    assert outcomes["ilegible"] == outcomes["json_roto"]
    # Control: the pre-152a expression raised on the new input, not on broken JSON.
    with pytest.raises(json.JSONDecodeError):
        json.loads(b"{ not json".decode("utf-8"))
    with pytest.raises((UnicodeDecodeError, RecursionError)):
        json.loads(unreadable_raw.decode("utf-8"))


# --- the loader: fail-closed, and the helper comes from THIS motor


@pytest.fixture(params=[pr, dc], ids=["prefix_resolver", "destination_context"])
def loader_module(request):
    return request.param


def test_helper_path_is_this_scripts_motor(loader_module):
    """``__file__`` of the script IS the motor: not ``--motor-root``, not ``sys.path``."""
    script = Path(loader_module.__file__).resolve()
    assert (
        script.parent.parent / "runtime" / "motor_link.py"
    ) == loader_module.MOTOR_LINK_MODULE_PATH
    assert loader_module.MOTOR_LINK_MODULE_PATH.is_file()


def test_a_poisoned_runtime_in_the_motor_root_argument_is_ignored(
    case: Path, monkeypatch: pytest.MonkeyPatch
):
    """``resolve_by_project_name`` receives ``motor_root``; a fake helper there must not run."""
    poison = case / "motor" / "runtime"
    poison.mkdir()
    (poison / "motor_link.py").write_text(
        "raise RuntimeError('loaded from the motor_root argument')\n", encoding="utf-8"
    )
    _link_path(case).write_bytes(json.dumps(_payload(case)).encode("utf-8"))
    assert _c205(case) == Path(case / "dest")
    assert _b110(case) == {PREFIX: [Path(case / "dest")]}


def test_loader_failure_makes_the_link_unreadable_never_an_exception(
    loader_module, case: Path, monkeypatch: pytest.MonkeyPatch
):
    """Same link, same readers: with the real helper it resolves, without it it does not."""
    link = _link_path(case)
    link.write_bytes(json.dumps(_payload(case)).encode("utf-8"))
    monkeypatch.setattr(loader_module, "_motor_link_module", None)
    data, reason = loader_module._read_link(link)  # control: loader works
    assert data == _payload(case)
    assert reason is None

    monkeypatch.setattr(loader_module, "_motor_link_module", None)
    monkeypatch.setattr(
        loader_module,
        "MOTOR_LINK_MODULE_PATH",
        case / "no_hay_runtime" / "motor_link.py",
    )
    data, reason = loader_module._read_link(link)
    assert data is None
    assert reason is not None
    assert reason.startswith("import:")


@pytest.mark.parametrize("name", NAMES)
def test_every_reader_is_fail_closed_when_the_helper_cannot_load(
    name: str, case: Path, monkeypatch: pytest.MonkeyPatch
):
    _link_path(case).write_bytes(json.dumps(_payload(case)).encode("utf-8"))
    for module in (pr, dc):
        monkeypatch.setattr(module, "_motor_link_module", None)
        monkeypatch.setattr(
            module, "MOTOR_LINK_MODULE_PATH", case / "no_hay_runtime" / "motor_link.py"
        )
    _assert_unresolved(name, _call(name, case, monkeypatch), "ilegible", case)


def test_a_broken_helper_module_is_also_fail_closed(
    loader_module, case: Path, monkeypatch: pytest.MonkeyPatch
):
    """A helper that exists but explodes at import (not just a missing file)."""
    bad = case / "motor_link.py"
    bad.write_text("raise RuntimeError('boom')\n", encoding="utf-8")
    link = _link_path(case)
    link.write_bytes(json.dumps(_payload(case)).encode("utf-8"))
    monkeypatch.setattr(loader_module, "_motor_link_module", None)
    monkeypatch.setattr(loader_module, "MOTOR_LINK_MODULE_PATH", bad)
    data, reason = loader_module._read_link(link)
    assert data is None
    assert reason is not None
    assert reason.startswith("import:")


# --- the two loader copies must not diverge


EQUIVALENCE_FORMS = [
    ("ok", json.dumps({"motor_root": "M", "ticket_prefix": PREFIX}).encode("utf-8")),
    ("bom", BOM + json.dumps({"motor_root": "M"}).encode("utf-8")),
    ("vacio", b""),
    ("truncado", b'{"motor_root'),
    ("no_dict", b"null"),
    ("no_utf8", b'{"a": "\xff"}'),
    ("recursion", b"[" * 5000 + b"]" * 5000),
    ("ausente", None),
    ("directorio", "DIR"),
]


@pytest.mark.parametrize(
    ("form", "raw"), EQUIVALENCE_FORMS, ids=[f[0] for f in EQUIVALENCE_FORMS]
)
def test_both_loader_copies_behave_the_same_on_every_form(
    form: str, raw, case: Path, monkeypatch: pytest.MonkeyPatch
):
    _install(case, raw)
    link = _link_path(case)
    for module in (pr, dc):
        monkeypatch.setattr(module, "_motor_link_module", None)
    assert pr._read_link(link) == dc._read_link(link)


def test_both_loader_copies_behave_the_same_when_the_helper_cannot_load(
    case: Path, monkeypatch: pytest.MonkeyPatch
):
    link = _link_path(case)
    link.write_bytes(json.dumps(_payload(case)).encode("utf-8"))
    for module in (pr, dc):
        monkeypatch.setattr(module, "_motor_link_module", None)
        monkeypatch.setattr(
            module, "MOTOR_LINK_MODULE_PATH", case / "no_hay_runtime" / "motor_link.py"
        )
    got_pr = pr._read_link(link)
    got_dc = dc._read_link(link)
    assert got_pr[0] is None
    assert got_dc[0] is None
    assert (got_pr[1] or "").startswith("import:")
    assert (got_dc[1] or "").startswith("import:")


# --- census: DoD (2) "zero strict reads of the LINK" in the two scripts

LINK_READER_FUNCTIONS = frozenset(
    {
        "discover_motor_root",
        "scan_links",
        "resolve_by_project_name",
        "resolve_prefix_for_destination",
        "resolve_ticket_alternation",
        "find_destination_link",
        "resolve_motor_link",
        "_read_link",
    }
)
# Strict utf-8 reads that are NOT the link, excluded BY NAME and with the reason.
# Everything else in destination_context (wp_path, tm_path, sm_path, events_path,
# map_path, ...) is excluded by construction: it is neither inside a link-reader
# function nor does its receiver mention the link.
NOT_THE_LINK = {
    "load_overrides": "reads prefix_resolver.local.json (the overrides file), "
    "not motor_destination_link.json; outside the 152a DoD (the row said 8 sites, "
    "the 8th, :148, is this one)",
}
STRICT_ENCODINGS = frozenset({None, "utf-8", "utf8", "UTF-8"})


def _read_call(node: ast.Call) -> tuple[str, str | None] | None:
    """``(receiver text, encoding)`` when ``node`` reads text from a path, else None.

    Covers ``X.read_text(enc)``, ``X.open(..., encoding=enc)`` and ``open(X, ...,
    encoding=enc)``. ``encoding`` is None when absent (the locale default: not
    BOM-tolerant either).
    """
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr in ("read_text", "open"):
        target = ast.unparse(func.value)
        positional = 0 if func.attr == "read_text" else None
    elif isinstance(func, ast.Name) and func.id == "open" and node.args:
        target = ast.unparse(node.args[0])
        positional = None
    else:
        return None
    for kw in node.keywords:
        if kw.arg == "encoding" and isinstance(kw.value, ast.Constant):
            return target, kw.value.value
    if positional is not None and len(node.args) > positional:
        arg = node.args[positional]
        return target, arg.value if isinstance(arg, ast.Constant) else None
    return target, None


def _strict_link_reads(source: str, ignore_exclusions: bool = False) -> list[str]:
    """Calls that read text with a non-BOM-tolerant encoding on a link receiver.

    A call is a strict read when ``_read_call`` finds ``encoding`` absent or plain
    utf-8 (``utf-8-sig`` is the tolerant one). It is "on the link" when it sits inside
    one of ``LINK_READER_FUNCTIONS`` or its receiver text mentions ``link``/``LINK_REL``;
    functions in ``NOT_THE_LINK`` are skipped by name (``ignore_exclusions=True``
    turns that exemption off and treats them as link readers, to prove it is real).
    """
    found: list[str] = []

    def visit(node: ast.AST, func: str | None) -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            func = node.name
        read = _read_call(node) if isinstance(node, ast.Call) else None
        if read is not None and read[1] in STRICT_ENCODINGS:
            on_link = (
                func in LINK_READER_FUNCTIONS
                or "link" in read[0].lower()
                or "LINK_REL" in read[0]
                or (ignore_exclusions and func in NOT_THE_LINK)
            )
            if on_link and (ignore_exclusions or func not in NOT_THE_LINK):
                found.append(f"{func}:{node.lineno}: {ast.unparse(node)}")
        for child in ast.iter_child_nodes(node):
            visit(child, func)

    visit(ast.parse(source), None)
    return found


def test_census_finds_an_injected_strict_read_and_ignores_the_tolerant_one():
    """Positive control of the census itself (it must be able to see the defect)."""
    injected = (
        "def resolve_motor_link(p):\n"
        '    return json.loads(link_path.read_text(encoding="utf-8"))\n'
        "def scan(p):\n"
        '    return open(p / LINK_REL, encoding="utf-8").read()\n'
        "def other(p):\n"
        "    return link.read_text()\n"
        "def tolerant(p):\n"
        '    return link_path.read_text(encoding="utf-8-sig")\n'
        "def load_overrides(p):\n"
        '    return json.loads(path.read_text(encoding="utf-8"))\n'
        "def unrelated(wp_path):\n"
        '    return wp_path.read_text(encoding="utf-8")\n'
    )
    hits = _strict_link_reads(injected)
    assert len(hits) == 3
    assert hits[0].startswith("resolve_motor_link:2")
    assert hits[1].startswith("scan:4")
    assert hits[2].startswith("other:6")


@pytest.mark.parametrize(
    "module", [pr, dc], ids=["prefix_resolver", "destination_context"]
)
def test_no_strict_utf8_read_of_the_link_remains(module):
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert _strict_link_reads(source) == []


def test_the_excluded_overrides_read_exists_and_is_strict():
    """The exclusion is real, not a hole: ``load_overrides`` still reads strictly."""
    source = Path(pr.__file__).read_text(encoding="utf-8")
    assert _strict_link_reads(source) == []
    hits = _strict_link_reads(source, ignore_exclusions=True)
    assert len(hits) == 1
    assert hits[0].startswith("load_overrides:")
    assert "read_text" in hits[0]
