# Work Plan - WP-2026-162

## Metadata
- **ID:** WP-2026-162
- **Estado:** APPROVED
- **deliverable_type:** code
- **Titulo:** Ticket Quality & Improvement Loop - fase automatizada
- **Asignado a:** Builder

## Objetivo
Implementar el validador mecanico de prosa de ticket y exponer sus warnings en `--validate` sin romper el flujo existente. Esta fase convierte en codigo las reglas de calidad de ticket definidas en WP-2026-161.

## Contexto
- La fase documental ya existe: catalogo TP, checklist de calidad y `## TP Check` en la skill del Manager.
- Ahora falta automatizar la deteccion de defectos obvios de redaccion para que `--validate` avise antes del handoff.
- La automatizacion debe ser conservadora: warnings si hay problemas, pero no bloqueo del flujo por defectos de prosa.
- Las mejoras retroactivas mas pesadas (metricas, precision/recall, injection de observaciones a prompts) quedan fuera de este ticket.

## Decision Arquitectonica
- `scripts/validate_ticket_prose.py` sera un validador standalone que lea `work_plan.md` y emita warnings de calidad.
- `_handle_validate()` en `.agent/agent_controller.py` consumira esos warnings y los agregara al JSON de salida bajo `warnings.ticket_prose`.
- `--validate` seguira devolviendo exit code 0 cuando solo existan warnings; solo fallara con errores reales.
- La cobertura de pruebas debe incluir el validador aislado y la integracion en el controlador.

## Non-goals
- No crear `plan_accuracy_check.py` en este ticket.
- No calcular metricas F1, precision o recall.
- No inyectar observaciones en prompts de forma programatica.
- No convertir los warnings de prosa en errores bloqueantes.
- No reescribir el catalogo TP ni la checklist documental de WP-2026-161.

## Fases

### Fase 1: validador de prosa de ticket
- **Tipo:** TAREA AGENTE
- **Archivos:** `scripts/validate_ticket_prose.py`, `tests/test_validate_ticket_prose.py`
- **Accion:** Crear
- **Descripcion:** Implementar un validador determinista que lea `work_plan.md` (o un path alternativo), detecte los patrones de prosa y los TP-P estructurales obligatorios, y devuelva warnings con regla, evidencia y sugerencia. Las detecciones obligatorias son: throat-clearing, declarativo vago, pasivo impreciso, extremos lazy, objetivo difuso, non-goals ausentes, criterio no verificable, Files Likely Touched imprecisos, ticket sobredimensionado, decision arquitectonica ausente y dependencia fantasma. Adicionalmente, el validador debe comprobar que existe un `AUDIT_WP-*.md` en `.agent/collaboration/` y que contiene una seccion `## TP Check`; si no la tiene, emite un warning estructural `audit-missing-tp-check`.
- **Riesgo:** Bajo
- **Criterio de Aceptacion:** Cada regla de deteccion tiene al menos un test directo que la dispara y otro que no la dispara; un fixture defectuoso genera warnings con IDs y sugerencias; un fixture limpio no genera warnings; un AUDIT sin `## TP Check` genera el warning `audit-missing-tp-check`; el script sale con exit code 0 en todos los casos.
- **Si falla:** Reducir el detector a las cuatro reglas de prosa mas deterministas (throat-clearing, declarativo vago, pasivo impreciso, extremos lazy) mas la comprobacion de AUDIT estructural, que es la mas valiosa.

### Fase 2: integracion en `--validate`
- **Tipo:** TAREA AGENTE
- **Archivos:** `.agent/agent_controller.py`, `tests/test_agent_controller.py`
- **Accion:** Modificar
- **Descripcion:** Integrar el validador de prosa en `_handle_validate()` para que los warnings aparezcan en la salida JSON y en consola bajo una clave dedicada (`warnings.ticket_prose`), preservando la semantica actual: warnings no bloquean, errores si. Mantener `--force` sin cambios funcionales.
- **Riesgo:** Medio
- **Criterio de Aceptacion:** `python .agent/agent_controller.py --validate --json --force` muestra `warnings.ticket_prose` cuando el `work_plan.md` activo contiene uno o mas patrones detectables y sigue devolviendo exit code 0 si no hay errores reales.
- **Si falla:** Mantener el validador standalone y posponer la integracion para un ticket posterior.

### Fase 3: cobertura end-to-end
- **Tipo:** TAREA AGENTE
- **Archivos:** `tests/test_validate_ticket_prose.py`, `tests/test_agent_controller.py`
- **Accion:** Añadir
- **Descripcion:** Completar la cobertura con un test para un plan defectuoso que produzca warnings y un test para un plan limpio que no produzca warnings. La cobertura debe demostrar que los warnings no bloquean `mark-ready`.
- **Riesgo:** Medio
- **Criterio de Aceptacion:** Cada funcion de deteccion de Fase 1 aparece invocada directamente en al menos un test (no solo a traves del fixture general); existe un test para plan limpio sin warnings y uno para AUDIT sin `## TP Check` que dispara `audit-missing-tp-check`.
- **Si falla:** Limitar la cobertura a nivel de unidad y dejar el smoke end-to-end para un WP posterior.

## Files Likely Touched
- `scripts/validate_ticket_prose.py`
- `tests/test_validate_ticket_prose.py`
- `.agent/agent_controller.py`
- `tests/test_agent_controller.py`
- `.agent/collaboration/work_plan.md`
- `.agent/collaboration/execution_log.md`

## Calidad
- `python scripts/validate_ticket_prose.py`
- `python .agent/agent_controller.py --validate --json --force`
- `python -m pytest tests/test_validate_ticket_prose.py tests/test_agent_controller.py -q`

## Criterios de aceptacion
- El validador standalone existe y reporta warnings utiles para planes defectuosos.
- `--validate` incorpora warnings de ticket prose sin cambiar el exit code por warnings solos.
- La cobertura automatizada valida tanto un plan limpio como uno defectuoso.
- La validacion canonica sigue pasando.
