"""Tests for the real PreToolUse triaje notice boundary.

Before: the hook is absent during the red phase and tests exercise its
production subprocess boundary, the real registry, and the literal settings
wrapper.
During: payloads use only the measured Claude/T3 fields and a sanitized
environment; no discriminator environment variables are fabricated.
After: the active coordinator emits one informational context and every other
case remains silent and successful.
"""

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SETTINGS = REPO_ROOT / ".claude" / "settings.json"
REAL_REGISTRY = (
    Path(r"C:\Users\fdl\Proyectos_Python\orquestador_de_agentes_workspace")
    / ".agent"
    / "runtime"
    / "flight"
    / "vuelo-20261026b"
    / "session_registry.json"
)
# Active coordinator when the live tests were written (WOT-2026-176e). It goes
# stale at every relief, so ``REAL_SESSION_ID`` is derived below from the live
# registry; this literal is only the fallback when derivation is impossible.
HISTORIC_REAL_SESSION_ID = "6e2764c7-e3eb-4aef-b20c-9298ab358452"
IM_SESSION_ID = "25b3f440-e83f-4604-bcfc-dc347a473aae"
# Registered live as IM-208, role=implantacion, status=SETTLED: a negative of
# the registered-but-not-active-orquestadora kind, NOT an absent session.
SETTLED_SESSION_ID = "5d4ce451-feb5-4d71-a4f3-321e5e49602d"
# Live T3 flight state exists only on the operator machine: CI checkouts have
# no destination registry (link gitignored, flight unversioned) and no
# provider logs, so tests that read it skip there and run where m-02/m-03
# are actually measurable (WOT-2026-176e B-1). The marker itself
# (``needs_live_state``) is defined after ``_load_hook_module`` because its
# condition also needs the hook's own resolution functions.


def _hook_path() -> Path:
    """Resolve the hook, retaining a test-only seam for mutation copies.

    Before: normal tests must execute the repository hook.
    During: PRETOOLUSE_TRIAJE_HOOK may point at a copied mutant only.
    After: returns the selected subprocess entrypoint without changing runtime
        hook discovery.
    """
    return Path(
        os.environ.get(
            "PRETOOLUSE_TRIAJE_HOOK",
            REPO_ROOT / ".agent" / "hooks" / "pretooluse_triaje_notice.py",
        )
    )


def _load_hook_module(path: Path | None = None):
    """Import the hook under a path-unique name for localization assertions.

    Before: the hook ships as a standalone script, not an importable module.
    During: an importlib spec loads ``path`` (default ``_hook_path()``) under a
        name derived from its resolved path so mutation runs never share a
        stale cache entry.
    After: the freshly executed module is returned for direct function checks.
    """
    path = _hook_path() if path is None else path
    name = f"pretooluse_triaje_notice_{abs(hash(str(path.resolve())))}"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)
_REPO_HOOK = REPO_ROOT / ".agent" / "hooks" / "pretooluse_triaje_notice.py"


def _derive_active_session_id() -> tuple[str | None, str]:
    """Derive the Claude session id of the ACTIVE coordinator from live state.

    Before: ``REAL_REGISTRY`` names the active orquestadora thread
        (``orquestador_activo``, role orquestadora, status ACTIVA); the hook
        resolves a session id to a thread by reading the first 8 KB of the
        thread's own provider log. The REPOSITORY hook is used here, never the
        mutation seam, so a mutant cannot change which cases run.
    During: reads the head of the active thread's log, and returns the first
        UUID that the hook's own ``_thread_for_session`` maps back to that
        thread.
    After: returns ``(session_id, "")`` or ``(None, reason)`` with reason one of
        ``no-registry``, ``no-active-coordinator``, ``no-log`` or
        ``log-format-unresolved`` (the log exists but no UUID in its head
        resolves: the undocumented format changed) or ``derivation-error``
        (any unexpected exception: reported, never silently skipped).
    """
    if not REAL_REGISTRY.is_file():
        return None, "no-registry"
    try:
        hook = _load_hook_module(_REPO_HOOK)
        registry = json.loads(REAL_REGISTRY.read_text(encoding="utf-8-sig"))
        active = registry.get("orquestador_activo")
        threads = [
            session["threadId"]
            for session in registry["sessions"]
            if session.get("code") == active
            and session.get("role") == "orquestadora"
            and isinstance(session.get("status"), str)
            and hook.ACTIVE_PREFIX.match(session["status"])
            and isinstance(session.get("threadId"), str)
        ]
        if not threads:
            return None, "no-active-coordinator"
        log_dir = Path.home() / ".t3" / "userdata" / "logs" / "provider"
        saw_log = False
        for thread in threads:
            uuid_ = thread.removeprefix("mcp:")
            log = log_dir / f"events.mcp-{uuid_}.log"
            if not log.is_file():
                continue
            saw_log = True
            with log.open("rb") as handle:
                head = handle.read(8192).decode("utf-8", "ignore")
            # The thread's own UUID trivially resolves to itself; the hook is
            # driven by the Claude session id, which is a different UUID.
            for candidate in dict.fromkeys(_UUID_RE.findall(head)):
                if candidate.lower() == uuid_.lower():
                    continue
                resolved = hook._thread_for_session(candidate)
                if resolved is not None and hook._same_thread(thread, resolved):
                    return candidate, ""
        return None, ("log-format-unresolved" if saw_log else "no-log")
    except Exception:  # an unexpected failure must stay LOUD, never a skip
        return None, "derivation-error"


_ACTIVE_SESSION_ID, _ACTIVE_SESSION_REASON = _derive_active_session_id()
REAL_SESSION_ID = _ACTIVE_SESSION_ID or HISTORIC_REAL_SESSION_ID

needs_live_state = pytest.mark.skipif(
    not REAL_REGISTRY.is_file(),
    reason="live T3 flight state only on the operator machine",
)

# Cases whose verdict depends on ``REAL_SESSION_ID`` being the ACTIVE
# coordinator (fire cases, and silence cases that must reach the later clauses).
# ``log-format-unresolved`` and ``derivation-error`` are NOT skipped: the cases
# then run with the historic id and the tripwire fails, so a real defect is loud.
_SKIPPABLE_REASONS = ("no-registry", "no-active-coordinator", "no-log")
needs_active_coordinator = pytest.mark.skipif(
    _ACTIVE_SESSION_ID is None and _ACTIVE_SESSION_REASON in _SKIPPABLE_REASONS,
    reason=(
        "cannot derive the active coordinator's session id from live state "
        f"({_ACTIVE_SESSION_REASON}); the identity-dependent case is not measurable"
    ),
)


def _env() -> dict[str, str]:
    """Return the minimum real environment required by the subprocess.

    Before: the parent process may contain unrelated local variables.
    During: removes the three forbidden topology/discriminator variables and
        forces UTF-8 output.
    After: returns a clean environment without inventing session metadata.
    """
    env = os.environ.copy()
    for key in ("T3_THREAD_ID", "FLIGHT_DIR", "AGENT_PROJECT_ROOT"):
        env.pop(key, None)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def _run(
    payload: dict | str, *, cwd: Path = REPO_ROOT
) -> subprocess.CompletedProcess[str]:
    """Execute the hook through the production subprocess boundary."""
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(
        [sys.executable, str(_hook_path())],
        input=raw,
        text=True,
        capture_output=True,
        cwd=cwd,
        env=_env(),
        check=False,
    )


def _event(
    session_id: str,
    tool_input: object,
    tool_name: str = "Agent",
    cwd: Path = REPO_ROOT,
) -> dict:
    """Build a measured Claude Code PreToolUse-shaped event."""
    return {
        "cwd": str(cwd),
        "session_id": session_id,
        "tool_name": tool_name,
        "tool_input": tool_input,
    }


def _output(result: subprocess.CompletedProcess[str]) -> dict:
    """Parse and return the hook-specific output from a successful firing."""
    assert result.returncode == 0
    assert result.stderr == ""
    data = json.loads(result.stdout)
    return data["hookSpecificOutput"]


def _real_registry() -> dict:
    """Load the registry used by the live measured flight, if available."""
    return json.loads(REAL_REGISTRY.read_text(encoding="utf-8-sig"))


def _notice_entry() -> dict:
    """Return the sole new PreToolUse entry for the three supported tools."""
    settings = json.loads(SETTINGS.read_text(encoding="utf-8-sig"))
    matches = [
        entry
        for entry in settings["hooks"]["PreToolUse"]
        if set(str(entry.get("matcher", "")).split("|"))
        >= {"Agent", "Task", "mcp__t3-code__delegate_task"}
        and "pretooluse_triaje_notice.py" in json.dumps(entry)
    ]
    assert len(matches) == 1
    return matches[0]


def _first_command(entry: dict) -> str:
    """Extract the command hook used by the settings anti-inertia test."""
    hooks = [hook for hook in entry["hooks"] if hook.get("type") == "command"]
    assert len(hooks) == 1
    return hooks[0]["command"]


@needs_live_state
def test_m02_real_registry_and_outside_project_silence(tmp_path):
    """The hook localizes the real registry from repo cwd without env vars.

    Before: the environment carries no T3_THREAD_ID, FLIGHT_DIR, or
        AGENT_PROJECT_ROOT (removed by ``_env``) and the registry file must
        exist and parse as a live sessions list.
    During: the hook's own discovery functions run against the measured repo
        root (a motor worktree), proving at least one registry is localized
        from cwd alone; then the same hook is executed end to end from a cwd
        outside any project, where it must stay silent.
    After: one or more registries are localized in-project, zero notices fire
        outside, and every process exits zero with empty streams.
    """
    data = _real_registry()
    assert REAL_REGISTRY.exists()
    assert isinstance(data["sessions"], list)
    assert data["sessions"]

    hook = _load_hook_module()
    root = hook._find_project_root(REPO_ROOT)
    assert hook._registry_candidates(root)
    located = hook._load_registry(root)
    assert isinstance(located, dict)
    assert located["sessions"]

    outside_dir = Path(r"C:\Temp\co141\im-176e\outside")
    outside_dir.mkdir(parents=True, exist_ok=True)
    outside = _run(
        _event(REAL_SESSION_ID, {"prompt": "triaje del backlog"}, cwd=outside_dir),
        cwd=outside_dir,
    )
    assert (outside.returncode, outside.stdout, outside.stderr) == (0, "", "")
    outside_root = hook._find_project_root(outside_dir)
    assert not hook._registry_candidates(outside_root)


@needs_live_state
@pytest.mark.parametrize(
    ("session_id", "fixture_name", "fires"),
    [
        pytest.param(
            REAL_SESSION_ID, "incident_prompt.txt", True, marks=needs_active_coordinator
        ),
        (IM_SESSION_ID, "incident_prompt.txt", False),
        (SETTLED_SESSION_ID, "incident_prompt.txt", False),
        pytest.param(
            REAL_SESSION_ID,
            "neg_agent_only_triaje.txt",
            False,
            marks=needs_active_coordinator,
        ),
        pytest.param(
            REAL_SESSION_ID,
            "neg_delegate_only_tickets.txt",
            False,
            marks=needs_active_coordinator,
        ),
        pytest.param(
            REAL_SESSION_ID,
            "neg_incident_lens_review.txt",
            False,
            marks=needs_active_coordinator,
        ),
        pytest.param(
            REAL_SESSION_ID,
            "neg_task_only_backlog.txt",
            False,
            marks=needs_active_coordinator,
        ),
    ],
)
def test_m03_registry_discriminator_and_fixture_patterns(
    session_id, fixture_name, fires
):
    """Apply the full discriminator to registry sessions and all five fixtures."""
    fixture = (
        REPO_ROOT / "tests" / "fixtures" / "pretooluse_triaje_notice" / fixture_name
    )
    prompt = fixture.read_text(encoding="utf-8")
    result = _run(_event(session_id, {"prompt": prompt}))
    if fires:
        output = _output(result)
        assert output["hookEventName"] == "PreToolUse"
        assert output["additionalContext"]
        assert "WOT-2026-176e" in output["additionalContext"]
    else:
        assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


@needs_live_state
@needs_active_coordinator
def test_m03_real_session_id_is_the_log_format_tripwire():
    """The measured UUID tripwires the undocumented, fragile provider-log source.

    If T3 changes its first-8-KB log format, this test fails even though the
    runtime hook is designed to call silently.
    """
    assert _ACTIVE_SESSION_REASON not in (
        "log-format-unresolved",
        "derivation-error",
    ), (
        "cannot derive the active coordinator's session id "
        f"({_ACTIVE_SESSION_REASON}): the provider-log format the hook relies on "
        "changed, or the derivation itself failed"
    )
    result = _run(_event(REAL_SESSION_ID, {"prompt": "triaje del backlog"}))
    assert _output(result)["additionalContext"]


def test_m04_malformed_stdin_is_fully_fail_open():
    """Unreadable stdin exits successfully with both output streams empty."""
    result = _run("not-json")
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_m04_hook_source_has_no_blocking_contract_tokens():
    """The source cannot accidentally advertise a blocking decision contract."""
    source = _hook_path().read_text(encoding="utf-8")
    assert source.lower().count("deny") == 0
    assert source.count("permissionDecision") == 0
    assert source.lower().count("exit 2") == 0
    assert source.lower().count("exit(2)") == 0


@needs_live_state
@needs_active_coordinator
def test_m05_settings_has_one_entry_and_literal_command_fires():
    """The literal tracked wrapper must reach the hook end to end."""
    entry = _notice_entry()
    command = _first_command(entry)
    assert entry["matcher"] == "Agent|Task|mcp__t3-code__delegate_task"
    payload = json.dumps(
        _event(
            REAL_SESSION_ID,
            {
                "prompt": (
                    REPO_ROOT
                    / "tests"
                    / "fixtures"
                    / "pretooluse_triaje_notice"
                    / "incident_prompt.txt"
                ).read_text(encoding="utf-8")
            },
        )
    )
    result = subprocess.run(  # noqa: S602 - literal settings command is production path
        command,
        shell=True,
        cwd=REPO_ROOT,
        input=payload,
        text=True,
        capture_output=True,
        env=_env(),
        check=False,
    )
    assert (result.returncode, result.stderr) == (0, "")
    assert json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]


def test_m05_pretooluse_delta_is_exactly_one():
    """Settings add exactly one PreToolUse entry to the committed baseline.

    Before: ``HEAD`` holds the two legacy entries while the worktree carries
        the new notice entry: the temporal delta of exactly +1 is only
        meaningful while that commit has not been made yet.
    During: once an entry referencing ``pretooluse_triaje_notice`` is already
        in ``HEAD`` (post-commit operator runs, every CI run on a clone, which
        only ever sees committed state) the invariant is satisfied by history
        and the test skips instead of failing a permanent delta of zero.
    After: pre-commit it still asserts delta == 1 with the legacy prefix intact.
    """
    baseline = json.loads(
        subprocess.run(
            ["git", "show", "HEAD:.claude/settings.json"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )
    current = json.loads(SETTINGS.read_text(encoding="utf-8-sig"))
    old = baseline["hooks"]["PreToolUse"]
    new = current["hooks"]["PreToolUse"]
    committed = [
        entry for entry in old if "pretooluse_triaje_notice" in json.dumps(entry)
    ]
    if committed:
        pytest.skip(
            "notice entry already committed: delta==1 is a pre-commit "
            "invariant (WOT-2026-176e)"
        )
    assert len(new) == len(old) + 1
    assert new[:-1] == old


def _tmp_project(tmp_path: Path, sessions: list[dict], active_code: str) -> Path:
    """Build a throwaway project whose flight registry holds ``sessions``.

    Before: the m-03 control needs a registry the hook locates from payload
        cwd alone, without fabricating any environment variable.
    During: a ``.claude`` marker and ``.agent/runtime/flight/vuelo-test/
        session_registry.json`` are written under ``tmp_path`` with the given
        sessions and ``orquestador_activo``.
    After: the temp project root is returned to be used as the event cwd.
    """
    (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)
    flight = tmp_path / ".agent" / "runtime" / "flight" / "vuelo-test"
    flight.mkdir(parents=True, exist_ok=True)
    (flight / "session_registry.json").write_text(
        json.dumps({"sessions": sessions, "orquestador_activo": active_code}),
        encoding="utf-8",
    )
    return tmp_path


def _active_registry_entry() -> dict:
    """Anchor tests on the live active-coordinator entry, never a hardcoded copy.

    Before: the live registry names whichever session is ``orquestador_activo``
        today, so a literal UUID would rot on the next coordinadora relaunch.
    During: the entry with ``code == orquestador_activo`` and
        ``role == "orquestadora"`` is copied out of the live registry.
    After: that mutable-content-independent anchor dict is returned.
    """
    real = _real_registry()
    active = real.get("orquestador_activo")
    for session in real["sessions"]:
        if session.get("code") == active and session.get("role") == "orquestadora":
            return dict(session)
    raise AssertionError("no active orquestadora entry in the live registry")


@needs_live_state
@needs_active_coordinator
def test_m03_control_registry_without_calling_session_stays_silent(tmp_path):
    """DoD control: a located registry lacking the calling session never notices.

    Before: the calling session resolves to the live coordinator thread while
        the located temp registry only knows an unrelated active session.
    During: the full hook runs with payload cwd on the temp project and the
        measured session id, using the real minimal environment.
    After: stdout, stderr and return code stay (0, "", ""): no entry, no notice.
    """
    project = _tmp_project(
        tmp_path,
        [
            {
                "code": "XX-0",
                "role": "orquestadora",
                "threadId": "mcp:00000000-0000-4000-8000-000000000000",
                "status": "ACTIVA (synthetic)",
            }
        ],
        "XX-0",
    )
    result = _run(
        _event(REAL_SESSION_ID, {"prompt": "triaje del backlog"}, cwd=project)
    )
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


@needs_live_state
@pytest.mark.parametrize(
    ("mutation", "fires"),
    [
        pytest.param({}, True, marks=needs_active_coordinator),
        pytest.param({"role": "implantacion"}, False, marks=needs_active_coordinator),
        pytest.param(
            {"status": "SETTLED (superseded)"}, False, marks=needs_active_coordinator
        ),
    ],
)
def test_m03_role_and_status_clauses_via_synthetic_registry(tmp_path, mutation, fires):
    """The active entry's role and ACTIVA border are independent discriminator clauses.

    Before: the anchor entry is copied from the live registry under its real
        ``orquestador_activo`` code, then mutated per case (role mismatch,
        non-ACTIVA status, or unmodified positive control).
    During: the hook resolves the measured calling session to that thread and
        runs the full predicate against the temp registry from payload cwd.
    After: only the unmodified entry notices; role and status mutations stay
        silent with (0, "", "").
    """
    anchor = _active_registry_entry()
    entry = dict(anchor)
    entry.update(mutation)
    project = _tmp_project(tmp_path, [entry], str(anchor["code"]))
    prompt = (
        REPO_ROOT
        / "tests"
        / "fixtures"
        / "pretooluse_triaje_notice"
        / "incident_prompt.txt"
    ).read_text(encoding="utf-8")
    result = _run(_event(REAL_SESSION_ID, {"prompt": prompt}, cwd=project))
    if fires:
        output = _output(result)
        assert "WOT-2026-176e" in output["additionalContext"]
    else:
        assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


@needs_live_state
@needs_active_coordinator
def test_m02_recursive_string_pattern_is_casefolded():
    """The positive pattern may be split across nested keys and values."""
    result = _run(
        _event(
            REAL_SESSION_ID,
            {"TRIAJE": {"nested": ["preparar", {"kind": "TICKETS"}]}},
            "mcp__t3-code__delegate_task",
        )
    )
    assert _output(result)["additionalContext"]
