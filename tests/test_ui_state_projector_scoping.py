"""Test UI State Projector with active ticket scoping."""

from __future__ import annotations

import json
from pathlib import Path
import sys

agent_dir = Path(__file__).parent.parent / ".agent"
if str(agent_dir) not in sys.path:
    sys.path.insert(0, str(agent_dir))

from runtime.ui_state_projector import UIStateProjector


def test_get_active_ticket_from_supervisor_state(tmp_path):
    """Test that _get_active_ticket_id reads from supervisor_state.json."""
    runtime_dir = tmp_path / "runtime"
    collab_dir = tmp_path / "collaboration"
    runtime_dir.mkdir()
    collab_dir.mkdir()

    # Setup supervisor state with specific active ticket
    supervisor_state = {
        "active_ticket": "WP-2026-028",
        "completed_tickets": ["WP-2026-024", "WP-2026-025"],
        "last_processed_sequence": 100,
        "last_action": "ACTIVATE",
    }
    supervisor_state_file = runtime_dir / "supervisor_state.json"
    supervisor_state_file.write_text(json.dumps(supervisor_state), encoding="utf-8")

    projector = UIStateProjector(runtime_dir=runtime_dir)

    # Verify active ticket is read from supervisor state
    assert projector._get_active_ticket_id() == "WP-2026-028"


def test_get_active_ticket_fallback_to_ninguno(tmp_path):
    """Test that _get_active_ticket_id returns NINGUNO when no supervisor state."""
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()

    projector = UIStateProjector(runtime_dir=runtime_dir)

    # No supervisor_state.json, no TURN.md → should return NINGUNO
    assert projector._get_active_ticket_id() == "NINGUNO"


def test_get_active_ticket_ignores_ninguno(tmp_path):
    """Test that _get_active_ticket_id ignores 'NINGUNO' in supervisor state."""
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()

    # Setup supervisor state with NINGUNO (edge case)
    supervisor_state = {
        "active_ticket": "NINGUNO",
        "completed_tickets": [],
        "last_processed_sequence": 0,
    }
    supervisor_state_file = runtime_dir / "supervisor_state.json"
    supervisor_state_file.write_text(json.dumps(supervisor_state), encoding="utf-8")

    projector = UIStateProjector(runtime_dir=runtime_dir)

    # Should return NINGUNO (not find it in supervisor state)
    assert projector._get_active_ticket_id() == "NINGUNO"


def test_get_active_ticket_fallback_to_turn_md_table_format(tmp_path):
    """Test that _get_active_ticket_id reads Plan ID from TURN.md table format.

    Critical test: validates fallback when supervisor_state.json is missing/corrupted.
    """
    runtime_dir = tmp_path / "runtime"
    collab_dir = tmp_path / "collaboration"
    runtime_dir.mkdir()
    collab_dir.mkdir()

    # Create TURN.md with actual table format (no supervisor_state.json)
    turn_content = """# TURNO ACTUAL

**Ultima actualizacion:** 2026-05-11 18:46:22

---

## Agente Activo

| Campo | Valor |
|-------|-------|
| **ROL** | **BUILDER** |
| **Plan ID** | WP-2026-030 |
| **Tipo** | IMPLEMENTATION |
| **Accion** | IMPLEMENT |

---

## Instruccion

> Implementar feature X

---

*Generado por agent_controller.py v5*
"""
    (collab_dir / "TURN.md").write_text(turn_content, encoding="utf-8")

    # Create projector with correct paths from start
    projector = UIStateProjector(runtime_dir=runtime_dir)
    # Override paths to use tmp_path
    projector.collaboration_dir = collab_dir
    projector.turn_path = collab_dir / "TURN.md"

    # Should extract WP-2026-030 from TURN.md table
    assert projector._get_active_ticket_id() == "WP-2026-030"


def test_get_active_ticket_fallback_ignores_ninguno_in_turn_md(tmp_path):
    """Test that fallback to TURN.md respects NINGUNO as invalid ticket."""
    runtime_dir = tmp_path / "runtime"
    collab_dir = tmp_path / "collaboration"
    runtime_dir.mkdir()
    collab_dir.mkdir()

    # Create TURN.md with NINGUNO in Plan ID
    turn_content = """# TURNO ACTUAL

| Campo | Valor |
|-------|-------|
| **ROL** | **MANAGER** |
| **Plan ID** | NINGUNO |
| **Accion** | CREATE_PLAN |
"""
    (collab_dir / "TURN.md").write_text(turn_content, encoding="utf-8")

    projector = UIStateProjector(runtime_dir=runtime_dir)
    projector.collaboration_dir = collab_dir
    projector.turn_path = collab_dir / "TURN.md"

    # Should return NINGUNO (fallback respects NINGUNO in TURN.md)
    assert projector._get_active_ticket_id() == "NINGUNO"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
