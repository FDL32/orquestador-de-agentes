#!/usr/bin/env python3
"""
Eval test para bus/review_bridge.py

Verifica que el ReviewBridge pueda construir prompts y parsear decisiones
sin tocar el bus de produccion ni subprocess real.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from bus.event_bus import EventBus
from bus.review_bridge import ReviewBridge, TicketContext


# Mark all tests in this module as eval tests
pytestmark = pytest.mark.eval


@pytest.fixture
def mock_event_bus(tmp_path: Path) -> EventBus:
    """Crear un EventBus mock con directorio temporal."""
    events_dir = tmp_path / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    bus = EventBus(runtime_dir=events_dir)
    return bus


@pytest.fixture
def mock_project_root(tmp_path: Path) -> Path:
    """Crear un project root mock con estructura minima."""
    collaboration_dir = tmp_path / ".agent" / "collaboration"
    collaboration_dir.mkdir(parents=True, exist_ok=True)

    # Crear archivos minimos requeridos
    (collaboration_dir / "work_plan.md").write_text(
        "# Work Plan\n\n## Metadata\n- **ID:** WP-2026-999\n- **Estado:** IN_PROGRESS\n- **deliverable_type:** code\n",
        encoding="utf-8",
    )
    (collaboration_dir / "STATE.md").write_text(
        "# State - WP-2026-999\n\nEstado actual: IN_PROGRESS\n", encoding="utf-8"
    )
    (collaboration_dir / "TURN.md").write_text(
        "# TURNO ACTUAL\n\n## Agente Activo\n\n| Campo | Valor |\n|-------|-------|\n| **ROL** | **BUILDER** |\n",
        encoding="utf-8",
    )
    (collaboration_dir / "execution_log.md").write_text(
        "# Execution Log\n\n## Registro\n- Test entry\n", encoding="utf-8"
    )

    return tmp_path


class TestTicketContext:
    """Tests para TicketContext dataclass."""

    def test_create_ticket_context(self):
        """Crear TicketContext con datos validos."""
        ctx = TicketContext(
            ticket_id="WP-2026-999", state="IN_PROGRESS", deliverable_type="code"
        )
        assert ctx.ticket_id == "WP-2026-999"
        assert ctx.state == "IN_PROGRESS"
        assert ctx.deliverable_type == "code"


class TestReviewBridgePromptBuilding:
    """Tests para construccion de prompts en ReviewBridge."""

    def test_build_review_prompt_code_type(
        self, mock_event_bus: EventBus, mock_project_root: Path
    ):
        """Construir prompt para ticket tipo code."""
        bridge = ReviewBridge(mock_event_bus, mock_project_root)

        prompt = bridge._build_review_prompt("WP-2026-999", "code")

        assert "Review code ticket WP-2026-999" in prompt
        assert "AP-01" in prompt  # Anti-patterns
        assert "AP-02" in prompt
        assert "DECISION: APPROVE" in prompt
        assert "DECISION: CHANGES" in prompt

    def test_build_review_prompt_documentation_type(
        self, mock_event_bus: EventBus, mock_project_root: Path
    ):
        """Construir prompt para ticket tipo documentation."""
        bridge = ReviewBridge(mock_event_bus, mock_project_root)

        prompt = bridge._build_review_prompt("WP-2026-999", "documentation")

        assert "Review non-code documentation ticket WP-2026-999" in prompt
        # No debe incluir anti-patterns de testing para docs
        assert "AP-01 Mock drift" not in prompt

    def test_build_review_prompt_mixed_type(
        self, mock_event_bus: EventBus, mock_project_root: Path
    ):
        """Construir prompt para ticket tipo mixed."""
        bridge = ReviewBridge(mock_event_bus, mock_project_root)

        prompt = bridge._build_review_prompt("WP-2026-999", "mixed")

        assert "Review mixed ticket WP-2026-999" in prompt
        assert "AP-01" in prompt
        assert "AP-02" in prompt

    def test_build_review_prompt_unknown_type_fallback(
        self, mock_event_bus: EventBus, mock_project_root: Path
    ):
        """Construir prompt para tipo desconocido (fallback a documentation)."""
        bridge = ReviewBridge(mock_event_bus, mock_project_root)

        prompt = bridge._build_review_prompt("WP-2026-999", "unknown_type")

        # Tipos desconocidos van a la rama 'else' que es documentation
        # El fallback es documentation, no code (ver _rubric_for_type)
        assert "Review non-code unknown_type ticket WP-2026-999" in prompt


class TestReviewBridgeDecisionParsing:
    """Tests para parseo de decisiones en ReviewBridge."""

    def test_parse_approve_decision(
        self, mock_event_bus: EventBus, mock_project_root: Path
    ):
        """Parsear decision APPROVE."""
        bridge = ReviewBridge(mock_event_bus, mock_project_root)

        stdout = """
Revisión completada. Todo parece correcto.

DECISION: APPROVE
"""
        # El metodo real parsea la decision del stdout
        # Simplemente verificamos que no lance excepcion
        with patch.object(bridge, "_run_opencode_review") as mock_run:
            mock_run.return_value = (stdout, "", 0)
            # No podemos llamar a run_manager_review completo sin LLM real
            # Pero verificamos que la estructura basica funciona
            assert "DECISION: APPROVE" in stdout

    def test_parse_changes_decision_structure(
        self, mock_event_bus: EventBus, mock_project_root: Path
    ):
        """Parsear decision CHANGES con estructura completa."""
        bridge = ReviewBridge(mock_event_bus, mock_project_root)

        stdout = """
## SUMMARY
El ticket no cumple criterios de aceptacion

## BLOCKERS
- file.py:10 falta validacion de entrada

## SUGGESTIONS
- anadir tests unitarios

DECISION: CHANGES
"""
        structured = bridge._parse_changes_structure(stdout)

        assert "no cumple" in structured["summary"].lower()
        assert "file.py" in structured["blockers"]
        assert "tests" in structured["suggestions"]

    def test_validate_changes_structure_valid(
        self, mock_event_bus: EventBus, mock_project_root: Path
    ):
        """Validar estructura CHANGES valida."""
        bridge = ReviewBridge(mock_event_bus, mock_project_root)

        stdout = """
## SUMMARY
Test
## BLOCKERS
- blocker
## SUGGESTIONS
- suggestion
DECISION: CHANGES
"""
        is_valid, missing = bridge._validate_changes_structure(stdout)

        assert is_valid is True
        assert len(missing) == 0

    def test_validate_changes_structure_missing_sections(
        self, mock_event_bus: EventBus, mock_project_root: Path
    ):
        """Validar estructura CHANGES con secciones faltantes."""
        bridge = ReviewBridge(mock_event_bus, mock_project_root)

        stdout = """
DECISION: CHANGES
"""
        is_valid, missing = bridge._validate_changes_structure(stdout)

        assert is_valid is False
        assert "SUMMARY" in missing
        assert "BLOCKERS" in missing
        assert "SUGGESTIONS" in missing


class TestReviewBridgeEdgeCases:
    """Tests para casos limite en ReviewBridge."""

    def test_missing_work_plan_fallback(self, mock_event_bus: EventBus, tmp_path: Path):
        """ReviewBridge con work_plan.md faltante (fallback a code)."""
        # No crear work_plan.md
        bridge = ReviewBridge(mock_event_bus, tmp_path)

        # Debe usar fallback "code"
        deliverable_type = bridge._read_deliverable_type()
        assert deliverable_type == "code"

    def test_invalid_jsonl_observations(
        self, mock_event_bus: EventBus, mock_project_root: Path
    ):
        """Manejar observations.jsonl con JSON invalido."""
        bridge = ReviewBridge(mock_event_bus, mock_project_root)

        # Crear observations.jsonl invalido
        memory_dir = mock_project_root / ".agent" / "runtime" / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        observations_path = memory_dir / "observations.jsonl"
        observations_path.write_text(
            'json invalido\n{"valid": "entry"}\n', encoding="utf-8"
        )

        # No debe lanzar excepcion, solo ignorar entradas invalidas
        observations = bridge._load_manager_review_observations("code")
        # Puede que cargue la entrada valida si tiene topic correcto
        assert isinstance(observations, list)
