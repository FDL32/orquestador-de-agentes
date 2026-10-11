"""Barrier tests for check_archive_rename_complete (WOT-2026-010u).

Reproduce the delete+untracked limbo a real git repo enters when
archive_collaboration_artifacts.py moves a closed STRATEGY_/AUDIT_ artifact into
_archive/plan_audit/ without committing the rename. The guard must block with a
stable reason and a self-service remediation, without auto-committing or deleting.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = PROJECT_ROOT / "scripts" / "delivery_hygiene_check.py"

_spec = importlib.util.spec_from_file_location("delivery_hygiene_check", MODULE_PATH)
dhc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dhc)


def _init_git_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@e.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "T"], cwd=repo, check=True, capture_output=True
    )
    (repo / "README.md").write_text("# repo")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True
    )


def _collab(repo: Path) -> Path:
    d = repo / ".agent" / "collaboration"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _commit_artifact(repo: Path, rel: str, content: str) -> None:
    """Create + commit a tracked artifact so a later move shows as a delete."""
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    subprocess.run(["git", "add", "--", rel], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", f"add {rel}"], cwd=repo, check=True, capture_output=True
    )


def _simulate_archiver_move(repo: Path, name: str) -> tuple[str, str]:
    """Move a committed collaboration artifact into _archive/plan_audit/ WITHOUT
    committing (what shutil.move in the archiver leaves behind)."""
    old_rel = f".agent/collaboration/{name}"
    new_rel = f".agent/collaboration/_archive/plan_audit/{name}"
    old, new = repo / old_rel, repo / new_rel
    new.parent.mkdir(parents=True, exist_ok=True)
    new.write_text(old.read_text())
    old.unlink()
    return old_rel, new_rel


def test_uncommitted_archive_rename_blocks(tmp_path: Path) -> None:
    """Barrier: D AUDIT_*.md + ?? _archive/plan_audit/AUDIT_*.md is detected and
    blocked with the stable reason and a remediation naming both paths."""
    repo = tmp_path / "destino"
    _init_git_repo(repo)
    _collab(repo)
    _commit_artifact(repo, ".agent/collaboration/AUDIT_WOT-2026-999z.md", "audit")
    old_rel, new_rel = _simulate_archiver_move(repo, "AUDIT_WOT-2026-999z.md")

    result = dhc.check_archive_rename_complete(repo)

    assert result.passed is False
    blob = " ".join([result.message, *(result.details or [])])
    assert "archive_rename_uncommitted" in blob
    assert old_rel in blob and new_rel in blob  # origen + destino
    assert "git add" in blob and "git commit" in blob  # remediacion self-service
    # No auto-commit / no delete: the archived copy still exists, original gone.
    assert (repo / new_rel).exists()
    assert not (repo / old_rel).exists()


def test_strategy_and_plan_prefixes_also_detected(tmp_path: Path) -> None:
    repo = tmp_path / "destino"
    _init_git_repo(repo)
    _collab(repo)
    for name in ("STRATEGY_WOT-2026-999z.md", "PLAN_WP-2026-001a.md"):
        _commit_artifact(repo, f".agent/collaboration/{name}", "x")
        _simulate_archiver_move(repo, name)
    result = dhc.check_archive_rename_complete(repo)
    assert result.passed is False
    assert "STRATEGY_WOT-2026-999z.md" in " ".join(result.details or [])
    assert "PLAN_WP-2026-001a.md" in " ".join(result.details or [])


def test_bare_delete_without_archived_copy_is_not_flagged(tmp_path: Path) -> None:
    """No false positive: a deletion WITHOUT an archived copy is a normal dirty
    file, not an incomplete rename. This guard must stay silent on it."""
    repo = tmp_path / "destino"
    _init_git_repo(repo)
    _collab(repo)
    _commit_artifact(repo, ".agent/collaboration/AUDIT_WOT-2026-888y.md", "audit")
    (repo / ".agent" / "collaboration" / "AUDIT_WOT-2026-888y.md").unlink()
    # No copy under _archive/plan_audit/.
    result = dhc.check_archive_rename_complete(repo)
    assert result.passed is True


def test_unrelated_untracked_file_is_not_flagged(tmp_path: Path) -> None:
    """No false positive for unrelated files."""
    repo = tmp_path / "destino"
    _init_git_repo(repo)
    _collab(repo)
    (repo / "scratch.txt").write_text("noise")
    result = dhc.check_archive_rename_complete(repo)
    assert result.passed is True


def test_clean_tree_passes(tmp_path: Path) -> None:
    repo = tmp_path / "destino"
    _init_git_repo(repo)
    result = dhc.check_archive_rename_complete(repo)
    assert result.passed is True
    assert "pendientes" in result.message


def test_stable_reason_is_contract_for_closeout_011a(tmp_path: Path) -> None:
    """WOT-2026-011a depends on the stable reason `archive_rename_uncommitted`
    surfacing in details so the closeout step can forward it verbatim. Lock it
    so a future edit to the helper cannot silently drop the contract string."""
    repo = tmp_path / "destino"
    _init_git_repo(repo)
    _collab(repo)
    _commit_artifact(repo, ".agent/collaboration/STRATEGY_WOT-2026-999z.md", "s")
    _simulate_archiver_move(repo, "STRATEGY_WOT-2026-999z.md")

    result = dhc.check_archive_rename_complete(repo)

    assert result.passed is False
    assert result.message == "ARCHIVE_RENAME_UNCOMMITTED"
    assert any("archive_rename_uncommitted" in d for d in (result.details or []))


# --- WOT-2026-055d: follow-up del motor vs el repo que aloja la fila -----------
# El workspace de dogfooding del motor se declara con `.agent/config/motor_workspace.txt`
# (un NOMBRE resuelto contra parent(motor_root), WOT-2026-053h) o con el campo
# `motor_workspace_root` del link del destino; su `ticket_prefix` identifica los
# follow-ups del motor. Una fila con `delivery_authority: repo_motor` de ESE prefijo
# escrita en otro backlog debe FALLAR; una de prefijo ajeno legitimamente entregada
# al motor (WOT-2026-066i) NO.

_ROW = (
    "| Alta | {tid} | deliverable_type: code, delivery_authority: {auth} "
    "[LINEA: test] | pending | - | - |"
)
_FICHA = (
    "## Fichas detalladas\n\n### {tid} - titulo\n- **delivery_authority:** {auth}\n"
)


def _write_backlog(root: Path, body: str) -> None:
    path = root / ".agent" / "collaboration"
    path.mkdir(parents=True, exist_ok=True)
    (path / "backlog.md").write_text("# Backlog\n\n## Vista rapida\n\n" + body)


def _write_link(root: Path, fields: dict) -> None:
    cfg = root / ".agent" / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    import json

    (cfg / "motor_destination_link.json").write_text(json.dumps(fields))


def _setup_motor(tmp_path: Path, prefix: str = "WOT") -> tuple[Path, Path]:
    """Motor declara su workspace `ws`; `ws` declara su `ticket_prefix`."""
    motor = tmp_path / "motor"
    cfg = motor / ".agent" / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "motor_workspace.txt").write_text("ws\n")
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    _write_link(
        ws,
        {
            "motor_root": str(motor),
            "destination_root": str(ws),
            "ticket_prefix": prefix,
        },
    )
    return motor, ws


def test_backlog_motor_followup_row_in_foreign_backlog_fails(tmp_path: Path) -> None:
    """Barrier (WOT-2026-055d): a motor follow-up (prefix of the motor workspace,
    `delivery_authority: repo_motor`) in a backlog that is NOT the motor's workspace
    FAILS, naming the ticket."""
    motor, _ws = _setup_motor(tmp_path)
    dest = tmp_path / "dest"
    _write_backlog(dest, _ROW.format(tid="WOT-2026-999z", auth="repo_motor"))

    result = dhc.check_backlog_delivery_authority_location(dest, motor)

    assert result.passed is False
    assert result.message == "BACKLOG_DELIVERY_AUTHORITY_MISPLACED"
    blob = " ".join(result.details or [])
    assert "WOT-2026-999z" in blob
    assert "backlog_delivery_authority_misplaced" in blob


def test_backlog_motor_followup_ficha_in_foreign_backlog_fails(tmp_path: Path) -> None:
    """Same barrier via the DETAILED-FICHA form (`### <ID>` + field on its own
    line), not just the `## Vista rapida` table row."""
    motor, _ws = _setup_motor(tmp_path)
    dest = tmp_path / "dest"
    _write_backlog(dest, _FICHA.format(tid="WOT-2026-888y", auth="repo_motor"))

    result = dhc.check_backlog_delivery_authority_location(dest, motor)

    assert result.passed is False
    assert "WOT-2026-888y" in " ".join(result.details or [])


def test_backlog_motor_followup_in_motor_workspace_passes(tmp_path: Path) -> None:
    """CONTROL NEGATIVO: the SAME row, in the motor's own dogfooding workspace,
    is legitimate (3.7 registers motor follow-ups there) -> green."""
    motor, ws = _setup_motor(tmp_path)
    _write_backlog(ws, _ROW.format(tid="WOT-2026-999z", auth="repo_motor"))

    result = dhc.check_backlog_delivery_authority_location(ws, motor)

    assert result.passed is True


def test_backlog_foreign_prefix_repo_motor_row_is_legitimate(tmp_path: Path) -> None:
    """NO false positive (WOT-2026-066i): a ticket of a FOREIGN prefix that
    declares `delivery_authority: repo_motor` (delivered in motor commits) lives
    legitimately in its OWN destination's backlog. Real case: CTL-2026-012j."""
    motor, _ws = _setup_motor(tmp_path)
    dest = tmp_path / "dest"
    _write_backlog(dest, _ROW.format(tid="CTL-2026-012j", auth="repo_motor"))

    result = dhc.check_backlog_delivery_authority_location(dest, motor)

    assert result.passed is True


def test_backlog_repo_destino_row_in_foreign_backlog_passes(tmp_path: Path) -> None:
    """CONTROL NEGATIVO: a `repo_destino` row in a foreign backlog is not the
    misplacement this check hunts -> green (no false positive)."""
    motor, _ws = _setup_motor(tmp_path)
    dest = tmp_path / "dest"
    _write_backlog(dest, _ROW.format(tid="WOT-2026-999z", auth="repo_destino"))

    result = dhc.check_backlog_delivery_authority_location(dest, motor)

    assert result.passed is True


def test_backlog_authority_skips_when_motor_workspace_undetermined(
    tmp_path: Path,
) -> None:
    """LIMITE DECLARADO: sin `motor_workspace.txt` ni `motor_workspace_root` el
    workspace del motor no es determinable -> skip visible (verde), NUNCA un
    falso rojo sobre el propio workspace del motor cuando aun no se declara."""
    motor = tmp_path / "motor"
    (motor / ".agent" / "config").mkdir(parents=True)
    dest = tmp_path / "dest"
    _write_backlog(dest, _ROW.format(tid="WOT-2026-999z", auth="repo_motor"))

    result = dhc.check_backlog_delivery_authority_location(dest, motor)

    assert result.passed is True
    assert "no determinable" in result.message


def test_backlog_authority_uses_link_motor_workspace_when_declared(
    tmp_path: Path,
) -> None:
    """Señal 2: cuando el link del destino declara `motor_workspace_root`, el
    check decide sin depender de `motor_workspace.txt`. Follow-up ajeno -> FAIL;
    el propio workspace del motor -> PASS."""
    motor = tmp_path / "motor"
    (motor / ".agent" / "config").mkdir(parents=True)

    ws = tmp_path / "ws"
    _write_link(
        ws,
        {
            "motor_root": str(motor),
            "motor_workspace_root": str(ws),
            "ticket_prefix": "WOT",
        },
    )
    _write_backlog(ws, _ROW.format(tid="WOT-2026-999z", auth="repo_motor"))
    assert dhc.check_backlog_delivery_authority_location(ws, motor).passed is True

    dest = tmp_path / "dest"
    _write_link(
        dest,
        {
            "motor_root": str(motor),
            "motor_workspace_root": str(ws),
            "ticket_prefix": "CTL",
        },
    )
    _write_backlog(dest, _ROW.format(tid="WOT-2026-999z", auth="repo_motor"))
    assert dhc.check_backlog_delivery_authority_location(dest, motor).passed is False


def test_backlog_authority_resolves_motor_root_from_own_link(tmp_path: Path) -> None:
    """El check corre en la ruta de cierre aunque el llamante no pase
    `motor_root`: lo resuelve del link del propio destino."""
    motor, _ws = _setup_motor(tmp_path)
    dest = tmp_path / "dest"
    _write_link(dest, {"motor_root": str(motor)})
    _write_backlog(dest, _ROW.format(tid="WOT-2026-999z", auth="repo_motor"))

    # motor_root omitted on purpose.
    result = dhc.check_backlog_delivery_authority_location(dest)

    assert result.passed is False
    assert "WOT-2026-999z" in " ".join(result.details or [])
