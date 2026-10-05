# DEC-router-prompts-001: taxonomia de fases y contrato de metadatos de los prompts

**Ticket:** pendiente de admision (familia "Plan A/Plan B" del router de prompts; ID no asignado todavia).
**Fecha:** 2026-10-06. **Estado:** APROBADA por el usuario el 2026-10-06 (v2.1).
**Revision:** 2 rondas adversariales (`EXPLORATORY-prompts-router-planA`, DESIGN_REVIEW): R1 Codex (con
filesystem) + nan qwen + mistral, 3/3 CHANGES, 9 hallazgos adoptados y 6 rechazados con evidencia; R2 de
confirmacion solo Codex (decision del usuario), CHANGES con 2 precisiones incorporadas (v2.1) y no
re-revisadas. **Origen:** auditoria de prompts del 2026-10-04/05 (29/40 prompts no alcanzables desde lo que
un agente lee al arrancar).
**Correcciones de hecho del Plan B (marcadas [Plan B]):** no cambian ninguna regla; ajustan lo que la DEC
afirmaba del codigo existente.

## 1. Contexto
29/40 prompts no son alcanzables desde lo que un agente lee al arrancar. WOT-2026-022o definio la cabecera
`PROMPT-SUMMARY` (`what/when/not`), adoptada en 3/40; su test exigia un "ticket sucesor" para ampliarla.
`discover_skills.py` ya parseaba el frontmatter de los prompts, pero solo para `status` y `legacy_aliases`.
**[Plan B]** `_derive_role()` existia solo para las skills: las entradas `prompt` del catalogo no derivaban
`role` (por eso los 40 salian `shared`); el Plan B la conecta.

## 2. Decision

### D1. Fases del ciclo (`cycle_phase`)
No confundir con el `--phase` del dispatcher de ensemble (CONTRACT_AUDIT, DESIGN_REVIEW...), que es OTRO
vocabulario (ver D5). Valores, solo temporales:
| Valor | Ambito | Que pasa |
|---|---|---|
| `F0-arranque-sesion` | sesion | abrir sesion (desarrollo / diseno / destino / refactor) |
| `F1-backlog` | sesion de diseno | alta, triaje, diseno de vuelo, escalado destino->motor |
| `F2-contrato` | ticket | formar el contrato |
| `F3-auditoria-contrato` | ticket | gate pre-builder sobre el contrato |
| `F4-lanzamiento` | ticket | preparar y lanzar al builder, incluido el gate de /goal autonomo |
| `F5-implementacion` | ticket | el rol builder implementa |
| `F6-revision` | ticket | el rol manager revisa y CIERRA EL TICKET (cierre logico del ticket) |
| `F7-cierre-sesion` | sesion | cierra la SESION: memoria, auditoria de cierre, puente a la siguiente |
| `F8-meta-auditoria` | posterior | audita una ejecucion YA cerrada (ticket, batch o sesion) |
Limites: F6 cierra un TICKET; F7 cierra una SESION (que puede contener varios tickets); F8 solo actua sobre
algo ya cerrado. `cycle_phase` es un CONJUNTO (lista sin orden). NO son fases: los pasos internos del bucle
de ensemble (`challenge_fanout`, `premise_check`, `smoke`) ni los del /goal autonomo (`loop_*`).

### D2. Tipo de enrutado (`route_kind`), enum cerrado
Se llama `route_kind` y no `kind` porque el catalogo de `discover_skills.py` ya tiene un campo `kind`
(`prompt`/`skill`/`reference`/`shared`/`script-consumer`, columna de `INDEX.md`).
- `entry`: abre una fase; el agente lo abre por iniciativa propia.
- `modo`: orquesta varias fases por ticket.
- `modulo`: NO se abre por iniciativa propia; lo ordena u ofrece otro fichero.
- `mantenimiento`: fuera del ciclo.
- `externo`: lo consume otro agente/sistema; SOLO por lista de exencion (`hermes_soul.md`), sin frontmatter.

### D3. Rol (`role`), escalar
UN valor de los canonicos de AGENTS.md (`orchestrator`, `manager`, `builder`, `auditor`): el rol que POSEE el
prompt. `_derive_role()` solo acepta `str`; una lista caeria a `shared`. Un prompt sin `role` sale `shared`
en `INDEX.md`. Nunca un backend.

### D4. Contrato de metadatos (hibrido)
```
---
role: manager
cycle_phase: [F6-revision]
route_kind: entry
---
# Titulo
<!-- PROMPT-SUMMARY
what: <una linea>
when: <una linea>
not: <que NO es -> a donde ir>
-->
```
| `route_kind` | `role` | `cycle_phase` | `PROMPT-SUMMARY` |
|---|---|---|---|
| `entry` | obligatorio | obligatoria | obligatorio |
| `modo` | obligatorio | obligatoria | obligatorio |
| `modulo` | opcional (sin el, `shared`) | **PROHIBIDA** | obligatorio |
| `mantenimiento` | obligatorio | ausente | obligatorio |
| `externo` | - | - | exento (allowlist) |
**Modulos:** su relacion con las fases NO se escribe a mano (la asignacion manual tuvo 2 errores en
`_shared`); el router muestra "lo citan: <citadores>", DERIVADO de las citas en `prompts/`,
`prompts/_shared/` y `AGENTS.md`; con mas de 5 citadores, "transversal (N)". Es una PROYECCION HEURISTICA DE
NAVEGACION, no una relacion semantica garantizada. Un modulo con CERO citas es un error (T9).
**Definicion ejecutable de "cita"** (UNA funcion compartida para T9 y el generador: `module_citations`): una
aparicion literal del FICHERO del modulo con su extension -- `prompts/<nombre>.md`,
`prompts/_shared/<nombre>.md`, `_shared/<nombre>.md` o `<nombre>.md` como token (no precedido de letra,
digito, `_`, `-` ni `/`; `skills/_shared/...` no cuenta) -- en un fichero del universo DISTINTO del propio
modulo. Las menciones en prosa con la ruta CUENTAN a proposito (que ningun modulo quede huerfano;
`builder_invocation_contract` y `artifact_ownership` solo los cita `AGENTS.md`). Distinguir "ordena" de
"menciona" queda para el calculo futuro de coste por fase. Casos de frontera obligatorios: cuenta la ruta;
no cuenta la palabra suelta sin `.md`; no cuenta la auto-cita. **[Plan B]** Tampoco cuenta lo que esta dentro
de un bloque `PROMPT-SUMMARY`: su linea `not:` dice "esto NO es <fichero>", metadato de enrutado y no cita
(medido en el piloto: el `not:` de `_shared/loop_readiness.md` aparecia como citador de `ensemble_loop.md`).
**[Plan B, bucle de revision del codigo]** Precisiones medidas con sonda: (1) el nombre necesita frontera a
AMBOS lados -- `foo.x.md`, `x.md.bak` y `x.mdx` son otros ficheros y no cuentan; `x.md.` a final de frase si;
(2) el bloque `PROMPT-SUMMARY` solo se descarta si cierra dentro de su ventana de 12 lineas: uno sin cerrar no
descarta nada y no puede ocultar una cita posterior; (3) los separadores `\` se normalizan a `/` antes de
buscar, asi `skills\_shared\x.md` queda excluido igual que `skills/_shared/x.md`.
**[Plan B] Metadatos invalidos no llegan al router:** `router_metadata_errors()` valida D4, T6 y T9 de todo
fichero con `route_kind`; `--generate-index` se niega a escribir y `--check-index` falla si hay errores.
**Fin del frontmatter, sin segundo parser:** una funcion compartida devuelve tambien el desplazamiento del
cuerpo, con el MISMO corte `content.split("---", 2)` anclado a la linea 1; `parse_frontmatter()` delega en
ella sin cambiar su firma ni su salida, y el test usa esa misma funcion. **[Plan B]** Implementadas como
`_split_frontmatter()` y `read_prompt_parts()` en `discover_skills.py`.

### D5. Parametros del bucle por fase (para el router)
La columna `--phase` es el valor que se PASA AL DISPATCHER (vocabulario del scorecard), NO un valor de D1.
| `cycle_phase` | `--phase` | ¿gobierno? | `--task-type` |
|---|---|---|---|
| F1 | TRIAGE_AUDIT | no (texto libre, sin nonce) | `triage` |
| F3 | CONTRACT_AUDIT | si | `contract-audit` |
| F6 | MANAGER_REVIEW | si | `code-review`; `prose` si el entregable es documentation/research/analysis |
| F7 | CLOSE | si | `contract-audit` |
| (revisar una propuesta sin commit) | DESIGN_REVIEW | no (sin nonce, `loop_id EXPLORATORY-<tema>`) | `prompt-audit` / `exploracion` |
Las fases de gobierno se validan contra `GOVERNMENT_PHASES` con la MISMA normalizacion que el dispatcher
(minusculas, `-` -> `_`); las no-gobierno son texto libre por contrato (`prompts/ensemble_loop.md` sec. 3.4).
**Nota F6, decision PROVISIONAL del usuario (2026-10-05):** `prose` para entregables documentales; medido:
679 filas `manager_review` (sin distinguir mayusculas), 0 con `prose`: decision nueva sin historico. La
rubrica del manager por `deliverable_type` sigue en `bus/review_bridge.py`.

## 3. Criterios de aceptacion del test
Universo: `prompts/*.md` + `prompts/_shared/*.md`. El test usa las MISMAS funciones que produccion: una
mutacion solo cuenta si atraviesa ese codigo.
| # | Comprobacion | Mutacion que lo pone ROJO |
|---|---|---|
| T1 | Todo fichero adoptado tiene frontmatter valido | borrar el frontmatter de un fichero adoptado |
| T2 | `route_kind` existe y pertenece al enum | `route_kind: entrada` |
| T3 | Obligatoriedad de D4 por `route_kind` (incluida la PROHIBICION de `cycle_phase` en `modulo`) | anadir `cycle_phase` a un modulo; quitarla a un entry |
| T4 | `cycle_phase` solo con valores de D1; `role` escalar y de D3 | `cycle_phase: [F9-x]`; `role: [manager]`; `role: codex` |
| T5 | CAMBIO CONSCIENTE del contrato de 022o: `PROMPT-SUMMARY` con `what/when/not` dentro de las 12 lineas SIGUIENTES al fin del frontmatter | frontera: bloque que cierra en la linea relativa 12 -> verde; en la 13 -> rojo |
| T6 | Allowlist `externo` == {`hermes_soul.md`}; sin frontmatter de enrutado | marcar otro fichero `externo` |
| T7 | Tabla D5: cada `--task-type` en `TASK_TYPES`; cada `--phase` "gobierno" en `GOVERNMENT_PHASES` normalizada | `--task-type code_review`; marcar TRIAGE_AUDIT como gobierno |
| T8 | `--check-naming` recorre tambien `prompts/_shared/` | renombrar un `_shared` a `LoopX.md` |
| T9 | Todo `modulo` tiene >= 1 cita (definicion de D4) | borrar la unica cita de un modulo; y los 3 casos de frontera |
**Trinquete:** durante el despliegue por lotes, T1-T6 y T9 se aplican a una lista de ADOPTADOS que solo puede
crecer y que el propio test valida; sustituye conscientemente a `test_allowlist_is_bounded` de 022o. Cuando
la lista == universo, el test pasa a universal y la lista se elimina en ese mismo cambio.

## 4. Condiciones de refutacion
- Ya activadas y resueltas: la clave `kind` colisionaba con el campo `kind` del catalogo (-> `route_kind`);
  `role` en lista rompia `_derive_role` (-> escalar).
- Si aparece un consumidor que exige el H1 en la linea 1 o toma la primera linea como titulo: el frontmatter
  cae. (Censo del 2026-10-05: ninguno; el test de 022o buscaba un MARCADOR en una ventana.)
- Si las citas dejan de reflejar quien ordena leer un modulo (T9 verde pero lista enganosa): `modulo` vuelve
  a declarar fase.
- Consumidores de las claves: `role` -> `_derive_role` (intencionado); `cycle_phase` y `route_kind` -> solo
  el router. Si otra herramienta (Claude Code, Cursor, OpenCode) llegara a interpretarlas, se renombran.

## 5. Non-goals
No tocar `TASK_TYPES`, `GOVERNMENT_PHASES` ni `review_bridge`; no normalizar el `phase` del scorecard (ficha
lateral); no tocar skills (fase posterior).

## 6. Relacion con otras decisiones
DEC-008B-001 (`ROUTER.md` es proyeccion generada, no segunda fuente); DEC-008D-001 (nombres sin cambios; T8
extiende su gate a `prompts/_shared/`); WOT-2026-022o (se conserva `PROMPT-SUMMARY`; T5 cambia su ventana a
conciencia).

## Anexo (NO normativo): asignacion inicial prevista (2026-10-05)
- **entry (19):** F0 `orchestrator_session_bootstrap`, `orchestrator_session_bootstrap_design`,
  `orchestrator_destination_bootstrap`, `orchestrator_refactor_bootstrap`; [F7,F0] `session_hop`; F1
  `backlog_admit`, `backlog_triage`, `escalate_to_motor`; F2 `contract_formation_pipeline`; F3
  `audit_ticket_contract`; F4 `orchestrator_prepare_and_launch_ticket`; F6 `manager_review`; F7
  `orchestrator_session_close_full_audit`, `orchestrator_session_close_full_audit_design`,
  `orchestrator_session_close_chat`; F8 `audit_pipeline`, `audit_pipeline_codeonly`,
  `audit_autonomous_ticket_batch`, `audit_goal_completion`.
- **modo (4), [F4,F5,F6]:** `orchestrator_pipeline`, `orchestrator_pipeline_codeonly`,
  `orchestrator_autonomous_ticket_batch`, `orchestrator_destination_batch`.
- **modulo (16):** `audit_cf_repo_charter`, `audit_cf_plan_graph`, `audit_cf_ticket_contract`,
  `orchestrator_launch_builder`, `builder_invocation_contract`, `ensemble_loop`, `audit_agent_output`,
  `memory_upload` y los 8 de `prompts/_shared/`.
- **mantenimiento (8):** `audit_post_change_system_health`, `audit_git_publication`,
  `audit_complete_motor_destination`, `audit_portability_legacy_surface`, `audit_bus`, `suite_optimization`,
  `doc_optimization`, `memory_optimization`.
- **externo (1):** `hermes_soul` (`scripts/hermes_build_context_bundle.py` lo exporta entero).
- **Piloto del Plan B (6, uno por tipo):** `audit_ticket_contract`, `manager_review`, `ensemble_loop`,
  `_shared/loop_readiness`, `orchestrator_pipeline`, `doc_optimization`.
- **Lateral:** `builder_invocation_contract.md` sec. 2 exige que lo cite todo prompt que lance un Builder real;
  hoy no lo cita ninguno.
