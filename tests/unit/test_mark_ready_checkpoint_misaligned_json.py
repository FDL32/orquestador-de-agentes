# WOT-2026-091g: `--mark-ready --json` con el checkpoint M3 desalineado no debe
# fallar en silencio.
#
# Defecto: la rama `pre_handoff_guard_failed` de `_handle_mark_ready` no
# propagaba `checkpoint_misaligned` al payload de HANDOFF_BLOCKED y, con
# `--json`, no imprimia nada a stdout (el guard solo imprime sin `--json`).
#
# Estos tests ejercen la ruta REAL: `_handle_mark_ready` con repo git en
# tmp_path y el guard REAL (`scripts/pre_handoff_guard.py` por subprocess).
# NO se mockea `_run_pre_handoff_guard`: hacerlo ocultaria justo el campo que
# se prueba. Solo se parchean los seams ajenos al guard (ronda del Builder,
# evidencia de implementacion, bus, efectos laterales de cierre).

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

from tests.test_pre_handoff_guard import init_git_repo
from tests.test_pre_handoff_multirepo import _git


_AGENT_DIR = Path(__file__).resolve().parent.parent.parent / ".agent"
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

TICKET = "WOT-2026-091g"


class _RecordingBus:
    """Bus minimo: registra los emit; no deriva estado previo del ticket."""

    def __init__(self) -> None:
        self.emitted: list[tuple[str, dict]] = []

    def read_events(self, **_kw) -> list:
        return []

    def latest_event(self, **_kw):
        return None

    def emit(self, *, event_type: str, payload: dict, **_kw) -> None:
        self.emitted.append((event_type, payload))


def _make_repo(tmp_path: Path, *, tag_on_initial: bool) -> Path:
    """Repo git con work_plan y execution_log commiteados, arbol limpio.

    tag_on_initial=True deja el tag M3 en el commit inicial (su subject NO
    nombra el ticket y HEAD es otro): DESALINEADO. False no crea tag aun.
    """
    repo = tmp_path / "repo"
    init_git_repo(repo)
    if tag_on_initial:
        _git(
            ["tag", "-a", f"checkpoint/review-{TICKET}", "-m", "M3 desalineado"],
            cwd=repo,
        )
    collab = repo / ".agent" / "collaboration"
    collab.mkdir(parents=True)
    (collab / "work_plan.md").write_text(
        "# Work Plan\n\n## Metadata\n"
        f"- **ID:** {TICKET}\n- **Estado:** APPROVED\n"
        "- **deliverable_type:** code\n\n"
        "## Files Likely Touched\n- `.agent/agent_controller.py`\n",
        encoding="utf-8",
    )
    (collab / "execution_log.md").write_text(
        "# Execution Log\n\n**Estado:** IN_PROGRESS\n\n", encoding="utf-8"
    )
    _git(["add", "-A"], cwd=repo)
    _git(["commit", "-m", f"wp {TICKET}"], cwd=repo)
    return repo


def _run_mark_ready(repo: Path, monkeypatch, *, json_output: bool = True):
    ac = importlib.import_module("agent_controller")
    collab = repo / ".agent" / "collaboration"
    bus = _RecordingBus()
    monkeypatch.setattr(ac, "PROJECT_ROOT", repo)
    monkeypatch.setattr(ac, "_MOTOR_ROOT", repo)
    monkeypatch.setattr(ac, "WORK_PLAN", collab / "work_plan.md")
    monkeypatch.setattr(ac, "EXEC_LOG", collab / "execution_log.md")
    monkeypatch.setattr(ac, "BUS_AVAILABLE", True)
    monkeypatch.setattr(ac, "event_bus", bus)
    monkeypatch.setattr(
        ac, "_ensure_active_builder_round", lambda *a, **kw: (True, None, None)
    )
    monkeypatch.setattr(
        ac,
        "_check_circuit_breaker",
        lambda *a, **kw: {
            "open": False,
            "reason": None,
            "failures": 0,
            "no_progress_count": 0,
        },
    )
    monkeypatch.setattr(ac, "_check_implementation_evidence", lambda *a, **kw: [])
    monkeypatch.setattr(ac, "_emit_builder_exit", lambda *a, **kw: None)
    monkeypatch.setattr(ac, "_release_builder_lock", lambda *a, **kw: None)
    rc = ac._handle_mark_ready(
        scope_override=None, json_output=json_output, force_mode=False
    )
    return rc, bus


def _blocked_payload(bus: _RecordingBus) -> dict:
    blocked = [p for t, p in bus.emitted if t == "HANDOFF_BLOCKED"]
    assert len(blocked) == 1, f"esperaba 1 HANDOFF_BLOCKED, hubo {bus.emitted}"
    return blocked[0]


def test_misaligned_checkpoint_prints_cause_json_to_stdout(
    tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """DoD (a): stdout con JSON que nombra la causa, no stdout vacio."""
    repo = _make_repo(tmp_path, tag_on_initial=True)

    rc, _bus = _run_mark_ready(repo, monkeypatch)

    out = capsys.readouterr().out
    assert rc == 1
    assert out.strip(), "stdout vacio: el fallo es silencioso"
    # Contrato de salida completo: cada campo con su valor concreto.
    assert json.loads(out) == {
        "status": "blocked",
        "reason": "pre_handoff_guard_failed",
        "checkpoint_misaligned": True,
        "checkpoint_tag": f"checkpoint/review-{TICKET}",
        "plan_id": TICKET,
    }


def test_misaligned_checkpoint_in_handoff_blocked_payload(
    tmp_path: Path, monkeypatch
) -> None:
    """DoD (b): el evento HANDOFF_BLOCKED lleva checkpoint_misaligned=True."""
    repo = _make_repo(tmp_path, tag_on_initial=True)

    rc, bus = _run_mark_ready(repo, monkeypatch)

    assert rc == 1
    payload = _blocked_payload(bus)
    assert payload["reason"] == "pre_handoff_guard_failed"
    assert payload["checkpoint_misaligned"] is True


def test_misaligned_checkpoint_without_json_prints_no_json_object(
    tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Sin --json no se imprime el objeto JSON nuevo (el texto lo da el guard)."""
    repo = _make_repo(tmp_path, tag_on_initial=True)

    rc, bus = _run_mark_ready(repo, monkeypatch, json_output=False)

    out = capsys.readouterr().out
    assert rc == 1
    assert '"checkpoint_misaligned"' not in out
    assert _blocked_payload(bus)["checkpoint_misaligned"] is True


def test_dirty_tree_cause_unchanged_silent_json_stdout(
    tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """DoD (d) control negativo: dirty_tree sigue sin imprimir nada con --json."""
    repo = _make_repo(tmp_path, tag_on_initial=False)
    _git(["tag", "-a", f"checkpoint/review-{TICKET}", "-m", "M3 en HEAD"], cwd=repo)
    (repo / "README.md").write_text("# cambiado sin commitear", encoding="utf-8")

    rc, bus = _run_mark_ready(repo, monkeypatch)

    assert rc == 1
    assert capsys.readouterr().out == ""
    payload = _blocked_payload(bus)
    assert payload["reason"] == "pre_handoff_guard_failed"
    assert payload["dirty_tree"] is True
    assert payload["missing_checkpoint"] is False
    assert payload.get("checkpoint_misaligned", False) is False


def test_missing_checkpoint_cause_unchanged_silent_json_stdout(
    tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """DoD (d) control negativo: missing_checkpoint sigue sin imprimir con --json."""
    repo = _make_repo(tmp_path, tag_on_initial=False)

    rc, bus = _run_mark_ready(repo, monkeypatch)

    assert rc == 1
    assert capsys.readouterr().out == ""
    payload = _blocked_payload(bus)
    assert payload["reason"] == "pre_handoff_guard_failed"
    assert payload["missing_checkpoint"] is True
    assert payload["dirty_tree"] is False
    assert payload.get("checkpoint_misaligned", False) is False
