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

## Impact Simulation

| Plan | Superficies | Shared deps | Conflicto esperado | Mitigacion | Paralelizable |
|------|-------------|-------------|--------------------|------------|---------------|
| PLAN-001 | scripts/check_distribution_agnostic.py, prompts/**, skills/** | MANIFEST.distribute | ninguno con 002/003 (superficies disjuntas) | — | yes |
| PLAN-002 | scripts/check_claude_settings_portability.py + su test | link schema, canonical_hook_command() | comparte `canonical_hook_command()` (solo LEE) con 001 | 001 no muta esa API; 002 solo la consume | yes |
| PLAN-003 | install_agent_system.py, MANIFEST.workspace | MANIFEST.distribute (comparte con 001) | 001 y 003 leen MANIFEST.distribute; 003 no lo muta | owner unico del MANIFEST; 003 solo lee | yes |
| PLAN-004 | .claude/settings.json + hooks de destinos externos | el censo de 002 | 004 necesita el denominador que 002 produce | serializar tras 002 | after PLAN-002 |

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

## Merge Regression Audit
Antes de integrar resultados de planes que tocaron superficies vecinas:
- **001 + 002** comparten `canonical_hook_command()`: revalidar que 002 la consume sin que 001 la
  haya cambiado de forma (si 001 cambia la forma canonica, 002 debe re-medir su clase 1).
- **002 + 003** comparten `MANIFEST.distribute`: revalidar que el denominador de agnosticismo y el
  set instalable siguen coherentes.
- Gates sobre la union: suite `--level all` completa (no solo los tests de cada plan);
  `check_distribution_agnostic` exit 0; CI verde.
- Si la auditoria de merge falla, el paralelismo era ilegitimo: re-serializar y abrir
  `CONTRACT_GAP`.
