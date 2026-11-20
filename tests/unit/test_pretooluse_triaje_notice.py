"""Tests for the triaje notice hook through its real subprocess boundary.

Before: the hook script and the settings entry may not exist yet (red phase).
During: every test drives the production script or the production wrapper
    command with an isolated environment and synthetic registries.
After: positive cases must emit one valid PreToolUse additionalContext JSON;
    negative and fail-open cases must return rc 0 with empty streams.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / ".agent" / "hooks" / "pretooluse_triaje_notice.py"
SETTINGS = REPO_ROOT / ".claude" / "settings.json"
NEEDED_MATCHER = {"Agent", "Task", "mcp__t3-code__delegate_task"}


def _run(payload, env):
    """Run the hook with a JSON payload.

    Before: ``payload`` is the exact PreToolUse event and ``env`` is isolated.
    During: starts the production script as a child process.
    After: returns the real process result for behavioral assertions.
    """
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=payload if isinstance(payload, str) else json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def _env(flight_dir, tid=None):
    """Build a clean environment for one discriminator scenario.

    Before: ``flight_dir`` is a temporary registry directory or ``None``.
    During: removes inherited discriminator variables (exact names plus the
        F2_/T3_ families the probes also strip) and restores only fixtures.
    After: returns an environment that cannot depend on the live registry.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"T3_THREAD_ID", "FLIGHT_DIR", "AGENT_PROJECT_ROOT"}
        and not key.startswith("F2_")
        and not key.startswith("T3_")
    }
    if flight_dir is not None:
        env["FLIGHT_DIR"] = str(flight_dir)
    if tid is not None:
        env["T3_THREAD_ID"] = tid
    return env


def _registry(path, tr=False, bom=False):
    """Write a minimal registry containing the requested live sessions.

    Before: ``path`` is a temporary directory, ``tr`` selects a live triaje and
        ``bom`` selects a UTF-8 BOM prefix (PowerShell 5.1 writer case).
    During: serializes the same session schema used by the flight registry.
    After: creates a deterministic registry fixture for the subprocess.
    """
    sessions = [{"role": "orquestadora", "status": "ACTIVA", "threadId": "CO-FIX"}]
    if tr:
        sessions.append({"role": "triaje", "status": "ACTIVA", "threadId": "TR-FIX"})
    payload = json.dumps({"sessions": sessions})
    target = path / "session_registry.json"
    if bom:
        target.write_bytes(b"\xef\xbb\xbf" + payload.encode("utf-8"))
    else:
        target.write_text(payload, encoding="utf-8")


def _event(tool, tool_input):
    """Create the smallest valid event for one supported tool name."""
    return {"tool_name": tool, "tool_input": tool_input}


def _fires(result):
    """Validate the positive output contract rather than merely its existence."""
    if result.returncode != 0 or result.stderr != "":
        return False
    data = json.loads(result.stdout)
    output = data["hookSpecificOutput"]
    return (
        output["hookEventName"] == "PreToolUse"
        and isinstance(output["additionalContext"], str)
        and bool(output["additionalContext"].strip())
    )


def _notice_entry():
    """Return the single settings PreToolUse entry that targets our script.

    Before: the tracked ``.claude/settings.json`` may lack the entry (red phase).
    During: filters PreToolUse entries whose matcher carries the three required
        alternatives and whose hooks name our script.
    After: returns that entry or ``None``; more than one match is a defect.
    """
    settings = json.loads(SETTINGS.read_text(encoding="utf-8-sig"))
    entries = []
    for entry in settings.get("hooks", {}).get("PreToolUse", []):
        parts = {part for part in str(entry.get("matcher", "")).split("|") if part}
        names_script = "pretooluse_triaje_notice.py" in json.dumps(
            entry, ensure_ascii=False
        )
        if parts.issuperset(NEEDED_MATCHER) and names_script:
            entries.append(entry)
    if len(entries) != 1:
        return None
    return entries[0]


def test_supported_tools_and_recursive_strings_fire(tmp_path):
    """Verify all tools, split fields, and nested strings trigger a notice.

    Before: a registry has the active coordinator matching the normalized tid.
    During: sends three tool shapes plus split and nested patterns.
    After: every positive emits only the required informational JSON object.
    """
    _registry(tmp_path)
    env = _env(tmp_path, "mcp:CO-FIX")
    cases = [
        ("Agent", {"prompt": "triaje del backlog"}),
        ("Task", {"task": "triaje de tickets"}),
        ("mcp__t3-code__delegate_task", {"description": "fichas de triage"}),
        (
            "Agent",
            {"description": "plan de triaje", "title": "backlog", "prompt": "limpio"},
        ),
        (
            "Task",
            {"meta": {"items": ["brief", {"value": "triage de fichas"}]}},
        ),
    ]
    for tool, tool_input in cases:
        assert _fires(_run(_event(tool, tool_input), env))


def test_negative_pattern_and_unknown_tool_are_silent(tmp_path):
    """Verify incomplete patterns and unsupported tools remain silent.

    Before: the registry and coordinator are valid, so only pattern/tool gates vary.
    During: invokes the hook with one-term, unknown-tool, and malformed events.
    After: each invocation exits zero with both output streams empty.
    """
    _registry(tmp_path)
    env = _env(tmp_path, "mcp:CO-FIX")
    cases = [
        _event("Agent", {"prompt": "triaje solamente"}),
        _event("Task", {"prompt": "backlog solamente"}),
        _event("Other", {"prompt": "triaje del backlog"}),
        "not json",
    ]
    for case in cases:
        result = _run(case, env)
        assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_discriminator_branches_and_active_boundary(tmp_path):
    """Cover coordinator/tid and no-tid/TR-live discriminator branches.

    Before: two registries model the five required e1..e5 cases.
    During: runs matching, foreign, and absent tid scenarios, including ACTIVA2.
    After: only e1, e3, and e4 fire; ACTIVA2 is deliberately inactive.
    """
    no_tr = tmp_path / "no_tr"
    with_tr = tmp_path / "with_tr"
    no_tr.mkdir()
    with_tr.mkdir()
    _registry(no_tr)
    _registry(with_tr, tr=True)
    event = _event("Agent", {"prompt": "triaje del backlog"})
    expected = [
        (_env(no_tr, "mcp:CO-FIX"), True),
        (_env(no_tr, "mcp:OTHER"), False),
        (_env(with_tr, "mcp:CO-FIX"), True),
        (_env(no_tr), True),
        (_env(with_tr), False),
    ]
    for env, fires in expected:
        result = _run(event, env)
        assert result.returncode == 0
        if fires:
            assert _fires(result)
        else:
            assert result.stdout == ""

    (no_tr / "session_registry.json").write_text(
        json.dumps(
            {
                "sessions": [
                    {"role": "orquestadora", "status": "ACTIVA2", "threadId": "CO-FIX"}
                ]
            }
        ),
        encoding="utf-8",
    )
    result = _run(event, _env(no_tr, "mcp:CO-FIX"))
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_fail_open_with_sanitized_environment():
    """Verify invalid stdin and missing discriminators are fully fail-open.

    Before: the process receives malformed input and no registry variables.
    During: executes the production entry point twice.
    After: both calls return zero and emit no stdout or stderr.
    """
    env = _env(None)
    for payload in ("not json", _event("Agent", {"prompt": "triaje del backlog"})):
        result = _run(payload, env)
        assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_registry_bom_still_fires(tmp_path):
    """A registry written with a UTF-8 BOM must still be readable (fail-open fix).

    Before: the fixture registry carries the EF BB BF prefix that PowerShell 5.1
        writes by default.
    During: the same coordinator-tid positive runs against the BOM file.
    After: the notice still fires, proving the reader uses utf-8-sig.
    """
    _registry(tmp_path, bom=True)
    env = _env(tmp_path, "mcp:CO-FIX")
    result = _run(_event("Agent", {"prompt": "triaje del backlog"}), env)
    assert _fires(result)


def test_settings_entry_invokes_hook_end_to_end(tmp_path):
    """The tracked wrapper command must really invoke the hook (anti-inertia).

    Before: ``.claude/settings.json`` holds exactly one entry whose matcher
        carries Agent, Task and mcp__t3-code__delegate_task and whose command
        names pretooluse_triaje_notice.py.
    During: runs that LITERAL command through the shell with cwd = repo root,
        a firing stdin payload and a synthetic coordinator registry env.
    After: rc 0, empty stderr and a valid additionalContext JSON - a wrapper
        that resolves nothing (the multiline inertia measured on 10cf6d41)
        produces empty stdout and fails here.
    """
    entry = _notice_entry()
    assert entry is not None, "falta la entrada PreToolUse con las tres alternativas"
    hooks = [
        h for h in entry.get("hooks", []) if isinstance(h, dict) and h.get("command")
    ]
    assert hooks, "la entrada sin comando type=command"
    command = hooks[0]["command"]
    assert "exit(2)" not in command.lower()
    assert "deny" not in command.lower()
    assert "permissiondecision" not in command.lower()
    _registry(tmp_path)
    env = _env(tmp_path, "mcp:CO-FIX")
    payload = json.dumps(_event("Agent", {"prompt": "triaje del backlog"}))
    result = subprocess.run(  # noqa: S602 - el camino de produccion ES shell=True
        command,
        shell=True,
        cwd=str(REPO_ROOT),
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert (result.returncode, result.stderr) == (0, "")
    data = json.loads(result.stdout)
    output = data["hookSpecificOutput"]
    assert output["hookEventName"] == "PreToolUse"
    assert isinstance(output["additionalContext"], str)
    assert output["additionalContext"].strip()
