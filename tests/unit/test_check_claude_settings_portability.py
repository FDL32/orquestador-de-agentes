"""Tests for the Claude settings portability/security gate (WOT-2026-003c).

Fleet-mode tests (WOT-2026-024f-A) build their fixtures under
``conftest.REAL_SYSTEM_TEMP`` (a real system-temp dir OUTSIDE the repo tree),
not under the repo-rooted ``tmp_path``: fleet discovery walks parent(motor_root)
and resolves paths by walking up, so a fixture inside the repo tree would
pollute that walk-up. Each fixture cleans up after itself.
"""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.conftest import REAL_SYSTEM_TEMP


_ROOT = Path(__file__).resolve().parent.parent.parent
# Import the gate module from scripts/ and the canonical entrypoint.
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / ".agent" / "hooks"))

import check_claude_settings_portability as gate  # noqa: E402
import claude_guard_entry  # noqa: E402


_CANONICAL = claude_guard_entry.canonical_hook_command()
_NON_CANONICAL = 'python -c "import sys; sys.exit(2)"'


@pytest.fixture
def fleet_root() -> Iterator[Path]:
    """A hermetic parent dir OUTSIDE the repo tree for fleet fixtures.

    Returns the parent under which a ``motor`` dir and destination siblings are
    created. Built under ``REAL_SYSTEM_TEMP`` so ``_discover_destinations``'s
    ``.resolve()`` walk-up never reaches the real motor repo.
    """
    root = REAL_SYSTEM_TEMP / f"fleet_024f_{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _make_link(
    dest_dir: Path,
    *,
    destination_root: str | None = None,
    motor_root: str | None = None,
) -> None:
    """Write a motor_destination_link.json under ``dest_dir/.agent/config/``."""
    cfg = dest_dir / ".agent" / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    payload: dict[str, str] = {}
    if destination_root is not None:
        payload["destination_root"] = destination_root
    if motor_root is not None:
        payload["motor_root"] = motor_root
    (cfg / "motor_destination_link.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _make_settings(dest_dir: Path, command: str = _CANONICAL) -> None:
    """Write a .claude/settings.json with a write-gating hook ``command``."""
    claude = dest_dir / ".claude"
    claude.mkdir(parents=True, exist_ok=True)
    (claude / "settings.json").write_text(json.dumps(_settings(command)), "utf-8")


def _settings(command: str = _CANONICAL, matcher: str = "Write|Edit|MultiEdit") -> dict:
    """Un settings CANONICO minimo.

    WOT-2026-057b: incluye los dos hooks de CONTEXTO ademas del write guard.
    Antes solo traia `PreToolUse`, y ese fixture describia como "limpio" una
    configuracion que deja al repo sin memoria por ningun canal -- justo el
    estado del destino real, que este mismo guard aprobaba con rc=0. Un fixture
    que no distingue el defecto del correcto no puede cazarlo.
    """
    return {
        "hooks": {
            "PreToolUse": [
                {"matcher": matcher, "hooks": [{"type": "command", "command": command}]}
            ],
            "SessionStart": [
                {
                    "matcher": "",
                    "hooks": [
                        {
                            "type": "command",
                            "command": gate.claude_guard_entry.canonical_command_for(
                                "session_start_hook.py", "agent_hooks"
                            ),
                        }
                    ],
                }
            ],
            "PreCompact": [
                {
                    "matcher": "",
                    "hooks": [
                        {
                            "type": "command",
                            "command": gate.claude_guard_entry.canonical_command_for(
                                "pre_compact_hook.py", "agent_hooks"
                            ),
                        }
                    ],
                }
            ],
        }
    }


class TestPersonalGrants:
    def test_permissions_allow_flagged(self):
        violations = gate.check_no_personal_grants(
            {"permissions": {"allow": ["Bash(rm:*)"]}}
        )
        assert any("permissions.allow" in v for v in violations)

    def test_no_permissions_is_clean(self):
        assert gate.check_no_personal_grants(_settings()) == []


class TestWriteGuardPresent:
    def test_missing_pretooluse_is_flagged(self):
        violations = gate.check_write_guard_present({"hooks": {}})
        assert violations and "no PreToolUse hook gates writes" in violations[0]

    def test_read_only_matcher_is_flagged(self):
        # A guard that only matches Read does not cover writes.
        violations = gate.check_write_guard_present(_settings(matcher="Read"))
        assert violations and "no PreToolUse hook gates writes" in violations[0]

    def test_partial_matcher_is_flagged(self):
        # Covers Write but not Edit/MultiEdit.
        violations = gate.check_write_guard_present(_settings(matcher="Write"))
        assert violations and "does not cover" in violations[0]
        assert "Edit" in violations[0] and "MultiEdit" in violations[0]

    def test_full_matcher_passes(self):
        assert gate.check_write_guard_present(_settings()) == []


class TestCommandCanonical:
    def test_non_canonical_command_flagged(self):
        violations = gate.check_command_is_canonical(_settings(command=_NON_CANONICAL))
        assert violations and "canonical" in violations[0]

    def test_canonical_command_passes(self):
        assert gate.check_command_is_canonical(_settings()) == []


class TestEntrypointFailsClosed:
    def test_real_entrypoint_fails_closed(self):
        # The shipped claude_guard_entry.py must fail closed with no guard.
        assert gate.check_entrypoint_fails_closed() == []


class TestFileAndMain:
    def test_clean_canonical_file_returns_zero(self, tmp_path: Path):
        p = tmp_path / "settings.json"
        p.write_text(json.dumps(_settings()), encoding="utf-8")
        assert gate.check_settings_file(p) == []
        assert gate.main([str(p)]) == 0

    def test_dirty_file_returns_one(self, tmp_path: Path):
        p = tmp_path / "settings.json"
        bad = _settings(command=_NON_CANONICAL, matcher="Write")
        bad["permissions"] = {"allow": ["Bash(python3:*)"]}
        p.write_text(json.dumps(bad), encoding="utf-8")
        violations = gate.check_settings_file(p)
        assert any("permissions.allow" in v for v in violations)
        assert any("does not cover" in v for v in violations)
        assert any("canonical" in v for v in violations)
        assert gate.main([str(p)]) == 1

    def test_missing_file_is_clean(self, tmp_path: Path):
        assert gate.check_settings_file(tmp_path / "nope.json") == []

    def test_dir_argument_resolves_claude_settings(self, tmp_path: Path):
        claude = tmp_path / ".claude"
        claude.mkdir()
        (claude / "settings.json").write_text(json.dumps(_settings()), encoding="utf-8")
        assert gate.main([str(tmp_path)]) == 0

    def test_real_motor_settings_pass(self):
        # The motor's own tracked settings must satisfy its own gate.
        assert gate.check_settings_file(_ROOT / ".claude" / "settings.json") == []


class TestFleetMode:
    # --- DoD-1: no silent skip; census invariant -------------------------
    def test_discover_destinations_finds_destinations(self, fleet_root: Path):
        """Two distinct external destinations are both INCLUDED."""
        motor = fleet_root / "motor"
        motor.mkdir()
        dest1 = fleet_root / "dest_one"
        dest1.mkdir()
        _make_link(dest1, destination_root=str(dest1))
        dest2 = fleet_root / "dest_two"
        dest2.mkdir()
        _make_link(dest2, destination_root=str(dest2))

        result = gate._discover_destinations(motor)
        assert sorted(p.name for p in result.included) == ["dest_one", "dest_two"]
        # Census invariant: nothing dropped silently.
        assert (
            len(result.included)
            + len(result.skipped)
            + len(result.excluded)
            + len(result.deduped)
            == result.links_total
        )

    def test_discover_destinations_skips_missing_link(self, fleet_root: Path):
        """A dir without motor_destination_link.json is not a destination."""
        motor = fleet_root / "motor"
        motor.mkdir()
        (fleet_root / "not_a_dest").mkdir()
        result = gate._discover_destinations(motor)
        assert result.included == []
        assert result.links_total == 0

    def test_discover_destinations_no_destination_root_is_skipped(
        self, fleet_root: Path
    ):
        """DoD-1: a link WITHOUT destination_root is SKIPPED with reason, not dropped.

        Mutation intent: removing destination_root from a link must make it
        surface in the SKIPPED list and drive --fleet non-zero, never vanish.
        """
        motor = fleet_root / "motor"
        motor.mkdir()
        dest = fleet_root / "dest_incomplete"
        dest.mkdir()
        _make_link(dest)  # no destination_root

        result = gate._discover_destinations(motor)
        assert dest.name not in [p.name for p in result.included]
        skipped_names = [name for name, _reason in result.skipped]
        assert dest.name in skipped_names
        assert result.links_total == 1
        # Census invariant holds even with a skip.
        assert (
            len(result.included)
            + len(result.skipped)
            + len(result.excluded)
            + len(result.deduped)
            == result.links_total
        )
        # And --fleet is non-zero when there is an unresolved skip.
        report = gate.fleet_check(motor)
        assert gate._report_fleet(report) == 1

    # --- DoD-2: published denominator; inspected==0 is RED ---------------
    def test_fleet_inspected_zero_is_red(self, fleet_root: Path, capsys):
        """DoD-2: no inspectable destination -> RED (non-zero), denominator printed."""
        motor = fleet_root / "motor"
        motor.mkdir()
        report = gate.fleet_check(motor)
        assert gate._report_fleet(report) == 1
        out = capsys.readouterr().out
        assert "denominator" in out
        assert "inspected=0" in out

    def test_fleet_check_no_settings_flagged(self, fleet_root: Path):
        """A destination without .claude/settings.json is reported as sin_settings."""
        motor = fleet_root / "motor"
        motor.mkdir()
        dest = fleet_root / "dest"
        dest.mkdir()
        _make_link(dest, destination_root=str(dest))

        report = gate.fleet_check(motor)
        assert dest.name in report.sin_settings

    def test_fleet_check_canonical_ok(self, fleet_root: Path):
        """DoD-6: a destination with the REAL canonical command + resolvable hook.

        The fixture uses the UNMODIFIED return of canonical_hook_command() (not a
        synthetic canonical). A correct canonical destination must NOT be flagged.
        The external dest declares an UPSTREAM motor (not the fleet's own motor),
        so the identity-based exclusion does not remove it.
        """
        motor = fleet_root / "motor"
        motor.mkdir()
        # Upstream motor the external dest points at (NOT the fleet's own motor).
        upstream = fleet_root / "upstream_motor"
        (upstream / ".agent" / "hooks").mkdir(parents=True)
        (upstream / ".agent" / "hooks" / "claude_guard_entry.py").write_text(
            "", "utf-8"
        )

        dest = fleet_root / "dest"
        dest.mkdir()
        _make_link(dest, destination_root=str(dest), motor_root=str(upstream))
        _make_settings(dest, command=_CANONICAL)  # REAL canonical

        report = gate.fleet_check(motor)
        assert dest.name not in report.sin_settings
        assert dest.name in report.inspected
        # No missing-hook flag: canonical + entry resolvable via motor link.
        assert all(name != dest.name for name, _ in report.missing_hook)

    def test_fleet_empty_when_no_destinations(self, fleet_root: Path):
        """No destinations = empty inspection with a published (zero) denominator."""
        motor = fleet_root / "motor"
        motor.mkdir()
        report = gate.fleet_check(motor)
        assert report.violations == []
        assert report.sin_settings == []
        assert report.missing_hook == []
        assert report.inspected == []
        assert report.discovery.included == []

    # --- DoD-3: dedupe BEFORE exclusion ---------------------------------
    def test_dedupe_before_exclusion_alias_counts_once(self, fleet_root: Path):
        """DoD-3: two links resolving to the same root count ONCE.

        Mutation intent: two links to the same destination_root -> INCLUDED once,
        not twice.
        """
        motor = fleet_root / "motor"
        motor.mkdir()
        dest = fleet_root / "shared_dest"
        dest.mkdir()
        alias_a = fleet_root / "alias_a"
        alias_a.mkdir()
        alias_b = fleet_root / "alias_b"
        alias_b.mkdir()
        _make_link(alias_a, destination_root=str(dest))
        _make_link(alias_b, destination_root=str(dest))

        result = gate._discover_destinations(motor)
        resolved_included = [p for p in result.included if p == dest.resolve()]
        assert len(resolved_included) == 1
        assert result.links_total == 2
        # The collapsed alias is accounted for (not silently dropped).
        assert len(result.deduped) == 1
        assert (
            len(result.included)
            + len(result.skipped)
            + len(result.excluded)
            + len(result.deduped)
            == result.links_total
        )

    def test_dogfooding_workspace_excluded_by_motor_root_identity(
        self, fleet_root: Path
    ):
        """DoD-3: THIS motor's dogfooding is excluded by motor_root IDENTITY.

        The excluded workspace is identified by its link's ``motor_root``
        resolving to the running motor -- a resolved-topology FACT in the data --
        NOT by any directory-name convention. Deliberately, the workspace here
        has a NON-conventional name (no ``_workspace`` suffix) to prove the
        exclusion does not key off spelling. The motor root itself is also
        excluded.
        """
        motor = fleet_root / "the_motor"
        motor.mkdir()
        upstream = fleet_root / "upstream_motor"
        upstream.mkdir()
        # Dogfooding workspace of THIS motor, NON-conventionally named. ONLY its
        # own link declares motor_root == this motor -> must be EXCLUDED.
        workspace = fleet_root / "zzz_dogfood_area"
        workspace.mkdir()
        _make_link(workspace, destination_root=str(workspace), motor_root=str(motor))
        # The principal's alias link ALSO resolves to the workspace but declares
        # an UPSTREAM motor_root, and sorts BEFORE the workspace's own dir
        # ("aaa_" < "zzz_"). It therefore wins the dedupe naming slot and would
        # MASK the this-motor identity if the signal were not OR-ed per path.
        alias = fleet_root / "aaa_principal_alias"
        alias.mkdir()
        _make_link(alias, destination_root=str(workspace), motor_root=str(upstream))
        # A link resolving to the motor itself -> excluded (motor is not a dest).
        motor_alias = fleet_root / "motor_alias"
        motor_alias.mkdir()
        _make_link(motor_alias, destination_root=str(motor), motor_root=str(upstream))
        # A genuine external destination whose motor_root points ELSEWHERE.
        ext = fleet_root / "external_dest"
        ext.mkdir()
        _make_link(ext, destination_root=str(ext), motor_root=str(upstream))

        result = gate._discover_destinations(motor)
        included = result.included
        excluded_paths = [path for _name, path in result.excluded]
        # Dogfooding workspace and the motor itself are excluded by identity.
        assert workspace.resolve() not in included
        assert str(workspace.resolve()) in excluded_paths
        assert motor.resolve() not in included
        assert str(motor.resolve()) in excluded_paths
        # The external destination survives.
        assert ext.resolve() in included

    def test_conventionally_named_but_foreign_dest_is_included(self, fleet_root: Path):
        """Anti-heuristic: a ``foo_dev`` / ``*_workspace`` dir whose motor_root points
        ELSEWHERE must be INCLUDED (proves the name heuristic is gone).

        A prior implementation excluded by stripping ``_dev`` / appending
        ``_workspace`` on the motor name; that would WRONGLY drop these external
        repos. The identity rule keys off motor_root, so they are external.
        """
        motor = fleet_root / "acme"
        motor.mkdir()
        upstream = fleet_root / "some_other_motor"
        upstream.mkdir()
        # Named like the old heuristic's targets, but foreign (motor_root != motor).
        looks_like_dev = fleet_root / "acme_dev"
        looks_like_dev.mkdir()
        _make_link(
            looks_like_dev,
            destination_root=str(looks_like_dev),
            motor_root=str(upstream),
        )
        looks_like_ws = fleet_root / "acme_workspace"
        looks_like_ws.mkdir()
        _make_link(
            looks_like_ws, destination_root=str(looks_like_ws), motor_root=str(upstream)
        )

        result = gate._discover_destinations(motor)
        assert looks_like_dev.resolve() in result.included
        assert looks_like_ws.resolve() in result.included
        assert result.excluded == []

    # --- DoD-4: real hook, 3 CLOSED classes -----------------------------
    def test_classify_canonical_by_equality(self, fleet_root: Path):
        """DoD-4/DoD-6: the canonical class is EQUALITY to the REAL canonical."""
        dest = fleet_root / "d"
        dest.mkdir()
        cls, path = gate.classify_hook_command(_CANONICAL, dest)
        assert cls == gate.CLASS_CANONICAL
        assert path is None

    def test_classify_python_path_relative_to_dest(self, fleet_root: Path):
        """DoD-4: `python <ruta>.py` is parsed and resolved relative to dest_root."""
        dest = fleet_root / "d"
        dest.mkdir()
        cls, path = gate.classify_hook_command(
            "python .agent/hooks/guard_paths.py", dest
        )
        assert cls == gate.CLASS_PYTHON_PATH
        assert path == dest / ".agent" / "hooks" / "guard_paths.py"

    def test_classify_unparseable(self, fleet_root: Path):
        """DoD-4: neither canonical nor python-path -> noncanonical_unparseable."""
        dest = fleet_root / "d"
        dest.mkdir()
        cls, path = gate.classify_hook_command("bash -c 'echo hi'", dest)
        assert cls == gate.CLASS_UNPARSEABLE
        assert path is None

    def test_upscaler_missing_referenced_py_is_flagged(self, fleet_root: Path):
        """DoD-4: a command referencing a NON-EXISTENT .py is flagged missing.

        Upscaler case: `python .agent/hooks/guard_paths.py` with the file absent.
        `0 missing hook files` must be impossible while this destination exists.
        """
        dest = fleet_root / "upscaler"
        dest.mkdir()
        # No guard_paths.py file created.
        violations = gate.check_hook_file_exists(
            dest, "python .agent/hooks/guard_paths.py"
        )
        assert violations != []
        assert "does not exist" in violations[0]

    def test_python_path_present_py_is_clean(self, fleet_root: Path):
        """DoD-4: `python <ruta>.py` whose file EXISTS -> no missing-hook flag."""
        dest = fleet_root / "ok"
        (dest / ".agent" / "hooks").mkdir(parents=True)
        (dest / ".agent" / "hooks" / "guard_paths.py").write_text("", "utf-8")
        assert (
            gate.check_hook_file_exists(dest, "python .agent/hooks/guard_paths.py")
            == []
        )

    def test_fleet_missing_hook_surfaces_in_report(self, fleet_root: Path):
        """DoD-4 end-to-end: an Upscaler-like destination drives missing_hook + non-zero.

        The dest points at an UPSTREAM motor (not the fleet's own motor) so it is
        counted as external, not excluded as this motor's dogfooding.
        """
        motor = fleet_root / "motor"
        motor.mkdir()
        upstream = fleet_root / "upstream_motor"
        upstream.mkdir()
        dest = fleet_root / "upscaler"
        dest.mkdir()
        _make_link(dest, destination_root=str(dest), motor_root=str(upstream))
        _make_settings(dest, command="python .agent/hooks/guard_paths.py")

        report = gate.fleet_check(motor)
        assert any(name == dest.name for name, _ in report.missing_hook)
        assert gate._report_fleet(report) == 1

    # --- Adapted signature tests (check_hook_file_exists now takes command) ---
    def test_check_hook_file_canonical_local_exists(self, fleet_root: Path):
        """Canonical command + local claude_guard_entry.py present = clean."""
        dest = fleet_root / "d"
        (dest / ".agent" / "hooks").mkdir(parents=True)
        (dest / ".agent" / "hooks" / "claude_guard_entry.py").write_text("", "utf-8")
        assert gate.check_hook_file_exists(dest, _CANONICAL) == []

    def test_check_hook_file_canonical_missing_local(self, fleet_root: Path):
        """Canonical command, no local hook and no motor link = violation."""
        dest = fleet_root / "d"
        dest.mkdir()
        assert gate.check_hook_file_exists(dest, _CANONICAL) != []

    def test_check_hook_file_canonical_resolved_via_motor_link(self, fleet_root: Path):
        """REFRAMED: the remote branch is CORRECT for the CANONICAL command.

        The motor-link resolution of claude_guard_entry.py is valid only for the
        canonical class; here the command IS canonical, so it is clean.
        """
        motor = fleet_root / "motor"
        (motor / ".agent" / "hooks").mkdir(parents=True)
        (motor / ".agent" / "hooks" / "claude_guard_entry.py").write_text("", "utf-8")
        dest = fleet_root / "d"
        _make_link(dest, motor_root=str(motor))
        assert gate.check_hook_file_exists(dest, _CANONICAL) == []


# ---------------------------------------------------------------------------
# WOT-2026-042d -- the five muted hooks
#
# DELIVERABLE tests for invariants (a)(b)(c)(d). The 13 tests above are
# NO-REGRESSION (PreToolUse + permissions) and must stay green.
#
# BINDING (flight plan, "EXIGENCIA DE RUTA REAL"): an assertion over the TEXT of
# settings.json does NOT satisfy (a) or (b). ``assert 'cands=[' not in text``
# passes without proving anything -- it cannot tell a fixed hook from a DELETED
# one. So (b), and one test of (a), LAUNCH THE REAL WRAPPER by subprocess with
# its target absent and assert exit != 0 plus a stderr diagnostic.
#
# BINDING (flight plan, "AISLAMIENTO OBLIGATORIO"): every test that launches a
# wrapper runs in a TEMPORARY tree with its own .claude/ and .agent/ and writes
# NOTHING outside it -- these hooks persist state (observations.jsonl). If a
# wrapper resolved to the real motor during a test, the TEST is wrong.
# ---------------------------------------------------------------------------

_MOTOR_SETTINGS = _ROOT / ".claude" / "settings.json"
_HOOK_PAYLOAD = (
    b'{"tool_name":"Read","session_id":"t","result":{"filePath":"x","content":"a"}}'
)


def _sandbox_tree(root: Path) -> Path:
    """A self-contained repo-like tree with its own ``.claude`` marker.

    The marker stops the wrappers' walk-up HERE, so nothing resolves out to the
    real motor and writes into the real runtime.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / ".claude").mkdir(exist_ok=True)
    (root / ".agent" / "hooks").mkdir(parents=True, exist_ok=True)
    return root


def _run_hook_command(command: str, cwd: Path) -> subprocess.CompletedProcess:
    """Launch a settings.json hook command for real, in a sandboxed cwd.

    Executes the exact ``python -c "<code>"`` payload from settings.json, so it
    exercises the SAME resolution path production takes rather than a
    reimplementation of it.
    """
    return subprocess.run(
        [sys.executable, "-c", shlex.split(command)[-1]],
        input=_HOOK_PAYLOAD,
        cwd=str(cwd),
        capture_output=True,
        timeout=60,
    )


def _motor_commands() -> dict[str, str]:
    """Tracked motor settings commands, keyed ``event::matcher``."""
    data = json.loads(_MOTOR_SETTINGS.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for event, entries in data["hooks"].items():
        for entry in entries:
            for hook in entry["hooks"]:
                out[f"{event}::{entry.get('matcher', '')}"] = hook["command"]
    return out


@pytest.fixture
def sandbox(fleet_root: Path) -> Path:
    """A hermetic tree OUTSIDE the repo; ``fleet_root`` cleans it up."""
    return _sandbox_tree(fleet_root / "sandbox")


class TestInvariantAResolution:
    """(a) No hook command resolves the motor by a GUESSED directory name."""

    def test_no_command_guesses_a_directory_name(self):
        """Cheap canary, deliberately NOT the evidence for (a).

        The real evidence is ``test_wrapper_resolves_target_in_sandbox``, which
        runs the path instead of reading it.
        """
        for key, cmd in _motor_commands().items():
            assert "cands=[" not in cmd, f"{key} still guesses directory names"

    def test_wrapper_resolves_target_in_sandbox(self, sandbox: Path):
        """RUNS the real command: with the target PRESENT it must reach it.

        Distinguishes a fixed hook from a deleted one, which a text assertion
        cannot. The stub writes a marker, so success is proven by an ARTIFACT --
        a muted hook also exits 0.
        """
        marker = sandbox / "reached.txt"
        stub = sandbox / ".agent" / "hooks" / "native_post_tool_hook.py"
        stub.write_text(
            "from pathlib import Path\n"
            f"Path(r'{marker}').write_text('reached', encoding='utf-8')\n",
            encoding="utf-8",
        )
        result = _run_hook_command(
            _motor_commands()["PostToolUse::Read|Grep|Glob|WebFetch"], sandbox
        )
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        assert marker.read_text(encoding="utf-8") == "reached"


class TestInvariantBFailsClosed:
    """(b) With no resolvable target, a hook exits != 0 with a diagnostic.

    The invariant the flight plan singles out: its evidence MUST be a real
    wrapper launch. Before the fix every one of these exited 0 silently, so
    this class is a barrier that could not have existed before.
    """

    @pytest.mark.parametrize(
        "key",
        [
            "PostToolUse::Read|Grep|Glob|WebFetch",
            "PostToolUse::Write|Edit|MultiEdit",
            "PreCompact::",
            "Stop::",
            "SubagentStop::",
        ],
    )
    def test_missing_target_exits_nonzero_with_stderr(self, key: str, sandbox: Path):
        """Target ABSENT in the sandbox -> exit != 0 AND a stderr diagnostic."""
        result = _run_hook_command(_motor_commands()[key], sandbox)
        assert result.returncode != 0, (
            f"{key} exited 0 with no resolvable target: the silent fail-green "
            "that WOT-2026-042d removes"
        )
        stderr = result.stderr.decode(errors="replace")
        assert "HOOK INACTIVE" in stderr, f"{key} failed mute: {stderr!r}"

    def test_failing_hooks_write_no_runtime_state(self, sandbox: Path):
        """Counterpart of demanding the real path: these wrappers persist state."""
        for key, cmd in _motor_commands().items():
            if not key.startswith("PreToolUse"):
                _run_hook_command(cmd, sandbox)
        assert not (sandbox / ".agent" / "runtime").exists(), (
            "a failing hook must not create runtime state"
        )


class TestInvariantCPayloadArrives:
    """(c) native_post_tool_hook reaches post_tool_hook without ImportError."""

    def test_payload_reaches_post_tool_hook_and_writes_observation(
        self, fleet_root: Path
    ):
        """Runs the REAL wrapper and asserts the ARTIFACT it must produce.

        Evidence is a record with ``source: post_tool_hook``: of the 73 (motor)
        / 64 (destino) records in observations.jsonl, ZERO had that source
        before this fix -- all were manual promotions. Exit 0 alone proves
        nothing here, because the OLD code also exited 0.
        """
        cwd = _sandbox_tree(fleet_root / "payload")
        result = subprocess.run(
            [
                sys.executable,
                str(_ROOT / ".agent" / "hooks" / "native_post_tool_hook.py"),
            ],
            input=_HOOK_PAYLOAD,
            cwd=str(cwd),
            capture_output=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        written = cwd / ".agent" / "runtime" / "memory" / "observations.jsonl"
        assert written.exists(), (
            "the payload never reached post_tool_hook: the ImportError branch "
            "is disguising the failure again"
        )
        record = json.loads(written.read_text(encoding="utf-8").splitlines()[0])
        assert record["source"] == "post_tool_hook"
        assert record["tool"] == "view_file"

    def test_broken_payload_import_is_not_disguised_as_success(self, fleet_root: Path):
        """A payload that cannot be imported must FAIL, not print and exit 0.

        Behavioural, not textual: an earlier version of this test grepped for
        ``except ImportError`` and failed on a COMMENT that merely named the old
        branch -- detecting text instead of behaviour, the very anti-pattern the
        flight plan forbids.

        Runs a COPY of the real wrapper inside a sandbox tree whose own
        ``hooks/post_tool_hook.py`` raises on import. The wrapper prepends its
        grandparent (``.agent/``) and great-grandparent to ``sys.path``, so the
        sandbox copies shadow the real modules -- shadowing via ``PYTHONPATH``
        would NOT work, since those inserts land at ``sys.path[0]``, ahead of it
        (measured 2026-07-28: the real ``bus`` won and the probe exited 0).
        """
        sandbox_root = fleet_root / "broken_payload"
        agent = sandbox_root / ".agent"
        (agent / "hooks").mkdir(parents=True)
        (agent / "hooks" / "__init__.py").write_text("", encoding="utf-8")
        (agent / "hooks" / "post_tool_hook.py").write_text(
            "raise ImportError('shadowed payload')\n", encoding="utf-8"
        )
        wrapper = agent / "hooks" / "native_post_tool_hook.py"
        wrapper.write_text(
            (_ROOT / ".agent" / "hooks" / "native_post_tool_hook.py").read_text(
                encoding="utf-8"
            ),
            encoding="utf-8",
        )
        cwd = _sandbox_tree(sandbox_root / "cwd")
        result = subprocess.run(
            [sys.executable, str(wrapper)],
            input=_HOOK_PAYLOAD,
            cwd=str(cwd),
            capture_output=True,
            timeout=60,
        )
        assert result.returncode != 0, (
            "a broken payload import exited 0: the error branch is "
            "indistinguishable from success again"
        )
        assert b"ImportError" in result.stderr or b"Error" in result.stderr


class TestInvariantDGuardCoversAll:
    """(d) The wired guard audits ALL hook commands, not only PreToolUse."""

    def test_tracked_motor_settings_pass(self):
        """The real tracked file is clean under the extended gate."""
        settings = json.loads(_MOTOR_SETTINGS.read_text(encoding="utf-8"))
        assert gate.check_all_hook_commands_are_canonical(settings) == []

    def test_reverted_post_tool_use_is_rejected(self):
        """MUTATION of (d): revert a PostToolUse to guessing + exit 0 -> violation.

        This is the gate's red. Before WOT-2026-042d it returned rc=0 ("OK,
        portable, fail-closed") for this exact input: the guard was wired and
        fail-closed, and simply did not look at PostToolUse.
        """
        data = json.loads(_MOTOR_SETTINGS.read_text(encoding="utf-8"))
        data["hooks"]["PostToolUse"][0]["hooks"][0]["command"] = (
            "python -c \"import sys; cands=['a']; sys.exit(0)\""
        )
        assert gate.check_all_hook_commands_are_canonical(data) != []

    def test_unknown_hook_target_is_rejected(self):
        """An unmapped hook must not pass unaudited (fail-closed by scope)."""
        data = json.loads(_MOTOR_SETTINGS.read_text(encoding="utf-8"))
        data["hooks"]["Notification"] = [
            {"matcher": "", "hooks": [{"type": "command", "command": "python -c ''"}]}
        ]
        assert gate.check_all_hook_commands_are_canonical(data) != []

    def test_gate_uses_canonical_generator_not_a_duplicated_literal(self):
        """The expected literal comes from claude_guard_entry, the single source.

        Duplicating the bootstrap inside the gate would reintroduce the drift
        class the gate exists to prevent, so changing the generator must change
        what the gate accepts.
        """
        expected = claude_guard_entry.canonical_command_for(
            "native_post_tool_hook.py", "agent_hooks"
        )
        assert _motor_commands()["PostToolUse::Read|Grep|Glob|WebFetch"] == expected


# ===================================================== WOT-2026-057b
# "Barrera del alcance": el guard mordia bien, pero no miraba donde ocurria
# el fallo. Auditaba la CANONICIDAD de los hooks presentes y jamas la
# PRESENCIA de los que inyectan memoria.


class TestContextHooksMustBePresent:
    """Un settings sin los hooks de contexto deja al repo SIN memoria.

    Medido 2026-08-17 sobre el destino real: declaraba solo `PreToolUse` y el
    guard daba `rc=0, OK (portable, fail-closed)`. Le faltaban los DOS unicos
    hooks que inyectan contexto -- `SessionStart` y `PreCompact` --, asi que
    ningun agente que operase alli recibia memoria por ningun canal, ni al
    abrir sesion ni al compactar. Y el destino es justo donde viven las 135
    lecciones de TOPOLOGIA que ese agente necesita.

    El guard existia, estaba cableado y mordia... la propiedad equivocada:
    `_NON_GATING_TARGETS` audita que los hooks PRESENTES sean canonicos, no
    que los REQUERIDOS existan. Registrar `SessionStart` en ese censo (como
    hizo 057b) es INERTE si el settings ni lo declara.
    """

    def test_settings_without_context_hooks_is_rejected(self) -> None:
        """BARRERA: solo PreToolUse -> ERROR nombrando los hooks que faltan."""
        solo_write = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Write|Edit|MultiEdit",
                        "hooks": [
                            {
                                "type": "command",
                                "command": gate.claude_guard_entry.canonical_hook_command(),
                            }
                        ],
                    }
                ]
            }
        }
        errors = gate.check_context_hooks_present(solo_write)
        assert errors, (
            "un settings sin SessionStart ni PreCompact deja al repo sin memoria "
            "por NINGUN canal, y el guard lo aprobaba"
        )
        combined = " ".join(errors)
        assert "SessionStart" in combined and "PreCompact" in combined, (
            "el error debe NOMBRAR los hooks ausentes: un diagnostico que no "
            "dice que falta obliga a adivinar"
        )

    def test_settings_with_both_context_hooks_passes(self) -> None:
        """Control positivo: con los dos, cero errores.

        Sin este control el test anterior pasaria con un guard que rechaza
        SIEMPRE, que no discrimina nada.
        """
        completo = {
            "hooks": {
                "SessionStart": [{"matcher": "", "hooks": [{"type": "command"}]}],
                "PreCompact": [{"matcher": "", "hooks": [{"type": "command"}]}],
            }
        }
        assert gate.check_context_hooks_present(completo) == []

    def test_real_motor_settings_declare_both_context_hooks(self) -> None:
        """El motor cumple su propio contrato (aplicate tu propia vara)."""
        settings = json.loads(
            (_ROOT / ".claude" / "settings.json").read_text(encoding="utf-8")
        )
        assert gate.check_context_hooks_present(settings) == []
