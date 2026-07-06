# Estrategia Tecnica - WOT-2026-019r

## Resumen ejecutivo

Dos fases secuenciales con gate de cobertura entre ellas. Fase 1 produce un
inventario nuevo (`docs/audit/worktree_topology_surface_inventory.md`) que
clasifica CADA artefacto de la superficie del pipeline (24 prompts, skills,
7 scripts candidatos, 3 puntos de superficie destino roles/backends) en
`OK-agnostico`/`DESFASADO`/`N/A`, sin editar nada. Fase 2 edita SOLO lo
marcado `DESFASADO`, aplicando el cambio propuesto documentado en Fase 1.

## Por que dos fases y no una

Auditar y editar en la misma pasada crea dos riesgos: (1) cobertura
incompleta -- un artefacto se salta porque el Builder ya esta "en modo
edicion" y no revisa sistematicamente los 24+skills+7 scripts; (2)
re-clasificacion optimista -- bajo presion de terminar, un artefacto que en
realidad cita el modelo viejo se marca `OK-agnostico` porque "no vale la
pena editarlo ahora". El gate 1.4 (conteo explicito antes de Fase 2) hace
la cobertura verificable de forma mecanica, no por confianza en el
Builder.

## Marcadores del modelo viejo (los 4 que Fase 1 debe buscar en cada
artefacto)

1. cwd de arranque = el checkout principal (`orquestador_de_agentes`, sin
   sufijo `_dev`).
2. `main` vive en el checkout principal (implicito o explicito).
3. `git pull --ff-only` como paso de sincronizacion/cierre.
4. Ausencia total de mencion a la worktree cuando el prompt describe un
   flujo de arranque o cierre de sesion que la topologia nueva afecta
   directamente (arranque, cierre, handoff, bootstrap).

Un artefacto es `DESFASADO` si contiene AL MENOS UNO de estos 4 marcadores
en un contexto donde afecta el comportamiento real de arranque/cierre. Un
artefacto que menciona "el repo" o "el checkout" de forma generica SIN
asumir cwd/rama especifica (p.ej. un audit prompt que solo lee archivos sin
importar cwd) es candidato a `OK-agnostico` o `N/A`, segun corresponda.

## Modelo nuevo (destino de la actualizacion en Fase 2)

- Arranque de trabajo de evolucion del motor: cwd =
  `orquestador_de_agentes_dev` (worktree que lleva `main`).
- Cierre de un ciclo de trabajo: `git fetch` + `git checkout --detach
  origin/main` en el checkout PRINCIPAL (`orquestador_de_agentes`), NO
  `git pull --ff-only` (no aplica sobre un HEAD sin rama en el principal
  detached).
- Consumo por destinos: el destino sigue leyendo el checkout principal
  detached via `motor_destination_link.json`, SIN cambios en ese mecanismo
  de consumo -- esto es lo que hace posible que Fase 2 NO tenga que tocar
  nada del lado destino salvo la documentacion que describe roles/backends.

Referencia canonica de este modelo: `QUICKSTART.md` seccion "0d. Motor dev
worktree" y `scripts/setup_dev_worktree.ps1`.

## Superficie exacta a inventariar en Fase 1

- 24 prompts en `prompts/*.md` (lista completa en `work_plan.md`, seccion
  1.1).
- Subdirectorios de `skills/` (36 medidos en vivo 2026-07-06, incl.
  `skills/_shared`).
- 7 scripts candidatos: `scripts/install_agent_system.py`,
  `scripts/destination_context.py`, `scripts/validate_authority.py`,
  `scripts/update_project_map.py`, `.agent/session_tracker.py`,
  `.agent/agent_controller.py`, `scripts/setup_dev_worktree.ps1`.
- 3 puntos de superficie destino roles/backends: (a) mecanismo de sync de
  `install_agent_system.py --sync` sobre `agents.json`/config de roles del
  destino; (b) prompts de destino que citan roles/backends
  (`orchestrator_destination_bootstrap.md`,
  `orchestrator_destination_batch.md`, y cualquier otro detectado); (c) el
  gap de configuracion-de-roles-por-destino (alimenta WOT-2026-019t, no se
  resuelve aqui).

## Politica de edicion en Fase 2

Solo se edita lo marcado `DESFASADO`. El cambio aplicado en cada artefacto
debe ser el MISMO que el inventario propuso en Fase 1 (no una redaccion
distinta improvisada durante la edicion). Si al aplicar el cambio
propuesto resulta ambiguo o insuficiente, el Builder detiene esa edicion
puntual, lo documenta en `execution_log.md` y escala al Manager -- no
improvisa una solucion distinta a la inventariada.

## Manejo de hallazgos de codigo roto

Si Fase 1 (al inspeccionar los 7 scripts) encuentra una ruta o rama
hardcodeada que esta REALMENTE ROTA (no solo un comentario desactualizado
que menciona el modelo viejo), ese hallazgo:

- se documenta en el inventario como nota aparte (no como fila DESFASADO
  de topologia documental);
- se registra como fila nueva en `backlog.md` (append, sin editar filas
  existentes) para abrir un sub-ticket futuro;
- NO se corrige dentro de este ticket 019r bajo ninguna circunstancia (ver
  Non-goals de `work_plan.md`).

## Riesgo principal y mitigacion

Riesgo: editar un prompt operativo de arranque/cierre (p.ej.
`orchestrator_session_bootstrap.md`) de forma incorrecta podria romper el
flujo real de sesiones futuras. Mitigacion: el cambio de Fase 2.1 se limita
EXCLUSIVAMENTE a reemplazar el marcador de topologia detectado en Fase 1
por el modelo nuevo ya verificado y documentado en `QUICKSTART.md` seccion
"0d"; no se reescribe la logica ni el orden de pasos del prompt mas alla
de esa sustitucion puntual. Ademas, `Fase 2.3` corre `--validate --json` y
el guard de encoding sobre cada archivo tocado antes de cerrar.

## Verificacion de cierre

Antes de handoff a review: `--validate --json` exit 0 (`errors: 0,
warnings: 0`), encoding guard verde sobre el inventario y sobre todo
archivo editado en Fase 2, y (si se toco algun `.py`) `ruff check .` exit
0. El checklist de "lector nuevo puede arrancar solo con la doc" se
documenta explicitamente en `execution_log.md` como paso manual de Fase
2.3.
