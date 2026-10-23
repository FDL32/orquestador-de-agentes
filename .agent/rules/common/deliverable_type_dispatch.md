# Dispatch por deliverable_type: quality gates y rubrica de review (capa 2 de la piramide)

> **Procedencia:** piramide pasada 2 + lote R1, HEAD base
> `8e956837`, 2026-10-19. Secciones origen (verbatim abajo):
> - `## Quality gates dispatch by deliverable_type (WP-2026-089)` -- `AGENTS.md:818-833`
> - `## Pluggable manager review rubric by deliverable_type (WP-2026-091)` -- `AGENTS.md:853-861`
> - `### Contrato operativo por tipo de ticket` -- `AGENTS.md:793-817`
> - Las lineas citadas son de esa HEAD base. Desde WOT-2026-120a (2026-10-23) la cuspide ya no
>   tiene el encabezado WP-2026-091: lo funde en `## Referencias de instalacion, review y
>   relanzamiento`, como item por ID WP (directiva + puntero aqui).
>
> Extractores por encabezado: leer este modulo; la cuspide solo conserva la directiva.

**Ownership:** este modulo conserva VERBATIM las secciones origen de `AGENTS.md` listadas en
su cabecera de procedencia. La cuspide conserva encabezado, directiva (prohibiciones,
obligaciones, comando canonico) y puntero. Este modulo es `referencia-bajo-demanda`: se
consulta al trabajar en el mecanismo, no en cada sesion. En divergencia de CONTENIDO manda
este modulo; toda modificacion de uno exige revisar el otro en el mismo commit.

## Quality gates dispatch by deliverable_type (WP-2026-089)

`builder-run-quality-gates` invoca ahora `scripts/run_gates_dispatch.py` que lee `deliverable_type` del work_plan activo y dispatchea:

- `code` / fallback → ruff + pytest-safe + pip-audit (condicional)
- `mixed` → ambos sets (code gates + deliverable existence check)
- `documentation` / `research` / `analysis` → solo deliverable existence check

**Conditional pip-audit policy (WP-2026-092)**:
Para los perfiles `code` y `mixed`, `pip-audit` se ejecutará de forma exclusiva cuando la lista `Files Likely Touched` dentro de `work_plan.md` incluya un archivo de manifiesto de dependencias (`pyproject.toml`, `uv.lock`, `requirements.txt`, etc). Si no hay cambios en la superficie de dependencias, la política emitirá un salto auditable, reduciendo latencia.

**Pre-commit Ruff Scope Guard (WP-2026-093)**:
Para evitar regresiones o cambios accidentales en `.pre-commit-config.yaml` que expandan el alcance de `ruff` y causen falsos positivos en tickets no-código (Markdown, documentación, análisis, etc.), se implementa `scripts/check_ruff_hook_scope.py`. Este script verifica que los hooks `ruff-check` y `ruff-format` permanezcan limitados estrictamente a Python (`types: [python]` o `files: \.py$`). Cualquier desviación detiene las gates de pytest inmediatamente.

El dispatcher, sus políticas y guardias son stdlib only; no añaden dependencias.

## Pluggable manager review rubric by deliverable_type (WP-2026-091)

- **Pluggable Prompts**: El Review Bridge (`bus/review_bridge.py`) lee el campo `deliverable_type` del plan de trabajo activo. En lugar de utilizar un prompt único y ciego, adapta el prompt de revisión enviado al backend OpenCode Manager:
  - `code`: Verifica la correctitud del código, cobertura de tests y estándares de estilo.
  - `mixed`: Combina la verificación técnica de código con la revisión estructural y exhaustiva de todos los entregables no-código declarados.
  - `documentation` / `research` / `analysis`: Enfoca la revisión del Manager estrictamente en la claridad, profundidad, calidad e integridad estructural de los entregables documentales correspondientes, omitiendo criterios de código irrelevantes.
- **Salida formal**: Se conserva estrictamente el contrato canónico de salida (`DECISION: APPROVE` o `DECISION: CHANGES`) para mantener la interoperabilidad total del bus de eventos y la máquina de estados.
- **Fallback**: Si `deliverable_type` no está declarado o contiene un tipo desconocido, se activa un fallback seguro y automático a la estrategia `code`.

### Contrato operativo por tipo de ticket

El `deliverable_type` no es decorativo: cambia que evidencia debe producir el
Builder y que debe auditar el Manager.

- `code`: requiere diff/commit productivo del ticket, tests/ruff aplicables y
  evidencia de gates en `execution_log.md`.
- `mixed`: requiere el contrato de `code` mas existencia verificable de los
  artefactos no-codigo declarados.
- `documentation` / `research` / `analysis`: no debe exigirse commit de codigo
  ni pytest/ruff salvo que el plan toque codigo. El cierre se basa en artefactos
  documentales declarados y una linea de evidencia en `execution_log.md` que
  combine artefacto y gate final, por ejemplo:
  `Reporte .agent/runtime/compare/<archivo>.md creado. Validate: exit code 0, 0 errors, 0 warnings.`

En tickets documentales, separa explicitamente las superficies:
- `Builder`: archivos que debe crear o modificar y que cuentan como entregables.
- `Read/inspect only`: fuentes que puede leer pero no deben contar como
  entregables ni como scope productivo.
- `Manager-only`: gates o revisiones que ejecuta el Manager y no el Builder.

Si el plan mezcla estas superficies, `check_deliverables_exist.py` puede bloquear
el handoff o validar una evidencia equivocada. El plan debe dejar claro que existe
en disco al final y que solo era contexto.
