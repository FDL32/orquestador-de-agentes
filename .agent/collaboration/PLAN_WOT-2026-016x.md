# PLAN - WOT-2026-016x

**Ticket:** WOT-2026-016x - run_quality_gates no imprime el WARN de "veredicto no
concluyente" de pytest cuando el stamp es inconclusive.
**Estado:** APPROVED
**delivery_authority:** repo_motor | **deliverable_type:** code

Este documento es la estrategia tecnica breve del ticket; el contrato completo
(diagnostico detallado, criterios, gates, STOP conditions) vive en work_plan.md.
Si algo difiere entre ambos, work_plan.md manda.

## Resumen del problema

.agent/agent_controller.py, funcion run_quality_gates (linea 2089-2154):
cuando _read_pytest_safe_verdict() devuelve verdict "inconclusive" (stamp
stale o ausente), la funcion anade un WARN a results["warnings"] (linea
2142-2146) pero NUNCA lo imprime: solo imprime el header (linea 2091) y el
status final [PASSED]/[FAILED] (linea 2152-2153). El caller relevante,
_check_quality_gates (linea 2227-2255), solo evalua gate_result["passed"]
(que sigue True por diseno, correctamente, cuando el veredicto es
inconclusive) y descarta summary/warnings. El operador nunca ve el WARN. La
severidad es redundante-segura: --pre-handoff exige stamp verde por separado,
asi que no hay riesgo de falso-verde de cierre, solo un gap de visibilidad
diagnostica.

## Estrategia (cambio minimo)

1. Confirmar en codigo (ya hecho en Fase 0 del Manager) las 3 lineas exactas
   del diagnostico: la construccion de results (linea 2092), el append del
   WARN (linea 2142-2146), y el status final sin imprimir warnings/summary
   (linea 2152-2153).
2. Anadir, dentro de run_quality_gates, inmediatamente antes de la linea
   status = "[PASSED]" if results["passed"] else "[FAILED]", un bucle que
   imprima cada item de results["warnings"] con el mismo formato de
   indentacion que usa el resto de la funcion (tres espacios de margen).
3. Crear un test nuevo en tests/test_agent_controller.py, dentro de
   class TestRunQualityGates, usando el fixture nativo capsys de pytest, que
   mockea _read_pytest_safe_verdict con verdict inconclusive y verifica que
   el WARN aparece en capsys.readouterr().out, y que result["passed"] sigue
   True.
4. Ejercer mutation: revertir el bucle de impresion anadido, confirmar que el
   test nuevo falla; restaurar, confirmar que pasa. Registrar ambos
   resultados literales en execution_log.md.
5. Correr gates: pytest focal de tests/test_agent_controller.py (incluyendo
   no-regresion explicita de los 4 tests existentes de TestRunQualityGates y
   los 2 de TestAutoRejectQualityGates), ruff check sobre los 2 archivos
   tocados, y la suite canonica run_pytest_safe.py --level all.
6. Commitear en repo_motor con WOT-2026-016x en el mensaje, mark-ready,
   esperar review del Manager (validate es Manager gate).

## Archivos tocados

- .agent/agent_controller.py (funcion run_quality_gates unicamente)
- tests/test_agent_controller.py (un test nuevo dentro de TestRunQualityGates)

## Criterios de cierre

Identicos a work_plan.md seccion "Criterios de Aceptacion (binarios)" items
1-6. No duplicados aqui para evitar deriva; ver work_plan.md como fuente
unica de los comandos exactos.
