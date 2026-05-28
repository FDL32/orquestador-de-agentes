#!/usr/bin/env python
"""Tests para validate_ticket_prose.py.

Cobertura requerida por WP-2026-162:
- Cada regla de deteccion tiene test positivo (dispara warning) y negativo (no dispara)
- Fixture defectuoso genera warnings con IDs y sugerencias
- Fixture limpio no genera warnings
- AUDIT sin TP Check genera warning audit-missing-tp-check
- Exit code 0 en todos los casos
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


# Add scripts dir to path
scripts_dir = Path(__file__).parent.parent / "scripts"
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

from validate_ticket_prose import (
    ValidationResult,
    detect_audit_missing_tp_check,
    detect_diffuse_objective,
    detect_ghost_dependency,
    detect_imprecise_files_touched,
    detect_imprecise_passive,
    detect_lazy_extremes,
    detect_missing_architectural_decision,
    detect_missing_nongoals,
    detect_nonverifiable_criteria,
    detect_oversized_ticket,
    detect_throat_clearing,
    detect_vague_declarative,
    format_output,
    validate_ticket_prose,
)


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def clean_plan() -> str:
    """Plan limpio sin warnings detectables."""
    return """# Work Plan - WP-2026-TEST

## Metadata
- **ID:** WP-2026-TEST
- **Estado:** APPROVED
- **deliverable_type:** code

## Objetivo
Implementar validador de prosa que detecte 11 patrones y emita warnings con regla, evidencia y sugerencia.
Criterio: `python scripts/validate_ticket_prose.py` sale con exit code 0.

## Non-goals
- No bloquear el flujo por warnings de prosa.
- No calcular metricas F1 o precision.
- No reescribir el catalogo TP de WP-2026-161.

## Decision Arquitectonica
Validador standalone en `scripts/validate_ticket_prose.py` con 11 reglas de prosa + 1 estructural.

## Fases
### Fase 1: validador de prosa
- Archivos: `scripts/validate_ticket_prose.py`

### Fase 2: integracion
- Archivos: `.agent/agent_controller.py`

## Files Likely Touched
- `scripts/validate_ticket_prose.py`
- `tests/test_validate_ticket_prose.py`
- `.agent/agent_controller.py`

## Criterios de aceptacion
- `python scripts/validate_ticket_prose.py` con exit code 0.
- `pytest tests/test_validate_ticket_prose.py -q` verde.
"""


@pytest.fixture
def defective_plan() -> str:
    """Plan con multiples defectos de prosa."""
    return """# Work Plan - WP-2026-TEST

## Metadata
- **ID:** WP-2026-TEST
- **Estado:** APPROVED

## Objetivo
Este ticket tiene como objetivo mejorar la calidad de los tickets de forma significativa.
El proposito de este plan es reforzar el sistema.

## Non-goals


## Fases
### Fase 1: hacer algo
### Fase 2: optimizar cosas
### Fase 3: varias fases mas
### Fase 4: otra fase
### Fase 5: fase cinco
### Fase 6: fase seis

## Files Likely Touched
- `scripts/**/*.py`
- `tests/**/*`
- `src/`

## Criterios de aceptacion
El sistema debe ser mejorado significativamente.
Se realizaran pruebas para verificar que todo funciona correctamente.
"""


@pytest.fixture
def plan_missing_audit(tmp_path: Path) -> Path:
    """Crea un work_plan.md en un directorio sin AUDIT."""
    collab_dir = tmp_path / "collab"
    collab_dir.mkdir()
    work_plan = collab_dir / "work_plan.md"
    work_plan.write_text("# Plan\n\n## Metadata\n- **ID:** TEST\n", encoding="utf-8")
    return work_plan, collab_dir


@pytest.fixture
def plan_with_audit_no_tp_check(tmp_path: Path) -> tuple[Path, Path]:
    """Crea work_plan.md y AUDIT sin TP Check."""
    collab_dir = tmp_path / "collab"
    collab_dir.mkdir()
    work_plan = collab_dir / "work_plan.md"
    work_plan.write_text("# Plan\n\n## Metadata\n- **ID:** TEST\n", encoding="utf-8")
    audit = collab_dir / "AUDIT_WP-TEST.md"
    audit.write_text("# Audit\n\nSin TP Check\n", encoding="utf-8")
    return work_plan, collab_dir


@pytest.fixture
def plan_with_audit_tp_check(tmp_path: Path) -> tuple[Path, Path]:
    """Crea work_plan.md y AUDIT con TP Check."""
    collab_dir = tmp_path / "collab"
    collab_dir.mkdir()
    work_plan = collab_dir / "work_plan.md"
    work_plan.write_text("# Plan\n\n## Metadata\n- **ID:** TEST\n", encoding="utf-8")
    audit = collab_dir / "AUDIT_WP-TEST.md"
    audit.write_text("# Audit\n\n## TP Check\n- TP-01: verificado\n", encoding="utf-8")
    return work_plan, collab_dir


# ============================================================================
# TESTS DE REGLAS DE PROSA INDIVIDUALES
# ============================================================================


class TestDetectThroatClearing:
    """Tests para detect_throat_clearing."""

    def test_detects_throat_clearing(self):
        """Detecta preambulos redundantes."""
        content = "Este ticket tiene como objetivo implementar X"
        warnings = detect_throat_clearing(content)
        assert len(warnings) == 1
        assert warnings[0]["rule_id"] == "TP-PROSE-01"
        assert warnings[0]["rule_name"] == "throat-clearing"

    def test_no_throat_clearing(self):
        """No detecta cuando no hay preambulo."""
        content = "Implementar validador de prosa con 11 reglas."
        warnings = detect_throat_clearing(content)
        assert len(warnings) == 0


class TestDetectVagueDeclarative:
    """Tests para detect_vague_declarative."""

    def test_detects_vague_mejorar(self):
        """Detecta 'mejorar' sin metrica."""
        content = "Mejorar la calidad del sistema"
        warnings = detect_vague_declarative(content)
        assert len(warnings) == 1
        assert warnings[0]["rule_id"] == "TP-PROSE-02"

    def test_no_vague_with_metric(self):
        """No detecta cuando hay metrica."""
        content = "Mejorar la cobertura de tests del 80% al 95%"
        warnings = detect_vague_declarative(content)
        assert len(warnings) == 0


class TestDetectImprecisePassive:
    """Tests para detect_imprecise_passive."""

    def test_detects_passive_sera_realizado(self):
        """Detecta voz pasiva 'sera realizado'."""
        content = "El validador sera realizado por el Builder"
        warnings = detect_imprecise_passive(content)
        assert len(warnings) == 1
        assert warnings[0]["rule_name"] == "pasivo-impreciso"

    def test_no_passive_active_voice(self):
        """No detecta con voz activa."""
        content = "Builder implementa el validador"
        warnings = detect_imprecise_passive(content)
        assert len(warnings) == 0


class TestDetectLazyExtremes:
    """Tests para detect_lazy_extremes."""

    def test_detects_cosas(self):
        """Detecta termino vago 'cosas'."""
        content = "Arreglar varias cosas en el codigo"
        warnings = detect_lazy_extremes(content)
        assert len(warnings) >= 1

    def test_no_lazy_specific(self):
        """No detecta cuando es especifico."""
        content = "Arreglar 3 bugs en validate_ticket_prose.py"
        warnings = detect_lazy_extremes(content)
        assert len(warnings) == 0


class TestDetectDiffuseObjective:
    """Tests para detect_diffuse_objective."""

    def test_detects_diffuse_objective(self):
        """Detecta objetivo sin criterio verificable."""
        content = """## Objetivo
Mejorar significativamente la calidad del sistema de validacion.
"""
        warnings = detect_diffuse_objective(content)
        assert len(warnings) == 1
        assert warnings[0]["rule_id"] == "TP-PROSE-05"

    def test_no_diffuse_with_command(self):
        """No detecta cuando hay comando verificable."""
        content = """## Objetivo
Implementar validador. Criterio: `python scripts/validate.py` sale con exit code 0.
"""
        warnings = detect_diffuse_objective(content)
        assert len(warnings) == 0


class TestDetectMissingNonGoals:
    """Tests para detect_missing_nongoals."""

    def test_detects_missing_nongoals(self):
        """Detecta seccion Non-goals ausente."""
        content = "# Plan\n\n## Objetivo\nTest\n"
        warnings = detect_missing_nongoals(content)
        assert len(warnings) == 1
        assert warnings[0]["rule_id"] == "TP-PROSE-06"

    def test_no_missing_nongoals(self, clean_plan: str):
        """No detecta cuando Non-goals existe con contenido."""
        warnings = detect_missing_nongoals(clean_plan)
        assert len(warnings) == 0


class TestDetectNonverifiableCriteria:
    """Tests para detect_nonverifiable_criteria."""

    def test_detects_nonverifiable_criteria(self):
        """Detecta criterios sin comando/test."""
        content = """## Criterios de aceptacion
El sistema funciona correctamente y es robusto.
"""
        warnings = detect_nonverifiable_criteria(content)
        assert len(warnings) == 1
        assert warnings[0]["rule_id"] == "TP-PROSE-07"

    def test_no_nonverifiable_with_command(self, clean_plan: str):
        """No detecta cuando hay comando citado."""
        warnings = detect_nonverifiable_criteria(clean_plan)
        assert len(warnings) == 0


class TestDetectImpreciseFilesTouched:
    """Tests para detect_imprecise_files_touched."""

    def test_detects_wildcards(self):
        """Detecta comodines en Files Likely Touched."""
        content = """## Files Likely Touched
- `scripts/**/*.py`
- `tests/**/*`
"""
        warnings = detect_imprecise_files_touched(content)
        assert len(warnings) == 1
        assert warnings[0]["rule_id"] == "TP-PROSE-08"

    def test_no_wildcards_specific_files(self, clean_plan: str):
        """No detecta con archivos especificos."""
        warnings = detect_imprecise_files_touched(clean_plan)
        assert len(warnings) == 0


class TestDetectOversizedTicket:
    """Tests para detect_oversized_ticket."""

    def test_detects_many_files(self):
        """Detecta ticket con mas de 10 archivos."""
        files = "\n".join([f"- `file{i}.py`" for i in range(15)])
        content = f"""## Files Likely Touched
{files}
"""
        warnings = detect_oversized_ticket(content)
        assert len(warnings) >= 1
        assert warnings[0]["rule_id"] == "TP-PROSE-09"

    def test_detects_many_phases(self):
        """Detecta ticket con mas de 5 fases."""
        phases = "\n".join([f"### Fase {i}: descripcion" for i in range(1, 8)])
        content = f"""## Fases
{phases}
"""
        warnings = detect_oversized_ticket(content)
        assert len(warnings) >= 1

    def test_no_oversized(self, clean_plan: str):
        """No detecta ticket de tamano normal."""
        warnings = detect_oversized_ticket(clean_plan)
        assert len(warnings) == 0


class TestDetectMissingArchitecturalDecision:
    """Tests para detect_missing_architectural_decision."""

    def test_detects_missing_decision(self):
        """Detecta Decision Arquitectonica ausente."""
        content = "# Plan\n\n## Objetivo\nTest\n"
        warnings = detect_missing_architectural_decision(content)
        assert len(warnings) == 1
        assert warnings[0]["rule_id"] == "TP-PROSE-10"

    def test_no_missing_decision(self, clean_plan: str):
        """No detecta cuando existe la seccion."""
        warnings = detect_missing_architectural_decision(clean_plan)
        assert len(warnings) == 0


class TestDetectGhostDependency:
    """Tests para detect_ghost_dependency."""

    def test_detects_ghost_dependency(self):
        """Detecta mencion de libreria nueva sin verificar."""
        content = "Usar la libreria requests para HTTP"
        warnings = detect_ghost_dependency(content)
        assert len(warnings) == 1
        assert warnings[0]["rule_id"] == "TP-PROSE-11"

    def test_no_ghost_dependency(self, clean_plan: str):
        """No detecta cuando no hay menciones de libs nuevas."""
        warnings = detect_ghost_dependency(clean_plan)
        assert len(warnings) == 0


# ============================================================================
# TESTS DE VERIFICACION ESTRUCTURAL (AUDIT)
# ============================================================================


class TestDetectAuditMissingTpCheck:
    """Tests para detect_audit_missing_tp_check."""

    def test_no_audit_files(self, plan_missing_audit: tuple):
        """Emite warning cuando no hay AUDIT."""
        _, collab_dir = plan_missing_audit
        warnings = detect_audit_missing_tp_check(collab_dir)
        assert len(warnings) == 1
        assert warnings[0]["rule_id"] == "TP-STRUCT-01"
        assert warnings[0]["rule_name"] == "audit-missing-tp-check"

    def test_audit_without_tp_check(self, plan_with_audit_no_tp_check: tuple):
        """Emite warning cuando AUDIT no tiene TP Check."""
        _, collab_dir = plan_with_audit_no_tp_check
        warnings = detect_audit_missing_tp_check(collab_dir)
        assert len(warnings) == 1
        assert warnings[0]["rule_name"] == "audit-missing-tp-check"

    def test_audit_with_tp_check(self, plan_with_audit_tp_check: tuple):
        """No emite warning cuando AUDIT tiene TP Check."""
        _, collab_dir = plan_with_audit_tp_check
        warnings = detect_audit_missing_tp_check(collab_dir)
        assert len(warnings) == 0


# ============================================================================
# TESTS DE VALIDADOR PRINCIPAL
# ============================================================================


class TestValidateTicketProse:
    """Tests para validate_ticket_prose."""

    def test_missing_work_plan(self, tmp_path: Path):
        """Retorna warning fatal si work_plan no existe."""
        fake_path = tmp_path / "nonexistent.md"
        collab_dir = tmp_path / "collab"
        collab_dir.mkdir()
        result = validate_ticket_prose(fake_path, collab_dir)
        assert result["warning_count"] == 1
        assert result["warnings"][0]["rule_id"] == "TP-FATAL-01"

    def test_clean_plan_no_warnings(self, tmp_path: Path, clean_plan: str):
        """Plan limpio no genera warnings."""
        collab_dir = tmp_path / "collab"
        collab_dir.mkdir()
        work_plan = collab_dir / "work_plan.md"
        work_plan.write_text(clean_plan, encoding="utf-8")
        # Crear AUDIT con TP Check
        audit = collab_dir / "AUDIT_WP-TEST.md"
        audit.write_text("# Audit\n\n## TP Check\n- TP-01: ok\n", encoding="utf-8")

        result = validate_ticket_prose(work_plan, collab_dir)
        assert result["warning_count"] == 0

    def test_defective_plan_multiple_warnings(self, tmp_path: Path, defective_plan: str):
        """Plan defectuoso genera multiples warnings."""
        collab_dir = tmp_path / "collab"
        collab_dir.mkdir()
        work_plan = collab_dir / "work_plan.md"
        work_plan.write_text(defective_plan, encoding="utf-8")

        result = validate_ticket_prose(work_plan, collab_dir)
        assert result["warning_count"] > 5
        # Verificar que hay IDs y sugerencias
        for warning in result["warnings"]:
            assert "rule_id" in warning
            assert "suggestion" in warning
            assert warning["rule_id"].startswith("TP-")


# ============================================================================
# TESTS DE FORMATO DE SALIDA
# ============================================================================


class TestFormatOutput:
    """Tests para format_output."""

    def test_json_output(self):
        """Formatea salida como JSON."""
        result: ValidationResult = {
            "warnings": [
                {
                    "rule_id": "TP-PROSE-01",
                    "rule_name": "throat-clearing",
                    "evidence": "Este ticket tiene como objetivo",
                    "suggestion": "Ve directo al grano",
                }
            ],
            "warning_count": 1,
        }
        output = format_output(result, json_output=True)
        parsed = json.loads(output)
        assert parsed["warning_count"] == 1
        assert parsed["warnings"][0]["rule_id"] == "TP-PROSE-01"

    def test_text_output_clean(self):
        """Formatea salida legible sin warnings."""
        result: ValidationResult = {"warnings": [], "warning_count": 0}
        output = format_output(result, json_output=False)
        assert "[OK]" in output
        assert "No se detectaron problemas" in output

    def test_text_output_with_warnings(self):
        """Formatea salida legible con warnings."""
        result: ValidationResult = {
            "warnings": [
                {
                    "rule_id": "TP-PROSE-01",
                    "rule_name": "throat-clearing",
                    "evidence": "test",
                    "suggestion": "fix",
                }
            ],
            "warning_count": 1,
        }
        output = format_output(result, json_output=False)
        assert "TP-PROSE-01" in output
        assert "throat-clearing" in output


# ============================================================================
# TEST DE INTEGRACION (MAIN)
# ============================================================================


class TestMainIntegration:
    """Tests de integracion para main()."""

    def test_main_exit_code_zero(self, tmp_path: Path, clean_plan: str):
        """main() siempre retorna exit code 0."""
        from validate_ticket_prose import main

        collab_dir = tmp_path / "collab"
        collab_dir.mkdir()
        work_plan = collab_dir / "work_plan.md"
        work_plan.write_text(clean_plan, encoding="utf-8")
        audit = collab_dir / "AUDIT_WP-TEST.md"
        audit.write_text("# Audit\n\n## TP Check\n- TP-01: ok\n", encoding="utf-8")

        with patch.object(
            sys,
            "argv",
            [
                "validate_ticket_prose.py",
                "--work-plan",
                str(work_plan),
                "--collab-dir",
                str(collab_dir),
            ],
        ):
            exit_code = main()
            assert exit_code == 0

    def test_main_json_output(self, tmp_path: Path, defective_plan: str):
        """main() con --json produce JSON valido."""
        from validate_ticket_prose import main

        collab_dir = tmp_path / "collab"
        collab_dir.mkdir()
        work_plan = collab_dir / "work_plan.md"
        work_plan.write_text(defective_plan, encoding="utf-8")

        with patch.object(
            sys,
            "argv",
            [
                "validate_ticket_prose.py",
                "--work-plan",
                str(work_plan),
                "--collab-dir",
                str(collab_dir),
                "--json",
            ],
        ):
            # Capturar stdout
            from io import StringIO

            captured = StringIO()
            with patch.object(sys, "stdout", captured):
                exit_code = main()

            output = captured.getvalue()
            parsed = json.loads(output)
            assert "warnings" in parsed
            assert "warning_count" in parsed
            assert exit_code == 0
