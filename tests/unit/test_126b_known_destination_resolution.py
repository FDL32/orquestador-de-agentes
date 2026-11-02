"""WOT-2026-126b: resolve the KNOWN destination before scanning, fail-closed.

A motor living in a T3 worktree (a linked worktree whose parent is NOT the parent
of the main checkout) used to scan its unrelated siblings: `--guard CTL-...`,
`check_worktree_topology` and `session_closeout` could not resolve a non-WOT
destination. These tests build that layout with REAL git (no mocking of git, no
fake `resolve_prefix_fn` for the closeout) and keep the canonical `_dev` pair
(linked worktree that is a SIBLING of the main checkout) scanning as before.

Layout (short names on purpose: Windows MAX_PATH, see WOT-2026-109d):

    c/motor, c/motor_dev     canonical pair (primary + linked sibling)
    t/m, t/f1, t/f2          T3-like: linked worktrees of c/motor, parent != c/;
                             f1/f2 carry fossil WOT links
    d/ctl                    primary of the CTL destination (own link)
    u/w                      linked worktree of d/ctl, its link points at t/m
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from scripts import prefix_resolver as pr, session_closeout as sc
from scripts.check_worktree_topology import check_topology
from scripts.flight import integrate_ticket as it


TICKET = "CTL-2026-001a"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _init(repo: Path) -> None:
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("r\n", encoding="utf-8")
    (repo / ".agent").mkdir()
    (repo / ".agent" / "agent_controller.py").write_text("#\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")


def _worktree(primary: Path, path: Path, branch: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _git(primary, "worktree", "add", "-b", branch, str(path))


def _link(root: Path, **fields: object) -> Path:
    link = root / ".agent" / "config" / "motor_destination_link.json"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.write_text(json.dumps(fields), encoding="utf-8")
    return link


@dataclass
class Layout:
    motor: Path
    motor_dev: Path
    t3_motor: Path
    t3_dir: Path
    ctl_primary: Path
    ctl_wt: Path


@pytest.fixture(autouse=True)
def _isolate_git_discovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Stop git's upward discovery walk at tmp_path (see test_check_worktree_topology)."""
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))


@pytest.fixture
def lay(tmp_path: Path) -> Layout:
    motor = tmp_path / "c" / "motor"
    _init(motor)
    motor_dev = tmp_path / "c" / "motor_dev"
    _worktree(motor, motor_dev, "dev")
    t3_motor = tmp_path / "t" / "m"
    _worktree(motor, t3_motor, "t3m")
    for name in ("f1", "f2"):
        fossil = tmp_path / "t" / name
        _worktree(motor, fossil, f"fos-{name}")
        _link(
            fossil,
            motor_root=str(fossil),
            destination_root=str(fossil),
            ticket_prefix="WOT",
        )
    ctl_primary = tmp_path / "d" / "ctl"
    _init(ctl_primary)
    _link(
        ctl_primary,
        motor_root=str(motor),
        destination_root=str(ctl_primary),
        ticket_prefix="CTL",
        destination_id="ctl",
    )
    ctl_wt = tmp_path / "u" / "w"
    _worktree(ctl_primary, ctl_wt, "ctlwt")
    _link(
        ctl_wt,
        motor_root=str(t3_motor),
        destination_root=str(ctl_wt),
        ticket_prefix="CTL",
        destination_id="w",
    )
    return Layout(motor, motor_dev, t3_motor, tmp_path / "t", ctl_primary, ctl_wt)


# --- the known step in a T3 layout ------------------------------------------


def test_t3_known_destination_resolves(lay: Layout) -> None:
    got = pr.resolve_prefix_known("CTL", lay.t3_motor, lay.ctl_wt)
    assert got == pr.Resolution(lay.ctl_wt, "known")
    # control: without the known destination the same motor cannot resolve it
    assert pr.resolve_prefix("CTL", lay.t3_motor) is None


def test_t3_without_known_names_the_cause_even_with_a_unique_sibling(
    lay: Layout,
) -> None:
    hub = lay.t3_dir / "hub"
    _worktree(lay.motor, hub, "hub")
    _link(hub, motor_root=str(hub), destination_root=str(hub), ticket_prefix="FDL")
    # a unique sibling link used to resolve; a linked worktree outside the main
    # checkout's parent must not be scanned any more (DoD 4, declared reading)
    assert pr.resolve_prefix_known("FDL", lay.t3_motor) == pr.Resolution(
        None, "linked_worktree_no_known"
    )
    assert pr.resolve_prefix("FDL", lay.t3_motor) is None


def test_t3_cross_prefix_known_is_strict(
    lay: Layout, capsys: pytest.CaptureFixture
) -> None:
    """[B2] (decided by CO-24): a ticket of ANOTHER prefix than the known
    destination's (FDL from a CTL workspace) in a T3 layout is NOT answered by
    a sibling link, however unique; the only legitimate path is a local
    override, which the error names. Without the override: None +
    known_prefix_mismatch. With it: resolves, reason 'override'."""
    hub = lay.t3_dir / "hub"
    _worktree(lay.motor, hub, "hub")
    _link(hub, motor_root=str(hub), destination_root=str(hub), ticket_prefix="FDL")
    assert pr.resolve_prefix_known("FDL", lay.t3_motor, lay.ctl_wt) == pr.Resolution(
        None, "known_prefix_mismatch"
    )
    assert pr.guard("FDL-2026-001a", lay.ctl_wt, lay.t3_motor) == 2
    err = capsys.readouterr().err
    assert "known_prefix_mismatch" in err
    assert "declara un override local para FDL" in err
    overrides = lay.t3_motor / "scripts" / pr.LOCAL_OVERRIDES.name
    overrides.parent.mkdir(exist_ok=True)
    overrides.write_text(json.dumps({"overrides": {"FDL": str(hub)}}), encoding="utf-8")
    assert pr.resolve_prefix_known("FDL", lay.t3_motor, lay.ctl_wt) == pr.Resolution(
        hub, "override"
    )


@pytest.mark.parametrize(
    "fields",
    [
        {"destination_root": "FOREIGN"},
        {"destination_root": None},
        {"destination_root": ""},
        {"destination_root": "u/w"},
    ],
    ids=["copied-foreign-root", "root-null", "root-empty", "root-relative"],
)
def test_t3_copied_link_still_blocks(lay: Layout, fields: dict) -> None:
    """A link copied from another destination (prefix ok, root not ours) blocks."""
    root = fields["destination_root"]
    if root == "FOREIGN":
        root = str(lay.ctl_primary)
    link = {
        "motor_root": str(lay.t3_motor),
        "ticket_prefix": "CTL",
        "destination_id": "w",
    }
    if root is not None or "destination_root" in fields:
        link["destination_root"] = root
    _link(lay.ctl_wt, **link)
    assert pr.resolve_prefix_known("CTL", lay.t3_motor, lay.ctl_wt) == pr.Resolution(
        None, "known_root_mismatch"
    )


@pytest.mark.parametrize(
    ("write", "reason"),
    [
        (lambda p: None, "known_link_missing"),
        (lambda p: p.write_text("", encoding="utf-8"), "known_link_unreadable"),
        (
            lambda p: p.write_text('{"ticket_prefix": "CT', encoding="utf-8"),
            "known_link_unreadable",
        ),
        (lambda p: p.write_text("[]", encoding="utf-8"), "known_link_unreadable"),
        (lambda p: p.write_bytes(b"\xff\xfe\x00bad"), "known_link_unreadable"),
        (
            lambda p: p.write_text(
                json.dumps({"destination_root": "x"}), encoding="utf-8"
            ),
            "known_link_no_prefix",
        ),
        (
            lambda p: p.write_text(
                json.dumps({"ticket_prefix": "  "}), encoding="utf-8"
            ),
            "known_link_no_prefix",
        ),
        (
            lambda p: p.write_text(
                json.dumps({"ticket_prefix": "EXF"}), encoding="utf-8"
            ),
            "known_prefix_mismatch",
        ),
    ],
    ids=[
        "absent",
        "empty",
        "truncated",
        "not-a-dict",
        "not-utf8",
        "no-prefix",
        "blank-prefix",
        "other-prefix",
    ],
)
def test_t3_known_link_forms_name_their_cause(lay: Layout, write, reason: str) -> None:
    link = lay.ctl_wt / pr.LINK_REL
    link.unlink()
    write(link)
    got = pr.resolve_prefix_known("CTL", lay.t3_motor, lay.ctl_wt)
    assert got == pr.Resolution(None, reason)


def test_known_link_with_bom_resolves(lay: Layout) -> None:
    link = lay.ctl_wt / pr.LINK_REL
    link.write_bytes(b"\xef\xbb\xbf" + link.read_bytes())
    assert pr.resolve_prefix_known("CTL", lay.t3_motor, lay.ctl_wt).reason == "known"


def test_known_destination_path_forms_compare_equal(
    lay: Layout, monkeypatch: pytest.MonkeyPatch
) -> None:
    forms = [lay.ctl_wt / ".." / lay.ctl_wt.name, Path(str(lay.ctl_wt) + os.sep)]
    if sys.platform == "win32":
        s = str(lay.ctl_wt)
        forms.append(Path(s[0].swapcase() + s[1:]))
    monkeypatch.chdir(lay.ctl_wt.parent)
    forms.append(Path(lay.ctl_wt.name))
    for form in forms:
        got = pr.resolve_prefix_known("CTL", lay.t3_motor, form)
        assert got.reason == "known", form


def test_known_destination_missing_dir(lay: Layout, tmp_path: Path) -> None:
    got = pr.resolve_prefix_known("CTL", lay.t3_motor, tmp_path / "nope")
    assert got == pr.Resolution(None, "known_link_missing")


# --- by project name ----------------------------------------------------------


def test_t3_known_by_project_name(lay: Layout) -> None:
    got = pr.resolve_prefix_known("w", lay.t3_motor, lay.ctl_wt, by_name=True)
    assert got == pr.Resolution(lay.ctl_wt, "known")
    assert pr.resolve_by_project_name("w", lay.t3_motor) is None
    other = pr.resolve_prefix_known("zzz", lay.t3_motor, lay.ctl_wt, by_name=True)
    assert other == pr.Resolution(None, "known_prefix_mismatch")


def test_t3_project_name_copied_link_blocks(lay: Layout) -> None:
    _link(
        lay.ctl_wt,
        motor_root=str(lay.t3_motor),
        destination_root=str(lay.ctl_primary),
        destination_id="w",
    )
    got = pr.resolve_prefix_known("w", lay.t3_motor, lay.ctl_wt, by_name=True)
    assert got == pr.Resolution(None, "known_root_mismatch")


# --- canonical layout unchanged ---------------------------------------------------


def test_dev_pair_keeps_scanning_as_before(lay: Layout, tmp_path: Path) -> None:
    """The linked `_dev` worktree is a SIBLING of the main checkout: scannable."""
    dest = tmp_path / "c" / "ctl_dest"
    _init(dest)
    _link(
        dest,
        motor_root=str(lay.motor_dev),
        destination_root=str(dest),
        ticket_prefix="CTL",
    )
    assert pr.resolve_prefix_known("CTL", lay.motor_dev) == pr.Resolution(dest, "map")
    assert pr.resolve_prefix("CTL", lay.motor) == dest
    assert pr.resolve_by_project_name("ctl_dest", lay.motor_dev) == dest


def test_non_git_motor_keeps_scanning(tmp_path: Path) -> None:
    motor = tmp_path / "plain" / "motor"
    motor.mkdir(parents=True)
    dest = tmp_path / "plain" / "dest"
    _link(dest, motor_root=str(motor), destination_root=str(dest), ticket_prefix="EXF")
    assert pr.resolve_prefix_known("EXF", motor) == pr.Resolution(dest, "map")


def test_canonical_known_of_other_destination_falls_through_to_scan(
    lay: Layout, tmp_path: Path
) -> None:
    dest = tmp_path / "c" / "ctl_dest"
    _init(dest)
    _link(
        dest,
        motor_root=str(lay.motor_dev),
        destination_root=str(dest),
        ticket_prefix="CTL",
    )
    other = tmp_path / "c" / "exf"
    _init(other)
    _link(
        other,
        motor_root=str(lay.motor_dev),
        destination_root=str(other),
        ticket_prefix="EXF",
    )
    got = pr.resolve_prefix_known("CTL", lay.motor_dev, other)
    assert got == pr.Resolution(dest, "map")


def test_canonical_ambiguous_without_known_but_known_wins(
    lay: Layout, tmp_path: Path
) -> None:
    a = tmp_path / "c" / "a"
    b = tmp_path / "c" / "b"
    for d in (a, b):
        _init(d)
        _link(
            d,
            motor_root=str(lay.motor_dev),
            destination_root=str(d),
            ticket_prefix="CTL",
        )
    assert pr.resolve_prefix_known("CTL", lay.motor_dev) == pr.Resolution(
        None, "ambiguous"
    )
    assert pr.resolve_prefix_known("CTL", lay.motor_dev, a) == pr.Resolution(a, "known")


def test_canonical_copied_link_does_not_resolve_to_the_copy(
    lay: Layout, tmp_path: Path
) -> None:
    dest = tmp_path / "c" / "real"
    _init(dest)
    _link(
        dest,
        motor_root=str(lay.motor_dev),
        destination_root=str(dest),
        ticket_prefix="CTL",
    )
    copy = tmp_path / "c" / "copy"
    _init(copy)
    _link(
        copy,
        motor_root=str(lay.motor_dev),
        destination_root=str(dest),
        ticket_prefix="CTL",
    )
    # two CTL links in the scanned parent: the copy's own defect names the cause
    got = pr.resolve_prefix_known("CTL", lay.motor_dev, copy)
    assert got == pr.Resolution(None, "known_root_mismatch")
    # L1 (declared): with a SINGLE visible link the canonical scan answers as before
    # (the copy's foreign root); the guard still blocks because cwd != that root
    solo = tmp_path / "c2" / "motor"
    _init(solo)
    lonely = tmp_path / "c2" / "copy"
    _init(lonely)
    _link(lonely, motor_root=str(solo), destination_root=str(dest), ticket_prefix="CTL")
    assert pr.resolve_prefix_known("CTL", solo, lonely) == pr.Resolution(dest, "map")
    assert pr.guard("CTL-2026-001a", lonely, solo) == 1


# --- wiring: guard, CLI, topology, closeout (no fakes), integrate_ticket ---------


def test_guard_in_t3_with_cwd_as_known(
    lay: Layout, capsys: pytest.CaptureFixture
) -> None:
    assert pr.guard(TICKET, lay.ctl_wt, lay.t3_motor) == 0
    assert pr.guard("w", lay.ctl_wt, lay.t3_motor) == 0


def test_guard_in_t3_copied_link_exits_2_naming_the_reason(
    lay: Layout, capsys: pytest.CaptureFixture
) -> None:
    _link(
        lay.ctl_wt,
        motor_root=str(lay.t3_motor),
        destination_root=str(lay.ctl_primary),
        ticket_prefix="CTL",
    )
    assert pr.guard(TICKET, lay.ctl_wt, lay.t3_motor) == 2
    assert "known_root_mismatch" in capsys.readouterr().err


def test_guard_wrong_cwd_in_t3_exits_2(
    lay: Layout, capsys: pytest.CaptureFixture
) -> None:
    assert pr.guard(TICKET, lay.t3_motor, lay.t3_motor) == 2
    assert "known_link_missing" in capsys.readouterr().err


def test_cmd_resolve_project_root_is_the_known_destination(
    lay: Layout, capsys: pytest.CaptureFixture
) -> None:
    argv = ["--resolve", "CTL", "--motor-root", str(lay.t3_motor)]
    assert pr.main([*argv, "--project-root", str(lay.ctl_wt)]) == 0
    assert capsys.readouterr().out.strip() == str(lay.ctl_wt)
    assert pr.main(argv) == 1
    assert "linked_worktree_no_known" in capsys.readouterr().err


def test_topology_in_t3_resolves_ticket_and_project_name(lay: Layout) -> None:
    code, msg = check_topology(TICKET, lay.ctl_wt, lay.t3_motor, lay.ctl_wt)
    assert (code, msg.startswith("topologia correcta")) == (0, True), msg
    code, msg = check_topology("w", lay.ctl_wt, lay.t3_motor, lay.ctl_wt)
    assert code == 0, msg


def test_topology_in_t3_copied_link_exits_2(lay: Layout) -> None:
    _link(
        lay.ctl_wt,
        motor_root=str(lay.t3_motor),
        destination_root=str(lay.ctl_primary),
        ticket_prefix="CTL",
        destination_id="w",
    )
    code, msg = check_topology(TICKET, lay.ctl_wt, lay.t3_motor, lay.ctl_wt)
    assert code == 2
    assert "known_root_mismatch" in msg
    code, msg = check_topology("w", lay.ctl_wt, lay.t3_motor, lay.ctl_wt)
    assert code == 2
    assert "known_root_mismatch" in msg


def _write_plan(root: Path) -> None:
    plan = root / ".agent" / "collaboration" / "work_plan.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(
        f"# Work plan\n\n- **ID:** {TICKET}\n- **Estado:** IN_PROGRESS\n"
        "- **delivery_authority:** repo_destino\n- **deliverable_type:** code\n",
        encoding="utf-8",
    )


def _closeout_result(project_root: Path):
    setup = sc._resolve_writer_setup(project_root, None)
    assert not isinstance(setup, sc.StepResult), setup
    return sc._process_ticket_targets(
        TICKET,
        project_root,
        setup.motor_root,
        setup.extract_prefix_fn,
        setup.resolve_prefix_fn,
        [],
    )


def test_closeout_real_path_in_t3_passes_without_fakes(lay: Layout) -> None:
    _write_plan(lay.ctl_wt)
    res = _closeout_result(lay.ctl_wt)
    assert (res.status, res.blocking) == ("PASS", False), res.detail


def test_closeout_real_path_in_t3_copied_link_is_blocking(lay: Layout) -> None:
    _write_plan(lay.ctl_wt)
    _link(
        lay.ctl_wt,
        motor_root=str(lay.t3_motor),
        destination_root=str(lay.ctl_primary),
        ticket_prefix="CTL",
    )
    res = _closeout_result(lay.ctl_wt)
    assert (res.status, res.blocking) == ("FAIL", True)
    assert "FAIL_TARGETS_MISSING" in res.detail


def test_known_prefix_adapter_keeps_the_optional_path_signature(lay: Layout) -> None:
    known, plain = pr.resolve_prefix_known, pr.resolve_prefix
    assert sc._known_prefix_adapter(None, plain, lay.ctl_wt) is None
    assert sc._known_prefix_adapter(known, None, lay.ctl_wt) is None
    adapter = sc._known_prefix_adapter(known, plain, lay.ctl_wt)
    assert adapter("CTL", lay.t3_motor) == lay.ctl_wt
    assert adapter("EXF", lay.t3_motor) is None
    assert adapter(None, lay.t3_motor) is None


def test_known_prefix_adapter_falls_back_to_the_patchable_resolve_prefix(
    lay: Layout, tmp_path: Path
) -> None:
    """The closeout's existing tests patch `prefix_resolver.resolve_prefix`; the
    adapter must keep honouring that seam when the known step does not match."""
    other = tmp_path / "elsewhere"
    adapter = sc._known_prefix_adapter(
        pr.resolve_prefix_known, lambda prefix, _motor: other, lay.ctl_wt
    )
    assert adapter("EXF", lay.t3_motor) == other
    assert adapter("CTL", lay.t3_motor) == lay.ctl_wt


def test_integrate_ticket_target_line_binds_the_known_adapter(
    lay: Layout, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict = {}

    def _capture(ticket, project_root, motor_root, extract, resolve, since):
        seen["resolve"] = resolve
        return sc._TicketTargetResult([], "PASS")

    monkeypatch.setattr(sc, "_process_ticket_targets", _capture)
    it._target_line(TICKET, lay.ctl_wt, lay.t3_motor, "1970-01-01")
    assert seen["resolve"]("CTL", lay.t3_motor) == lay.ctl_wt


# --- --verify ------------------------------------------------------------------------


def test_verify_reports_unreadable_links_and_motor_worktree_links(
    lay: Layout, capsys: pytest.CaptureFixture
) -> None:
    bad = lay.t3_dir / "bad"
    bad.mkdir()
    (bad / ".agent" / "config").mkdir(parents=True)
    broken = bad / ".agent" / "config" / "motor_destination_link.json"
    broken.write_text('{"ticket_prefix": ', encoding="utf-8")
    rc = pr.main(["--verify", "--motor-root", str(lay.t3_motor)])
    err = capsys.readouterr().err
    assert rc == 1
    assert f"UNREADABLE {broken} json" in err
    assert f"MOTOR-WORKTREE LINK {lay.t3_dir / 'f1'}" in err
    assert "DUPLICATE prefix 'WOT'" in err


def test_verify_motor_worktree_link_is_a_warn_not_an_issue(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    motor = tmp_path / "c" / "motor"
    _init(motor)
    m = tmp_path / "t" / "m"
    _worktree(motor, m, "t3m")
    fossil = tmp_path / "t" / "f"
    _worktree(motor, fossil, "fos")
    _link(
        fossil,
        motor_root=str(fossil),
        destination_root=str(fossil),
        ticket_prefix="WOT",
    )
    rc = pr.main(["--verify", "--motor-root", str(m)])
    cap = capsys.readouterr()
    assert rc == 0
    assert f"MOTOR-WORKTREE LINK {fossil}" in cap.err
    assert "0 issues" in cap.out


def test_cmd_resolve_namespace_without_project_root_attribute(lay: Layout) -> None:
    ns = argparse.Namespace(resolve="CTL", motor_root=str(lay.t3_motor))
    assert pr.cmd_resolve(ns) == 1


# --- ronda 2: git indeterminado, PermissionError, precedencia, last_resolution ----


def _hub(lay: Layout) -> Path:
    """A unique FDL link sitting next to the T3 motor (the sibling-guess bait)."""
    hub = lay.t3_dir / "hub"
    _worktree(lay.motor, hub, "hub")
    _link(hub, motor_root=str(hub), destination_root=str(hub), ticket_prefix="FDL")
    return hub


class _Proc:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


_GIT_FAILURES = {
    "git-missing": None,
    "oserror": OSError("boom"),
    "dubious-ownership": _Proc(128, "", "fatal: detected dubious ownership"),
    "odd-output": _Proc(0, "only-one-line\n", ""),
    "rc1-no-message": _Proc(1, "", ""),
}


def _break_git(monkeypatch: pytest.MonkeyPatch, how: str) -> None:
    """Make `git rev-parse` unusable for prefix_resolver only (not the fixtures)."""
    failure = _GIT_FAILURES[how]
    if how == "git-missing":
        monkeypatch.setattr(pr, "_git_executable", lambda: None)
        return

    def _run(*_a, **_k):
        if isinstance(failure, Exception):
            raise failure
        return failure

    monkeypatch.setattr(pr.subprocess, "run", _run)


@pytest.mark.parametrize("how", list(_GIT_FAILURES))
def test_t3_linked_motor_with_undeterminable_git_does_not_scan(
    lay: Layout, monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    """'git cannot tell' is NOT 'not a repo' (BA254 r1, A): a linked T3 motor with
    a unique sibling link must stay linked_worktree_no_known."""
    _hub(lay)
    with monkeypatch.context() as m:
        _break_git(m, how)
        assert pr.resolve_prefix_known("FDL", lay.t3_motor) == pr.Resolution(
            None, "linked_worktree_no_known"
        )


def test_undeterminable_git_still_scans_dev_pair_primary_and_plain_motor(
    lay: Layout, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The .git marker answers without git: the `_dev` pair (file -> the main
    checkout's sibling), the primary checkout (.git dir) and a REAL non-git motor
    all keep scanning."""
    dest = tmp_path / "c" / "ctl_dest"
    _init(dest)
    _link(
        dest, motor_root=str(lay.motor), destination_root=str(dest), ticket_prefix="CTL"
    )
    plain = tmp_path / "plain" / "motor"
    plain.mkdir(parents=True)
    plain_dest = tmp_path / "plain" / "dest"
    _link(
        plain_dest,
        motor_root=str(plain),
        destination_root=str(plain_dest),
        ticket_prefix="EXF",
    )
    with monkeypatch.context() as m:
        _break_git(m, "git-missing")
        assert pr.resolve_prefix_known("CTL", lay.motor_dev) == pr.Resolution(
            dest, "map"
        )
        assert pr.resolve_prefix_known("CTL", lay.motor) == pr.Resolution(dest, "map")
        assert pr.resolve_prefix_known("EXF", plain) == pr.Resolution(plain_dest, "map")


def test_undeterminable_git_nested_or_odd_marker_is_fail_closed(
    lay: Layout, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without git: a motor nested INSIDE a repo, or with a .git file that is not a
    worktree gitdir (submodule shape, garbage), cannot be established: no scan."""
    nested = lay.motor / "sub" / "m"
    nested.mkdir(parents=True)
    _link(
        lay.motor / "sub" / "x",
        motor_root="m",
        destination_root="x",
        ticket_prefix="FDL",
    )
    odd = tmp_path / "odd" / "motor"
    odd.mkdir(parents=True)
    (odd / ".git").write_text("gitdir: ../elsewhere/.git/modules/m\n", encoding="utf-8")
    _link(
        tmp_path / "odd" / "y",
        motor_root="m",
        destination_root="y",
        ticket_prefix="FDL",
    )
    junk = tmp_path / "junk" / "motor"
    junk.mkdir(parents=True)
    (junk / ".git").write_text("not a gitdir line\n", encoding="utf-8")
    _link(
        tmp_path / "junk" / "z",
        motor_root="m",
        destination_root="z",
        ticket_prefix="FDL",
    )
    with monkeypatch.context() as m:
        _break_git(m, "git-missing")
        for motor in (nested, odd, junk):
            assert pr.resolve_prefix_known("FDL", motor) == pr.Resolution(
                None, "linked_worktree_no_known"
            ), motor


def test_unlistable_scan_root_is_unknown_not_a_raise(
    lay: Layout, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PermissionError while listing parent(motor_root) (BA254 r1, D)."""
    dest = tmp_path / "c" / "ctl_dest"
    _init(dest)
    _link(
        dest,
        motor_root=str(lay.motor_dev),
        destination_root=str(dest),
        ticket_prefix="CTL",
    )

    def _denied(self):
        raise PermissionError("denied")

    with monkeypatch.context() as m:
        m.setattr(Path, "iterdir", _denied)
        assert pr.resolve_prefix_known("CTL", lay.motor_dev) == pr.Resolution(
            None, "unknown"
        )
        assert pr.resolve_prefix_known(
            "ctl_dest", lay.motor_dev, by_name=True
        ) == pr.Resolution(None, "unknown")
        assert pr.resolve_prefix("CTL", lay.motor_dev) is None


# --- ronda 2 (C): razones y precedencia que faltaban -------------------------------


def test_override_wins_and_is_reported(lay: Layout, tmp_path: Path) -> None:
    other = tmp_path / "elsewhere"
    for motor in (lay.t3_motor, lay.motor_dev):
        overrides = motor / "scripts" / pr.LOCAL_OVERRIDES.name
        overrides.parent.mkdir(exist_ok=True)
        overrides.write_text(
            json.dumps({"overrides": {"CTL": str(other)}}), encoding="utf-8"
        )
        # the override beats even a valid known destination
        assert pr.resolve_prefix_known("CTL", motor, lay.ctl_wt) == pr.Resolution(
            other, "override"
        )
        # project-name lookups do not consult overrides
        assert (
            pr.resolve_prefix_known("w", motor, lay.ctl_wt, by_name=True).reason
            == "known"
        )


def test_unknown_without_known_in_a_scannable_layout(lay: Layout) -> None:
    assert pr.resolve_prefix_known("ZZZ", lay.motor_dev) == pr.Resolution(
        None, "unknown"
    )
    assert pr.resolve_prefix_known("", lay.motor_dev) == pr.Resolution(None, "unknown")
    assert pr.resolve_prefix_known(None, lay.motor_dev) == pr.Resolution(
        None, "unknown"
    )


def _write_root_mismatch(path: Path, other: str) -> None:
    path.write_text(
        json.dumps({"ticket_prefix": "CTL", "destination_root": other}),
        encoding="utf-8",
    )


def _write_unreadable(path: Path, other: str) -> None:
    path.write_text("{", encoding="utf-8")


def _write_no_prefix(path: Path, other: str) -> None:
    path.write_text(json.dumps({"destination_root": other}), encoding="utf-8")


@pytest.mark.parametrize(
    ("write", "reason"),
    [
        (_write_root_mismatch, "known_root_mismatch"),
        (_write_unreadable, "known_link_unreadable"),
        (_write_no_prefix, "known_link_no_prefix"),
    ],
    ids=["root-mismatch", "unreadable", "no-prefix"],
)
def test_canonical_known_defect_is_kept_when_the_scan_finds_nothing(
    lay: Layout, tmp_path: Path, write, reason: str
) -> None:
    broken = tmp_path / "x" / "broken"  # outside the scanned parent (c/)
    _init(broken)
    link = _link(broken, motor_root=str(lay.motor_dev), destination_root=str(broken))
    write(link, str(lay.motor))
    assert pr.resolve_prefix_known("CTL", lay.motor_dev, broken) == pr.Resolution(
        None, reason
    )


def test_known_defect_beats_ambiguous_but_soft_reasons_do_not(
    lay: Layout, tmp_path: Path
) -> None:
    for name in ("a", "b"):
        d = tmp_path / "c" / name
        _init(d)
        _link(
            d,
            motor_root=str(lay.motor_dev),
            destination_root=str(d),
            ticket_prefix="CTL",
        )
    copied = tmp_path / "c" / "copied"
    _init(copied)
    _link(
        copied,
        motor_root=str(lay.motor_dev),
        destination_root=str(lay.motor),
        ticket_prefix="CTL",
    )
    missing = tmp_path / "c" / "nolink"
    missing.mkdir()
    other = tmp_path / "c" / "exf"
    _init(other)
    _link(
        other,
        motor_root=str(lay.motor_dev),
        destination_root=str(other),
        ticket_prefix="EXF",
    )
    # documented precedence: defect > ambiguous > soft known reasons > unknown
    assert (
        pr.resolve_prefix_known("CTL", lay.motor_dev, copied).reason
        == "known_root_mismatch"
    )
    assert pr.resolve_prefix_known("CTL", lay.motor_dev, missing).reason == "ambiguous"
    assert pr.resolve_prefix_known("CTL", lay.motor_dev, other).reason == "ambiguous"
    assert (
        pr.resolve_prefix_known("QQQ", lay.motor_dev, other).reason
        == "known_prefix_mismatch"
    )


# --- ronda 2 (B): L7, the cause stays reachable without changing the signature ----


def test_adapter_keeps_the_last_resolution_without_changing_the_signature(
    lay: Layout,
) -> None:
    hub = _hub(lay)
    adapter = sc._known_prefix_adapter(
        pr.resolve_prefix_known, pr.resolve_prefix, lay.ctl_wt
    )
    assert adapter.last_resolution is None
    assert adapter("CTL", lay.t3_motor) == lay.ctl_wt
    assert adapter.last_resolution == pr.Resolution(lay.ctl_wt, "known")
    assert adapter("FDL", lay.t3_motor) is None
    assert adapter.last_resolution == pr.Resolution(None, "known_prefix_mismatch")
    seam = sc._known_prefix_adapter(
        pr.resolve_prefix_known, lambda prefix, _m: hub, lay.ctl_wt
    )
    assert seam("FDL", lay.t3_motor) == hub
    assert seam.last_resolution.path == hub


# --- capa 1 (BA254, MAJOR 1): gitdir administrativo podado, repro con git real -------


def _prune_admin_dir(lay: Layout) -> None:
    """The T3 motor keeps its `.git` FILE but the main repo lost `.git/worktrees/m`:
    git then says `not a git repository: <gitdir>` (no 'or any of the parent
    directories' tail) although the directory IS a (broken) linked worktree."""
    import shutil

    shutil.rmtree(lay.motor / ".git" / "worktrees" / lay.t3_motor.name)


def test_pruned_t3_worktree_is_a_broken_repo_not_a_non_repo(lay: Layout) -> None:
    _hub(lay)
    _prune_admin_dir(lay)
    dirs, status = pr._git_probe(lay.t3_motor)
    assert (dirs, status) == (None, "unknown")
    assert pr.resolve_prefix_known("FDL", lay.t3_motor) == pr.Resolution(
        None, "linked_worktree_no_known"
    )


def test_not_a_repo_with_a_git_marker_is_still_decided_from_the_marker(
    lay: Layout, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Belt: even if git answered with the genuine non-repo wording, a `.git`
    marker at the motor root sends the decision to the marker (T3 pointer)."""
    _hub(lay)
    genuine = _Proc(
        128,
        "",
        "fatal: not a git repository (or any of the parent directories): .git",
    )
    with monkeypatch.context() as m:
        m.setattr(pr.subprocess, "run", lambda *a, **k: genuine)
        assert pr._git_probe(lay.t3_motor) == (None, "not-a-repo")
        assert pr.resolve_prefix_known("FDL", lay.t3_motor) == pr.Resolution(
            None, "linked_worktree_no_known"
        )


# --- capa 1 ronda 2 (BA254): marcador .git que no es ni directorio ni fichero ------


def _dangling_git_marker(motor: Path, scratch: Path) -> None:
    """Make `<motor>/.git` a link whose target no longer exists (symlink on POSIX,
    junction on Windows, where symlinks need a privilege)."""
    target = scratch / "gone"
    target.mkdir()
    marker = motor / ".git"
    if sys.platform == "win32":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(marker), str(target)],
            check=True,
            capture_output=True,
        )
    else:
        marker.symlink_to(target, target_is_directory=True)
    target.rmdir()
    assert not marker.exists()
    assert os.path.lexists(marker)


@pytest.mark.parametrize("how", ["git-missing", "genuine-no-repo"])
def test_dangling_git_marker_is_not_a_non_git_motor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    motor = tmp_path / "d" / "motor"
    motor.mkdir(parents=True)
    _dangling_git_marker(motor, tmp_path)
    sibling = tmp_path / "d" / "dest"
    _link(
        sibling,
        motor_root=str(motor),
        destination_root=str(sibling),
        ticket_prefix="EXF",
    )
    with monkeypatch.context() as m:
        if how == "git-missing":
            _break_git(m, "git-missing")
        else:
            genuine = _Proc(
                128,
                "",
                "fatal: not a git repository (or any of the parent directories): .git",
            )
            m.setattr(pr.subprocess, "run", lambda *a, **k: genuine)
        assert pr.resolve_prefix_known("EXF", motor) == pr.Resolution(
            None, "linked_worktree_no_known"
        )


def test_dangling_git_marker_in_an_ancestor_is_not_a_non_git_motor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outer = tmp_path / "o"
    motor = outer / "inner" / "motor"
    motor.mkdir(parents=True)
    _dangling_git_marker(outer, tmp_path)
    sibling = outer / "inner" / "dest"
    _link(
        sibling,
        motor_root=str(motor),
        destination_root=str(sibling),
        ticket_prefix="EXF",
    )
    with monkeypatch.context() as m:
        _break_git(m, "git-missing")
        assert (
            pr.resolve_prefix_known("EXF", motor).reason == "linked_worktree_no_known"
        )


# --- capa 1 ronda 3 (BA254): un error de acceso al marcador NO es "ausente" ----------


@pytest.mark.parametrize(
    ("how", "where"),
    [
        ("git-missing", "motor-root"),
        ("git-missing", "ancestor"),
        ("genuine-no-repo", "motor-root"),
    ],
)
def test_unreadable_git_marker_is_not_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, how: str, where: str
) -> None:
    motor = tmp_path / "d" / "motor"
    motor.mkdir(parents=True)
    sibling = tmp_path / "d" / "dest"
    _link(
        sibling,
        motor_root=str(motor),
        destination_root=str(sibling),
        ticket_prefix="EXF",
    )
    real_lstat = os.lstat
    watched = motor / ".git" if where == "motor-root" else motor.parent / ".git"

    def _lstat(path, *a, **k):
        if os.path.normcase(str(path)) == os.path.normcase(str(watched)):
            raise PermissionError("denied")
        return real_lstat(path, *a, **k)

    with monkeypatch.context() as m:
        m.setattr(pr.os, "lstat", _lstat)
        if how == "git-missing":
            _break_git(m, "git-missing")
        else:
            genuine = _Proc(
                128,
                "",
                "fatal: not a git repository (or any of the parent directories): .git",
            )
            m.setattr(pr.subprocess, "run", lambda *a, **k: genuine)
        assert pr.resolve_prefix_known("EXF", motor) == pr.Resolution(
            None, "linked_worktree_no_known"
        )


# --- ronda 5 (CO-24 M2/M3): el FAIL del closeout nombra la causa --------------------


def _write_other_ticket_plan(root: Path, ticket: str) -> None:
    plan = root / ".agent" / "collaboration" / f"work_plan_{ticket}.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(
        f"# Work plan\n\n- **ID:** {ticket}\n- **Estado:** IN_PROGRESS\n"
        "- **delivery_authority:** repo_destino\n- **deliverable_type:** code\n",
        encoding="utf-8",
    )


def test_closeout_fail_names_the_cause_known_root_mismatch(lay: Layout) -> None:
    _write_plan(lay.ctl_wt)
    _link(
        lay.ctl_wt,
        motor_root=str(lay.t3_motor),
        destination_root=str(lay.ctl_primary),
        ticket_prefix="CTL",
    )
    res = _closeout_result(lay.ctl_wt)
    assert (res.status, res.blocking) == ("FAIL", True)
    assert "FAIL_TARGETS_MISSING" in res.detail
    assert "[causa de la resolucion: known_root_mismatch]" in res.detail


def test_closeout_fail_for_another_prefix_names_cause_and_override(lay: Layout) -> None:
    """[B2] seen from the closeout: a FDL ticket audited from a CTL workspace in T3."""
    _hub(lay)
    _write_other_ticket_plan(lay.ctl_wt, "FDL-2026-001a")
    setup = sc._resolve_writer_setup(lay.ctl_wt, None)
    res = sc._process_ticket_targets(
        "FDL-2026-001a",
        lay.ctl_wt,
        setup.motor_root,
        setup.extract_prefix_fn,
        setup.resolve_prefix_fn,
        [],
    )
    assert (res.status, res.blocking) == ("FAIL", True)
    assert "known_prefix_mismatch; declara un override local para FDL" in res.detail


def test_closeout_dry_run_prediction_carries_the_cause(lay: Layout) -> None:
    _write_plan(lay.ctl_wt)
    _link(
        lay.ctl_wt,
        motor_root=str(lay.t3_motor),
        destination_root=str(lay.ctl_primary),
        ticket_prefix="CTL",
    )
    step = sc._dry_run_targets_prediction(lay.ctl_wt, [TICKET])
    assert "known_root_mismatch" in step.detail


def test_closeout_fail_without_a_cause_offering_callback_is_unchanged(
    lay: Layout,
) -> None:
    """A plain callback (test fake, plain resolver) has no last_resolution: the
    FAIL detail is exactly the historical text, with no cause suffix."""
    _write_plan(lay.ctl_wt)
    res = sc._process_ticket_targets(
        TICKET,
        lay.ctl_wt,
        lay.t3_motor,
        lambda ticket: ticket.split("-")[0],
        lambda prefix, motor: None,
        [],
    )
    assert (res.status, res.blocking) == ("FAIL", True)
    assert "causa de la resolucion" not in res.detail
    assert res.detail.endswith("(WOT-2026-066i D2)")


def test_resolution_cause_ignores_a_stale_result_of_another_prefix(lay: Layout) -> None:
    adapter = sc._known_prefix_adapter(
        pr.resolve_prefix_known, pr.resolve_prefix, lay.ctl_wt
    )
    assert sc._resolution_cause(adapter, "FDL") == ""  # nothing resolved yet
    assert adapter("FDL", lay.t3_motor) is None
    assert "known_prefix_mismatch" in sc._resolution_cause(adapter, "FDL")
    assert sc._resolution_cause(adapter, "CTL") == ""  # last call was for FDL


def test_adapter_fallback_provenance_is_documented_and_kept_apart(
    lay: Layout, tmp_path: Path
) -> None:
    other = tmp_path / "elsewhere"
    answering = sc._known_prefix_adapter(
        pr.resolve_prefix_known, lambda prefix, _m: other, lay.ctl_wt
    )
    assert answering("FDL", lay.t3_motor) == other
    # the plain fallback reports no reason: the final answer is only "map" ...
    assert answering.last_resolution == pr.Resolution(other, "map")
    # ... but why the KNOWN step did not match is kept apart
    assert answering.last_known_resolution == pr.Resolution(
        None, "known_prefix_mismatch"
    )
    assert answering.last_prefix == "FDL"
    silent = sc._known_prefix_adapter(
        pr.resolve_prefix_known, lambda prefix, _m: None, lay.ctl_wt
    )
    assert silent("FDL", lay.t3_motor) is None
    assert silent.last_resolution == silent.last_known_resolution


def test_failing_call_does_not_inherit_the_cause_of_an_earlier_call(
    lay: Layout,
) -> None:
    """Same prefix, two tickets: the second call raises, so the FAIL must NOT
    carry the first call's cause (BA254 ronda 5)."""
    _link(
        lay.ctl_wt,
        motor_root=str(lay.t3_motor),
        destination_root=str(lay.ctl_primary),
        ticket_prefix="CTL",
    )
    calls: list[int] = []

    def flaky_known(prefix, motor_root, known_destination):
        calls.append(1)
        if len(calls) > 1:
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "boom")
        return pr.resolve_prefix_known(prefix, motor_root, known_destination)

    adapter = sc._known_prefix_adapter(flaky_known, pr.resolve_prefix, lay.ctl_wt)
    assert adapter("CTL", lay.t3_motor) is None
    assert "known_root_mismatch" in sc._resolution_cause(adapter, "CTL")
    with pytest.raises(UnicodeDecodeError):
        adapter("CTL", lay.t3_motor)
    assert sc._resolution_cause(adapter, "CTL") == ""
    _write_plan(lay.ctl_wt)
    _write_other_ticket_plan(lay.ctl_wt, "CTL-2026-002a")
    calls.clear()
    adapter_e2e = sc._known_prefix_adapter(flaky_known, pr.resolve_prefix, lay.ctl_wt)
    results = [
        sc._process_ticket_targets(
            ticket,
            lay.ctl_wt,
            lay.t3_motor,
            lambda t: t.split("-")[0],
            adapter_e2e,
            [],
        )
        for ticket in (TICKET, "CTL-2026-002a")
    ]
    assert "known_root_mismatch" in results[0].detail
    assert results[1].blocking and "FAIL_TARGETS_MISSING" in results[1].detail
    assert "causa de la resolucion" not in results[1].detail


# --- ronda 7 (CO-24 capa 2): un GIT_DIR heredado y VALIDO no sustituye el repo ----


@pytest.mark.parametrize(
    "variable", ["GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"]
)
def test_inherited_valid_git_env_does_not_make_a_t3_motor_look_primary(
    lay: Layout, monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    """A valid foreign GIT_DIR makes ``rev-parse --git-dir/--git-common-dir`` answer
    the SAME dir for any path, i.e. "primary checkout": the lone sibling used to be
    scanned (fail-open) instead of linked_worktree_no_known."""
    _hub(lay)
    foreign = lay.motor / ".git"
    monkeypatch.setenv(variable, str(foreign))
    assert pr.resolve_prefix_known("FDL", lay.t3_motor, None) == pr.Resolution(
        None, "linked_worktree_no_known"
    )
    dirs, status = pr._git_probe(lay.t3_motor)
    assert status == "ok" and dirs is not None and dirs[0] != dirs[1]


def test_inherited_git_dir_does_not_equate_two_unrelated_repos(
    lay: Layout, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_DIR", str(lay.motor / ".git"))
    assert pr._git_common_dir(lay.ctl_primary) != pr._git_common_dir(lay.motor)
