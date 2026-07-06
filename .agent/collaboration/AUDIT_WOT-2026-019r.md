# Audit - WOT-2026-019r

## Criterios que el Manager verificara en el review

### Fase 1 (auditoria + inventario)

- `docs/audit/worktree_topology_surface_inventory.md` existe.
- Contiene exactamente 24 filas de prompts (una por cada archivo de
  `prompts/*.md` listado en `work_plan.md` seccion 1.1), cada una con
  veredicto (`OK-agnostico`/`DESFASADO`/`N/A`), linea/seccion exacta, y
  cambio propuesto si `DESFASADO`.
- Clasifica el 100% de los subdirectorios de `skills/` (individualmente o
  agrupados con justificacion explicita por grupo, nunca un veredicto
  global sin desglose).
- Clasifica los 7 scripts candidatos (`scripts/install_agent_system.py`,
  `scripts/destination_context.py`, `scripts/validate_authority.py`,
  `scripts/update_project_map.py`, `.agent/session_tracker.py`,
  `.agent/agent_controller.py`, `scripts/setup_dev_worktree.ps1`) con
  veredicto+linea+cambio propuesto cada uno.
- Clasifica los 3 puntos de superficie destino roles/backends (sync de
  `install_agent_system.py`, prompts de destino que citan roles/backends,
  gap de configuracion-de-roles-por-destino) con evidencia literal
  (funcion+linea o prompt+seccion) cada uno.
- `execution_log.md` documenta el conteo de cobertura (Fase 1.4) ANTES de
  cualquier tarea de Fase 2: 24/24 prompts, N/N skills, 7/7 scripts, 3/3
  superficie destino, 0 pendientes.

### Fase 2 (actualizacion condicionada)

- Cada archivo editado en Fase 2 estaba marcado `DESFASADO` en el
  inventario de Fase 1 (verificar cruzando el diff real contra el
  inventario; ningun archivo `OK-agnostico`/`N/A` aparece en el diff).
- El cambio aplicado en cada archivo corresponde al "cambio propuesto"
  documentado en el inventario para ese artefacto (no una redaccion
  distinta improvisada).
- Si aparece algun hallazgo de ruta/rama hardcodeada rota en un script:
  existe una fila nueva (append) en `backlog.md` describiendola, y el
  diff de este ticket NO modifica esa logica de script.
- `--validate --json --force` (o sin `--force` si el arbol esta limpio)
  exit 0 con `errors: 0, warnings: 0`.
- Encoding guard verde sobre `docs/audit/worktree_topology_surface_inventory.md`
  y sobre cada archivo editado en Fase 2.
- Si el diff incluye algun `.py`: `ruff check .` exit 0. Si no incluye
  ningun `.py`, `execution_log.md` documenta explicitamente esa omision.
- `execution_log.md` documenta el checklist de "lector nuevo arranca solo
  con la doc actualizada" (Fase 2.3, punto 4).

## Evidencia esperada (comando + salida literal)

1. `.venv\Scripts\python.exe .agent\agent_controller.py --validate --json --project-root .`
   -> JSON con `errors: 0`, `warnings: 0`.
2. Diff de `docs/audit/worktree_topology_surface_inventory.md` mostrando
   las 4 secciones (prompts, skills, scripts, superficie destino) con
   conteo completo.
3. Diff de cada archivo editado en Fase 2, cruzado contra las filas
   `DESFASADO` del inventario (mismo archivo, mismo marcador citado).
4. Si aplica: diff de `backlog.md` con la fila nueva de sub-ticket para
   una ruta/rama rota encontrada.
5. Salida de `ruff check .` si el diff toco algun `.py` (o nota explicita
   de que no aplico).

## Blockers (bloquean aprobacion si no se resuelven)

- Un artefacto de la superficie medida (24 prompts, skills, 7 scripts, 3
  puntos destino) sin fila en el inventario.
- Un archivo editado en Fase 2 que el inventario NO marco `DESFASADO`.
- Un artefacto `DESFASADO` en el inventario que Fase 2 dejo sin editar sin
  justificacion documentada.
- `--validate --json` con `errors > 0` o `warnings > 0`.
- Encoding guard en rojo sobre el inventario o sobre cualquier archivo
  editado.
- Un hallazgo de ruta/rama rota corregido dentro de este ticket en vez de
  derivado a sub-ticket en `backlog.md`.
- Fase 2 iniciada sin que `execution_log.md` registre el conteo completo
  de cobertura de Fase 1.4.

## TP Check

- TP-01: verificado - las dos fases son secuenciales con gate explicito
  (1.4) entre ellas; ninguna tarea de Fase 2 puede ejecutarse antes de que
  el conteo de cobertura de Fase 1.4 este completo, y ninguna fase pide
  simultaneamente editar y no editar el mismo recurso.
- TP-02: verificado - cada criterio de aceptacion de fase cita un
  artefacto y un mecanismo de verificacion literal (conteo de filas del
  inventario, comando `--validate --json` con exit code y campos
  `errors`/`warnings`, comando `ruff check .`, diff cruzado contra el
  inventario); ninguno usa "correcto"/"observable" sin definicion.
- TP-03: verificado - `Files Likely Touched` de `work_plan.md` enumera
  los 24 prompts por nombre, los 7 scripts por ruta exacta y declara
  explicitamente que la edicion de Fase 2 se limita al subconjunto
  `DESFASADO` del inventario (no "otros archivos" ni comodines sin
  enumerar la superficie candidata completa).
- TP-04: verificado - no aparece "si procede"/"stale"/"opcionalmente" en
  el flujo critico; la unica condicionalidad (que archivos se editan en
  Fase 2) esta atada a un mecanismo objetivo y verificable (el veredicto
  `DESFASADO` del inventario de Fase 1), no a criterio discrecional del
  Builder.
- TP-05: verificado - `AUDIT_WOT-2026-019r.md` (este documento) replica
  exactamente las mismas fases, archivos candidatos y criterios que
  `work_plan.md` y `STRATEGY_WOT-2026-019r.md`: los 4 marcadores del
  modelo viejo, la superficie de 24+skills+7+3, y la politica de
  "editar solo lo DESFASADO" aparecen identicos en los tres documentos;
  los verbos de los Blockers de arriba ("sin fila", "editado sin marca",
  "dejado sin editar sin justificacion") coinciden con los verbos de las
  Fases correspondientes del plan ("clasificar", "editar
  EXCLUSIVAMENTE", "aplicar el cambio propuesto").
- TP-06: verificado - este `## TP Check` usa la forma canonica
  `TP-01`..`TP-07` sobre el PLAN, no criterios de diseno del entregable
  (esos viven arriba en "Criterios que el Manager verificara").
- TP-07: verificado - no hay clausulas "si existe"/"si aplica" decidiendo
  alcance; la unica condicionalidad de Fase 2 esta cerrada por el
  mecanismo objetivo del inventario (veredicto `DESFASADO`), no por
  interpretacion del Builder en el momento de ejecutar.

## Trampas especificas de este ticket (no genericas del catalogo TP)

- Fase 1 SIN editar: si el Builder edita cualquier prompt/skill/script
  durante Fase 1 (antes del gate 1.4), es un blocker aunque el cambio en
  si mismo sea correcto -- la secuencia F1-antes-de-F2 es el contrato, no
  una sugerencia.
- No re-clasificar como `OK-agnostico` algo que cita el modelo viejo solo
  porque editarlo parece tedioso o de bajo impacto aparente: el veredicto
  se basa unicamente en la presencia de los 4 marcadores, no en la
  prioridad percibida del artefacto.
- No expandir el ticket a "mejorar" contenido de prompts mas alla de la
  topologia (redaccion general, ejemplos nuevos, reestructuracion): eso
  esta fuera de scope y lo prohibe `Non-goals` de `work_plan.md`.
- Si Fase 1 revela una ruta/rama hardcodeada rota en un script: la
  tentacion de "ya que estoy aqui, la arreglo" esta expresamente vetada;
  debe derivarse a `backlog.md` como sub-ticket.


## Warnings residuales aceptados en validate --json (total_errors: 0)

- `TP-PROSE-02`/`TP-PROSE-04`: el validador heuristico de prosa (regex sobre
  palabras castellanas comunes) marca "optimizar" (dentro del Non-goal "No
  optimizar el contenido de los prompts...", uso correcto y exigido por el
  catalogo TP) y "algo"/"todo" (uso natural del idioma en frases como
  "clasificar como OK-agnostico algo que..." y "sobre todo archivo
  editado"). Revisados manualmente: no representan vaguedad de alcance real
  ni contradicen TP-04 del catalogo canonico.
- `TP-PROSE-09` (ticket-sobredimensionado, >10 archivos en Files Likely
  Touched): esperado y aceptado -- la ficha del backlog exige DoD binario
  "0 artefactos sin clasificar" sobre los 24 prompts nombrados
  explicitamente; dividir el inventario en 2+ tickets fragmentaria la
  auditoria de coherencia topologica que el ticket pide como una unidad.
- `bus_drift` ("No STATE_CHANGED event found"): esperado en esta etapa
  (CREATE_PLAN); el evento de bus lo emite el handoff
  (`--bootstrap-ticket`), fuera del alcance de este Manager segun la
  instruccion de la tarea (no bootstrap-ticket, no reset-turn).

Ninguno de estos 5 warnings bloquea la aprobacion: `total_errors: 0` en
`--validate --json --project-root .`.
