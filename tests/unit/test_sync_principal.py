"""Tests for scripts/sync_principal.py (safe primary-checkout sync).

Uses REAL ephemeral git repos under tmp_path (the logic IS git plumbing, so real
git exercises it far more faithfully than mocks). Each test builds a topology and
asserts the plan/apply behaviour, with the load-bearing case being DIVERGENCE:
the primary has unpushed commits that must be rescued, never dropped (the exact
WOT-2026-019f / CTL-012i loss scenario).
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path


_SPEC = importlib.util.spec_from_file_location(
    "sync_principal",
    Path(__file__).resolve().parents[2] / "scripts" / "sync_principal.py",
)
sp = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sp)


def _g(args, cwd):
    """Run a git command in cwd, raising on failure (test setup must succeed)."""
    subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _sha(cwd, ref="HEAD"):
    return subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", ref],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _make_repo_with_main(tmp_path):
    """A bare 'origin' + a work clone with main having 2 commits pushed.

    Returns (origin_bare, work). `work` is the primary-like checkout; main is at
    origin/main. Callers then diverge/detach `work` to build each scenario.
    """
    origin = tmp_path / "origin.git"
    _g(["init", "--bare", "-b", "main", "-q", str(origin)], tmp_path)
    work = tmp_path / "work"
    _g(["clone", "-q", str(origin), str(work)], tmp_path)
    _g(["config", "user.email", "t@t.com"], work)
    _g(["config", "user.name", "t"], work)
    (work / "base.txt").write_text("base\n", encoding="utf-8")
    _g(["add", "base.txt"], work)
    _g(["commit", "-qm", "base"], work)
    (work / "more.txt").write_text("more\n", encoding="utf-8")
    _g(["add", "more.txt"], work)
    _g(["commit", "-qm", "main advances"], work)
    _g(["push", "-q", "origin", "main"], work)
    _g(["fetch", "-q", "origin"], work)
    return origin, work


def test_already_current(tmp_path):
    """Primary HEAD == origin/main -> action already_current, no mutation."""
    _origin, work = _make_repo_with_main(tmp_path)
    _g(["checkout", "-q", "--detach", "origin/main"], work)
    plan = sp.plan_sync(work, work, "origin/main", "20260101_0000")
    assert plan["action"] == "already_current"


def test_advance_clean_fast_forward(tmp_path):
    """Primary is an ANCESTOR of origin/main (behind, no divergence) -> advance."""
    _origin, work = _make_repo_with_main(tmp_path)
    # detach one commit behind origin/main
    _g(["checkout", "-q", "--detach", "origin/main~1"], work)
    behind = _sha(work)
    plan = sp.plan_sync(work, work, "origin/main", "20260101_0000")
    assert plan["action"] == "advance"
    assert "rescue_branch" not in plan
    log = sp.apply_plan(work, work, plan)
    assert _sha(work) == _sha(work, "origin/main")  # advanced
    assert _sha(work) != behind
    assert any("advanced" in ln for ln in log)


def test_divergent_unpushed_is_rescued_then_advanced(tmp_path):
    """The load-bearing case: primary has 2 UNPUSHED divergent commits.

    Must create a rescue branch pointing at the old HEAD, advance the primary to
    origin/main, and leave the 2 commits fully reachable (nothing dropped).
    """
    _origin, work = _make_repo_with_main(tmp_path)
    _g(["checkout", "-q", "--detach", "origin/main~1"], work)
    (work / "ctl1.txt").write_text("ctl1\n", encoding="utf-8")
    _g(["add", "ctl1.txt"], work)
    _g(["commit", "-qm", "CTL commit 1"], work)
    (work / "ctl2.txt").write_text("ctl2\n", encoding="utf-8")
    _g(["add", "ctl2.txt"], work)
    _g(["commit", "-qm", "CTL commit 2 unpushed"], work)
    old_head = _sha(work)

    plan = sp.plan_sync(work, work, "origin/main", "20260710_1300")
    assert plan["action"] == "rescue_then_advance"
    assert len(plan["unpushed_commits"]) == 2
    assert plan["rescue_branch"] == f"rescue/{old_head[:7]}-20260710_1300"

    sp.apply_plan(work, work, plan)
    # primary advanced to origin/main
    assert _sha(work) == _sha(work, "origin/main")
    # rescue branch exists and points at the old head -> both commits reachable
    rescued = _sha(work, plan["rescue_branch"])
    assert rescued == old_head
    subjects = subprocess.run(
        ["git", "-C", str(work), "log", "--format=%s", plan["rescue_branch"]],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "CTL commit 1" in subjects and "CTL commit 2 unpushed" in subjects


def test_rescue_branch_is_auto_pushed_to_origin(tmp_path):
    """#2: the rescue branch is pushed to origin so it does not depend on the reflog
    (the ctl-012i-wip single-point-of-failure). The repo has a real bare origin."""
    origin, work = _make_repo_with_main(tmp_path)
    _g(["checkout", "-q", "--detach", "origin/main~1"], work)
    (work / "u.txt").write_text("u\n", encoding="utf-8")
    _g(["add", "u.txt"], work)
    _g(["commit", "-qm", "unpushed CTL"], work)
    plan = sp.plan_sync(work, work, "origin/main", "20260710_1300")
    assert plan["action"] == "rescue_then_advance"
    log = sp.apply_plan(work, work, plan)
    rb = plan["rescue_branch"]
    # the rescue branch now exists in the bare origin (recoverable without the reflog)
    remote = subprocess.run(
        [
            "git",
            "-C",
            str(origin),
            "for-each-ref",
            "--format=%(refname:short)",
            f"refs/heads/{rb}",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert remote == rb
    assert any("pushed to origin" in ln for ln in log)


def test_rescue_autopush_failopen_still_advances(tmp_path):
    """#2 fail-OPEN: if the rescue push fails (no remote), the run WARNs but the
    primary STILL advances and the local rescue branch still exists -- the push
    failure must never abort the advance or drop work."""
    _origin, work = _make_repo_with_main(tmp_path)
    _g(["checkout", "-q", "--detach", "origin/main~1"], work)
    (work / "u.txt").write_text("u\n", encoding="utf-8")
    _g(["add", "u.txt"], work)
    _g(["commit", "-qm", "unpushed CTL"], work)
    old_head = _sha(work)
    # remove the remote so the push cannot succeed
    _g(["remote", "remove", "origin"], work)
    plan = sp.plan_sync(work, work, "refs/heads/main", "20260710_1300")
    # MUST be rescue_then_advance, or this test would vacuously pass without ever
    # exercising the fail-open push path (a barrier that stops being tested is a
    # false-green). The unpushed commit against a diverged main IS a rescue case.
    assert plan["action"] == "rescue_then_advance", (
        f"expected rescue_then_advance to exercise fail-open, got {plan['action']}"
    )
    log = sp.apply_plan(work, work, plan)
    rb = plan["rescue_branch"]
    # advance still happened
    assert _sha(work) == _sha(work, "refs/heads/main")
    # local rescue branch still holds the work
    assert _sha(work, rb) == old_head
    # a WARN was logged, not a raise
    assert any("WARN" in ln and "push" in ln.lower() for ln in log)


def test_divergent_but_pushed_advances_without_rescue(tmp_path):
    """Divergent commits that ARE on a remote branch are safe to leave -> advance,
    no rescue branch (they are recoverable from the remote)."""
    _origin, work = _make_repo_with_main(tmp_path)
    _g(["checkout", "-q", "--detach", "origin/main~1"], work)
    (work / "side.txt").write_text("side\n", encoding="utf-8")
    _g(["add", "side.txt"], work)
    _g(["commit", "-qm", "side commit"], work)
    # push it to a remote branch so it's recoverable, then re-fetch
    _g(["push", "-q", "origin", "HEAD:refs/heads/sidebranch"], work)
    _g(["fetch", "-q", "origin"], work)
    plan = sp.plan_sync(work, work, "origin/main", "20260101_0000")
    assert plan["action"] == "advance"  # not rescue: it's already on a remote
    assert plan["divergent_commits"]  # there WAS divergence
    assert plan["unpushed_commits"] == []  # but nothing unpushed


def test_refuse_named_branch(tmp_path):
    """Primary on a NAMED branch (not detached) -> refuse, do not touch."""
    _origin, work = _make_repo_with_main(tmp_path)
    _g(["checkout", "-q", "main"], work)  # named branch, not detached
    plan = sp.plan_sync(work, work, "origin/main", "20260101_0000")
    assert plan["action"] == "refuse_named_branch"
    before = _sha(work)
    log = sp.apply_plan(work, work, plan)  # must be a no-op
    assert log == []
    assert _sha(work) == before  # untouched


def test_rescue_queue_reports_unmerged(tmp_path):
    """A rescue/* branch not merged into the target appears in the pending queue;
    once merged (ancestor of target) it drops off."""
    _origin, work = _make_repo_with_main(tmp_path)
    # create a rescue branch off an old commit (not merged into origin/main path)
    _g(["branch", "rescue/abc1234-20260101_0000", "origin/main~1"], work)
    pending = sp._rescue_queue(work, "origin/main")
    # origin/main~1 IS an ancestor of origin/main -> considered "merged" -> not pending
    assert all("rescue/abc1234" not in r["branch"] for r in pending)
    # now make a truly divergent rescue branch (a commit not on origin/main)
    _g(["checkout", "-q", "--detach", "origin/main~1"], work)
    (work / "x.txt").write_text("x\n", encoding="utf-8")
    _g(["add", "x.txt"], work)
    _g(["commit", "-qm", "divergent"], work)
    _g(["branch", "rescue/div0000-20260101_0000", "HEAD"], work)
    _g(["checkout", "-q", "--detach", "origin/main"], work)
    pending = sp._rescue_queue(work, "origin/main")
    assert any("rescue/div0000" in r["branch"] for r in pending)


def test_detect_primary_picks_non_dev_worktree(tmp_path):
    """_detect_primary returns the single worktree whose basename is not *_dev."""
    _origin, work = _make_repo_with_main(tmp_path)
    dev = tmp_path / "work_dev"
    _g(["worktree", "add", "-q", "--detach", str(dev), "HEAD"], work)
    primary = sp._detect_primary(work)
    assert primary is not None
    assert primary.name == "work"  # not work_dev


def test_bad_motor_root_exits_2(tmp_path):
    notrepo = tmp_path / "x"
    notrepo.mkdir()
    rc = sp.main(["--motor-root", str(notrepo), "--primary-root", str(notrepo)])
    assert rc == 2


def test_dry_run_does_not_mutate(tmp_path):
    """Without --apply, a rescue_then_advance plan is reported but nothing changes."""
    _origin, work = _make_repo_with_main(tmp_path)
    _g(["checkout", "-q", "--detach", "origin/main~1"], work)
    (work / "u.txt").write_text("u\n", encoding="utf-8")
    _g(["add", "u.txt"], work)
    _g(["commit", "-qm", "unpushed"], work)
    before = _sha(work)
    rc = sp.main(
        [
            "--motor-root",
            str(work),
            "--primary-root",
            str(work),
            "--now",
            "20260101_0000",  # dry-run (no --apply)
        ]
    )
    assert rc == 0
    assert _sha(work) == before  # unchanged
    # no rescue branch created in dry-run
    branches = subprocess.run(
        ["git", "-C", str(work), "branch", "--list", "rescue/*"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert branches == ""


def test_refuse_named_branch_exit_1(tmp_path):
    _origin, work = _make_repo_with_main(tmp_path)
    _g(["checkout", "-q", "main"], work)
    rc = sp.main(["--motor-root", str(work), "--primary-root", str(work)])
    assert rc == 1
