# PLAN - WOT-2026-016y

**Ticket:** WOT-2026-016y - Documentar la convencion de anotaciones
descriptivas en bullets de Files Likely Touched (parentesis/corchetes, o path
en linea propia).
**Estado:** APPROVED
**deliverable_type:** documentation

## Resumen (debe coincidir operativamente con work_plan.md; work_plan.md manda si difieren)

Anadir un item nuevo al checklist
skills/manager-create-work-plan/references/plan-quality-checklist.md, bajo la
seccion ## Alcance, inmediatamente despues del item de la linea 14 (el que ya
exige que Files Likely Touched enumere todos los archivos). El item nuevo fija
la convencion: las anotaciones descriptivas tras un path en un bullet FLT van
entre parentesis (...) o corchetes [...], o el path va en su propia linea; no
se escribe prosa libre tras el path en el mismo bullet.

Este ticket es puramente documental. NO se toca .agent/scope_gate.py ni
scripts/check_deliverables_exist.py. El diagnostico de Fase 0 (ver work_plan.md,
seccion Contexto) confirmo que el caso problematico que motivo este ticket
(bullet con forma "path.py es read-only, no tocar") tiene 0 ocurrencias reales
en el repo, mientras que existen anotaciones legitimas SIN parentesis que una
barrera de codigo estricta romperia. Por eso la correccion es documental, no de
codigo.

## Secuencia de fases

### Fase 1: Leer el checklist completo y confirmar el punto de insercion
- Leer skills/manager-create-work-plan/references/plan-quality-checklist.md
  completo (54 lineas).
- Confirmar que el item de la linea 14 dice exactamente:
  "Files Likely Touched enumera todos los archivos que el plan espera tocar."
- El item nuevo se inserta INMEDIATAMENTE DESPUES de esa linea, dentro de la
  misma seccion ## Alcance (antes del item de la linea 15 sobre comodines).

### Fase 2: Insertar el item de checklist
- Anadir el siguiente item (ver work_plan.md, seccion "Convencion a
  documentar" para el texto exacto):

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

- No modificar ningun otro item existente del checklist. No reordenar
  secciones. No tocar ninguna otra seccion del archivo (Secuencia,
  Verificabilidad, TP Check, Redaccion para prompts, Salida).

### Fase 3: Gates de cierre (documentation, sin pytest/ruff)
- Ejecutar: .venv/Scripts/python.exe .agent/agent_controller.py --validate --json --project-root .
  -> debe dar 0 errors / 0 warnings.
- Ejecutar: .venv/Scripts/python.exe scripts/check_encoding_guard.py skills/manager-create-work-plan/references/plan-quality-checklist.md
  -> exit code 0.
- Ejecutar: grep -n "parentesis" skills/manager-create-work-plan/references/plan-quality-checklist.md
  -> al menos 1 match.
- Confirmar con git diff --name-only (o equivalente) que NINGUN archivo de
  codigo (.agent/scope_gate.py, scripts/check_deliverables_exist.py) aparece
  en el diff del ticket.

### Fase 4: Registrar cierre en execution_log.md
- Anadir al final de execution_log.md una linea que combine artefacto + gate,
  sin la palabra "pendiente", por ejemplo:
  "Checklist actualizado en skills/manager-create-work-plan/references/plan-quality-checklist.md.
  Validate: exit code 0, 0 errors, 0 warnings."

## Non-goals (identicos a work_plan.md)

- NO modificar .agent/scope_gate.py.
- NO modificar scripts/check_deliverables_exist.py.
- NO anadir barrera de codigo ni test de regresion sobre el parser FLT.
- NO documentar la convencion en mas de un archivo .md (solo el checklist).
- NO re-litigar el diagnostico ni los fixes de WOT-2026-016s / WOT-2026-016w.

## Files Likely Touched (identico a work_plan.md)

### repo_motor
#### Builder
- skills/manager-create-work-plan/references/plan-quality-checklist.md

## Read/inspect only
- .agent/scope_gate.py (fuente del parser FLT citado en el diagnostico; no se modifica)
- scripts/check_deliverables_exist.py (fuente del parser FLT citado en el diagnostico; no se modifica)
- prompts/orchestrator_pipeline.md (referencia de la seccion Autoridad del FLT; no se modifica)
