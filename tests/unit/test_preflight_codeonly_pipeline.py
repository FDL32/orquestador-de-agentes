"""Tests for scripts/preflight_codeonly_pipeline.py warnings taxonomy (WOT-2026-021u).

Covers `classify_warnings`: raw `validate --json` warnings (a dict keyed by CATEGORY --
ticket_prose/bus_drift/invariants) are split into accepted_advisories vs
actionable_warnings. The load-bearing rules (each with a mutation that a test catches):
  - bus_drift/invariants -> accepted ONLY if code_only (a destination with a broken bus
    is NOT advisory);
  - ticket_prose [TP-PROSE-*] -> accepted ONLY if the work_plan is TERMINAL;
  - [TP-FATAL-01] -> ALWAYS actionable (a missing-work_plan signal is never advisory);
  - unknown category / unparseable code -> actionable (fail-closed).
The counts are always derived from the classification, never hardcoded.
"""

from __future__ import annotations

import sys
from pathlib import Path


# scripts/ is not a package: insert it on sys.path as the script itself does.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import preflight_codeonly_pipeline as pcp  # noqa: E402


# The exact 8-warning shape that `validate --json` emits on the motor with a
# COMPLETED work_plan (5 ticket_prose + 1 bus_drift + 2 invariants).
_REAL_WARNINGS = {
    "ticket_prose": [
        "[TP-PROSE-04] extremos-lazy: enumera los elementos concretos",
        "[TP-PROSE-04] extremos-lazy: enumera los elementos concretos",
        "[TP-PROSE-04] extremos-lazy: enumera los elementos concretos",
        "[TP-PROSE-06] non-goals-ausentes: anade una seccion Non-goals",
        "[TP-PROSE-10] decision-arquitectonica-ausente: anade una seccion",
    ],
    "bus_drift": ["No STATE_CHANGED event found in bus for ticket WOT-2026-021i"],
    "invariants": [
        "Cannot verify BUILDER_EXIT for ticket WOT-2026-021i in state COMPLETED",
        "Cannot verify STATE_CHANGED for ticket WOT-2026-021i",
    ],
}

_WP_COMPLETED = (
    "# Plan\n\n## Metadata\n- **ID:** WOT-2026-021i\n- **Estado:** COMPLETED\n"
)
_WP_IN_PROGRESS = (
    "# Plan\n\n## Metadata\n- **ID:** WOT-2026-021i\n- **Estado:** IN_PROGRESS\n"
)


def _counts(result):
    return len(result["accepted_advisories"]), len(result["actionable_warnings"])


# --------------------------------------------------------------------------- #
# Fixture 1: code-only + work_plan COMPLETED + bus absent + TP-PROSE -> all accepted
# --------------------------------------------------------------------------- #
def test_code_only_terminal_plan_all_accepted():
    result = pcp.classify_warnings(
        _REAL_WARNINGS, code_only=True, work_plan_content=_WP_COMPLETED
    )
    accepted, actionable = _counts(result)
    # count is DERIVED from the input, never hardcoded to 8
    total = sum(len(v) for v in _REAL_WARNINGS.values())
    assert accepted == total
    assert actionable == 0
    # every input string is classified into exactly one bucket
    assert accepted + actionable == total


# --------------------------------------------------------------------------- #
# Fixture 2: TP-PROSE on a NON-terminal (IN_PROGRESS) plan -> prose is actionable
# (bus/invariants stay accepted because code_only is still True)
# --------------------------------------------------------------------------- #
def test_prose_on_active_plan_is_actionable():
    result = pcp.classify_warnings(
        _REAL_WARNINGS, code_only=True, work_plan_content=_WP_IN_PROGRESS
    )
    accepted, actionable = _counts(result)
    # 3 bus/invariants accepted; 5 ticket_prose now actionable
    assert actionable == 5
    assert accepted == 3
    assert all("TP-PROSE" in w for w in result["actionable_warnings"])


# --------------------------------------------------------------------------- #
# Fixture 3: TP-FATAL-01 (missing work_plan) -> ALWAYS actionable, never accepted
# --------------------------------------------------------------------------- #
def test_tp_fatal_is_always_actionable():
    warnings = {
        "ticket_prose": [
            "[TP-FATAL-01] work-plan-not-found: asegurate de que work_plan.md existe"
        ],
        "bus_drift": ["No active ticket found for bus drift check"],
        "invariants": ["No active plan for invariant check"],
    }
    # even code_only=True and no work_plan: the FATAL prose must be actionable
    result = pcp.classify_warnings(warnings, code_only=True, work_plan_content=None)
    assert any("TP-FATAL-01" in w for w in result["actionable_warnings"])
    assert not any("TP-FATAL-01" in w for w in result["accepted_advisories"])


def test_tp_fatal_actionable_even_when_plan_is_terminal():
    # ISOLATES the `code == "TP-FATAL-01"` special-case: with a TERMINAL work_plan,
    # a plain TP-PROSE would be accepted, so if the FATAL special-case were removed
    # TP-FATAL-01 would wrongly fall into accepted via the terminal branch. This
    # fixture kills that mutation (the chain meta-audit caught that the
    # work_plan=None fixture alone did NOT -- FATAL fell to actionable via the
    # non-terminal `else`, masking the special-case removal).
    warnings = {
        "ticket_prose": [
            "[TP-FATAL-01] work-plan-not-found: asegurate de que work_plan.md existe"
        ]
    }
    result = pcp.classify_warnings(
        warnings, code_only=True, work_plan_content=_WP_COMPLETED
    )
    assert any("TP-FATAL-01" in w for w in result["actionable_warnings"])
    assert not any("TP-FATAL-01" in w for w in result["accepted_advisories"])


# --------------------------------------------------------------------------- #
# Fixture 4 (synthetic N2): code_only False (destination with a broken bus) ->
# bus_drift/invariants are actionable. In THIS preflight is_motor_code_only is
# always True, so this is a unit test of the classifier LOGIC, not a real flow.
# --------------------------------------------------------------------------- #
def test_bus_warnings_actionable_when_not_code_only():
    result = pcp.classify_warnings(
        _REAL_WARNINGS, code_only=False, work_plan_content=_WP_COMPLETED
    )
    # bus_drift + invariants (3) now actionable; TP-PROSE (5) still accepted (terminal)
    assert all(
        w in result["actionable_warnings"]
        for w in _REAL_WARNINGS["bus_drift"] + _REAL_WARNINGS["invariants"]
    )
    assert len(result["actionable_warnings"]) == 3
    assert len(result["accepted_advisories"]) == 5


# --------------------------------------------------------------------------- #
# Fail-closed: an unknown category is never silently accepted
# --------------------------------------------------------------------------- #
def test_unknown_category_is_actionable():
    warnings = {"deliverable_type": ["some new validator warning we do not know"]}
    result = pcp.classify_warnings(
        warnings, code_only=True, work_plan_content=_WP_COMPLETED
    )
    assert result["accepted_advisories"] == []
    assert len(result["actionable_warnings"]) == 1


# --------------------------------------------------------------------------- #
# No work_plan content -> prose cannot be terminal -> TP-PROSE actionable
# (guards the `work_plan_content is not None` half of plan_is_terminal)
# --------------------------------------------------------------------------- #
def test_prose_actionable_when_no_work_plan_content():
    warnings = {"ticket_prose": ["[TP-PROSE-04] extremos-lazy: ..."]}
    result = pcp.classify_warnings(warnings, code_only=True, work_plan_content=None)
    assert len(result["actionable_warnings"]) == 1
    assert result["accepted_advisories"] == []


# --------------------------------------------------------------------------- #
# ticket_prose WITHOUT a [TP-...] prefix (code is None) -> actionable, never
# silently accepted. Guards the fail-closed `or code is None` branch even when
# the work_plan is terminal (so the terminal path cannot swallow it).
# --------------------------------------------------------------------------- #
def test_prose_without_tp_prefix_is_actionable():
    warnings = {"ticket_prose": ["malformed prose warning with no TP code prefix"]}
    result = pcp.classify_warnings(
        warnings, code_only=True, work_plan_content=_WP_COMPLETED
    )
    assert len(result["actionable_warnings"]) == 1
    assert result["accepted_advisories"] == []


# --------------------------------------------------------------------------- #
# is_completed_plan (extracted to a public function in validate_ticket_prose)
# --------------------------------------------------------------------------- #
def test_is_completed_plan_public_helper():
    from validate_ticket_prose import is_completed_plan

    assert is_completed_plan(_WP_COMPLETED) is True
    assert is_completed_plan(_WP_IN_PROGRESS) is False
    assert is_completed_plan("no metadata here") is False


# --------------------------------------------------------------------------- #
# session_state (WOT-2026-022f): derive_session_state() unit fixtures.
# Consumes the exact schema emitted by `init_session_scratch.py list
# --include-archive` ({"session_id", "record_count", "lock_state", "archived"}).
# --------------------------------------------------------------------------- #
def test_session_state_none_when_no_sessions():
    # empty list -> none. Also covers a session that only has archived/empty
    # entries (never counted as a live signal).
    assert pcp.derive_session_state([]) == "none"
    assert (
        pcp.derive_session_state(
            [
                {
                    "session_id": "a",
                    "record_count": 0,
                    "lock_state": "none",
                    "archived": False,
                }
            ]
        )
        == "none"
    )


def test_session_state_active_when_lock_live():
    sessions = [
        {
            "session_id": "20260716-1200-abc123-aaaa",
            "record_count": 3,
            "lock_state": "live",
            "archived": False,
        }
    ]
    assert pcp.derive_session_state(sessions) == "active"


def test_session_state_stale_when_lock_expired_or_corrupt():
    # lock_state == "stale" (expired expires_at) and lock_state == "none" (no
    # lock file / corrupt+unreadable) on a non-empty, non-archived session both
    # count as reclaimable/stale -- neither is a live session in use.
    stale_expired = [
        {
            "session_id": "20260716-1200-abc123-bbbb",
            "record_count": 2,
            "lock_state": "stale",
            "archived": False,
        }
    ]
    stale_no_lock = [
        {
            "session_id": "20260716-1200-abc123-cccc",
            "record_count": 1,
            "lock_state": "none",
            "archived": False,
        }
    ]
    assert pcp.derive_session_state(stale_expired) == "stale"
    assert pcp.derive_session_state(stale_no_lock) == "stale"


def test_session_state_ignores_archived_sessions():
    # An archived session with a live lock must NOT count toward "active": the
    # aggregate only looks at active (non-archived) sessions.
    sessions = [
        {
            "session_id": "20260716-1200-abc123-dddd",
            "record_count": 5,
            "lock_state": "live",
            "archived": True,
        }
    ]
    assert pcp.derive_session_state(sessions) == "none"


def test_latest_archived_summary_path_picks_max_by_id():
    from pathlib import Path

    from scripts.init_session_scratch import _archive_root

    sessions = [
        {"session_id": "20260710-0900-aaa-1111", "archived": True},
        {"session_id": "20260716-1200-bbb-2222", "archived": True},
        {"session_id": "20260716-1300-ccc-3333", "archived": False},
    ]
    workspace = Path("C:/fake/workspace")
    result = pcp._latest_archived_summary_path(workspace, sessions)
    assert result == str(_archive_root(workspace) / "20260716-1200-bbb-2222")


def test_latest_archived_summary_path_none_when_no_archived():
    from pathlib import Path

    assert pcp._latest_archived_summary_path(Path("C:/fake"), []) is None


# --------------------------------------------------------------------------- #
# EJE fixture: the session lives in a repo DISTINCT from the motor, and the
# preflight FINDS it via --workspace-root (not --dev-root). Without this fixture
# the check is blind to the structural leak described in the ticket contract:
# looking for the session in the motor would report `none` unconditionally.
# --------------------------------------------------------------------------- #
class TestSessionStateEjeWorkspaceRoot:
    def test_session_found_in_workspace_root_not_motor(self, tmp_path):
        import subprocess
        import uuid
        from datetime import datetime, timezone

        motor_root = Path(__file__).resolve().parent.parent.parent
        init_script = motor_root / "scripts" / "init_session_scratch.py"

        # workspace repo, DISTINCT from the motor, with its own .agent/
        workspace = tmp_path / "workspace_repo"
        workspace.mkdir()
        (workspace / ".agent").mkdir()
        subprocess.run(
            ["git", "init"], cwd=str(workspace), capture_output=True, timeout=10
        )

        now = datetime.now(timezone.utc)
        sid = f"{now.strftime('%Y%m%d-%H%M')}-nogit-{uuid.uuid4().hex[:8]}"

        init_res = subprocess.run(
            [
                sys.executable,
                str(init_script),
                "--project-root",
                str(workspace),
                "init",
                "--session-id",
                sid,
                "--generator",
                "eje_test",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert init_res.returncode == 0, init_res.stderr

        add_res = subprocess.run(
            [
                sys.executable,
                str(init_script),
                "--project-root",
                str(workspace),
                "add",
                "--session-id",
                sid,
                "--event",
                "artifact_added",
                "--generator",
                "eje_test",
                "--artifact-path",
                "artifact.txt",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert add_res.returncode == 0, add_res.stderr

        # Sanity: the session must NOT exist under the motor's own session dir.
        motor_session_dir = motor_root / ".agent" / "runtime" / "session" / sid
        assert not motor_session_dir.exists()

        findings: dict = {"checks": {}, "automatic_criticals": []}
        args = type("Args", (), {})()
        pcp._check_session_state(findings, args, motor_root, workspace)

        check = findings["checks"]["session_state"]
        assert check["root_source"] == "workspace"
        assert check["session_state"] == "active", check
        assert check["session_count"] >= 1


# --------------------------------------------------------------------------- #
# End-to-end `stale` fixture (real subprocess through `init_session_scratch.py
# list`), the one the TTL mutation must break. Writes an EXPIRED lock.json
# directly (expires_at in the past) on top of a real session with records, then
# asserts _check_session_state reports "stale" via the real entry point.
# --------------------------------------------------------------------------- #
class TestSessionStateEjeStaleLock:
    def test_session_state_stale_end_to_end(self, tmp_path):
        import json as _json
        import subprocess
        import uuid
        from datetime import datetime, timedelta, timezone

        motor_root = Path(__file__).resolve().parent.parent.parent
        init_script = motor_root / "scripts" / "init_session_scratch.py"

        workspace = tmp_path / "workspace_repo_stale"
        workspace.mkdir()
        (workspace / ".agent").mkdir()
        subprocess.run(
            ["git", "init"], cwd=str(workspace), capture_output=True, timeout=10
        )

        now = datetime.now(timezone.utc)
        sid = f"{now.strftime('%Y%m%d-%H%M')}-nogit-{uuid.uuid4().hex[:8]}"

        init_res = subprocess.run(
            [
                sys.executable,
                str(init_script),
                "--project-root",
                str(workspace),
                "init",
                "--session-id",
                sid,
                "--generator",
                "eje_stale_test",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert init_res.returncode == 0, init_res.stderr

        add_res = subprocess.run(
            [
                sys.executable,
                str(init_script),
                "--project-root",
                str(workspace),
                "add",
                "--session-id",
                sid,
                "--event",
                "artifact_added",
                "--generator",
                "eje_stale_test",
                "--artifact-path",
                "artifact.txt",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert add_res.returncode == 0, add_res.stderr

        # Overwrite lock.json with an EXPIRED expires_at (foreign pid, past TTL).
        session_dir = workspace / ".agent" / "runtime" / "session" / sid
        lock_path = session_dir / "lock.json"
        expired = {
            "pid": 999999,
            "session_id": sid,
            "op": "init",
            "created_at": (now - timedelta(seconds=2000)).isoformat(),
            "expires_at": (now - timedelta(seconds=100)).isoformat(),
        }
        lock_path.write_text(_json.dumps(expired), encoding="utf-8")

        findings: dict = {"checks": {}, "automatic_criticals": []}
        args = type("Args", (), {})()
        pcp._check_session_state(findings, args, motor_root, workspace)

        check = findings["checks"]["session_state"]
        assert check["session_state"] == "stale", check


# --------------------------------------------------------------------------- #
# WOT-2026-025r: mode barrier. The commit-directo (code-only) preflight must
# run with is_motor_code_only() == True. AGENT_PROJECT_ROOT pointing at a
# workspace INVERTS the mode (destino/bus) and empties the canonical suite
# (measured 2026-07-16: run_pytest_safe against the workspace's empty tests/
# -> exit 5, "Ran 0 tests" -- a textbook false-green baseline). Live red leg
# reproduced at HEAD d02218d: env->workspace, is_motor_code_only()=False and
# the collector still returned exit 0 with "no automatic criticals".
# Mutation each test names: remove the _check_mode call from collect() (or
# the critical append) -> the corresponding test flips RED.
# --------------------------------------------------------------------------- #


def test_mode_env_contradiction_is_automatic_critical(monkeypatch):
    """Destino mode (is_motor_code_only False) -> checks.mode recorded AND
    the automatic critical `mode_env_contradiction` present (exit 1 path)."""
    monkeypatch.setattr(pcp, "is_motor_code_only", lambda: False)
    monkeypatch.setenv("AGENT_PROJECT_ROOT", "X:/some/workspace")

    findings: dict = {"checks": {}, "automatic_criticals": []}
    pcp._check_mode(findings)

    mode = findings["checks"]["mode"]
    assert mode["is_motor_code_only"] is False
    assert mode["agent_project_root"] == "X:/some/workspace"
    assert "mode_env_contradiction" in findings["automatic_criticals"]


def test_mode_code_only_true_is_clean(monkeypatch):
    """Code-only mode (the correct config: env UNSET) -> mode check recorded,
    NO critical appended."""
    monkeypatch.setattr(pcp, "is_motor_code_only", lambda: True)
    monkeypatch.delenv("AGENT_PROJECT_ROOT", raising=False)

    findings: dict = {"checks": {}, "automatic_criticals": []}
    pcp._check_mode(findings)

    mode = findings["checks"]["mode"]
    assert mode["is_motor_code_only"] is True
    assert mode["agent_project_root"] is None
    assert findings["automatic_criticals"] == []


def test_collect_wires_mode_check(monkeypatch, tmp_path):
    """WIRING: collect() itself must invoke the mode barrier (a check nobody
    calls is a norm, not a barrier). Heavy sibling checks are stubbed to
    no-ops; is_motor_code_only patched to False; the critical must surface in
    collect()'s own findings. Mutation: drop the _check_mode call from
    collect() -> RED (the unit tests above stay green, this one flips)."""
    monkeypatch.setattr(pcp, "is_motor_code_only", lambda: False)
    for heavy in (
        "_check_shas",
        "_check_validate",
        "_check_session_state",
        "_check_topology",
        "_check_consumers",
    ):
        monkeypatch.setattr(pcp, heavy, lambda *a, **k: None)
    (tmp_path / ".git").mkdir()  # collect() requires a git-looking dev root

    args = type(
        "Args",
        (),
        {
            "dev_root": str(tmp_path),
            "principal_root": None,
            "workspace_root": None,
            "ticket": "WOT-2026-025r",
            "retire_token": None,
            "retire_owner": None,
            "expect_dev_sha": None,
            "expect_principal_sha": None,
            "expect_workspace_sha": None,
        },
    )()
    findings = pcp.collect(args)

    assert "mode" in findings["checks"], "collect() must wire _check_mode"
    assert "mode_env_contradiction" in findings["automatic_criticals"]


# --------------------------------------------------------------------------- #
# WOT-2026-026e / T-026E-001 criterion (i): RUTA PRODUCTIVA. The preflight's
# OWN productive path (collect(), unmocked) must SURFACE the agents_accessible
# signal when run against the REAL motor config -- never an injected/mocked
# profile set. This is DISTINCT from criterion (h) (which is tested via
# check_guard_wiring.py and only proves the IMPORT is wired): mutating away the
# INVOCATION `_check_agents_accessible(findings, dev)` inside `collect()` while
# leaving the import untouched leaves check_guard_wiring GREEN (an import is
# still evidence of wiring) but makes the signal vanish from THIS test's
# output -- which is exactly the "import-only, dead" false-green the frozen
# contract calls out.
# --------------------------------------------------------------------------- #
class TestAgentsAccessibleWiredInPreflight:
    def test_agents_accessible_signal_emitted_by_real_preflight(self):
        motor_root = Path(__file__).resolve().parent.parent.parent
        args = type(
            "Args",
            (),
            {
                "dev_root": str(motor_root),
                "principal_root": None,
                "workspace_root": None,
                "ticket": "WOT-2026-026e",
                "retire_token": None,
                "retire_owner": None,
                "expect_dev_sha": None,
                "expect_principal_sha": None,
                "expect_workspace_sha": None,
            },
        )()

        findings = pcp.collect(args)

        assert "agents_accessible" in findings["checks"], (
            "collect() must wire _check_agents_accessible -- the signal is "
            "missing from the real preflight's own output"
        )
        signal = findings["checks"]["agents_accessible"]
        assert "error" not in signal, signal.get("error")
        # STRUCTURE only, NEVER a hardcoded profile COUNT (criterion (k): 025z
        # can add/remove ensemble_profiles without invalidating this test).
        assert signal["n_total"] > 0
        assert signal["n_total"] == signal["n_checked"] + signal["n_excluded"]
        real_profile_names = set(
            pcp.load_agents_config(project_root=motor_root)["ensemble_profiles"]
        )
        assert signal["profiles"], (
            "must contain REAL profiles read from the motor's own agents.json, "
            "not an injected/mocked set"
        )
        assert set(signal["profiles"]) <= real_profile_names
