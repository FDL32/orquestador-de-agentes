# PLAN - WOT-2026-019b

Ticket: WOT-2026-019b - Fuga PII en el detail de "stamp ilegible" de
_read_pytest_safe_verdict (OSError vuelca ruta absoluta con username).
Estado: APPROVED
delivery_authority: repo_motor | deliverable_type: code

Este documento es la estrategia tecnica breve del ticket; el contrato completo
(diagnostico detallado, criterios, gates, STOP conditions) vive en work_plan.md. Si
algo difiere entre ambos, work_plan.md manda.

## Resumen del problema

.agent/agent_controller.py, funcion _read_pytest_safe_verdict (lineas 2038-2039):

except (OSError, json.JSONDecodeError) as exc:
    return {"verdict": "inconclusive", "detail": f"stamp ilegible: {exc}"}

Un OSError (p. ej. al leer .agent/runtime/pytest-safe/last-run.json) embebe la ruta
absoluta del archivo en str(exc) via exc.filename, que en esta maquina cae bajo
C:\Users\<username>\... . Ese detail se propaga a run_quality_gates() y de ahi a
stdout/summary/warnings, filtrando el username local. json.JSONDecodeError NO tiene
este problema (hereda de ValueError, describe posicion del JSON, no una ruta).

La ficha original sugeria reusar "el patron 016e/_relativize_scope_path" asumiendo
que vive en agent_controller.py. Verificado que en realidad vive en
.agent/scope_gate.py (linea 539), ya importado en agent_controller.py (linea 52,
scope_gate.<funcion>(...) es el patron establecido en 14 sitios distintos del
archivo). El helper toma un path (str), no una excepcion -- hay que extraer
exc.filename en el sitio de uso y pasarlo al helper, no modificar la firma del
helper.

## Estrategia (cambio minimo)

1. Confirmar en codigo (ya hecho en Fase 0 del Orquestador/Manager) que el sintoma
   existe (OSError concatena ruta absoluta) y que json.JSONDecodeError NO lo
   comparte (no hereda de OSError).
2. Separar el except combinado en dos: except json.JSONDecodeError (sin cambios,
   str(exc) sigue siendo seguro) y except OSError (nuevo: componer detail desde
   exc.strerror + exc.errno + scope_gate._relativize_scope_path(exc.filename,
   PROJECT_ROOT) cuando exc.filename existe).
3. Anadir un test de regresion en tests/test_agent_controller.py, clase
   TestRunQualityGates, junto al test existente
   test_read_pytest_safe_verdict_partial_coverage_is_inconclusive: forzar OSError en
   la lectura del stamp (monkeypatch de Path.read_text o equivalente quirurgico) con
   exc.filename = ruta absoluta bajo PROJECT_ROOT, y verificar que detail NO
   contiene la ruta absoluta ni el username, y SI contiene <REPO_ROOT> o el
   basename.
4. Confirmar que los tests existentes de TestRunQualityGates siguen en verde tras
   el cambio (no solo el nuevo).
5. Ejercer mutation: revertir el fix (volver al except combinado), confirmar que el
   test nuevo falla; restaurar, confirmar que pasa. Registrar ambos resultados
   literales en execution_log.md.
6. Correr gates: pytest focal de TestRunQualityGates, ruff check, ruff format
   --check, suite canonica run_pytest_safe.py (level=all, stamp fresco sobre HEAD).
7. Commitear en repo_motor con WOT-2026-019b en el mensaje, mark-ready, esperar
   review del Manager (validate es Manager gate).

## Archivos tocados

- .agent/agent_controller.py (funcion _read_pytest_safe_verdict unicamente, lineas
  2036-2039)
- tests/test_agent_controller.py (1 test nuevo en TestRunQualityGates)

## Criterios de cierre

Identicos a work_plan.md seccion "Criterios de Aceptacion Global". No duplicados
aqui para evitar deriva; ver work_plan.md como fuente unica de los comandos exactos.

