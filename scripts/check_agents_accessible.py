#!/usr/bin/env python3
# ruff: noqa: S603
"""NIVEL 0 accessibility preflight for `ensemble_profiles` agents (WOT-2026-026e).

Checks, for every profile in `agents.json::ensemble_profiles`, whether the agent
is REACHABLE -- never whether it would succeed at a real task. This is a
presence/liveness signal, not a policy/quota/quality oracle (that class of
failure -- e.g. an API returning HTTP 400 for an unsupported `service_tier` --
is NIVEL 1, out of scope here; see criterion (j) of the frozen contract).

Two channels, two disjoint verdicts, discriminated ONLY by `profile["channel"]`
(never by `executable`, never by heuristics on the backend name):

  channel=agent  -- the ORACLE is a real subprocess invocation:
      `subprocess.run([executable, "--version"], shell=False,
      capture_output=True, stdin=DEVNULL, timeout=<N>)`. NEVER `shutil.which`:
      a PATH-existence probe and a real CreateProcess invocation can DIVERGE
      (see `tests/unit/test_check_agents_accessible.py::test_which_vs_invocation_divergence`
      -- a `.cmd` resolved by `which`'s PATHEXT search is NOT necessarily
      invocable via a bare `subprocess.run([name, ...], shell=False)`, because
      CreateProcess's own extension search differs from `PATHEXT`/shell lookup).
      Exactly 3 outcomes:
        - `FileNotFoundError`/other `OSError`  -> INACCESIBLE
        - `subprocess.TimeoutExpired`          -> INACCESIBLE-timeout (captured
          SEPARATELY; NOT folded into the OSError branch)
        - any return (any return code, rc is IRRELEVANT) -> ACCESIBLE

  channel=api    -- the verdict is the PRESENCE (never the VALUE) of the
      environment variable NAMED by `profile["api_key_env"]`. The value is
      never read into a local, never printed, never returned.

Before: `.agent/config/agents.json` of the MOTOR is loadable and passes
    `agents_config.load_agents_config` (the single schema layer, WOT-2026-019o);
    this script does not re-validate or re-derive that schema.
During: `collect_accessibility()` computes the accessibility signal for every
    profile (or a directly-constructed config dict, for hermetic testing) and
    NEVER performs channel=api network traffic -- `--level 1` (real smoke
    traffic) is refused unconditionally by `main()` before touching config,
    env or subprocess (owner: WOT-2026-025s).
After: prints a denominator line ALWAYS (also on exit 1): `N=<n> -> M=<m>
    (<k> excluidos); required=<r> ok=<o> warn=<w> fail=<f>`, with every
    excluded profile enumerated by name and reason. Exit 0 if no REQUIRED
    profile failed (default: nothing required -> everything WARN-only ->
    exit 0); exit 1 if a required profile is inaccessible or `agents.json` is
    invalid; exit 2 on usage error (`--require` of an unknown profile,
    or `--level 1`).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


# Motor-explicit root (M9): the repo that owns THIS script, never the env
# (AGENT_PROJECT_ROOT's priority-1 resolution would point at a workspace whose
# agents.json has no ensemble_* keys). Copied verbatim from the precedent at
# scripts/validate_agent_config.py:31-40.
MOTOR_ROOT = Path(__file__).resolve().parent.parent
_AGENT_DIR = MOTOR_ROOT / ".agent"
# APPEND, never insert(0): with .agent up front, `runtime` would resolve to
# `.agent/runtime/` instead of `<motor>/runtime/` (pytest-collection hazard
# documented in AGENTS.md).
if str(_AGENT_DIR) not in sys.path:
    sys.path.append(str(_AGENT_DIR))

from agents_config import (  # noqa: E402
    AgentsConfigError,
    load_agents_config,
    resolve_executable,
)


DEFAULT_TIMEOUT = 10.0
SUPPORTED_CHANNELS = ("agent", "api")


def _check_agent_channel(
    profile: dict, config: dict, timeout: float
) -> tuple[str, str]:
    """channel=agent verdict: a real subprocess invocation is the ORACLE.

    Before: `profile["backend"]` names a key in `config["backends"]`; `timeout`
        is a positive number of seconds.
    During: resolves the executable via `agents_config.resolve_executable`
        (single schema layer -- this function re-derives NOTHING about the
        backend schema) and calls `subprocess.run([executable, "--version"],
        shell=False, capture_output=True, stdin=DEVNULL, timeout=timeout)`.
        NEVER `shutil.which`. The return code is irrelevant: any completed
        process proves the executable is invocable.
    After: returns exactly one of 3 outcomes: `("ACCESIBLE", detail)` on any
        return; `("INACCESIBLE-timeout", detail)` on `subprocess.TimeoutExpired`
        (caught SEPARATELY, never folded into the OSError branch);
        `("INACCESIBLE", detail)` on `FileNotFoundError`/other `OSError`
        (includes an unresolvable backend, normalized to the same verdict).
    """
    backend_name = profile.get("backend")
    try:
        executable = resolve_executable(backend_name, config)
    except AgentsConfigError as exc:
        return "INACCESIBLE", f"backend resolution failed: {exc}"
    if not executable:
        return "INACCESIBLE", f"backend '{backend_name}' has no executable configured"
    try:
        subprocess.run(
            [executable, "--version"],
            shell=False,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return (
            "INACCESIBLE-timeout",
            f"'{executable} --version' exceeded the {timeout}s timeout",
        )
    except OSError as exc:
        return (
            "INACCESIBLE",
            f"'{executable} --version' could not be invoked: {exc.__class__.__name__}",
        )
    return (
        "ACCESIBLE",
        f"'{executable} --version' ran to completion (return code irrelevant)",
    )


def _check_api_channel(profile: dict) -> tuple[str, str]:
    """channel=api verdict: PRESENCE of the named env var, its VALUE never read.

    Before: `profile["api_key_env"]` is the NAME of an environment variable
        (agents_config's credential-literal ban already forbids a literal
        secret here).
    During: checks `env_name in os.environ` -- existence only. The value is
        never assigned to a local, never printed, never placed in the detail
        string returned to the caller.
    After: returns `("ACCESIBLE", detail)` if the var is defined, else
        `("INACCESIBLE", detail)`. Neither branch's detail string contains the
        variable's value.
    """
    env_name = profile.get("api_key_env")
    if not env_name:
        return "INACCESIBLE", "profile has no 'api_key_env' declared"
    if env_name in os.environ:
        return "ACCESIBLE", f"env var '{env_name}' is defined"
    return "INACCESIBLE", f"env var '{env_name}' is NOT defined"


def collect_accessibility(
    config: dict, require: list[str] | None = None, timeout: float = DEFAULT_TIMEOUT
) -> dict:
    """Compute the NIVEL 0 accessibility signal for every `ensemble_profiles` entry.

    Before: `config` is a dict shaped like the output of
        `agents_config.load_agents_config` (must carry `ensemble_profiles`;
        `backends` needed only for channel=agent profiles). `require` is a
        list of profile NAMES that must resolve to ACCESIBLE (default: none,
        meaning every profile is WARN-only). Callers (CLI `main()` or the
        preflight collector) are responsible for validating that every name in
        `require` actually exists in `config["ensemble_profiles"]` -- this
        function does not raise on an unknown required name; see `missing_required`.
    During: iterates every profile once; dispatches strictly on
        `profile["channel"]` (never on `executable` or backend name). A
        `channel` outside `SUPPORTED_CHANNELS` is EXCLUDED (never silently
        treated as accessible) and, if the profile is in `require`, that
        exclusion counts as `fail` (fail-closed). NEVER performs any network
        traffic; channel=agent only spawns a local subprocess, channel=api only
        reads an env var's presence.
    After: returns a dict with `n_total`/`n_checked`/`n_excluded`, the
        `excluded` list (each `{"profile", "reason"}`), `required`/`n_required`,
        the `n_ok`/`n_warn`/`n_fail` counts, `missing_required` (names in
        `require` absent from `config["ensemble_profiles"]`), the per-profile
        `profiles` dict (`channel`/`verdict`/`detail`) and the per-profile
        `status` dict (`ok`/`warn`/`fail`/`excluded`). The denominator
        (`n_total`/`n_checked`/`n_excluded`) is always fully populated, even
        when `n_fail > 0`.
    """
    profiles = config.get("ensemble_profiles") or {}
    require = list(require or [])
    missing_required = sorted(r for r in require if r not in profiles)

    checked: dict[str, dict] = {}
    excluded: list[dict] = []
    for name, prof in profiles.items():
        channel = prof.get("channel")
        if channel not in SUPPORTED_CHANNELS:
            excluded.append(
                {"profile": name, "reason": f"unsupported channel {channel!r}"}
            )
            continue
        if channel == "agent":
            verdict, detail = _check_agent_channel(prof, config, timeout)
        else:
            verdict, detail = _check_api_channel(prof)
        checked[name] = {"channel": channel, "verdict": verdict, "detail": detail}

    excluded_names = {e["profile"] for e in excluded}
    status: dict[str, str] = {}
    n_ok = n_warn = n_fail = 0
    for name in profiles:
        is_required = name in require
        if name in excluded_names:
            outcome = "fail" if is_required else "excluded"
        else:
            accessible = checked[name]["verdict"] == "ACCESIBLE"
            outcome = ("ok" if accessible else "fail") if is_required else "warn"
        status[name] = outcome
        if outcome == "ok":
            n_ok += 1
        elif outcome == "warn":
            n_warn += 1
        elif outcome == "fail":
            n_fail += 1

    return {
        "n_total": len(profiles),
        "n_checked": len(checked),
        "n_excluded": len(excluded),
        "excluded": excluded,
        "required": require,
        "n_required": len(require),
        "missing_required": missing_required,
        "n_ok": n_ok,
        "n_warn": n_warn,
        "n_fail": n_fail,
        "profiles": checked,
        "status": status,
    }


def _report(result: dict) -> None:
    excluded = result["excluded"]
    excluded_str = (
        ", ".join(f"{e['profile']} ({e['reason']})" for e in excluded)
        if excluded
        else "none"
    )
    print(
        f"[agents-accessible] N={result['n_total']} -> M={result['n_checked']} "
        f"({result['n_excluded']} excluidos); required={result['n_required']} "
        f"ok={result['n_ok']} warn={result['n_warn']} fail={result['n_fail']}"
    )
    print(f"[agents-accessible] excluded: {excluded_str}")
    for name in sorted(result["profiles"]):
        info = result["profiles"][name]
        outcome = result["status"][name]
        print(
            f"    {name} [{info['channel']}] -> {info['verdict']} "
            f"({outcome}) :: {info['detail']}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="NIVEL 0 accessibility preflight for ensemble_profiles agents "
        "(WOT-2026-026e). Presence/liveness only -- never real traffic."
    )
    parser.add_argument(
        "--require",
        action="append",
        default=[],
        metavar="PROFILE",
        help="Ensemble profile name that MUST be ACCESIBLE (repeatable). "
        "Default: none required -> every profile is WARN-only, exit 0.",
    )
    parser.add_argument(
        "--level",
        type=int,
        choices=(0, 1),
        default=0,
        help="0 = this structural presence check. 1 = real smoke traffic -- "
        "NOT implemented here; refuses unconditionally with exit 2 "
        "(owner: WOT-2026-025s).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"Per-agent subprocess timeout in seconds (default {DEFAULT_TIMEOUT}).",
    )
    args = parser.parse_args(argv)

    if args.level == 1:
        print(
            "[agents-accessible] ERROR: --level 1 (real smoke traffic) is not "
            "implemented by this NIVEL 0 check; refusing with ZERO external "
            "traffic before touching config, env or subprocess. "
            "Owner: WOT-2026-025s.",
            file=sys.stderr,
        )
        return 2

    try:
        config = load_agents_config(project_root=MOTOR_ROOT)
    except AgentsConfigError as exc:
        print(f"[agents-accessible] ERROR: invalid agents.json: {exc}", file=sys.stderr)
        return 1

    profiles = config.get("ensemble_profiles") or {}
    unknown = sorted(r for r in args.require if r not in profiles)
    if unknown:
        print(
            f"[agents-accessible] ERROR: --require references unknown profile(s) "
            f"{unknown}. Known profiles: {sorted(profiles)}",
            file=sys.stderr,
        )
        return 2

    result = collect_accessibility(config, require=args.require, timeout=args.timeout)
    _report(result)

    return 1 if result["n_fail"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
