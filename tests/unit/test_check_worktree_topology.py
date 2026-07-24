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
    workspace = tmp_path / "orquestador_de_agentes_workspace"
    workspace.mkdir()
    _make_link(workspace, motor, "WOT", "orquestador_de_agentes_workspace")

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
    ctl = search_root / "Crear_Texto_LLM"
    ctl.mkdir()
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
    ctl = search_root / "Crear_Texto_LLM"
    ctl.mkdir()
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
# (h) --allow-diagnostic on case (b) -> exit 0, [DIAGNOSTIC MODE] verdict
# ---------------------------------------------------------------------------


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
    directory that is NOT the orquestador_de_agentes_workspace link."""
    motor, dev = _make_git_tree(tmp_path)
    real_workspace = tmp_path / "orquestador_de_agentes_workspace"
    real_workspace.mkdir()
    _make_link(real_workspace, motor, "WOT", "orquestador_de_agentes_workspace")
    wrong_workspace = tmp_path / "some_other_project"
    wrong_workspace.mkdir()

    exit_code, message = check_topology("WOT-2026-021g", dev, motor, wrong_workspace)
    assert exit_code == 1
    # Assert on the RESOLVED path, not on the bare name: since WOT-2026-023i the
    # message interpolates the resolved destination, and the name is a SUBSTRING
    # of that path -- so asserting the name alone would keep passing even if the
    # message stopped naming the right workspace. (Pre-023i the name came from a
    # hardcoded constant, which is exactly what this ticket removed.)
    assert str(real_workspace) in message
    assert str(wrong_workspace) in message


# ---------------------------------------------------------------------------
# (j) WOT-2026-023i: Verification B resolves the workspace by ticket_prefix,
# NOT by destination_id. This is the test that kills the retired workaround.
# ---------------------------------------------------------------------------


def test_verification_b_resolves_by_ticket_prefix_not_destination_id(
    tmp_path: Path,
) -> None:
    """Verification B must derive the expected workspace from the WOT
    ticket_prefix (via prefix_resolver.resolve_prefix), never from a
    hardcoded destination_id.

    Step 3 is the one with teeth: the link keeps the CORRECT destination_id
    but declares a FOREIGN ticket_prefix. Under the retired
    _find_workspace_by_destination_id it would still resolve -> exit 0. It
    must now fail to resolve -> exit 2. Without this step, removing that
    helper would be an uncovered change: migrating the fixtures alone leaves
    cases (a)-(i) green either way, because none of them distinguishes the
    two lookup mechanisms.

    Note the exit code: a link that does not resolve is exit 2 ("cannot
    determine"), NOT exit 1 ("wrong workspace"). Asserting `!= 0` here would
    be a false green -- it would pass for either reason.
    """
    motor, dev = _make_git_tree(tmp_path)
    workspace = tmp_path / "orquestador_de_agentes_workspace"
    workspace.mkdir()

    # (1) The link declares ticket_prefix WOT -> resolves -> authorized.
    _make_link(workspace, motor, "WOT", "orquestador_de_agentes_workspace")
    exit_code, _ = check_topology("WOT-2026-023i", dev, motor, workspace)
    assert exit_code == 0

    # (2) No ticket_prefix (the pre-023i defect) -> WOT is not resolvable.
    _make_link(workspace, motor, None, "orquestador_de_agentes_workspace")
    exit_code, message = check_topology("WOT-2026-023i", dev, motor, workspace)
    assert exit_code == 2
    assert "ticket_prefix" in message

    # (3) Correct destination_id, FOREIGN ticket_prefix: resolution is by
    #     prefix, so this must NOT resolve. Reintroducing the destination_id
    #     lookup flips this to 0 and the test dies.
    _make_link(workspace, motor, "XXX", "orquestador_de_agentes_workspace")
    exit_code, message = check_topology("WOT-2026-023i", dev, motor, workspace)
    assert exit_code == 2
    assert "ticket_prefix" in message


def test_verification_b_ambiguous_wot_prefix_is_exit_two(tmp_path: Path) -> None:
    """Two links declaring ticket_prefix WOT make resolve_prefix ambiguous
    (None). Verification B must report that as exit 2 ("cannot determine"),
    not as exit 1 ("wrong workspace") -- the operator needs to know the
    topology is broken, not that they picked the wrong directory. This
    failure mode only exists since WOT-2026-023i put WOT through the generic
    scan; the retired early-return made it unreachable."""
    motor, dev = _make_git_tree(tmp_path)
    workspace = tmp_path / "orquestador_de_agentes_workspace"
    workspace.mkdir()
    _make_link(workspace, motor, "WOT", "orquestador_de_agentes_workspace")
    impostor = tmp_path / "otro_workspace"
    impostor.mkdir()
    _make_link(impostor, motor, "WOT", "otro_workspace")

    exit_code, message = check_topology("WOT-2026-023i", dev, motor, workspace)
    assert exit_code == 2
    assert "ambiguo" in message


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
    workspace = tmp_path / "orquestador_de_agentes_workspace"
    workspace.mkdir()
    _make_link(workspace, motor, "WOT", "orquestador_de_agentes_workspace")
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
    """Verification B se mantiene: flight correcto pero workspace equivocado -> exit 1."""
    motor, _dev = _make_git_tree(tmp_path)
    workspace = tmp_path / "orquestador_de_agentes_workspace"
    workspace.mkdir()
    _make_link(workspace, motor, "WOT", "orquestador_de_agentes_workspace")
    impostor = tmp_path / "otro_workspace"
    impostor.mkdir()
    flight = _add_flight_worktree(motor, tmp_path, "027h")

    exit_code, message = check_topology("WOT-2026-027h", flight, motor, impostor)
    assert exit_code == 1, message


def test_wot_dev_main_still_valid_after_flight_support(tmp_path: Path) -> None:
    """El flujo canonico _dev/main NO se rompe al anadir soporte de vuelo."""
    motor, dev = _make_git_tree(tmp_path)
    workspace = tmp_path / "orquestador_de_agentes_workspace"
    workspace.mkdir()
    _make_link(workspace, motor, "WOT", "orquestador_de_agentes_workspace")

    exit_code, message = check_topology("WOT-2026-027h", dev, motor, workspace)
    assert exit_code == 0, message
    assert "correcta" in message
