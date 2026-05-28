# Work Plan - WP-2026-165

## Metadata
- **ID:** WP-2026-165
- **Estado:** COMPLETED
- **deliverable_type:** mixed
- **Titulo:** Delivery preflight wrapper - canonical push readiness
- **Asignado a:** Builder

## Objetivo
Convertir la rutina manual de pre-push en un comando canónico y reutilizable que permita saber, antes de `git push`, si el arbol esta realmente listo. El wrapper debe agrupar la higiene de entrega ya acordada, devolver diagnosticos accionables y evitar que el operador dependa de recordar una lista larga de comandos.

## Contexto
- En la sesion previa ya se estabilizo la higiene de entrega: `delivery_hygiene_check.py`, hooks mutadores confinados a `pre-commit` y `uv-lock` limitado a `pre-commit`.
- Aun asi, la validacion previa al push sigue estando repartida entre tres comandos manuales adicionales y eso sigue creando friccion operativa.
- El flujo de `project-finalize` ya documenta el preflight de entrega; lo que falta es una entrada unica y reusable para el dia a dia.
- El wrapper debe detectar antes del push los mismos problemas que ya vimos: hooks mutadores en `pre-push`, artefactos generados reescritos, arbol sucio y checks de calidad que fallan.
- `.agent/context/project-map.json` es un artefacto generado de runtime; puede regenerarse en bootstrap, pero no forma parte del entregable ni del flujo mutador por defecto.
- Este ticket tambien recupera el aprendizaje de planificacion TP-07 / TP-PROSE-12 para que el mismo commit deje trazabilidad completa entre catalogo, checklist y detector.
- Este ticket formaliza tambien los anti-patrones de delivery AP-D01 / AP-D02 para que Builder y Manager compartan el mismo lenguaje sobre scope safety y artefactos generados.

## Decision Arquitectonica
- El wrapper es exclusivamente de verificacion. No muta el arbol en ningun camino.
- Contrato CLI fijo: `python scripts/prepush_check.py` (verificacion, exit 0/1) y `python scripts/prepush_check.py --help`.
- No existe modo de reparacion en este WP. Si el preflight falla, el operador corre la pasada mutadora manualmente (`ruff format .` o `pre-commit run --hook-stage pre-commit`) y vuelve a llamar al wrapper.
- La secuencia de checks es: `delivery_hygiene_check.py` → `ruff check` → `ruff format --check` → `agent_controller --validate --json --force` → `git status --short`. Cada uno debe pasar para exit 0.
- `python skills/validate_all.py` se ejecuta pero es informacional: imprime el resultado y no bloquea el exit code del wrapper.
- La deteccion de higiene de entrega se reutiliza desde `scripts/delivery_hygiene_check.py`; no se reescribe esa logica.
- `pre-push` sigue siendo solo de verificacion; los mutadores se quedan en `pre-commit`.
- La documentacion del flujo de entrega debe referenciar un comando canonico unico, no una lista que el operador tenga que reconstruir a mano.
- El aprendizaje recuperado de TP-07 debe quedar documentado y probado en el mismo ticket para no perderlo otra vez por una reconciliacion del builder.

## Non-goals
- No implementar modo de reparacion automatica en este WP (queda para un ticket posterior).
- No cambiar el ciclo de cierre canonico de tickets.
- No tocar supervisor, bus o la logica de review.
- No añadir nuevos topics de mejora continua.
- No convertir el wrapper en un auto-push.
- No reabrir el problema de scope de `delivery_hygiene_check.py`.

## Fases

### Fase 1: crear el wrapper de preflight de entrega
- **Tipo:** TAREA AGENTE
- **Archivos:** `scripts/prepush_check.py`
- **Accion:** Crear
- **Descripcion:** Implementar `scripts/prepush_check.py` con CLI `python scripts/prepush_check.py` (verify-only, exit 0/1) y `--help`. Secuencia fija: (1) llama a `run_delivery_hygiene_check()` de `delivery_hygiene_check.py`; (2) `ruff check .`; (3) `ruff format --check .`; (4) `agent_controller --validate --json --force`; (5) `git status --short` — falla si hay salida. Adicionalmente ejecuta `python skills/validate_all.py` e imprime su resultado sin bloquear el exit code. El wrapper nunca muta el arbol.
- **Riesgo:** Medio
- **Criterio de Aceptacion:** `python scripts/prepush_check.py` existe, imprime estado de cada check con etiqueta OK/FAIL, devuelve exit 0 solo si los cinco checks bloqueantes pasan, y `git status --short` no muestra cambios tras su ejecucion.
- **Si falla:** Eliminar la llamada a `agent_controller --validate` y limitarla a higiene + ruff + git status.

### Fase 2: cobertura de tests para el preflight
- **Tipo:** TAREA AGENTE
- **Archivos:** `tests/test_prepush_check.py`
- **Accion:** Crear
- **Descripcion:** Tests para tres caminos: (a) camino limpio — los cinco checks pasan, exit 0, arbol sin cambios; (b) camino con arbol sucio — `git status --short` devuelve output, exit 1; (c) camino con mutador en pre-push detectado por `delivery_hygiene_check` — exit 1. Usar `monkeypatch`/`tmp_path` para aislar llamadas a subprocess y git.
- **Riesgo:** Medio
- **Criterio de Aceptacion:** Los tres caminos tienen cobertura explicita; ningun test muta el sistema de archivos real; los tres pasan con `pytest tests/test_prepush_check.py -q`.

### Fase 3: documentacion del ciclo de delivery
- **Tipo:** TAREA AGENTE
- **Archivos:** `skills/project-finalize/SKILL.md`, `PROJECT.md`, `QUICKSTART.md`, `skills/_shared/ticket-anti-patterns.md`, `skills/bui-implement-from-plan/references/code-rules.md`, `skills/man-review-implementation/references/review-checklist.md`, `skills/_shared/ap-schema.md`
- **Accion:** Modificar
- **Descripcion:** Referenciar el wrapper como comando canonico del preflight de entrega y explicar cuando usarlo, que hace si falla y que no sustituye al push remoto ni a los checks de GitHub Actions. Formalizar AP-D01 / AP-D02 en el catalogo, la regla del Builder, la checklist del Manager y la taxonomia compartida de observaciones.
- **Riesgo:** Bajo
- **Criterio de Aceptacion:** La documentacion del ciclo de delivery nombra un unico comando canonico y deja claro el orden: preflight local, correccion si hace falta, confirmacion limpia y solo entonces push. AP-D01 / AP-D02 quedan trazados en el catalogo, la regla del Builder y la checklist del Manager.
- **Si falla:** Mantener la documentacion en `project-finalize` y diferir `PROJECT.md` / `QUICKSTART.md` para un ajuste posterior.

## Files Likely Touched
- `scripts/prepush_check.py`
- `tests/test_prepush_check.py`
- `scripts/validate_ticket_prose.py`
- `tests/test_validate_ticket_prose.py`
- `skills/_shared/ticket-anti-patterns.md`
- `skills/man-create-work-plan/references/plan-quality-checklist.md`
- `skills/project-finalize/SKILL.md`
- `PROJECT.md`
- `QUICKSTART.md`
- `skills/_shared/ticket-anti-patterns.md`
- `skills/bui-implement-from-plan/references/code-rules.md`
- `skills/man-review-implementation/references/review-checklist.md`
- `skills/_shared/ap-schema.md`

## Calidad
- `python scripts/prepush_check.py --help`
- `python scripts/prepush_check.py`
- `python -m pytest tests/test_prepush_check.py -q`
- `python -m pytest tests/test_validate_ticket_prose.py -q`
- `python skills/validate_all.py`
- `python .agent/agent_controller.py --validate --json --force`

## Criterios de aceptacion
- `python scripts/prepush_check.py` existe y devuelve exit 0/1 con diagnostico legible por check.
- El wrapper no muta el arbol en ningun camino de ejecucion.
- `pytest tests/test_prepush_check.py -q` pasa cubriendo los tres caminos: limpio, arbol sucio, mutador en pre-push.
- `pytest tests/test_validate_ticket_prose.py -q` pasa cubriendo TP-07 / TP-PROSE-12.
- La documentacion del ciclo de delivery en `project-finalize/SKILL.md`, `PROJECT.md` y `QUICKSTART.md` nombra `python scripts/prepush_check.py` como el comando unico de preflight.
- El flujo de entrega queda: preflight local → correccion manual si falla → preflight de nuevo → push.
