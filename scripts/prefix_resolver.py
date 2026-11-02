#!/usr/bin/env python3
"""
Prefix resolver: maps ticket prefixes to destination repos (WOT-2026-020s).

ARCHITECTURE: scans parent(motor_root) for motor_destination_link.json files,
each declaring a ticket_prefix + destination_root. Builds a reverse map
prefix -> destination_root. EVERY prefix goes through that map, WOT included
(WOT-2026-023i): WOT resolves to the workspace destination, which is where the
motor's own operational state lives (backlog.md, the bus). There is no special
case. Note that resolving is a different question from where a WOT ticket is
WORKED (the _dev worktree of the motor) and from where it is COMMITTED
(delivery_authority: repo_motor) -- those are separate axes, enforced by
scripts/check_worktree_topology.py.

No versioned registry, no auto-registration in install. The mapping is derived
purely from the links that already exist on disk. A local overrides file
(prefix_resolver.local.json, gitignored) can add destinations outside the
search tree; a .example template is versioned.

CLI:
    python scripts/prefix_resolver.py --resolve <PREFIX> [--motor-root <PATH>] [--project-root <PATH>]
    python scripts/prefix_resolver.py --verify [--motor-root <PATH>]
    python scripts/prefix_resolver.py --guard <TICKET_OR_PROJECT> [--motor-root <PATH>]

Exit codes:
    0 = success (resolved / verified / guard passed)
    1 = resolution failed (unknown prefix, mismatch) or verify found issues
    2 = error (malformed input, cannot discover motor_root)
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import NamedTuple


LINK_REL = Path(".agent") / "config" / "motor_destination_link.json"
LOCAL_OVERRIDES = Path(__file__).resolve().parent / "prefix_resolver.local.json"
WOT_PREFIX = "WOT"
# Canonical ticket ID: PREFIX-YYYY-NNNx (e.g. WOT-2026-020t, EXF-2026-010a)
TICKET_ID_RE = re.compile(r"^[A-Z]{2,5}-\d{4}-\d{3}[a-z]$")
# Malformed ticket ID: looks like one but doesn't match canonical pattern
MALFORMED_ID_RE = re.compile(r"^[A-Za-z]{2,5}-\d{1,4}-\d{1,4}[a-z]?$")
PREFIX_RE = re.compile(r"^[A-Z]{2,5}$")
# WOT-2026-152a: the helper lives in THIS motor (the script's own location), not in
# whatever ``--motor-root``/``motor_root`` a caller passes and not on ``sys.path``.
MOTOR_LINK_MODULE_PATH = (
    Path(__file__).resolve().parent.parent / "runtime" / "motor_link.py"
)
_motor_link_module: ModuleType | None = None


def _read_link(link_path: Path) -> tuple[dict | None, str | None]:
    """Read a motor_destination_link.json through ``runtime.motor_link.read_motor_link``.

    WOT-2026-152a: every reader of the link in this module goes through here, so a
    UTF-8 BOM (PowerShell 5.1) no longer makes a healthy link look unreadable.

    Before: ``link_path`` is the full path of the link (it may not exist). The
            helper is loaded by path from ``MOTOR_LINK_MODULE_PATH``.
    During: loads the helper once (cached on success), then one tolerant read.
            Writes nothing.
    After: ``(data, None)`` for a readable link object; ``(None, reason)`` otherwise,
           with ``reason`` ``"missing"`` or the helper's cause (``decode``, ``json``,
           ``not-a-dict``, ``io``). If the helper itself cannot be loaded the link
           counts as unreadable (``"import: ..."``): fail-closed. Never raises.
    """
    global _motor_link_module
    try:
        if _motor_link_module is None:
            spec = importlib.util.spec_from_file_location(
                "_motor_link_152a_prefix_resolver", MOTOR_LINK_MODULE_PATH
            )
            if spec is None or spec.loader is None:
                raise ImportError(f"cannot load {MOTOR_LINK_MODULE_PATH}")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            _motor_link_module = module
        result = _motor_link_module.read_motor_link(link_path)
        if result.state == _motor_link_module.LINK_OK:
            return result.data, None
        return None, result.reason or "missing"
    except Exception as exc:  # fail-closed: nothing may escape
        return None, f"import: {exc}"


def discover_motor_root(cwd: Path) -> Path | None:
    """Discover motor_root from cwd.

    Before: cwd may be the motor itself (has agent_controller.py) or a
            destination (has a link pointing to the motor).
    During: checks FIRST if cwd IS the motor (agent_controller.py present),
            then tries cwd's link (motor_root field), then AGENT_PROJECT_ROOT
            env. Motor-first avoids treating the motor as a destination when
            it has a stale/self-referential link.
    After: returns the motor_root Path, or None if undiscoverable. The links
           are read through ``_read_link`` (WOT-2026-152a): a UTF-8 BOM is
           tolerated and a non-UTF-8 / too-deep link counts as unreadable (None
           path onward) instead of raising.
    """
    if (cwd / ".agent" / "agent_controller.py").exists():
        return cwd
    link_path = cwd / LINK_REL
    if link_path.exists():
        data, _reason = _read_link(link_path)
        if data and data.get("motor_root"):
            return Path(data["motor_root"])
    env_root = os.environ.get("AGENT_PROJECT_ROOT")
    if env_root:
        p = Path(env_root)
        if (p / ".agent" / "agent_controller.py").exists():
            return p
        link_path = p / LINK_REL
        if link_path.exists():
            data, _reason = _read_link(link_path)
            if data and data.get("motor_root"):
                return Path(data["motor_root"])
    return None


def scan_links(search_root: Path) -> dict[str, list[Path]]:
    """Scan search_root one level deep for motor_destination_link.json.

    Before: search_root is parent(motor_root).
    During: iterates search_root/*/.agent/config/motor_destination_link.json,
            reads ticket_prefix + destination_root from each. Skips links
            with null/missing prefix or destination. Each link is read through
            ``_read_link`` (WOT-2026-152a): BOM tolerated; an unreadable link
            (incl. non-UTF-8 or too deeply nested, which used to raise) is skipped.
    After: returns dict prefix -> list of destination_roots (list for
          duplicate detection; singleton when unique).
    """
    mapping: dict[str, list[Path]] = {}
    if not search_root.exists():
        return mapping
    for child in sorted(search_root.iterdir()):
        if child.name.startswith("."):
            continue
        link_path = child / LINK_REL
        if not link_path.exists():
            continue
        data, _reason = _read_link(link_path)
        if data is None:
            continue
        prefix = data.get("ticket_prefix")
        dest = data.get("destination_root")
        if not prefix or not dest:
            continue
        mapping.setdefault(prefix, []).append(Path(dest))
    return mapping


def load_overrides(motor_root: Path | None = None) -> dict[str, Path]:
    """Load ``prefix_resolver.local.json`` overrides (gitignored, optional).

    Before: ``motor_root`` is the motor repository root, or ``None`` (legacy
        mode: the directory of THIS script, kept only so an external caller
        with no root keeps the old behaviour). The file is OPTIONAL.
    During: resolves ``<motor_root>/scripts/prefix_resolver.local.json`` and
        reads JSON ``{"overrides": {"PREFIX": "/path"}}``. Scoping the path to
        the motor is the fix for a measured regression: the previous absolute
        path (``Path(__file__).parent``) applied to EVERY ``--motor-root``,
        including fixture motors under ``tmp_path``, so 5 tests that assert
        ``resolve_prefix("WOT") is None`` / a clean ``--verify`` started failing
        the moment a real local override existed (control medido: con override
        5 failed / sin override 76 passed).
    After: returns dict prefix -> Path, or empty if the file is missing or
        malformed. Never raises.
    """
    path = (
        LOCAL_OVERRIDES
        if motor_root is None
        else Path(motor_root) / "scripts" / LOCAL_OVERRIDES.name
    )
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    overrides = data.get("overrides", {})
    if not isinstance(overrides, dict):
        return {}
    # WOT-2026-103f: a structurally malformed override value (non-dict
    # `overrides`, or a non-string value) is skipped, not raised -- the
    # docstring above promises "Never raises" and a syntactically valid but
    # ill-shaped JSON file must not crash every caller (resolve_prefix,
    # the --verify CLI) on a hand-edited gitignored file.
    return {k: Path(v) for k, v in overrides.items() if isinstance(v, str)}


class Resolution(NamedTuple):
    """Result of ``resolve_prefix_known`` (WOT-2026-126b): ``path`` is the
    destination_root or None, ``reason`` always names the cause."""

    path: Path | None
    reason: str


_GIT_OK, _GIT_NOT_A_REPO, _GIT_UNKNOWN = "ok", "not-a-repo", "unknown"

# Variables that make git answer for ANOTHER repository than the one at ``-C <path>``.
# An inherited one turns "which repo is this motor?" into "which repo does the
# environment say", so two unrelated paths read as the same repo (fail-open).
# GIT_CEILING_DIRECTORIES / GIT_DISCOVERY_ACROSS_FILESYSTEM only RESTRICT discovery
# (never substitute the repo) and are kept: tests and CI rely on them.
_GIT_REPO_SUBSTITUTING_ENV = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_NAMESPACE",
    "GIT_PREFIX",
)


def _git_env() -> dict[str, str]:
    """Environment for a repo-identity probe: inherited, minus the variables that
    substitute the repository, plus ``LC_ALL=C`` (stable git wording)."""
    env = {k: v for k, v in os.environ.items() if k not in _GIT_REPO_SUBSTITUTING_ENV}
    env["LC_ALL"] = "C"
    return env


def _git_probe(path: Path) -> tuple[tuple[Path, Path] | None, str]:
    """Ask git for ``(git_dir, git_common_dir)`` of ``path``, THREE-state.

    Before: ``path`` is a directory that may or may not be inside a git repo.
    During: ONE ``git rev-parse --path-format=absolute --git-dir
            --git-common-dir`` (check=False, LC_ALL=C so the "not a git
            repository" wording is stable; same flag rationale as
            ``_git_common_dir``). git_dir != git_common_dir identifies a LINKED
            worktree. A path that does not exist is "not a repo".
            The environment is sanitized (``_git_env``): an inherited GIT_DIR & co.
            must not make git answer for another repository.
    After: ``(dirs, "ok")``; ``(None, "not-a-repo")`` only when git itself said
           so with its discovery-failure wording (or the path does not exist); ``(None, "unknown")`` for EVERYTHING
           else (git missing from PATH, OS error, any other git failure such as
           a broken repo or dubious ownership, unexpected output). "unknown"
           means "cannot tell": callers must not read it as "not a repo".
           Never raises.
    """
    if not Path(path).exists():
        return None, _GIT_NOT_A_REPO
    git = _git_executable()
    if git is None:
        return None, _GIT_UNKNOWN
    try:
        result = subprocess.run(  # noqa: S603
            [
                git,
                "-C",
                str(path),
                "rev-parse",
                "--path-format=absolute",
                "--git-dir",
                "--git-common-dir",
            ],
            capture_output=True,
            text=True,
            check=False,
            env=_git_env(),
        )
        lines = result.stdout.strip().splitlines()
        if result.returncode == 0 and len(lines) == 2:
            return (Path(lines[0]).resolve(), Path(lines[1]).resolve()), _GIT_OK
    except (OSError, RuntimeError, ValueError):
        return None, _GIT_UNKNOWN
    # Only git's discovery failure counts ("... (or any of the parent
    # directories): .git"). A dangling worktree pointer says "not a git
    # repository: <gitdir>" WITHOUT that tail: it is a broken repo, not a non-repo.
    stderr = result.stderr.lower()
    if result.returncode != 0 and "not a git repository (or any of" in stderr:
        return None, _GIT_NOT_A_REPO
    return None, _GIT_UNKNOWN


def _git_dirs(path: Path) -> tuple[Path, Path] | None:
    """``(git_dir, git_common_dir)`` for ``path`` or None (any non-"ok" probe)."""
    return _git_probe(path)[0]


def _same_path(a: Path, b: Path) -> bool:
    """Path equality after ``resolve`` and ``normcase`` (Windows drive/case)."""
    try:
        return os.path.normcase(str(a.resolve())) == os.path.normcase(str(b.resolve()))
    except (OSError, RuntimeError, ValueError):
        return False


def _marker_present(path: Path) -> bool:
    """Is there ANYTHING at ``path`` (a ``.git`` marker), without following links?

    Before: ``path`` is ``<dir>/.git``. During: one ``os.lstat``. After: True if
    something is there (file, dir, dangling link/junction); False ONLY when it is
    effectively absent (FileNotFoundError / NotADirectoryError). Any other OSError
    (PermissionError, path too long, ...) is re-raised: "cannot tell" must not
    read as "absent" (``os.path.lexists`` would swallow it); the caller turns it
    into a fail-closed answer.
    """
    try:
        os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return False
    return True


def _parent_scan_is_meaningful(motor_root: Path) -> bool:
    """Is scanning ``parent(motor_root)`` for destination links meaningful?

    WOT-2026-126b. Declared interpretation of DoD (4) ("never return the
    canonical destination from a linked worktree"): it applies to linked
    worktrees whose parent is NOT the parent of the main checkout (T3 layouts,
    ``.claude/worktrees``), where the siblings are unrelated worktrees and
    fossil links, not destinations. The canonical ``_dev`` pair (linked worktree
    that is a SIBLING of the main checkout) keeps scanning exactly as before.

    Before: ``motor_root`` is the motor root (may not exist / be a git repo).
    During: one ``_git_probe``. git said "not a repo" (or the path does not
            exist) AND the motor root carries no ``.git`` marker => True (a real
            non-git motor scans as before; a ``.git`` marker that git cannot use,
            e.g. a pruned worktree, goes to ``_layout_without_git`` instead). Not linked
            => True. Linked: True only if the main checkout
            (``git_common_dir.parent``, a ``.git`` dir) shares its parent with
            ``motor_root``; a bare/odd common dir is fail-closed (False).
            If git CANNOT tell (missing, broken, odd output) the layout is read
            from the ``.git`` marker without running git
            (``_layout_without_git``); never "cannot tell" => True.
    After: bool; any OS-level error while deciding => False (fail-closed).
    """
    try:
        dirs, status = _git_probe(motor_root)
        if status == _GIT_NOT_A_REPO and not _marker_present(Path(motor_root) / ".git"):
            return True
        if dirs is None:
            return _layout_without_git(motor_root)
        git_dir, common_dir = dirs
        if git_dir == common_dir:
            return True
        if common_dir.name != ".git":
            return False
        return _same_path(motor_root.resolve().parent, common_dir.parent.parent)
    except (OSError, RuntimeError, ValueError):
        return False


def _layout_without_git(motor_root: Path) -> bool:
    """Scannability when git cannot answer, read from the ``.git`` marker only.

    Before: ``_git_probe`` returned "unknown" for ``motor_root``.
    During: filesystem reads, no git. ``.git`` DIRECTORY at the motor root =
            main checkout => True. ``.git`` FILE ``gitdir: <...>/worktrees/<n>``
            = linked worktree: True only if the main checkout it points at
            (``<common>/..`` with ``<common>`` named ``.git``) shares the motor's
            parent (the ``_dev`` pair); any other gitdir shape (submodule,
            unparsable, bare) => False. A marker that is neither (a dangling
            symlink/junction) => False. No marker at the root: a ``.git`` in an
            ancestor (up to ``GIT_CEILING_DIRECTORIES``, as git does) means the
            motor sits INSIDE some repo we cannot read => False; no ``.git``
            anywhere => a genuinely non-git motor => True.
    After: bool. May raise OSError/RuntimeError/ValueError (the caller,
           ``_parent_scan_is_meaningful``, turns that into False).
    """
    root = Path(motor_root).resolve()
    marker = root / ".git"
    if marker.is_dir():
        return True
    if marker.is_file():
        first = marker.read_text(encoding="utf-8", errors="replace").splitlines()[:1]
        if not first or not first[0].startswith("gitdir:"):
            return False
        gitdir = Path(first[0][len("gitdir:") :].strip())
        if not gitdir.is_absolute():
            gitdir = root / gitdir
        gitdir = gitdir.resolve()
        common = gitdir.parent.parent
        if gitdir.parent.name != "worktrees" or common.name != ".git":
            return False
        return _same_path(root.parent, common.parent.parent)
    if _marker_present(marker):
        return False  # a marker that is neither dir nor file (dangling link/junction)
    ceilings = {
        os.path.normcase(str(Path(c).resolve()))
        for c in os.environ.get("GIT_CEILING_DIRECTORIES", "").split(os.pathsep)
        if c
    }
    for ancestor in root.parents:
        if os.path.normcase(str(ancestor)) in ceilings:
            break
        if _marker_present(ancestor / ".git"):
            return False
    return True


def _match_known(
    key: str, known_destination: Path, by_name: bool
) -> tuple[Path | None, str]:
    """Check that ``known_destination`` IS the destination for ``key``.

    Before: ``key`` is a prefix (or a project name when ``by_name``);
            ``known_destination`` is the destination the caller already knows.
    During: reads ``known/LINK_REL`` through ``_read_link`` (BOM tolerated,
            never raises). Accepts ONLY if the link's prefix (or
            destination_id / directory name) matches AND its absolute
            ``destination_root`` resolves to ``known_destination`` itself
            (a link copied from another destination fails the second test).
    After: ``(known_destination, "known")`` or ``(None, reason)`` with reason in
           known_link_missing / known_link_unreadable / known_link_no_prefix /
           known_prefix_mismatch / known_root_mismatch.
    """
    data, why = _read_link(known_destination / LINK_REL)
    if data is None:
        return (
            None,
            "known_link_missing" if why == "missing" else "known_link_unreadable",
        )
    if by_name:
        name_ok = data.get("destination_id") == key or known_destination.name == key
        if not name_ok:
            return None, "known_prefix_mismatch"
    else:
        declared = data.get("ticket_prefix")
        if not isinstance(declared, str) or not declared.strip():
            return None, "known_link_no_prefix"
        if declared != key:
            return None, "known_prefix_mismatch"
    root = data.get("destination_root")
    if (
        not isinstance(root, str)
        or not root.strip()
        or not Path(root).is_absolute()
        or not _same_path(Path(root), known_destination)
    ):
        return None, "known_root_mismatch"
    return known_destination, "known"


def _scan_lookup(key: str, motor_root: Path, by_name: bool) -> Resolution:
    """The historical scan of ``parent(motor_root)`` (unchanged semantics).

    Prefix: unique link wins, duplicates are ``ambiguous``. Project name: first
    link whose destination_id / directory name matches (as before).
    """
    if not by_name:
        dests = scan_links(motor_root.parent).get(key)
        if not dests:
            return Resolution(None, "unknown")
        if len(dests) > 1:
            return Resolution(None, "ambiguous")
        return Resolution(dests[0], "map")
    search_root = motor_root.parent
    if not search_root.exists():
        return Resolution(None, "unknown")
    for child in sorted(search_root.iterdir()):
        link_path = child / LINK_REL
        if not link_path.exists():
            continue
        data, _reason = _read_link(link_path)
        if data is None:
            continue
        if data.get("destination_id") == key or child.name == key:
            dest = data.get("destination_root")
            if dest:
                return Resolution(Path(dest), "map")
    return Resolution(None, "unknown")


def _scan_or_unknown(key: str, motor_root: Path, by_name: bool) -> Resolution:
    """``_scan_lookup`` that turns an unlistable scan root (OSError, e.g.
    PermissionError) into ``Resolution(None, "unknown")`` instead of raising."""
    try:
        return _scan_lookup(key, motor_root, by_name)
    except OSError:
        return Resolution(None, "unknown")


_OVERRIDE_HINT_REASONS = ("known_prefix_mismatch", "linked_worktree_no_known")


def describe_reason(resolution: Resolution, prefix: str | None) -> str:
    """Text for the failure message of a ``Resolution`` (WOT-2026-126b).

    Before: ``resolution`` came from ``resolve_prefix_known``; ``prefix`` is the
        ticket prefix that was asked for, or None for a project-name lookup.
    During: pure string building.
    After: the reason; for a prefix that the known destination does not own
        (``known_prefix_mismatch``) or that a T3 layout cannot scan
        (``linked_worktree_no_known``) it also names the legitimate way to
        reach another prefix's destination: a local override (the only path
        that is declared by the user instead of guessed from siblings).
    """
    if prefix is not None and resolution.reason in _OVERRIDE_HINT_REASONS:
        return (
            f"{resolution.reason}; declara un override local para {prefix} "
            f"({LOCAL_OVERRIDES.name})"
        )
    return resolution.reason


# Known-link defects: the known destination itself is broken or lies, so they
# are reported ahead of ``ambiguous`` (they are the actionable cause).
_KNOWN_DEFECTS = (
    "known_root_mismatch",
    "known_link_unreadable",
    "known_link_no_prefix",
)


def resolve_prefix_known(
    prefix_or_project: str | None,
    motor_root: Path,
    known_destination: Path | None = None,
    *,
    by_name: bool = False,
) -> Resolution:
    """Resolve a prefix (or project name) to a destination_root, KNOWN FIRST.

    WOT-2026-126b. Before: ``prefix_or_project`` is a ticket prefix, or a project
        name when ``by_name``; ``motor_root`` is the motor root;
        ``known_destination`` is the destination the caller already knows
        (cwd / project_root) or None.
    During: (1) local overrides (prefixes only, as before); (2) the KNOWN
        destination: accepted only if its own link matches the prefix/name AND
        its ``destination_root`` resolves to ``known_destination`` (see
        ``_match_known``); (3) otherwise the historical scan of
        ``parent(motor_root)``, but ONLY where that scan is meaningful
        (``_parent_scan_is_meaningful``: never for a linked worktree outside
        the main checkout's parent, i.e. T3 layouts); there a failed known step
        stays failed (fail-closed) and with no known the cause is
        ``linked_worktree_no_known``. In meaningful layouts a failed known step
        falls through to the scan, exactly as before this ticket. If the layout
        cannot be established (git missing/broken AND the ``.git`` marker not
        readable) the scan is NOT run (fail-closed). Reads only.
    After: ``Resolution(path, reason)``; reason in known / map / override /
        known_link_missing / known_link_unreadable / known_link_no_prefix /
        known_prefix_mismatch / known_root_mismatch / linked_worktree_no_known /
        ambiguous / unknown. ``path`` is None for every failing reason.
        PRECEDENCE of the reason when nothing resolves (documented, tested):
        a known-link DEFECT (root_mismatch / unreadable / no_prefix) > ``ambiguous``
        > the soft known reasons (missing / prefix_mismatch) > ``unknown``.
        ``unknown`` also covers a scan root that cannot be listed (OSError,
        e.g. PermissionError): the scan is skipped, never raised. Does not
        raise on OS errors of the scan/layout/path comparison; the helpers it
        calls (``load_overrides``, ``_read_link``) already never raise.
    """
    if not prefix_or_project:
        return Resolution(None, "unknown")
    if not by_name:
        overrides = load_overrides(motor_root)
        if prefix_or_project in overrides:
            return Resolution(overrides[prefix_or_project], "override")
    known_reason: str | None = None
    if known_destination is not None:
        path, known_reason = _match_known(
            prefix_or_project, Path(known_destination), by_name
        )
        if path is not None:
            return Resolution(path, "known")
    if not _parent_scan_is_meaningful(motor_root):
        return Resolution(None, known_reason or "linked_worktree_no_known")
    scanned = _scan_or_unknown(prefix_or_project, motor_root, by_name)
    if scanned.path is not None:
        return scanned
    if known_reason in _KNOWN_DEFECTS:
        return Resolution(None, known_reason)
    if scanned.reason == "ambiguous":
        return scanned
    return Resolution(None, known_reason or scanned.reason)


def resolve_prefix(prefix: str | None, motor_root: Path) -> Path | None:
    """Resolve a ticket prefix to a destination_root (no known destination).

    Before: prefix is a short uppercase string (e.g. EXF, WOT); motor_root
            is the motor repository root.
    During: ``resolve_prefix_known`` with no known destination: overrides, then
            the scan of parent(motor_root) where meaningful (WOT-2026-126b:
            not for a T3-style linked worktree). WOT has NO special case
            (WOT-2026-023i). Returns None if prefix is None, not found, or
            ambiguous (duplicate).
    After: returns the destination_root Path, or None.
    """
    return resolve_prefix_known(prefix, motor_root).path


def resolve_by_project_name(name: str, motor_root: Path) -> Path | None:
    """Resolve by destination_id (project directory name).

    Before: name is a project name (not a ticket ID).
    During: ``resolve_prefix_known(..., by_name=True)`` with no known
            destination: scans links, matches destination_id (BOM tolerated,
            unreadable links skipped), where the scan is meaningful.
    After: returns the destination_root Path, or None.
    """
    return resolve_prefix_known(name, motor_root, by_name=True).path


def resolve_prefix_for_destination(destination_root: Path) -> str | None:
    """Read the ticket_prefix from a destination's own motor_destination_link.json.

    Before: destination_root is a repo_destino path.
    During: reads .agent/config/motor_destination_link.json from destination_root.
    After: returns the ticket_prefix string (e.g. "WOT", "CTL"), or None if
          the link is missing, unreadable (incl. non-UTF-8 or too deeply
          nested, which used to raise; WOT-2026-152a), malformed, or has no
          ticket_prefix field. A UTF-8 BOM is tolerated.
    """
    link_path = destination_root / LINK_REL
    if not link_path.exists():
        return None
    data, _reason = _read_link(link_path)
    if data is None:
        return None
    prefix = data.get("ticket_prefix")
    return str(prefix) if prefix else None


def extract_prefix(ticket_or_project: str) -> str | None:
    """Extract prefix from a ticket ID, or return None for a project name.

    Before: ticket_or_project may be a ticket ID (WOT-2026-020t) or a
            project name (Extractor_Facturas_PDF_Seguro).
    During: matches against TICKET_ID_RE. If it matches, returns the prefix
            (group 1). If it looks malformed (MALFORMED_ID_RE), raises
            ValueError. Otherwise returns None (project name).
    After: returns prefix string, None, or raises ValueError.
    """
    if TICKET_ID_RE.match(ticket_or_project):
        return ticket_or_project.split("-")[0]
    if MALFORMED_ID_RE.match(ticket_or_project):
        raise ValueError(f"Malformed ticket ID: {ticket_or_project}")
    return None


# WOT-2026-068k: la triada legacy que AGENTS.md declara `legacy-compat` y que
# el contrato frozen 061a (opcion A) exige incluir SIEMPRE ademas del prefijo
# declarado. Distinta de la pareja (WP, WT) que usa _prefix_alternation de
# check_contract_backlog_reconcile (WOT-2026-058p): ahi el prefijo declarado
# suele SER WOT, aqui se suma explicitamente para cubrir el caso RDS/CTL sobre
# un backlog con filas historicas WOT.
LEGACY_TICKET_PREFIXES = ("WOT", "WP", "WT")


def ticket_prefix_alternation(prefix: str | None) -> str | None:
    """Alternancia regex declarativa: prefijo del destino + la triada legacy.

    Before: ``prefix`` es el ``ticket_prefix`` leido del link (p.ej. "RDS"),
        o None/vacio cuando el link no lo declara.
    During: puro, sin I/O. Deduplica conservando el orden
        (declarado primero, luego WOT, WP, WT) y escapa cada alternativa con
        ``re.escape``.
    After: devuelve p.ej. ``"RDS|WOT|WP|WT"`` / ``"WOT|WP|WT"``; None cuando
        no hay prefijo declarado -- nunca inventa politica (NG-RAIZ: quien
        decidir el patron es el link, no esta funcion). Nunca lanza.
    """
    if not prefix or not str(prefix).strip():
        return None
    seen: list[str] = []
    for candidate in (str(prefix).strip(), *LEGACY_TICKET_PREFIXES):
        if candidate not in seen:
            seen.append(candidate)
    return "|".join(re.escape(c) for c in seen)


def find_destination_link(start: Path) -> Path | None:
    """Camina hacia arriba desde ``start`` buscando el link del destino.

    Before: ``start`` es un fichero o directorio DENTRO de un repo_destino
        (backlog.md, queued/, la raiz misma). El camino ascendente es finito
        y termina en la raiz del filesystem.
    During: para cada ancestro (inclusive), comprueba
        ``<ancestro>/.agent/config/motor_destination_link.json``.
    After: la ruta del link encontrado o None. Solo lectura; nunca lanza.
    """
    current = start if start.is_dir() else start.parent
    for candidate in (current, *current.parents):
        link = candidate / LINK_REL
        if link.exists():
            return link
    return None


def resolve_ticket_alternation(
    start: Path | None = None,
) -> tuple[str | None, str | None]:
    """Resuelve la alternancia de prefijos del destino que audita un gate.

    WOT-2026-068k: unica puerta para que los gates de backlog dejen de
    cablear su alternancia de prefijos como lista cerrada escrita a mano en
    cada modulo. Politica fijada por el contrato frozen
    061a (opcion A): el patron se CONSTRUYE desde el ``ticket_prefix``
    declarado en el ``motor_destination_link.json`` del destino, mas la
    triada legacy; si el link no lo declara, FALLA EXPLICITO.

    Before: ``start`` (opcional) es un camino dentro del destino cuyo link
        resolver (p.ej. el backlog, el queued/ o la raiz). Sin ``start`` se
        cae a ``AGENT_PROJECT_ROOT``.
    During: I/O de lectura exclusivamente: link por ascenso desde ``start``,
        o desde ``AGENT_PROJECT_ROOT`` si no hay ``start``; ausencia total de
        link y ausencia/vacio de ``ticket_prefix`` son el MISMO fallo
        fail-closed (motivo nombrado). El link se lee por ``_read_link``
        (WOT-2026-152a): un BOM UTF-8 se tolera; un link no UTF-8 o con
        anidamiento que desborda la recursion es "ilegible", ya no lanza
        (antes UnicodeDecodeError/RecursionError escapaban pese a este contrato).
    After: ``("RDS|WOT|WP|WT", None)`` cuando el link lo declara; si no,
        ``(None, "<motivo>")`` -- el llamador DEBE fallar explicito con ese
        motivo, nunca asumir un prefijo por defecto. Nunca lanza.
    """
    origins: list[tuple[str, Path]] = []
    if start is not None:
        origins.append(("start", Path(start)))
    env_root = os.environ.get("AGENT_PROJECT_ROOT", "").strip()
    if env_root:
        origins.append(("AGENT_PROJECT_ROOT", Path(env_root)))
    if not origins:
        return None, (
            "ticket_prefix no resoluble: sin camino de origen y sin "
            "AGENT_PROJECT_ROOT -- el motor no inventa politica de prefijos"
        )
    for _label, origin in origins:
        try:
            link = find_destination_link(origin)
        except OSError:
            continue
        if link is None:
            continue
        data, reason = _read_link(link)
        if data is None:
            kind = (
                "malformado" if (reason or "").startswith("not-a-dict") else "ilegible"
            )
            return None, (
                f"link {kind} en {link}: ticket_prefix no resoluble "
                "(fail-closed, el motor no inventa politica)"
            )
        alternation = ticket_prefix_alternation(data.get("ticket_prefix"))
        if alternation is None:
            return None, (
                f"el link {link} no declara ticket_prefix (ausente o vacio) -- "
                "fallar explicito, nunca asumir un prefijo por defecto"
            )
        return alternation, None
    return None, (
        "ticket_prefix no resoluble: ningun motor_destination_link.json "
        "declarado encontrado desde el origen dado (ascenso + AGENT_PROJECT_ROOT)"
    )


def _git_executable() -> str | None:
    """Resolve the absolute path to the git executable, or None if missing.

    Satisfies ruff S607 (partial executable path) without a noqa: the
    literal string "git" is never passed to subprocess directly, only the
    resolved absolute path from shutil.which.
    """
    return shutil.which("git")


def _git_common_dir(path: Path) -> Path | None:
    """Resolve the absolute git-common-dir for path, or None on failure.

    Before: path is a directory that may or may not be a git worktree.
    During: invokes `git -C <path> rev-parse --path-format=absolute
            --git-common-dir` with check=False (never check=True unguarded).
            The --path-format=absolute flag is mandatory: without it, git
            returns a relative path (e.g. ".git") for the primary checkout
            of a worktree set, and Path(...).resolve() on that relative
            output resolves against the calling PROCESS cwd, not against
            <path> -- producing a false mismatch (verified live, see
            work_plan.md "Verificacion en vivo"). Do NOT use
            --absolute-git-dir: that returns the LINKED worktree's own
            git-dir (.git/worktrees/<name>), which never matches between
            sibling worktrees of the same repo.
    After: returns the resolved absolute Path, or None if path is not a
          git repo (non-zero returncode) or git is not on PATH
          (FileNotFoundError). Callers must treat None as fail-closed.
    """
    git = _git_executable()
    if git is None:
        return None
    try:
        result = subprocess.run(  # noqa: S603
            [
                git,
                "-C",
                str(path),
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            ],
            capture_output=True,
            text=True,
            check=False,
            env=_git_env(),
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    raw = result.stdout.strip()
    if not raw:
        return None
    return Path(raw).resolve()


def guard(ticket_or_project: str, cwd: Path, motor_root: Path) -> int:
    """Guard: is cwd the right repo to work ticket_or_project from?

    Before: ticket_or_project is a ticket ID or project name; cwd is the
            current working directory; motor_root is the motor root.
    During: extracts the prefix (or uses the project name). WOT is decided
            FIRST and WITHOUT resolving the prefix to a destination: the
            question for WOT is "is cwd the same git repo as motor_root"
            (any worktree of it -- the _dev worktree and the primary
            detached checkout are the SAME motor), answered by comparing
            git-common-dir. That answer does not depend on where the WOT
            prefix RESOLVES to, so this branch must not require a
            resolution: demanding one would make a missing or duplicate WOT
            link (resolve_prefix -> None -> exit 2) block every WOT ticket
            from the correct worktree. It also does NOT enforce write
            discipline (which worktree/branch to use for WOT belongs to
            scripts/check_worktree_topology.py, exclusively). If
            git-common-dir cannot be determined for either side (not a git
            repo, or git missing from PATH), fails closed: mismatch
            (exit 1), never a crash, never exit 0. All other prefixes
            resolve to a destination_root and keep the literal-path
            comparison, unchanged.
    After: returns 0 if match, 1 if mismatch, 2 if resolution fails.
          Prints to stderr on failure (NO bus event: runs before
          --bootstrap-ticket).
    """
    try:
        prefix = extract_prefix(ticket_or_project)
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    if prefix == WOT_PREFIX:
        cwd_common = _git_common_dir(cwd)
        motor_common = _git_common_dir(motor_root)
        if cwd_common is None or motor_common is None:
            print(
                f"[ERROR] Cannot determine git-common-dir for cwd={cwd} or "
                f"motor_root={motor_root}: not a git repository, or git not "
                "found on PATH",
                file=sys.stderr,
            )
            return 1
        if cwd_common != motor_common:
            print(
                f"[ERROR] Repo mismatch: '{ticket_or_project}' is a motor "
                f"ticket, but cwd is {cwd}, which is not a worktree of the "
                f"motor at {motor_root} (different git repo)",
                file=sys.stderr,
            )
            return 1
        return 0
    if prefix is not None:
        resolution = resolve_prefix_known(prefix, motor_root, cwd)
    else:
        resolution = resolve_prefix_known(
            ticket_or_project, motor_root, cwd, by_name=True
        )
    resolved = resolution.path
    if resolved is None:
        print(
            f"[ERROR] Cannot resolve '{ticket_or_project}' to a destination "
            f"(reason: {describe_reason(resolution, prefix)})",
            file=sys.stderr,
        )
        return 2
    if cwd.resolve() != resolved.resolve():
        print(
            f"[ERROR] Prefix mismatch: '{ticket_or_project}' resolves to "
            f"{resolved}, but cwd is {cwd}",
            file=sys.stderr,
        )
        return 1
    return 0


def _get_motor_root(args: argparse.Namespace) -> Path | None:
    if args.motor_root:
        return Path(args.motor_root)
    return discover_motor_root(Path.cwd())


def cmd_resolve(args: argparse.Namespace) -> int:
    motor_root = _get_motor_root(args)
    if motor_root is None:
        print("[ERROR] Cannot discover motor_root (use --motor-root)", file=sys.stderr)
        return 2
    prefix = args.resolve
    if prefix is None:
        print("[ERROR] prefix is None (use --resolve <PREFIX>)", file=sys.stderr)
        return 2
    if not PREFIX_RE.match(prefix):
        print(f"[ERROR] Malformed prefix: {prefix}", file=sys.stderr)
        return 2
    project_root = getattr(args, "project_root", None)
    known = Path(project_root) if project_root else None
    resolution = resolve_prefix_known(prefix, motor_root, known)
    if resolution.path is None:
        print(
            f"[ERROR] Unknown or ambiguous prefix: {prefix} "
            f"(reason: {describe_reason(resolution, prefix)})",
            file=sys.stderr,
        )
        return 1
    print(str(resolution.path))
    return 0


def _collect_verify_issues(motor_root: Path) -> list[str]:
    """Collect verify issues: duplicates, unreachable, override collisions."""
    search_root = motor_root.parent
    mapping = scan_links(search_root)
    issues: list[str] = []
    for prefix, dests in sorted(mapping.items()):
        if len(dests) > 1:
            issues.append(
                f"DUPLICATE prefix '{prefix}' -> {len(dests)} destinations: "
                f"{[str(d) for d in dests]}"
            )
        issues.extend(
            f"UNREACHABLE prefix '{prefix}' -> {dest} (path does not exist)"
            for dest in dests
            if not dest.exists()
        )
    overrides = load_overrides(motor_root)
    for prefix, dest in sorted(overrides.items()):
        if prefix in mapping:
            issues.append(f"OVERRIDE collision: '{prefix}' in both overrides and scan")
        if not dest.exists():
            issues.append(
                f"OVERRIDE unreachable: '{prefix}' -> {dest} (path does not exist)"
            )
    issues.extend(_unreadable_link_issues(search_root))
    return issues


def _link_dirs(search_root: Path) -> list[Path]:
    """Sorted non-hidden children of ``search_root`` that carry a link file."""
    if not search_root.exists():
        return []
    return [
        child
        for child in sorted(search_root.iterdir())
        if not child.name.startswith(".") and (child / LINK_REL).exists()
    ]


def _unreadable_link_issues(search_root: Path) -> list[str]:
    """``UNREADABLE <link> <reason>`` for each link ``scan_links`` skips (126b).

    Before: ``search_root`` is parent(motor_root). During: re-reads each link
    through ``_read_link`` (read-only). After: one issue per unreadable link.
    """
    issues = []
    for child in _link_dirs(search_root):
        data, reason = _read_link(child / LINK_REL)
        if data is None:
            issues.append(f"UNREADABLE {child / LINK_REL} {reason}")
    return issues


def _motor_worktree_link_warnings(motor_root: Path) -> list[str]:
    """``MOTOR-WORKTREE LINK <path>`` WARN for links living in a worktree of the
    MOTOR's own repo (fossils such as pilot-104m / repo-audit-run; WOT-2026-126b).
    WARN only: not counted in the rc and not excluded from the mapping (a
    legitimate destination can also be a motor worktree).
    """
    motor_dirs = _git_dirs(motor_root)
    if motor_dirs is None:
        return []
    warnings = []
    for child in _link_dirs(motor_root.parent):
        child_dirs = _git_dirs(child)
        if child_dirs is not None and child_dirs[1] == motor_dirs[1]:
            warnings.append(f"MOTOR-WORKTREE LINK {child}")
    return warnings


def cmd_verify(args: argparse.Namespace) -> int:
    motor_root = _get_motor_root(args)
    if motor_root is None:
        print("[ERROR] Cannot discover motor_root (use --motor-root)", file=sys.stderr)
        return 2
    issues = _collect_verify_issues(motor_root)
    for warning in _motor_worktree_link_warnings(motor_root):
        print(f"[VERIFY] WARN {warning}", file=sys.stderr)
    if issues:
        for issue in issues:
            print(f"[VERIFY] {issue}", file=sys.stderr)
        print(f"[VERIFY] {len(issues)} issue(s) found", file=sys.stderr)
        return 1
    mapping = scan_links(motor_root.parent)
    print(f"[VERIFY] OK: {len(mapping)} prefixes mapped, 0 issues")
    return 0


def cmd_guard(args: argparse.Namespace) -> int:
    motor_root = _get_motor_root(args)
    if motor_root is None:
        print("[ERROR] Cannot discover motor_root (use --motor-root)", file=sys.stderr)
        return 2
    return guard(args.guard, Path.cwd(), motor_root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prefix resolver: maps ticket prefixes to destination repos."
    )
    parser.add_argument(
        "--motor-root",
        help="Path to the motor repo (auto-discovered if omitted).",
    )
    parser.add_argument(
        "--project-root",
        help="Destination already known (--resolve only); resolved FIRST "
        "(WOT-2026-126b) so it works from a motor in a T3 worktree.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--resolve",
        metavar="PREFIX",
        help="Resolve a prefix to its destination_root path.",
    )
    group.add_argument(
        "--verify",
        action="store_true",
        help="Re-scan and detect duplicates, drift, unreachable paths.",
    )
    group.add_argument(
        "--guard",
        metavar="TICKET_OR_PROJECT",
        help="Guard: resolve and compare with cwd (exit 1 on mismatch).",
    )
    args = parser.parse_args(argv)
    if args.resolve is not None:
        return cmd_resolve(args)
    if args.verify:
        return cmd_verify(args)
    if args.guard is not None:
        return cmd_guard(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
