"""Sandbox git hermeticity (WOT-2026-021k).

TWO SEPARATE BARRIERS, EACH WITH ITS OWN MUTATION. Do not merge them: merging is
what killed v2 of the contract -- a single mutation did not DISCRIMINATE.

  BARRIER A: the GLOBAL autouse fixture in tests/conftest.py
             (``_isolate_git_discovery_global``) kills the ascent to the REAL
             MOTOR from a strict descendant of tmp_path.
             MUTATION A = remove the global fixture -> this test FAILS (the plain
             dir resolves to the motor's .git).
  BARRIER B: the CEILING RULE itself, against a SYNTHETIC parent the test builds
             under tmp_path. The GLOBAL ceiling does NOT cover this case (the
             synthetic parent hangs BELOW it), so the guard returns rc=0 -- THE
             DAMAGE. An INTERNAL ceiling (strict ancestor of the scanned dir)
             cuts it -> rc=2, fail-closed.
             MUTATION B = remove the INTERNAL ceiling -> this test FAILS.

rc=2 IS THE GOAL, NOT A FAILURE: with a corrupt .git the topology is NOT
determinable, and fail-closed is the honest verdict. rc=1 ("topology known to be
wrong") is not reachable here and is not the correct answer either.

PATH LENGTH (measured 2026-07-13, git 2.53.0.windows.1): a real tmp_path of this
repo is ~136 chars; the deepest file of the tree built below is ~200; git starts
failing with "Filename too long" once tmp_path reaches ~196. Margin ~54 chars, so
this test CAN build the tree under tmp_path -- unlike
scripts/probe_sandbox_git_ascension.py, which uses C:\\tmp out of caution. If the
build ever broke anyway, the setup asserts below report git's literal stderr
instead of lying with "the false-green no longer reproduces".
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import scripts.check_worktree_topology as cwt


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _git_exe() -> str:
    git = shutil.which("git")
    assert git is not None, "git is not on PATH: the test would be vacuous"
    return git


def _run_git(
    *args: str, cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_git_exe(), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _env_without_ceiling() -> dict[str, str]:
    """A copy of the environment with the global ceiling REMOVED."""
    env = dict(os.environ)
    env.pop("GIT_CEILING_DIRECTORIES", None)
    return env


# ---------------------------------------------------------------------------
# BARRIER A -- the global fixture kills the ascent to the REAL MOTOR
# ---------------------------------------------------------------------------


def test_global_ceiling_blocks_ascent_to_real_motor(tmp_path: Path) -> None:
    """A plain dir under tmp_path must not resolve to the motor's .git."""
    # The barrier EXISTS. If the global fixture loses its autouse or gets renamed
    # (or shadowed by a same-named module fixture), this says so directly instead
    # of letting us infer it from an exit code.
    assert os.environ.get("GIT_CEILING_DIRECTORIES") == str(tmp_path)

    # CONTROL against a vacuous test: git works and DOES resolve where it should.
    # Without this, "git is missing from PATH" would make the barrier assert below
    # pass for the wrong reason.
    assert (PROJECT_ROOT / "pyproject.toml").is_file(), PROJECT_ROOT
    control = _run_git(
        "-C",
        str(PROJECT_ROOT),
        "rev-parse",
        "--path-format=absolute",
        "--git-common-dir",
        cwd=PROJECT_ROOT,
    )
    assert control.returncode == 0, control.stderr

    plain = tmp_path / "plain"
    plain.mkdir()
    # Without this, a non-existent dir would yield rc != 0 via "cannot change to",
    # satisfying the barrier assert below for a reason that has nothing to do with
    # the ceiling (measured: the two stderrs differ).
    assert plain.is_dir()

    # THE COUNTERFACTUAL -- this is what makes the barrier assert LOAD-BEARING.
    # Without it, the test would only prove "the env var is set" plus "a dir with
    # no repo above it is not a repo", and it would stay GREEN even if the damage
    # it guards against no longer existed (e.g. once TEST_RUNTIME_ROOT moves out of
    # the tree, which is a separate ticket). Here we PIN THE DAMAGE: with the
    # ceiling removed from the subprocess env, this very dir resolves to the SAME
    # git dir as the real motor. If this ever fails, the premise of this barrier is
    # dead and the test must be reconsidered -- loudly, not silently.
    damage = _run_git(
        "-C",
        str(plain),
        "rev-parse",
        "--path-format=absolute",
        "--git-common-dir",
        cwd=plain,
        env=_env_without_ceiling(),
    )
    assert damage.returncode == 0, damage.stderr
    assert Path(damage.stdout.strip()) == Path(control.stdout.strip()), (
        f"expected the sandbox to ascend into the motor ({control.stdout.strip()}), "
        f"got {damage.stdout.strip()!r}"
    )

    # THE BARRIER: with the ceiling in place (the global fixture), the same command
    # must NOT resolve to any repo.
    result = _run_git(
        "-C",
        str(plain),
        "rev-parse",
        "--path-format=absolute",
        "--git-common-dir",
        cwd=plain,
    )
    assert result.returncode != 0, result.stdout
    assert "not a git repository" in result.stderr, result.stderr
    assert ".git" not in result.stdout


# ---------------------------------------------------------------------------
# BARRIER B -- the ceiling rule against a SYNTHETIC parent under tmp_path
# ---------------------------------------------------------------------------


def test_internal_ceiling_kills_the_false_green(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The INTERNAL ceiling turns rc=0 (THE DAMAGE) into rc=2 (fail-closed)."""
    # --- build the 4 conditions of the premise, under tmp_path ---------------
    motor = tmp_path / "motor"
    motor.mkdir()
    setup: list[subprocess.CompletedProcess[str]] = [
        _run_git("init", "-b", "main", cwd=motor),
        _run_git("config", "user.email", "probe@example.com", cwd=motor),
        _run_git("config", "user.name", "Probe", cwd=motor),
    ]
    (motor / "README.md").write_text("probe\n", encoding="utf-8")
    setup.append(_run_git("add", "-A", cwd=motor))
    setup.append(_run_git("commit", "-m", "base", cwd=motor))
    # git refuses the same branch in two worktrees: detach the primary FIRST.
    setup.append(_run_git("checkout", "--detach", "main", cwd=motor))
    motor_dev = tmp_path / "motor_dev"
    setup.append(_run_git("worktree", "add", str(motor_dev), "main", cwd=motor))

    fixture = motor_dev / "tests" / "sandbox" / "fx"
    fixture.mkdir(parents=True)
    setup.append(_run_git("init", "-b", "main", cwd=fixture))
    (fixture / ".git" / "HEAD").unlink()  # CONDITION 2: the .git is INCOMPLETE

    workspace = tmp_path / "orquestador_de_agentes_workspace"
    link_dir = workspace / ".agent" / "config"
    link_dir.mkdir(parents=True)
    link = link_dir / "motor_destination_link.json"
    link.write_text(
        json.dumps(
            {
                "motor_root": str(motor),
                "destination_root": str(workspace),
                "motor_version": "v9.17.1",
                "destination_id": "orquestador_de_agentes_workspace",
                "ticket_prefix": "WOT",  # CONDITION 3
            }
        ),
        encoding="utf-8",
    )

    # --- setup asserts: without them the test is a FALSE GREEN ---------------
    # A silently-failed `git init` leaves a PLAIN dir, which ascends just the
    # same: the test would still see rc=0 then rc=2 and pass WITHOUT ever
    # exercising condition 2 (an incomplete .git) -- i.e. green without the
    # mechanism this ticket exists to kill.
    for proc in setup:
        assert proc.returncode == 0, f"broken setup: {proc.args} -> {proc.stderr}"
    assert (motor_dev / ".git").exists()  # condition 1
    assert (fixture / ".git").is_dir()  # condition 2a: there WAS a .git
    assert not (fixture / ".git" / "HEAD").exists()  # condition 2b: INCOMPLETE
    assert json.loads(link.read_text(encoding="utf-8"))["ticket_prefix"] == "WOT"
    # Condition 2 in its OBSERVABLE form: the ascent really happens.
    assert cwt._git_common_dir(fixture) == cwt._git_common_dir(motor)
    # A work_plan in the synthetic motor would short-circuit check_topology with
    # rc=2 for an unrelated reason (contract incoherence), masking the false-green.
    assert not (motor / ".agent" / "collaboration" / "work_plan.md").exists()

    # resolve_prefix consults load_overrides() BEFORE scan_links, and
    # scripts/prefix_resolver.local.json is gitignored: it does not exist here, but
    # a third party with a WOT override would get rc=1 and this test would die.
    # NOTE: the guard imports the TOP-LEVEL module `prefix_resolver` (sys.path
    # insert + bare import, check_worktree_topology.py:66-67), NOT
    # `scripts.prefix_resolver` -- they are two distinct objects, so patching the
    # packaged one is a silent no-op.
    monkeypatch.setattr(
        cwt.prefix_resolver, "LOCAL_OVERRIDES", tmp_path / "no_such.json"
    )
    assert cwt.prefix_resolver.load_overrides() == {}  # the patch bit

    # --- 1) NO internal ceiling: only the GLOBAL one (= tmp_path), which does
    #        NOT cover this case (the synthetic parent hangs BELOW it).
    assert os.environ["GIT_CEILING_DIRECTORIES"] == str(tmp_path)
    exit_code, message = cwt.check_topology("WOT-2026-021k", fixture, motor, workspace)
    assert exit_code == 0, message  # THE DAMAGE: the guard approves a foreign topology
    assert "topologia correcta" in message

    # --- 2) WITH the internal ceiling (strict ancestor of the scanned dir).
    # GIT_CEILING_DIRECTORIES is a LIST: keep the global entry too, so this test
    # does not switch off the protection against the REAL motor while it runs.
    monkeypatch.setenv(
        "GIT_CEILING_DIRECTORIES",
        os.pathsep.join([str(fixture.parent), str(tmp_path)]),
    )
    exit_code_2, message_2 = cwt.check_topology(
        "WOT-2026-021k", fixture, motor, workspace
    )
    assert exit_code_2 == 2, message_2  # fail-closed is the honest verdict (not rc=1)
    assert "no se puede determinar topologia" in message_2
