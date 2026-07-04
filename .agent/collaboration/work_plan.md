# Work Plan - WOT-2026-016y

## Metadata
- **ID:** WOT-2026-016y
- **Estado:** APPROVED
- **deliverable_type:** documentation
- **Titulo:** Documentar la convencion de anotaciones descriptivas en bullets de
  Files Likely Touched (parentesis/corchetes, o path en linea propia) para que
  el caso teorico de prosa-libre-tras-el-path nunca surja en la practica.
- **Asignado a:** Builder
- **delivery_authority:** repo_motor

## Objetivo

Anadir al checklist canonico de calidad de planes
(skills/manager-create-work-plan/references/plan-quality-checklist.md) una
convencion explicita de redaccion: las anotaciones descriptivas que siguen a un
path en un bullet de Files Likely Touched deben ir entre parentesis (...) o
corchetes [...], o el path debe ir en su propia linea; NO se debe escribir
prosa libre tras el path en el mismo bullet. Resultado observable: el checklist
contiene la regla, con ejemplo NO/SI, junto al item existente de FLT (linea 14).
Verificacion (comando exacto): `grep -n "parentesis" skills/manager-create-work-plan/references/plan-quality-checklist.md`
debe encontrar al menos 1 match tras el cambio (0 matches antes del cambio).

## Contexto (diagnostico de Fase 0 del Orquestador, CORREGIDO con evidencia)

WOT-2026-016y nacio de Review 2 de WOT-2026-016w: el heuristico FLT compartido
(.agent/scope_gate.py:_normalize_flt_line de WOT-2026-016s y
scripts/check_deliverables_exist.py:_resolve_flt_bullet_tokens de
WOT-2026-016w) usa .split(" ", 1)[0] para quedarse con el primer token del
bullet tras des-comillar. Review 2 planteo que un bullet con forma
"path.py es read-only, no tocar" (path PRIMERO, seguido de prosa) se trataria
como deliverable obligatorio, porque el primer token (path.py) pasa
looks_like_path y el resto de la prosa se descarta silenciosamente.

Fase 0 verifico esta premisa contra el repo real y la CORRIGIO:

1. El patron problematico (path + prosa "es/no/sigue read-only" en el MISMO
   bullet, path primero) tiene 0 ocurrencias en los work_plans
   vivos (.agent/collaboration/*.md) ni en el archivo (.agent/collaboration/_archive/*.md).
   Verificado con:
   grep -rhnE "path\.(py|md) (es|no|sigue|read-only)" .agent/collaboration/*.md .agent/collaboration/_archive/*.md
   -> 0 matches. El caso es TEORICO: Review 2 lo construyo como fixture
   adversarial, no existe en uso real archivado.
2. Las anotaciones FLT reales en el repo usan mayoritariamente parentesis
   (60+ bullets con forma "path (anotacion)", ej.
   ".agent/agent_controller.py (funcion run_quality_gates unicamente)",
   "scripts/check_closeout_reconciliation.py (nuevo, read-only)"). Existen
   tambien anotaciones legitimas SIN parentesis que ya funcionan hoy porque el
   primer token sigue siendo el path exacto: "file_info_cb.py  sha256=...",
   "runtime/project_root.py L36 (...)", "run_pytest_safe.py -> 3467 passed".
3. Una barrera de codigo que exigiera "solo parentesis" romperia esas
   anotaciones sin parentesis (falsos negativos reales en un GATE de
   deliverables) para cerrar un caso teorico con 0 ocurrencias (falso positivo
   que nunca ocurrio). Es el anti-patron que Fase 0 identifica: cambiar codigo
   para un problema que no existe en la practica, a costa de introducir un
   problema nuevo que si existiria.
4. El caso simetrico ya resuelto -- prosa PRIMERO, path despues (ej. "Notas:
   los scripts inspeccionados (foo.py) son read-only") -- ya esta protegido
   por looks_like_path (el primer token de esa prosa no parece un path) segun
   el docstring de _resolve_flt_bullet_tokens (WOT-2026-016w). WOT-2026-016s y
   WOT-2026-016w ya cerraron el problema PRACTICO (anotacion CON espacio tras un
   path real). No queda gap practico que un cambio de codigo deba cerrar.

Decision del humano (tras ver la evidencia de Fase 0): cerrar WOT-2026-016y
SIN cambio de codigo. Es documentacion pura: fijar la convencion de escritura
para que el caso teorico (path + prosa libre sin parentesis) nunca se produzca
en planes futuros, sin tocar el parser existente.

## Non-goals

- NO modificar .agent/scope_gate.py (en particular _normalize_flt_line ni
  _looks_like_path_token).
- NO modificar scripts/check_deliverables_exist.py (en particular
  _resolve_flt_bullet_tokens ni _extract_flt_paths).
- NO anadir ninguna barrera de codigo, validador nuevo ni test de regresion
  sobre el parser FLT: el diagnostico de Fase 0 confirma que el caso teorico
  tiene 0 ocurrencias reales y que una barrera estricta introduciria falsos
  negativos sobre anotaciones sin parentesis ya en uso.
- NO documentar la convencion en mas de un sitio primario: el checklist
  (plan-quality-checklist.md) es la unica fuente canonica nueva. NO
  duplicar el texto completo en prompts/orchestrator_launch_builder.md ni en
  la seccion "Autoridad del FLT" de prompts/orchestrator_pipeline.md (linea
  456) -- esa seccion trata de DONDE vive el FLT canonico (contrato vs
  backlog), no de la sintaxis de anotaciones dentro de un bullet; no es el
  sitio natural para esta convencion y anadir texto ahi violaria el principio
  de cambio minimo / un solo sitio primario.
- NO reabrir ni re-litigar la severidad o el diagnostico de WOT-2026-016s /
  WOT-2026-016w: sus fixes de codigo (.split(" ", 1)[0]) se dan por
  correctos y vigentes para el uso real observado.

## Files Likely Touched

### repo_motor

#### Builder

- skills/manager-create-work-plan/references/plan-quality-checklist.md

## Read/inspect only

- .agent/scope_gate.py (fuente del parser FLT citado en el diagnostico; no se modifica)
- scripts/check_deliverables_exist.py (fuente del parser FLT citado en el diagnostico; no se modifica)
- prompts/orchestrator_pipeline.md (referencia de la seccion Autoridad del FLT; no se modifica)

## Convencion a documentar (texto exacto a insertar)

En la seccion ## Alcance del checklist, inmediatamente despues del item
existente de la linea 14 (Files Likely Touched enumera todos los archivos que
el plan espera tocar.), anadir un nuevo item de checklist:

    - [ ] Si un bullet de Files Likely Touched lleva una anotacion descriptiva
      tras el path, esa anotacion va entre parentesis (...) o corchetes [...],
      o el path ocupa su propia linea (p.ej. bajo Read/inspect only). No se
      escribe prosa libre tras el path en el mismo bullet (evitar
      "scripts/x.py es read-only, no tocar"; usar
      "scripts/x.py (read-only, no tocar)" o mover ese path a la subseccion
      Read/inspect only). Motivo: el parser FLT (scope_gate._normalize_flt_line,
      check_deliverables_exist._resolve_flt_bullet_tokens) se queda solo con el
      primer token del bullet; una anotacion entre parentesis es inequivoca, la
      prosa libre sin parentesis es ambigua para el parser y para el lector humano.

## Tests Esperados

No aplica (deliverable_type: documentation). No hay codigo tocado; no se
anaden ni modifican tests de pytest.

## Criterios de Aceptacion (binarios)

1. skills/manager-create-work-plan/references/plan-quality-checklist.md
   contiene el nuevo item de checklist bajo ## Alcance, inmediatamente
   despues del item de la linea 14 actual, con el texto de la convencion
   (parentesis/corchetes o linea propia; ejemplo NO/SI explicito).
   Verificable con: grep -n "parentesis" skills/manager-create-work-plan/references/plan-quality-checklist.md
   debe encontrar al menos 1 match.
2. Ningun archivo de codigo (.agent/scope_gate.py,
   scripts/check_deliverables_exist.py) aparece modificado en el diff del
   ticket. Verificable con: git diff --name-only (o el diff del commit del
   ticket) NO debe listar ninguno de los dos archivos.
3. .venv/Scripts/python.exe .agent/agent_controller.py --validate --json
   --project-root . -> 0 errors / 0 warnings.
4. .venv/Scripts/python.exe scripts/check_encoding_guard.py
   skills/manager-create-work-plan/references/plan-quality-checklist.md (o el
   comando canonico equivalente de encoding guard sobre el archivo tocado) ->
   exit code 0, sin caracteres de encoding invalidos.
5. execution_log.md registra una linea final que combina artefacto + gate,
   sin la palabra "pendiente", del tipo: "Checklist actualizado en
   skills/manager-create-work-plan/references/plan-quality-checklist.md.
   Validate: exit code 0, 0 errors, 0 warnings."

## Quality Gates

- Builder ejecuta:
  - .venv/Scripts/python.exe .agent/agent_controller.py --validate --json --project-root .
  - .venv/Scripts/python.exe scripts/check_encoding_guard.py skills/manager-create-work-plan/references/plan-quality-checklist.md
  - grep -n "parentesis" skills/manager-create-work-plan/references/plan-quality-checklist.md
- Manager gate (revision de contenido, unica review -- ver justificacion
  abajo):
  - Lectura del diff completo del .md tocado.
  - .venv/Scripts/python.exe .agent/agent_controller.py --validate --json --project-root . (repetido por el Manager)

## STOP conditions

- Si el Builder toca .agent/scope_gate.py o
  scripts/check_deliverables_exist.py: DETENTE, es un Non-goal explicito;
  revertir y documentar la desviacion en execution_log.md.
- Si el Builder anade el texto de la convencion en mas de un archivo .md
  (duplicacion en 3 sitios): DETENTE, viola el principio de cambio minimo /
  un solo sitio primario de este ticket.
- Si validate --json no da 0 errors / 0 warnings tras el cambio: DETENTE, no
  reportes cierre; corrige el checklist o el formato de Metadata antes de
  continuar.

## Riesgos

- Bajo: cambio de un archivo .md de documentacion interna del propio
  sistema Manager, sin tocar codigo ejecutable ni tests. No hay superficie de
  regresion funcional.

## Decision Arquitectonica

Por que documentar en vez de anadir una barrera de codigo: la evidencia de
Fase 0 (0 ocurrencias reales del caso problematico, 60+ casos legitimos con
parentesis, y 3 casos legitimos SIN parentesis (citados arriba) que ya funcionan porque el
primer token coincide con el path) muestra que una barrera estricta
"solo parentesis" convertiria anotaciones hoy validas en falsos negativos de
un gate de deliverables -- cambiando un problema teorico por uno real. Fijar
la convencion en el checklist que el Manager ya usa para redactar y aprobar
Files Likely Touched previene el caso teorico en planes futuros sin tocar el
parser que ya funciona correctamente para el uso real observado.

## Trade-offs Considerados

| Opcion | Pros | Contras | Decision |
|--------|------|---------|----------|
| Documentar la convencion en el checklist (parentesis/corchetes o linea propia) | Cierra el caso teorico para planes futuros sin tocar codigo; cero riesgo de regresion; el Manager ya lee este checklist antes de aprobar cada plan | No previene retroactivamente planes ya redactados sin esta convencion (mitigado: 0 ocurrencias reales hoy) | Elegida |
| Anadir barrera de codigo que exija parentesis en _normalize_flt_line / _resolve_flt_bullet_tokens | Cierre automatico, no depende de que el Manager recuerde la convencion | Rompe 3+ anotaciones legitimas sin parentesis ya en uso (file_info_cb.py  sha256=..., etc.); introduce falso-negativo real para cerrar falso-positivo teorico (0 ocurrencias) | Descartada |
| No hacer nada (dejar el caso teorico sin documentar) | Cero esfuerzo | El caso teorico podria materializarse en un plan futuro sin que nadie lo prevenga explicitamente | Descartada |

## Criterios de Aceptacion Global
- [ ] El checklist contiene la convencion de anotaciones FLT (parentesis/corchetes o linea propia) junto al item de la linea 14
- [ ] Ningun archivo de codigo (scope_gate.py, check_deliverables_exist.py) aparece modificado
- [ ] validate --json 0 errors / 0 warnings
- [ ] check_encoding_guard.py limpio sobre el .md tocado
- [ ] execution_log.md registra la linea final artefacto + gate sin "pendiente"
