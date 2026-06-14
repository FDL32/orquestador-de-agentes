# UPSTREAM_LEARNINGS.md

## Pendientes de revision

### 2026-06-12 | origen: contrato | estado: generalizable | ttl_wps: N/A

- learning: "El bootstrap en un destino real debe ejecutar la triada link + context map + validate (destination_bootstrap.md pasos 1-5); cualquier friccion observada durante ese arranque se trata como senal de integracion del motor y se convierte en fix o ticket del motor, no se normaliza."
- evidencia: commits de7c8d3 (bug de parsing del rol detectado en el bootstrap de Crear_Texto_LLM) y b9c0bc0 (paso validate canonico + resumen HANDOFF_BLOCKED con estado de resolucion).
- razon: el arranque en destino real ejercita el contrato motor-link de extremo a extremo; cada friccion es un test de integracion que el motor no tiene en CI.


### 2026-06-12 | origen: proceso | estado: generalizable | ttl_wps: N/A
- learning: "Los cierres por chat y por bus deben converger en un unico pipeline canonico. Un prompt que reconstruye el cierre mediante scripts sueltos crea rutas divergentes y puede omitir rotacion, archivado o consolidacion."
- evidencia: "commit `961f210`; `prompts/session_close_chat.md`; `scripts/session_closeout.py`; tests de `tests/test_session_closeout.py`."
- razon: "La rotacion de `review_queue.md` no se ejecutaba en cierres por chat porque el wrapper no invocaba `--session-close`. Centralizar la orquestacion elimina esa divergencia."
- propuesta de aplicacion en herramienta:
  - `prompts/session_close_chat.md`
  - `skills/project-finalize/SKILL.md`
  - `scripts/session_closeout.py`
- decision del usuario: aceptado

### 2026-06-12 | origen: proceso | estado: generalizable | ttl_wps: N/A
- learning: "Un learning no puede promoverse como generalizable sin un ancla de evidencia verificable. Debe incluir commit, test, archivo:linea o comando con resultado; sin ella se clasifica como dudoso o se descarta."
- evidencia: "commit `961f210`; `skills/man-session-closeout/SKILL.md` version 1.1.0."
- razon: "La evidencia permite validar la regla en sesiones futuras sin reconstruir el relato original y reduce la promocion de recuerdos ambiguos a contrato del motor."
- propuesta de aplicacion en herramienta:
  - `skills/man-session-closeout/SKILL.md`
  - `skills/man-session-closeout/references/upstream-learnings-format.md`
- decision del usuario: aceptado

### 2026-06-10 | origen: WT-2026-248a | estado: generalizable | ttl_wps: N/A
- learning: "Toda lógica que parsea ticket IDs debe usar `extract_all_ticket_ids()` de `bus/ticket_id.py`; los regex inline como `(?:WT|WP)-\d+(?:-\d+)*` truncan sufijos alfanuméricos (248a -> 248) y degradan en rutas de cierre."
- razon: "Cualquier código nuevo que valide IDs puede heredar el bug. Ya ocurrió en `--manager-approve`. El parser canónico debe ser el único punto de entrada."
- propuesta de aplicacion en herramienta:
  - `prompts/launch_builder.md`
  - `prompts/review_manager.md`
  - `skills/bui-implement-from-plan/references/code-rules.md`
- decision del usuario: aceptado

### 2026-06-10 | origen: WT-2026-248a | estado: generalizable | ttl_wps: N/A
- learning: "En PowerShell 5.1, `Set-Content`/`Out-File` con `-Encoding UTF8` añade BOM (EF BB BF) silenciosamente a archivos trackeados sin BOM. El idiom seguro para restauración byte-exacta es `[IO.File]::WriteAllBytes($path, $bytes)`."
- razon: "Aplica a cualquier proyecto con launcher PS5.1 y archivos versionados restaurados en runtime. El drift no siempre se detecta hasta comparar bytes."
- propuesta de aplicacion en herramienta:
  - `scripts/launch_agent_terminals.ps1`
- decision del usuario: aceptado

### 2026-06-10 | origen: WT-2026-248a | estado: generalizable | ttl_wps: N/A
- learning: "Un ticket puede estar funcionalmente cerrado y aun así dejar deuda residual de infraestructura o arquitectura. Separar fix funcional de follow-up estructural evita reabrir tickets correctos y hace visible la deuda sin ocultar el progreso real."
- razon: "Es un aprendizaje de proceso reusable. Se observó claramente en 248a: el bug quedó resuelto aunque persista fragilidad estructural alrededor de `.opencode/opencode.json`."
- propuesta de aplicacion en herramienta:
  - `skills/project-finalize/SKILL.md`
  - `skills/man-session-closeout/SKILL.md`
- decision del usuario: aceptado

### 2026-06-10 | origen: WT-2026-248a | estado: generalizable | ttl_wps: N/A
- learning: "Cuando un prompt de chat y una skill del bus sirven el mismo proceso, la skill es la fuente canónica (workflow, constraints, references) y el prompt es un wrapper contextual que la referencia explícitamente. Mantener ambos sin relación explícita crea drift estructural con el tiempo."
- razon: "La sesión mostró drift real entre `prompts/` y `skills/` en Builder/Manager. La separación de responsabilidades debe quedar explícita."
- propuesta de aplicacion en herramienta:
  - `prompts/review_manager.md`
  - `prompts/launch_builder.md`
  - `skills/man-review-implementation/SKILL.md`
  - `skills/bui-implement-from-plan/SKILL.md`
- decision del usuario: aceptado

## Confirmados

### 2026-06-14 | origen: proceso | estado: generalizable
- learning: "Antes de implementar un ticket que describe un estado pasado del sistema, reproduce su premisa en modo read-only y re-scopea si es falsa. La solucion correcta puede estar en un hazard distinto del relato original."
- evidencia: "WOT-2026-003d; `python scripts/install_agent_system.py --sync --dry-run`; commit `ff05b8d`; review independiente de 003d."
- razon: "En esta sesion, el dry-run desmintio la premisa historica de 003d y redirigio el trabajo al riesgo real: prune de rutas trackeadas del destino. Es un juicio reusable de seguridad y alcance."
- propuesta de aplicacion en herramienta:
  - `prompts/orchestrator_pipeline.md`
  - `prompts/audit_pipeline.md`
  - `prompts/audit_post_change_system_health.md`
- decision del usuario: aceptado

### 2026-06-14 | origen: contrato | estado: generalizable
- learning: "En topologia host-extends, retirar copias motor-provides exige auditar primero resolvers vivos, hooks y CI del destino. El contrato documental no basta para declarar segura la limpieza."
- evidencia: "WOT-2026-003b; WOT-2026-003c; WOT-2026-005b; WOT-2026-005c; `prompts/destination_bootstrap.md`; `prompts/audit_post_change_system_health.md`."
- razon: "La sesion mostro que un destino puede seguir apuntando a superficies locales ya retiradas aunque el modelo host-extends este bien documentado. Esto sigue siendo juicio operativo reusable."
- propuesta de aplicacion en herramienta:
  - `prompts/destination_bootstrap.md`
  - `skills/orchestrate-pipeline/references/destination-preflight.md`
  - `prompts/audit_post_change_system_health.md`
- decision del usuario: aceptado

### 2026-06-14 | origen: contrato | estado: generalizable
- learning: "Los gates de cierre y de alcance deben respetar `delivery_authority`. Un ticket code o mixed del repo_destino no puede exigir evidencia productiva en repo_motor para cerrar de forma canonica."
- evidencia: "Bloqueo estructural detectado en la cadena WOT-2026-003x; uso de `delivery_authority` en `work_plan.md`; cierre de tickets destino-authority sin commit productivo en motor."
- razon: "Es un contrato estructural del sistema multi-repo: el repositorio de autoridad del deliverable determina donde debe vivir la evidencia canonicamente exigible."
- propuesta de aplicacion en herramienta:
  - `.agent/agent_controller.py`
  - `bus/motor_checkpoint.py`
  - `prompts/orchestrator_pipeline.md`
- decision del usuario: aceptado

### 2026-06-14 | origen: bug-fix | estado: generalizable
- learning: "Un hook de seguridad que no puede resolver su guard debe fallar cerrado. Si sale con `exit 0` por dependencia ausente, la barrera es falsa y el sistema queda fail-open."
- evidencia: "WOT-2026-003b; WOT-2026-003c; `scripts/check_claude_settings_portability.py`; `.agent/hooks/claude_guard_entry.py`; tests de 003c."
- razon: "Este principio ya quedo endurecido por barrera; la memoria debe conservar el por que y donde vive, no tratarlo como opinion abierta."
- propuesta de aplicacion en herramienta:
  - `scripts/check_claude_settings_portability.py`
  - `.agent/hooks/claude_guard_entry.py`
  - `prompts/audit_post_change_system_health.md`
- decision del usuario: aceptado

### 2026-06-14 | origen: bug-fix | estado: generalizable
- learning: "Un test o gate verde sin assert real ni parsing correcto no es evidencia. Los false-greens deben tratarse como deuda critica y cerrarse con barreras explicitas."
- evidencia: "WOT-2026-006a; `pytest.ini` con `error::PytestReturnNotNoneWarning`; WOT-2026-006b; `scripts/check_encoding_guard.py` con chequeo de rutas explicitas."
- razon: "Este principio tambien quedo endurecido por barreras. La memoria conserva la regla y el puntero a la barrera para evitar futuras re-derivaciones ingenuas."
- propuesta de aplicacion en herramienta:
  - `pytest.ini`
  - `scripts/check_encoding_guard.py`
  - `prompts/audit_agent_output.md`
- decision del usuario: aceptado

### 2026-06-14 | origen: contrato | estado: generalizable
- learning: "En CI o clone fresco, ausencia del bus runtime debe clasificarse como no verificable, no como violacion dura. Error solo cuando el bus del ticket esta presente y falta el evento requerido."
- evidencia: "WOT-2026-003a; CHANGELOG v9.17.1; `tests/test_completion_integration.py`; prompts de auditoria completa y post-change actualizados en 005c y 005d."
- razon: "La sesion endurecio el comportamiento del validador y ademas lo llevo a la capa de auditoria. La memoria debe conservar el contrato y el contexto de uso."
- propuesta de aplicacion en herramienta:
  - `.agent/agent_controller.py`
  - `tests/test_completion_integration.py`
  - `prompts/audit_complete_motor_destination.md`
- decision del usuario: aceptado

## Archivados

_Vacío._
