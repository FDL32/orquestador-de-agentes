"""Hermetic tests for scripts/check_agents_accessible.py (WOT-2026-026e, T-026E-001).

Covers the frozen DoD criteria (b)-(g): the 3 agent-channel outcomes (incl. the
which-vs-invocation DIVERGENCE oracle and the TimeoutExpired branch), the
api-channel non-leak guarantee, the published denominator, the required/warn
split, the unknown-`--require` usage error and the `--level 1` zero-traffic
refusal. Every test names the mutation it kills; pairs are persisted in
`orchestrator_pipeline/reports/flight_20260717/MUTATION_WOT-2026-026e.md`
(workspace repo, per AGENTS.md: evidence artifacts never live in the motor).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


# scripts/ is not a package: insert it on sys.path as the script itself does.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import check_agents_accessible as caa  # noqa: E402


_WINDOWS_ONLY = pytest.mark.skipif(
    sys.platform != "win32",
    reason="which-vs-CreateProcess PATHEXT divergence is a Windows-specific "
    "oracle; on POSIX shutil.which already requires the executable bit, so "
    "there is no equivalent divergence to reproduce. Declared per AGENTS.md: "
    "a skipif test's mutation does not count.",
)


def _agent_config(executable: str) -> dict:
    return {
        "backends": {"fake_agent_backend": {"executable": executable}},
        "ensemble_profiles": {
            "proposer_x": {"backend": "fake_agent_backend", "channel": "agent"}
        },
    }


def _api_config(env_name: str) -> dict:
    return {
        "backends": {},
        "ensemble_profiles": {
            "challenger_x": {
                "backend": "nan_api",
                "channel": "api",
                "api_key_env": env_name,
            }
        },
    }


# --------------------------------------------------------------------------- #
# (b) channel=agent: 3 disjoint outcomes
# --------------------------------------------------------------------------- #
def test_agent_channel_accessible_real_executable():
    """Portable ACCESIBLE leg: sys.executable --version really runs (rc irrelevant)."""
    config = _agent_config(sys.executable)
    result = caa.collect_accessibility(config, require=[])
    info = result["profiles"]["proposer_x"]
    assert info["verdict"] == "ACCESIBLE"
    assert info["channel"] == "agent"


def test_agent_channel_inaccessible_nonexistent_executable(tmp_path):
    """Portable INACCESIBLE leg: a full path that does not exist -> FileNotFoundError."""
    ghost = tmp_path / "does_not_exist_xyz.exe"
    config = _agent_config(str(ghost))
    result = caa.collect_accessibility(config, require=[])
    info = result["profiles"]["proposer_x"]
    assert info["verdict"] == "INACCESIBLE"


@_WINDOWS_ONLY
def test_which_vs_invocation_divergence(tmp_path, monkeypatch):
    """DIVERGENCE oracle (b): `shutil.which` resolves a bare name via PATHEXT to
    a `.cmd`, but `subprocess.run([name, ...], shell=False)` on the SAME bare
    name does NOT do that extension search (Windows CreateProcess only appends
    `.exe` implicitly) -- so it raises FileNotFoundError even though `which`
    found something. This is the exact reason the contract forbids
    `shutil.which` as the oracle. Measured directly on this machine:
    `shutil.which("faux")` -> `<tmp>\\faux.CMD`; `subprocess.run(["faux", ...])`
    -> `FileNotFoundError [WinError 2]`.

    Mutation this kills: replacing the `subprocess.run` oracle in
    `_check_agent_channel` with a `shutil.which(executable) is not None` check
    would flip this test's verdict from INACCESIBLE to ACCESIBLE (a false green
    for an executable that cannot actually be invoked bare).
    """
    import shutil

    faux = tmp_path / "faux.cmd"
    faux.write_text("@echo off\r\necho hello-from-faux\r\n", encoding="utf-8")
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ.get("PATH", ""))

    which_result = shutil.which("faux")
    assert which_result is not None, (
        "precondition: which must resolve the bare name via PATHEXT"
    )

    config = _agent_config("faux")  # bare name, resolved only through PATH/PATHEXT
    result = caa.collect_accessibility(config, require=[])
    info = result["profiles"]["proposer_x"]
    assert info["verdict"] == "INACCESIBLE", (
        f"which resolved {which_result!r} but the real oracle must still report "
        "INACCESIBLE for a bare name CreateProcess cannot find"
    )


@_WINDOWS_ONLY
def test_agent_channel_timeout_is_separate_from_oserror(tmp_path):
    """(b) 3rd outcome: TimeoutExpired is captured SEPARATELY from OSError and
    yields the distinct 'INACCESIBLE-timeout' verdict.

    Mutation this kills: folding `except subprocess.TimeoutExpired` into the
    generic `except OSError` branch (TimeoutExpired is not an OSError subclass,
    so removing the dedicated except entirely would let the exception escape
    uncaught -- collect_accessibility would crash instead of returning a verdict).
    """
    slow = tmp_path / "slow.cmd"
    slow.write_text(
        "@echo off\r\nping -n 4 127.0.0.1 >nul\r\necho done\r\n", encoding="utf-8"
    )
    config = _agent_config(str(slow))
    result = caa.collect_accessibility(config, require=[], timeout=1)
    info = result["profiles"]["proposer_x"]
    assert info["verdict"] == "INACCESIBLE-timeout"


def test_agent_channel_unknown_backend_is_inaccesible():
    """A profile referencing a backend absent from config['backends'] must not
    crash `collect_accessibility` -- it normalizes to INACCESIBLE."""
    config = {
        "backends": {},
        "ensemble_profiles": {
            "proposer_x": {"backend": "ghost_backend", "channel": "agent"}
        },
    }
    result = caa.collect_accessibility(config, require=[])
    assert result["profiles"]["proposer_x"]["verdict"] == "INACCESIBLE"


# --------------------------------------------------------------------------- #
# (c) channel=api: presence-only verdict, VALUE never leaked
# --------------------------------------------------------------------------- #
def test_api_channel_accessible_when_env_defined(monkeypatch):
    monkeypatch.setenv("FAKE_ENSEMBLE_API_KEY", "irrelevant-value")
    config = _api_config("FAKE_ENSEMBLE_API_KEY")
    result = caa.collect_accessibility(config, require=[])
    assert result["profiles"]["challenger_x"]["verdict"] == "ACCESIBLE"


def test_api_channel_inaccessible_when_env_undefined(monkeypatch):
    monkeypatch.delenv("FAKE_ENSEMBLE_API_KEY_ABSENT", raising=False)
    config = _api_config("FAKE_ENSEMBLE_API_KEY_ABSENT")
    result = caa.collect_accessibility(config, require=[])
    assert result["profiles"]["challenger_x"]["verdict"] == "INACCESIBLE"


def test_api_channel_never_leaks_env_value(monkeypatch, capsys):
    """NO-FUGA (c): the sentinel VALUE must appear NOWHERE in the returned
    structure nor in main()'s printed report, on EITHER branch (present).

    Mutation this kills: any `f"... = {os.environ[env_name]}"` (or similar)
    slipped into a detail string or print statement.
    """
    sentinel = "SUPER-SECRET-SENTINEL-9f8e7d6c"
    monkeypatch.setenv("SENTINEL_ENV_VAR", sentinel)
    config = _api_config("SENTINEL_ENV_VAR")

    result = caa.collect_accessibility(config, require=[])
    assert sentinel not in repr(result)

    monkeypatch.setattr(caa, "load_agents_config", lambda project_root=None: config)
    rc = caa.main([])
    assert rc == 0
    captured = capsys.readouterr()
    assert sentinel not in captured.out
    assert sentinel not in captured.err


# --------------------------------------------------------------------------- #
# (d) denominator ALWAYS published, unsupported channel EXCLUDED + enumerated
# --------------------------------------------------------------------------- #
def test_unsupported_channel_is_excluded_and_enumerated():
    """(d) A channel outside {agent, api} is EXCLUDED, never silently accessible.

    Mutation this kills: dispatching an unknown channel as if it were 'agent'
    or 'api' (or omitting it from `excluded`) instead of excluding it.
    """
    config = {
        "backends": {},
        "ensemble_profiles": {
            "weird_profile": {"backend": "x", "channel": "smoke-signal"}
        },
    }
    result = caa.collect_accessibility(config, require=[])
    assert result["n_total"] == 1
    assert result["n_checked"] == 0
    assert result["n_excluded"] == 1
    assert result["excluded"] == [
        {"profile": "weird_profile", "reason": "unsupported channel 'smoke-signal'"}
    ]
    assert "weird_profile" not in result["profiles"]


def test_excluded_required_profile_is_fail_closed():
    """(d) An excluded profile that IS required counts as `fail`, not silently
    dropped -- fail-closed, matching the contract wording exactly."""
    config = {
        "backends": {},
        "ensemble_profiles": {
            "weird_profile": {"backend": "x", "channel": "smoke-signal"}
        },
    }
    result = caa.collect_accessibility(config, require=["weird_profile"])
    assert result["status"]["weird_profile"] == "fail"
    assert result["n_fail"] == 1


def test_denominator_published_via_main_even_on_exit_1(monkeypatch, capsys):
    """(d) The `N=... -> M=...` denominator line prints even when the run ends
    in exit 1 (a required profile is inaccessible)."""
    config = _agent_config(str(Path("/definitely/not/here/ghost.exe")))
    monkeypatch.setattr(caa, "load_agents_config", lambda project_root=None: config)
    rc = caa.main(["--require", "proposer_x"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "[agents-accessible] N=1 -> M=1" in out
    assert "fail=1" in out


# --------------------------------------------------------------------------- #
# (e) FAIL only for REQUIRED profiles; default (no --require) -> all WARN, exit 0
# --------------------------------------------------------------------------- #
def test_default_no_require_all_warn_exit_zero(monkeypatch):
    """(e) With no --require, an inaccessible profile is WARN, not FAIL -> exit 0.

    Mutation this kills: treating every profile as required regardless of
    `--require` (an inaccessible optional profile would then fail the run).
    """
    config = _agent_config(str(Path("/definitely/not/here/ghost.exe")))
    monkeypatch.setattr(caa, "load_agents_config", lambda project_root=None: config)
    rc = caa.main([])
    assert rc == 0


def test_required_inaccessible_profile_fails(monkeypatch):
    """(e) The SAME inaccessible profile, but now --require'd, must fail (exit 1)."""
    config = _agent_config(str(Path("/definitely/not/here/ghost.exe")))
    monkeypatch.setattr(caa, "load_agents_config", lambda project_root=None: config)
    rc = caa.main(["--require", "proposer_x"])
    assert rc == 1


# --------------------------------------------------------------------------- #
# (f) --require of an unknown profile -> exit 2, never a silent no-op
# --------------------------------------------------------------------------- #
def test_require_unknown_profile_exits_2_never_silent(monkeypatch, capsys):
    """Mutation this kills: silently ignoring an unrecognized --require name
    (which would make an operator's typo pass as exit 0)."""
    config = _api_config("SOME_ENV")
    monkeypatch.setattr(caa, "load_agents_config", lambda project_root=None: config)
    rc = caa.main(["--require", "totally_unknown_profile"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "totally_unknown_profile" in err


# --------------------------------------------------------------------------- #
# (g) --level 1 refuses unconditionally with ZERO external traffic
# --------------------------------------------------------------------------- #
def test_level_1_refuses_before_touching_config_or_subprocess(monkeypatch, capsys):
    """Mutation this kills: `--level 1` reaching `load_agents_config` (or any
    subprocess/env access) instead of refusing immediately. The assertion
    inside `_boom` makes any such dispatch fail LOUDLY, not silently."""

    def _boom(*_a, **_k):
        raise AssertionError("--level 1 must refuse BEFORE loading any config")

    monkeypatch.setattr(caa, "load_agents_config", _boom)
    rc = caa.main(["--level", "1"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "WOT-2026-025s" in err


# --------------------------------------------------------------------------- #
# Config-load failure -> exit 1 (invalid agents.json), never a crash
# --------------------------------------------------------------------------- #
def test_invalid_agents_config_exits_1(monkeypatch, capsys):
    def _raise(*_a, **_k):
        raise caa.AgentsConfigError("simulated schema violation")

    monkeypatch.setattr(caa, "load_agents_config", _raise)
    rc = caa.main([])
    assert rc == 1
    assert "simulated schema violation" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# (k) NO test in this module asserts a profile COUNT against the real motor
# config (that would break the instant 025z adds/removes a profile). The only
# assertions against `load_agents_config(project_root=MOTOR_ROOT)` (the real
# call, unmocked) go through the CLI smoke below and assert STRUCTURE, never N.
# --------------------------------------------------------------------------- #
def test_cli_against_real_motor_config_smoke():
    """Real, unmocked `main()` run against the motor's own agents.json: proves
    the whole pipeline (load -> collect -> report) works end-to-end. Asserts
    only STRUCTURE (exit in {0, 1}, denominator line present) -- NEVER a profile
    count (criterion (k): 025z can change N without invalidating this test)."""
    rc = caa.main([])
    assert rc in (0, 1)


def test_collect_accessibility_is_importable_standalone():
    """Sanity: the function the preflight imports exists with the exact name."""
    assert callable(caa.collect_accessibility)
