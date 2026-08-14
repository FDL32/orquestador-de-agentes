"""Tests for scripts/destination_context.py.

Covers:
- New destination without graphify produces a useful map
- Absence of git does not crash
- Unversioned repo (no .git) does not crash
- Missing/invalid motor_destination_link.json gives clear error
- Byte budget truncation preserves identity + operational state
- Optional files missing degrades cleanly
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts.destination_context import (
    build_map,
    compute_contract_surface_drift,
    compute_motor_drift,
    extract_file_preview,
    get_git_info,
    get_operational_state,
    main,
    resolve_motor_link,
)


def _write_link(project_root: Path, *, ticket_prefix: str | None = None) -> dict:
    """Helper: write a valid motor_destination_link.json in the project."""
    config_dir = project_root / ".agent" / "config"
    config_dir.mkdir(parents=True)
    payload = {
        "motor_root": str(project_root.resolve()),
        "destination_root": str(project_root.resolve()),
        "motor_version": "9.15.0-test",
        "destination_id": project_root.name,
        "ticket_prefix": ticket_prefix,
        "created_at": "2026-06-05T00:00:00+00:00",
        "manifest_version": "1.0",
    }
    link_path = config_dir / "motor_destination_link.json"
    link_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def _write_work_plan(project_root: Path, *, ticket_id: str = "WT-9999-NNN") -> None:
    """Helper: write a minimal work_plan.md in the project."""
    collab = project_root / ".agent" / "collaboration"
    collab.mkdir(parents=True)
    content = (
        f"# Work Ticket - {ticket_id}\n"
        f"\n"
        f"## Metadata\n"
        f"- **ID:** {ticket_id}\n"
        f"- **Title:** Test ticket for destination context\n"
        f"- **Priority:** Alta\n"
        f"- **Estado:** APPROVED\n"
        f"- **deliverable_type:** code\n"
    )
    (collab / "work_plan.md").write_text(content, encoding="utf-8")


def _write_state_md(project_root: Path) -> None:
    """Helper: write a minimal STATE.md in the project."""
    collab = project_root / ".agent" / "collaboration"
    collab.mkdir(parents=True, exist_ok=True)
    (collab / "STATE.md").write_text(
        "ACTIVE_TICKET: WT-9999-NNN\nSTATUS: IN_PROGRESS\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# resolve_motor_link
# ---------------------------------------------------------------------------


def test_resolve_motor_link_valid(tmp_path):
    """Valid link returns parsed dict."""
    payload = _write_link(tmp_path, ticket_prefix="WT")
    result = resolve_motor_link(tmp_path)
    assert result is not None
    assert result["motor_root"] == payload["motor_root"]
    assert result["ticket_prefix"] == "WT"


def test_resolve_motor_link_missing(tmp_path):
    """Missing link returns None."""
    assert resolve_motor_link(tmp_path) is None


def test_resolve_motor_link_invalid_json(tmp_path):
    """Invalid JSON returns None."""
    config_dir = tmp_path / ".agent" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "motor_destination_link.json").write_text(
        "{invalid", encoding="utf-8"
    )
    assert resolve_motor_link(tmp_path) is None


# ---------------------------------------------------------------------------
# get_git_info
# ---------------------------------------------------------------------------


def test_git_info_no_git_dir(tmp_path):
    """No .git directory returns None."""
    info = get_git_info(tmp_path)
    assert info is None


def test_git_info_clean_repo(tmp_path):
    """Clean git repo returns clean status."""
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True
    )
    (tmp_path / "README.md").write_text("# Test", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)

    info = get_git_info(tmp_path)
    assert info is not None
    assert info["branch"] in ("main", "master")
    assert info["dirty"] is False
    assert "error" not in info


# ---------------------------------------------------------------------------
# extract_file_preview
# ---------------------------------------------------------------------------


def test_extract_file_preview(tmp_path):
    """Returns first N lines of a text file."""
    f = tmp_path / "test.md"
    f.write_text("line1\nline2\nline3\n", encoding="utf-8")
    preview = extract_file_preview(f, max_lines=2)
    assert preview is not None
    assert "line1" in preview
    assert "line2" in preview
    assert "line3" not in preview


def test_extract_file_preview_missing(tmp_path):
    """Missing file returns None."""
    assert extract_file_preview(tmp_path / "nonexistent.md") is None


# ---------------------------------------------------------------------------
# get_operational_state
# ---------------------------------------------------------------------------


def test_get_operational_state_no_collab(tmp_path):
    """No collaboration directory returns empty state."""
    state = get_operational_state(tmp_path)
    assert state.get("ticket_id") is None
    assert state.get("state_md_present") is False


def test_get_operational_state_with_ticket(tmp_path):
    """Active ticket ID is parsed from work_plan.md."""
    _write_work_plan(tmp_path, ticket_id="WT-9999-NNN")
    state = get_operational_state(tmp_path)
    assert state["ticket_id"] == "WT-9999-NNN"
    assert state["ticket_title"] == "Test ticket for destination context"
    assert state["estado"] == "APPROVED"


def test_get_operational_state_with_state_md(tmp_path):
    """STATE.md content is captured."""
    _write_state_md(tmp_path)
    state = get_operational_state(tmp_path)
    assert state["state_md_present"] is True
    assert "WT-9999-NNN" in state.get("state_md_content", "")


# ---------------------------------------------------------------------------
# build_map - identity and topology
# ---------------------------------------------------------------------------


def test_build_map_includes_identity(tmp_path):
    """Map contains destination root and motor link info."""
    _write_link(tmp_path, ticket_prefix="WT")
    content = build_map(tmp_path, max_bytes=204800)
    # WOT-2026-016p: la proyeccion es PII-safe - nombre presente, ruta ausente.
    assert tmp_path.resolve().name in content
    assert str(tmp_path.resolve()) not in content
    assert "destination-hosted" in content
    assert "Motor link:" in content
    assert "valid" in content


def test_build_map_identity_without_link(tmp_path):
    """Without link, identity shows standalone mode."""
    content = build_map(tmp_path, max_bytes=204800)
    assert "standalone" in content
    assert "absent" in content
    assert "not resolvable" in content


# ---------------------------------------------------------------------------
# build_map - operational state
# ---------------------------------------------------------------------------


def test_build_map_includes_ticket_info(tmp_path):
    """Active ticket metadata appears in the map."""
    _write_link(tmp_path)
    _write_work_plan(tmp_path)
    content = build_map(tmp_path, max_bytes=204800)
    assert "WT-9999-NNN" in content
    assert "APPROVED" in content


def test_build_map_no_ticket_shows_none(tmp_path):
    """When no ticket exists, shows 'none'."""
    _write_link(tmp_path)
    content = build_map(tmp_path, max_bytes=204800)
    assert "Active Ticket:" in content
    assert "**none**" in content or "none" in content


# ---------------------------------------------------------------------------
# build_map - git section
# ---------------------------------------------------------------------------


def test_build_map_no_git(tmp_path):
    """Map includes degraded git section when no repo."""
    _write_link(tmp_path)
    content = build_map(tmp_path, max_bytes=204800)
    assert "no git repository" in content or "Git State" in content


# ---------------------------------------------------------------------------
# build_map - byte budget truncation
# ---------------------------------------------------------------------------


def test_build_map_respects_byte_budget(tmp_path):
    """Map never exceeds max_bytes limit."""
    _write_link(tmp_path)
    _write_work_plan(tmp_path)
    content = build_map(tmp_path, max_bytes=1024)
    assert len(content.encode("utf-8")) <= 1024


def test_build_map_small_budget_preserves_identity(tmp_path):
    """Even with small budget, identity and state survive."""
    _write_link(tmp_path)
    _write_work_plan(tmp_path)
    _write_state_md(tmp_path)
    # Use budget large enough for identity + operational but small enough
    # to force truncation of lower-priority sections
    content = build_map(tmp_path, max_bytes=1024)
    # Identity must be there
    # WOT-2026-016p: la proyeccion es PII-safe - nombre presente, ruta ausente.
    assert tmp_path.resolve().name in content
    assert str(tmp_path.resolve()) not in content
    # Operational state must be there
    assert "WT-9999-NNN" in content
    assert "IN_PROGRESS" in content
    # Size must be within budget
    assert len(content.encode("utf-8")) <= 1024


# ---------------------------------------------------------------------------
# build_map - graphify absent
# ---------------------------------------------------------------------------


def test_build_map_no_graphify(tmp_path):
    """Absence of graphify-out/ does not crash or add graphify section."""
    _write_link(tmp_path)
    content = build_map(tmp_path, max_bytes=204800)
    assert "Graphify" not in content


# ---------------------------------------------------------------------------
# main() integration
# ---------------------------------------------------------------------------


def test_main_missing_link_returns_error(tmp_path, capsys):
    """--bootstrap without link gives clear error and non-zero exit."""
    exit_code = main(
        [
            "--bootstrap",
            "--project-root",
            str(tmp_path),
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "not found or invalid" in captured.err


def test_main_generates_map(tmp_path, capsys):
    """--bootstrap with valid link generates destination_map.md."""
    _write_link(tmp_path)
    exit_code = main(
        [
            "--bootstrap",
            "--project-root",
            str(tmp_path),
        ]
    )
    assert exit_code == 0
    map_file = tmp_path / ".agent" / "context" / "destination_map.md"
    assert map_file.exists()
    content = map_file.read_text(encoding="utf-8")
    # WOT-2026-016p: la proyeccion es PII-safe - nombre presente, ruta ausente.
    assert tmp_path.resolve().name in content
    assert str(tmp_path.resolve()) not in content
    assert "Destination Context Map" in content


def test_main_respects_max_bytes(tmp_path, capsys):
    """--max-bytes flag limits output size."""
    _write_link(tmp_path)
    _write_work_plan(tmp_path)
    # Use 800 bytes — enough for identity + operational + partial git
    exit_code = main(
        [
            "--bootstrap",
            "--project-root",
            str(tmp_path),
            "--max-bytes",
            "800",
        ]
    )
    assert exit_code == 0
    map_file = tmp_path / ".agent" / "context" / "destination_map.md"
    content = map_file.read_text(encoding="utf-8")
    assert len(content.encode("utf-8")) <= 800


def test_main_invalid_project_root(tmp_path, capsys):
    """Non-existent project root returns error."""
    exit_code = main(
        [
            "--bootstrap",
            "--project-root",
            str(tmp_path / "nonexistent"),
        ]
    )
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "does not exist" in captured.err


# ---------------------------------------------------------------------------
# Regression: no graphify, no crash
# ---------------------------------------------------------------------------


def test_build_map_no_optional_files(tmp_path):
    """Map handles missing PROJECT.md, README, etc. gracefully."""
    _write_link(tmp_path)
    content = build_map(tmp_path, max_bytes=204800)
    # Should not crash, key sections present
    assert "Identity & Topology" in content
    assert "Operational State" in content


# ---------------------------------------------------------------------------
# _latest_handoff_blocked (HANDOFF_BLOCKED summary with resolution status)
# ---------------------------------------------------------------------------


def _write_events(tmp_path: Path, events: list[dict]) -> None:
    events_dir = tmp_path / ".agent" / "runtime" / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    lines = "\n".join(json.dumps(e) for e in events)
    (events_dir / "events.jsonl").write_text(lines + "\n", encoding="utf-8")


def test_handoff_blocked_unresolved(tmp_path):
    """A trailing HANDOFF_BLOCKED with no later activity is unresolved."""
    from scripts.destination_context import _latest_handoff_blocked

    _write_events(
        tmp_path,
        [
            {
                "event_type": "STATE_CHANGED",
                "ticket_id": "CTL-2026-001a",
                "sequence_number": 1,
            },
            {
                "event_type": "HANDOFF_BLOCKED",
                "ticket_id": "CTL-2026-001a",
                "sequence_number": 2,
                "payload": {"reason": "scope gate rejected"},
            },
        ],
    )
    result = _latest_handoff_blocked(tmp_path)
    assert result is not None
    assert result["ticket_id"] == "CTL-2026-001a"
    assert result["sequence"] == 2
    assert result["reason"] == "scope gate rejected"
    assert result["status"] == "unresolved"


def test_handoff_blocked_resolved_by_later_event(tmp_path):
    """Later lifecycle activity for the same ticket marks the block resolved."""
    from scripts.destination_context import _latest_handoff_blocked

    _write_events(
        tmp_path,
        [
            {
                "event_type": "HANDOFF_BLOCKED",
                "ticket_id": "CTL-2026-001a",
                "sequence_number": 5,
                "payload": {"reason": "stale checkpoint"},
            },
            {
                "event_type": "STATE_CHANGED",
                "ticket_id": "CTL-2026-001a",
                "sequence_number": 6,
            },
        ],
    )
    result = _latest_handoff_blocked(tmp_path)
    assert result is not None
    assert result["status"] == "resolved_by_STATE_CHANGED"


def test_handoff_blocked_absent_bus(tmp_path):
    """No bus file -> no hint (None), map must not crash."""
    from scripts.destination_context import _latest_handoff_blocked

    assert _latest_handoff_blocked(tmp_path) is None


# ---------------------------------------------------------------------------
# compute_motor_drift (WOT-2026-024j) — motor_sha staleness SIGNAL, never a gate
# ---------------------------------------------------------------------------


def _init_git_repo(root: Path) -> None:
    """Init a REAL (non-shallow) git repo with a working commit graph."""
    subprocess.run(["git", "init"], cwd=root, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=root,
        capture_output=True,
        check=True,
    )


def _commit(root: Path, filename: str, content: str) -> str:
    """Write filename, commit it, and return the new commit sha."""
    (root / filename).write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", f"add {filename}"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _make_motor_repo(tmp_path: Path) -> tuple[Path, str, str]:
    """Build a real git repo with 2 commits and an origin/main reference.

    Returns (motor_root, old_sha, origin_main_sha).
    The origin is a bare repo so that ``origin/main`` resolves locally.
    """
    motor_root = tmp_path / "motor"
    motor_root.mkdir()
    _init_git_repo(motor_root)
    old_sha = _commit(motor_root, "a.txt", "1")
    head_sha = _commit(motor_root, "b.txt", "2")
    # WOT-2026-047j: create a bare origin so origin/main is resolvable.
    bare_origin = tmp_path / "origin.git"
    bare_origin.mkdir()
    subprocess.run(
        ["git", "init", "--bare"],
        cwd=bare_origin,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", str(bare_origin)],
        cwd=motor_root,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "push", "origin", "main"],
        cwd=motor_root,
        capture_output=True,
        check=True,
    )
    return motor_root, old_sha, head_sha


def test_compute_motor_drift_old_sha_gives_warn_with_count(tmp_path):
    """Guard 4: link_sha is a valid ancestor != origin/main -> WARN with commit count."""
    motor_root, old_sha, origin_main_sha = _make_motor_repo(tmp_path)
    link = {"motor_root": str(motor_root), "motor_sha": old_sha}

    warning = compute_motor_drift(link)

    assert warning is not None
    assert "1 commits detras de origin/main" in warning
    assert old_sha[:12] in warning
    assert origin_main_sha[:12] in warning


def test_compute_motor_drift_head_sha_no_warn(tmp_path):
    """Guard 3: link_sha == origin/main -> no drift, returns None."""
    motor_root, _old_sha, origin_main_sha = _make_motor_repo(tmp_path)
    link = {"motor_root": str(motor_root), "motor_sha": origin_main_sha}

    assert compute_motor_drift(link) is None


def test_compute_motor_drift_missing_sha_soft_warn(tmp_path):
    """Guard 1: motor_sha absent -> soft WARN, no crash."""
    motor_root, _old_sha, _head_sha = _make_motor_repo(tmp_path)
    link = {"motor_root": str(motor_root)}

    warning = compute_motor_drift(link)

    assert warning is not None
    assert "sin motor_sha" in warning


def test_compute_motor_drift_unknown_sentinel_soft_warn(tmp_path):
    """Guard 1: motor_sha == 'unknown' (old-installer sentinel) -> soft WARN."""
    motor_root, _old_sha, _head_sha = _make_motor_repo(tmp_path)
    link = {"motor_root": str(motor_root), "motor_sha": "unknown"}

    warning = compute_motor_drift(link)

    assert warning is not None
    assert "sin motor_sha" in warning


def test_compute_motor_drift_unresolvable_sha_soft_warn_no_crash(tmp_path):
    """Guard 2: motor_sha does not resolve in the motor repo -> soft WARN,
    NEVER a crash. This is the guard that exists because
    `git rev-list --count <bad-sha>..HEAD` raises `fatal: Invalid revision
    range` for an unresolvable sha (verified by probe before writing this
    guard) -- without guard 2, this call would blow up compute_motor_drift.
    """
    motor_root, _old_sha, _head_sha = _make_motor_repo(tmp_path)
    link = {"motor_root": str(motor_root), "motor_sha": "0" * 40}

    warning = compute_motor_drift(link)

    assert warning is not None
    assert "no resoluble" in warning


def test_compute_motor_drift_mutation_guard(tmp_path):
    """Mutation-to-prove (DoD c): if the sha comparison were removed and
    compute_motor_drift always returned None, this test goes red."""
    motor_root, old_sha, _head_sha = _make_motor_repo(tmp_path)
    link = {"motor_root": str(motor_root), "motor_sha": old_sha}

    assert compute_motor_drift(link) is not None


def test_compute_motor_drift_names_distance_and_sha(tmp_path):
    """WOT-2026-047j DoD(3): a stale motor fixture produces a WARN that
    NOMBRA la distancia (commit count) AND the consumed motor_sha, so
    gate failures can distinguish 'stale motor' from 'missing mechanism'."""
    motor_root, old_sha, _origin_main_sha = _make_motor_repo(tmp_path)
    link = {"motor_root": str(motor_root), "motor_sha": old_sha}

    warning = compute_motor_drift(link)

    assert warning is not None
    # Must name the distance (commit count).
    assert "1 commits detras de origin/main" in warning
    # Must name the consumed motor_sha.
    assert old_sha[:12] in warning
    # Must name origin/main.
    assert "origin/main" in warning


def test_compute_motor_drift_compares_origin_main_not_head(tmp_path):
    """WOT-2026-047j DoD(1): drift is measured against origin/main, not HEAD.
    If motor_sha == origin/main but HEAD is ahead (unpushed commits), no WARN."""
    motor_root, _old_sha, origin_main_sha = _make_motor_repo(tmp_path)
    # Add a third commit that is local-only (not pushed to origin).
    _commit(motor_root, "c.txt", "3")
    # motor_sha == origin_main_sha -> should NOT warn despite HEAD being ahead.
    link = {"motor_root": str(motor_root), "motor_sha": origin_main_sha}

    assert compute_motor_drift(link) is None


def test_main_bootstrap_emits_drift_warn_for_stale_link(tmp_path, capsys):
    """Full --bootstrap flow: a destination whose link pins an old motor_sha
    prints the drift WARN on stdout and exits 0 (signal, not a gate)."""
    motor_root, old_sha, _origin_main_sha = _make_motor_repo(tmp_path)

    config_dir = tmp_path / ".agent" / "config"
    config_dir.mkdir(parents=True)
    payload = {
        "motor_root": str(motor_root),
        "destination_root": str(tmp_path.resolve()),
        "motor_version": "9.17.1",
        "motor_sha": old_sha,
        "destination_id": tmp_path.name,
        "ticket_prefix": "WOT",
        "created_at": "2026-07-19T00:00:00+00:00",
        "manifest_version": "1.0",
    }
    (config_dir / "motor_destination_link.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )

    exit_code = main(["--bootstrap", "--project-root", str(tmp_path)])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "motor drift" in captured.out
    assert "1 commits detras de origin/main" in captured.out

    map_file = tmp_path / ".agent" / "context" / "destination_map.md"
    content = map_file.read_text(encoding="utf-8")
    assert "Motor drift" in content


def test_main_bootstrap_no_drift_warn_when_sha_matches_head(tmp_path, capsys):
    """A link pinned to the CURRENT origin/main must not print a drift WARN."""
    motor_root, _old_sha, origin_main_sha = _make_motor_repo(tmp_path)

    config_dir = tmp_path / ".agent" / "config"
    config_dir.mkdir(parents=True)
    payload = {
        "motor_root": str(motor_root),
        "destination_root": str(tmp_path.resolve()),
        "motor_version": "9.17.1",
        "motor_sha": origin_main_sha,
        "destination_id": tmp_path.name,
        "ticket_prefix": "WOT",
        "created_at": "2026-07-19T00:00:00+00:00",
        "manifest_version": "1.0",
    }
    (config_dir / "motor_destination_link.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )

    exit_code = main(["--bootstrap", "--project-root", str(tmp_path)])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "motor drift" not in captured.out


# ---------------------------------------------------------------------------
# compute_contract_surface_drift (WOT-2026-053a) -- el discriminante NO es
# "cuantos commits", es "¿divergio el CONTRATO que voy a leer?".
#
# Origen medido (2026-08-08): una sesion leyo prompts del checkout PRINCIPAL
# stale y volo un batch de 3 tickets contra un contrato obsoleto. El unico
# aviso existente vivia en el CIERRE (`prepush_check.run_principal_freshness_
# check`), que informa DESPUES de haber volado. Este avisa en el ARRANQUE.
#
# Por que por SUPERFICIE y no por umbral N de commits: un N seria un umbral en
# MESETA sin barrido (AGENTS.md lo prohibe) -- 1 commit puede cambiar el prompt
# de cierre y 50 pueden no tocar `prompts/`. El discriminante es BINARIO y no
# exige justificar ningun numero.
# ---------------------------------------------------------------------------


def test_contract_surface_drift_warns_when_a_prompt_diverges(tmp_path):
    """Un fichero de `prompts/` que difiere entre primary y HEAD -> WARN que lo NOMBRA.

    MUTACION: si el discriminante pasara a contar commits en vez de mirar
    superficies, este test seguiria verde por accidente; por eso asserta el
    NOMBRE del fichero divergente, no el hecho de que haya drift.
    """
    motor_root = tmp_path / "motor"
    motor_root.mkdir()
    _init_git_repo(motor_root)
    (motor_root / "prompts").mkdir()
    primary = _commit(motor_root, "prompts/contrato.md", "v1")
    _commit(motor_root, "prompts/contrato.md", "v2-DIVERGENTE")

    warn = compute_contract_surface_drift(motor_root, primary, ref="HEAD")

    assert warn is not None
    assert "prompts/contrato.md" in warn
    assert "contract surface drift" in warn


def test_contract_surface_drift_silent_when_only_noncontract_files_change(tmp_path):
    """27 commits que NO tocan superficie contractual son RUIDO, no senal.

    Este es el control negativo que justifica el diseno: sin el, el WARN se
    dispararia por cualquier avance del motor y entrenaria a ignorarlo.
    """
    motor_root = tmp_path / "motor"
    motor_root.mkdir()
    _init_git_repo(motor_root)
    (motor_root / "prompts").mkdir()
    (motor_root / "tests").mkdir()
    primary = _commit(motor_root, "prompts/contrato.md", "v1")
    _commit(motor_root, "tests/test_algo.py", "irrelevante")
    _commit(motor_root, "README.md", "tambien irrelevante")

    assert compute_contract_surface_drift(motor_root, primary, ref="HEAD") is None


def test_contract_surface_drift_is_signal_never_gate(tmp_path):
    """Un motor_root ilegible NO revienta y NO propaga: devuelve None.

    Misma politica que `compute_motor_drift` (WOT-2026-024j): es SENAL, nunca
    gate. Un guard que revienta por git es peor que uno que calla.
    """
    assert compute_contract_surface_drift(tmp_path / "no-existe", "deadbeef") is None
