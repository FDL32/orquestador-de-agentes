"""Tests de session_tracker + refresh post-close (WOT-2026-039d).

Contrato: al FINAL de un --session-close EXITOSO el tracker
`.session_state.json` se refresca (work_plan con ID resoluble) o se limpia
(sin ID resoluble); en un close FALLIDO no se toca. Antes del fix,
`save_session()` vivia solo en la rama STATUS del controller y el tracker
quedaba STALE apuntando a un ticket ajeno (caso 2026-07-15: falso
"[INFO] Session already completed" por `.session_state.json` stale).

La mutation de la ficha decide el test central: cerrar con el tracker
apuntando a un ticket AJENO -> tras el cierre el tracker NO apunta a ese
ticket (cubre las ramas i y ii).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


_MOTOR_ROOT = Path(__file__).resolve().parents[2]
_AGENT_DIR = _MOTOR_ROOT / ".agent"
for _p in (str(_MOTOR_ROOT), str(_AGENT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import session_tracker  # noqa: E402


@pytest.fixture()
def collab(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Collab dir sintetico: el tracker resuelve rutas via _collab_dir()."""
    collab_dir = tmp_path / ".agent" / "collaboration"
    collab_dir.mkdir(parents=True)
    monkeypatch.setattr(session_tracker, "_collab_dir", lambda: collab_dir)
    return collab_dir


def _tracker_file(collab_dir: Path) -> Path:
    return collab_dir / ".session_state.json"


def test_save_session_writes_active_plan_from_workplan(collab: Path):
    """Rama (i): work_plan con ID -> save_session escribe ese active_plan."""
    (collab / "work_plan.md").write_text(
        "# Work Plan\n- **ID:** WOT-2026-039d\n", encoding="utf-8"
    )
    session_tracker.save_session()
    data = json.loads(_tracker_file(collab).read_text(encoding="utf-8"))
    assert data["active_plan"] == "WOT-2026-039d"
    assert data["last_activity"]


def test_clear_session_removes_tracker_and_is_idempotent(collab: Path):
    """Rama (ii): clear_session elimina el fichero; segunda llamada = no-op."""
    _tracker_file(collab).write_text("{}", encoding="utf-8")
    session_tracker.clear_session()
    assert not _tracker_file(collab).exists()
    session_tracker.clear_session()  # idempotente, no lanza
    assert not _tracker_file(collab).exists()


def test_close_refresh_tracker_no_longer_points_to_foreign_ticket(
    collab: Path, monkeypatch: pytest.MonkeyPatch
):
    """MUTATION DE LA FICHA (039d): tracker con ticket AJENO antes del close.

    Tras el refresh post-close, el tracker NO apunta al ticket ajeno:
    - rama (i): work_plan cerrado con ID propio -> active_plan = ID propio;
    - rama (ii): sin ID resoluble -> tracker eliminado.
    Si alguien quita el refresh del camino de close (la mutation), el tracker
    conserva el ticket ajeno y AMBAS aserciones caen.
    """
    import agent_controller

    # Estado stale: el tracker apunta a un ticket AJENO.
    _tracker_file(collab).write_text(
        json.dumps({"active_plan": "WOT-2026-OTRO", "last_activity": "2026-01-01"}),
        encoding="utf-8",
    )

    # El refresh del controller usa session_tracker via import; parcheamos el
    # collab dir del tracker (fixture) y garantizamos disponibilidad.
    monkeypatch.setattr(agent_controller, "SESSION_TRACKER_AVAILABLE", True)
    monkeypatch.setattr(agent_controller, "save_session", session_tracker.save_session)
    monkeypatch.setattr(
        agent_controller, "clear_session", session_tracker.clear_session
    )

    # Rama (i): work_plan con ID propio.
    (collab / "work_plan.md").write_text(
        "# Work Plan\n- **ID:** WOT-2026-039d\n", encoding="utf-8"
    )
    agent_controller._refresh_session_tracker_after_close()
    data = json.loads(_tracker_file(collab).read_text(encoding="utf-8"))
    assert data["active_plan"] == "WOT-2026-039d"
    assert data["active_plan"] != "WOT-2026-OTRO"

    # Rama (ii): sin work_plan (ID no resoluble) -> limpiar.
    _tracker_file(collab).write_text(
        json.dumps({"active_plan": "WOT-2026-OTRO"}), encoding="utf-8"
    )
    (collab / "work_plan.md").unlink()
    agent_controller._refresh_session_tracker_after_close()
    assert not _tracker_file(collab).exists()


def test_session_close_success_invokes_refresh(monkeypatch: pytest.MonkeyPatch):
    """El CAMINO real: _handle_session_close exitoso -> refresh invocado.

    Ancla la mutation alcanzable: si alguien quita la llamada a
    `_refresh_session_tracker_after_close()` del camino de close (la
    regresion original: save_session solo en la rama STATUS), este test CAE.
    """
    import types
    from unittest.mock import patch

    import agent_controller

    calls: list[str] = []
    fake_result = types.SimpleNamespace(returncode=0, stdout="", stderr="")
    with (
        patch.object(agent_controller, "read_file", return_value=""),
        patch.object(agent_controller.subprocess, "run", return_value=fake_result),
        patch.object(agent_controller, "_sync_state_after_session_close"),
        patch.object(
            agent_controller,
            "_refresh_session_tracker_after_close",
            lambda: calls.append("refresh"),
        ),
    ):
        rc = agent_controller._handle_session_close(
            dry_run=False,
            skip_slow=True,
            ticket=None,
            tickets=None,
            force_mode=False,
            json_output=False,
        )
    assert rc == 0
    assert calls == ["refresh"]


def test_session_close_failure_preserves_tracker(monkeypatch: pytest.MonkeyPatch):
    """Rama (iii): close FALLIDO -> el refresh NO se invoca (tracker intacto)."""
    import types
    from unittest.mock import patch

    import agent_controller

    calls: list[str] = []
    fake_result = types.SimpleNamespace(returncode=1, stdout="", stderr="boom")
    with (
        patch.object(agent_controller, "read_file", return_value=""),
        patch.object(agent_controller.subprocess, "run", return_value=fake_result),
        patch.object(
            agent_controller,
            "_refresh_session_tracker_after_close",
            lambda: calls.append("refresh"),
        ),
    ):
        rc = agent_controller._handle_session_close(
            dry_run=False,
            skip_slow=True,
            ticket=None,
            tickets=None,
            force_mode=False,
            json_output=False,
        )
    assert rc == 1
    assert calls == []


def test_refresh_never_raises_when_tracker_fails(monkeypatch: pytest.MonkeyPatch):
    """Rama best-effort: un fallo del tracker NUNCA degrada el close."""
    import agent_controller

    monkeypatch.setattr(agent_controller, "SESSION_TRACKER_AVAILABLE", True)

    def _boom():
        raise RuntimeError("tracker roto")

    monkeypatch.setattr(session_tracker, "_get_current_plan_id", _boom)
    agent_controller._refresh_session_tracker_after_close()  # no lanza


def test_refresh_noop_when_tracker_unavailable(monkeypatch: pytest.MonkeyPatch):
    """Sin tracker disponible, el refresh es un no-op silencioso."""
    import agent_controller

    monkeypatch.setattr(agent_controller, "SESSION_TRACKER_AVAILABLE", False)
    agent_controller._refresh_session_tracker_after_close()  # no lanza
