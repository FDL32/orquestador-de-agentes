# UPSTREAM_LEARNINGS.md

## Pendientes de revision

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

_Vacío. Los ítems pasan directamente de Pendientes a motor cuando se implemente la herramienta._

## Archivados

_Vacío._
