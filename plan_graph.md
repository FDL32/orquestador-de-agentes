# Plan Graph — Motor de orquestacion multi-agente

> Descompone `repo_charter.md` (raiz del motor) en `PLAN-*`. Vive en la RAIZ, no viaja
> (no esta en `MANIFEST.distribute`). **La independencia entre planes se verifica, no se
> declara por buena fe.** Aprobado con el charter (2026-07-15).

## PLAN-001 — Agnosticismo de la superficie distribuida
- objetivo: OBJ-001 (nada que viaja nombra esta maquina/workspace/dogfooding)
- tickets: [WOT-2026-024z, WOT-2026-025e, WOT-2026-025h, WOT-2026-025i]
- depends_on: -
- superficies_archivo: [scripts/check_distribution_agnostic.py, MANIFEST.distribute,
  prompts/**, skills/**]
- interfaces: [check_distribution_agnostic CLI, canonical_hook_command()]
- shared_dependencies: [MANIFEST.distribute (denominador de lo que viaja)]

## PLAN-002 — Medida de la flota (instrumento)
- objetivo: OBJ-002 (el censo de proteccion conoce su denominador y falla honestamente)
- tickets: [WOT-2026-024f-A]
- depends_on: -
- superficies_archivo: [scripts/check_claude_settings_portability.py,
  tests/unit/test_check_claude_settings_portability.py]
- interfaces: [--fleet CLI, fleet_check(), _discover_destinations(), check_hook_file_exists()]
- shared_dependencies: [motor_destination_link.json (schema del link),
  claude_guard_entry.canonical_hook_command() (forma canonica del hook)]

## PLAN-003 — Despliegue no destructivo + no-contaminante
- objetivo: OBJ-003 (instalar/sincronizar no pisa el destino ni le inyecta dogfooding)
- tickets: [WOT-2026-024d (cerrado), WOT-2026-024h, WOT-2026-020t]
- depends_on: -
- superficies_archivo: [scripts/install_agent_system.py, MANIFEST.workspace,
  .agent/planning/ticket_contracts.md (seed)]
- interfaces: [install/--sync/--install, copy_tree, DESTINATION_OWNED_DIRS]
- shared_dependencies: [MANIFEST.workspace (allowlist de copy_tree),
  MANIFEST.distribute (lo que se instala)]

## PLAN-004 — Endurecimiento de la flota (write-guards reales)
- objetivo: OBJ-002 (rama de proteccion, no de medida)
- tickets: [WOT-2026-024f-B]
- depends_on: [PLAN-002]  # medir antes de endurecer
- superficies_archivo: [ficheros .claude/settings.json y .agent/hooks/ de los destinos EXTERNOS]
- interfaces: [PreToolUse hook contract (payload tool_input anidado, exit 2 = bloquea)]
- shared_dependencies: [el censo de PLAN-002 (denominador de destinos a endurecer)]

## PLAN-005 - Guards de auditoria de prompts de arranque
- objetivo: OBJ-002 (el censo de proteccion conoce su denominador y falla honestamente)
- tickets: [ESPEJO-MOTOR-067n-a, ESPEJO-MOTOR-067n-b, ESPEJO-MOTOR-067n-c]
- depends_on: -
- superficies_archivo: [scripts/check_launch_prompt_paths.py,
  tests/unit/test_check_launch_prompt_paths.py]
- interfaces: [CLI del guard, resolucion del universo de prompts inspeccionados]
- shared_dependencies: [la nocion de denominador declarado que OBJ-002 exige a todo
  instrumento de auditoria de la flota]
- origen: DEC-067N-001 (decidido [B] el 2026-09-12). Se abre plan propio en vez de ampliar
  PLAN-002, que esta acotado a `check_claude_settings_portability.py`.
- NOTA (bucle L722): `OBJ-002` del charter declara `related_plans: [PLAN-002]` y NO lista ni
  a PLAN-004 (que tambien cuelga de OBJ-002, ver `:37`) ni a PLAN-005. **La omision es
  PRE-EXISTENTE, no la introduce PLAN-005.** No se corrige aqui: definir si `related_plans`
  es informativo o vinculante es semantica del charter, y decidirla por heuristica violaria
  NG-RAIZ. Requiere DEC propia que cubra las DOS omisiones.

## PLAN-006 - Instrumentacion del recolector de triage
- objetivo: OBJ-002 (el instrumento conoce su denominador y falla honestamente cuando no
  puede enumerar)
- tickets: [WOT-2026-067w]
- depends_on: -
- superficies_archivo: [scripts/backlog_reconcile.py,
  tests/unit/test_backlog_reconcile.py]
- interfaces: [schema de `findings.json` (solo ADICION de campos), canal
  `automatic_warnings`]
- shared_dependencies: [la nocion de denominador declarado que OBJ-002 exige a todo
  instrumento de auditoria; NINGUNA API compartida con 001-005]
- origen: bucle adversarial de formacion de contrato del 2026-09-16. El contrato de
  `WOT-2026-067w` se congelo citando un `PLAN-TRIAGE-INSTRUMENTATION` INEXISTENTE, y una
  lente lo cazo: sin plan, las `Forbidden Surfaces` del ticket no derivaban de ninguna
  fuente. Se abre plan propio en vez de ampliar PLAN-005, cuya superficie
  (`check_launch_prompt_paths.py`) es disjunta de esta.
- DEFECTO QUE ATACA, medido 2026-09-16 sobre poblacion completa: `backlog_reconcile.py`
  emite `grep_commits: []` en 262 de 330 tickets, y de esos 262 hay **158 falsos
  negativos** (`denominador=262 / inspeccionados=262 / hits=158 / saltados=0`). Dos
  causas distintas: (a) `_signal_commits` se invoca contra UN solo repo, el que resuelve
  `_scope_repo`, mientras el commit puede vivir en el otro; (b) cuando `_scope_repo`
  devuelve `("n/a", None)` la funcion **no se invoca en absoluto**. Es el `failure_mode`
  literal de OBJ-002: un universo vacio presentado como universo medido.
- NOTA: aplica la misma omision PRE-EXISTENTE que declara PLAN-005 -- `OBJ-002` del
  charter lista `related_plans: [PLAN-002]` y no nombra a PLAN-004, PLAN-005 ni a este.
  No se corrige aqui por el mismo motivo (semantica del charter, requiere DEC propia).

## Impact Simulation

| Plan | Superficies | Shared deps | Conflicto esperado | Mitigacion | Paralelizable |
|------|-------------|-------------|--------------------|------------|---------------|
| PLAN-001 | scripts/check_distribution_agnostic.py, prompts/**, skills/** | MANIFEST.distribute | ninguno con 002/003 (superficies disjuntas) | — | yes |
| PLAN-002 | scripts/check_claude_settings_portability.py + su test | link schema, canonical_hook_command() | comparte `canonical_hook_command()` (solo LEE) con 001 | 001 no muta esa API; 002 solo la consume | yes |
| PLAN-003 | install_agent_system.py, MANIFEST.workspace | MANIFEST.distribute (comparte con 001) | 001 y 003 leen MANIFEST.distribute; 003 no lo muta | owner unico del MANIFEST; 003 solo lee | yes |
| PLAN-004 | .claude/settings.json + hooks de destinos externos | el censo de 002 | 004 necesita el denominador que 002 produce | serializar tras 002 | after PLAN-002 |
| PLAN-005 | scripts/check_launch_prompt_paths.py + su test | ninguna de codigo; comparte con 002 y 004 la NOCION de denominador declarado (OBJ-002), no una API | ninguno de ARCHIVO con 001/002/003/004 (superficies disjuntas). SI hay conflicto SEMANTICO: 002, 004 y 005 cuelgan de OBJ-002 con censos distintos (002 destinos, 005 universo de prompts) y sus denominadores pueden DIVERGIR sin que nadie revalide | par 002+005 en Merge Regression Audit (abajo): la coherencia de denominadores se audita en merge, no se presume. Si 005 inspeccionase superficies de destinos, se serializa tras 004 por REQUIERE_HUMANO | yes |
| PLAN-006 | scripts/backlog_reconcile.py + su test | ninguna de codigo; comparte con 002, 004 y 005 la NOCION de denominador declarado (OBJ-002), no una API | ninguno de ARCHIVO con 001-005 (superficies disjuntas). Conflicto SEMANTICO de la misma clase que el par 002+005: 006 declara un denominador propio (el universo de tickets recolectados) que puede DIVERGIR de los otros censos de OBJ-002 sin que nadie revalide | par 005+006 en Merge Regression Audit: la coherencia de denominadores se audita en merge, no se presume. 006 es read-only sobre el backlog y no toca superficies de destinos, asi que no se serializa tras 004 | yes |

Reglas aplicadas:
- PLAN-004 degradado a `after PLAN-002`: endurecer sin medir es operar a ciegas (no es
  independencia probada).
- PLAN-001/002/003 `yes`: superficies de archivo disjuntas; la unica dep compartida
  (`canonical_hook_command()`, `MANIFEST.distribute`) es de solo-lectura para los consumidores,
  con owner unico -> estabilizada por contrato.

## Forbidden Surfaces por plan
- **PLAN-002 (024F-A)**: NO tocar ficheros fuera de `<motor>`; NO tocar el exit/semantica del
  modo por-fichero de `check_claude_settings_portability.py` (superficie viva de pre-commit); NO
  ejecutar el guard de ningun destino (eso es PLAN-004). NO mutar `canonical_hook_command()`.
- **PLAN-004 (024F-B)**: NO ejecutar hasta que PLAN-002 publique el denominador; toca repos
  ajenos -> REQUIERE_HUMANO.
- **PLAN-003**: NO pisar `DESTINATION_OWNED_DIRS`; NO distribuir dogfooding (NG-1).
- **PLAN-001**: NO introducir un hardcode en una entrada de `MANIFEST.distribute`.
- **PLAN-005 (067n-a/b/c)**: NO tocar `check_claude_settings_portability.py` ni su test (son
  superficie de PLAN-002); NO tocar prompts ni skills (PLAN-001); NO ejecutar guards de
  destinos ajenos (PLAN-004); NO reabrir `WOT-2026-067n`, completed con limite declarado
  *"NO re-audita la implementacion"*.

- **PLAN-006 (067w)**: NO tocar `prompts/backlog_triage.md` (consumidor, no superficie del
  plan); NO tocar `scripts/check_backlog_contract.py` (superficie viva de `WOT-2026-068k`);
  NO cruzar la frontera recolector/juez -- el script no emite `LIKELY_DONE`/
  `LIKELY_PENDING`/`NEEDS_HUMAN_VERIFY` (su docstring lo declara: *"This script NEVER
  classifies"*); NO renombrar ni retirar campos de `findings.json`, solo ANADIR; NO mutar
  `backlog.md` (el recolector es read-only sobre el backlog).

## Merge Regression Audit
Antes de integrar resultados de planes que tocaron superficies vecinas:
- **001 + 002** comparten `canonical_hook_command()`: revalidar que 002 la consume sin que 001 la
  haya cambiado de forma (si 001 cambia la forma canonica, 002 debe re-medir su clase 1).
- **002 + 003** comparten `MANIFEST.distribute`: revalidar que el denominador de agnosticismo y el
  set instalable siguen coherentes.
- **002 + 005** cuelgan ambos de OBJ-002 y cada uno declara un denominador, pero **cuentan
  COSAS DISTINTAS**: 002 enumera DESTINOS (`--fleet`), 005 enumera PROMPTS DE ARRANQUE.
  No son el mismo conjunto y no deben compararse elemento a elemento -- compararlos asi es
  el error que esta linea contenia antes (bucle L722, BA10: la mitigacion era ambigua en su
  propio texto). Lo que SI hay que revalidar es la RELACION entre ambos: que todo destino
  del censo de 002 tenga su universo de prompts RESUELTO por 005 (con `inspeccionados`
  declarado, aunque sea cero por ausencia legitima), y que 005 no inspeccione prompts de
  destinos que 002 no enumera. Un destino medido por 002 cuyo universo de prompts nadie
  resuelve es el `failure_mode` literal de OBJ-002: *"se salta en silencio y el censo sale
  verde"*. Sin este par, la independencia de 005 seria declarada y no verificada, que es lo
  que la cabecera prohibe.
- Gates sobre la union: suite `--level all` completa (no solo los tests de cada plan);
  `check_distribution_agnostic` exit 0; CI verde.
- Si la auditoria de merge falla, el paralelismo era ilegitimo: re-serializar y abrir
  `CONTRACT_GAP`.
