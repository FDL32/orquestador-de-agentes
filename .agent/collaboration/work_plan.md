# Plan de Trabajo: retirada del subsistema --engine (Goose/Claw) de orquestador.py

## Metadata
- **ID:** WOT-2026-020n
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Creado:** 2026-07-10
- **delivery_authority:** repo_motor
- **Prioridad:** MEDIA
- **Asignado a:** Builder

## Objetivo
Retirar el subsistema de motores externos `--engine` (Goose/Claw) de
`scripts/orquestador.py`, ya codigo muerto (0 consumidores runtime, 0 tests que
lo ejerzan, VERIFICADO 2026-07-10 por git grep). La ruta `--skill`
(`execute_skill`) SOBREVIVE intacta: es el backend real vivo, ortogonal al motor
externo. Resultado: `orquestador.py` queda como un lanzador de skills puro.

## Contexto
El script arrastra un patron legacy `Claude Code -> orquestador.py -> goose|claw`
deprecado en WT-2026-254a. Las clases `GooseAdapter`/`ClawAdapter`, el dict
`ADAPTERS`, la rama `--engine` de `main()` y toda su cadena de helpers
(`run_supervisor`, `print_dry_run`, `build_payload`, `write_log`,
`git_changed_files`, `sanitize_context`, `read_json_file`) forman un subarbol
autocontenido que solo alcanza `main()` a traves de `--engine`. Verificado que
ningun modulo externo importa simbolos de `orquestador`.

Etiqueta N2 (handoff): **RIESGO bajo** (codigo muerto confirmado) pero **DIFF
medio** (se retira el subsistema `--engine` completo, no un residuo aislado).

## Configuracion Privada Requerida
Ninguna.

## Alcance EXACTO (target end-state verificado in-vivo 2026-07-10)

### RETIRAR (subarbol engine-only, todo alcanzable solo via --engine)
- Clases: `AdapterBase` (l.146), `GooseAdapter` (l.171), `ClawAdapter` (l.194).
- Dict: `ADAPTERS` (l.210).
- Funciones engine-only: `run_supervisor` (l.360), `print_dry_run` (l.325),
  `build_payload` (l.266), `write_log` (l.107), `git_changed_files` (l.82),
  `sanitize_context` (l.70), `read_json_file` (l.61).
- Constantes engine-only: `TIMEOUT_SECONDS`, `LOG_DIR`, `ALLOWLIST_PATH`,
  `DENYLIST_PATH`, `CREDENTIAL_PATTERN` (l.36-43).
- CLI: flag `--engine` (l.508-513), flag `--mode` (l.521-526), flag `--dry-run`
  (l.527-531); todos solo servian al motor externo.
- Validacion mutuamente-excluyente `--skill`/`--engine` (l.542-548): SIMPLIFICAR
  a exigir solo `--skill` (`if not args.skill: error`).
- Rama `else` de `main()` (l.557-570) que invoca `print_dry_run`/`run_supervisor`.
- Docstrings/`description` DEPRECATED del motor (l.3-21 del modulo, l.504-513 del
  parser).
- Imports que quedan huerfanos tras la retirada (verificar y retirar solo los
  que ningun simbolo superviviente use).

### CONSERVAR (ruta --skill, backend real vivo)
- `read_file_safe` (l.51) — usado por `main()` para `--file`.
- `discover_available_skills` (l.221) — usado por `execute_skill`.
- `execute_skill` (l.429) — la ruta viva.
- `main()` reducido a: parsear `--skill`/`--query`/`--file`, validar `--skill`
  presente, llamar `execute_skill`.

## Definition of Done (DoD)
- (a) `git grep -nE "GooseAdapter|ClawAdapter|ADAPTERS|--engine" -- scripts/` = 0
  salvo referencias historicas en `CHANGELOG.md` (permitidas).
- (b) `orquestador.py --skill /gates --query "..."` funciona (exit 0):
  `tests/test_refactoring_impact.py::test_skill_execution_unchanged` VERDE.
- (c) `python -m py_compile scripts/orquestador.py` OK y
  `ruff check scripts/` limpio (test_scripts_executable + test_code_quality).
- (d) Encoding-guard: `orquestador.py` esta en `CORE_SCOPE_REGRESSION`
  (test_encoding_integrity.py:59) -> el archivo debe quedar ASCII limpio.
- (e) Suite `run_pytest_safe.py --level all` exit 0.

## Riesgos y barreras
- El unico test que ejerce la superficie a tocar es `test_skill_execution_unchanged`
  (la ruta que CONSERVAMOS). Ningun test ejerce el motor externo -> la retirada
  no rompe tests existentes. Barrera: DoD-(b) prueba que la ruta viva sigue viva.
- Blast de imports: NULO (ningun `from scripts.orquestador import ...` en el repo).
