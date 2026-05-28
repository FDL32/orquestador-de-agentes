# Work Plan - WP-2026-164

## Metadata
- **ID:** WP-2026-164
- **Estado:** APPROVED
- **deliverable_type:** code
- **Titulo:** Delivery Hygiene Loop - pre-push no mutating preflight
- **Asignado a:** Builder

## Objetivo
Reducir los fallos repetidos de entrega separando de forma explicita los hooks mutadores de los hooks de verificacion, excluyendo los artefactos generados que se reescriben en cada sincronizacion y dejando un preflight no mutador que valide el arbol antes del `git push`.

## Contexto
- En esta sesion ya se vieron fallos de push por hooks que mutaban archivos durante `pre-push`.
- `.agent/context/project-map.json` es un artefacto generado que no debe ser tratado como fuente editable por hooks de whitespace o formato.
- `project-finalize` ya documenta un preflight de entrega; ahora falta materializarlo en el tooling para que no dependa de la memoria del operador.
- El objetivo es que el fallo se vea antes de subir nada y no como sorpresa de GitHub Actions o del siguiente intento de push.

## Decision Arquitectonica
- Los hooks mutadores se ejecutan solo en `pre-commit`.
- `pre-push` queda para verificaciones no mutadoras y comprobaciones de entrega.
- El repo debe disponer de un chequeo de entrega que valide que el arbol queda limpio tras la pasada correctiva.
- Los artefactos generados de contexto o sincronizacion deben quedar excluidos del formateo y del fix automatico.

## Non-goals
- No crear un nuevo sistema de mejora continua de tickets.
- No tocar `man-session-closeout`.
- No cambiar el criterio de cierre canonico salvo la parte de entrega.
- No promover AP-D formales en este ticket.
- No convertir el preflight de entrega en un gate oculto que bloquee por heuristicas ambiguas.

## Fases

### Fase 1: separar mutadores y verificadores en el flujo de pre-commit
- **Tipo:** TAREA AGENTE
- **Archivos:** `.pre-commit-config.yaml`
- **Accion:** Modificar
- **Descripcion:** Reorganizar los hooks para que `end-of-file-fixer`, `mixed-line-ending`, `trailing-whitespace` y `ruff format` vivan solo en `pre-commit`, mientras que `pre-push` conserve unicamente verificaciones no mutadoras. Mantener la exclusion de `.agent/context/project-map.json` y de otros artefactos generados que no deben reescribirse en entrega.
- **Riesgo:** Medio
- **Criterio de Aceptacion:** Un `pre-push` no muta archivos; si hay que corregir formato, la correccion ocurre antes en `pre-commit`; `project-map.json` y artefactos equivalentes no vuelven a ser tocados por hooks de whitespace o formato.
- **Si falla:** Mantener `pre-push` como verificacion pura y sacar todo hook mutador de esa fase, incluso si eso obliga a simplificar temporalmente la configuracion.

### Fase 2: crear el chequeo de higiene de entrega
- **Tipo:** TAREA AGENTE
- **Archivos:** `scripts/delivery_hygiene_check.py`, `tests/test_delivery_hygiene_check.py`
- **Accion:** Crear
- **Descripcion:** Implementar un chequeo determinista que valide que el arbol queda limpio tras la pasada correctiva, detecte hooks mutadores en `pre-push`, confirme que los artefactos generados estan excluidos y devuelva un diagnostico accionable antes del `git push`.
- **Riesgo:** Medio
- **Criterio de Aceptacion:** El chequeo falla con un mensaje claro si detecta mutadores en `pre-push` o artefactos generados tocados por hooks; un arbol limpio pasa; un caso de prueba con mutacion detectada produce el diagnostico esperado.
- **Si falla:** Limitar el chequeo a detectar solo mutadores en `pre-push` y arbol sucio, dejando las exclusiones avanzadas para un ticket posterior.

### Fase 3: cobertura de entrega y comportamiento observable
- **Tipo:** TAREA AGENTE
- **Archivos:** `tests/test_delivery_hygiene_check.py`, `tests/test_supervisor.py`
- **Accion:** Anadir
- **Descripcion:** Completar la cobertura con tests para un flujo limpio de entrega, un flujo con hook mutador que obliga a corregir antes del push y un caso donde el supervisor anuncia de forma clara un estado idle cuando no hay ticket activo.
- **Riesgo:** Bajo
- **Criterio de Aceptacion:** La cobertura demuestra que el preflight detecta mutaciones antes de empujar, que el arbol limpio deja pasar la entrega y que la observabilidad del supervisor no se mezcla con el ticket activo.
- **Si falla:** Mantener la cobertura de unidad del chequeo de entrega y posponer los escenarios de integracion para un ticket posterior.

## Files Likely Touched
- `.pre-commit-config.yaml`
- `scripts/delivery_hygiene_check.py`
- `tests/test_delivery_hygiene_check.py`
- `tests/test_supervisor.py`

## Calidad
- `uv run pre-commit run --all-files --hook-stage pre-push`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `python -m pytest tests/test_delivery_hygiene_check.py tests/test_supervisor.py -q`

## Criterios de aceptacion
- Los hooks mutadores quedan fuera de `pre-push`.
- El chequeo de higiene de entrega detecta mutaciones y arbol sucio antes del push.
- Los artefactos generados relevantes quedan excluidos del formateo automatico.
- El flujo de entrega deja de depender de un segundo intento por mutaciones evitables.
