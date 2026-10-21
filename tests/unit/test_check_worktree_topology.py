"""Unit tests for scripts/check_worktree_topology.py (WOT-2026-021g).

Covers the 9 cases (a)-(i) of the work_plan Fase 4:
(a) WOT + _dev (main) + correct workspace -> exit 0
(b) WOT + primary detached checkout -> exit 1 (cites setup_dev_worktree.ps1)
(c) WOT + _dev missing -> exit 1 ("Crea la worktree _dev")
(d) known destination + workspace == resolved destination -> exit 0
(e) known destination + workspace != resolved destination -> exit 1
(f) unknown prefix -> exit 2
(g) contract incoherence (delivery_authority vs prefix) -> exit 2
(h) --allow-diagnostic on case (b) -> exit 0, stdout/stderr has
    [DIAGNOSTIC MODE] and the real (blocked) verdict
(i) WOT + _dev correct (Verificacion A passes) + --project-root pointing to
    a DIFFERENT synthetic directory than the orquestador_de_agentes_workspace
    link -> exit 1, literal contract message (isolates Verificacion B / the
    BLOCKER 2 the audit called out)
(j) WOT-2026-023i: Verificacion B resolves the workspace by ticket_prefix
    (prefix_resolver.resolve_prefix), NOT by a hardcoded destination_id ->
    a link with the right destination_id but a foreign ticket_prefix must
    NOT resolve (exit 2). Plus: an ambiguous WOT prefix (two links) is exit
    2, not exit 1.
(k) WOT-2026-104h: the DESTINATION workspace must be a linked worktree, not
    its repo's primary checkout -- enforced on BOTH dispatch legs (WOT and
    non-WOT) and on the bare project-name leg. Destination fixtures are
    therefore real git repos with a real linked worktree
    (`_make_linked_worktree`), never plain directories.
(l) WOT-2026-104h r2 (H1): git's directory discovery ASCENDS, so a
    project_root nested inside a repo is NOT a verifiable checkout -- whether
    that repo is a linked worktree or its primary -- and must fail closed with
    exit 2, never exit 0 (false green) nor a misleading exit 1.

Every WOT fixture declares ticket_prefix "WOT" on the workspace link, mirroring
the real link. They used to pass prefix=None -- encoding the very defect
WOT-2026-023i fixed -- which meant the cases stayed green no matter which lookup
mechanism Verification B used.

Fixtures use real git repos (tmp_path + `git init -b main`, forcing the
branch explicitly) -- NEVER mock git symbolic-ref/subprocess, matching the
DoD's mock-drift avoidance criterion. `git init -b main` (not a bare
`git init`) is mandatory: an unforced init depends on init.defaultBranch,
'main' on this machine but 'master' on the CI runner (no such config
there), which would false-RED the `symbolic-ref == "main"` checks of
cases (a)/(c)/(h) ONLY in CI.

GIT_CEILING_DIRECTORIES is set via monkeypatch on every fixture-building
test to stop git's ambient directory-discovery walk at tmp_path: without
it, a plain (non-git) tmp_path subdirectory would have its git-common-dir
resolution ASCEND into whichever real repo contains the pytest sandbox
(this repo itself), producing a false match/false git-repo detection --
the same root cause documented in tests/unit/test_prefix_resolver.py for
test_guard_wot_in_destination_blocks.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from scripts.check_worktree_topology import _check_contract_coherence, check_topology


def _git_init_main(repo_path: Path) -> None:
    """Init a git repo at repo_path with the branch forced to 'main'."""
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=repo_path, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    (repo_path / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )


def _make_git_tree(tmp_path: Path) -> tuple[Path, Path]:
    """Create a synthetic motor (detached HEAD) + _dev worktree (main),
    mirroring the real topology of this machine exactly (verified live:
    `git worktree list` shows the primary checkout DETACHED and only the
    linked worktree carrying 'main'). Motor is detached BEFORE the linked
    worktree is added because git refuses the same branch checked out in
    two worktrees at once."""
    motor = tmp_path / "motor"
    motor.mkdir()
    _git_init_main(motor)
    subprocess.run(
        ["git", "checkout", "--detach", "main"],
        cwd=motor,
        check=True,
        capture_output=True,
    )
    dev = tmp_path / "motor_dev"
    subprocess.run(
        ["git", "worktree", "add", str(dev), "main"],
        cwd=motor,
        check=True,
        capture_output=True,
    )
    return motor, dev


def _make_linked_worktree(base: Path, name: str) -> Path:
    """Create a real git repo under base and return a LINKED worktree of it.

    WOT-2026-104h: the destination workspace must be a linked worktree, not
    the primary checkout, so destination fixtures can no longer be plain
    directories. `git worktree add -b <branch>` is mandatory (the primary
    already has `main` checked out). No subprocess mocking: the topology is
    created by real git, exactly like the motor fixtures above.

    WOT-2026-109d: keep `name` SHORT (a few chars). Git names the worktree's
    administrative directory after `name` (the basename of `linked`, not the
    branch) -- `.git/worktrees/<name>/refs`. A long `name` (measured: 33
    chars, `"orquestador_de_agentes_workspace"`, chosen for realism) combined
    with pytest's own deep `tmp_path` and a long outer checkout prefix hits
    Windows MAX_PATH with `Filename too long`, 100% reproducible, 7/7 callers
    that used the long name. Shortening the branch alone does NOT fix it --
    the failing path segment comes from `name`, not `session/{name}`.
    """
    primary = base / f"{name}_primary"
    primary.mkdir()
    _git_init_main(primary)
    linked = base / name
    subprocess.run(
        ["git", "worktree", "add", "-b", f"session/{name}", str(linked), "main"],
        cwd=primary,
        check=True,
        capture_output=True,
    )
    return linked


def _make_link(
    dest_root: Path,
    motor_root: Path,
    prefix: str | None,
    dest_id: str | None = None,
) -> None:
    """Create a motor_destination_link.json in dest_root."""
    link_dir = dest_root / ".agent" / "config"
    link_dir.mkdir(parents=True, exist_ok=True)
    data: dict = {
        "motor_root": str(motor_root),
        "destination_root": str(dest_root),
        "motor_version": "v9.17.1",
    }
    if prefix is not None:
        data["ticket_prefix"] = prefix
    if dest_id is not None:
        data["destination_id"] = dest_id
    (link_dir / "motor_destination_link.json").write_text(
        json.dumps(data), encoding="utf-8"
    )


@pytest.fixture(autouse=True)
def _isolate_git_discovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Stop git's ambient upward directory-discovery walk at tmp_path for
    every test in this module. Without this, a plain (non-git) subdirectory
    of tmp_path would ascend into the real repo containing the pytest
    sandbox and produce false git-repo detections. See module docstring."""
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))


# ---------------------------------------------------------------------------
# (a) WOT + _dev (main) + correct workspace -> exit 0
# ---------------------------------------------------------------------------


def test_case_a_wot_dev_correct_workspace_exits_zero(tmp_path: Path) -> None:
    motor, dev = _make_git_tree(tmp_path)
    workspace = _make_linked_worktree(tmp_path, "ws_wot")
    _make_link(workspace, motor, "WOT", "ws_wot")

    exit_code, message = check_topology("WOT-2026-021g", dev, motor, workspace)
    assert exit_code == 0
    assert "correcta" in message


# ---------------------------------------------------------------------------
# (b) WOT + primary detached checkout -> exit 1
# ---------------------------------------------------------------------------


def test_case_b_wot_primary_detached_exits_one(tmp_path: Path) -> None:
    motor, _dev = _make_git_tree(tmp_path)
    workspace = tmp_path / "orquestador_de_agentes_workspace"
    workspace.mkdir()
    _make_link(workspace, motor, "WOT", "orquestador_de_agentes_workspace")

    # cwd == motor (the detached primary checkout itself)
    exit_code, message = check_topology("WOT-2026-021g", motor, motor, workspace)
    assert exit_code == 1
    assert "setup_dev_worktree.ps1" in message


# ---------------------------------------------------------------------------
# (c) WOT + _dev missing -> exit 1
# ---------------------------------------------------------------------------


def test_case_c_wot_dev_missing_exits_one(tmp_path: Path) -> None:
    motor = tmp_path / "motor"
    motor.mkdir()
    _git_init_main(motor)
    # No worktree add: no _dev entry exists in `git worktree list`.
    workspace = tmp_path / "orquestador_de_agentes_workspace"
    workspace.mkdir()
    _make_link(workspace, motor, "WOT", "orquestador_de_agentes_workspace")

    exit_code, message = check_topology("WOT-2026-021g", motor, motor, workspace)
    assert exit_code == 1
    assert "Crea la worktree _dev" in message


# ---------------------------------------------------------------------------
# (d) known destination + workspace == resolved destination -> exit 0
# ---------------------------------------------------------------------------


def test_case_d_destination_correct_workspace_exits_zero(tmp_path: Path) -> None:
    search_root = tmp_path / "projects"
    search_root.mkdir()
    motor = search_root / "orquestador_de_agentes"
    motor.mkdir()
    (motor / ".agent").mkdir(parents=True)
    (motor / ".agent" / "agent_controller.py").write_text("# motor\n", encoding="utf-8")
    ctl = _make_linked_worktree(search_root, "Crear_Texto_LLM")
    _make_link(ctl, motor, "CTL", "Crear_Texto_LLM")

    exit_code, message = check_topology("CTL-2026-001a", motor, motor, ctl)
    assert exit_code == 0
    assert "correcta" in message


# ---------------------------------------------------------------------------
# (e) known destination + workspace != resolved destination -> exit 1
# ---------------------------------------------------------------------------


def test_case_e_destination_wrong_workspace_exits_one(tmp_path: Path) -> None:
    search_root = tmp_path / "projects"
    search_root.mkdir()
    motor = search_root / "orquestador_de_agentes"
    motor.mkdir()
    (motor / ".agent").mkdir(parents=True)
    (motor / ".agent" / "agent_controller.py").write_text("# motor\n", encoding="utf-8")
    ctl = _make_linked_worktree(search_root, "Crear_Texto_LLM")
    _make_link(ctl, motor, "CTL", "Crear_Texto_LLM")
    wrong_workspace = search_root / "Otro_Proyecto"
    wrong_workspace.mkdir()

    exit_code, message = check_topology("CTL-2026-001a", motor, motor, wrong_workspace)
    assert exit_code == 1
    assert "CTL" in message


# ---------------------------------------------------------------------------
# (f) unknown prefix -> exit 2
# ---------------------------------------------------------------------------


def test_case_f_unknown_prefix_exits_two(tmp_path: Path) -> None:
    search_root = tmp_path / "projects"
    search_root.mkdir()
    motor = search_root / "orquestador_de_agentes"
    motor.mkdir()
    (motor / ".agent").mkdir(parents=True)
    (motor / ".agent" / "agent_controller.py").write_text("# motor\n", encoding="utf-8")

    exit_code, message = check_topology("XYZ-2026-001a", motor, motor, motor)
    assert exit_code == 2
    assert "XYZ" in message


# ---------------------------------------------------------------------------
# (g) contract incoherence (delivery_authority vs prefix) -> exit 2
# ---------------------------------------------------------------------------


def test_case_g_contract_incoherence_exits_two(tmp_path: Path) -> None:
    search_root = tmp_path / "projects"
    search_root.mkdir()
    motor = search_root / "orquestador_de_agentes"
    motor.mkdir()
    (motor / ".agent").mkdir(parents=True)
    (motor / ".agent" / "agent_controller.py").write_text("# motor\n", encoding="utf-8")
    collab_dir = motor / ".agent" / "collaboration"
    collab_dir.mkdir(parents=True)
    # prefix WOT but delivery_authority says repo_destino -> incoherent
    (collab_dir / "work_plan.md").write_text(
        "# Plan\n\n- **delivery_authority:** repo_destino\n",
        encoding="utf-8",
    )

    exit_code, message = check_topology("WOT-2026-021g", motor, motor, motor)
    assert exit_code == 2
    assert "incoherencia de contrato" in message


# ---------------------------------------------------------------------------
# (g2) WOT-2026-021s: a work_plan in a TERMINAL state (COMPLETED) must NOT
# block the launch of a new ticket of a DIFFERENT prefix. The residual
# COMPLETED work_plan of a prior WOT (delivery_authority repo_motor) would
# otherwise false-block any CTL start. Mutation-to-prove: removing the
# terminal-state guard makes this flip back to exit 2.
# ---------------------------------------------------------------------------


def _make_motor_with_workplan(tmp_path: Path, workplan_body: str) -> Path:
    search_root = tmp_path / "projects"
    search_root.mkdir()
    motor = search_root / "orquestador_de_agentes"
    motor.mkdir()
    (motor / ".agent").mkdir(parents=True)
    (motor / ".agent" / "agent_controller.py").write_text("# motor\n", encoding="utf-8")
    collab_dir = motor / ".agent" / "collaboration"
    collab_dir.mkdir(parents=True)
    (collab_dir / "work_plan.md").write_text(workplan_body, encoding="utf-8")
    return motor


# These assert on _check_contract_coherence DIRECTLY (the unit under test):
# None = no contract block, (2, msg) = block. Going through check_topology()
# would mask the result, because for a CTL prefix the later dispatch always
# ends in "prefijo desconocido" in this test env (no CTL destination configured)
# -- so "incoherencia not in message" would pass trivially even with a broken
# terminal filter. The direct call has no such masking.


@pytest.mark.parametrize("terminal", ["COMPLETED", "SUPERSEDED", "BLOCKED_FINAL"])
def test_terminal_workplan_does_not_block_other_prefix(
    tmp_path: Path, terminal: str
) -> None:
    # A work_plan in ANY of the 3 irreversible terminal states (mirror of
    # bus/state_machine.py IRREVERSIBLE_TERMINAL_STATES) carrying repo_motor +
    # an incoming CTL ticket -> the terminal-state guard returns None (no block).
    # Parametrizing over all 3 makes the "mirrors the canonical set" claim
    # load-bearing: dropping any terminal from the frozenset fails here.
    motor = _make_motor_with_workplan(
        tmp_path,
        f"# Plan\n\n- **Estado:** {terminal}\n- **delivery_authority:** repo_motor\n",
    )
    assert _check_contract_coherence(motor, "CTL") is None


@pytest.mark.parametrize(
    "decorated",
    ["completed", "COMPLETED (archivado 2026-07-10)", "COMPLETED  "],
)
def test_decorated_terminal_status_is_still_terminal(
    tmp_path: Path, decorated: str
) -> None:
    # A decorated Estado marker (lowercase / parenthetical suffix / trailing
    # space) must still be recognized as terminal -> None (no block). Guards the
    # normalization (upper + first token) before the membership test: removing
    # it makes the lowercase case slip through as non-terminal and fail here.
    motor = _make_motor_with_workplan(
        tmp_path,
        f"# Plan\n\n- **Estado:** {decorated}\n- **delivery_authority:** repo_motor\n",
    )
    assert _check_contract_coherence(motor, "CTL") is None


def test_active_workplan_still_blocks_incoherent_prefix(tmp_path: Path) -> None:
    # Guardrail: a LIVE (non-terminal) work_plan must still block. IN_PROGRESS
    # carrying repo_motor + a CTL prefix (expects repo_destino) -> (2, msg).
    motor = _make_motor_with_workplan(
        tmp_path,
        "# Plan\n\n- **Estado:** IN_PROGRESS\n- **delivery_authority:** repo_motor\n",
    )
    result = _check_contract_coherence(motor, "CTL")
    assert result is not None
    exit_code, message = result
    assert exit_code == 2
    assert "incoherencia de contrato" in message


# ---------------------------------------------------------------------------
# WOT-2026-092m: a NEUTRAL SEED motor (no active ticket) must NOT block a
# non-WOT ticket. The motor's most common resting state ships work_plan.md with
# `**ID:** none` + `**Estado:** READY_TO_START` and NO delivery_authority key;
# read_delivery_authority defaults that to "repo_motor", so a CTL/EXF launch
# against the untouched seed used to false-block (exit 2). The exemption reuses
# state_validation.is_seed_neutral_state, which requires BOTH files.
# ---------------------------------------------------------------------------

_SEED_WORK_PLAN = "# Work Plan\n\n**ID:** none\n**Estado:** READY_TO_START\n"
_SEED_EXEC_LOG = "# Execution Log\n\n**ID:** none\n**Estado:** READY_TO_START\n"


def _make_seed_motor(tmp_path: Path, *, with_log: bool) -> Path:
    """Motor whose collaboration is the portable neutral seed. with_log toggles
    the sibling execution_log.md (is_seed_neutral_state needs both)."""
    motor = _make_motor_with_workplan(tmp_path, _SEED_WORK_PLAN)
    if with_log:
        (motor / ".agent" / "collaboration" / "execution_log.md").write_text(
            _SEED_EXEC_LOG, encoding="utf-8"
        )
    return motor


def _add_ctl_destination(motor: Path, tmp_path: Path) -> Path:
    """Register a CTL destination under <tmp>/projects so the CTL topology leg
    can resolve and the full CLI path is exercisable."""
    ctl = _make_linked_worktree(tmp_path / "projects", "Crear_Texto_LLM")
    _make_link(ctl, motor, "CTL", "Crear_Texto_LLM")
    return ctl


def test_seed_neutral_motor_does_not_block_destination_ticket(tmp_path: Path) -> None:
    # (a) Regression (WOT-2026-092m): prefix CTL + a genuine neutral seed
    # (work_plan.md AND execution_log.md both neutral) -> the contract guard
    # returns None and the whole CLI path exits 0. Mutation-to-prove: removing
    # the seed guard flips this back to exit 2.
    motor = _make_seed_motor(tmp_path, with_log=True)
    ctl = _add_ctl_destination(motor, tmp_path)
    assert _check_contract_coherence(motor, "CTL") is None
    exit_code, message = check_topology("CTL-2026-999a", motor, motor, ctl)
    assert exit_code == 0, message
    assert "correcta" in message


def test_seed_neutral_without_execution_log_still_blocks(tmp_path: Path) -> None:
    # (d) Fail-closed: a seed-neutral-LOOKING work_plan WITHOUT its sibling
    # execution_log.md does NOT open the exemption. is_seed_neutral_state needs
    # BOTH contents; with the log absent, read_delivery_authority still defaults
    # to repo_motor -> mismatch with CTL's expected repo_destino -> exit 2.
    motor = _make_seed_motor(tmp_path, with_log=False)
    result = _check_contract_coherence(motor, "CTL")
    assert result is not None
    exit_code, message = result
    assert exit_code == 2
    assert "incoherencia de contrato" in message


def test_active_motor_workplan_still_blocks_destination_ticket(tmp_path: Path) -> None:
    # (c) Negative control: an ACTIVE ticket (a real **ID:**) carrying an
    # incoherent delivery_authority must STILL block -> exit 2. Guards that the
    # seed exemption does not degenerate into "any non-terminal plan is exempt".
    motor = _make_motor_with_workplan(
        tmp_path,
        "# Plan\n\n**ID:** WOT-2026-999z\n**Estado:** IN_PROGRESS\n"
        "- **delivery_authority:** repo_motor\n",
    )
    (motor / ".agent" / "collaboration" / "execution_log.md").write_text(
        "# Log\n\n**ID:** WOT-2026-999z\n**Estado:** IN_PROGRESS\n",
        encoding="utf-8",
    )
    result = _check_contract_coherence(motor, "CTL")
    assert result is not None
    exit_code, message = result
    assert exit_code == 2
    assert "incoherencia de contrato" in message


# ---------------------------------------------------------------------------
# WOT-2026-092n: fail-closed of UnicodeDecodeError in both readings.
# Work_plan corruption → exit 2 "ilegible"; execution_log corruption →
# log_content None → seed exemption NOT opened → "incoherencia de contrato".
# ---------------------------------------------------------------------------


def test_corrupted_workplan_fails_closed(tmp_path: Path) -> None:
    # work_plan.md present but contains non-UTF-8 bytes → _check_contract_coherence
    # returns (2, msg) with "ilegible" in message. Mutation-to-prove: reverting
    # the UnicodeDecodeError capture to only OSError makes this raise.
    motor = _make_motor_with_workplan(tmp_path, _SEED_WORK_PLAN)
    # Overwrite work_plan.md with corrupted bytes (write_bytes to bypass any
    # text-mode encoding; read_text(encoding="utf-8") will raise UnicodeDecodeError).
    collab = motor / ".agent" / "collaboration"
    (collab / "work_plan.md").write_bytes(b"\xff\xfe invalid utf-8 content\n")
    result = _check_contract_coherence(motor, "CTL")
    assert result is not None
    exit_code, message = result
    assert exit_code == 2
    assert "ilegible" in message


def test_corrupted_execution_log_forfeits_seed_exemption(tmp_path: Path) -> None:
    # execution_log.md present but corrupted → log_content = None (aligned with
    # OSError handler). Since is_seed_neutral_state needs BOTH files valid, the
    # seed exemption is NOT opened → delivery_authority mismatch → exit 2 with
    # "incoherencia de contrato". Mutation-to-prove: reverting the
    # UnicodeDecodeError capture to only OSError makes this raise.
    motor = _make_seed_motor(tmp_path, with_log=True)
    collab = motor / ".agent" / "collaboration"
    (collab / "execution_log.md").write_bytes(b"\xff\xfe invalid utf-8 content\n")
    result = _check_contract_coherence(motor, "CTL")
    assert result is not None
    exit_code, message = result
    assert exit_code == 2
    assert "incoherencia de contrato" in message


def test_valid_utf8_pair_unchanged(tmp_path: Path) -> None:
    # Control positive: both files valid UTF-8 seed state → still None (no change
    # from pre-fix behavior). The seed exemption remains open.
    motor = _make_seed_motor(tmp_path, with_log=True)
    result = _check_contract_coherence(motor, "CTL")
    assert result is None


def test_workplan_is_directory_returns_none(tmp_path: Path) -> None:
    # NON-GOAL guard: work_plan.md as a directory → IsADirectoryError (subclass
    # of OSError) → return None (semántica BASE, no bloqueo). With the r1
    # merged handler (OSError + UnicodeDecodeError → "ilegible") this test
    # failed with (2, …). The B1 fix separates the handlers so OSError → None.
    motor = _make_motor_with_workplan(tmp_path, _SEED_WORK_PLAN)
    collab = motor / ".agent" / "collaboration"
    # Remove the file, create a directory with the same name.
    (collab / "work_plan.md").unlink()
    (collab / "work_plan.md").mkdir()
    result = _check_contract_coherence(motor, "CTL")
    assert result is None


def test_case_h_allow_diagnostic_always_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    from scripts.check_worktree_topology import main

    motor, _dev = _make_git_tree(tmp_path)
    workspace = tmp_path / "orquestador_de_agentes_workspace"
    workspace.mkdir()
    _make_link(workspace, motor, "WOT", "orquestador_de_agentes_workspace")

    monkeypatch.chdir(motor)
    rc = main(
        [
            "--ticket",
            "WOT-2026-021g",
            "--motor-root",
            str(motor),
            "--project-root",
            str(workspace),
            "--allow-diagnostic",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "[DIAGNOSTIC MODE]" in combined
    assert "bloqueado" in combined


def test_case_h_worktree_guard_bypass_env_always_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Same as case (h) but via the WORKTREE_GUARD_BYPASS=1 env var instead
    of --allow-diagnostic, confirming both trigger the same behavior."""
    from scripts.check_worktree_topology import main

    motor, _dev = _make_git_tree(tmp_path)
    workspace = tmp_path / "orquestador_de_agentes_workspace"
    workspace.mkdir()
    _make_link(workspace, motor, "WOT", "orquestador_de_agentes_workspace")

    monkeypatch.chdir(motor)
    monkeypatch.setenv("WORKTREE_GUARD_BYPASS", "1")
    rc = main(
        [
            "--ticket",
            "WOT-2026-021g",
            "--motor-root",
            str(motor),
            "--project-root",
            str(workspace),
        ]
    )
    assert rc == 0
    combined = "".join(capsys.readouterr())
    assert "[DIAGNOSTIC MODE]" in combined


# ---------------------------------------------------------------------------
# (i) WOT + _dev correct (Verificacion A OK) + workspace incorrect -> exit 1
# ---------------------------------------------------------------------------


def test_case_i_wot_dev_correct_wrong_workspace_exits_one(tmp_path: Path) -> None:
    """Isolates Verificacion B (workspace) from Verificacion A (worktree):
    _dev/main is correct, but --project-root points to a synthetic
    directory that is a REGISTERED destination with a FOREIGN prefix (not
    the orquestador_de_agentes_workspace link).

    WOT-2026-097: `wrong_workspace` debe declarar un ticket_prefix real
    distinto de WOT (no quedar sin link) para que el escenario siga siendo
    "workspace equivocado" (exit 1) -- tras el fix de causa raiz, Verification
    B lee el ticket_prefix directamente del link de `project_root`, asi que
    un directorio SIN link cae por la rama de "no se pudo derivar" (exit 2),
    un caso distinto ya cubierto en test_verification_b_resolves_by_ticket_
    prefix_not_destination_id caso (2)."""
    motor, dev = _make_git_tree(tmp_path)
    real_workspace = tmp_path / "orquestador_de_agentes_workspace"
    real_workspace.mkdir()
    _make_link(real_workspace, motor, "WOT", "orquestador_de_agentes_workspace")
    wrong_workspace = tmp_path / "some_other_project"
    wrong_workspace.mkdir()
    _make_link(wrong_workspace, motor, "CTL", "some_other_project")

    exit_code, message = check_topology("WOT-2026-021g", dev, motor, wrong_workspace)
    assert exit_code == 1
    # El mensaje ya no nombra el destino WOT resuelto (no hace falta
    # adivinarlo), pero SI debe nombrar el workspace equivocado y su
    # ticket_prefix real para que el operador sepa que vio y por que es
    # incorrecto.
    assert str(wrong_workspace) in message
    assert "CTL" in message


# ---------------------------------------------------------------------------
# (j) WOT-2026-023i: Verification B resolves the workspace by ticket_prefix,
# NOT by destination_id. This is the test that kills the retired workaround.
# ---------------------------------------------------------------------------


def test_verification_b_resolves_by_ticket_prefix_not_destination_id(
    tmp_path: Path,
) -> None:
    """Verification B must derive the ticket_prefix from the PROJECT_ROOT's
    own link (via prefix_resolver.resolve_prefix_for_destination), never from
    a hardcoded destination_id.

    WOT-2026-097: Verification B stopped guessing "the" unique WOT
    destination among N candidates (prefix_resolver.resolve_prefix) and now
    reads the ticket_prefix directly off project_root's own link
    (resolve_prefix_for_destination) -- see _verify_wot_workspace's
    docstring for the causa-raiz fix. The exit codes below reflect that: a
    MISSING/malformed link is exit 2 ("cannot determine"); a link that
    EXISTS but declares the WRONG prefix is exit 1 ("wrong workspace"),
    because the workspace IS a real, resolvable destination -- just not the
    WOT one.

    Step 3 is the one with teeth: the link keeps the CORRECT destination_id
    but declares a FOREIGN ticket_prefix. Under the retired
    _find_workspace_by_destination_id it would still resolve -> exit 0. It
    must now resolve to a DIFFERENT prefix -> exit 1, not exit 0. Without
    this step, removing that helper would be an uncovered change: migrating
    the fixtures alone leaves cases (a)-(i) green either way, because none
    of them distinguishes the two lookup mechanisms.
    """
    motor, dev = _make_git_tree(tmp_path)
    workspace = _make_linked_worktree(tmp_path, "ws_wot")

    # (1) The link declares ticket_prefix WOT -> resolves -> authorized.
    _make_link(workspace, motor, "WOT", "ws_wot")
    exit_code, _ = check_topology("WOT-2026-023i", dev, motor, workspace)
    assert exit_code == 0

    # (2) No ticket_prefix (the pre-023i defect) -> WOT is not resolvable.
    _make_link(workspace, motor, None, "ws_wot")
    exit_code, message = check_topology("WOT-2026-023i", dev, motor, workspace)
    assert exit_code == 2
    assert "ticket_prefix" in message

    # (3) Correct destination_id, FOREIGN ticket_prefix: resolution is by
    #     prefix, so this must resolve to XXX, not WOT -> exit 1 ("wrong
    #     workspace"), never exit 0 (reintroducing the destination_id lookup
    #     would flip this to 0 and the test would die) nor exit 2 (the link
    #     DOES resolve, just to the wrong prefix).
    _make_link(workspace, motor, "XXX", "ws_wot")
    exit_code, message = check_topology("WOT-2026-023i", dev, motor, workspace)
    assert exit_code == 1
    assert "ticket_prefix" in message


def test_verification_b_two_wot_destinations_does_not_block_either(
    tmp_path: Path,
) -> None:
    """WOT-2026-097 (fix de causa raiz de B3): dos destinos distintos
    declarando ticket_prefix WOT (el patron real de N worktrees paralelos
    del mismo destino, WOT-2026-039c) ya NO bloquea la verificacion de
    NINGUNO de los dos como exit 2 ("ambiguo").

    Antes del fix, Verification B adivinaba "el" unico destino WOT via
    prefix_resolver.resolve_prefix(WOT_PREFIX, motor_root) -- que devuelve
    None en cuanto hay >1 candidato -- e IGNORABA el project_root que ya
    recibia como parametro hasta comparar DESPUES. Dos destinos WOT
    legitimos hacian caer exit 2 sobre un project_root perfectamente
    valido. El fix resuelve por el PROPIO project_root
    (resolve_prefix_for_destination), sin escanear ni desambiguar entre
    candidatos: no hace falta que exista un UNICO destino WOT en el
    sistema, solo que ESE path declare WOT.

    (Antes de este fix este mismo escenario era exit 2 con "ambiguo" en el
    mensaje -- ver WOT-2026-023i; ese comportamiento era el BUG, no una
    propiedad a preservar.)"""
    motor, dev = _make_git_tree(tmp_path)
    workspace = _make_linked_worktree(tmp_path, "ws_wot")
    _make_link(workspace, motor, "WOT", "ws_wot")
    otro_destino_wot = _make_linked_worktree(tmp_path, "otro_workspace")
    _make_link(otro_destino_wot, motor, "WOT", "otro_workspace")

    # Verificar `workspace` como project_root -> exit 0, sin importar que
    # `otro_destino_wot` tambien declare WOT.
    exit_code, _message = check_topology("WOT-2026-023i", dev, motor, workspace)
    assert exit_code == 0

    # Verificar el OTRO destino como project_root -> tambien exit 0: ninguno
    # de los dos queda bloqueado por la existencia del otro.
    exit_code, _message = check_topology("WOT-2026-023i", dev, motor, otro_destino_wot)
    assert exit_code == 0


# ---------------------------------------------------------------------------
# CLI --help
# ---------------------------------------------------------------------------


def test_cli_help_documents_all_flags(capsys: pytest.CaptureFixture) -> None:
    from scripts.check_worktree_topology import main

    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "--ticket" in out
    assert "--motor-root" in out
    assert "--project-root" in out
    assert "--allow-diagnostic" in out


# ---------------------------------------------------------------------------
# WOT-2026-040q: worktree-por-vuelo (flight/<suffix>) es topologia valida.
# El guard exigia _dev/main y era CIEGO al modelo de vuelos-paralelos, bloqueando
# los 3 vuelos que corren en su propia worktree. Adjudicado por Codex 2026-07-25.
# ---------------------------------------------------------------------------


def _add_flight_worktree(motor: Path, tmp_path: Path, suffix: str) -> Path:
    """Add a per-flight worktree on branch flight/<suffix> (e.g. flight/027h).

    Mirrors the real launch: `git worktree add -b flight/<suffix> <path> main`.
    The worktree basename does NOT end in _dev and the branch is NOT main, which
    is EXACTLY what the pre-040q guard rejected."""
    wt = tmp_path / f"orquestador_wt_{suffix}"
    subprocess.run(
        ["git", "worktree", "add", "-b", f"flight/{suffix}", str(wt), "main"],
        cwd=motor,
        check=True,
        capture_output=True,
    )
    return wt


def test_wot_flight_worktree_matching_suffix_exits_zero(tmp_path: Path) -> None:
    """(d) DoD: WOT-2026-027h desde una worktree en rama flight/027h -> exit 0.
    Es el caso que bloqueaba los 3 vuelos paralelos."""
    motor, _dev = _make_git_tree(tmp_path)
    workspace = _make_linked_worktree(tmp_path, "ws_wot")
    _make_link(workspace, motor, "WOT", "ws_wot")
    flight = _add_flight_worktree(motor, tmp_path, "027h")

    exit_code, message = check_topology("WOT-2026-027h", flight, motor, workspace)
    assert exit_code == 0, message
    assert "correcta" in message


def test_wot_flight_worktree_cross_ticket_exits_one(tmp_path: Path) -> None:
    """(b/d) DoD fail-closed: WOT-2026-025i desde flight/027h (CRUZADO) -> exit 1.
    Un vuelo no puede trabajar un ticket distinto al que nombra su rama."""
    motor, _dev = _make_git_tree(tmp_path)
    workspace = tmp_path / "orquestador_de_agentes_workspace"
    workspace.mkdir()
    _make_link(workspace, motor, "WOT", "orquestador_de_agentes_workspace")
    flight = _add_flight_worktree(motor, tmp_path, "027h")

    exit_code, message = check_topology("WOT-2026-025i", flight, motor, workspace)
    assert exit_code == 1, message
    assert "025i" in message or "flight" in message.lower()


def test_wot_flight_worktree_wrong_workspace_exits_one(tmp_path: Path) -> None:
    """Verification B se mantiene: flight correcto pero workspace equivocado -> exit 1.

    WOT-2026-097: `impostor` debe ser un destino REGISTRADO con un prefijo
    DISTINTO de WOT (no un directorio sin link) para que el escenario siga
    siendo genuinamente "workspace equivocado" (exit 1) en vez de "workspace
    sin registrar" (exit 2, cubierto aparte por el caso (2) de
    test_verification_b_resolves_by_ticket_prefix_not_destination_id) -- tras
    el fix de causa raiz, Verification B lee el ticket_prefix directamente
    del link de `impostor`, asi que un `impostor` sin link ya no produce
    exit 1 por la via antigua (adivinar "el" WOT y comparar)."""
    motor, _dev = _make_git_tree(tmp_path)
    workspace = tmp_path / "orquestador_de_agentes_workspace"
    workspace.mkdir()
    _make_link(workspace, motor, "WOT", "orquestador_de_agentes_workspace")
    impostor = tmp_path / "otro_workspace"
    impostor.mkdir()
    _make_link(impostor, motor, "CTL", "otro_workspace")
    flight = _add_flight_worktree(motor, tmp_path, "027h")

    exit_code, message = check_topology("WOT-2026-027h", flight, motor, impostor)
    assert exit_code == 1, message


def test_wot_dev_main_still_valid_after_flight_support(tmp_path: Path) -> None:
    """El flujo canonico _dev/main NO se rompe al anadir soporte de vuelo."""
    motor, dev = _make_git_tree(tmp_path)
    workspace = _make_linked_worktree(tmp_path, "ws_wot")
    _make_link(workspace, motor, "WOT", "ws_wot")

    exit_code, message = check_topology("WOT-2026-027h", dev, motor, workspace)
    assert exit_code == 0, message
    assert "correcta" in message


# ---------------------------------------------------------------------------
# WOT-2026-040p (absorbe 040m): el INDICE del worktree de vuelo debe estar
# limpio. Un `git checkout` que no limpia el indice deja un fichero STAGED que
# re-introduce un cambio revertido, con el WORKING TREE aparentemente limpio.
# ---------------------------------------------------------------------------


def _stage_tracked_file_change(worktree: Path) -> None:
    """Edit a tracked file and `git add` it, leaving the change STAGED.

    After this the working tree matches the index (`git status` shows a staged
    `M ` entry, not an unstaged ` M`), so a working-tree-only check would see
    "clean" and wave it through -- exactly the 040m shape.
    """
    (worktree / "README.md").write_text("# staged residue\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "README.md"],
        cwd=worktree,
        check=True,
        capture_output=True,
    )


def test_wot_flight_worktree_staged_index_is_blocked(tmp_path: Path) -> None:
    """(a) MUTATION con los dos rc publicados.

    Con `_check_index_clean` cableado en la rama flight -> exit 1 (el indice
    sucio bloquea). Sin el (codigo pre-040p) -> exit 0: el guard acepta la
    worktree de vuelo con residuo staged. El cambio se crea editando un
    fichero trackeado y `git add`-eandolo, asi que el working tree queda
    SINCRONIZADO con el indice (`M ` staged) -- un check del working tree no
    lo veria.
    """
    motor, _dev = _make_git_tree(tmp_path)
    workspace = tmp_path / "orquestador_de_agentes_workspace"
    workspace.mkdir()
    _make_link(workspace, motor, "WOT", "orquestador_de_agentes_workspace")
    flight = _add_flight_worktree(motor, tmp_path, "027h")

    _stage_tracked_file_change(flight)

    # Control de forma: el cambio esta STAGED, el working tree no difiere de
    # el indice. Si esto cambiara, el test dejaria de probar lo que dice.
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=flight,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert status.startswith("M "), f"se esperaba un cambio STAGED, status={status!r}"

    exit_code, message = check_topology("WOT-2026-027h", flight, motor, workspace)
    assert exit_code == 1, message
    assert "INDICE" in message
    assert "STAGED" in message


def test_wot_flight_worktree_unstaged_only_index_change_is_not_blocked(
    tmp_path: Path,
) -> None:
    """(b) El check es INDEX-especifico: un cambio SOLO del working tree (sin
    `git add`) deja el indice limpio y NO bloquea -- trabajo en curso normal.

    MUTATION: si el check se cambiara por uno del working tree (p.ej. `git
    diff` sin `--cached`), este caso pasaria a exit 1 y el test moriria.
    """
    motor, _dev = _make_git_tree(tmp_path)
    workspace = _make_linked_worktree(tmp_path, "ws_wot")
    _make_link(workspace, motor, "WOT", "ws_wot")
    flight = _add_flight_worktree(motor, tmp_path, "027h")

    # Edit without `git add`: working tree dirty, INDEX clean.
    (flight / "README.md").write_text("# unstaged only\n", encoding="utf-8")

    exit_code, message = check_topology("WOT-2026-027h", flight, motor, workspace)
    assert exit_code == 0, message
    assert "correcta" in message


def test_wot_dev_main_with_staged_index_still_passes(tmp_path: Path) -> None:
    """Aditividad: el check de indice se aplica SOLO al modo vuelo, asi que el
    flujo canonico `_dev`/main NO cambia de comportamiento (STOP condition de
    WOT-2026-040p: no romper el modo _dev). Un _dev con indice staged sigue
    dando exit 0.
    """
    motor, dev = _make_git_tree(tmp_path)
    workspace = _make_linked_worktree(tmp_path, "ws_wot")
    _make_link(workspace, motor, "WOT", "ws_wot")

    _stage_tracked_file_change(dev)

    exit_code, message = check_topology("WOT-2026-027h", dev, motor, workspace)
    assert exit_code == 0, message


# ---------------------------------------------------------------------------
# WOT-2026-104h: el workspace del DESTINO tambien debe ser una worktree
# ENLAZADA, no el checkout principal de su repo. Dos sesiones sobre el mismo
# project_root principal comparten work_plan.md/execution_log.md/backlog.
# ---------------------------------------------------------------------------


def test_destination_linked_worktree_exits_zero(tmp_path: Path) -> None:
    """(positivo) Un project_root que es worktree ENLAZADA -> exit 0.

    Fixture con `git worktree add` real (sin mockear subprocess): el repo
    primario queda en <name>_primary y la worktree enlazada en <name>.
    """
    from scripts.check_worktree_topology import _check_destination_is_linked_worktree

    linked = _make_linked_worktree(tmp_path, "destino_enlazado")

    exit_code, message = _check_destination_is_linked_worktree(linked)
    assert exit_code == 0, message
    assert "enlazada" in message


def test_destination_primary_checkout_exits_one(tmp_path: Path) -> None:
    """(negativo) El checkout PRINCIPAL del repo del destino -> exit 1.

    Mismo repo real que el positivo, pero apuntando a su working tree
    primario: es el topology hazard que este guard bloquea.
    """
    from scripts.check_worktree_topology import _check_destination_is_linked_worktree

    primary = tmp_path / "destino_primary"
    primary.mkdir()
    _git_init_main(primary)

    exit_code, message = _check_destination_is_linked_worktree(primary)
    assert exit_code == 1, message
    assert "PRINCIPAL" in message
    assert "worktree" in message.lower()


def test_destination_non_git_workspace_fails_closed(tmp_path: Path) -> None:
    """Si no se puede determinar la topologia (no es repo git), fail-closed
    exit 2 -- misma semantica que la Verificacion A del motor, nunca 0 por
    no poder confirmar el aislamiento."""
    from scripts.check_worktree_topology import _check_destination_is_linked_worktree

    plain = tmp_path / "plain_workspace"
    plain.mkdir()

    exit_code, message = _check_destination_is_linked_worktree(plain)
    assert exit_code == 2, message
    assert "no se puede determinar" in message


def test_destination_plain_dir_nested_in_linked_worktree_fails_closed(
    tmp_path: Path,
) -> None:
    """(H1, caso C del Revisor) Un directorio LLANO anidado dentro de una
    worktree ENLAZADA no es un checkout: git asciende y reporta la worktree
    padre como toplevel.

    Pre-fix devolvia exit 0 (falso verde: toplevel != primary), que es
    exactamente el fallo real de WOT-2026-104f (el lanzador dejo un directorio
    vacio sin `git worktree add`). La precondition toplevel == project_root
    lo reclasifica a exit 2. Mutation-to-prove: quitar esa precondition
    devuelve 0 y este test muere."""
    from scripts.check_worktree_topology import _check_destination_is_linked_worktree

    linked = _make_linked_worktree(tmp_path, "destino_enlazado")
    nested = linked / "not_a_repo"
    nested.mkdir()

    exit_code, message = _check_destination_is_linked_worktree(nested)
    assert exit_code == 2, message
    assert "no se puede determinar" in message


def test_destination_plain_dir_nested_in_primary_checkout_fails_closed(
    tmp_path: Path,
) -> None:
    """(NIT-2) Un directorio LLANO anidado en el checkout PRINCIPAL no ES el
    checkout principal: pre-fix devolvia exit 1 con el mensaje falso "el
    workspace ... es el checkout PRINCIPAL". La precondition lo reclasifica a
    exit 2 ("no determinable"), que es lo que el docstring promete."""
    from scripts.check_worktree_topology import _check_destination_is_linked_worktree

    primary = tmp_path / "destino_primary"
    primary.mkdir()
    _git_init_main(primary)
    nested = primary / "not_a_repo"
    nested.mkdir()

    exit_code, message = _check_destination_is_linked_worktree(nested)
    assert exit_code == 2, message
    assert "no se puede determinar" in message


def test_ctl_primary_checkout_is_blocked_by_wiring(tmp_path: Path) -> None:
    """El camino NO-WOT (prefijo CTL) exige la worktree enlazada: el checkout
    principal del destino resuelve el prefijo correctamente y aun asi se
    bloquea con exit 1. Sin el cableado en _check_destination_topology este
    caso daria exit 0."""
    search_root = tmp_path / "projects"
    search_root.mkdir()
    motor = search_root / "orquestador_de_agentes"
    motor.mkdir()
    (motor / ".agent").mkdir(parents=True)
    (motor / ".agent" / "agent_controller.py").write_text("# motor\n", encoding="utf-8")
    primary = search_root / "Crear_Texto_LLM"
    primary.mkdir()
    _git_init_main(primary)
    _make_link(primary, motor, "CTL", "Crear_Texto_LLM")

    exit_code, message = check_topology("CTL-2026-001a", motor, motor, primary)
    assert exit_code == 1, message
    assert "PRINCIPAL" in message


def test_wot_primary_destination_checkout_is_blocked(tmp_path: Path) -> None:
    """El camino WOT tambien exige la worktree enlazada: con la Verificacion A
    del motor correcta (_dev/main) y un link WOT valido, el checkout primario
    del destino bloquea con exit 1. Sin el cableado en _verify_wot_workspace
    este caso daria exit 0."""
    motor, dev = _make_git_tree(tmp_path)
    primary = tmp_path / "destino_wot"
    primary.mkdir()
    _git_init_main(primary)
    _make_link(primary, motor, "WOT", "destino_wot")

    exit_code, message = check_topology("WOT-2026-104h", dev, motor, primary)
    assert exit_code == 1, message
    assert "PRINCIPAL" in message


# H2 (WOT-2026-104h r2): the bare PROJECT-NAME leg dispatches without a ticket
# prefix. It must carry the SAME linked-worktree requirement, otherwise
# invoking the guard by project name (prompts/orchestrator_destination_
# bootstrap.md:47 passes <TICKET_O_PROYECTO>) would be a trivial bypass.
# Removing the `_check_destination_is_linked_worktree` call on that leg flips
# the negative test below to exit 0 -> it dies.


def test_project_name_linked_worktree_exits_zero(tmp_path: Path) -> None:
    """(positivo, H2) Nombre de proyecto resuelto a una worktree ENLAZADA ->
    exit 0, y el mensaje declara la worktree enlazada (NIT-1)."""
    search_root = tmp_path / "projects"
    search_root.mkdir()
    motor = search_root / "orquestador_de_agentes"
    motor.mkdir()
    (motor / ".agent").mkdir(parents=True)
    (motor / ".agent" / "agent_controller.py").write_text("# motor\n", encoding="utf-8")
    linked = _make_linked_worktree(search_root, "Crear_Texto_LLM")
    _make_link(linked, motor, "CTL", "Crear_Texto_LLM")

    exit_code, message = check_topology("Crear_Texto_LLM", motor, motor, linked)
    assert exit_code == 0, message
    assert "enlazada" in message


def test_project_name_primary_checkout_is_blocked_by_wiring(tmp_path: Path) -> None:
    """(negativo, H2) Nombre de proyecto resuelto al checkout PRINCIPAL del
    destino -> exit 1. Es el test que muerde la rama project-name: sin el
    cableado en check_topology, este caso daria exit 0."""
    search_root = tmp_path / "projects"
    search_root.mkdir()
    motor = search_root / "orquestador_de_agentes"
    motor.mkdir()
    (motor / ".agent").mkdir(parents=True)
    (motor / ".agent" / "agent_controller.py").write_text("# motor\n", encoding="utf-8")
    primary = search_root / "Crear_Texto_LLM"
    primary.mkdir()
    _git_init_main(primary)
    _make_link(primary, motor, "CTL", "Crear_Texto_LLM")

    exit_code, message = check_topology("Crear_Texto_LLM", motor, motor, primary)
    assert exit_code == 1, message
    assert "PRINCIPAL" in message
