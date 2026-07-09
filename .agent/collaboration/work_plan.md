# Plan de Trabajo: barrido transversal Goose/Claw (artefactos vivos + docs nombradas)

## Metadata
- **ID:** WOT-2026-021l
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Creado:** 2026-07-10
- **delivery_authority:** repo_motor
- **Prioridad:** MEDIA
- **Asignado a:** Builder

## Objetivo
Barrido transversal final de Goose/Claw en el motor tras cerrar 020n y 021d:
retirar los ARTEFACTOS VIVOS restantes (fichero `.goosehints`, flag `--goose`,
entrada en CRITICAL_PATHS, `.pyc` huerfanos, entrada en cleanup_legacy, ignore de
runtime en .gitignore) + las lineas de doc que el handoff nombro
(`.claude/rules/02` y `03`). Se PRESERVA la historia deliberada de la
deprecacion (decision del usuario 2026-07-10).

## Contexto
El mapeo Goose (workflow 3 exploradores) revelo 3 sistemas independientes; 021l
es el barrido transversal de lo que 020n (orquestador.py) y 021d (refactor_kit)
no cubren. DEC-021D-001 excluye explicitamente que 021l toque
`agent_system/refactor_kit/` (dominio de 021d). Frontera limpia.

## Decision de alcance (usuario 2026-07-10): "Live + named docs only"
- RETIRAR: artefactos vivos + `.claude/rules/02-03`.
- PRESERVAR: registros historicos deliberados (AGENTS.md, llms-full.txt,
  tests/integration/RETIRED_TESTS.md, docs/test_performance/*, docs/skills_taxonomy/*,
  MANIFEST.*, CHANGELOG). Documentan la deprecacion WT-2026-254a a proposito;
  borrarlos borraria el rastro de auditoria.

## Configuracion Privada Requerida
Ninguna.

## Alcance EXACTO (verificado in-vivo 2026-07-10)

### RETIRAR (artefactos vivos)
1. `.goosehints` — fichero tracked: `git rm`. Referenciado SOLO por
   upgrade_agent_system.py:50 (verificado; ningun test lo referencia).
2. `scripts/upgrade_agent_system.py:50` — entrada `".goosehints"` en CRITICAL_PATHS.
   test_upgrade.py itera y usa `len(CRITICAL_PATHS)` dinamicamente (no hardcode)
   -> quitar 1 entrada mantiene el invariante `total == len(CRITICAL_PATHS)`.
3. `scripts/discover_skills.py`: rama `elif "--goose" in sys.argv:` (l.822-827) +
   la nota del docstring sobre `--goose`/Goose/Claw (l.8-11). Ningun test ejerce
   el flag (verificado). El resto del CLI (--json, default) intacto.
4. `scripts/cleanup_legacy.py:27` — entrada `"test_goose_realworld.py"` en
   OLD_SCRIPT_NAMES. test_cleanup_legacy.py no la asserta (verificado).
5. 2 `.pyc` huerfanos (UNTRACKED, borrar de disco):
   `skills/refactor-manager/__pycache__/goose_integration.cpython-310.pyc` +
   `tests/__pycache__/test_goose_native_skill.cpython-310-pytest-9.0.3.pyc`.
6. `.gitignore:47-48` — comentario + linea `.agent/runtime/goose/` (ignore del
   runtime del CLI Goose retirado).
7. `.claude/rules/02-multi-agent-system.md` (l.8,16,19-20) y
   `.claude/rules/03-skills-discovery.md` (l.20,28): lineas nombradas por el
   handoff. Reescribir para reflejar el estado actual (Claude Code backend), sin
   inventar; conservar el marcador `[DEPRECATED - WT-2026-254a]` como historia si
   aporta, pero sin describir goose.exe/claw.exe como piezas activas.

### PRESERVAR (no tocar)
- AGENTS.md, llms-full.txt (avisos de deprecacion deliberados).
- tests/integration/RETIRED_TESTS.md (registro de retirada).
- docs/test_performance/*, docs/skills_taxonomy/* (notas de backlog historicas).
- MANIFEST.distribute, MANIFEST.workspace (comentarios de ejemplo).
- CHANGELOG.md, .agent/planning/decisions.md.
- `skills/repo-compare/*` y `skills/refactor-manager/SKILL.md` (avisos historicos
  en prosa; no artefacto vivo).

## Definition of Done (DoD)
- (a) `.goosehints` retirado del repo (git rm); `git ls-files | grep goosehints` = 0.
- (b) `git grep -n "goosehints\|--goose" -- scripts/` = 0.
- (c) `git grep -in "goose\|claw" -- .claude/rules/02-multi-agent-system.md
  .claude/rules/03-skills-discovery.md` = 0 (o solo marcador historico si se
  decide conservar; el DoD prefiere 0 en superficie activa).
- (d) 2 `.pyc` huerfanos ausentes de disco.
- (e) `discover_skills.py --json` sigue funcionando; py_compile + ruff limpios.
- (f) Suite `run_pytest_safe.py --level all` exit 0 (test_upgrade con
  len(CRITICAL_PATHS)-1; test_cleanup_legacy; discover paridad trigger_map).
- (g) Historia PRESERVADA intacta (los ficheros de la lista PRESERVAR sin cambios).

## Riesgos y barreras
- Quitar `.goosehints` de CRITICAL_PATHS cambia `len(...)`; el test lo deriva
  dinamicamente -> invariante se mantiene. Barrera: DoD-f (suite).
- Borrar el fichero `.goosehints`: nada de codigo lo lee salvo la lista de backup
  (que tambien se limpia). Barrera: DoD-f.
- No sobre-redactar: PRESERVAR la historia deliberada (DoD-g).
